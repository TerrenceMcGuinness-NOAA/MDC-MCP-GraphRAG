#!/usr/bin/env python3
"""PDF ingestion pipeline for unified manifest pdf_download sources.

Downloads PDFs, extracts text via pypdf, chunks at 512-token windows with
64-token overlap, embeds with Titan v2 (1024-dim), indexes to OpenSearch.
"""

import argparse
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import requests
from pypdf import PdfReader

# Add scripts dir to path for local imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from embedding_provider import BedrockProvider, EmbeddingError
from embedding_registry import EmbeddingModelRegistry


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest PDF sources from unified manifest into OpenSearch"
    )
    parser.add_argument(
        "--manifest",
        default="mcp_server_python/src/config/unified_manifest.json",
        help="Path to unified manifest JSON",
    )
    parser.add_argument("--region", default="us-east-1", help="AWS region")
    parser.add_argument("--source", help="Process only this named source")
    parser.add_argument("--dry-run", action="store_true", help="Skip embed/index")
    return parser.parse_args()


def load_pdf_sources(
    manifest_path: str, source_filter: Optional[str] = None
) -> Tuple[List[dict], dict]:
    """Load manifest, return (filtered_sources, full_manifest_data)."""
    with open(manifest_path) as f:
        manifest = json.load(f)

    pdf_sources = [
        s for s in manifest["sources"]
        if s.get("crawl_type") == "pdf_download" and s.get("enabled", False)
    ]

    if source_filter:
        matched = [s for s in pdf_sources if s["name"] == source_filter]
        if not matched:
            print(
                f"ERROR: source '{source_filter}' not found among enabled "
                f"pdf_download entries",
                file=sys.stderr,
            )
            sys.exit(1)
        pdf_sources = matched

    return pdf_sources, manifest


def download_pdf(url: str, source_name: str) -> Optional[bytes]:
    """Download PDF bytes. Returns None on failure."""
    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        return resp.content
    except requests.RequestException as exc:
        print(f"[ERROR] Failed to download {source_name} from {url}: {exc}",
              file=sys.stderr)
        return None


def extract_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF, concatenating non-empty pages with markers."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    parts = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text()
        if text and text.strip():
            parts.append(f"\n\n--- Page {i} ---\n\n{text}")
    return "".join(parts)


def chunk_text(text: str, chunk_size: int = 512, overlap: int = 64) -> List[str]:
    """Split text into token-based chunks with sliding window overlap.

    Uses whitespace splitting. Absorbs final remainder < overlap into last chunk.
    """
    tokens = text.split()
    if not tokens:
        return []

    chunks = []
    start = 0
    while start < len(tokens):
        end = start + chunk_size
        remaining = len(tokens) - end
        if 0 < remaining < overlap:
            chunks.append(" ".join(tokens[start:]))
            break
        chunks.append(" ".join(tokens[start:end]))
        if end >= len(tokens):
            break
        start = end - overlap

    return chunks


def embed_chunks(
    chunks: List[str], provider: "BedrockProvider", source_name: str
) -> List[Tuple[int, List[float]]]:
    """Embed chunks, returning (chunk_index, vector) pairs. Skips failures."""
    results = []
    for i, chunk in enumerate(chunks):
        try:
            vectors = provider.embed([chunk])
            results.append((i, vectors[0]))
        except EmbeddingError as exc:
            print(f"[ERROR] Embedding failed for {source_name} chunk {i}: {exc}",
                  file=sys.stderr)
    return results


def _estimate_page(chunk_text: str) -> int:
    """Extract page number from the most recent page marker in chunk."""
    matches = re.findall(r"--- Page (\d+) ---", chunk_text)
    return int(matches[-1]) if matches else 1


def index_chunks(source: dict, chunks: List[str],
                 embeddings: List[Tuple[int, List[float]]], collection) -> int:
    """Index embedded chunks to OpenSearch. Returns count indexed."""
    source_name = source["name"]
    ids, documents, vectors, metadatas = [], [], [], []

    for chunk_idx, vector in embeddings:
        ids.append(f"{source_name}-chunk-{chunk_idx}")
        documents.append(chunks[chunk_idx])
        vectors.append(vector)
        metadatas.append({
            "source": source_name,
            "url": source["url"],
            "page": _estimate_page(chunks[chunk_idx]),
            "chunk_index": chunk_idx,
            "tier": source.get("tier", ""),
            "crawl_type": "pdf_download",
        })

    if ids:
        collection.upsert(ids=ids, documents=documents,
                          embeddings=vectors, metadatas=metadatas)
    return len(ids)


def update_manifest(manifest_path: str, manifest_data: dict) -> None:
    """Write manifest atomically (temp file + rename)."""
    tmp_path = manifest_path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(manifest_data, f, indent=2)
        f.write("\n")
    os.replace(tmp_path, manifest_path)


def main() -> None:
    args = parse_args()
    start_time = time.time()

    pdf_sources, manifest_data = load_pdf_sources(args.manifest, args.source)
    print(f"Found {len(pdf_sources)} PDF source(s) to process")

    provider = None
    collection = None
    if not args.dry_run:
        os.environ.setdefault("AWS_REGION", args.region)
        profile = EmbeddingModelRegistry().get_profile("titan1024")
        provider = BedrockProvider(profile)
        from aws_backend import get_vector_client
        os_client = get_vector_client()
        collection = os_client.get_or_create_collection(
            "global-workflow-docs-v8-0-0-titan1024")

    total_chunks = 0
    sources_processed = 0

    for source in pdf_sources:
        pdf_bytes = download_pdf(source["url"], source["name"])
        if pdf_bytes is None:
            continue

        text = extract_text(pdf_bytes)
        chunks = chunk_text(text)
        sources_processed += 1

        if args.dry_run:
            print(f"\n[DRY-RUN] {source['name']}")
            print(f"  PDF size: {len(pdf_bytes) / 1024 / 1024:.1f} MB")
            print(f"  Pages extracted: {text.count('--- Page ')}")
            print(f"  Chunks produced: {len(chunks)}")
            if chunks:
                print(f"  First chunk sample: {chunks[0][:200]}")
            continue

        embeddings = embed_chunks(chunks, provider, source["name"])
        indexed = index_chunks(source, chunks, embeddings, collection)
        total_chunks += indexed

        for entry in manifest_data["sources"]:
            if entry["name"] == source["name"]:
                entry["last_ingested"] = datetime.now(timezone.utc).isoformat()
                entry["doc_count"] = indexed
                break

        print(f"  [OK] {source['name']}: {indexed} chunks indexed")

    if not args.dry_run and sources_processed > 0:
        update_manifest(args.manifest, manifest_data)

    elapsed = time.time() - start_time
    print(f"\nDone: {sources_processed} sources, {total_chunks} chunks indexed, "
          f"{elapsed:.1f}s elapsed")


if __name__ == "__main__":
    main()
