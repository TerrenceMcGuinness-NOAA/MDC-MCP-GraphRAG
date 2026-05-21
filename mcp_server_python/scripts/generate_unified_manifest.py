"""Bootstrap script: generate ``unified_manifest.json`` from current state.

Runs offline against the source tree (and optionally against
OpenSearch) to produce a valid :class:`UnifiedManifest` covering all
seven source types.

Discovery strategy
------------------

1. **URL crawl sources** — copied from the existing
   ``documentation_sources.json`` so the migration does not drop any
   declared URLs.
2. **Other source types** — generated from a curated
   ``KNOWN_SOURCES`` list mapping each ingestion script under
   ``mcp_server_node/scripts/`` to a representative SourceEntry. The
   list is hand-maintained (the script set is small enough that
   automatic discovery would risk misclassifying scripts).
3. **Doc counts** — when ``--with-actual-counts`` is passed and an
   OpenSearch endpoint is reachable, the script populates
   ``doc_count`` from ``cat.indices`` rather than the legacy
   ``documentation_sources.json`` values.

Usage::

    python scripts/generate_unified_manifest.py
    python scripts/generate_unified_manifest.py --output /tmp/manifest.json
    python scripts/generate_unified_manifest.py --dry-run
    python scripts/generate_unified_manifest.py --with-actual-counts

Run from ``mcp_server_python/`` so relative paths resolve.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

# Make ``src.*`` importable when executed as a script from anywhere.
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.manifest.models import SourceEntry, SourceType, UnifiedManifest

log = logging.getLogger("generate_unified_manifest")


#: Default output location (Requirement 7.1).
DEFAULT_OUTPUT: Path = ROOT / "src" / "config" / "unified_manifest.json"

#: Legacy URL manifest used as the seed for url_crawl entries.
LEGACY_URL_MANIFEST: Path = (
    ROOT / "src" / "config" / "documentation_sources.json"
)


# ── known sources catalog ─────────────────────────────────────────────


#: Manually curated mapping for non-URL source types. Each entry is a
#: ``(name, source_type, ingestion_script, type_fields)`` tuple plus
#: common metadata. Doc counts are placeholders — pass
#: ``--with-actual-counts`` to populate from live OpenSearch.
KNOWN_SOURCES: list[dict[str, object]] = [
    {
        "name": "global-workflow-rst",
        "source_type": SourceType.ON_DISK_SUBMODULE,
        "collection_target": "global-workflow-docs-v8-0-0",
        "embedding_profile": "titan1024",
        "enabled": True,
        "description": "Local .rst documentation from the global-workflow submodule",
        "ingestion_script": "scripts/ingest_local_docs_v4.py",
        "doc_count": 1759,
        "type_fields": {
            "local_path": "supported_repos/global-workflow/docs",
            "file_patterns": ["**/*.rst"],
            "parser": "rst_sphinx",
        },
    },
    {
        "name": "fortran-code-context",
        "source_type": SourceType.CODE_PARSE,
        "collection_target": "code-with-context-v8-0-0",
        "embedding_profile": "titan1024",
        "enabled": True,
        "description": "Fortran subroutines/functions/programs with surrounding context",
        "ingestion_script": "scripts/ingest_code_v8.py",
        "doc_count": 77613,
        "type_fields": {
            "root_path": "supported_repos/global-workflow/sorc",
            "languages": ["fortran"],
            "chunk_strategy": "function_boundary",
        },
    },
    {
        "name": "shell-code-context",
        "source_type": SourceType.CODE_PARSE,
        "collection_target": "code-with-context-v8-0-0",
        "embedding_profile": "titan1024",
        "enabled": True,
        "description": "Shell scripts (j-jobs, ush, ex* drivers) with execution context",
        "ingestion_script": "scripts/ingest_shell_graph_v8.py",
        "doc_count": 0,
        "type_fields": {
            "root_path": "supported_repos/global-workflow",
            "languages": ["shell"],
            "chunk_strategy": "function_boundary",
        },
    },
    {
        "name": "python-code-context",
        "source_type": SourceType.CODE_PARSE,
        "collection_target": "code-with-context-v8-0-0",
        "embedding_profile": "titan1024",
        "enabled": True,
        "description": "Python modules / utilities ingestible from the global-workflow tree",
        "ingestion_script": "scripts/ingest_python_graph.py",
        "doc_count": 0,
        "type_fields": {
            "root_path": "supported_repos/global-workflow/ush",
            "languages": ["python"],
            "chunk_strategy": "function_boundary",
        },
    },
    {
        "name": "rocoto-config",
        "source_type": SourceType.CONFIG_PARSE,
        "collection_target": "code-with-context-v8-0-0",
        "embedding_profile": "titan1024",
        "enabled": True,
        "description": "Rocoto XML workflow definitions (tasks, metatasks, dependencies)",
        "ingestion_script": "scripts/ingest_rocoto_xml.py",
        "doc_count": 0,
        "type_fields": {
            "config_root": "supported_repos/global-workflow/parm",
            "file_patterns": ["**/*.xml"],
            "parser": "rocoto_xml",
        },
    },
    {
        "name": "expdir-configs",
        "source_type": SourceType.CONFIG_PARSE,
        "collection_target": "code-with-context-v8-0-0",
        "embedding_profile": "titan1024",
        "enabled": True,
        "description": "Experiment-directory bash configs (config.* files)",
        "ingestion_script": "scripts/ingest_expdir_configs.py",
        "doc_count": 0,
        "type_fields": {
            "config_root": "supported_repos/global-workflow/parm/config",
            "file_patterns": ["config.*"],
            "parser": "bash_kv",
        },
    },
    {
        "name": "ee2-standards",
        "source_type": SourceType.STANDARDS,
        "collection_target": "ee2-standards-v5-0-0-enhanced",
        "embedding_profile": "titan1024",
        "enabled": True,
        "description": "NOAA EE2 (NCO production) coding standards",
        "ingestion_script": "scripts/ingest_ee2_v7.py",
        "doc_count": 0,
        "type_fields": {
            "standards_source": "supported_repos/nws-hpc-standards",
            "document_count": 0,
        },
    },
    {
        "name": "community-summaries",
        "source_type": SourceType.COMMUNITY_SUMMARY,
        "collection_target": "community-summaries",
        "embedding_profile": "titan1024",
        "enabled": True,
        "description": "Graph-derived community summaries (Leiden algorithm)",
        "ingestion_script": "scripts/import_llm_summaries.js",
        "doc_count": 0,
        "type_fields": {
            "graph_source": "neptune",
            "community_algorithm": "leiden",
        },
    },
    {
        "name": "jjob-docs",
        "source_type": SourceType.JJOB_DOCS,
        "collection_target": "jjobs-v8-0-0",
        "embedding_profile": "titan1024",
        "enabled": True,
        "description": "J-Job script documentation extracted from jobs/ headers",
        "ingestion_script": "scripts/ingest_jjobs_v8.py",
        "doc_count": 0,
        "type_fields": {
            "job_script_root": "supported_repos/global-workflow/jobs",
            "documentation_format": "header_block",
        },
    },
]


# ── builders ─────────────────────────────────────────────────────────


def _load_legacy_url_sources() -> list[SourceEntry]:
    """Migrate ``documentation_sources.json`` entries to url_crawl SourceEntries."""
    if not LEGACY_URL_MANIFEST.is_file():
        log.warning(
            "legacy URL manifest not found at %s — emitting no url_crawl sources",
            LEGACY_URL_MANIFEST,
        )
        return []

    with LEGACY_URL_MANIFEST.open("r", encoding="utf-8") as fh:
        legacy = json.load(fh)

    # Names that collide with curated non-URL entries; rename the URL
    # variant with the ``-url`` suffix so both can coexist. Currently
    # only ee2-standards collides — the legacy URL entry is explicitly
    # disabled with a description pointing to the RST-based local
    # ingestion path, so the RST entry deserves the canonical name.
    URL_NAME_OVERRIDES = {"ee2-standards": "ee2-standards-url"}

    out: list[SourceEntry] = []
    for entry in legacy.get("sources") or []:
        legacy_name = entry["name"]
        out.append(
            SourceEntry(
                name=URL_NAME_OVERRIDES.get(legacy_name, legacy_name),
                source_type=SourceType.URL_CRAWL,
                collection_target="global-workflow-docs-v8-0-0",
                embedding_profile="titan1024",
                enabled=bool(entry.get("enabled", True)),
                description=entry.get("description") or "",
                last_ingested=entry.get("last_ingested"),
                ingestion_script="scripts/ingest_documentation_v8.py",
                doc_count=int(entry.get("doc_count") or 0),
                type_fields={
                    "url": entry["url"],
                    "crawl_type": entry.get("type", "readthedocs"),
                    "max_pages": int(entry.get("max_pages") or 0),
                    "tier": entry.get("tier", "tier3_optional"),
                    **(
                        {"priority": entry["priority"]}
                        if "priority" in entry
                        else {}
                    ),
                    **(
                        {"local_path": entry["local_path"]}
                        if "local_path" in entry
                        else {}
                    ),
                    **(
                        {"path_prefix": entry["path_prefix"]}
                        if "path_prefix" in entry
                        else {}
                    ),
                },
            )
        )
    log.info("loaded %d url_crawl sources from legacy manifest", len(out))
    return out


def _build_known_sources() -> list[SourceEntry]:
    """Materialize the curated KNOWN_SOURCES list as SourceEntry instances."""
    out: list[SourceEntry] = []
    for spec in KNOWN_SOURCES:
        out.append(
            SourceEntry(
                name=str(spec["name"]),
                source_type=spec["source_type"],  # type: ignore[arg-type]
                collection_target=str(spec["collection_target"]),
                embedding_profile=str(spec["embedding_profile"]),
                enabled=bool(spec["enabled"]),
                description=str(spec["description"]),
                last_ingested=None,
                ingestion_script=str(spec.get("ingestion_script") or ""),
                doc_count=int(spec.get("doc_count") or 0),
                type_fields=dict(spec.get("type_fields") or {}),
            )
        )
    return out


async def _populate_actual_counts(
    sources: list[SourceEntry],
) -> list[SourceEntry]:
    """Best-effort: query OpenSearch and populate ``doc_count`` per source.

    Uses two strategies:
    1. For indices with a single source → assign the full index doc count.
    2. For shared indices (multiple sources target the same index) →
       run a ``metadata.source`` terms aggregation to get per-source counts.

    Skips silently when the data layer fails to initialize (no creds,
    no network) — the script must keep working offline.
    """
    try:
        from src.config import load_config
        from src.data.backend_selector import create_data_access
    except Exception as exc:
        log.warning("could not import data layer: %s — skipping actual counts", exc)
        return sources

    try:
        config = load_config()
        data = await create_data_access(config)
    except Exception as exc:
        log.warning(
            "data-access init failed: %s — skipping actual counts", exc
        )
        return sources

    try:
        health = await data.vector_db.health_check(deep=True)
    except Exception as exc:
        log.warning("health_check failed: %s — skipping actual counts", exc)
        return sources

    indices_detail = health.get("indices_detail") or {}
    if not isinstance(indices_detail, dict):
        return sources

    from src.config.aws_config import resolve_index

    # Build a map of index_name → list of source entries targeting it
    index_to_sources: dict[str, list[int]] = {}
    source_indices: list[str | None] = []
    for i, entry in enumerate(sources):
        try:
            index_name = resolve_index(
                entry.collection_target, entry.embedding_profile
            )
        except Exception:
            index_name = None
        source_indices.append(index_name)
        if index_name and index_name in indices_detail:
            index_to_sources.setdefault(index_name, []).append(i)

    # For shared indices, query per-source breakdown via aggregation
    per_source_counts: dict[str, dict[str, int]] = {}
    per_language_counts: dict[str, dict[str, int]] = {}
    for index_name, source_idxs in index_to_sources.items():
        if len(source_idxs) <= 1:
            continue
        # This index has multiple sources — run aggregation
        try:
            raw_client = data.vector_db._raw_client()
            import asyncio
            agg_body = {
                "size": 0,
                "aggs": {
                    "sources": {
                        "terms": {"field": "metadata.source.keyword", "size": 200}
                    }
                },
            }
            resp = await asyncio.to_thread(
                raw_client.search, index=index_name, body=agg_body
            )
            buckets = resp.get("aggregations", {}).get("sources", {}).get("buckets", [])
            per_source_counts[index_name] = {
                b["key"]: b["doc_count"] for b in buckets
            }
            log.info(
                "aggregation for %s: %d sources, %d total docs",
                index_name,
                len(buckets),
                sum(b["doc_count"] for b in buckets),
            )
        except Exception as exc:
            log.warning("aggregation for %s failed: %s", index_name, exc)

        # Also run a language aggregation for code_parse sources
        try:
            lang_body = {
                "size": 0,
                "aggs": {
                    "languages": {
                        "terms": {"field": "metadata.language.keyword", "size": 20}
                    }
                },
            }
            resp = await asyncio.to_thread(
                raw_client.search, index=index_name, body=lang_body
            )
            buckets = resp.get("aggregations", {}).get("languages", {}).get("buckets", [])
            if buckets:
                per_language_counts[index_name] = {
                    b["key"]: b["doc_count"] for b in buckets
                }
                log.info(
                    "language aggregation for %s: %s",
                    index_name,
                    {b["key"]: b["doc_count"] for b in buckets},
                )
        except Exception as exc:
            log.debug("language aggregation for %s failed: %s", index_name, exc)

    # Now assign counts
    new_sources: list[SourceEntry] = []
    for i, entry in enumerate(sources):
        index_name = source_indices[i]
        if not index_name or index_name not in indices_detail:
            new_sources.append(entry)
            continue

        # Determine the doc_count for this source
        doc_count = 0
        source_idxs = index_to_sources.get(index_name, [])

        if len(source_idxs) == 1:
            # Sole owner of this index — gets the full count
            doc_count = int(indices_detail[index_name])
        elif index_name in per_source_counts:
            # Shared index — look up by source name in the aggregation
            agg = per_source_counts[index_name]
            doc_count = agg.get(entry.name, 0)
            # For code_parse sources, fall back to language-based count
            if doc_count == 0 and entry.source_type.value == "code_parse":
                lang_agg = per_language_counts.get(index_name, {})
                languages = entry.type_fields.get("languages", [])
                for lang in languages:
                    if lang in lang_agg:
                        doc_count = lang_agg[lang]
                        break
            # For config_parse sources, try phase40_* source names
            if doc_count == 0 and entry.source_type.value == "config_parse":
                agg = per_source_counts.get(index_name, {})
                # Map manifest names to actual metadata.source values
                config_source_map = {
                    "expdir-configs": "phase40_expdir_ingestion",
                    "rocoto-config": "phase40_config_ingestion",
                }
                mapped_name = config_source_map.get(entry.name)
                if mapped_name and mapped_name in agg:
                    doc_count = agg[mapped_name]
        else:
            # Shared index but aggregation failed — leave at 0
            pass

        if doc_count > 0 or entry.doc_count == 0:
            replacement = SourceEntry(
                name=entry.name,
                source_type=entry.source_type,
                collection_target=entry.collection_target,
                embedding_profile=entry.embedding_profile,
                enabled=entry.enabled,
                description=entry.description,
                last_ingested=entry.last_ingested,
                ingestion_script=entry.ingestion_script,
                doc_count=doc_count if doc_count > 0 else entry.doc_count,
                type_fields=dict(entry.type_fields),
            )
            new_sources.append(replacement)
        else:
            new_sources.append(entry)

    return new_sources


def build_manifest(version: str = "9.0.0") -> UnifiedManifest:
    """Produce a manifest combining legacy URL sources + known non-URL sources."""
    sources: list[SourceEntry] = []
    sources.extend(_load_legacy_url_sources())
    sources.extend(_build_known_sources())

    return UnifiedManifest(
        version=version,
        description=(
            "Unified ingest manifest — all knowledge base sources "
            "(url_crawl, on_disk_submodule, code_parse, config_parse, "
            "standards, community_summary, jjob_docs)"
        ),
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        sources=sources,
    )


# ── CLI ──────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="generate_unified_manifest",
        description=(
            "Bootstrap unified_manifest.json from the current source tree. "
            "Writes a valid manifest covering all 7 source types based on "
            "the legacy documentation_sources.json plus a curated list of "
            "non-URL sources."
        ),
    )
    p.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output path (default: {DEFAULT_OUTPUT})",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print manifest to stdout instead of writing to disk",
    )
    p.add_argument(
        "--with-actual-counts",
        action="store_true",
        help=(
            "Query OpenSearch (using DB_BACKEND/AWS env vars) and "
            "populate doc_count fields with actual index document counts"
        ),
    )
    p.add_argument(
        "--version",
        default="9.0.0",
        help="Manifest version string (default: 9.0.0)",
    )
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(levelname)s %(name)s — %(message)s",
    )

    manifest = build_manifest(version=args.version)

    if args.with_actual_counts:
        manifest = UnifiedManifest(
            version=manifest.version,
            description=manifest.description,
            generated_at=manifest.generated_at,
            sources=asyncio.run(
                _populate_actual_counts(list(manifest.sources))
            ),
        )

    payload = manifest.to_dict()

    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")
    log.info(
        "[OK] wrote %s (sources=%d, enabled=%d, version=%s)",
        args.output,
        len(manifest.sources),
        sum(1 for s in manifest.sources if s.enabled),
        manifest.version,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
