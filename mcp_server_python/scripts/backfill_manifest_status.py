#!/usr/bin/env python3
"""Backfill unified_manifest.json doc_count and last_ingested from OpenSearch."""

import argparse
import json
from datetime import datetime, timezone

import boto3
from opensearchpy import OpenSearch, RequestsHttpConnection, AWSV4SignerAuth


def main():
    parser = argparse.ArgumentParser(description="Backfill manifest status from OpenSearch")
    parser.add_argument("--manifest", required=True, help="Path to unified_manifest.json")
    parser.add_argument("--opensearch-endpoint", required=True, help="OpenSearch domain (no https://)")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--index", default="mdc-workflow-docs-titan1024")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    credentials = boto3.Session().get_credentials()
    auth = AWSV4SignerAuth(credentials, args.region, "es")
    client = OpenSearch(
        hosts=[{"host": args.opensearch_endpoint, "port": 443}],
        http_auth=auth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
    )

    with open(args.manifest) as f:
        manifest = json.load(f)

    now = datetime.now(timezone.utc).isoformat()
    updated = 0

    for src in manifest.get("sources", []):
        if src.get("source_type") != "url_crawl":
            continue
        name = src["name"]
        query = {"query": {"term": {"metadata.source.keyword": name}}}
        try:
            result = client.count(index=args.index, body=query)
            count = result["count"]
        except Exception:
            # Fallback: try without .keyword
            try:
                query2 = {"query": {"match": {"metadata.source": name}}}
                result = client.count(index=args.index, body=query2)
                count = result["count"]
            except Exception as e:
                print(f"  [ERROR] {name}: {e}")
                continue

        old_count = src.get("doc_count", 0)
        if count != old_count:
            print(f"  [UPDATE] {name}: {old_count} -> {count}")
            src["doc_count"] = count
            if count > 0:
                src["last_ingested"] = now
            updated += 1
        else:
            print(f"  [OK] {name}: {count} (unchanged)")

    if not args.dry_run:
        with open(args.manifest, "w") as f:
            json.dump(manifest, f, indent=2)
        print(f"\n[OK] Manifest updated: {updated} sources changed")
    else:
        print(f"\n[DRY RUN] Would update {updated} sources")


if __name__ == "__main__":
    main()
