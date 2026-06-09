"""Property tests for the Fortran regex fallback extractor.

Feature: fortran-parse-fallback
  Property 1: Fallback never runs on success
  Property 2: Fallback never raises (arbitrary bytes)
  Property 3: Definition recovery completeness
  Property 4: Edge recovery completeness (incl. continuations)
  Property 5: No invented edges (control constructs / comments)
  Property 6: Result-shape invariance
  Property 7: Containment soundness
  Property 8: Provenance accounting

All properties run with Hypothesis at >= 100 examples. Definition/edge
properties drive the real ``_fallback_extract`` directly on generated source so
they do not depend on fparser2's exact failure surface; triggering and
provenance properties go through ``parse_file`` end-to-end.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).parents[2]))
sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from scripts._fortran_parser import FortranParser, FortranParseResult
from scripts.ingest_fortran_graph_v8 import (
    _result_node_counts,
    _result_rel_counts,
)

PROP_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ── helpers ─────────────────────────────────────────────────────────────

_SUFFIX = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789_", min_size=0, max_size=6
)


def _names(prefix: str, min_size: int, max_size: int):
    """Strategy producing a list of unique valid identifiers with a prefix."""
    return st.lists(_SUFFIX, min_size=min_size, max_size=max_size, unique=True).map(
        lambda suffixes: [prefix + s for s in suffixes]
    )


def _extract(src: str) -> FortranParseResult | None:
    """Write source to a temp worktree and run the fallback extractor directly."""
    d = tempfile.mkdtemp()
    try:
        path = os.path.join(d, "gen.f90")
        with open(path, "w") as f:
            f.write(src)
        return FortranParser(d)._fallback_extract(path, path)
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ════════════════════════════════════════════════════════════════════════
# Property 1: Fallback never runs on success (R1.1)
# ════════════════════════════════════════════════════════════════════════


class TestProperty1NoFallbackOnSuccess:
    @given(mods=_names("mod", min_size=1, max_size=5))
    @PROP_SETTINGS
    def test_valid_source_uses_fparser2(self, mods):
        src = "\n".join(f"module {m}\nend module {m}" for m in mods) + "\n"
        d = tempfile.mkdtemp()
        try:
            path = os.path.join(d, "ok.f90")
            with open(path, "w") as f:
                f.write(src)
            parser = FortranParser(d)
            called = {"fb": False}
            real = parser._fallback_extract

            def _spy(*a, **k):
                called["fb"] = True
                return real(*a, **k)

            parser._fallback_extract = _spy
            r = parser.parse_file(path)
            assert r is not None
            assert r.source == "fparser2"
            assert called["fb"] is False
        finally:
            shutil.rmtree(d, ignore_errors=True)


# ════════════════════════════════════════════════════════════════════════
# Property 2: Fallback never raises (R1.5)
# ════════════════════════════════════════════════════════════════════════


class TestProperty2NeverRaises:
    @given(blob=st.binary(min_size=0, max_size=400))
    @PROP_SETTINGS
    def test_arbitrary_bytes(self, blob):
        d = tempfile.mkdtemp()
        try:
            path = os.path.join(d, "rand.f90")
            with open(path, "wb") as f:
                f.write(blob)
            parser = FortranParser(d)
            result = parser.parse_file(path)  # must never raise
            assert result is None or isinstance(result, FortranParseResult)
        finally:
            shutil.rmtree(d, ignore_errors=True)


# ════════════════════════════════════════════════════════════════════════
# Property 3: Definition recovery completeness (R2.1-R2.4, R2.7)
# ════════════════════════════════════════════════════════════════════════


class TestProperty3DefinitionCompleteness:
    @given(
        mods=_names("mod", min_size=0, max_size=4),
        subs=_names("sub", min_size=0, max_size=4),
        funcs=_names("fn", min_size=0, max_size=4),
        progs=_names("prog", min_size=0, max_size=2),
        noise=st.lists(_SUFFIX, min_size=0, max_size=6),
    )
    @PROP_SETTINGS
    def test_all_definitions_recovered_no_closings(
        self, mods, subs, funcs, progs, noise
    ):
        lines: list[str] = []
        for m in mods:
            lines.append(f"module {m}")
            lines.append(f"end module {m}")
        for s in subs:
            lines.append(f"pure subroutine {s}()")
            lines.append(f"end subroutine {s}")
        for fn in funcs:
            lines.append(f"real function {fn}()")
            lines.append(f"end function {fn}")
        for p in progs:
            lines.append(f"program {p}")
            lines.append(f"end program {p}")
        # Comment noise is always stripped and can never match a keyword.
        for nz in noise:
            lines.append(f"! noise {nz}")
        src = "\n".join(lines) + "\n"

        r = _extract(src)
        if not (mods or subs or funcs or progs):
            # Nothing definitional → fallback recovers nothing.
            assert r is None
            return
        assert r is not None
        assert {m["name"] for m in r.modules} == set(mods)
        assert {s["name"] for s in r.subroutines} == set(subs)
        assert {f["name"] for f in r.functions} == set(funcs)
        assert {p["name"] for p in r.programs} == set(progs)


# ════════════════════════════════════════════════════════════════════════
# Property 4: Edge recovery completeness incl. continuations (R3.1-R3.3, R6.1)
# ════════════════════════════════════════════════════════════════════════


class TestProperty4EdgeCompleteness:
    @given(
        callees=_names("c", min_size=1, max_size=6),
        modules=_names("u", min_size=1, max_size=6),
        split=st.booleans(),
    )
    @PROP_SETTINGS
    def test_calls_and_uses_recovered(self, callees, modules, split):
        lines = ["subroutine driver()"]
        for c in callees:
            if split:
                lines.append(f"  call {c}( &")
                lines.append("       )")
            else:
                lines.append(f"  call {c}()")
        for m in modules:
            if split:
                lines.append(f"  use {m}, only: aa, &")
                lines.append("      bb")
            else:
                lines.append(f"  use {m}")
        lines.append("end subroutine driver")
        src = "\n".join(lines) + "\n"

        r = _extract(src)
        assert r is not None
        assert {c["callee"] for c in r.calls} == set(callees)
        assert {u["module"] for u in r.uses} == set(modules)
        # One call entry per generated call (each on a distinct logical line).
        assert len(r.calls) == len(callees)


# ════════════════════════════════════════════════════════════════════════
# Property 5: No invented edges (R6.2, R6.3)
# ════════════════════════════════════════════════════════════════════════


class TestProperty5NoInventedEdges:
    @given(
        names=_names("x", min_size=1, max_size=6),
        nums=st.lists(st.integers(min_value=0, max_value=99),
                      min_size=1, max_size=6),
    )
    @PROP_SETTINGS
    def test_control_constructs_and_comments(self, names, nums):
        # An anchor definition guarantees the result is non-None so we can
        # inspect calls/uses; the remaining lines must invent no edges.
        lines = ["subroutine anchor_sub()"]
        for nm in names:
            lines.append(f"  if ({nm} > 0) then")
            lines.append("  end if")
            lines.append(f"  y = arr({nm}_call_count)")
            lines.append(f"  ! call commented_{nm}")
            lines.append(f"  z = 1  ! use faked_{nm}")
        for nval in nums:
            lines.append(f"  do i = 1, {nval}")
            lines.append("  end do")
        lines.append("end subroutine anchor_sub")
        src = "\n".join(lines) + "\n"

        r = _extract(src)
        assert r is not None
        assert r.calls == []
        assert r.uses == []


# ════════════════════════════════════════════════════════════════════════
# Property 6: Result-shape invariance (R4.1, R4.5)
# ════════════════════════════════════════════════════════════════════════


class TestProperty6ShapeInvariance:
    @given(
        subs=_names("sub", min_size=0, max_size=4),
        callees=_names("c", min_size=0, max_size=4),
        modules=_names("u", min_size=0, max_size=4),
    )
    @PROP_SETTINGS
    def test_counts_are_nonneg_ints(self, subs, callees, modules):
        lines = ["module host"]
        for s in subs:
            lines.append(f"  subroutine {s}()")
            lines.append(f"  end subroutine {s}")
        for c in callees:
            lines.append(f"  call {c}()")
        for m in modules:
            lines.append(f"  use {m}")
        lines.append("end module host")
        src = "\n".join(lines) + "\n"

        r = _extract(src)
        assert r is not None  # the module alone guarantees recovery
        nodes = _result_node_counts(r)
        rels = _result_rel_counts(r)
        for v in list(nodes.values()) + list(rels.values()):
            assert isinstance(v, int) and v >= 0


# ════════════════════════════════════════════════════════════════════════
# Property 7: Containment soundness (R4.2)
# ════════════════════════════════════════════════════════════════════════


class TestProperty7Containment:
    @given(
        inside=_names("ins", min_size=0, max_size=4),
        outside=_names("out", min_size=0, max_size=4),
    )
    @PROP_SETTINGS
    def test_parent_module_only_inside_block(self, inside, outside):
        lines = ["module host_mod"]
        for s in inside:
            lines.append(f"  subroutine {s}()")
            lines.append(f"  end subroutine {s}")
        lines.append("end module host_mod")
        for s in outside:
            lines.append(f"subroutine {s}()")
            lines.append(f"end subroutine {s}")
        src = "\n".join(lines) + "\n"

        r = _extract(src)
        assert r is not None  # module host_mod always recovered
        by_name = {s["name"]: s["parent_module"] for s in r.subroutines}
        for s in inside:
            assert by_name[s] == "host_mod"
        for s in outside:
            assert by_name[s] is None
        # Every non-None parent_module corresponds to a recovered module.
        mod_names = {m["name"] for m in r.modules}
        for parent in by_name.values():
            if parent is not None:
                assert parent in mod_names


# ════════════════════════════════════════════════════════════════════════
# Property 8: Provenance accounting (R5.1)
# ════════════════════════════════════════════════════════════════════════


class TestProperty8ProvenanceAccounting:
    @given(blobs=st.lists(st.binary(min_size=0, max_size=200),
                          min_size=1, max_size=8))
    @PROP_SETTINGS
    def test_counters_sum_to_call_count(self, blobs):
        d = tempfile.mkdtemp()
        try:
            parser = FortranParser(d)
            for i, blob in enumerate(blobs):
                path = os.path.join(d, f"f_{i}.f90")
                with open(path, "wb") as f:
                    f.write(blob)
                parser.parse_file(path)
            total = (
                parser.stats["files_parsed_fparser2"]
                + parser.stats["files_parsed_fallback"]
                + parser.stats["files_failed"]
            )
            assert total == len(blobs)
        finally:
            shutil.rmtree(d, ignore_errors=True)
