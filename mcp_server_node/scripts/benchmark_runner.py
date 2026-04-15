#!/usr/bin/env python3
"""
Benchmark Runner — Evaluate retrieval quality across models/dimensions/search modes

Computes precision@k, recall@k, MRR, nDCG per model/dimension/search_mode
using ground-truth query-document mappings.
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, List

import boto3
import numpy as np
from botocore.exceptions import ClientError


@dataclass
class ModelMetrics:
    precision_at_k: Dict[int, float]
    recall_at_k: Dict[int, float]
    mrr: float
    ndcg: float


@dataclass
class BenchmarkReport:
    queries: int
    results: Dict[str, ModelMetrics]
    timestamp: str


class BenchmarkRunner:
    """Evaluates retrieval quality across models/dimensions/search modes."""

    def __init__(self):
        self.s3 = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
        self.bucket = os.environ.get('BENCHMARK_REPORTS_BUCKET', 'mdc-mcp-rag-benchmark-reports')
        self._os_client = self._init_opensearch()
        self._embed_cache = {}  # model -> provider

    def _init_opensearch(self):
        from opensearchpy import OpenSearch, RequestsHttpConnection, AWSV4SignerAuth
        endpoint = os.environ.get('OPENSEARCH_ENDPOINT', '')
        region = os.environ.get('AWS_REGION', 'us-east-1')
        if not endpoint:
            print("[ERROR] OPENSEARCH_ENDPOINT required", file=sys.stderr)
            sys.exit(1)
        creds = boto3.Session().get_credentials()
        auth = AWSV4SignerAuth(creds, region, 'es')
        return OpenSearch(
            hosts=[{"host": endpoint.replace("https://", "").rstrip("/"), "port": 443}],
            http_auth=auth, use_ssl=True, verify_certs=True,
            connection_class=RequestsHttpConnection,
        )

    def _get_provider(self, model_short):
        if model_short not in self._embed_cache:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
            from embedding_registry import EmbeddingModelRegistry
            from embedding_provider import create_provider
            profile = EmbeddingModelRegistry().get_profile(model_short)
            self._embed_cache[model_short] = create_provider(profile)
        return self._embed_cache[model_short]

    def run(self, ground_truth_file: str, models: List[str],
            search_modes: List[str] = None) -> BenchmarkReport:
        search_modes = search_modes or ['vector', 'hybrid']
        gt_data = self._load_ground_truth(ground_truth_file)
        queries = gt_data.get('queries', [])

        results = {}
        latencies = {}
        for model in models:
            for mode in search_modes:
                key = f"{model}-{mode}"
                print(f"[BENCH] Evaluating {key} ({len(queries)} queries)...")
                metrics, lat = self._evaluate(queries, model, mode)
                results[key] = metrics
                latencies[key] = lat

        report = BenchmarkReport(
            queries=len(queries),
            results=results,
            timestamp=datetime.utcnow().isoformat() + 'Z'
        )
        report.latencies = latencies

        self._upload_report(report)
        self._generate_markdown(report)
        return report

    def _load_ground_truth(self, file_path: str) -> dict:
        with open(file_path) as f:
            return json.load(f)

    def _evaluate(self, queries: list, model: str, search_mode: str):
        import time
        provider = None if search_mode == 'bm25' else self._get_provider(model)
        all_p5, all_p10, all_r5, all_r10, all_mrr, all_ndcg = [], [], [], [], [], []
        query_latencies = []

        for q in queries:
            index = q['index_pattern'].replace('{model}', model)
            relevant = set(q['relevant_doc_ids'])
            text = q['query']

            t0 = time.time()
            try:
                vec = provider.embed([text])[0] if provider else []
                retrieved_ids = self._search(index, text, vec, search_mode, k=10)
            except Exception as e:
                print(f"  [WARN] Query '{text[:40]}' failed on {index}: {e}")
                retrieved_ids = []
            elapsed_ms = (time.time() - t0) * 1000
            query_latencies.append(elapsed_ms)

            all_p5.append(self._compute_precision_at_k(retrieved_ids, relevant, 5))
            all_p10.append(self._compute_precision_at_k(retrieved_ids, relevant, 10))
            all_r5.append(self._compute_recall_at_k(retrieved_ids, relevant, 5))
            all_r10.append(self._compute_recall_at_k(retrieved_ids, relevant, 10))
            all_mrr.append(self._compute_mrr(retrieved_ids, relevant))
            all_ndcg.append(self._compute_ndcg(retrieved_ids, relevant, 10))

        metrics = ModelMetrics(
            precision_at_k={5: float(np.mean(all_p5)), 10: float(np.mean(all_p10))},
            recall_at_k={5: float(np.mean(all_r5)), 10: float(np.mean(all_r10))},
            mrr=float(np.mean(all_mrr)),
            ndcg=float(np.mean(all_ndcg)),
        )
        lat = {
            "p50": float(np.percentile(query_latencies, 50)),
            "p95": float(np.percentile(query_latencies, 95)),
            "p99": float(np.percentile(query_latencies, 99)),
        } if query_latencies else {}
        return metrics, lat

    def _search(self, index: str, text: str, vector: list,
                mode: str, k: int = 10) -> List[str]:
        if mode == 'vector':
            body = {
                "size": k, "_source": False,
                "query": {"knn": {"embedding": {"vector": vector, "k": k}}},
            }
        elif mode == 'bm25':
            body = {
                "size": k, "_source": False,
                "query": {"match": {"content": {"query": text}}},
            }
        else:  # hybrid
            body = {
                "size": k, "_source": False,
                "query": {
                    "bool": {
                        "should": [
                            {"match": {"content": {"query": text, "boost": 1.0}}},
                            {"knn": {"embedding": {"vector": vector, "k": k}}},
                        ],
                        "minimum_should_match": 1,
                    }
                },
            }
        resp = self._os_client.search(index=index, body=body)
        return [h["_id"] for h in resp["hits"]["hits"]]
    
    def _compute_precision_at_k(self, retrieved: List[str], relevant: List[str], k: int) -> float:
        """Compute precision@k."""
        retrieved_k = retrieved[:k]
        relevant_retrieved = len(set(retrieved_k) & set(relevant))
        return relevant_retrieved / k if k > 0 else 0.0
    
    def _compute_recall_at_k(self, retrieved: List[str], relevant: List[str], k: int) -> float:
        """Compute recall@k."""
        retrieved_k = retrieved[:k]
        relevant_retrieved = len(set(retrieved_k) & set(relevant))
        return relevant_retrieved / len(relevant) if relevant else 0.0
    
    def _compute_mrr(self, retrieved: List[str], relevant: List[str]) -> float:
        """Compute Mean Reciprocal Rank."""
        for i, doc_id in enumerate(retrieved, 1):
            if doc_id in relevant:
                return 1.0 / i
        return 0.0
    
    def _compute_ndcg(self, retrieved: List[str], relevant: List[str], k: int = 10) -> float:
        """Compute Normalized Discounted Cumulative Gain."""
        dcg = sum((1 if retrieved[i] in relevant else 0) / np.log2(i + 2) 
                  for i in range(min(k, len(retrieved))))
        idcg = sum(1 / np.log2(i + 2) for i in range(min(k, len(relevant))))
        return dcg / idcg if idcg > 0 else 0.0
    
    def _upload_report(self, report: BenchmarkReport):
        """Upload benchmark report to S3."""
        key = f"benchmark-reports/{report.timestamp}.json"
        try:
            self.s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=json.dumps(asdict(report), indent=2),
                ContentType='application/json'
            )
            print(f"[OK] Benchmark report uploaded to s3://{self.bucket}/{key}")
        except ClientError as e:
            print(f"[WARN] Failed to upload benchmark report: {e}", file=sys.stderr)
    
    def _generate_markdown(self, report: BenchmarkReport):
        """Generate markdown comparison report."""
        md = f"# Benchmark Report\n\n**Timestamp**: {report.timestamp}  \n**Queries**: {report.queries}\n\n"
        md += "## Retrieval Quality\n\n"
        md += "| Model-Mode | P@5 | P@10 | R@5 | R@10 | MRR | nDCG |\n"
        md += "|------------|-----|------|-----|------|-----|------|\n"

        for key, metrics in report.results.items():
            md += f"| {key} | {metrics.precision_at_k[5]:.3f} | {metrics.precision_at_k[10]:.3f} | "
            md += f"{metrics.recall_at_k[5]:.3f} | {metrics.recall_at_k[10]:.3f} | "
            md += f"{metrics.mrr:.3f} | {metrics.ndcg:.3f} |\n"

        if hasattr(report, 'latencies') and report.latencies:
            md += "\n## Latency (ms)\n\n"
            md += "| Model-Mode | p50 | p95 | p99 |\n"
            md += "|------------|-----|-----|-----|\n"
            for key, lat in report.latencies.items():
                md += f"| {key} | {lat.get('p50',0):.0f} | {lat.get('p95',0):.0f} | {lat.get('p99',0):.0f} |\n"

        print(f"\n{md}")


def main():
    parser = argparse.ArgumentParser(description='Run retrieval quality benchmarks')
    parser.add_argument('ground_truth', help='Ground truth JSON file')
    parser.add_argument('--models', nargs='+', default=['mpnet768', 'titan1024'],
                        help='Model short names to benchmark')
    parser.add_argument('--search-modes', nargs='+', default=['vector', 'hybrid'],
                        choices=['vector', 'hybrid', 'bm25'])

    args = parser.parse_args()
    runner = BenchmarkRunner()
    report = runner.run(args.ground_truth, args.models, args.search_modes)

    print(f"\n[OK] Benchmark complete: {report.queries} queries evaluated")


if __name__ == '__main__':
    main()
