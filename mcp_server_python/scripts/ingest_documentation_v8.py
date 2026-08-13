"""Tenant-aware documentation ingestion (v8).

Ingests workflow documentation files under a tenant's prefixed
OpenSearch indices. Supports --tenant, --mode {diff,full}, and
content-addressed dedupe via SHAIndex.

The file set is manifest-driven and disk-priority (disk-priority-ingest,
Req 1/2): ``resolve_doc_file_set`` selects each source's ``local_path`` subtree
(scoped by a documentation extension allowlist) instead of walking the whole
worktree, and probes each source so stale URL-only sources fall through to the
crawler. Every written document carries provenance (Req 3).

Implements: Requirements 3.1, 3.2, 3.3, 3.5, 3.7 of omd-tenants-2-v17-pilot;
Requirements 1, 2, 3 of disk-priority-ingest.
"""
from __future__ import annotations

import asyncio
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1]))

from _ingest_common import (
    COLLECTION_DOCUMENTATION,
    build_ingestion_data_access,
    build_ingestion_parser,
    resolve_collection_name,
    resolve_collection_version,
    resolve_tenant_and_mode,
    resolve_worktree_root,
    write_vector_doc,
)
from _ingest_cost_model import IngestionReportWriter
from _ingest_dedupe import SHAIndex, make_reference_document
from _ingest_provenance import build_provenance
from _ingest_sources import (
    DISPOSITION_DISK,
    load_doc_sources,
    resolve_doc_file_set,
)
from _ingest_walkers import files_for_diff

# Manifest + repo root for source-set resolution (disk-priority-ingest).
_MANIFEST_PATH = Path(__file__).parents[1] / "src" / "config" / "unified_manifest.json"
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _resolve_profile_and_dimension(vector_db=None) -> tuple[str, int]:
    """Resolve the active embedding profile short-name and vector dimension.

    Prefers the already-resolved provider's profile (so the provenance stamp
    records what was actually used) and falls back to the registry keyed by
    the active ``MCP_EMBEDDING_PROFILE`` — which is also the only path
    available in ``--dry-run`` where no backend is connected.
    """
    from src.data.collection_namer import active_embedding_profile
    from src.data.embedding_registry import EmbeddingModelRegistry

    prof_obj = getattr(vector_db, "_profile", None) if vector_db is not None else None
    if prof_obj is not None and getattr(prof_obj, "short_name", None):
        return prof_obj.short_name, prof_obj.dimensions
    profile = active_embedding_profile()
    return profile, EmbeddingModelRegistry().get_profile(profile).dimensions


def _print_review_gate(index_name, profile, dimension, decisions, resolved_files, mode):
    """Print the resolved source set — the Req 5.2 review gate (dry-run + write)."""
    per_source = Counter(source.name for _, source, _ in resolved_files)
    print("[PLAN] documentation source-set resolution")
    print(f"  index      : {index_name}")
    print(f"  profile    : {profile} ({dimension}-dim)")
    print(f"  mode       : {mode}")
    print(f"  {'source':24s} {'decision':12s} {'reason':18s} files")
    print(f"  {'-' * 62}")
    for d in decisions:
        count = per_source.get(d.name, 0) if d.disposition == DISPOSITION_DISK else 0
        print(f"  {d.name:24s} {d.disposition:12s} {d.reason:18s} {count}")
    print(f"  {'-' * 62}")
    disk = sum(1 for d in decisions if d.disposition == DISPOSITION_DISK)
    crawl = sum(1 for d in decisions if d.disposition != DISPOSITION_DISK)
    print(f"  totals     : {disk} disk / {crawl} needs_crawl / "
          f"{len(resolved_files)} documentation files")


async def main() -> int:
    parser = build_ingestion_parser("Tenant-aware documentation ingestion (v8)")
    args = parser.parse_args()

    catalog_path = os.environ.get(
        "MCP_TENANT_CATALOG_PATH",
        str(Path(__file__).parents[1] / "src" / "config" / "tenants.yaml"),
    )
    from src.config.tenants import load_catalog

    catalog = load_catalog(catalog_path)
    tenant, mode = resolve_tenant_and_mode(args, catalog)
    worktree_root = resolve_worktree_root(tenant)

    print(f"[INFO] tenant={tenant.tenant_id} mode={mode} root={worktree_root}")

    # ── Source-set resolution (manifest-driven, disk-priority) ──────────────
    collection_version = resolve_collection_version(args)
    # Documentation is SHARED (NWS-wide) — one unprefixed collection for every
    # tenant (rag-data-plane-gap-closure R3.4). Profile-derived name.
    index_name = resolve_collection_name(
        domain="workflow-docs", scope="shared", tenant=tenant,
        version=collection_version,
    )
    # Profile + dimension for the dry-run banner and provenance. Refined from
    # the live provider after the data layer connects (below).
    profile, dimension = _resolve_profile_and_dimension()

    manifest_path = os.environ.get("MCP_UNIFIED_MANIFEST_PATH", str(_MANIFEST_PATH))
    doc_sources = load_doc_sources(manifest_path)
    if args.only:
        wanted = set(args.only)
        doc_sources = [s for s in doc_sources if s.name in wanted]

    resolved_files, decisions = resolve_doc_file_set(
        doc_sources, worktree_root, repo_root=_REPO_ROOT,
    )
    # In diff mode, intersect the resolved set with the changed-file list
    # rather than replacing it (design.md).
    if mode == "diff":
        try:
            changed = {p.resolve() for p in files_for_diff(worktree_root)}
            resolved_files = [
                (p, s, pr) for (p, s, pr) in resolved_files if p.resolve() in changed
            ]
        except Exception as exc:  # noqa: BLE001 — diff is best-effort
            print(f"[WARN] diff intersect skipped: {exc}", file=sys.stderr)

    _print_review_gate(index_name, profile, dimension, decisions, resolved_files, mode)

    if args.dry_run:
        print("[DRY-RUN] no writes performed")
        return 0

    # Build data access layer
    try:
        uda, raw_os_client = await build_ingestion_data_access()
    except Exception as e:
        print(f"[ERROR] Failed to connect data layer: {e}", file=sys.stderr)
        print("  Check: DB_BACKEND, OPENSEARCH_ENDPOINT, NEPTUNE_ENDPOINT, AWS_REGION", file=sys.stderr)
        return 1

    # Record the profile/dimension actually resolved by the live provider.
    profile, dimension = _resolve_profile_and_dimension(uda.vector_db)

    sha_index = SHAIndex(client=raw_os_client)
    print(f"[INFO] collection_version={collection_version} index={index_name}")

    report = IngestionReportWriter(tenant.tenant_id, tenant.branch, mode)

    for path, source, probe in resolved_files:
        # Skip binary files, broken symlinks, and empty files
        try:
            content = path.read_text(errors="strict")
        except (UnicodeDecodeError, ValueError, OSError):
            continue
        if not content.strip():
            continue

        report.increment("total_files_processed")
        sha = sha_index.hash_file(path)

        provenance = build_provenance(
            source_name=source.name,
            source_kind="disk",
            resolved_path=path,
            commit_sha=probe.commit_sha,
            dirty=probe.dirty,
            profile=profile,
            dimension=dimension,
        )

        try:
            result = await sha_index.lookup(sha, collection=COLLECTION_DOCUMENTATION)

            if result.is_duplicate:
                ref = make_reference_document(
                    tenant=tenant,
                    source_path=str(path),
                    sha=sha,
                    canonical_index=result.canonical_index,
                    canonical_id=result.canonical_id,
                    canonical_tenant=result.canonical_index.split("_")[0] if result.canonical_index else "gw",
                )
                # Deduped references carry the same provenance (Req 3.3).
                ref["metadata"].update(provenance)
                report.increment("documents_deduped")
                await asyncio.to_thread(
                    raw_os_client.index, index=index_name, id=f"ref_{sha[:12]}", body=ref,
                )
            else:
                truncated = content[:8000]
                embedding = await uda.vector_db._generate_embedding(truncated)

                doc_id = f"doc_{sha[:12]}"
                doc_meta = {
                    "tenant_id": tenant.tenant_id,
                    "source": str(path),
                    "content_sha256": sha,
                    **provenance,
                }
                await write_vector_doc(
                    uda, raw_os_client, index=index_name, doc_id=doc_id,
                    content=truncated, metadata=doc_meta, embedding=embedding,
                )
                report.increment("bedrock_invocations")
                report.increment("estimated_tokens", len(truncated) // 4)
                report.increment(f"docs:{index_name}")
                await sha_index.register(
                    sha, collection=COLLECTION_DOCUMENTATION, tenant=tenant,
                    index=index_name, doc_id=doc_id,
                )

        except Exception as exc:
            print(f"[WARN] {path.name}: {exc}", file=sys.stderr)
            continue

        if args.delay and args.delay > 0:
            await asyncio.sleep(args.delay)

    report_path = report.finalize()
    print(f"[DONE] report: {report_path}")
    await uda.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
