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

SCHEMA_VERSION = 2
GLOBAL_TENANT = "__global__"
TERMINAL_STATES = frozenset({"done", "skipped", "blocked"})
ACTIONABLE_STATES = frozenset({"pending", "failed"})

# Valid scope values for Reingest_Unit (Phase 81 extension).
VALID_SCOPES = frozenset({"shared", "tenant", "hybrid_external", "hybrid_local",
                          "global"})  # "global" is legacy alias for "shared"

_DEFAULT_CATALOG = _SERVER_ROOT / "src" / "config" / "tenants.yaml"
_DEFAULT_STAGES = _SCRIPT_DIR / "reingest_stages.yaml"
_DEFAULT_MANIFEST = _SERVER_ROOT / "src" / "config" / "unified_manifest.json"

# Kinds for which --mode / --collection-version are meaningful (ingest stages).
_INGEST_KINDS = frozenset({"vector", "dual", "graph"})

# Kinds that trigger manifest writeback on `done` or `blocked` transitions
# (Phase 81, Requirement 7).
_WRITEBACK_KINDS = frozenset({"vector", "dual", "graph"})

# ---------------------------------------------------------------------------
# Stage → manifest source name mapping (Phase 81, Requirement 7).
#
# Maps a stage name to the manifest source name(s) it covers. Stages whose
# sources are declared in their YAML ``args: ["--sources", "..."]`` field use
# those names directly at runtime — this dict is the static fallback for stages
# that name their sources implicitly. The mapping is a documented iteration
# point (extend when new stages are added).
# ---------------------------------------------------------------------------

STAGE_TO_SOURCES: dict[str, list[str]] = {
    "jjobs": ["jjob-docs"],
    "ee2_standards": ["ee2-standards"],
    "community_summaries": ["community-summaries"],
    "config": ["rocoto-config", "expdir-configs"],
    "shell_graph": ["shell-code-context"],
    "fortran_graph": ["fortran-code-context"],
    "bridge": [],  # no manifest source — derived from other graph stages
    "expdir": ["expdir-configs"],
    "rocoto": ["rocoto-config"],
}

# Stages with an ``args: ["--sources", "<csv>"]`` entry in the catalog — their
# source list is extracted at runtime from the stage dict itself. This set gates
# the extraction logic so we don't spuriously parse unrelated ``args`` entries.
_STAGES_WITH_ARGS_SOURCES = frozenset({
    "workflow_docs_external", "pdf_sources", "workflow_docs_local",
    "code_with_context_local",
})


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
    """Build one Reingest_Unit from a stage template + a tenant (or global).

    Phase 81 additions: ``shared_once``, ``tenancy_precheck``, ``validation_path``.
    """
    kind = stage["kind"]
    is_global = tenant is None
    tenant_id = GLOBAL_TENANT if is_global else tenant.tenant_id
    lifecycle = "" if is_global else tenant.lifecycle
    mode = (
        _derive_mode(lifecycle, mode_override)
        if kind in _INGEST_KINDS
        else None
    )

    # Scope: prefer explicit field from the stage catalog; fall back to legacy
    # heuristic (global=>"shared", otherwise=>"tenant").
    scope = stage.get("scope", "shared" if is_global else "tenant")

    # shared_once: whether this stage should produce exactly one Work_Matrix unit
    # regardless of tenant count.
    shared_once = bool(stage.get("shared_once", False))

    # tenancy_precheck: what prefix/tenant_id the runtime should validate before
    # allowing this unit to run.
    if scope in ("shared", "hybrid_external") or is_global:
        tenancy_precheck = {
            "expected_prefix": "",
            "expected_tenant": None,
        }
    else:
        tenancy_precheck = {
            "expected_prefix": "" if is_global else (tenant.index_prefix if tenant else ""),
            "expected_tenant": tenant_id,
        }

    # validation_path: populated at init for validate-kind units.
    validation_path: str | None = None
    if kind == "validate" and not is_global:
        validation_path = f"validation/{tenant_id}.json"
    elif kind == "validate" and is_global:
        validation_path = "validation/_shared_once.json"

    unit: dict[str, Any] = {
        "id": f"{tenant_id}:{stage['name']}",
        "tenant_id": tenant_id,
        "scope": scope,
        "shared_once": shared_once,
        "tenancy_precheck": tenancy_precheck,
        "validation_path": validation_path,
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
        "depends_on_all_tenants": bool(stage.get("depends_on_all_tenants", False)),
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
    """Full Work_Matrix, scope-aware (rag-data-plane-gap-closure R2, Phase 81).

    Each stage declares ``scope: shared | tenant | hybrid_external |
    hybrid_local`` (reingest_stages.yaml). A ``shared`` or
    ``hybrid_external`` stage emits exactly ONE unit
    (``tenant_id="__global__"``, no tenant coupling); a ``tenant`` or
    ``hybrid_local`` stage emits one unit per catalog tenant. Stages with
    ``shared_once: true`` also emit exactly once regardless of scope
    (belt-and-braces for the Shared_Once_Rule).

    For the current 5-tenant catalog this yields 55 tenant-scoped + 3-6
    shared = 58-61 units depending on the catalog.
    """
    units: list[dict[str, Any]] = []

    def _emit(stage: dict[str, Any], default_scope: str) -> None:
        scope = stage.get("scope", default_scope)
        shared_once = bool(stage.get("shared_once", False))
        # Stages with shared_once=true or scope in the shared family emit once.
        if shared_once or scope in ("shared", "hybrid_external"):
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
# Schema migration (v1 → v2) and scope-drift detection (Phase 81)
# ---------------------------------------------------------------------------


def _migrate_state_v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    """Upgrade a v1 State_File to v2 in-place (additive fields only).

    Fields added to every unit that lacks them:
      - ``shared_once: False``
      - ``tenancy_precheck: None``
      - ``validation_path: None``
      - ``depends_on_all_tenants: False``

    The existing ``scope`` field (v1 had ``"global"`` or ``"tenant"``) is
    preserved as-is — the extended enum values (``"shared"``,
    ``"hybrid_external"``, ``"hybrid_local"``) only appear on freshly-built
    units.

    The top-level ``schema_version`` is bumped to 2.
    """
    for unit in data.get("units", []):
        if "shared_once" not in unit:
            unit["shared_once"] = False
        if "tenancy_precheck" not in unit:
            unit["tenancy_precheck"] = None
        if "validation_path" not in unit:
            unit["validation_path"] = None
        if "depends_on_all_tenants" not in unit:
            unit["depends_on_all_tenants"] = False
    data["schema_version"] = SCHEMA_VERSION
    if "warnings" not in data:
        data["warnings"] = []
    return data


def _detect_scope_drift(
    existing_units: list[dict[str, Any]],
    fresh_units: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Detect ``catalog_scope_drift``: a stage whose ``shared_once`` changed.

    Returns a list of warning dicts, each:
    ``{"type": "catalog_scope_drift", "unit_id": ..., "old": ..., "new": ...}``
    """
    fresh_by_stage: dict[str, dict[str, Any]] = {}
    for u in fresh_units:
        fresh_by_stage.setdefault(u["stage"], u)

    warnings: list[dict[str, Any]] = []
    seen_stages: set[str] = set()
    for eu in existing_units:
        stage_name = eu["stage"]
        if stage_name in seen_stages:
            continue
        seen_stages.add(stage_name)
        fu = fresh_by_stage.get(stage_name)
        if fu is None:
            continue
        old_shared_once = eu.get("shared_once", False)
        new_shared_once = fu.get("shared_once", False)
        if old_shared_once != new_shared_once:
            warnings.append({
                "type": "catalog_scope_drift",
                "unit_id": eu["id"],
                "stage": stage_name,
                "old_shared_once": old_shared_once,
                "new_shared_once": new_shared_once,
                "message": (
                    f"Stage '{stage_name}' shared_once changed from "
                    f"{old_shared_once} to {new_shared_once}. "
                    f"Re-run init with --force-scope-migration to accept."
                ),
            })
    return warnings


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
        """Units eligible for `next`: status actionable, under cap, deps terminal.

        When a unit has ``depends_on_all_tenants: true``, the listed stages must
        be terminal for EVERY tenant in the catalog (cross-tenant gating). This
        is used by ``neo4j_rebuild_indexes`` to wait for all per-tenant graph
        stages before it rebuilds the shared index set.
        """
        cap = int(self.load()["attempt_cap"])
        out: list[dict[str, Any]] = []
        for u in self.units():
            if u["status"] not in ACTIONABLE_STATES:
                continue
            if u["attempts"] >= cap:
                continue
            deps = u.get("depends_on") or []
            if deps:
                if u.get("depends_on_all_tenants", False):
                    # Cross-tenant: every tenant's listed stages must be terminal.
                    if not self._all_tenants_deps_terminal(deps):
                        continue
                else:
                    # Same-tenant: only the unit's own tenant must be terminal.
                    sibling = self._tenant_stage_status(u["tenant_id"])
                    if not all(sibling.get(d) in TERMINAL_STATES for d in deps):
                        continue
            out.append(u)
        return out

    def _all_tenants_deps_terminal(self, stage_names: list[str]) -> bool:
        """Check that the given stage names are terminal for every tenant.

        Only checks non-global tenants (``tenant_id != "__global__"``). A stage
        that does not exist for a given tenant (e.g. because it is shared-once
        and emits as __global__) is treated as satisfied.
        """
        tenant_ids = {
            u["tenant_id"] for u in self.units()
            if u["tenant_id"] != GLOBAL_TENANT
        }
        for tid in tenant_ids:
            sibling = self._tenant_stage_status(tid)
            for stage_name in stage_names:
                status = sibling.get(stage_name)
                # If the stage doesn't exist for this tenant, treat as satisfied
                # (it might be a shared-once stage emitted as __global__).
                if status is not None and status not in TERMINAL_STATES:
                    return False
        return True

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

        # Phase 81: migrate v1 → v2 schema if needed.
        migrated = False
        if data.get("schema_version", 1) < SCHEMA_VERSION:
            data = _migrate_state_v1_to_v2(data)
            migrated = True
            print("[INFO] migrated state file from schema_version 1 to 2",
                  file=sys.stderr)

        # Phase 81: detect catalog_scope_drift (shared_once changed on a stage).
        # Skip drift detection on freshly-migrated files — migration sets defaults
        # that may not match the current catalog; that is expected, not drift.
        if not migrated:
            drift_warnings = _detect_scope_drift(data["units"], fresh_units)
            if drift_warnings and not getattr(args, "force_scope_migration", False):
                data.setdefault("warnings", []).extend(drift_warnings)
                for w in drift_warnings:
                    print(f"[WARN] {w['message']}", file=sys.stderr)
                store._data = data
                store.save()
                print("[ERROR] catalog_scope_drift detected. Re-run with "
                      "--force-scope-migration to accept.", file=sys.stderr)
                return 1

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

        # Clear drift warnings on successful re-init (either forced or no drift).
        if getattr(args, "force_scope_migration", False):
            data["warnings"] = [
                w for w in data.get("warnings", [])
                if w.get("type") != "catalog_scope_drift"
            ]

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
        "warnings": [],
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


# ---------------------------------------------------------------------------
# Manifest writeback (Phase 81, Requirement 7)
# ---------------------------------------------------------------------------


def _resolve_stage_sources(unit: dict[str, Any], stages_data: dict[str, Any] | None = None) -> list[str]:
    """Resolve the manifest source name(s) a unit covers.

    Resolution order:
    1. If the stage has ``args: ["--sources", "<csv>"]`` in the catalog, parse
       those names.
    2. Else fall back to the static ``STAGE_TO_SOURCES`` mapping.
    3. If neither yields names, return an empty list (no writeback for this unit).

    Parameters
    ----------
    unit : dict
        The Reingest_Unit dict from the State_File.
    stages_data : dict | None
        Optional parsed stages catalog (for extracting ``args``). If None, only
        the static mapping is used.
    """
    stage_name = unit["stage"]

    # Try extracting from the catalog's args field.
    if stages_data is not None and stage_name in _STAGES_WITH_ARGS_SOURCES:
        all_stages = list(stages_data.get("per_tenant", []))
        all_stages.extend(stages_data.get("global", []))
        for s in all_stages:
            if s.get("name") == stage_name:
                args_list = s.get("args", [])
                for i, arg in enumerate(args_list):
                    if arg == "--sources" and i + 1 < len(args_list):
                        return [n.strip() for n in args_list[i + 1].split(",") if n.strip()]
                break

    # Static fallback.
    return list(STAGE_TO_SOURCES.get(stage_name, []))


def _writeback_manifest_status(
    unit: dict[str, Any],
    *,
    manifest_path: Path | None = None,
    blocked_reason: str | None = None,
    stages_data: dict[str, Any] | None = None,
) -> int:
    """Write ``ingest_status`` to unified_manifest.json for the unit's sources.

    Called from ``cmd_done`` (status="done") and ``cmd_fail`` when a unit reaches
    ``blocked``. Writes atomically (temp file + os.replace).

    Parameters
    ----------
    unit : dict
        The Reingest_Unit dict (must have ``stage``, ``kind``, ``metrics``).
    manifest_path : Path | None
        Path to ``unified_manifest.json``. Defaults to the canonical location.
    blocked_reason : str | None
        If set, the unit is blocked and this is the reason string to record
        in ``ingest_status.blocked_reason``.
    stages_data : dict | None
        Parsed stages catalog for ``--sources`` extraction; None uses static map.

    Returns
    -------
    int
        Number of sources updated in the manifest.
    """
    if manifest_path is None:
        manifest_path = _DEFAULT_MANIFEST

    # Only writeback for kinds that produce ingested content.
    if unit.get("kind") not in _WRITEBACK_KINDS:
        return 0

    source_names = _resolve_stage_sources(unit, stages_data=stages_data)
    if not source_names:
        return 0

    # Read the manifest.
    if not manifest_path.is_file():
        print(f"[WARN] manifest not found at {manifest_path}; skipping writeback",
              file=sys.stderr)
        return 0

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sources = manifest.get("sources", [])

    # Build the ingest_status block.
    metrics = unit.get("metrics") or {}
    status_block: dict[str, Any] = {
        "collection_version": unit.get("metrics", {}).get("collection_version", "v9-0-0"),
        "actual_docs": int(metrics.get("docs_ingested", metrics.get("actual_docs", 0))),
        "ingested_at": unit.get("ended_at") or _utcnow(),
        "sha": metrics.get("sha", ""),
        "backend": metrics.get("backend", "cots"),
        "embedding_profile": metrics.get("embedding_profile", "mpnet768"),
    }

    if blocked_reason:
        status_block["blocked_reason"] = blocked_reason
        # Clear actual_docs for blocked units — they didn't successfully ingest.
        status_block["actual_docs"] = 0

    # Apply to matching sources.
    updated = 0
    for source in sources:
        if source.get("name") in source_names:
            source["ingest_status"] = status_block
            updated += 1

    if updated == 0:
        print(f"[WARN] no manifest sources matched stage '{unit['stage']}' "
              f"(looked for: {source_names})", file=sys.stderr)
        return 0

    # Write atomically.
    manifest_dir = manifest_path.parent
    fd, tmp = tempfile.mkstemp(
        dir=str(manifest_dir), prefix=".manifest.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, sort_keys=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, str(manifest_path))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

    print(f"[OK] manifest writeback: {updated} source(s) updated for "
          f"stage '{unit['stage']}'")
    return updated


def cmd_done(args: argparse.Namespace) -> int:
    metrics = json.loads(args.metrics) if args.metrics else {}
    manifest_path = Path(args.manifest) if hasattr(args, "manifest") and args.manifest else None

    def _fn(store: StateStore, unit: dict[str, Any]) -> None:
        unit["status"] = "done"
        unit["ended_at"] = _utcnow()
        unit["metrics"] = {**(unit.get("metrics") or {}), **metrics}
        unit["last_error"] = None

    # Run the state mutation.
    store = _require_state(args)
    unit = store.by_id(args.id)
    if unit is None:
        print(f"[ERROR] unknown unit id: {args.id!r}", file=sys.stderr)
        return 1
    _fn(store, unit)
    store.save()
    print(f"[OK] {args.id} -> {unit['status']}")

    # Phase 81 Requirement 7: manifest writeback on done for ingest kinds.
    if unit.get("kind") in _WRITEBACK_KINDS:
        _writeback_manifest_status(
            unit,
            manifest_path=manifest_path,
        )

    return 0


def cmd_fail(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest) if hasattr(args, "manifest") and args.manifest else None

    def _fn(store: StateStore, unit: dict[str, Any]) -> None:
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

    # Run the state mutation.
    store = _require_state(args)
    unit = store.by_id(args.id)
    if unit is None:
        print(f"[ERROR] unknown unit id: {args.id!r}", file=sys.stderr)
        return 1
    _fn(store, unit)
    store.save()
    print(f"[OK] {args.id} -> {unit['status']}")

    # Phase 81 Requirement 7: manifest writeback on blocked with reason.
    if unit["status"] == "blocked" and unit.get("kind") in _WRITEBACK_KINDS:
        _writeback_manifest_status(
            unit,
            manifest_path=manifest_path,
            blocked_reason=unit.get("last_error", "unknown"),
        )

    return 0


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
    pi.add_argument("--force-scope-migration", action="store_true", default=False,
                    help="Accept catalog_scope_drift without aborting (Phase 81).")
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
    pd.add_argument("--manifest", default=None,
                    help="Path to unified_manifest.json for writeback (default: canonical location).")
    pd.set_defaults(func=cmd_done)

    pf = sub.add_parser("fail", help="Record a failure (attempts++ or --requeue).")
    pf.add_argument("--id", required=True)
    pf.add_argument("--error", required=True)
    pf.add_argument("--requeue", action="store_true",
                    help="Reset to pending WITHOUT incrementing attempts (systematic fix).")
    pf.add_argument("--note", default=None, help="Adaptation note to record.")
    pf.add_argument("--manifest", default=None,
                    help="Path to unified_manifest.json for writeback (default: canonical location).")
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
