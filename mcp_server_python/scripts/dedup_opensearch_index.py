#!/usr/bin/env python3
"""Remove duplicate documents from an OpenSearch index by content fingerprint.

Groups documents by content[:200] fingerprint. For groups with >1 document,
keeps the one with the richest metadata (highest field count, most recent
timestamp). Deletes the rest via bulk API.

Usage:
  python dedup_opensearch_index.py --dry-run --index mdc-workflow-docs-titan1024
  python dedup_opensearch_index.py --index mdc-workflow-docs-titan1024
"""

import argparse
from collections import defaultdict

import boto3
from opensearchpy import OpenSearch, RequestsHttpConnection, AWSV4SignerAuth


def connect(endpoint: str, region: str) -> OpenSearch:
    credentials = boto3.Session().get_credentials()
    auth = AWSV4SignerAuth(credentials, region, "es")
    return OpenSearch(
        hosts=[{"host": endpoint, "port": 443}],
        http_auth=auth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
    )


def score_doc(doc: dict) -> tuple:
    """Score a document for keeper selection: (field_count, timestamp)."""
    src = doc.get("_source", {})
    meta = src.get("metadata", {})
    field_count = len(meta)
    ts = meta.get("ingested_at", meta.get("timestamp", ""))
    return (field_count, ts)


def main():
    parser = argparse.ArgumentParser(description="Deduplicate OpenSearch index by content fingerprint")
    parser.add_argument("--index", default="mdc-workflow-docs-titan1024")
    parser.add_argument("--endpoint", default="vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    client = connect(args.endpoint, args.region)

    # Get total doc count
    total = client.count(index=args.index)["count"]
    print(f"[INFO] Index: {args.index}")
    print(f"[INFO] Total documents: {total}")

    # Scroll through all documents
    fingerprints: dict[str, list[dict]] = defaultdict(list)
    scroll_body = {"query": {"match_all": {}}, "_source": ["content", "metadata"], "size": 500}
    resp = client.search(index=args.index, body=scroll_body, scroll="5m")
    scroll_id = resp["_scroll_id"]
    hits = resp["hits"]["hits"]

    while hits:
        for doc in hits:
            content = doc.get("_source", {}).get("content", "")
            fp = content[:200]
            fingerprints[fp].append(doc)
        resp = client.scroll(scroll_id=scroll_id, scroll="5m")
        scroll_id = resp["_scroll_id"]
        hits = resp["hits"]["hits"]

    client.clear_scroll(scroll_id=scroll_id)

    # Find duplicates
    to_delete = []
    for fp, docs in fingerprints.items():
        if len(docs) > 1:
            # Keep the doc with richest metadata
            docs.sort(key=score_doc, reverse=True)
            to_delete.extend(docs[1:])

    unique_count = len(fingerprints)
    dup_count = len(to_delete)

    print(f"[INFO] Unique content fingerprints: {unique_count}")
    print(f"[INFO] Duplicate documents to remove: {dup_count}")

    if dup_count == 0:
        print("[OK] No duplicates found")
        return

    if args.dry_run:
        print(f"[DRY RUN] Would delete {dup_count} documents, preserving {unique_count} unique")
        return

    # Bulk delete
    deleted = 0
    batch = []
    for doc in to_delete:
        batch.append({"delete": {"_index": args.index, "_id": doc["_id"]}})
        if len(batch) >= 500:
            resp = client.bulk(body=batch)
            deleted += len(batch)
            batch = []
            print(f"  [DELETE] {deleted}/{dup_count}...")

    if batch:
        client.bulk(body=batch)
        deleted += len(batch)

    # Force refresh
    client.indices.refresh(index=args.index)
    final_count = client.count(index=args.index)["count"]

    print(f"[OK] Deleted {deleted} duplicates")
    print(f"[OK] Final document count: {final_count}")
    print(f"[OK] Unique content preserved: {unique_count}")


if __name__ == "__main__":
    main()
