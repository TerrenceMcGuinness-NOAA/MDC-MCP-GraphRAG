"""Coverage-gap check: tenant-resolved path + graph fallback + multi-language.

fortran-coverage-gap-path-fix (SDD Phase 72). Exercises
`_check_coverage_gap` / `_coverage_for_language` directly with a recording
graph double and real tmp_path source trees — no live services.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from src.tools import semantic_search as ss

pytestmark = pytest.mark.unit


class _RecordingGraph:
    """Graph double: returns a count based on which label appears in the
    cypher, and records the ``tenant`` kwarg it was called with."""

    def __init__(self, counts: dict[str, int]):
        self._counts = counts
        self.tenants_seen: list[Any] = []

    async def query(self, cypher: str, tenant: Any = None, **_kw: Any):
        self.tenants_seen.append(tenant)
        for label, total in self._counts.items():
            if label in cypher:
                return [{"total": total}]
        return [{"total": 0}]


class _Data:
    def __init__(self, graph: Any):
        self.graph_db = graph
        self.vector_db = None


def _run(repo_base: Path, counts: dict[str, int]) -> tuple[list[ss._Check], _RecordingGraph]:
    graph = _RecordingGraph(counts)
    checks = asyncio.run(ss._check_coverage_gap(_Data(graph), repo_base=repo_base))
    return checks, graph


def _row(checks: list[ss._Check], label: str) -> ss._Check:
    return next(c for c in checks if c.name == f"Coverage Gap ({label})")


def _mk(paths: list[Path]) -> None:
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("! stub\n")


# ── never SKIP + per-language rows (R3.3, R4.1) ──────────────────────────


def test_returns_one_row_per_language_and_never_skips(tmp_path: Path) -> None:
    checks, _ = _run(tmp_path, {"FortranSubroutine": 500, "PythonModule": 500,
                                "ShellScript": 500})
    names = {c.name for c in checks}
    assert names == {"Coverage Gap (Fortran)", "Coverage Gap (Python)",
                     "Coverage Gap (Shell)"}
    assert all("[SKIP]" not in c.details for c in checks)


# ── filesystem cross-reference (R1.2, R4.2/4.3/4.4) ──────────────────────


def test_fortran_ok_when_nodes_ge_files(tmp_path: Path) -> None:
    _mk([tmp_path / "sorc" / "a.f90", tmp_path / "sorc" / "b.f90"])
    checks, _ = _run(tmp_path, {"FortranSubroutine": 100})
    row = _row(checks, "Fortran")
    assert row.passed is True
    assert row.details.startswith("[OK]")
    assert "2 files" in row.details


def test_fortran_fail_when_files_present_but_zero_nodes(tmp_path: Path) -> None:
    _mk([tmp_path / "sorc" / "a.f90"])
    checks, _ = _run(tmp_path, {"FortranSubroutine": 0})
    row = _row(checks, "Fortran")
    assert row.passed is False
    assert row.details.startswith("[FAIL]")


def test_fortran_warn_when_fewer_nodes_than_files(tmp_path: Path) -> None:
    _mk([tmp_path / "sorc" / f"f{i}.f90" for i in range(5)])
    checks, _ = _run(tmp_path, {"FortranSubroutine": 2})
    row = _row(checks, "Fortran")
    assert row.passed is True
    assert row.details.startswith("[WARN]")
    assert "partial coverage" in row.details


def test_no_source_files_is_ok(tmp_path: Path) -> None:
    (tmp_path / "sorc").mkdir()  # dir exists, no .f90 files
    checks, _ = _run(tmp_path, {"FortranSubroutine": 0})
    row = _row(checks, "Fortran")
    assert row.passed is True
    assert row.details.startswith("[OK]")


# ── graph-only fallback (R2) ─────────────────────────────────────────────


def test_graph_only_ok_above_threshold(tmp_path: Path) -> None:
    # tmp_path has no sorc/ → filesystem not available for Fortran.
    checks, _ = _run(tmp_path, {"FortranSubroutine": 500})
    row = _row(checks, "Fortran")
    assert row.passed is True
    assert row.details.startswith("[OK]")
    assert "graph-only" in row.details


def test_graph_only_warn_within_threshold(tmp_path: Path) -> None:
    checks, _ = _run(tmp_path, {"FortranSubroutine": 50})
    row = _row(checks, "Fortran")
    assert row.passed is True
    assert row.details.startswith("[WARN]")
    assert "graph-only" in row.details


def test_graph_only_fail_when_zero(tmp_path: Path) -> None:
    checks, _ = _run(tmp_path, {"FortranSubroutine": 0})
    row = _row(checks, "Fortran")
    assert row.passed is False
    assert row.details.startswith("[FAIL]")


# ── tenant scoping (R1 — was missing on the pre-Phase-72 query) ──────────


def test_graph_queries_are_tenant_scoped(tmp_path: Path) -> None:
    class _T:
        index_prefix = "gw_v17_"

    graph = _RecordingGraph({"FortranSubroutine": 10})

    async def _go():
        # Patch the module's tenant resolver to return our fake tenant.
        import src.tools.semantic_search as m
        orig = m._tenant
        m._tenant = lambda: _T()
        try:
            return await m._check_coverage_gap(_Data(graph), repo_base=tmp_path)
        finally:
            m._tenant = orig

    asyncio.run(_go())
    # Every graph query received the active tenant (not None).
    assert graph.tenants_seen
    assert all(getattr(t, "index_prefix", None) == "gw_v17_" for t in graph.tenants_seen)
