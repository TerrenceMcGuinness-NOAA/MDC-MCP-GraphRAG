"""Unit tests for the regex fallback extractor (fortran-parse-fallback).

The fallback runs only when fparser2 returns no tree, recovering MODULE /
SUBROUTINE / FUNCTION / PROGRAM definitions and CALLS / USES edges from the
sanitized/preprocessed source text and returning the identical
``FortranParseResult`` shape (with ``source="fallback"``).

Validates: R1.1, R1.2, R1.3, R1.5, R2.1-R2.7, R3.1-R3.4, R4.1-R4.5,
R5.1, R6.1, R6.2, R6.3 of fortran-parse-fallback.

Test design
-----------
Triggering and provenance-counter tests run end-to-end through ``parse_file``
using genuinely malformed fixtures that fparser2 rejects but the fallback can
recover (so the path is exercised for real, not simulated). The
definition/edge/containment tests call ``_fallback_extract`` directly on
crafted source so they test the extractor deterministically without depending
on fparser2's exact failure surface.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))
sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from scripts._fortran_parser import FortranParser, FortranParseResult
from scripts.ingest_fortran_graph_v8 import (
    _result_node_counts,
    _result_rel_counts,
)


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


# A clean file fparser2 parses cleanly.
_CLEAN = "module ok_mod\nimplicit none\nend module ok_mod\n"

# Malformed source fparser2 rejects (the ``@`` token is not valid Fortran) but
# the fallback recovers the subroutine + call.
_MALFORMED_RECOVERABLE = (
    "subroutine s_recover(x)\n"
    "  real :: x@bad_token\n"
    "  call worker(x)\n"
    "end subroutine s_recover\n"
)

# Content with no structural keywords at all → both paths recover nothing.
_UNRECOVERABLE = "%%% not fortran %%%\n@@@ 123 garbage @@@\n"


# ════════════════════════════════════════════════════════════════════════
# Triggering (R1.1, R1.2, R1.3)
# ════════════════════════════════════════════════════════════════════════


class TestTriggering:
    def test_clean_file_uses_fparser2_not_fallback(self, tmp_path):
        """R1.1: a non-None tree keeps fparser2 fidelity; fallback not invoked."""
        f = _write(tmp_path / "clean.f90", _CLEAN)
        parser = FortranParser(tmp_path)

        called = {"fallback": False}
        real_fb = parser._fallback_extract

        def _spy(*a, **k):
            called["fallback"] = True
            return real_fb(*a, **k)

        parser._fallback_extract = _spy
        r = parser.parse_file(f)
        assert r is not None
        assert r.source == "fparser2"
        assert called["fallback"] is False
        assert parser.stats["files_parsed_fparser2"] == 1
        assert parser.stats["files_parsed_fallback"] == 0

    def test_malformed_file_recovered_by_fallback(self, tmp_path):
        """R1.2: fparser2 failure falls through to the fallback."""
        f = _write(tmp_path / "bad.f90", _MALFORMED_RECOVERABLE)
        parser = FortranParser(tmp_path)
        r = parser.parse_file(f)
        assert r is not None
        assert r.source == "fallback"
        assert "s_recover" in [s["name"] for s in r.subroutines]
        assert "worker" in [c["callee"] for c in r.calls]
        assert parser.stats["files_parsed_fallback"] == 1

    def test_total_failure_returns_none(self, tmp_path):
        """R1.3: when the fallback also recovers nothing, return None."""
        f = _write(tmp_path / "junk.f90", _UNRECOVERABLE)
        parser = FortranParser(tmp_path)
        parser._parser = lambda _reader: None  # force fparser2 miss
        r = parser.parse_file(f)
        assert r is None
        assert parser.stats["files_failed"] == 1


# ════════════════════════════════════════════════════════════════════════
# Definition extraction (R2.1-R2.5, R2.7)
# ════════════════════════════════════════════════════════════════════════


class TestDefinitions:
    def test_prefixed_definitions_and_end_skipped(self, tmp_path):
        src = (
            "module weather_mod\n"
            "contains\n"
            "  pure subroutine compute(x)\n"
            "  end subroutine compute\n"
            "  recursive subroutine descend(n)\n"
            "  end subroutine descend\n"
            "  real function area(r) result(a)\n"
            "  end function area\n"
            "  integer(i_kind) function counter()\n"
            "  end function counter\n"
            "end module weather_mod\n"
        )
        f = _write(tmp_path / "defs.f90", src)
        parser = FortranParser(tmp_path)
        r = parser._fallback_extract(str(f), str(f))
        assert r is not None
        assert r.source == "fallback"
        assert [m["name"] for m in r.modules] == ["weather_mod"]
        assert sorted(s["name"] for s in r.subroutines) == ["compute", "descend"]
        assert sorted(fn["name"] for fn in r.functions) == ["area", "counter"]
        # No "end *" line was captured as a definition.
        for fn in r.functions:
            assert fn["return_type"] is None

    def test_program_and_executable_inference(self, tmp_path):
        f = _write(
            tmp_path / "sorc" / "ufs_model.fd" / "drv.f90",
            "program drv\n  call init()\nend program drv\n",
        )
        parser = FortranParser(tmp_path)
        r = parser._fallback_extract(str(f), str(f))
        assert r is not None
        prog = next(p for p in r.programs if p["name"] == "drv")
        assert prog["executable_name"] == "ufs_model.x"

    def test_module_procedure_not_a_module(self, tmp_path):
        src = (
            "module ifc_mod\n"
            "  interface\n"
            "    module procedure foo\n"
            "  end interface\n"
            "end module ifc_mod\n"
        )
        f = _write(tmp_path / "mp.f90", src)
        parser = FortranParser(tmp_path)
        r = parser._fallback_extract(str(f), str(f))
        assert r is not None
        # Only the real module is captured, not "MODULE PROCEDURE foo".
        assert [m["name"] for m in r.modules] == ["ifc_mod"]

    def test_module_subroutine_prefix_form(self, tmp_path):
        src = (
            "module sm_mod\n"
            "contains\n"
            "  module subroutine impl_a()\n"
            "  end subroutine impl_a\n"
            "end module sm_mod\n"
        )
        f = _write(tmp_path / "sm.f90", src)
        parser = FortranParser(tmp_path)
        r = parser._fallback_extract(str(f), str(f))
        assert r is not None
        assert [m["name"] for m in r.modules] == ["sm_mod"]
        assert "impl_a" in [s["name"] for s in r.subroutines]


# ════════════════════════════════════════════════════════════════════════
# Relationship extraction (R3.1-R3.3)
# ════════════════════════════════════════════════════════════════════════


class TestRelationships:
    def test_call_strips_arguments(self, tmp_path):
        src = (
            "subroutine driver()\n"
            "  call alpha(1, 2)\n"
            "  call beta()\n"
            "end subroutine driver\n"
        )
        f = _write(tmp_path / "c.f90", src)
        parser = FortranParser(tmp_path)
        r = parser._fallback_extract(str(f), str(f))
        assert r is not None
        assert sorted(c["callee"] for c in r.calls) == ["alpha", "beta"]

    def test_use_with_and_without_only(self, tmp_path):
        src = (
            "program p\n"
            "  use kinds_mod, only: r8, i4\n"
            "  use util_mod\n"
            "end program p\n"
        )
        f = _write(tmp_path / "u.f90", src)
        parser = FortranParser(tmp_path)
        r = parser._fallback_extract(str(f), str(f))
        assert r is not None
        by_mod = {u["module"]: u["only"] for u in r.uses}
        assert "kinds_mod" in by_mod
        assert by_mod["kinds_mod"] is not None
        assert "r8" in by_mod["kinds_mod"]
        assert "i4" in by_mod["kinds_mod"]
        assert by_mod["util_mod"] is None

    def test_continuation_split_call_and_use(self, tmp_path):
        src = (
            "subroutine s()\n"
            "  call setup( &\n"
            "       a, b, &\n"
            "       c)\n"
            "  use mod_a, only: x, &\n"
            "      y, z\n"
            "end subroutine s\n"
        )
        f = _write(tmp_path / "cont.f90", src)
        parser = FortranParser(tmp_path)
        r = parser._fallback_extract(str(f), str(f))
        assert r is not None
        assert "setup" in [c["callee"] for c in r.calls]
        u = next(u for u in r.uses if u["module"] == "mod_a")
        assert u["only"] is not None
        assert "x" in u["only"] and "z" in u["only"]


# ════════════════════════════════════════════════════════════════════════
# Negative / false-positive guard (R6.2, R6.3)
# ════════════════════════════════════════════════════════════════════════


class TestNegativeGuards:
    def test_control_constructs_and_arrays_not_calls(self, tmp_path):
        src = (
            "subroutine s(n, arr, call_count)\n"
            "  if (n > 0) then\n"
            "  end if\n"
            "  do i = 1, n\n"
            "  end do\n"
            "  where (arr > 0)\n"
            "  end where\n"
            "  y = arr(call_count)\n"
            "  recall = 5\n"
            "  select case (n)\n"
            "  end select\n"
            "end subroutine s\n"
        )
        f = _write(tmp_path / "neg.f90", src)
        parser = FortranParser(tmp_path)
        r = parser._fallback_extract(str(f), str(f))
        assert r is not None
        assert r.calls == []

    def test_commented_calls_not_captured(self, tmp_path):
        src = (
            "subroutine s()\n"
            "! call commented_full\n"
            "  a = 1  ! call inline_comment\n"
            "  call real_call()\n"
            "end subroutine s\n"
        )
        f = _write(tmp_path / "cmt.f90", src)
        parser = FortranParser(tmp_path)
        r = parser._fallback_extract(str(f), str(f))
        assert r is not None
        assert [c["callee"] for c in r.calls] == ["real_call"]

    def test_no_duplicate_call_on_same_line(self, tmp_path):
        # Two identical CALL lines on distinct physical lines -> two entries
        # (distinct line numbers); deduplication is on (callee, line).
        src = (
            "subroutine s()\n"
            "  call foo()\n"
            "  call foo()\n"
            "end subroutine s\n"
        )
        f = _write(tmp_path / "dup.f90", src)
        parser = FortranParser(tmp_path)
        r = parser._fallback_extract(str(f), str(f))
        assert r is not None
        foo_calls = [c for c in r.calls if c["callee"] == "foo"]
        assert len(foo_calls) == 2
        assert {c["line"] for c in foo_calls} == {2, 3}


# ════════════════════════════════════════════════════════════════════════
# Containment (R4.2, R4.3)
# ════════════════════════════════════════════════════════════════════════


class TestContainment:
    def test_parent_module_inside_and_outside(self, tmp_path):
        src = (
            "module host_mod\n"
            "contains\n"
            "  subroutine inner()\n"
            "  end subroutine inner\n"
            "end module host_mod\n"
            "subroutine outer()\n"
            "end subroutine outer\n"
        )
        f = _write(tmp_path / "mix.f90", src)
        parser = FortranParser(tmp_path)
        r = parser._fallback_extract(str(f), str(f))
        assert r is not None
        inner = next(s for s in r.subroutines if s["name"] == "inner")
        outer = next(s for s in r.subroutines if s["name"] == "outer")
        assert inner["parent_module"] == "host_mod"
        assert outer["parent_module"] is None
        assert inner["line_start"] == 3


# ════════════════════════════════════════════════════════════════════════
# Provenance counters (R5.1)
# ════════════════════════════════════════════════════════════════════════


class TestProvenanceCounters:
    def test_mixed_batch_counts(self, tmp_path):
        clean = _write(tmp_path / "a.f90", _CLEAN)
        recoverable = _write(tmp_path / "b.f90", _MALFORMED_RECOVERABLE)
        junk = _write(tmp_path / "c.f90", _UNRECOVERABLE)

        parser = FortranParser(tmp_path)
        # Clean parses via fparser2; recoverable falls back; junk fails both.
        r_clean = parser.parse_file(clean)
        r_rec = parser.parse_file(recoverable)
        r_junk = parser.parse_file(junk)

        assert r_clean is not None and r_clean.source == "fparser2"
        assert r_rec is not None and r_rec.source == "fallback"
        assert r_junk is None

        assert parser.stats["files_parsed_fparser2"] == 1
        assert parser.stats["files_parsed_fallback"] == 1
        assert parser.stats["files_failed"] == 1
        # Each file increments exactly one counter (R5.1 / Property 8).
        total = (
            parser.stats["files_parsed_fparser2"]
            + parser.stats["files_parsed_fallback"]
            + parser.stats["files_failed"]
        )
        assert total == 3


# ════════════════════════════════════════════════════════════════════════
# Never-raises (R1.5)
# ════════════════════════════════════════════════════════════════════════


class TestNeverRaises:
    def test_fallback_internal_error_yields_none(self, tmp_path):
        f = _write(tmp_path / "bad.f90", _MALFORMED_RECOVERABLE)
        parser = FortranParser(tmp_path)
        parser._parser = lambda _reader: None  # force the fallback path

        def _boom(_text):
            raise RuntimeError("fallback internal bug")

        parser._logical_lines = _boom
        # Must not propagate; counted as failed.
        assert parser.parse_file(f) is None
        assert parser.stats["files_failed"] == 1

    def test_fallback_read_error_yields_none(self, tmp_path):
        parser = FortranParser(tmp_path)
        # Path does not exist -> open raises OSError -> None (not a crash).
        assert parser._fallback_extract(
            str(tmp_path / "missing.f90"), str(tmp_path / "missing.f90")
        ) is None


# ════════════════════════════════════════════════════════════════════════
# Result shape invariance (R4.1, R4.5)
# ════════════════════════════════════════════════════════════════════════


class TestResultShape:
    def test_counting_helpers_run_on_fallback_result(self, tmp_path):
        src = (
            "module m\n"
            "contains\n"
            "  subroutine s()\n"
            "    call worker()\n"
            "    use other_mod\n"
            "  end subroutine s\n"
            "end module m\n"
        )
        f = _write(tmp_path / "shape.f90", src)
        parser = FortranParser(tmp_path)
        r = parser._fallback_extract(str(f), str(f))
        assert isinstance(r, FortranParseResult)
        assert r.source == "fallback"

        nodes = _result_node_counts(r)
        rels = _result_rel_counts(r)
        assert all(isinstance(v, int) and v >= 0 for v in nodes.values())
        assert all(isinstance(v, int) and v >= 0 for v in rels.values())
        assert nodes["FortranModule"] == 1
        assert nodes["FortranSubroutine"] == 1
        assert rels["CALLS"] == 1
        assert rels["USES"] == 1
        # Subroutine inside module → one CONTAINS edge.
        assert rels["CONTAINS"] == 1
