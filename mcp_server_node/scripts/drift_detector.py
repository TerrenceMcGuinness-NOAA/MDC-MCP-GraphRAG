#!/usr/bin/env python3
"""
Drift Detector — Detect embedding drift via re-embedding and cosine similarity

Samples documents from a collection, re-embeds them with the current model,
and compares to stored embeddings. Reports drift when similarity drops below threshold.
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Optional

import boto3
import numpy as np
from botocore.exceptions import ClientError

from embedding_registry import EmbeddingModelRegistry
from embedding_provider import create_provider


@dataclass
class StaleDoc:
    doc_id: str
    source_file: str
    reason: str  # "modified" | "deleted"


@dataclass
class DriftReport:
    collection_name: str
    sample_size: int
    mean_similarity: float
    min_similarity: float
    drifted: bool
    stale_documents: List[StaleDoc]
    timestamp: str


class DriftDetector:
    """Samples documents, re-embeds, computes cosine similarity to detect drift."""
    
    def __init__(self, sample_size: int = 100, threshold: float = 0.95):
        self.sample_size = sample_size
        self.threshold = threshold
        self.registry = EmbeddingModelRegistry()
        self.s3 = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
        self.bucket = os.environ.get('DRIFT_REPORTS_BUCKET', 'mdc-mcp-rag-drift-reports')
    
    def detect(self, collection_name: str, backend: str = 'aws') -> DriftReport:
        """Sample N docs, re-embed, compare. Returns DriftReport."""
        model_short = self._extract_model_from_collection(collection_name)
        profile = self.registry.get_profile(model_short)
        provider = create_provider(profile)
        
        docs = self._sample_documents(collection_name, backend)
        similarities = []
        
        for doc in docs:
            stored_embedding = np.array(doc['embedding'])
            fresh_embedding = np.array(provider.embed([doc['content']])[0])
            similarity = self._cosine_similarity(stored_embedding, fresh_embedding)
            similarities.append(similarity)
        
        mean_sim = np.mean(similarities)
        min_sim = np.min(similarities)
        drifted = mean_sim < self.threshold
        
        stale_docs = self.check_stale_documents(collection_name, backend)
        
        report = DriftReport(
            collection_name=collection_name,
            sample_size=len(docs),
            mean_similarity=float(mean_sim),
            min_similarity=float(min_sim),
            drifted=drifted,
            stale_documents=stale_docs,
            timestamp=datetime.utcnow().isoformat() + 'Z'
        )
        
        self._upload_report(report)
        return report
    
    def check_stale_documents(self, collection_name: str, backend: str = 'aws') -> List[StaleDoc]:
        """Find docs whose source files have been modified/deleted."""
        # Simplified: check if source files exist
        # Full implementation would compare file mtimes with doc ingestion timestamps
        return []
    
    def _extract_model_from_collection(self, collection_name: str) -> str:
        """Extract model short name from collection name."""
        for profile_name in self.registry.list_profiles():
            if collection_name.endswith(f'-{profile_name}'):
                return profile_name
        return 'mpnet768'  # default
    
    def _sample_documents(self, collection_name: str, backend: str) -> List[dict]:
        """Sample N documents from collection."""
        if backend == 'aws':
            return self._sample_from_opensearch(collection_name)
        else:
            return self._sample_from_chromadb(collection_name)
    
    def _sample_from_opensearch(self, collection_name: str) -> List[dict]:
        """Sample from OpenSearch (placeholder - requires opensearch-py client)."""
        return []
    
    def _sample_from_chromadb(self, collection_name: str) -> List[dict]:
        """Sample from ChromaDB (placeholder - requires chromadb client)."""
        return []
    
    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between two vectors."""
        return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
    
    def _upload_report(self, report: DriftReport):
        """Upload drift report to S3."""
        key = f"drift-reports/{report.collection_name}/{report.timestamp}.json"
        try:
            self.s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=json.dumps(asdict(report), indent=2),
                ContentType='application/json'
            )
            print(f"[OK] Drift report uploaded to s3://{self.bucket}/{key}")
        except ClientError as e:
            print(f"[WARN] Failed to upload drift report: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description='Detect embedding drift')
    parser.add_argument('collection', help='Collection name')
    parser.add_argument('--backend', default='aws', choices=['aws', 'legacy'])
    parser.add_argument('--sample-size', type=int, default=100)
    parser.add_argument('--threshold', type=float, default=0.95)
    
    args = parser.parse_args()
    detector = DriftDetector(sample_size=args.sample_size, threshold=args.threshold)
    report = detector.detect(args.collection, backend=args.backend)
    
    print(json.dumps(asdict(report), indent=2))
    
    if report.drifted:
        print(f"\n[WARN] Drift detected: mean_similarity={report.mean_similarity:.3f} < {args.threshold}")
        sys.exit(1)
    else:
        print(f"\n[OK] No drift: mean_similarity={report.mean_similarity:.3f} >= {args.threshold}")


if __name__ == '__main__':
    main()
