#!/usr/bin/env python3
"""
reembed_collection.py — Re-embed an existing OpenSearch collection with a new model.

Reads all documents from a source index (e.g., mdc-*-mpnet768), generates new
embeddings via the specified model (e.g., titan1024), and writes to the target
index (e.g., mdc-*-titan1024).

Usage:
  python3 scripts/reembed_collection.py --source mdc-community-summaries-mpnet768 \
    --target mdc-community-summaries-titan1024 --model titan1024
  python3 scripts/reembed_collection.py --source mdc-ee2-standards-mpnet768 \
    --target mdc-ee2-standards-titan1024 --model titan1024

Env vars: OPENSEARCH_ENDPOINT, AWS_REGION
"""

import os
import sys
import json
import time
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from embedding_registry import EmbeddingModelRegistry
from embedding_provider import create_provider


def main():
    parser = argparse.ArgumentParser(description="Re-embed OpenSearch collection")
    parser.add_argument("--source", required=True, help="Source index name")
    parser.add_argument("--target", required=True, help="Target index name")
    parser.add_argument("--model", default="titan1024", help="Model short name")
    parser.add_argument("--batch-size", type=int, default=25, help="Batch size")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    endpoint = os.environ.get("OPENSEARCH_ENDPOINT", "")
    region = os.environ.get("AWS_REGION", "us-east-1")
    if not endpoint:
        print("[ERROR] OPENSEARCH_ENDPOINT required")
        sys.exit(1)

    # Set up embedding provider
    registry = EmbeddingModelRegistry()
    profile = registry.get_profile(args.model)
    provider = create_provider(profile)
    print(f"[OK] Model: {profile.short_name} ({profile.dimensions}-dim, {profile.provider})")

    # Set up OpenSearch client
    from opensearchpy import OpenSearch, RequestsHttpConnection, AWSV4SignerAuth
    import boto3
    credentials = boto3.Session().get_credentials()
    auth = AWSV4SignerAuth(credentials, region, "es")
    client = OpenSearch(
        hosts=[{"host": endpoint.replace("https://", "").rstrip("/"), "port": 443}],
        http_auth=auth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
    )

    # Count source docs
    source_count = client.count(index=args.source)["count"]
    print(f"[OK] Source: {args.source} ({source_count} docs)")
    print(f"[OK] Target: {args.target}")

    if args.dry_run:
        print(f"[DRY-RUN] Would re-embed {source_count} docs")
        return

    # Scroll through source index
    scroll_body = {
        "query": {"match_all": {}},
        "size": args.batch_size,
        "_source": {"excludes": ["embedding"]},
    }
    resp = client.search(index=args.source, body=scroll_body, scroll="5m")
    scroll_id = resp["_scroll_id"]
    hits = resp["hits"]["hits"]

    total_processed = 0
    total_errors = 0
    start_time = time.time()

    while hits:
        # Extract content for embedding
        texts = []
        docs = []
        for hit in hits:
            src = hit["_source"]
            content = src.get("content", "")
            if content:
                texts.append(content)
                docs.append((hit["_id"], src))

        # Generate embeddings
        if texts:
            try:
                embeddings = provider.embed(texts)
            except Exception as e:
                print(f"[ERROR] Embedding batch failed: {e}")
                total_errors += len(texts)
                # Continue to next batch
                resp = client.scroll(scroll_id=scroll_id, scroll="5m")
                scroll_id = resp["_scroll_id"]
                hits = resp["hits"]["hits"]
                continue

            # Bulk index to target
            body = []
            for i, (doc_id, src) in enumerate(docs):
                body.append({"index": {"_index": args.target, "_id": doc_id}})
                body.append({
                    "content": src.get("content", ""),
                    "embedding": embeddings[i],
                    "metadata": src.get("metadata", {}),
                    "source_file": src.get("source_file", ""),
                    "chunk_id": src.get("chunk_id", doc_id),
                    "collection_name": src.get("collection_name", ""),
                    "model_profile": profile.short_name,
                })
            result = client.bulk(body=body)
            if result.get("errors"):
                failed = sum(
                    1 for item in result["items"]
                    if item.get("index", {}).get("error")
                )
                total_errors += failed

        total_processed += len(docs)
        elapsed = time.time() - start_time
        rate = total_processed / elapsed if elapsed > 0 else 0
        remaining = (source_count - total_processed) / rate if rate > 0 else 0
        print(
            f"  [PROGRESS] {total_processed}/{source_count} "
            f"({rate:.1f} docs/s, ~{remaining:.0f}s remaining)"
        )

        # Next scroll page
        resp = client.scroll(scroll_id=scroll_id, scroll="5m")
        scroll_id = resp["_scroll_id"]
        hits = resp["hits"]["hits"]

    # Clean up scroll
    try:
        client.clear_scroll(scroll_id=scroll_id)
    except Exception:
        pass

    elapsed = time.time() - start_time
    target_count = client.count(index=args.target)["count"]
    print(f"\n{'='*60}")
    print(f"Re-embedding complete")
    print(f"  Source: {args.source} ({source_count} docs)")
    print(f"  Target: {args.target} ({target_count} docs)")
    print(f"  Processed: {total_processed}, Errors: {total_errors}")
    print(f"  Time: {elapsed:.1f}s ({total_processed/elapsed:.1f} docs/s)")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
