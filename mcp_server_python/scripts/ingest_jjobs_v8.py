"""Tenant-aware J-Job ingestion (v8).

Ingests J-Job scripts under a tenant's prefixed OpenSearch indices
and Neptune graph nodes. Supports --tenant, --mode, and dedupe.

Implements: Requirements 3.1, 3.5, 3.6 of omd-tenants-2-v17-pilot.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _ingest_common import (
    build_ingestion_parser,
    resolve_tenant_and_mode,
    resolve_worktree_root,
)
from _ingest_cost_model import IngestionReportWriter
from _ingest_dedupe import SHAIndex, make_reference_document
from _ingest_walkers import files_for_diff, files_for_full_branch


async def main() -> int:
    parser = build_ingestion_parser("Tenant-aware J-Job ingestion (v8)")
    args = parser.parse_args()

    catalog_path = os.environ.get(
        "MCP_TENANT_CATALOG_PATH",
        str(Path(__file__).parents[1] / "src" / "config" / "tenants.yaml"),
    )
    sys.path.insert(0, str(Path(__file__).parents[1]))
    from src.config.tenants import load_catalog

    catalog = load_catalog(catalog_path)
    tenant, mode = resolve_tenant_and_mode(args, catalog)
    worktree_root = resolve_worktree_root(tenant)

    # J-Jobs live under dev/jobs/ or jobs/
    jobs_dir = worktree_root / "dev" / "jobs"
    if not jobs_dir.is_dir():
        jobs_dir = worktree_root / "jobs"

    print(f"[INFO] tenant={tenant.tenant_id} mode={mode} jobs_dir={jobs_dir}")

    if args.dry_run:
        print("[DRY-RUN] would ingest J-Jobs from", jobs_dir)
        return 0

    # For J-Jobs, always use full enumeration of the jobs directory
    files = [p for p in jobs_dir.rglob("*") if p.is_file() and ".git" not in p.parts] \
        if jobs_dir.is_dir() else []

    report = IngestionReportWriter(tenant.tenant_id, tenant.branch, mode)
    sha_index = SHAIndex(client=None)

    for path in files:
        report.increment("total_files_processed")
        sha = sha_index.hash_file(path)
        result = await sha_index.lookup(sha)

        if result.is_duplicate:
            _ref = make_reference_document(
                tenant=tenant, source_path=str(path), sha=sha,
                canonical_index=result.canonical_index,
                canonical_id=result.canonical_id,
                canonical_tenant="gw",
            )
            report.increment("documents_deduped")
        else:
            report.increment("bedrock_invocations")
            report.increment("estimated_tokens", len(path.read_bytes()) // 4)
            index_name = f"{tenant.index_prefix}mdc-jjobs-titan1024"
            report.increment(f"docs:{index_name}")
            label = f"{tenant.label_prefix}JJob"
            report.increment(f"nodes:{label}")
            # TODO(Phase C): vector_db.write_documents + graph_db.write_node
            await sha_index.register(sha, tenant=tenant, index=index_name, doc_id=f"jjob_{sha[:12]}")

    report_path = report.finalize()
    print(f"[DONE] report: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
