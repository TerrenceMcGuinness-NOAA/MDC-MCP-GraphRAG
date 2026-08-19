"""Nightly-wrapper integration tests (Task 4.2).

Feature: default-tenant-freeze-retirement.

Four groups, matching the task's structure:

1. ``get_quality_metrics`` reading a log the Benchmark_Harness produced,
   driven hermetically through the same Registration_Shim
   (``scripts.run_benchmark._ToolShim``) the harness itself uses, with
   ``utility.register``'s explicit ``state_dir`` as the seam -- no new
   production code needed (R7.4, R7.5).
2. The one genuine subprocess test: running ``run_benchmark_nightly.sh``
   once and asserting the log grows by exactly one line (R7.1).
3. The log-history table, extracted from the wrapper's inline
   ``python3 -`` heredoc and driven directly against synthetic logs of
   0, 1, 2, and 8 lines -- including the two-line trap where the outer
   guard reports ``ok`` while every metric is skipped, and the 8-line
   case that pins the strict ``<`` at exactly a 10.00 percent drop.
4. A byte-comparison of the wrapper's comment-stripped content against
   its recorded pre-change form, proving Task 4.1 changed only comments
   (R7.3).

Runs with no AWS credential and no reachable MCP server. The subprocess
test in group 2 points ``MCP_BENCHMARK_CMD`` at ``run_benchmark.py`` with
``DB_BACKEND=aws`` and no endpoint environment variables set. That
combination is genuinely hermetic and not a coincidental one: reading
``src/data/backend_selector.py`` shows ``_build_vector_db``/
``_build_graph_db`` return ``None`` without any socket call when their
endpoint env var is empty, and ``_connect_with_degrade`` only calls
``.connect()`` on a non-``None`` slot. So the harness runs end to end
(corpus load, closure collection, invocation, record write) with a fully
degraded facade and zero network traffic -- every case records an
``error`` and the run is the boundary case of Requirement 3 criterion 4.

CONTRADICTION WITH THE TASK TEXT, reported per the standing instruction to
report rather than route around: the task describes running the wrapper
"with the benchmark command pointed at the harness in injected-data mode."
No such mode exists on ``run_benchmark.py``'s CLI. ``main()`` (Task 3.3)
takes ``--corpus``, ``--category``, ``--dry-run``, ``--tenant-only``,
``--default-only``, and ``--results-dir`` only; it always calls
``run_benchmark(..., catalog=catalog, results_dir=...)`` with no ``data=``
argument, so ``_run_benchmark_async`` always takes the ``owns_data`` branch
and calls ``create_data_access(config)`` -- there is no env var or CLI flag
that threads a caller-supplied facade through the CLI entry point the way
``run_benchmark()`` itself accepts one as a Python argument. The empty-
endpoint ``DB_BACKEND=aws`` combination used here is hermetic (confirmed by
reading the adapter-construction code, not assumed) and exercises the real
subprocess path end to end, but it is a degraded-facade run rather than the
"injected-data" run the task text describes, and it cannot demonstrate a
*scored* (non-zero-coverage) append the way an injected recorded-response
facade would. Task 3's CLI surface would need a data-injection seam (e.g.
an env var naming a factory, mirroring ``MCP_BENCHMARK_RESULTS_DIR``'s
pattern) to close this gap; that is a change to ``scripts/run_benchmark.py``
this task does not own and the design/tasks docs do not call for.
"""

from __future__ import annotations

import json
import os
import shutil
import statistics
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.run_benchmark import _ToolShim
from src.tools import utility

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[3]
_WRAPPER_PATH = (
    _REPO_ROOT
    / "mcp_server_python"
    / "scripts"
    / "run_benchmark_nightly.sh"
)
_NODE_DIR = _REPO_ROOT / "mcp_server_node"


# ---------------------------------------------------------------------------
# Group 1: reading a Python-shaped log through the same Registration_Shim
# the harness uses (R7.4, R7.5) -- no live log, no new production code.
# ---------------------------------------------------------------------------


def _python_record(
    timestamp: str,
    *,
    coverage: float = 0.9,
    precision: float = 0.85,
    mrr: float = 0.9,
    recall: float = 0.9,
) -> dict:
    """Build one Python-shaped Benchmark_Run_Record.

    Shape matches ``scripts.run_benchmark._build_record``'s output:
    ``timestamp``, ``harness``, ``corpus_version``, ``total_queries``,
    ``overall``, and a ``categories`` object keyed by all six
    Benchmark_Category names -- exactly the fields
    ``_render_quality_metrics`` reads with ``.get`` (R7.4's "no field the
    record carries renders as a placeholder" applies to these fields).
    """
    scope = {
        "precision_at_k": precision,
        "recall_at_k": recall,
        "mrr": mrr,
        "coverage": coverage,
        "latency_p50_ms": 120,
        "latency_p95_ms": 340,
    }
    categories = {
        name: dict(scope)
        for name in (
            "code_structure",
            "semantic_search",
            "architecture",
            "ee2_compliance",
            "operational",
            "cross_language",
        )
    }
    return {
        "timestamp": timestamp,
        "version": "1.0.0",
        "harness": "python:run_benchmark.py:aws:titan1024",
        "corpus_version": "1.1.0",
        "total_queries": 60,
        "overall": dict(scope),
        "categories": categories,
        "tenant_overall": dict(scope),
        "tenant_categories": {k: dict(scope) for k in categories},
        "queries": [],
        "regression": {"compared_to": None, "warnings": [], "errors": []},
    }


def _register_utility_via_shim(data, state_dir: Path) -> _ToolShim:
    """Register ``utility`` against a fresh ``_ToolShim``.

    Reusing the harness's own Registration_Shim rather than importing
    ``_render_quality_metrics`` directly is the point: the integration
    test and the harness cannot drift apart in how they reach a tool. If
    the shim ever stopped collecting correctly, this test would fail
    too, instead of quietly exercising a path nothing else uses.
    """
    shim = _ToolShim()
    utility.register(shim, data, state_dir=str(state_dir))
    return shim


class TestReadingAPythonShapedLogThroughTheShim:
    """R7.4, R7.5: no missing-field placeholder, comparison block renders."""

    def test_overall_and_all_six_category_blocks_render(self, tmp_path):
        state_dir = tmp_path
        log_path = state_dir / "quality_metrics.jsonl"
        with open(log_path, "w", encoding="utf-8") as fh:
            fh.write(
                json.dumps(_python_record("2026-08-18T04:00:00.000Z"))
                + "\n"
            )
            fh.write(
                json.dumps(_python_record("2026-08-19T04:00:00.000Z"))
                + "\n"
            )

        shim = _register_utility_via_shim(None, state_dir)
        get_quality_metrics = shim.tools["get_quality_metrics"]

        import asyncio

        rendered = asyncio.run(get_quality_metrics(compare=False))

        assert "# RAG Quality Metrics" in rendered
        # `_render_category_block` renders humanized labels (via
        # `_fmt_category_name`), e.g. "Cross Language" for
        # "cross_language" -- not the raw corpus key.
        for label in (
            "Code Structure",
            "Semantic Search",
            "Architecture",
            "Ee2 Compliance",
            "Operational",
            "Cross Language",
        ):
            assert label in rendered, (
                f"missing category block {label!r} in:\n{rendered}"
            )

    def test_comparison_block_renders_when_asked(self, tmp_path):
        state_dir = tmp_path
        log_path = state_dir / "quality_metrics.jsonl"
        with open(log_path, "w", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    _python_record("2026-08-18T04:00:00.000Z", coverage=0.95)
                )
                + "\n"
            )
            fh.write(
                json.dumps(
                    _python_record("2026-08-19T04:00:00.000Z", coverage=0.90)
                )
                + "\n"
            )

        shim = _register_utility_via_shim(None, state_dir)
        get_quality_metrics = shim.tools["get_quality_metrics"]

        import asyncio

        without_compare = asyncio.run(get_quality_metrics(compare=False))
        with_compare = asyncio.run(get_quality_metrics(compare=True))

        assert "## Regression" not in without_compare
        assert "## Regression" in with_compare

    def test_no_missing_field_placeholder_for_a_field_the_record_carries(
        self, tmp_path
    ):
        state_dir = tmp_path
        log_path = state_dir / "quality_metrics.jsonl"
        record = _python_record("2026-08-19T04:00:00.000Z")
        with open(log_path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

        shim = _register_utility_via_shim(None, state_dir)
        get_quality_metrics = shim.tools["get_quality_metrics"]

        import asyncio

        rendered = asyncio.run(get_quality_metrics(compare=True))

        # The record supplies every field ``_render_quality_metrics`` reads
        # via ``.get`` with a fallback ("Unknown" / "N/A"), so none of
        # those fallbacks should appear for this one-line, single-run
        # render (the "N/A" comparison-unavailable message is a distinct,
        # legitimate one-snapshot case, not a missing-field placeholder --
        # asserted separately above).
        assert "Unknown" not in rendered
        assert record["corpus_version"] in rendered
        assert record["timestamp"] in rendered


# ---------------------------------------------------------------------------
# Group 2: the one genuine subprocess test (R7.1).
# ---------------------------------------------------------------------------


class TestOneWrapperInvocationAppendsExactlyOneLine:
    """R7.1: run the wrapper once; the log grows by exactly one line.

    Uses the hermetic ``DB_BACKEND=aws``-with-no-endpoints combination
    described in the module docstring's contradiction note. One
    invocation, not a sweep -- nothing varies with input here and each
    iteration costs a subprocess.
    """

    def test_log_grows_by_exactly_one_line(self, tmp_path):
        if shutil.which("bash") is None:
            pytest.skip("bash not available in this environment")

        state_dir = tmp_path / "state"
        results_dir = tmp_path / "results"
        node_test_dir = tmp_path / "node_test_dir"
        state_dir.mkdir()
        results_dir.mkdir()
        node_test_dir.mkdir()

        # Pre-seed the log with one line so "grew by exactly one" is a
        # real delta rather than 0 -> 1, which could pass vacuously if the
        # append step silently no-op'd.
        seed_path = state_dir / "quality_metrics.jsonl"
        seed_path.write_text(
            json.dumps(_python_record("2026-08-10T04:00:00.000Z")) + "\n",
            encoding="utf-8",
        )

        mcp_python_dir = _REPO_ROOT / "mcp_server_python"
        # The wrapper `cd`s into ${NODE_DIR} before evaluating
        # BENCHMARK_CMD (step 2), so the harness must be named by an
        # absolute path -- a path relative to mcp_server_python would
        # resolve against node_test_dir instead and fail to open.
        benchmark_script = mcp_python_dir / "scripts" / "run_benchmark.py"
        benchmark_cmd = (
            f"{sys.executable} {benchmark_script} "
            f"--results-dir {results_dir}"
        )

        env = dict(os.environ)
        env.update(
            {
                "MCP_NODE_DIR": str(node_test_dir),
                "MCP_HOST_STATE_DIR": str(state_dir),
                "MCP_CONTAINER_STATE_DIR": str(state_dir),
                "MCP_BENCHMARK_RESULTS_DIR": str(results_dir),
                "MCP_BENCHMARK_CMD": benchmark_cmd,
                "MCP_SECRETS_FILE": str(tmp_path / "no-such-secrets.env"),
                "DB_BACKEND": "aws",
                "PYTHONPATH": str(mcp_python_dir),
            }
        )
        # Hermetic: no endpoint set means create_data_access() builds both
        # adapter slots as None without ever touching a socket (see the
        # module docstring). Explicitly clear in case the ambient
        # environment carries either.
        env.pop("OPENSEARCH_ENDPOINT", None)
        env.pop("NEPTUNE_ENDPOINT", None)

        proc = subprocess.run(
            ["bash", str(_WRAPPER_PATH)],
            cwd=str(mcp_python_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

        assert seed_path.is_file(), (
            "wrapper did not produce a log file at all: "
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )
        lines = [
            ln for ln in seed_path.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        assert len(lines) == 2, (
            f"expected the log to grow from 1 to 2 lines, got {len(lines)}: "
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )
        appended = json.loads(lines[-1])
        assert appended["timestamp"] != "2026-08-10T04:00:00.000Z"
        assert "overall" in appended
        assert "categories" in appended


# ---------------------------------------------------------------------------
# Group 3: the log-history table (0, 1, 2, 8 lines), driven directly
# against the wrapper's own regression-check logic.
# ---------------------------------------------------------------------------


def _extract_regression_check_block() -> str:
    """Pull the inline ``python3 - ... <<'PY' ... PY`` heredoc verbatim.

    The Regression_Check is not a separate file -- it is embedded in
    ``run_benchmark_nightly.sh`` between a ``<<'PY'`` opener and a bare
    ``PY`` terminator. Extracting it lets the check be driven directly
    against synthetic logs without waiting for nights, and without
    re-implementing the comparison logic by hand (which would test a
    reimplementation, not the wrapper).
    """
    text = _WRAPPER_PATH.read_text(encoding="utf-8")
    start_marker = "<<'PY'\n"
    end_marker = "\nPY\n"
    start = text.index(start_marker) + len(start_marker)
    end = text.index(end_marker, start)
    return text[start:end]


_REGRESSION_CHECK_SOURCE = _extract_regression_check_block()


def _run_regression_check(
    log_lines: list[dict], *, window: int = 7, pct: float = 10.0, tmp_path
) -> tuple[dict, list[str]]:
    """Execute the extracted block against a synthetic log.

    Returns ``(stdout_status_json, stderr_error_lines)``. Runs the block
    as a real subprocess with the same argv shape
    (``path, window, pct``) the wrapper's ``python3 -`` invocation uses,
    so the exact ``sys.argv`` handling is exercised rather than bypassed.
    """
    log_path = tmp_path / "quality_metrics.jsonl"
    with open(log_path, "w", encoding="utf-8") as fh:
        for row in log_lines:
            fh.write(json.dumps(row) + "\n")

    proc = subprocess.run(
        [sys.executable, "-", str(log_path), str(window), str(pct)],
        input=_REGRESSION_CHECK_SOURCE,
        capture_output=True,
        text=True,
        timeout=30,
    )
    stdout_lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    status = json.loads(stdout_lines[-1]) if stdout_lines else {}
    error_lines = [
        ln for ln in proc.stderr.splitlines() if ln.startswith("[ERROR]")
    ]
    return status, error_lines


def _row(coverage: float, mrr: float, precision: float) -> dict:
    return {
        "categories": {
            "operational": {
                "coverage": coverage,
                "mrr": mrr,
                "precision_at_k": precision,
            }
        },
        "overall": {
            "coverage": coverage,
            "mrr": mrr,
            "precision_at_k": precision,
        },
    }


class TestLogHistoryTable:
    """The 0/1/2/8-line rows of the design's log-history table."""

    def test_zero_lines_reports_insufficient_history_no_error(
        self, tmp_path
    ):
        status, errors = _run_regression_check([], tmp_path=tmp_path)
        assert status.get("status") == "insufficient_history"
        assert status.get("snapshots") == 0
        assert errors == []

    def test_one_line_reports_insufficient_history_no_error(self, tmp_path):
        status, errors = _run_regression_check(
            [_row(1.0, 1.0, 1.0)], tmp_path=tmp_path
        )
        assert status.get("status") == "insufficient_history"
        assert status.get("snapshots") == 1
        assert errors == []

    def test_two_lines_reports_ok_but_evaluates_no_metric(self, tmp_path):
        """Row 3 of the design's table -- the trap.

        Two lines satisfy the wrapper's OUTER guard (``len(rows) < 2``),
        so the check clears that guard and prints ``status: ok`` -- but
        the PER-METRIC guard (``if len(vals) < 2: continue``, line 168)
        means the single prior row can never supply two history values
        for any metric, so every metric is silently skipped. "The check
        reported ok" and "the gate is armed" are different statements on
        the second night after a history reset (e.g. right after the
        Requirement 5 criterion 4 changeover archive): a reviewer citing
        the benchmark then would be citing nothing. Confirmed here by
        making the second row a catastrophic drop from the first (which
        would obviously fire once the gate is truly armed) and asserting
        it does NOT fire.
        """
        status, errors = _run_regression_check(
            [_row(1.0, 1.0, 1.0), _row(0.01, 0.01, 0.01)],
            tmp_path=tmp_path,
        )
        assert status.get("status") == "ok"
        assert errors == [], (
            "the gate must not fire on two lines -- the per-metric "
            "len(vals) < 2 guard skips every metric even though the "
            "outer guard alone would look armed"
        )

    def test_eight_lines_exact_threshold_passes_just_below_fires(
        self, tmp_path
    ):
        """Row 4 of the table, pinning the strict ``<`` at line 171.

        7 history rows all at coverage 1.0 (median 1.0). One case sits at
        *exactly* 10.00% below the median (0.90) -- per
        ``cur_v < med * (1 - pct / 100.0)`` with ``pct=10`` that is
        ``0.90 < 0.90``, which is False, so it must PASS (no ERROR line).
        A second case sits just below that (0.899999) and must FIRE. An
        off-by-one in the comparison operator (e.g. ``<=``) would
        otherwise surface only in production.
        """
        history = [_row(1.0, 1.0, 1.0) for _ in range(7)]

        exact_status, exact_errors = _run_regression_check(
            history + [_row(0.90, 0.90, 0.90)], tmp_path=tmp_path
        )
        assert exact_errors == [], (
            "a drop of exactly 10.00 percent must PASS under the strict "
            "'<' comparison"
        )
        assert exact_status.get("status") == "ok"

        just_below_status, just_below_errors = _run_regression_check(
            history + [_row(0.899999, 0.899999, 0.899999)],
            tmp_path=tmp_path,
        )
        assert just_below_errors, (
            "a drop of just over 10 percent must FIRE"
        )
        assert any(
            "coverage" in ln or "precision_at_k" in ln or "mrr" in ln
            for ln in just_below_errors
        )

    def test_eight_lines_median_matches_statistics_median(self, tmp_path):
        """Sanity check that the extracted block truly uses a live median
        over the trailing window rather than e.g. an average, so the
        exact-threshold pin above is measuring the real comparison."""
        values = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 0.95]
        history = [_row(v, v, v) for v in values]
        median = statistics.median(values)
        current = median * 0.905  # a 9.5% drop -> must not fire

        status, errors = _run_regression_check(
            history + [_row(current, current, current)], tmp_path=tmp_path
        )
        assert errors == []
        assert status.get("status") == "ok"


# ---------------------------------------------------------------------------
# Group 4: the wrapper is functionally unchanged (R7.3).
# ---------------------------------------------------------------------------


#: The wrapper's content immediately before Task 4.1, as a separate
#: fixture file rather than an embedded Python string literal.
#:
#: Two reasons it lives on disk instead of inline. First, it is a
#: byte-for-byte capture of a real ``.sh`` file (captured from
#: ``git show HEAD:mcp_server_python/scripts/run_benchmark_nightly.sh``
#: at the commit preceding this feature's changes) whose own lines
#: legitimately exceed 79 characters -- bash is not subject to PEP 8, and
#: reformatting the captured text to satisfy this file's own pycodestyle
#: gate would falsify the very byte-fidelity the fixture exists to
#: guarantee. pycodestyle only lints ``.py`` files, so a ``.sh`` fixture
#: sidesteps that without touching a single captured character. Second,
#: reading from disk means a diff against the fixture file is a normal,
#: reviewable text diff rather than a diff buried inside an escaped
#: Python string.
#:
#: Byte-identity with the pre-4.1 wrapper was confirmed once, at authoring
#: time, via ``diff`` against a ``git show`` capture; it is not re-derived
#: from git at test time (fragile after a real commit lands -- HEAD would
#: no longer be "pre-change"). Task 4.1 is documented as a comment-only
#: edit adding a threshold-reconciliation note; this fixture is what
#: "before" means for that claim.
_PRE_CHANGE_WRAPPER_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "run_benchmark_nightly.pre_change.sh"
)
_PRE_CHANGE_WRAPPER = _PRE_CHANGE_WRAPPER_PATH.read_text(encoding="utf-8")


def _strip_shell_comments(text: str) -> str:
    """Strip whole-line ``#``-comments and blank lines.

    What this covers: any line whose content, after stripping leading
    whitespace, begins with ``#`` (including the shebang) is dropped
    entirely; all other lines are kept verbatim, including their leading
    / trailing whitespace and any inline ``#`` that appears after real
    code.

    What this does NOT cover, and why it is still correct for this file:
    a general shell-comment stripper would need to track quoting state to
    avoid treating a ``#`` inside a string literal as a comment opener.
    This file has no line where a ``#`` appears both inside a string and
    at the exact position that would be ambiguous with a whole-line
    comment -- verified by inspection of every line above -- so the
    simpler whole-line rule is sufficient here. It would NOT be sufficient
    as a general-purpose bash comment stripper, and this helper is not
    exported or reused outside this file for that reason. Blank lines are
    also dropped so that Task 4.1's added comment block (which introduces
    blank comment-adjacent lines) cannot itself register as a content
    difference.
    """
    kept = []
    for line in text.splitlines():
        if line.strip().startswith("#"):
            continue
        if not line.strip():
            continue
        kept.append(line)
    return "\n".join(kept)


class TestWrapperIsFunctionallyUnchanged:
    """R7.3: comment-stripped content matches the pre-change form exactly."""

    def test_comment_stripped_content_matches_pre_change(self):
        current = _WRAPPER_PATH.read_text(encoding="utf-8")
        stripped_current = _strip_shell_comments(current)
        stripped_pre_change = _strip_shell_comments(_PRE_CHANGE_WRAPPER)

        assert stripped_current == stripped_pre_change, (
            "the wrapper's functional content changed -- Task 4.1 is "
            "specified as a comment-and-default-value-only edit, and the "
            "default was already 10, so no functional line should differ"
        )

    def test_the_fixture_itself_is_not_accidentally_stripped_to_nothing(
        self,
    ):
        # A cheap guard against the stripper degenerating (e.g. a typo
        # that drops every line): the stripped form must still contain
        # the load-bearing comparison operator this feature pins.
        stripped = _strip_shell_comments(_PRE_CHANGE_WRAPPER)
        assert "cur_v < med * (1 - pct / 100.0)" in stripped
        assert 'REGRESSION_PCT="${MCP_BENCHMARK_REGRESSION_PCT:-10}"' in (
            stripped
        )
