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
sys.path.insert(0, str(Path(__file__).parents[1]))

from _ingest_common import (
    COLLECTION_JJOBS,
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
from _ingest_walkers import files_for_full_branch


async def main() -> int:
    parser = build_ingestion_parser("Tenant-aware J-Job ingestion (v8)")
    args = parser.parse_args()

    catalog_path = os.environ.get(
        "MCP_TENANT_CATALOG_PATH",
        str(Path(__file__).parents[1] / "src" / "config" / "tenants.yaml"),
    )
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

    try:
        uda, raw_os_client = await build_ingestion_data_access()
    except Exception as e:
        print(f"[ERROR] Failed to connect data layer: {e}", file=sys.stderr)
        return 1

    sha_index = SHAIndex(client=raw_os_client)
    collection_version = resolve_collection_version(args)
    # J-Jobs are TENANT-scoped — per (repo, branch). Profile-derived name.
    index_name = resolve_collection_name(
        domain="jjobs", scope="tenant", tenant=tenant,
        version=collection_version,
    )
    label = f"{tenant.label_prefix}JJob"
    print(f"[INFO] collection_version={collection_version} index={index_name}")

    files = [p for p in jobs_dir.rglob("*") if p.is_file() and ".git" not in p.parts] \
        if jobs_dir.is_dir() else []

    report = IngestionReportWriter(tenant.tenant_id, tenant.branch, mode)

    for path in files:
        try:
            content = path.read_text(errors="strict")
        except (UnicodeDecodeError, ValueError, OSError):
            continue
        if not content.strip():
            continue

        report.increment("total_files_processed")
        sha = sha_index.hash_file(path)

        try:
            result = await sha_index.lookup(sha, collection=COLLECTION_JJOBS)

            if result.is_duplicate:
                ref = make_reference_document(
                    tenant=tenant, source_path=str(path), sha=sha,
                    canonical_index=result.canonical_index,
                    canonical_id=result.canonical_id,
                    canonical_tenant="gw",
                )
                report.increment("documents_deduped")
                await asyncio.to_thread(
                    raw_os_client.index, index=index_name, id=f"ref_{sha[:12]}", body=ref,
                )
            else:
                truncated = content[:8000]
                embedding = await uda.vector_db._generate_embedding(truncated)

                doc_id = f"jjob_{sha[:12]}"
                doc_meta = {
                    "tenant_id": tenant.tenant_id,
                    "source": str(path),
                    "content_sha256": sha,
                }
                await write_vector_doc(
                    uda, raw_os_client, index=index_name, doc_id=doc_id,
                    content=truncated, metadata=doc_meta, embedding=embedding,
                )
                report.increment("bedrock_invocations")
                report.increment("estimated_tokens", len(truncated) // 4)
                report.increment(f"docs:{index_name}")

                await sha_index.register(
                    sha, collection=COLLECTION_JJOBS, tenant=tenant,
                    index=index_name, doc_id=doc_id,
                )

            # ALWAYS model the graph — independent of the embedding/dedupe decision
            cypher = (
                f"MERGE (n:`{label}` {{name: $name, path: $path}}) "
                f"SET n.tenant_id = $tenant_id, n.sha256 = $sha, "
                f"n.collection_version = $cv"
            )
            await uda.graph_db.query(cypher, params={
                "name": path.stem, "path": str(path),
                "tenant_id": tenant.tenant_id, "sha": sha,
                "cv": collection_version,
            })
            report.increment(f"nodes:{label}")

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
