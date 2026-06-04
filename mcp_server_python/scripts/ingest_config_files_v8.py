"""Tenant-aware config file ingestion (v8) — Neptune + OpenSearch.

The ONLY dual-writer: creates ConfigFile nodes + SETS_ENV edges in Neptune
AND embeds config content to the tenant's OpenSearch code collection (with
SHAIndex content-addressed dedupe).

Implements: R1–R3, R9–R12 of graph-port-workflow-structure.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1]))

from _ingest_common import (
    COLLECTION_CONFIG,
    build_ingestion_data_access,
    build_ingestion_parser,
    resolve_tenant_and_mode,
    resolve_worktree_root,
)
from _ingest_cost_model import IngestionReportWriter
from _ingest_dedupe import SHAIndex
from _config_parser import ConfigFileParser

VERSION = "8.0.0"

# parm/config subtrees → system label
CONFIG_DIRS = {
    'parm/config/gfs': 'gfs',
    'parm/config/gefs': 'gefs',
    'parm/config/gcafs': 'gcafs',
    'parm/config/sfs': 'sfs',
}
EXCLUDED_SUFFIXES = {'.j2', '.yaml', '.yml'}


def discover_config_files(worktree_root: Path) -> list[dict]:
    """Discover plain config files under parm/config/{gfs,gefs,gcafs,sfs}/.

    Excludes Jinja2 templates (.j2), YAML (.yaml/.yml), and hidden files.
    Returns dicts: {abs_path, rel_path, filename, system}, sorted by path.
    """
    worktree_root = Path(worktree_root)
    configs: list[dict] = []
    for rel_dir, system in CONFIG_DIRS.items():
        abs_dir = worktree_root / rel_dir
        if not abs_dir.is_dir():
            continue
        for f in sorted(abs_dir.iterdir()):
            if not f.is_file():
                continue
            if f.suffix in EXCLUDED_SUFFIXES or f.name.startswith('.'):
                continue
            configs.append({
                'abs_path': str(f),
                'rel_path': str(f.relative_to(worktree_root)),
                'filename': f.name,
                'system': system,
            })
    return configs


def _node_name(cfg: dict) -> str:
    """GFS configs use the short name; non-GFS are system-qualified (R2.5)."""
    short = ConfigFileParser.config_short_name(cfg['filename'])
    return short if cfg['system'] == 'gfs' else f"{cfg['system']}/{short}"


# ════════════════════════════════════════════════════════════════════════
# Neptune write helpers — f-string label prefixing, tenant=None (R2)
# ════════════════════════════════════════════════════════════════════════


async def _write_config_node(graph_db, prefix: str, cfg: dict, parsed: dict, tenant):
    """MERGE a ConfigFile node with all properties (key: name)."""
    cypher = (
        f"MERGE (c:`{prefix}ConfigFile` {{name: $name}}) "
        f"SET c.file_path = $file_path, c.system = $system, "
        f"c.category = $category, c.env_var_count = $env_var_count, "
        f"c.line_count = $line_count, c.filename = $filename, "
        f"c.tenant_id = $tenant_id, c.version = $version, "
        f"c.updated_at = $updated_at"
    )
    await graph_db.query(cypher, params={
        "name": _node_name(cfg), "file_path": cfg['rel_path'],
        "system": cfg['system'],
        "category": ConfigFileParser.categorize_config(cfg['filename']),
        "env_var_count": len(parsed['env_vars']),
        "line_count": parsed.get('line_count', 0),
        "filename": cfg['filename'],
        "tenant_id": tenant.tenant_id, "version": VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }, tenant=None)


async def _write_sets_env_edges(graph_db, prefix: str, cfg: dict, parsed: dict):
    """Create SETS_ENV edges from ConfigFile to EnvironmentVariable (R2.2)."""
    node_name = _node_name(cfg)
    for var in parsed['env_vars']:
        if not var['name']:
            continue
        cypher = (
            f"MATCH (c:`{prefix}ConfigFile` {{name: $config_name}}) "
            f"MERGE (e:`{prefix}EnvironmentVariable` {{name: $var_name}}) "
            f"ON CREATE SET e.default_value = $dv "
            f"MERGE (c)-[r:SETS_ENV]->(e) "
            f"SET r.value = $value, r.is_default = $is_default"
        )
        await graph_db.query(cypher, params={
            "config_name": node_name, "var_name": var['name'],
            "dv": var.get('default_value', ''),
            "value": var.get('default_value', ''),
            "is_default": var.get('is_default', False),
        }, tenant=None)


# ════════════════════════════════════════════════════════════════════════
# OpenSearch helpers (R3)
# ════════════════════════════════════════════════════════════════════════


def _build_context_header(cfg: dict, parsed: dict) -> str:
    """Prepend a context header with filename, system, category, path, vars."""
    var_names = [v['name'] for v in parsed['env_vars']]
    category = ConfigFileParser.categorize_config(cfg['filename'])
    return (
        f"# Configuration File: {cfg['filename']}\n"
        f"# System: {cfg['system']}, Category: {category}\n"
        f"# Path: {cfg['rel_path']}\n"
        f"# Environment variables: {', '.join(var_names[:20])}\n\n"
    )


def _build_os_metadata(cfg: dict, parsed: dict, tenant) -> dict:
    """Structured metadata for the OpenSearch document (R3.2)."""
    var_names = [v['name'] for v in parsed['env_vars']]
    return {
        'tenant_id': tenant.tenant_id,
        'file_type': 'config',
        'system': cfg['system'],
        'category': ConfigFileParser.categorize_config(cfg['filename']),
        'file_path': cfg['rel_path'],
        'filename': cfg['filename'],
        'env_var_count': len(parsed['env_vars']),
        'env_vars': json.dumps(var_names[:50]),
    }


async def _write_os_document(raw_os_client, index: str, doc_id: str,
                             content: str, embedding, metadata: dict):
    """Index a config document into OpenSearch."""
    body = {"content": content, "metadata": metadata, "embedding": embedding}
    await asyncio.to_thread(raw_os_client.index, index=index, id=doc_id, body=body)


# ════════════════════════════════════════════════════════════════════════
# Entry point
# ════════════════════════════════════════════════════════════════════════


async def main() -> int:
    parser = build_ingestion_parser(
        "Config file ingestion (v8) — Neptune + OpenSearch")
    args = parser.parse_args()

    catalog_path = os.environ.get(
        "MCP_TENANT_CATALOG_PATH",
        str(Path(__file__).parents[1] / "src" / "config" / "tenants.yaml"),
    )
    from src.config.tenants import load_catalog

    catalog = load_catalog(catalog_path)
    tenant, mode = resolve_tenant_and_mode(args, catalog)
    worktree_root = resolve_worktree_root(tenant)
    prefix = tenant.label_prefix

    print(f"[INFO] tenant={tenant.tenant_id} mode={mode} "
          f"worktree={worktree_root} prefix={prefix!r}")

    configs = discover_config_files(worktree_root)
    print(f"[INFO] Discovered {len(configs)} config files")

    if args.dry_run:
        total_vars = 0
        for cfg in configs:
            total_vars += len(ConfigFileParser.parse_config_file(cfg['abs_path'])['env_vars'])
        print("=" * 60)
        print("DRY-RUN SUMMARY (no writes performed)")
        print("=" * 60)
        print(f"  Config files:        {len(configs)}")
        print(f"  ConfigFile nodes:    {len(configs)} (would create)")
        print(f"  SETS_ENV edges:      {total_vars} (would create)")
        print(f"  OpenSearch docs:     {len(configs)} (would embed)")
        print("=" * 60)
        return 0

    try:
        uda, raw_os_client = await build_ingestion_data_access()
    except Exception as e:
        print(f"[ERROR] Failed to connect data layer: {e}", file=sys.stderr)
        return 1

    graph_db = uda.graph_db
    sha_index = SHAIndex(client=raw_os_client)
    index_name = f"{tenant.index_prefix}mdc-code-titan1024"
    report = IngestionReportWriter(tenant.tenant_id, tenant.branch, mode)

    for cfg in configs:
        try:
            parsed = ConfigFileParser.parse_config_file(cfg['abs_path'])
        except Exception as e:
            print(f"[WARN] parse error {cfg['rel_path']}: {e}", file=sys.stderr)
            continue

        report.increment("total_files_processed")

        try:
            # ── Neptune writes ──
            await _write_config_node(graph_db, prefix, cfg, parsed, tenant)
            await _write_sets_env_edges(graph_db, prefix, cfg, parsed)
            report.increment(f"nodes:{prefix}ConfigFile")
            report.increment("relationships_created", len(parsed['env_vars']))

            # ── OpenSearch writes (SHAIndex dedupe) ──
            sha = sha_index.hash_file(Path(cfg['abs_path']))
            dedupe = await sha_index.lookup(sha, collection=COLLECTION_CONFIG)
            if dedupe.is_duplicate:
                report.increment("documents_deduped")
            else:
                content = _build_context_header(cfg, parsed) + parsed['raw_content']
                embedding = await uda.vector_db._generate_embedding(content[:8000])
                doc_id = f"config_{sha[:12]}"
                await _write_os_document(raw_os_client, index_name, doc_id,
                                         content, embedding,
                                         _build_os_metadata(cfg, parsed, tenant))
                await sha_index.register(sha, collection=COLLECTION_CONFIG,
                                         tenant=tenant, index=index_name,
                                         doc_id=doc_id)
                report.increment("bedrock_invocations")
                report.increment("estimated_tokens", len(content) // 4)
                report.increment(f"docs:{index_name}")
        except Exception as e:
            print(f"[WARN] {cfg['rel_path']}: {e}", file=sys.stderr)
            continue

        if args.delay and args.delay > 0:
            await asyncio.sleep(args.delay)

    report_path = report.finalize()
    print(f"[DONE] report: {report_path}")
    await uda.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
