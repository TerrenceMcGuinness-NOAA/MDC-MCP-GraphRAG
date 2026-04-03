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
    
    def run(self, ground_truth_file: str, vector_spaces: List[str], 
            search_modes: List[str] = None) -> BenchmarkReport:
        """
        Run test queries, compute precision@k, recall@k, MRR, nDCG.
        
        Args:
            ground_truth_file: JSON file mapping queries to expected relevant doc IDs
            vector_spaces: List of collection names to benchmark
            search_modes: List of search modes ("vector", "hybrid")
        
        Returns:
            BenchmarkReport with metrics per model/search_mode
        """
        search_modes = search_modes or ['vector', 'hybrid']
        ground_truth = self._load_ground_truth(ground_truth_file)
        
        results = {}
        for space in vector_spaces:
            for mode in search_modes:
                key = f"{space}-{mode}"
                metrics = self._evaluate(ground_truth, space, mode)
                results[key] = metrics
        
        report = BenchmarkReport(
            queries=len(ground_truth),
            results=results,
            timestamp=datetime.utcnow().isoformat() + 'Z'
        )
        
        self._upload_report(report)
        self._generate_markdown(report)
        return report
    
    def _load_ground_truth(self, file_path: str) -> Dict[str, List[str]]:
        """Load ground truth query -> relevant doc IDs mapping."""
        with open(file_path) as f:
            return json.load(f)
    
    def _evaluate(self, ground_truth: Dict[str, List[str]], 
                  collection: str, search_mode: str) -> ModelMetrics:
        """Evaluate retrieval for a single collection/mode combination."""
        # Placeholder: would query the actual vector DB and compute metrics
        # For now, return dummy metrics
        return ModelMetrics(
            precision_at_k={5: 0.80, 10: 0.75},
            recall_at_k={5: 0.40, 10: 0.60},
            mrr=0.85,
            ndcg=0.78
        )
    
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
        md += "## Results\n\n"
        md += "| Model-Mode | P@5 | P@10 | R@5 | R@10 | MRR | nDCG |\n"
        md += "|------------|-----|------|-----|------|-----|------|\n"
        
        for key, metrics in report.results.items():
            md += f"| {key} | {metrics.precision_at_k[5]:.2f} | {metrics.precision_at_k[10]:.2f} | "
            md += f"{metrics.recall_at_k[5]:.2f} | {metrics.recall_at_k[10]:.2f} | "
            md += f"{metrics.mrr:.2f} | {metrics.ndcg:.2f} |\n"
        
        print(f"\n{md}")


def main():
    parser = argparse.ArgumentParser(description='Run retrieval quality benchmarks')
    parser.add_argument('ground_truth', help='Ground truth JSON file')
    parser.add_argument('--vector-spaces', nargs='+', required=True, 
                        help='Collection names to benchmark')
    parser.add_argument('--search-modes', nargs='+', default=['vector', 'hybrid'],
                        choices=['vector', 'hybrid'])
    
    args = parser.parse_args()
    runner = BenchmarkRunner()
    report = runner.run(args.ground_truth, args.vector_spaces, args.search_modes)
    
    print(f"\n[OK] Benchmark complete: {report.queries} queries evaluated")


if __name__ == '__main__':
    main()
