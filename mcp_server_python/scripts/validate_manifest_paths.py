#!/usr/bin/env python3
"""Validate manifest local_path declarations against the worktree + .gitmodules.

disk-priority-ingest, Requirement 4.4/4.5.

Cheap, offline check (no network, no embedding): for the given tenant it probes
every documentation source that declares a ``local_path`` and prints a table of
source / declared path / verdict / reason. Exits non-zero if any source is a
``manifest_defect`` — a declared path that cannot resolve and is not a
registered submodule (the ``gsi-user-guide`` -> ``sorc/gsi.fd`` case).

path_absent / path_empty / below_min_files / submodule_off_pin / worktree_dirty
are reported but do NOT fail the run: those are legitimate disk states the
disk-priority resolver handles by falling through to ``needs_crawl``.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1]))

from _ingest_common import resolve_worktree_root
from _ingest_sources import (
    DISPOSITION_DISK,
    REASON_MANIFEST_DEFECT,
    load_doc_sources,
    probe_local,
)

# Repo root (contains supported_repos/) for the transitional repo-relative
# local_path fallback used by probe_local.
_REPO_ROOT = Path(__file__).resolve().parents[2]

_DEFAULT_MANIFEST = Path(__file__).parents[1] / "src" / "config" / "unified_manifest.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate manifest local_path declarations.")
    parser.add_argument("--tenant", default=None,
                        help="Tenant ID from tenants.yaml. None -> catalog default (gw).")
    parser.add_argument("--manifest", default=str(_DEFAULT_MANIFEST),
                        help="Path to the unified manifest JSON.")
    args = parser.parse_args()

    catalog_path = os.environ.get(
        "MCP_TENANT_CATALOG_PATH",
        str(Path(__file__).parents[1] / "src" / "config" / "tenants.yaml"),
    )
    from src.config.tenants import load_catalog

    catalog = load_catalog(catalog_path)
    tid = args.tenant or catalog.defaults.tenant_id
    tenant = catalog.by_id(tid)
    if tenant is None:
        print(f"[ERROR] unknown tenant_id={tid!r}; known: {catalog.tenant_ids}",
              file=sys.stderr)
        return 2

    worktree_root = resolve_worktree_root(tenant)
    sources = load_doc_sources(args.manifest)
    disk_sources = [s for s in sources if s.local_path is not None]

    print(f"# Manifest path validation — tenant={tenant.tenant_id} "
          f"worktree_root={worktree_root}")
    print(f"# {len(disk_sources)} source(s) declare a local_path "
          f"(of {len(sources)} documentation sources)")
    print()
    header = f"{'source':24s} {'verdict':12s} {'reason':18s} declared_path"
    print(header)
    print("-" * len(header))

    defects: list[str] = []
    for source in disk_sources:
        probe = probe_local(source, worktree_root, repo_root=_REPO_ROOT)
        verdict = DISPOSITION_DISK if probe.usable else "needs_crawl"
        if probe.reason == REASON_MANIFEST_DEFECT:
            defects.append(source.name)
        print(f"{source.name:24s} {verdict:12s} {probe.reason:18s} {source.local_path}")

    print()
    if defects:
        print(f"[ERROR] {len(defects)} manifest defect(s): {', '.join(defects)}",
              file=sys.stderr)
        print("  These declared paths do not resolve and are not registered "
              "submodules. Fix the manifest local_path.", file=sys.stderr)
        return 1

    print(f"[OK] no manifest defects for tenant {tenant.tenant_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
