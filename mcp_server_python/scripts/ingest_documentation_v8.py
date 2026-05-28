"""Tenant-aware documentation ingestion (v8).

Ingests workflow documentation files under a tenant's prefixed
OpenSearch indices. Supports --tenant, --mode {diff,full}, and
content-addressed dedupe via SHAIndex.

Implements: Requirements 3.1, 3.2, 3.3, 3.5, 3.7 of omd-tenants-2-v17-pilot.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Add scripts/ to path for sibling imports
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
    parser = build_ingestion_parser("Tenant-aware documentation ingestion (v8)")
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

    print(f"[INFO] tenant={tenant.tenant_id} mode={mode} root={worktree_root}")

    if args.dry_run:
        print("[DRY-RUN] would ingest documentation from", worktree_root)
        return 0

    # File enumeration
    if mode == "diff":
        files = list(files_for_diff(worktree_root))
    else:
        files = list(files_for_full_branch(worktree_root))

    report = IngestionReportWriter(tenant.tenant_id, tenant.branch, mode)
    sha_index = SHAIndex(client=None)  # No real client until Phase C

    for path in files:
        report.increment("total_files_processed")
        sha = sha_index.hash_file(path)
        result = await sha_index.lookup(sha)

        if result.is_duplicate:
            # Write reference document (no embedding call)
            _ref = make_reference_document(
                tenant=tenant,
                source_path=str(path),
                sha=sha,
                canonical_index=result.canonical_index,
                canonical_id=result.canonical_id,
                canonical_tenant=result.canonical_index.split("_")[0] if result.canonical_index else "gw",
            )
            report.increment("documents_deduped")
            # TODO(Phase C): vector_db.write_documents([_ref], tenant=tenant)
        else:
            # Full content document with embedding
            report.increment("bedrock_invocations")
            report.increment("estimated_tokens", len(path.read_bytes()) // 4)
            index_name = f"{tenant.index_prefix}mdc-workflow-docs-titan1024"
            report.increment(f"docs:{index_name}")
            # TODO(Phase C): embed + vector_db.write_documents([doc], tenant=tenant)
            await sha_index.register(sha, tenant=tenant, index=index_name, doc_id=f"doc_{sha[:12]}")

    report_path = report.finalize()
    print(f"[DONE] report: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
