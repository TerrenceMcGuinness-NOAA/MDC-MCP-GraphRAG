"""Property tests for Fortran AST graph ingestion (graph-port-fortran-ast).

Feature: graph-port-fortran-ast
  Property 1: Fortran graph completeness
  Property 2: CALLS edge correctness
  Property 3: USES edge correctness
  Property 4: CONTAINS hierarchy
  Property 5: Idempotence (MERGE semantics)
  Property 6: Tenant isolation
  Property 7: Parse failure resilience

All properties run with Hypothesis at >= 100 examples. Write-logic properties
drive the real async write helpers against in-memory stub graph databases;
parse-correctness properties generate synthetic Fortran source, parse it with
the real FortranParser, then drive the writers.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).parents[2]))
sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from scripts._fortran_parser import FortranParser, FortranParseResult
from scripts.ingest_fortran_graph_v8 import (
    _write_calls,
    _write_contains,
    _write_function_nodes,
    _write_module_nodes,
    _write_program_nodes,
    _write_subroutine_nodes,
    _write_uses,
)

PROP_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ════════════════════════════════════════════════════════════════════════
# Stubs + helpers
# ════════════════════════════════════════════════════════════════════════


class RecordingDB:
    """Stub graph_db that records every (cypher, params, tenant) call."""

    def __init__(self):
        self.calls: list[dict] = []

    async def query(self, cypher, params=None, *, tenant=None):
        self.calls.append({"cypher": cypher, "params": params, "tenant": tenant})


class MergeModelDB:
    """Stub graph_db that models Neptune MERGE idempotency.

    Each write is reduced to a canonical key: (cypher_template,
    params-excluding-volatile-timestamp). Re-applying an identical MERGE maps
    to the same set element, so the modeled graph state cannot grow on re-run.
    """

    def __init__(self):
        self.state: set[tuple] = set()

    async def query(self, cypher, params=None, *, tenant=None):
        p = params or {}
        key = tuple(sorted((k, v) for k, v in p.items() if k != "updated_at"))
        self.state.add((cypher, key))


def _run(coro):
    return asyncio.run(coro)


def _parse_source(src: str) -> FortranParseResult | None:
    """Write a Fortran source string to a temp worktree and parse it."""
    d = tempfile.mkdtemp()
    try:
        path = os.path.join(d, "gen.f90")
        with open(path, "w") as f:
            f.write(src)
        return FortranParser(d).parse_file(path)
    finally:
        shutil.rmtree(d, ignore_errors=True)


async def _write_all_nodes(db, prefix, result, tenant_id):
    await _write_module_nodes(db, prefix, result, tenant_id)
    await _write_subroutine_nodes(db, prefix, result, tenant_id)
    await _write_function_nodes(db, prefix, result, tenant_id)
    await _write_program_nodes(db, prefix, result, tenant_id)


async def _write_all_rels(db, prefix, result):
    await _write_calls(db, prefix, result)
    await _write_uses(db, prefix, result)
    await _write_contains(db, prefix, result)


# ── Hypothesis strategies for valid Fortran identifiers ─────────────────

_SUFFIX = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789_", min_size=0, max_size=6
)


def _names(prefix: str, min_size: int, max_size: int):
    """A strategy producing a unique list of valid identifiers with a prefix."""
    return st.lists(_SUFFIX, min_size=min_size, max_size=max_size, unique=True).map(
        lambda suffixes: [prefix + s for s in suffixes]
    )


# ════════════════════════════════════════════════════════════════════════
# Task 5 — P1: graph completeness, P7: parse failure resilience
# ════════════════════════════════════════════════════════════════════════


class TestProperty1Completeness:
    """Feature: graph-port-fortran-ast, Property 1: Fortran graph completeness.

    For a worktree with N parseable Fortran files, after node writes complete,
    at least N distinct file_path values appear across the created nodes.
    """

    @given(file_suffixes=_names("mod", min_size=1, max_size=6))
    @PROP_SETTINGS
    def test_n_files_contribute_n_filepaths(self, file_suffixes):
        wt = Path(tempfile.mkdtemp())
        try:
            sorc = wt / "sorc"
            sorc.mkdir(parents=True)
            expected_paths = set()
            for i, suf in enumerate(file_suffixes):
                rel = f"sorc/file_{i}.f90"
                expected_paths.add(rel)
                # Each file has a uniquely-named module → guaranteed parseable
                # and guaranteed to produce a node.
                (sorc / f"file_{i}.f90").write_text(
                    f"module m{i}_{suf}\nend module m{i}_{suf}\n"
                )

            fp = FortranParser(wt)
            files = fp.discover_fortran_files()
            assert len(files) == len(file_suffixes)

            db = RecordingDB()
            for path in files:
                result = fp.parse_file(path)
                assert result is not None
                _run(_write_all_nodes(db, "GW_V17_", result, "gw_v17"))

            seen_paths = {
                c["params"]["file_path"]
                for c in db.calls
                if c["params"] and "file_path" in c["params"]
            }
            assert expected_paths.issubset(seen_paths)
            assert len(seen_paths) >= len(file_suffixes)
        finally:
            shutil.rmtree(wt, ignore_errors=True)


class TestProperty7Resilience:
    """Feature: graph-port-fortran-ast, Property 7: Parse failure resilience.

    For a batch of N good files + K unparseable files, all N good files produce
    node writes and the K bad files neither raise nor abort the run.
    """

    @given(
        good=_names("g", min_size=1, max_size=5),
        n_bad=st.integers(min_value=0, max_value=4),
    )
    @PROP_SETTINGS
    def test_bad_files_do_not_abort(self, good, n_bad):
        wt = Path(tempfile.mkdtemp())
        try:
            sorc = wt / "sorc"
            sorc.mkdir(parents=True)
            good_modules = []
            for i, suf in enumerate(good):
                mod = f"good{i}_{suf}"
                good_modules.append(mod)
                (sorc / f"good_{i}.f90").write_text(f"module {mod}\nend module {mod}\n")
            for j in range(n_bad):
                # Null-byte content reliably fails fparser2 → parse_file None.
                (sorc / f"bad_{j}.f90").write_bytes(b"\x00\xff module ?? \x00 ;;;")

            fp = FortranParser(wt)
            files = fp.discover_fortran_files()
            assert len(files) == len(good) + n_bad

            db = RecordingDB()
            parsed_ok = 0
            for path in files:
                result = fp.parse_file(path)  # must never raise
                if result is not None:
                    parsed_ok += 1
                    _run(_write_all_nodes(db, "GW_V17_", result, "gw_v17"))

            # All good files parsed and contributed module nodes.
            assert parsed_ok >= len(good)
            written_modules = {
                c["params"]["name"]
                for c in db.calls
                if "FortranModule" in c["cypher"]
            }
            for mod in good_modules:
                assert mod in written_modules
        finally:
            shutil.rmtree(wt, ignore_errors=True)


# ════════════════════════════════════════════════════════════════════════
# Task 6 — P2: CALLS correctness, P3: USES correctness
# ════════════════════════════════════════════════════════════════════════


class TestProperty2CallsCorrectness:
    """Feature: graph-port-fortran-ast, Property 2: CALLS edge correctness.

    Every CALL <name> extracted from a parsed file produces a CALLS MERGE whose
    callee_name equals the called name.
    """

    @given(callees=_names("c", min_size=1, max_size=8))
    @PROP_SETTINGS
    def test_each_call_produces_calls_merge(self, callees):
        body = "\n".join(f"  call {c}()" for c in callees)
        src = f"subroutine driver()\n{body}\nend subroutine driver\n"
        result = _parse_source(src)
        assert result is not None
        assert {c["callee"] for c in result.calls} == set(callees)

        db = RecordingDB()
        _run(_write_calls(db, "GW_V17_", result))
        merged_callees = {
            c["params"]["callee_name"]
            for c in db.calls
            if "CALLS" in c["cypher"]
        }
        assert merged_callees == set(callees)
        for c in db.calls:
            assert "MERGE (callee:`GW_V17_FortranSubroutine`" in c["cypher"]
            assert c["tenant"] is None


class TestProperty3UsesCorrectness:
    """Feature: graph-port-fortran-ast, Property 3: USES edge correctness.

    Every USE <module> extracted from a parsed file produces a USES MERGE whose
    module_name equals the used module name.
    """

    @given(modules=_names("u", min_size=1, max_size=8))
    @PROP_SETTINGS
    def test_each_use_produces_uses_merge(self, modules):
        body = "\n".join(f"  use {m}" for m in modules)
        src = f"program p\n{body}\n  implicit none\nend program p\n"
        result = _parse_source(src)
        assert result is not None
        assert {u["module"] for u in result.uses} == set(modules)

        db = RecordingDB()
        _run(_write_uses(db, "GW_V17_", result))
        merged_modules = {
            c["params"]["module_name"]
            for c in db.calls
            if "USES" in c["cypher"]
        }
        assert merged_modules == set(modules)
        for c in db.calls:
            assert "MERGE (mod:`GW_V17_FortranModule`" in c["cypher"]
            assert c["tenant"] is None


# ════════════════════════════════════════════════════════════════════════
# Task 7 — P4: CONTAINS hierarchy, P5: idempotence
# ════════════════════════════════════════════════════════════════════════


class TestProperty4ContainsHierarchy:
    """Feature: graph-port-fortran-ast, Property 4: CONTAINS hierarchy.

    Every subroutine/function defined inside a MODULE gets a CONTAINS edge from
    that module.
    """

    @given(subs=_names("sub", min_size=1, max_size=6))
    @PROP_SETTINGS
    def test_module_contains_its_subroutines(self, subs):
        body = "\n".join(
            f"  subroutine {s}()\n  end subroutine {s}" for s in subs
        )
        src = f"module mod_host\ncontains\n{body}\nend module mod_host\n"
        result = _parse_source(src)
        assert result is not None
        # Every parsed subroutine resolved to the host module.
        for s in result.subroutines:
            assert s["parent_module"] == "mod_host"

        db = RecordingDB()
        _run(_write_contains(db, "GW_V17_", result))
        contained = {
            c["params"]["sub_name"]
            for c in db.calls
            if c["params"] and "sub_name" in c["params"]
        }
        assert contained == set(subs)
        for c in db.calls:
            assert "MERGE (m)-[:CONTAINS]->(s)" in c["cypher"]
            assert "`GW_V17_FortranModule`" in c["cypher"]


class TestProperty5Idempotence:
    """Feature: graph-port-fortran-ast, Property 5: Idempotence.

    Running the full node+relationship write logic twice yields the same
    modeled graph state — MERGE semantics guarantee no growth on re-run.
    """

    @given(
        mods=_names("mod", min_size=1, max_size=3),
        subs=_names("sub", min_size=1, max_size=3),
        callees=_names("c", min_size=0, max_size=3),
    )
    @PROP_SETTINGS
    def test_double_run_no_growth(self, mods, subs, callees):
        result = FortranParseResult(
            file_path="/wt/sorc/x.f90",
            relative_path="sorc/x.f90",
            modules=[{"name": m, "line_start": 1} for m in mods],
            subroutines=[
                {"name": s, "line_start": 2, "parent_module": mods[0]} for s in subs
            ],
            functions=[],
            programs=[],
            calls=[{"callee": c, "line": 3, "caller": None} for c in callees],
            uses=[{"module": mods[0], "only": None}],
        )

        db = MergeModelDB()

        async def _both():
            await _write_all_nodes(db, "GW_V17_", result, "gw_v17")
            await _write_all_rels(db, "GW_V17_", result)

        _run(_both())
        state_after_run1 = set(db.state)
        _run(_both())
        state_after_run2 = set(db.state)

        assert state_after_run2 == state_after_run1
        assert len(state_after_run2) == len(state_after_run1)


# ════════════════════════════════════════════════════════════════════════
# Task 8 — P6: tenant isolation
# ════════════════════════════════════════════════════════════════════════


class TestProperty6TenantIsolation:
    """Feature: graph-port-fortran-ast, Property 6: Tenant isolation.

    Two tenants with distinct label_prefix values over identical content
    produce node labels that are each prefixed with their own prefix and are
    disjoint across tenants. No unprefixed label ever leaks.
    """

    _LABEL_RE = re.compile(r"`(\w*?Fortran(?:Module|Subroutine|Function|Program))`")

    @given(
        mods=_names("mod", min_size=1, max_size=3),
        subs=_names("sub", min_size=1, max_size=3),
    )
    @PROP_SETTINGS
    def test_labels_disjoint_across_tenants(self, mods, subs):
        result = FortranParseResult(
            file_path="/wt/sorc/x.f90",
            relative_path="sorc/x.f90",
            modules=[{"name": m, "line_start": 1} for m in mods],
            subroutines=[
                {"name": s, "line_start": 2, "parent_module": mods[0]} for s in subs
            ],
            functions=[],
            programs=[{"name": "prog_a", "executable_name": None}],
            calls=[],
            uses=[{"module": mods[0], "only": None}],
        )

        def _labels_for(prefix: str, tenant_id: str) -> set[str]:
            db = RecordingDB()
            _run(_write_all_nodes(db, prefix, result, tenant_id))
            _run(_write_all_rels(db, prefix, result))
            labels: set[str] = set()
            for c in db.calls:
                labels.update(self._LABEL_RE.findall(c["cypher"]))
            return labels

        labels_a = _labels_for("GW_V17_", "gw_v17")
        labels_b = _labels_for("GW_SFS_", "gw_sfs")

        # Every label carries its tenant's prefix.
        assert labels_a and all(lbl.startswith("GW_V17_") for lbl in labels_a)
        assert labels_b and all(lbl.startswith("GW_SFS_") for lbl in labels_b)
        # Disjoint namespaces, and no unprefixed label leaked.
        assert labels_a.isdisjoint(labels_b)
        for leaked in ("FortranModule", "FortranSubroutine",
                       "FortranFunction", "FortranProgram"):
            assert leaked not in labels_a
            assert leaked not in labels_b
