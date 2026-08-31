#!/usr/bin/env python3
"""neo4j_index_rebuild.py — Drop and rebuild Neo4j indexes and constraints.

Manages the Index_Rebuild_Set for the COTS full re-ingest. Provides four
subcommands:

  list     Show the current Index_Rebuild_Set (definition + live state).
  drop     Drop all indexes/constraints in the set, with a pre-drop snapshot.
  create   Recreate the set for the target version (parametrised by tenant
           label prefixes from tenants.yaml).
  restore  Re-apply a previously captured snapshot (rollback).

Guards:
  * ``drop`` requires ``--i-mean-it Target_Version=<ver>`` confirmation token.
  * ``drop`` writes a JSON snapshot (re-applicable by ``restore``) before any
    destructive action.
  * ``create`` exits non-zero if the post-create state diverges from the target.

Connection:
  Reads NEO4J_URI (default bolt://localhost:7687) and NEO4J_PASSWORD (default
  gfsworkflow2025) from environment — same contract as the sibling ingesters.

Spec: .kiro/specs/mpnet768-tenant-reingest-aug2026/ (Task 3).
Design: Delta 3 — Neo4j drop-and-rebuild of indexes.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Path setup (mirrors sibling scripts)
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).resolve().parent
_SERVER_ROOT = _SCRIPT_DIR.parent
_REPO_ROOT = _SERVER_ROOT.parent
for _p in (str(_SCRIPT_DIR), str(_SERVER_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_DEFAULT_CATALOG = _SERVER_ROOT / "src" / "config" / "tenants.yaml"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "gfsworkflow2025")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")


def _utcnow() -> str:
    """UTC timestamp string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(msg: str) -> None:
    print(f"[{_utcnow()}] {msg}")


# ---------------------------------------------------------------------------
# Index_Rebuild_Set — the canonical set of indexes and constraints.
# ---------------------------------------------------------------------------

# Each entry is a dict with:
#   name:       logical name (used for matching and snapshot keys)
#   type:       "uniqueness" | "text" | "range"
#   label:      node label (WITHOUT tenant prefix — prefix is applied at runtime)
#   property:   property key
#   for_tenant: bool — if True, one index per tenant prefix is created;
#               if False, only the unprefixed (gw baseline) version is created.

INDEX_REBUILD_SET: list[dict[str, Any]] = [
    {
        "name": "file_path_uniq",
        "type": "uniqueness",
        "label": "File",
        "property": "path",
        "for_tenant": True,
    },
    {
        "name": "function_qname_uniq",
        "type": "uniqueness",
        "label": "Function",
        "property": "qname",
        "for_tenant": True,
    },
    {
        "name": "function_name_text",
        "type": "text",
        "label": "Function",
        "property": "name",
        "for_tenant": True,
    },
    {
        "name": "fortran_sub_name_text",
        "type": "text",
        "label": "FortranSubroutine",
        "property": "name",
        "for_tenant": True,
    },
    {
        "name": "fortran_fn_name_text",
        "type": "text",
        "label": "FortranFunction",
        "property": "name",
        "for_tenant": True,
    },
    {
        "name": "python_fn_name_text",
        "type": "text",
        "label": "PythonFunction",
        "property": "name",
        "for_tenant": True,
    },
    {
        "name": "shell_script_path_uniq",
        "type": "uniqueness",
        "label": "ShellScript",
        "property": "path",
        "for_tenant": True,
    },
]


def _load_tenant_prefixes(catalog_path: Path) -> list[str]:
    """Load label_prefix values from tenants.yaml.

    Returns a list including the empty string (for the unprefixed gw baseline).
    """
    with open(catalog_path) as f:
        catalog = yaml.safe_load(f)
    prefixes: list[str] = []
    for t in catalog.get("tenants", []):
        prefixes.append(t.get("label_prefix", ""))
    # Ensure the unprefixed baseline is present exactly once.
    if "" not in prefixes:
        prefixes.insert(0, "")
    return prefixes


def _expand_index_set(
    prefixes: list[str],
) -> list[dict[str, Any]]:
    """Expand the Index_Rebuild_Set across tenant prefixes.

    Returns a list of concrete index definitions with resolved label names
    and concrete index names.
    """
    expanded: list[dict[str, Any]] = []
    for entry in INDEX_REBUILD_SET:
        if entry["for_tenant"]:
            for prefix in prefixes:
                concrete_label = f"{prefix}{entry['label']}"
                # Construct a unique index name for this prefix+entry
                prefix_tag = prefix.rstrip("_").lower() if prefix else "base"
                concrete_name = f"{entry['name']}_{prefix_tag}"
                expanded.append({
                    "name": concrete_name,
                    "logical_name": entry["name"],
                    "type": entry["type"],
                    "label": concrete_label,
                    "property": entry["property"],
                    "prefix": prefix,
                })
        else:
            expanded.append({
                "name": entry["name"],
                "logical_name": entry["name"],
                "type": entry["type"],
                "label": entry["label"],
                "property": entry["property"],
                "prefix": "",
            })
    return expanded


def _cypher_create(entry: dict[str, Any]) -> str:
    """Generate the CREATE INDEX/CONSTRAINT cypher for one entry."""
    idx_name = entry["name"]
    label = entry["label"]
    prop = entry["property"]
    idx_type = entry["type"]

    if idx_type == "uniqueness":
        return (
            f"CREATE CONSTRAINT {idx_name} IF NOT EXISTS "
            f"FOR (n:`{label}`) REQUIRE n.{prop} IS UNIQUE"
        )
    elif idx_type == "text":
        return (
            f"CREATE TEXT INDEX {idx_name} IF NOT EXISTS "
            f"FOR (n:`{label}`) ON (n.{prop})"
        )
    elif idx_type == "range":
        return (
            f"CREATE RANGE INDEX {idx_name} IF NOT EXISTS "
            f"FOR (n:`{label}`) ON (n.{prop})"
        )
    else:
        raise ValueError(f"Unknown index type: {idx_type}")


def _cypher_drop(entry: dict[str, Any]) -> str:
    """Generate the DROP INDEX/CONSTRAINT cypher for one entry."""
    idx_name = entry["name"]
    idx_type = entry["type"]

    if idx_type == "uniqueness":
        return f"DROP CONSTRAINT {idx_name} IF EXISTS"
    else:
        return f"DROP INDEX {idx_name} IF EXISTS"


# ---------------------------------------------------------------------------
# Neo4j driver helpers
# ---------------------------------------------------------------------------


def _get_driver(dry_run: bool = False):
    """Create a neo4j driver. Returns None in dry-run mode."""
    if dry_run:
        return None
    try:
        from neo4j import GraphDatabase
    except ImportError:
        _log("[ERROR] neo4j Python driver not installed. "
             "Install with: pip install neo4j")
        sys.exit(1)
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        driver.verify_connectivity()
    except Exception as exc:
        _log(f"[ERROR] Cannot connect to Neo4j at {NEO4J_URI}: {exc}")
        sys.exit(1)
    return driver


def _run_cypher(driver, cypher: str) -> list[dict]:
    """Execute a single cypher statement and return records as dicts."""
    with driver.session() as session:
        result = session.run(cypher)
        return [record.data() for record in result]


def _get_live_indexes(driver) -> list[dict[str, Any]]:
    """Fetch current indexes from SHOW INDEXES."""
    records = _run_cypher(driver, "SHOW INDEXES")
    return records


def _get_live_constraints(driver) -> list[dict[str, Any]]:
    """Fetch current constraints from SHOW CONSTRAINTS."""
    records = _run_cypher(driver, "SHOW CONSTRAINTS")
    return records


# ---------------------------------------------------------------------------
# Snapshot (pre-drop schema preservation)
# ---------------------------------------------------------------------------


def _write_snapshot(
    snapshot_path: Path,
    *,
    indexes: list[dict[str, Any]],
    constraints: list[dict[str, Any]],
    target_version: str,
    dropped_entries: list[dict[str, Any]],
) -> None:
    """Write a JSON snapshot of the pre-drop schema for rollback."""
    snapshot = {
        "schema_version": 1,
        "target_version": target_version,
        "captured_at": _utcnow(),
        "indexes": indexes,
        "constraints": constraints,
        "dropped_entries": dropped_entries,
    }
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(snapshot_path.parent), suffix=".tmp"
    )
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(snapshot, f, indent=2, default=str)
        os.replace(tmp_path, str(snapshot_path))
    except Exception:
        os.unlink(tmp_path)
        raise
    _log(f"[OK] Snapshot written to {snapshot_path}")


def _load_snapshot(snapshot_path: Path) -> dict[str, Any]:
    """Load a snapshot from disk."""
    with open(snapshot_path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_list(args: argparse.Namespace) -> int:
    """List the Index_Rebuild_Set with live state if available."""
    prefixes = _load_tenant_prefixes(Path(args.catalog))
    expanded = _expand_index_set(prefixes)

    _log(f"Index_Rebuild_Set: {len(INDEX_REBUILD_SET)} templates "
         f"x {len(prefixes)} prefixes = {len(expanded)} concrete entries")
    _log(f"Tenant prefixes: {prefixes}")
    _log("")

    # If we can connect, show live state
    driver = None
    live_index_names: set[str] = set()
    live_constraint_names: set[str] = set()
    if not args.dry_run:
        try:
            driver = _get_driver(dry_run=False)
            live_indexes = _get_live_indexes(driver)
            live_constraints = _get_live_constraints(driver)
            live_index_names = {r.get("name", "") for r in live_indexes}
            live_constraint_names = {r.get("name", "") for r in live_constraints}
        except SystemExit:
            _log("[WARN] Cannot connect to Neo4j; showing definitions only")

    for entry in expanded:
        live_status = ""
        if driver is not None:
            if entry["type"] == "uniqueness":
                live_status = " [LIVE]" if entry["name"] in live_constraint_names else " [ABSENT]"
            else:
                live_status = " [LIVE]" if entry["name"] in live_index_names else " [ABSENT]"

        print(f"  {entry['name']:50s}  {entry['type']:12s}  "
              f":{entry['label']}.{entry['property']}{live_status}")

    if driver:
        driver.close()
    return 0


def cmd_drop(args: argparse.Namespace) -> int:
    """Drop all indexes/constraints in the Index_Rebuild_Set."""
    # Validate confirmation token (Requirement 8.1)
    if not args.i_mean_it:
        _log("[ERROR] --i-mean-it Target_Version=<ver> is required for drop")
        return 1

    # Parse the confirmation token
    token = args.i_mean_it
    if not token.startswith("Target_Version="):
        _log(f"[ERROR] Confirmation token must be 'Target_Version=<ver>', got: {token}")
        return 1
    confirmed_version = token.split("=", 1)[1]

    # Validate snapshot path
    snapshot_path = Path(args.snapshot)

    prefixes = _load_tenant_prefixes(Path(args.catalog))
    expanded = _expand_index_set(prefixes)

    if args.dry_run:
        _log(f"[DRY-RUN] Would drop {len(expanded)} indexes/constraints "
             f"for Target_Version={confirmed_version}")
        _log(f"[DRY-RUN] Would write snapshot to {snapshot_path}")
        for entry in expanded:
            print(f"  [DRY-RUN] {_cypher_drop(entry)}")
        return 0

    driver = _get_driver(dry_run=False)

    # Capture pre-drop state
    _log("Capturing pre-drop schema state...")
    live_indexes = _get_live_indexes(driver)
    live_constraints = _get_live_constraints(driver)

    # Write snapshot before any drops
    _write_snapshot(
        snapshot_path,
        indexes=live_indexes,
        constraints=live_constraints,
        target_version=confirmed_version,
        dropped_entries=expanded,
    )

    # Drop each entry
    dropped = 0
    errors = 0
    for entry in expanded:
        cypher = _cypher_drop(entry)
        try:
            _run_cypher(driver, cypher)
            dropped += 1
            _log(f"[OK] Dropped: {entry['name']}")
        except Exception as exc:
            # IF EXISTS means most errors are unexpected
            _log(f"[ERROR] Failed to drop {entry['name']}: {exc}")
            errors += 1

    driver.close()
    _log(f"Drop complete: {dropped} dropped, {errors} errors")
    return 1 if errors > 0 else 0


def cmd_create(args: argparse.Namespace) -> int:
    """Recreate the Index_Rebuild_Set for the target version."""
    target_version = args.target_version
    prefixes = _load_tenant_prefixes(Path(args.catalog))
    expanded = _expand_index_set(prefixes)

    if args.dry_run:
        _log(f"[DRY-RUN] Would create {len(expanded)} indexes/constraints "
             f"for target-version={target_version}")
        for entry in expanded:
            print(f"  [DRY-RUN] {_cypher_create(entry)}")
        return 0

    driver = _get_driver(dry_run=False)

    # Create each entry
    created = 0
    errors = 0
    for entry in expanded:
        cypher = _cypher_create(entry)
        try:
            _run_cypher(driver, cypher)
            created += 1
            _log(f"[OK] Created: {entry['name']}")
        except Exception as exc:
            _log(f"[ERROR] Failed to create {entry['name']}: {exc}")
            errors += 1

    # Verify: check that all entries are now live
    _log("Verifying post-create state...")
    live_indexes = _get_live_indexes(driver)
    live_constraints = _get_live_constraints(driver)
    live_index_names = {r.get("name", "") for r in live_indexes}
    live_constraint_names = {r.get("name", "") for r in live_constraints}

    missing: list[str] = []
    for entry in expanded:
        if entry["type"] == "uniqueness":
            if entry["name"] not in live_constraint_names:
                missing.append(entry["name"])
        else:
            if entry["name"] not in live_index_names:
                missing.append(entry["name"])

    if missing:
        _log(f"[ERROR] {len(missing)} indexes/constraints not confirmed live:")
        for m in missing:
            _log(f"  - {m}")
        driver.close()
        return 1

    driver.close()
    _log(f"Create complete: {created} created, {errors} errors, "
         f"all {len(expanded)} confirmed live")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    """Restore indexes/constraints from a pre-drop snapshot."""
    snapshot_path = Path(args.snapshot)
    if not snapshot_path.exists():
        _log(f"[ERROR] Snapshot file not found: {snapshot_path}")
        return 1

    snapshot = _load_snapshot(snapshot_path)
    dropped_entries = snapshot.get("dropped_entries", [])

    if not dropped_entries:
        _log("[WARN] Snapshot contains no dropped_entries; nothing to restore")
        return 0

    if args.dry_run:
        _log(f"[DRY-RUN] Would restore {len(dropped_entries)} "
             f"indexes/constraints from {snapshot_path}")
        for entry in dropped_entries:
            print(f"  [DRY-RUN] {_cypher_create(entry)}")
        return 0

    driver = _get_driver(dry_run=False)

    restored = 0
    errors = 0
    for entry in dropped_entries:
        cypher = _cypher_create(entry)
        try:
            _run_cypher(driver, cypher)
            restored += 1
            _log(f"[OK] Restored: {entry['name']}")
        except Exception as exc:
            _log(f"[ERROR] Failed to restore {entry['name']}: {exc}")
            errors += 1

    driver.close()
    _log(f"Restore complete: {restored} restored, {errors} errors")
    return 1 if errors > 0 else 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    # Common arguments shared across all subcommands via parents=.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--catalog", default=str(_DEFAULT_CATALOG),
        help="Path to tenants.yaml (default: %(default)s)",
    )
    common.add_argument(
        "--dry-run", action="store_true", default=False,
        help="Print the plan without executing.",
    )

    parser = argparse.ArgumentParser(
        description="Neo4j index and constraint management for the COTS re-ingest."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # list
    sub.add_parser("list", parents=[common],
                   help="Show the Index_Rebuild_Set with live state")

    # drop
    p_drop = sub.add_parser("drop", parents=[common],
                            help="Drop all indexes/constraints in the set")
    p_drop.add_argument(
        "--i-mean-it", type=str, required=True,
        help="Confirmation token: Target_Version=<ver>",
    )
    p_drop.add_argument(
        "--snapshot", type=str, required=True,
        help="Path to write the pre-drop JSON snapshot",
    )

    # create
    p_create = sub.add_parser("create", parents=[common],
                              help="Recreate the Index_Rebuild_Set")
    p_create.add_argument(
        "--target-version", type=str, required=True,
        help="Target version for the re-ingest (e.g. v9-0-0)",
    )

    # restore
    p_restore = sub.add_parser("restore", parents=[common],
                               help="Restore from a pre-drop snapshot")
    p_restore.add_argument(
        "--snapshot", type=str, required=True,
        help="Path to the snapshot JSON file",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "list":
        return cmd_list(args)
    elif args.command == "drop":
        return cmd_drop(args)
    elif args.command == "create":
        return cmd_create(args)
    elif args.command == "restore":
        return cmd_restore(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
