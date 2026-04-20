#!/usr/bin/env python3
"""
Re-embed documents from one OpenSearch index into another using a different
embedding model. Reads content from source index, generates new embeddings
via Bedrock, and bulk-indexes into the target index.

Usage:
  python3 scripts/reembed_index.py \
    --source mdc-workflow-docs-mpnet768 \
    --target mdc-workflow-docs-titan1024 \
    --model titan1024 \
    --batch-size 25

Requires: DB_BACKEND=aws, OPENSEARCH_ENDPOINT, AWS_REGION
"""

import os
import sys
import json
import time
import argparse

# Add scripts dir to path for registry imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from embedding_registry import EmbeddingModelRegistry
from embedding_provider import create_provider


def get_os_client():
    """Get authenticated OpenSearch client."""
    from opensearchpy import OpenSearch, RequestsHttpConnection
    from requests_aws4auth import AWS4Auth
    import boto3

    endpoint = os.environ["OPENSEARCH_ENDPOINT"]
    region = os.environ.get("AWS_REGION", "us-east-1")
    host = endpoint.replace("https://", "").replace("http://", "")

    creds = boto3.Session().get_credentials().get_frozen_credentials()
    auth = AWS4Auth(creds.access_key, creds.secret_key, region, "es",
                    session_token=creds.token)

    return OpenSearch(
        hosts=[{"host": host, "port": 443}],
        http_auth=auth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        timeout=60,
        max_retries=3,
        retry_on_timeout=True,
    )


def scroll_all(client, index, batch_size=500):
    """Yield all docs from an index via scroll API."""
    body = {"query": {"match_all": {}}, "size": batch_size}
    resp = client.search(index=index, body=body, scroll="5m")
    scroll_id = resp.get("_scroll_id")
    hits = resp["hits"]["hits"]
    total = resp["hits"]["total"]["value"]
    print(f"[INFO] Source index {index}: {total} docs")

    while hits:
        for h in hits:
            yield h
        resp = client.scroll(scroll_id=scroll_id, scroll="5m")
        hits = resp["hits"]["hits"]

    if scroll_id:
        try:
            client.clear_scroll(scroll_id=scroll_id)
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="Re-embed docs between OpenSearch indices")
    parser.add_argument("--source", required=True, help="Source index name")
    parser.add_argument("--target", required=True, help="Target index name")
    parser.add_argument("--model", default="titan1024", help="Target embedding model profile")
    parser.add_argument("--batch-size", type=int, default=25, help="Docs per Bedrock batch")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Skip docs already in target index")
    args = parser.parse_args()

    client = get_os_client()

    # Verify indices exist
    for idx in [args.source, args.target]:
        if not client.indices.exists(index=idx):
            print(f"[ERROR] Index {idx} does not exist")
            sys.exit(1)

    # Get target count before
    before = client.count(index=args.target)["count"]
    print(f"[INFO] Target index {args.target}: {before} docs before")

    # Load existing IDs if skip-existing
    existing_ids = set()
    if args.skip_existing and before > 0:
        print("[INFO] Loading existing target IDs...")
        for doc in scroll_all(client, args.target, batch_size=10000):
            existing_ids.add(doc["_id"])
        print(f"[INFO] {len(existing_ids)} existing IDs loaded")

    # Set up embedding provider
    profile = EmbeddingModelRegistry().get_profile(args.model)
    provider = create_provider(profile)
    print(f"[INFO] Embedding model: {profile.model_id} ({profile.dimensions}-dim)")

    # Process in batches
    batch_ids, batch_contents, batch_metas = [], [], []
    indexed, skipped, errors = 0, 0, 0

    for doc in scroll_all(client, args.source):
        doc_id = doc["_id"]
        src = doc["_source"]

        if doc_id in existing_ids:
            skipped += 1
            continue

        content = src.get("content", "")
        if not content:
            skipped += 1
            continue

        # Preserve original metadata, update model info
        meta = src.get("metadata", {})
        meta["embedding_model"] = profile.model_id
        meta["model_profile"] = args.model
        meta["reembedded_from"] = args.source

        batch_ids.append(doc_id)
        batch_contents.append(content)
        batch_metas.append(meta)

        if len(batch_ids) >= args.batch_size:
            n, e = _flush_batch(client, args.target, provider, profile,
                                batch_ids, batch_contents, batch_metas)
            indexed += n
            errors += e
            batch_ids, batch_contents, batch_metas = [], [], []

    # Final batch
    if batch_ids:
        n, e = _flush_batch(client, args.target, provider, profile,
                            batch_ids, batch_contents, batch_metas)
        indexed += n
        errors += e

    after = client.count(index=args.target)["count"]
    print(f"\n{'='*60}")
    print(f"RE-EMBED SUMMARY")
    print(f"{'='*60}")
    print(f"Source:  {args.source}")
    print(f"Target:  {args.target}")
    print(f"Model:   {profile.model_id} ({profile.dimensions}-dim)")
    print(f"Indexed: {indexed}")
    print(f"Skipped: {skipped}")
    print(f"Errors:  {errors}")
    print(f"Before:  {before}")
    print(f"After:   {after}")
    print(f"{'='*60}")


def _flush_batch(client, target, provider, profile,
                 ids, contents, metas):
    """Embed and index a batch. Returns (indexed_count, error_count)."""
    try:
        embeddings = provider.embed(contents)
    except Exception as e:
        # Try one-by-one for batches with oversized docs
        print(f"[WARN] Batch embed failed ({e}), retrying individually...")
        return _flush_individually(client, target, provider, profile,
                                   ids, contents, metas)

    body = []
    for i, doc_id in enumerate(ids):
        body.append({"index": {"_index": target, "_id": doc_id}})
        body.append({
            "content": contents[i],
            "embedding": embeddings[i],
            "metadata": metas[i],
            "source_file": metas[i].get("source_file", ""),
            "chunk_id": doc_id,
            "collection_name": target,
            "model_profile": profile.short_name,
        })

    result = client.bulk(body=body)
    failed = sum(1 for item in result.get("items", [])
                 if item.get("index", {}).get("error"))
    ok = len(ids) - failed
    if failed:
        print(f"[WARN] {failed}/{len(ids)} failed in bulk index")
    print(f"  [OK] {ok} docs indexed (total batch: {len(ids)})", end="\r")
    return ok, failed


def _flush_individually(client, target, provider, profile,
                        ids, contents, metas):
    """Fallback: embed and index one doc at a time."""
    indexed, errors = 0, 0
    for i, doc_id in enumerate(ids):
        try:
            emb = provider.embed([contents[i]])[0]
            body = {
                "content": contents[i],
                "embedding": emb,
                "metadata": metas[i],
                "source_file": metas[i].get("source_file", ""),
                "chunk_id": doc_id,
                "collection_name": target,
                "model_profile": profile.short_name,
            }
            client.index(index=target, id=doc_id, body=body)
            indexed += 1
        except Exception as e:
            err_msg = str(e)
            if "Too many input tokens" in err_msg or "maxLength" in err_msg:
                # Truncate to ~20K chars (well under 8192 token / 50K char limit)
                truncated = contents[i][:20000]
                try:
                    emb = provider.embed([truncated])[0]
                    body = {
                        "content": contents[i],
                        "embedding": emb,
                        "metadata": metas[i],
                        "source_file": metas[i].get("source_file", ""),
                        "chunk_id": doc_id,
                        "collection_name": target,
                        "model_profile": profile.short_name,
                    }
                    client.index(index=target, id=doc_id, body=body)
                    indexed += 1
                    continue
                except Exception:
                    pass
            print(f"[WARN] Doc {doc_id}: {err_msg[:80]}")
            errors += 1
    return indexed, errors


if __name__ == "__main__":
    main()
