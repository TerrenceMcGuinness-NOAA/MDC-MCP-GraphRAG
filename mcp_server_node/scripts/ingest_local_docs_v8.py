#!/usr/bin/env python3
"""
ingest_local_docs_v8.py — Phase 48 Local-First Documentation Ingestion

Reads `LOCAL_DOCUMENTATION_SOURCES` from documentation_sources_config.py (SPOT)
and ingests on-disk content from git submodules into ChromaDB. Replaces the
URL-crawl path for global-workflow / rocoto / ecflow user docs and adds the
GitHub Wiki as net-new coverage.

Usage:
    # Dry-run into a scratch collection
    DOCS_COLLECTION=phase48-scratch python3 ingest_local_docs_v8.py --dry-run

    # Real ingest into the v8.2.0 collection
    DOCS_COLLECTION=global-workflow-docs-v8-2-0 python3 ingest_local_docs_v8.py

    # Single source
    python3 ingest_local_docs_v8.py --source rocoto-local --limit-files 5

Env:
    DOCS_COLLECTION     Target collection name (default: phase48-scratch)
    CHROMADB_HOST/PORT  Defaults: localhost / 8080
    CACHE_ROOT          HuggingFace model cache root (default: /mcp_rag_eib/cache)
    REPO_ROOT           Override the repo root (default: derived from this file)

Output: ASCII-only [OK]/[WARN]/[ERROR] log lines + a summary table.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

# --- Make sibling modules importable regardless of CWD ----------------------
_SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS_DIR))

from documentation_sources_config import (  # noqa: E402
    LOCAL_DOCUMENTATION_SOURCES,
    get_all_local_sources,
)
from lib.doc_parsers import (  # noqa: E402
    EXTENSION_OVERRIDES,
    PARSER_REGISTRY,
    parse_roff_man_file,
)

# --- Configuration ----------------------------------------------------------
EMBEDDING_MODEL = "all-mpnet-base-v2"
DEFAULT_COLLECTION = "phase48-scratch"
CHROMADB_HOST = os.getenv("CHROMADB_HOST", "localhost")
CHROMADB_PORT = int(os.getenv("CHROMADB_PORT", "8080"))

REPO_ROOT = Path(os.getenv("REPO_ROOT", _SCRIPTS_DIR.parent.parent)).resolve()
SUPPORTED_REPOS = REPO_ROOT / "supported_repos"

CHROMA_BATCH = 100  # add() batch size

VERSION = "8.2.0-local"


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def log(level: str, msg: str) -> None:
    print(f"[{level}] {msg}", flush=True)


def get_submodule_commit(submodule_path: Path) -> str:
    """Return short submodule HEAD SHA, or 'unknown' on failure."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(submodule_path), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()[:12]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "unknown"


def make_id(submodule: str, rel_path: str, idx: int, content: str) -> str:
    h = hashlib.sha256(f"{submodule}:{rel_path}:{idx}:{content[:200]}".encode()).hexdigest()
    return h[:24]


def iter_files(root: Path, subpaths: List[str], exts: List[str]) -> Iterable[Path]:
    """Walk root/subpath(s) yielding files whose extension is in `exts`.

    `subpaths` may name directories (recursively walked) or individual files
    (yielded directly). `exts` is a list like ['.rst', '.md']; an empty
    string in the list matches files with NO extension (e.g. INSTALL).
    """
    ext_set = {e.lower() for e in exts}
    want_no_ext = "" in ext_set

    def _matches(p: Path) -> bool:
        suffix = p.suffix.lower()
        return suffix in ext_set or (want_no_ext and suffix == "")

    seen: set[Path] = set()
    for subpath in subpaths:
        target = (root / subpath).resolve()
        if not target.exists():
            continue
        if target.is_file():
            if _matches(target) and target not in seen:
                seen.add(target)
                yield target
            continue
        # Directory walk
        for p in target.rglob("*"):
            if not p.is_file() or p in seen:
                continue
            if any(part.startswith(".") for part in p.relative_to(target).parts):
                continue
            if _matches(p):
                seen.add(p)
                yield p


def select_parser_for_file(path: Path, default_parser: str) -> str:
    """Return the parser key, applying extension overrides."""
    return EXTENSION_OVERRIDES.get(path.suffix.lower(), default_parser)


# ---------------------------------------------------------------------------
# Per-source processing
# ---------------------------------------------------------------------------

def process_source(source: dict, limit_files: int = 0) -> Tuple[List[str], List[str], List[dict]]:
    """Walk one local source and return (ids, documents, metadatas)."""
    name = source["name"]
    submodule = source["submodule"]
    submodule_path = SUPPORTED_REPOS / submodule
    if not submodule_path.exists():
        log("WARN", f"{name}: submodule path missing: {submodule_path}")
        return [], [], []

    commit = get_submodule_commit(submodule_path)
    tier = source.get("tier", "unknown")
    default_parser = source["parser"]
    exts = source.get("extensions", [])

    files = list(iter_files(submodule_path, source["paths"], exts))
    if limit_files:
        files = files[:limit_files]
    log("OK", f"{name}: {len(files)} files (commit={commit}, parser={default_parser})")

    ids: List[str] = []
    docs: List[str] = []
    metas: List[dict] = []
    files_ok = files_skip = 0

    now_iso = datetime.now(timezone.utc).isoformat()

    for fpath in files:
        try:
            parser_key = select_parser_for_file(fpath, default_parser)
            if parser_key == "roff_man":
                chunks = parse_roff_man_file(fpath)
            else:
                content = fpath.read_text(encoding="utf-8", errors="replace")
                if not content.strip():
                    files_skip += 1
                    continue
                chunks = PARSER_REGISTRY[parser_key](content)
            if not chunks:
                files_skip += 1
                continue
            rel_path = str(fpath.relative_to(REPO_ROOT))
            for i, chunk in enumerate(chunks):
                cid = make_id(submodule, rel_path, i, chunk)
                ids.append(cid)
                docs.append(chunk)
                metas.append({
                    "source_type": "local",
                    "source_name": name,
                    "source": name,  # alias for back-compat with URL-crawl schema (used by SemanticSearchTools queries)
                    "submodule": submodule,
                    "submodule_commit": commit,
                    "file_path": rel_path,
                    "parser": parser_key,
                    "tier": tier,
                    "chunk_index": i,
                    "chunk_count": len(chunks),
                    "ingestion_date": now_iso,
                    "version": VERSION,
                })
            files_ok += 1
        except Exception as e:  # noqa: BLE001
            log("ERROR", f"{name}: failed on {fpath}: {e}")

    log("OK", f"{name}: produced {len(docs)} chunks ({files_ok} files OK, {files_skip} skipped)")
    return ids, docs, metas


# ---------------------------------------------------------------------------
# ChromaDB
# ---------------------------------------------------------------------------

def get_collection(collection_name: str, dry_run: bool):
    """Open / create the target collection. Returns (collection, embed_fn)."""
    import chromadb
    from chromadb.utils import embedding_functions

    cache_root = os.getenv("CACHE_ROOT", "/mcp_rag_eib/cache")
    hf_cache = os.path.join(cache_root, "huggingface")
    os.makedirs(hf_cache, exist_ok=True)
    os.environ["HF_HOME"] = hf_cache
    os.environ["TRANSFORMERS_CACHE"] = os.path.join(cache_root, "transformers")

    embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL,
        device="cpu",
        cache_folder=hf_cache,
    )

    log("OK", f"Connecting to ChromaDB at {CHROMADB_HOST}:{CHROMADB_PORT}")
    client = chromadb.HttpClient(host=CHROMADB_HOST, port=CHROMADB_PORT)

    coll = client.get_or_create_collection(
        name=collection_name,
        embedding_function=embed_fn,
        metadata={
            "version": VERSION,
            "type": "local-first-docs",
            "phase": "48",
            "embedding_model": EMBEDDING_MODEL,
        },
    )
    log("OK", f"Collection ready: {collection_name} (current count={coll.count()})")
    return coll


def write_in_batches(coll, ids: List[str], docs: List[str], metas: List[dict]) -> int:
    """Add chunks in CHROMA_BATCH-sized batches. Returns count actually added."""
    if not ids:
        return 0
    # Dedupe within batch (ChromaDB rejects duplicate ids in a single add)
    seen = set()
    u_ids, u_docs, u_metas = [], [], []
    for i, _id in enumerate(ids):
        if _id in seen:
            continue
        seen.add(_id)
        u_ids.append(_id)
        u_docs.append(docs[i])
        u_metas.append(metas[i])
    added = 0
    for start in range(0, len(u_ids), CHROMA_BATCH):
        end = start + CHROMA_BATCH
        try:
            coll.upsert(
                ids=u_ids[start:end],
                documents=u_docs[start:end],
                metadatas=u_metas[start:end],
            )
            added += end - start if end <= len(u_ids) else len(u_ids) - start
        except Exception as e:  # noqa: BLE001
            log("ERROR", f"batch {start}-{end} failed: {e}")
    return added


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--collection", default=os.getenv("DOCS_COLLECTION", DEFAULT_COLLECTION),
                    help="ChromaDB collection name (or set DOCS_COLLECTION env)")
    ap.add_argument("--source", action="append", default=[],
                    help="Restrict to named source(s). Repeatable. Default: all enabled.")
    ap.add_argument("--limit-files", type=int, default=0,
                    help="Limit files per source (0 = unlimited). Useful for smoke tests.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Parse + chunk only; do not write to ChromaDB.")
    args = ap.parse_args()

    log("OK", f"Phase 48 ingest starting (REPO_ROOT={REPO_ROOT})")
    log("OK", f"Target collection: {args.collection}{' (DRY-RUN)' if args.dry_run else ''}")

    sources = get_all_local_sources(enabled_only=True)
    if args.source:
        wanted = set(args.source)
        sources = [s for s in sources if s["name"] in wanted]
        missing = wanted - {s["name"] for s in sources}
        if missing:
            log("WARN", f"unknown source(s) ignored: {sorted(missing)}")
    if not sources:
        log("ERROR", "no sources to process")
        return 2

    coll = None
    if not args.dry_run:
        coll = get_collection(args.collection, dry_run=False)

    summary: List[Tuple[str, int, int]] = []  # (name, chunks, written)
    for src in sources:
        log("OK", f"--- processing {src['name']} ---")
        ids, docs, metas = process_source(src, limit_files=args.limit_files)
        written = 0
        if not args.dry_run and ids:
            written = write_in_batches(coll, ids, docs, metas)
            log("OK", f"{src['name']}: wrote {written} chunks to {args.collection}")
        summary.append((src["name"], len(ids), written))

    log("OK", "=" * 70)
    log("OK", f"{'source':<28} {'chunks':>10} {'written':>10}")
    log("OK", "-" * 70)
    total_chunks = total_written = 0
    for name, c, w in summary:
        log("OK", f"{name:<28} {c:>10} {w:>10}")
        total_chunks += c
        total_written += w
    log("OK", "-" * 70)
    log("OK", f"{'TOTAL':<28} {total_chunks:>10} {total_written:>10}")

    if coll is not None:
        log("OK", f"Collection {args.collection} final count: {coll.count()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
