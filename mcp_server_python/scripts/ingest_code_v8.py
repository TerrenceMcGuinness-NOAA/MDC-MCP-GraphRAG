"""Tenant-aware code metadata ingestion (v8).

Ingests source code files under a tenant's prefixed OpenSearch indices
and Neptune graph nodes. Supports --tenant, --mode, and dedupe.

Implements: Requirements 3.1, 3.2, 3.6 of omd-tenants-2-v17-pilot.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1]))

from _ingest_common import (
    COLLECTION_CODE,
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
from _ingest_walkers import files_for_diff, files_for_full_branch


async def main() -> int:
    parser = build_ingestion_parser("Tenant-aware code metadata ingestion (v8)")
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

    if args.dry_run:
        print("[DRY-RUN] would ingest code from", worktree_root)
        return 0

    try:
        uda, raw_os_client = await build_ingestion_data_access()
    except Exception as e:
        print(f"[ERROR] Failed to connect data layer: {e}", file=sys.stderr)
        return 1

    sha_index = SHAIndex(client=raw_os_client)
    collection_version = resolve_collection_version(args)
    # Code is TENANT-scoped — per (repo, branch). Domain "code-context" matches
    # the serving collection (rag-data-plane-gap-closure R3; fixes the historical
    # mdc-code-titan1024 vs mdc-code-context-* mismatch).
    index_name = resolve_collection_name(
        domain="code-context", scope="tenant", tenant=tenant,
        version=collection_version,
    )
    label = f"{tenant.label_prefix}File"
    print(f"[INFO] collection_version={collection_version} index={index_name}")

    files = list(files_for_diff(worktree_root) if mode == "diff"
                 else files_for_full_branch(worktree_root))

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
            result = await sha_index.lookup(sha, collection=COLLECTION_CODE)

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

                doc_id = f"code_{sha[:12]}"
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
                    sha, collection=COLLECTION_CODE, tenant=tenant,
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
