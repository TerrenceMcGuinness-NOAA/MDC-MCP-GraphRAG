"""Unit tests for :mod:`tests.parity.parity_runner` (Requirements 13.1 – 13.7).

Exercises every comparison mode, extractor projection, the
``run_cases`` batch API, and the ``ParitySummary`` reporter. Uses
``build_mock_tool_caller`` from ``conftest.py`` so no network calls
happen — this matches the user instruction to stand the framework up
without running it against live servers.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from tests.conftest import build_mock_tool_caller
from tests.parity.parity_runner import (
    DEFAULT_TOLERANCE,
    ComparisonMode,
    ParityCase,
    ParityResult,
    ParityRunner,
    ParitySummary,
    _load_cases,
    _parse_headers,
    main,
)

pytestmark = pytest.mark.unit


# ── ComparisonMode enum basics ─────────────────────────────────────────


def test_comparison_mode_from_string_round_trip() -> None:
    for mode in ComparisonMode:
        assert ComparisonMode(mode.value) is mode


def test_comparison_mode_covers_required_modes() -> None:
    values = {m.value for m in ComparisonMode}
    assert values == {"exact", "set_equality", "tolerance"}


def test_default_tolerance_is_ten_percent() -> None:
    assert DEFAULT_TOLERANCE == 0.10


# ── ParityRunner: EXACT mode ───────────────────────────────────────────


async def test_exact_match_passes() -> None:
    shared = {"hits": [{"id": "a"}, {"id": "b"}]}
    runner = ParityRunner(
        build_mock_tool_caller({"search_documentation": shared}),
        build_mock_tool_caller({"search_documentation": shared}),
    )
    result = await runner.assert_parity(
        "search_documentation",
        {"query": "forecast"},
        comparison="exact",
        id_extractor=lambda r: [h["id"] for h in r["hits"]],
    )
    assert result.passed, result.describe()
    assert result.nodejs_result == ["a", "b"]
    assert result.python_result == ["a", "b"]


async def test_exact_mismatch_reports_divergence() -> None:
    runner = ParityRunner(
        build_mock_tool_caller({"t": {"hits": [{"id": "a"}, {"id": "b"}]}}),
        build_mock_tool_caller({"t": {"hits": [{"id": "a"}, {"id": "c"}]}}),
    )
    result = await runner.assert_parity(
        "t",
        {},
        comparison=ComparisonMode.EXACT,
        id_extractor=lambda r: [h["id"] for h in r["hits"]],
    )
    assert not result.passed
    assert result.divergence is not None
    assert "nodejs=['a', 'b']" in result.divergence
    assert "python=['a', 'c']" in result.divergence


async def test_exact_mode_without_extractor_compares_raw() -> None:
    runner = ParityRunner(
        build_mock_tool_caller({"t": {"ok": True}}),
        build_mock_tool_caller({"t": {"ok": True}}),
    )
    result = await runner.assert_parity("t", {})
    assert result.passed
    assert result.nodejs_result == {"ok": True}


# ── SET_EQUALITY mode ──────────────────────────────────────────────────


async def test_set_equality_ignores_order() -> None:
    runner = ParityRunner(
        build_mock_tool_caller({"t": ["foo", "bar", "baz"]}),
        build_mock_tool_caller({"t": ["baz", "foo", "bar"]}),
    )
    result = await runner.assert_parity("t", {}, comparison="set_equality")
    assert result.passed


async def test_set_equality_rejects_duplicate_mismatches() -> None:
    # Counter semantics: ['foo', 'foo'] must not match ['foo'].
    runner = ParityRunner(
        build_mock_tool_caller({"t": ["foo", "foo"]}),
        build_mock_tool_caller({"t": ["foo"]}),
    )
    result = await runner.assert_parity("t", {}, comparison="set_equality")
    assert not result.passed
    assert "missing in python" in result.divergence


async def test_set_equality_reports_extras_and_missing() -> None:
    runner = ParityRunner(
        build_mock_tool_caller({"t": ["a", "b"]}),
        build_mock_tool_caller({"t": ["b", "c"]}),
    )
    result = await runner.assert_parity("t", {}, comparison="set_equality")
    assert not result.passed
    assert "missing in python" in result.divergence
    assert "extra in python" in result.divergence


async def test_set_equality_projects_via_name_extractor() -> None:
    runner = ParityRunner(
        build_mock_tool_caller({"t": {"callers": [{"name": "f"}, {"name": "g"}]}}),
        build_mock_tool_caller({"t": {"callers": [{"name": "g"}, {"name": "f"}]}}),
    )
    result = await runner.assert_parity(
        "t",
        {},
        comparison="set_equality",
        name_extractor=lambda r: [c["name"] for c in r["callers"]],
    )
    assert result.passed


# ── TOLERANCE mode ─────────────────────────────────────────────────────


async def test_tolerance_within_threshold_passes() -> None:
    runner = ParityRunner(
        build_mock_tool_caller({"t": [0.900, 0.800, 0.700]}),
        build_mock_tool_caller({"t": [0.901, 0.795, 0.710]}),
    )
    result = await runner.assert_parity(
        "t", {}, comparison="tolerance", tolerance=0.02
    )
    assert result.passed, result.describe()
    assert result.extra["max_relative_delta"] < 0.02


async def test_tolerance_exceeds_threshold_fails() -> None:
    runner = ParityRunner(
        build_mock_tool_caller({"t": [0.9]}),
        build_mock_tool_caller({"t": [0.5]}),
    )
    result = await runner.assert_parity(
        "t", {}, comparison="tolerance", tolerance=0.10
    )
    assert not result.passed
    assert "index 0" in result.divergence


async def test_tolerance_uses_default_when_not_specified() -> None:
    # 9% delta — within the default 10% but outside a tight override.
    runner = ParityRunner(
        build_mock_tool_caller({"t": [1.00]}),
        build_mock_tool_caller({"t": [0.91]}),
    )
    result = await runner.assert_parity("t", {}, comparison="tolerance")
    assert result.passed
    assert result.extra["tolerance"] == DEFAULT_TOLERANCE


async def test_tolerance_length_mismatch_is_divergence() -> None:
    runner = ParityRunner(
        build_mock_tool_caller({"t": [0.5, 0.6]}),
        build_mock_tool_caller({"t": [0.5]}),
    )
    result = await runner.assert_parity("t", {}, comparison="tolerance")
    assert not result.passed
    assert "length mismatch" in result.divergence


async def test_tolerance_near_zero_guarded() -> None:
    """|x - y| / max(|x|, |y|, 1) — ``1.0`` guard prevents blow-up."""
    runner = ParityRunner(
        build_mock_tool_caller({"t": [0.0]}),
        build_mock_tool_caller({"t": [0.05]}),
    )
    result = await runner.assert_parity(
        "t", {}, comparison="tolerance", tolerance=0.10
    )
    # 0.05 / 1.0 = 0.05, within 0.10.
    assert result.passed


async def test_tolerance_projects_via_score_extractor() -> None:
    runner = ParityRunner(
        build_mock_tool_caller({"t": {"hits": [{"score": 0.9}, {"score": 0.8}]}}),
        build_mock_tool_caller({"t": {"hits": [{"score": 0.89}, {"score": 0.81}]}}),
    )
    result = await runner.assert_parity(
        "t",
        {},
        comparison="tolerance",
        tolerance=0.02,
        score_extractor=lambda r: [h["score"] for h in r["hits"]],
    )
    assert result.passed


# ── exception handling ────────────────────────────────────────────────


async def test_exception_on_node_side_is_divergence() -> None:
    def _raise(_args: dict) -> None:
        raise RuntimeError("node exploded")

    runner = ParityRunner(
        build_mock_tool_caller({"t": _raise}),
        build_mock_tool_caller({"t": {"ok": True}}),
    )
    result = await runner.assert_parity("t", {})
    assert not result.passed
    assert "nodejs raised" in result.divergence
    assert "node exploded" in result.divergence


async def test_exception_on_python_side_is_divergence() -> None:
    def _raise(_args: dict) -> None:
        raise ValueError("python exploded")

    runner = ParityRunner(
        build_mock_tool_caller({"t": {"ok": True}}),
        build_mock_tool_caller({"t": _raise}),
    )
    result = await runner.assert_parity("t", {})
    assert not result.passed
    assert "python raised" in result.divergence


# ── ParityCase / run_cases ─────────────────────────────────────────────


async def test_run_cases_aggregates_pass_and_fail() -> None:
    runner = ParityRunner(
        build_mock_tool_caller(
            {"a": {"x": 1}, "b": {"x": 1}, "c": ["foo"]}
        ),
        build_mock_tool_caller(
            {"a": {"x": 1}, "b": {"x": 2}, "c": ["foo"]}
        ),
    )
    cases = [
        ParityCase("a", {}, ComparisonMode.EXACT),
        ParityCase("b", {}, ComparisonMode.EXACT),
        ParityCase("c", {}, ComparisonMode.SET_EQUALITY),
    ]
    summary = await runner.run_cases(cases)
    assert summary.total == 3
    assert summary.passed == 2
    assert summary.failed == 1
    assert len(summary.divergences) == 1
    assert summary.divergences[0].tool_name == "b"


async def test_run_cases_module_filter() -> None:
    runner = ParityRunner(
        build_mock_tool_caller({"a": 1, "b": 2}),
        build_mock_tool_caller({"a": 1, "b": 2}),
    )
    cases = [
        ParityCase("a", {}, ComparisonMode.EXACT, module="semantic_search"),
        ParityCase("b", {}, ComparisonMode.EXACT, module="code_analysis"),
    ]
    summary = await runner.run_cases(cases, module="semantic_search")
    assert summary.total == 1
    assert summary.results[0].tool_name == "a"


async def test_parity_case_effective_tolerance_default_and_override() -> None:
    assert ParityCase("a", {}).effective_tolerance() == DEFAULT_TOLERANCE
    assert ParityCase("a", {}, tolerance=0.25).effective_tolerance() == 0.25


# ── Concurrency: both sides run in parallel ────────────────────────────


async def test_both_callers_dispatched_concurrently() -> None:
    # Each side sleeps 50ms. If serial the total would be ~100ms; in
    # parallel it should be close to 50ms. Use a generous 90ms upper
    # bound to avoid flakes on slow CI.
    import time as _time

    runner = ParityRunner(
        build_mock_tool_caller({"t": "x"}, latency_ms=50),
        build_mock_tool_caller({"t": "x"}, latency_ms=50),
    )
    start = _time.perf_counter()
    result = await runner.assert_parity("t", {})
    elapsed_ms = (_time.perf_counter() - start) * 1000
    assert result.passed
    assert elapsed_ms < 90, f"expected parallel dispatch (<90ms), got {elapsed_ms:.1f}ms"


# ── ParitySummary reporter ─────────────────────────────────────────────


def test_summary_render_report_empty() -> None:
    s = ParitySummary()
    report = s.render_report()
    assert "Total: 0" in report
    assert "no parity cases executed" in report


def test_summary_render_report_includes_divergences() -> None:
    s = ParitySummary()
    s.add(
        ParityResult(
            tool_name="t",
            arguments={"q": "x"},
            comparison=ComparisonMode.EXACT,
            passed=True,
        )
    )
    s.add(
        ParityResult(
            tool_name="u",
            arguments={"q": "y"},
            comparison=ComparisonMode.TOLERANCE,
            passed=False,
            divergence="scores too far apart",
        )
    )
    report = s.render_report()
    assert "Total: 2" in report
    assert "Passed: 1" in report
    assert "Failed: 1" in report
    assert "u / tolerance" in report
    assert "scores too far apart" in report


def test_summary_to_dict_tracks_per_tool_counts() -> None:
    s = ParitySummary()
    for tool in ("a", "a", "b"):
        s.add(
            ParityResult(
                tool_name=tool,
                arguments={},
                comparison=ComparisonMode.EXACT,
                passed=True,
            )
        )
    data = s.to_dict()
    assert data["per_tool"]["a"] == 2
    assert data["per_tool"]["b"] == 1
    assert data["total"] == 3


# ── CLI helpers ────────────────────────────────────────────────────────


def test_parse_headers_valid_pairs() -> None:
    assert _parse_headers(["Authorization=Bearer x", "X-Foo=bar"]) == {
        "Authorization": "Bearer x",
        "X-Foo": "bar",
    }


def test_parse_headers_strips_whitespace() -> None:
    assert _parse_headers(["  K  =  v  "]) == {"K": "v"}


def test_parse_headers_rejects_missing_equals() -> None:
    with pytest.raises(ValueError, match="invalid header"):
        _parse_headers(["no-equals-here"])


def test_load_cases_roundtrip(tmp_path: Path) -> None:
    data = [
        {"tool_name": "a", "arguments": {"q": "x"}, "comparison": "exact"},
        {"tool_name": "b", "comparison": "tolerance", "tolerance": 0.2, "module": "semantic_search"},
    ]
    p = tmp_path / "cases.json"
    p.write_text(json.dumps(data))
    cases = _load_cases(str(p))
    assert len(cases) == 2
    assert cases[0].comparison is ComparisonMode.EXACT
    assert cases[0].arguments == {"q": "x"}
    assert cases[1].tolerance == 0.2
    assert cases[1].module == "semantic_search"
    assert cases[1].arguments == {}  # default when missing


def test_load_cases_rejects_non_array(tmp_path: Path) -> None:
    p = tmp_path / "cases.json"
    p.write_text('{"not": "an array"}')
    with pytest.raises(ValueError, match="must contain a JSON array"):
        _load_cases(str(p))


def test_main_without_cases_file_prints_help_and_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # No --cases-file means no live calls — just confirm the CLI doesn't
    # crash and returns 0 when there's nothing to compare.
    rc = main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "No cases provided" in out


# ── ParityResult.describe() formatting ─────────────────────────────────


def test_result_describe_pass_and_fail_shapes() -> None:
    passed = ParityResult(
        tool_name="t",
        arguments={"q": "x"},
        comparison=ComparisonMode.EXACT,
        passed=True,
    )
    assert "[PASS]" in passed.describe()

    failed = ParityResult(
        tool_name="t",
        arguments={"q": "x"},
        comparison=ComparisonMode.EXACT,
        passed=False,
        nodejs_result=[1, 2],
        python_result=[1, 3],
        divergence="mismatch",
    )
    text = failed.describe()
    assert "[FAIL]" in text
    assert "mismatch" in text
    assert "nodejs: [1, 2]" in text
    assert "python: [1, 3]" in text
