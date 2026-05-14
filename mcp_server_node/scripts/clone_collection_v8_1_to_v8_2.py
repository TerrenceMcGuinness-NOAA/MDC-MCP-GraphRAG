#!/usr/bin/env python3
"""
clone_collection_v8_1_to_v8_2.py — Phase 48 cutover helper.

Clones global-workflow-docs-v8-1-0 into global-workflow-docs-v8-2-0,
SKIPPING any chunks whose `source` (or `source_name`) field matches a
URL source that has been superseded by a Phase 48 local source. Embeddings
are copied verbatim — both ends use all-mpnet-base-v2 (768-dim) so
re-embedding is unnecessary.

After this clone runs, follow up with:
    DOCS_COLLECTION=global-workflow-docs-v8-2-0 \
        python3 ingest_local_docs_v8.py
to add the on-disk content for the superseded sources plus the new wiki.

Idempotent: uses upsert; re-running adds no duplicates.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import chromadb  # noqa: E402
from chromadb.utils import embedding_functions  # noqa: E402

from documentation_sources_config import get_url_names_replaced_by_local  # noqa: E402

SRC = "global-workflow-docs-v8-1-0"
DST = os.getenv("DOCS_COLLECTION", "global-workflow-docs-v8-2-0")
BATCH = 500

CHROMADB_HOST = os.getenv("CHROMADB_HOST", "localhost")
CHROMADB_PORT = int(os.getenv("CHROMADB_PORT", "8080"))


def main() -> int:
    skip = get_url_names_replaced_by_local(enabled_only=True)
    print(f"[OK] Skipping URL sources superseded by Phase 48 locals: {sorted(skip)}", flush=True)
    print(f"[OK] Source: {SRC}  ->  Destination: {DST}", flush=True)

    cache_root = os.getenv("CACHE_ROOT", "/mcp_rag_eib/cache")
    hf_cache = os.path.join(cache_root, "huggingface")
    os.environ["HF_HOME"] = hf_cache
    embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-mpnet-base-v2", device="cpu", cache_folder=hf_cache,
    )

    client = chromadb.HttpClient(host=CHROMADB_HOST, port=CHROMADB_PORT)
    src_coll = client.get_collection(SRC)
    dst_coll = client.get_or_create_collection(
        name=DST,
        embedding_function=embed_fn,
        metadata={
            "version": "8.2.0",
            "type": "documentation",
            "phase": "48",
            "embedding_model": "all-mpnet-base-v2",
            "lineage": f"clone-of:{SRC}+local",
        },
    )
    src_count = src_coll.count()
    print(f"[OK] {SRC} count: {src_count}", flush=True)
    print(f"[OK] {DST} starting count: {dst_coll.count()}", flush=True)

    offset = 0
    copied = 0
    skipped = 0
    while offset < src_count:
        page = src_coll.get(
            limit=BATCH,
            offset=offset,
            include=["documents", "embeddings", "metadatas"],
        )
        ids = page.get("ids") or []
        if not ids:
            break

        keep_ids, keep_docs, keep_embs, keep_metas = [], [], [], []
        embs = page.get("embeddings")
        if embs is None:
            embs = [None] * len(ids)
        docs = page.get("documents")
        if docs is None:
            docs = [None] * len(ids)
        metas = page.get("metadatas")
        if metas is None:
            metas = [{} for _ in ids]
        for i, _id in enumerate(ids):
            md = metas[i] or {}
            src_name = md.get("source") or md.get("source_name")
            if src_name in skip:
                skipped += 1
                continue
            keep_ids.append(_id)
            keep_docs.append(docs[i])
            keep_embs.append(embs[i])
            keep_metas.append(md)

        if keep_ids:
            dst_coll.upsert(
                ids=keep_ids,
                documents=keep_docs,
                embeddings=keep_embs,
                metadatas=keep_metas,
            )
            copied += len(keep_ids)

        offset += len(ids)
        print(f"[OK] progress: scanned={offset}/{src_count} copied={copied} skipped={skipped}", flush=True)

    print(f"[OK] Done. {DST} final count: {dst_coll.count()}", flush=True)
    print(f"[OK] copied={copied}, skipped={skipped}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
