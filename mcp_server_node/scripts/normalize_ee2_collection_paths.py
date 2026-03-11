#!/usr/bin/env python3
"""
Normalize absolute checkout-specific metadata paths in EE2 ChromaDB collections.

Purpose:
- Convert absolute paths like /mcp_rag_eib/eib-mcp-rag-server/supported_repos/... to
  repository-relative paths so integrity checks do not flag checkout-specific prefixes.

Default target collection:
- ee2-standards-v5-0-0-enhanced
"""

import argparse
from typing import Any, Dict, Optional

try:
    import chromadb
except ImportError as exc:
    raise SystemExit("[ERROR] chromadb is required. Install with: python3 -m pip install --user chromadb") from exc


REPO_ROOT_PREFIXES = [
    "/mcp_rag_eib/eib-mcp-rag-server/",
]

SUPPORTED_REPOS_MARKER = "/supported_repos/"


def normalize_path(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return value

    path_value = value.replace('\\\\', '/')

    for prefix in REPO_ROOT_PREFIXES:
        if path_value.startswith(prefix):
            return path_value[len(prefix):]

    marker_index = path_value.find(SUPPORTED_REPOS_MARKER)
    if marker_index >= 0:
        return path_value[marker_index + 1 :]

    return value


def normalize_metadata(meta: Optional[Dict[str, Any]]) -> (Optional[Dict[str, Any]], bool):
    if not isinstance(meta, dict):
        return meta, False

    updated = dict(meta)
    changed = False

    for key in ("file_path", "source_path", "source_file", "source"):
        old_value = updated.get(key)
        new_value = normalize_path(old_value)
        if new_value != old_value:
            updated[key] = new_value
            changed = True

    return updated, changed


def run(collection_name: str, host: str, port: int, batch_size: int, dry_run: bool) -> int:
    client = chromadb.HttpClient(host=host, port=port)
    collection = client.get_collection(collection_name)

    total = collection.count()
    print(f"[INIT] Collection: {collection_name}")
    print(f"[INIT] Host: {host}:{port}")
    print(f"[INIT] Documents: {total}")

    updated_docs = 0
    scanned_docs = 0

    for offset in range(0, total, batch_size):
        result = collection.get(
            limit=batch_size,
            offset=offset,
            include=["metadatas"],
        )

        ids = result.get("ids", [])
        metas = result.get("metadatas", [])

        update_ids = []
        update_metas = []

        for doc_id, meta in zip(ids, metas):
            scanned_docs += 1
            new_meta, changed = normalize_metadata(meta)
            if changed:
                updated_docs += 1
                update_ids.append(doc_id)
                update_metas.append(new_meta)

        if update_ids and not dry_run:
            collection.update(ids=update_ids, metadatas=update_metas)

    mode = "DRY-RUN" if dry_run else "APPLIED"
    print(f"[OK] Mode: {mode}")
    print(f"[OK] Scanned docs: {scanned_docs}")
    print(f"[OK] Updated docs: {updated_docs}")

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize EE2 collection metadata paths")
    parser.add_argument(
        "--collection",
        default="ee2-standards-v5-0-0-enhanced",
        help="ChromaDB collection name",
    )
    parser.add_argument("--host", default="127.0.0.1", help="ChromaDB host")
    parser.add_argument("--port", type=int, default=8080, help="ChromaDB port")
    parser.add_argument("--batch-size", type=int, default=200, help="Batch size for pagination")
    parser.add_argument("--dry-run", action="store_true", help="Scan only, do not update")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(
        run(
            collection_name=args.collection,
            host=args.host,
            port=args.port,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
        )
    )
