#!/usr/bin/env python3
"""Batch-update the code-with-context-v8-0-0 ChromaDB collection to strip
the spurious ``global-workflow/`` prefix from ``file_path`` metadata.

Audit showed 29,495 of 58,761 documents carry paths like
``global-workflow/sorc/...`` instead of ``sorc/...``.  This script walks the
collection in batches, rewrites the affected metadata, and prints progress
using ASCII-only output (no emoji) so it is safe to call from MCP pipelines.

Environment variables
---------------------
CHROMADB_HOST : str, default "localhost"
CHROMADB_PORT : int, default 8080

Usage
-----
    # Preview what would change (no writes)
    python fix_chromadb_paths.py --dry-run

    # Apply the fix
    python fix_chromadb_paths.py
"""

import argparse
import os
import sys

import chromadb

COLLECTION_NAME = "code-with-context-v8-0-0"
BAD_PREFIX = "global-workflow/"
BATCH_SIZE = 5000


def parse_args():
    parser = argparse.ArgumentParser(
        description="Strip 'global-workflow/' prefix from file_path metadata "
                    "in the ChromaDB collection."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count affected documents without modifying anything.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    host = os.environ.get("CHROMADB_HOST", "localhost")
    port = int(os.environ.get("CHROMADB_PORT", "8080"))

    print(f"[INFO] Connecting to ChromaDB at {host}:{port}")
    client = chromadb.HttpClient(host=host, port=port)

    try:
        col = client.get_collection(COLLECTION_NAME)
    except Exception as exc:
        print(f"[ERROR] Failed to open collection '{COLLECTION_NAME}': {exc}")
        sys.exit(1)

    total_docs = col.count()
    print(f"[INFO] Collection '{COLLECTION_NAME}' has {total_docs} documents")

    if args.dry_run:
        print("[INFO] Dry-run mode -- no changes will be written")

    total_fixed = 0
    batch_num = 0
    offset = 0

    while offset < total_docs:
        batch_num += 1
        result = col.get(
            limit=BATCH_SIZE,
            offset=offset,
            include=["metadatas"],
        )

        ids = result["ids"]
        metadatas = result["metadatas"]

        if not ids:
            break

        fix_ids = []
        fix_metadatas = []

        for doc_id, meta in zip(ids, metadatas):
            file_path = meta.get("file_path", "")
            if file_path.startswith(BAD_PREFIX):
                new_path = file_path[len(BAD_PREFIX):]
                updated_meta = dict(meta)
                updated_meta["file_path"] = new_path
                fix_ids.append(doc_id)
                fix_metadatas.append(updated_meta)

        if fix_ids and not args.dry_run:
            col.update(ids=fix_ids, metadatas=fix_metadatas)

        total_fixed += len(fix_ids)
        print(
            f"[OK] Batch {batch_num}: fixed {len(fix_ids)} paths "
            f"(total: {total_fixed})"
        )

        offset += len(ids)

    action = "would fix" if args.dry_run else "fixed"
    print(f"[OK] Complete: {action} {total_fixed} of {total_docs} total documents")


if __name__ == "__main__":
    main()
