#!/usr/bin/env python3
"""reingest_state.py — State_Manager for the COTS full re-ingest Ralph loop.

The durable, atomic, single source of truth for a ``(tenant, stage)`` work
matrix. Pure state I/O — no ingestion, no network (Requirement 4.5) — so it is
unit-testable against a ``tmp_path`` state file.

State lives at ``<state-root>/.reingest_state/<collection_version>/state.json``
(gitignored). Every mutation is written atomically (temp file + ``os.replace``)
and mirrored to a human-readable ``PROGRESS.md`` alongside it (Requirement 3.3,
3.4).

Subcommands (Requirement 4.1)
-----------------------------
  init         Build/refresh the Work_Matrix (idempotent).
  next         Emit the single highest-priority actionable unit as JSON.
  start        Mark a unit running.
  done         Mark a unit done (+ merge metrics).
  fail         Record a failure (attempts++ -> failed, or -> blocked at cap;
               ``--requeue`` resets to pending without incrementing attempts).
  skip         Mark a unit skipped (source precondition unmet / not applicable).
  report       Rewrite PROGRESS.md and print a summary table.
  is-complete  Exit 0 iff every unit is terminal (done/skipped/blocked).

Spec: .kiro/specs/cots-reingest-ralph-loop/ (Task 1.2).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

# Resolve import roots so `src.config.tenants` and `_ingest_common` load whether
# invoked as a module or a bare script (mirrors the sibling v8 ingesters).
_SCRIPT_DIR = Path(__file__).resolve().parent            # mcp_server_python/scripts
_SERVER_ROOT = _SCRIPT_DIR.parent                        # mcp_server_python
_REPO_ROOT = _SERVER_ROOT.parent                         # repo root
for _p in (str(_SCRIPT_DIR), str(_SERVER_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1
GLOBAL_TENANT = "__global__"
TERMINAL_STATES = frozenset({"done", "skipped", "blocked"})
ACTIONABLE_STATES = frozenset({"pending", "failed"})

_DEFAULT_CATALOG = _SERVER_ROOT / "src" / "config" / "tenants.yaml"
_DEFAULT_STAGES = _SCRIPT_DIR / "reingest_stages.yaml"

# Kinds for which --mode / --collection-version are meaningful (ingest stages).
_INGEST_KINDS = frozenset({"vector", "dual", "graph"})


def _utcnow() -> str:
    """UTC timestamp, second precision, ``Z`` suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_text(text: str) -> str:
    """SHA-256 hex digest of a UTF-8 string (for catalog/stages drift)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Catalog + stage loading
# ---------------------------------------------------------------------------


def _load_stage_catalog(path: Path) -> dict[str, Any]:
    """Parse reingest_stages.yaml into ``{per_tenant, global, attempt_cap_default}``."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "per_tenant": list(raw.get("per_tenant_stages", [])),
        "global": list(raw.get("global_stages", [])),
        "attempt_cap_default": int(raw.get("attempt_cap_default", 3)),
    }


def _derive_mode(lifecycle: str, mode_override: str | None) -> str | None:
    """Mode for an ingest stage: override wins, else lifecycle-derived."""
    if mode_override:
        return mode_override
    from _ingest_common import derive_mode_from_lifecycle

    try:
        return derive_mode_from_lifecycle(lifecycle)
    except ValueError:
        # merged/stale/unknown lifecycle: leave mode unset; the operator must
        # supply --mode-override. The unit still enters the matrix.
        return None


def _stage_unit(
    *,
    stage: dict[str, Any],
    tenant: Any,
    mode_override: str | None,
) -> dict[str, Any]:
    """Build one Reingest_Unit from a stage template + a tenant (or global)."""
    kind = stage["kind"]
    is_global = tenant is None
    tenant_id = GLOBAL_TENANT if is_global else tenant.tenant_id
    lifecycle = "" if is_global else tenant.lifecycle
    mode = (
        _derive_mode(lifecycle, mode_override)
        if kind in _INGEST_KINDS
        else None
    )
    unit: dict[str, Any] = {
        "id": f"{tenant_id}:{stage['name']}",
        "tenant_id": tenant_id,
        "scope": "global" if is_global else "tenant",
        "branch": "" if is_global else tenant.branch,
        "workflow_subdir": "" if is_global else tenant.workflow_subdir,
        "label_prefix": "" if is_global else tenant.label_prefix,
        "index_prefix": "" if is_global else tenant.index_prefix,
        "lifecycle": lifecycle,
        "stage": stage["name"],
        "order": int(stage["order"]),
        "kind": kind,
        "script": stage.get("script"),
        "mode": mode,
        "depends_on": list(stage.get("depends_on", [])),
        "destructive": bool(stage.get("destructive", False)),
        "optional": bool(stage.get("optional", False)),
        "probe": stage.get("probe", "none"),
        "source_precondition": stage.get("source_precondition"),
        "status": "pending",
        "attempts": 0,
        "last_error": None,
        "skip_reason": None,
        "adaptations": [],
        "metrics": {},
        "started_at": None,
        "ended_at": None,
    }
    return unit


def _build_matrix(
    *,
    catalog: Any,
    stages: dict[str, Any],
    mode_override: str | None,
) -> list[dict[str, Any]]:
    """Full Work_Matrix, scope-aware (rag-data-plane-gap-closure R2).

    Each stage declares ``scope: shared | tenant`` (reingest_stages.yaml).
    A ``shared`` stage emits exactly ONE unit (``tenant_id="__global__"``,
    no tenant coupling); a ``tenant`` stage emits one unit per catalog
    tenant. Stages in ``global_stages`` default to ``shared`` and stages
    in ``per_tenant_stages`` default to ``tenant`` when the field is
    absent (backward-compat with a pre-scope stages file).

    For the current 5-tenant catalog this yields 55 tenant-scoped + 3
    shared (documentation, ee2_standards, community_summaries) = 58 units
    (down from 62 — documentation collapses 5 → 1).
    """
    units: list[dict[str, Any]] = []

    def _emit(stage: dict[str, Any], default_scope: str) -> None:
        scope = stage.get("scope", default_scope)
        if scope == "shared":
            units.append(
                _stage_unit(stage=stage, tenant=None, mode_override=mode_override)
            )
        else:
            for tenant in catalog.tenants:
                units.append(
                    _stage_unit(
                        stage=stage, tenant=tenant, mode_override=mode_override
                    )
                )

    for stage in stages["per_tenant"]:
        _emit(stage, "tenant")
    for stage in stages["global"]:
        _emit(stage, "shared")
    return units


# ---------------------------------------------------------------------------
# State store (atomic I/O + PROGRESS.md mirror)
# ---------------------------------------------------------------------------


class StateStore:
    """Load/mutate/persist the state.json for one Collection_Version."""

    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.state_path = state_dir / "state.json"
        self.progress_path = state_dir / "PROGRESS.md"
        self._data: dict[str, Any] | None = None

    # -- persistence ------------------------------------------------------

    def exists(self) -> bool:
        return self.state_path.is_file()

    def load(self) -> dict[str, Any]:
        if self._data is None:
            self._data = json.loads(self.state_path.read_text(encoding="utf-8"))
        return self._data

    def _atomic_write(self) -> None:
        """Write state.json atomically (temp file in same dir + os.replace)."""
        assert self._data is not None
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._data["updated_at"] = _utcnow()
        fd, tmp = tempfile.mkstemp(
            dir=str(self.state_dir), prefix=".state.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2, sort_keys=False)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.state_path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def save(self) -> None:
        """Persist state + regenerate the PROGRESS.md mirror (Requirement 3.4)."""
        if self._data is None:
            self.load()
        self._atomic_write()
        self._write_progress()

    # -- unit helpers -----------------------------------------------------

    def units(self) -> list[dict[str, Any]]:
        return self.load()["units"]

    def by_id(self, unit_id: str) -> dict[str, Any] | None:
        return next((u for u in self.units() if u["id"] == unit_id), None)

    def _tenant_stage_status(self, tenant_id: str) -> dict[str, str]:
        """{stage_name: status} for one tenant — for depends_on gating."""
        return {
            u["stage"]: u["status"]
            for u in self.units()
            if u["tenant_id"] == tenant_id
        }

    def actionable(self) -> list[dict[str, Any]]:
        """Units eligible for `next`: status actionable, under cap, deps terminal."""
        cap = int(self.load()["attempt_cap"])
        out: list[dict[str, Any]] = []
        for u in self.units():
            if u["status"] not in ACTIONABLE_STATES:
                continue
            if u["attempts"] >= cap:
                continue
            deps = u.get("depends_on") or []
            if deps:
                sibling = self._tenant_stage_status(u["tenant_id"])
                if not all(sibling.get(d) in TERMINAL_STATES for d in deps):
                    continue
            out.append(u)
        return out

    def next_unit(self) -> dict[str, Any] | None:
        """Lowest ``(order, tenant_index)`` actionable unit, or None."""
        acts = self.actionable()
        if not acts:
            return None
        tenant_order = {
            tid: i for i, tid in enumerate(self.load().get("tenant_order", []))
        }
        return min(
            acts,
            key=lambda u: (u["order"], tenant_order.get(u["tenant_id"], 999)),
        )

    def is_complete(self) -> bool:
        return all(u["status"] in TERMINAL_STATES for u in self.units())

    # -- PROGRESS.md ------------------------------------------------------

    def _write_progress(self) -> None:
        data = self.load()
        units = data["units"]
        counts: dict[str, int] = {}
        for u in units:
            counts[u["status"]] = counts.get(u["status"], 0) + 1

        lines: list[str] = []
        lines.append(f"# COTS Re-Ingest Progress — {data['collection_version']}")
        lines.append("")
        lines.append(f"- Backend: `{data['backend']}` / embedding "
                     f"`{data['embedding_profile']}`")
        lines.append(f"- Attempt cap: {data['attempt_cap']}")
        lines.append(f"- Created: {data['created_at']}  |  "
                     f"Updated: {data['updated_at']}")
        total = len(units)
        done_like = sum(counts.get(s, 0) for s in TERMINAL_STATES)
        lines.append(f"- Units: {done_like}/{total} terminal  "
                     f"({', '.join(f'{k}={v}' for k, v in sorted(counts.items()))})")
        lines.append("")

        # Per-tenant grid (stage x status).
        by_tenant: dict[str, list[dict[str, Any]]] = {}
        for u in units:
            by_tenant.setdefault(u["tenant_id"], []).append(u)

        for tid in data.get("tenant_order", []) + [GLOBAL_TENANT]:
            tunits = by_tenant.get(tid)
            if not tunits:
                continue
            lines.append(f"## {tid}")
            lines.append("")
            lines.append("| stage | status | attempts | metrics/notes |")
            lines.append("|-------|--------|----------|---------------|")
            for u in sorted(tunits, key=lambda x: x["order"]):
                note = ""
                if u["status"] == "skipped" and u.get("skip_reason"):
                    note = f"skip: {u['skip_reason']}"
                elif u["status"] in ("failed", "blocked") and u.get("last_error"):
                    note = f"err: {str(u['last_error'])[:80]}"
                elif u.get("metrics"):
                    note = json.dumps(u["metrics"])[:80]
                lines.append(
                    f"| {u['stage']} | {u['status']} | {u['attempts']} | {note} |"
                )
            lines.append("")

        blocked = [u for u in units if u["status"] == "blocked"]
        if blocked:
            lines.append("## Blocked units (need a human)")
            lines.append("")
            for u in blocked:
                lines.append(f"- `{u['id']}` (attempts={u['attempts']}): "
                             f"{str(u.get('last_error'))[:160]}")
            lines.append("")

        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.progress_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------


def _state_dir(state_root: Path, collection_version: str) -> Path:
    return state_root / ".reingest_state" / collection_version


def cmd_init(args: argparse.Namespace) -> int:
    from src.config.tenants import load_catalog

    catalog_path = Path(args.catalog)
    stages_path = Path(args.stages)
    catalog = load_catalog(catalog_path)
    stages = _load_stage_catalog(stages_path)

    attempt_cap = (
        args.attempt_cap
        if args.attempt_cap is not None
        else stages["attempt_cap_default"]
    )

    store = StateStore(_state_dir(Path(args.state_root), args.collection_version))
    fresh_units = _build_matrix(
        catalog=catalog, stages=stages, mode_override=args.mode_override
    )
    catalog_sha = _sha256_text(catalog_path.read_text(encoding="utf-8"))
    stages_sha = _sha256_text(stages_path.read_text(encoding="utf-8"))

    if store.exists():
        # Idempotent re-init: preserve existing unit statuses, add missing units,
        # warn on catalog/stages drift (Requirement 2.3, 3.2).
        data = store.load()
        existing = {u["id"]: u for u in data["units"]}
        added = 0
        merged: list[dict[str, Any]] = []
        for u in fresh_units:
            if u["id"] in existing:
                merged.append(existing[u["id"]])
            else:
                merged.append(u)
                added += 1
        data["units"] = merged
        data["attempt_cap"] = attempt_cap
        data["tenant_order"] = list(catalog.tenant_ids)

        prev = data.get("config", {})
        if prev.get("tenants_yaml_sha") not in (None, catalog_sha):
            print("[WARN] tenants.yaml changed since last init "
                  f"({prev.get('tenants_yaml_sha')[:12]} -> {catalog_sha[:12]})",
                  file=sys.stderr)
        if prev.get("stages_yaml_sha") not in (None, stages_sha):
            print("[WARN] reingest_stages.yaml changed since last init "
                  f"({prev.get('stages_yaml_sha')[:12]} -> {stages_sha[:12]})",
                  file=sys.stderr)
        data["config"] = {"tenants_yaml_sha": catalog_sha,
                          "stages_yaml_sha": stages_sha}
        store._data = data
        store.save()
        print(f"[OK] re-init idempotent: {len(merged)} units "
              f"({added} added, {len(merged) - added} preserved) at "
              f"{store.state_path}")
        return 0

    data = {
        "schema_version": SCHEMA_VERSION,
        "collection_version": args.collection_version,
        "backend": args.backend,
        "embedding_profile": args.embedding_profile,
        "created_at": _utcnow(),
        "updated_at": _utcnow(),
        "attempt_cap": attempt_cap,
        "tenant_order": list(catalog.tenant_ids),
        "config": {"tenants_yaml_sha": catalog_sha, "stages_yaml_sha": stages_sha},
        "units": fresh_units,
    }
    store._data = data
    store.save()
    print(f"[OK] initialized {len(fresh_units)} units for "
          f"collection_version={args.collection_version} at {store.state_path}")
    return 0


def _require_state(args: argparse.Namespace) -> StateStore:
    store = StateStore(_state_dir(Path(args.state_root), args.collection_version))
    if not store.exists():
        print(f"[ERROR] no state file at {store.state_path}; run `init` first.",
              file=sys.stderr)
        raise SystemExit(1)
    return store


def cmd_next(args: argparse.Namespace) -> int:
    store = _require_state(args)
    unit = store.next_unit()
    print(json.dumps({"unit": unit}, indent=2 if args.pretty else None))
    return 0


def _mutate(args: argparse.Namespace, fn) -> int:
    store = _require_state(args)
    unit = store.by_id(args.id)
    if unit is None:
        print(f"[ERROR] unknown unit id: {args.id!r}", file=sys.stderr)
        return 1
    fn(store, unit)
    store.save()
    print(f"[OK] {args.id} -> {unit['status']}")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    def _fn(store: StateStore, unit: dict[str, Any]) -> None:
        unit["status"] = "running"
        unit["started_at"] = _utcnow()
        unit["ended_at"] = None

    return _mutate(args, _fn)


def cmd_done(args: argparse.Namespace) -> int:
    metrics = json.loads(args.metrics) if args.metrics else {}

    def _fn(store: StateStore, unit: dict[str, Any]) -> None:
        unit["status"] = "done"
        unit["ended_at"] = _utcnow()
        unit["metrics"] = {**(unit.get("metrics") or {}), **metrics}
        unit["last_error"] = None

    return _mutate(args, _fn)


def cmd_fail(args: argparse.Namespace) -> int:
    cap = None

    def _fn(store: StateStore, unit: dict[str, Any]) -> None:
        nonlocal cap
        cap = int(store.load()["attempt_cap"])
        unit["last_error"] = args.error
        unit["ended_at"] = _utcnow()
        if args.note:
            unit["adaptations"].append({"at": _utcnow(), "note": args.note})
        if args.requeue:
            # Systematic fix applied + re-queued: no attempt penalty (Req 11.3).
            unit["status"] = "pending"
            return
        unit["attempts"] += 1
        if unit["attempts"] >= cap:
            unit["status"] = "blocked"          # Terminal (Requirement 11.2)
        else:
            unit["status"] = "failed"

    return _mutate(args, _fn)


def cmd_skip(args: argparse.Namespace) -> int:
    def _fn(store: StateStore, unit: dict[str, Any]) -> None:
        unit["status"] = "skipped"
        unit["skip_reason"] = args.reason
        unit["ended_at"] = _utcnow()

    return _mutate(args, _fn)


def cmd_report(args: argparse.Namespace) -> int:
    store = _require_state(args)
    store.save()  # regenerate PROGRESS.md from current state
    data = store.load()
    units = data["units"]
    counts: dict[str, int] = {}
    for u in units:
        counts[u["status"]] = counts.get(u["status"], 0) + 1
    total = len(units)
    terminal = sum(counts.get(s, 0) for s in TERMINAL_STATES)
    print(f"# Re-ingest report — collection_version={data['collection_version']}")
    print(f"#   {terminal}/{total} units terminal")
    for status in ("pending", "running", "failed", "done", "skipped", "blocked"):
        if status in counts:
            print(f"#   {status:9s}: {counts[status]}")
    if counts.get("blocked"):
        print("# BLOCKED units:")
        for u in units:
            if u["status"] == "blocked":
                print(f"#   {u['id']} (attempts={u['attempts']}): "
                      f"{str(u.get('last_error'))[:100]}")
    print(f"# PROGRESS.md: {store.progress_path}")
    return 0


def cmd_is_complete(args: argparse.Namespace) -> int:
    store = _require_state(args)
    return 0 if store.is_complete() else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="State_Manager for the COTS full re-ingest Ralph loop."
    )
    p.add_argument(
        "--state-root",
        default=str(_REPO_ROOT),
        help="Root under which .reingest_state/<version>/ lives (default: repo root).",
    )
    p.add_argument(
        "--collection-version",
        default=os.environ.get("REINGEST_COLLECTION_VERSION", "v9-0-0"),
        help="Target Collection_Version (env REINGEST_COLLECTION_VERSION).",
    )
    sub = p.add_subparsers(dest="command", required=True)

    pi = sub.add_parser("init", help="Build/refresh the Work_Matrix (idempotent).")
    pi.add_argument("--catalog", default=str(_DEFAULT_CATALOG))
    pi.add_argument("--stages", default=str(_DEFAULT_STAGES))
    pi.add_argument("--attempt-cap", type=int, default=None)
    pi.add_argument("--mode-override", choices=("diff", "full"), default=None,
                    help="Force all ingest stages to this mode (else lifecycle-derived).")
    pi.add_argument("--backend", default=os.environ.get("DB_BACKEND", "cots"))
    pi.add_argument("--embedding-profile",
                    default=os.environ.get("MCP_EMBEDDING_PROFILE", "mpnet768"))
    pi.set_defaults(func=cmd_init)

    pn = sub.add_parser("next", help="Emit the next actionable unit as JSON.")
    pn.add_argument("--pretty", action="store_true")
    pn.set_defaults(func=cmd_next)

    ps = sub.add_parser("start", help="Mark a unit running.")
    ps.add_argument("--id", required=True)
    ps.set_defaults(func=cmd_start)

    pd = sub.add_parser("done", help="Mark a unit done (+ merge --metrics JSON).")
    pd.add_argument("--id", required=True)
    pd.add_argument("--metrics", default=None, help="JSON object to merge into metrics.")
    pd.set_defaults(func=cmd_done)

    pf = sub.add_parser("fail", help="Record a failure (attempts++ or --requeue).")
    pf.add_argument("--id", required=True)
    pf.add_argument("--error", required=True)
    pf.add_argument("--requeue", action="store_true",
                    help="Reset to pending WITHOUT incrementing attempts (systematic fix).")
    pf.add_argument("--note", default=None, help="Adaptation note to record.")
    pf.set_defaults(func=cmd_fail)

    pk = sub.add_parser("skip", help="Mark a unit skipped (precondition unmet).")
    pk.add_argument("--id", required=True)
    pk.add_argument("--reason", required=True)
    pk.set_defaults(func=cmd_skip)

    pr = sub.add_parser("report", help="Rewrite PROGRESS.md and print a summary.")
    pr.set_defaults(func=cmd_report)

    pc = sub.add_parser("is-complete", help="Exit 0 iff all units terminal.")
    pc.set_defaults(func=cmd_is_complete)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
