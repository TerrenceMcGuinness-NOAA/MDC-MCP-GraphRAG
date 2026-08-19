"""Python RAG benchmark harness (Phase 80 / default-tenant-freeze-retirement).

Mirrors ``mcp_server_node/scripts/run_benchmark.js``: loads the shared
ground-truth corpus, invokes registered tool closures, computes the same
quality metrics by the same formulas, and writes the result shape
``run_benchmark_nightly.sh`` normalises into ``quality_metrics.jsonl``.

Differs from the Node harness in three ways, all recorded in the design:

1. A Python Tool_Closure returns ``str``, so text extraction is the
   identity -- there is no ``content`` list to unwrap. The single-text
   consequence makes per-case ``mrr`` either ``0`` or ``1`` and therefore
   equal to the ``covered`` flag (the Gated_Metric triple
   ``{mrr, precision_at_k, coverage}`` has rank two -- two independent
   signals, not three).
2. Tenant-scoped cases are read from the corpus's ``tenant_categories``
   container and reported separately (``tenant_overall`` /
   ``tenant_categories``), so a Default_Tenant regression and a
   Prefixed_Tenant regression are distinguishable.
3. The ``categories`` object is computed from Default_Tenant cases only,
   so it stays comparable with the Node-harness history already in the
   Quality_Metrics_Log.

Scope note (Tasks 1.3, 3.1, 3.2, 3.3)
-------------------------------------
This module lands the data model and the pure scoring arithmetic
(Task 1.3 -- ``BenchmarkCase``, ``CaseResult``, ``ScopeMetrics``,
``Corpus``, ``load_corpus``, ``score_case``, ``aggregate``), the closure
collection through a ``FastMCP`` stand-in (Task 3.1 -- ``_ToolShim``,
``build_tool_map``), the invocation orchestration plus the emitted
Benchmark_Run_Record (Task 3.2 -- ``run_benchmark``, ``BenchmarkRun``),
and the command-line entry point (Task 3.3 -- ``main``).
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import math
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config.environment import load_config
from src.tenancy.runtime import get_catalog

# ---------------------------------------------------------------------------
# Corpus vocabulary
# ---------------------------------------------------------------------------

#: The six Benchmark_Category names, in corpus order. A shared constant so
#: the CLI's ``--category`` validation, the generators, and the aggregation
#: keys draw from one definition.
CATEGORY_NAMES: tuple[str, ...] = (
    "code_structure",
    "semantic_search",
    "architecture",
    "ee2_compliance",
    "operational",
    "cross_language",
)

#: The 15 tool names the corpus reaches once ``tenant_categories`` lands
#: (the 13 in the Corpus_Baseline_Set plus the two prefixed-status reporter
#: tools ``get_knowledge_base_status`` and ``check_knowledge_integrity``).
#: Ownership of each to a tool module is a Task 3.1 concern; this tuple is
#: the reference set the ``benchmark_cases()`` generator samples over.
CORPUS_TOOL_NAMES: tuple[str, ...] = (
    "analyze_code_structure",
    "find_dependencies",
    "find_callers_callees",
    "trace_full_execution_chain",
    "search_documentation",
    "explain_with_context",
    "get_knowledge_base_status",
    "check_knowledge_integrity",
    "search_architecture",
    "get_code_context",
    "trace_data_flow",
    "search_ee2_standards",
    "get_operational_guidance",
    "list_job_scripts",
    "get_job_details",
)

#: The eight declared Benchmark_Case fields. ``tenant_scoped`` is derived,
#: not read, so it is not in this set (see :class:`BenchmarkCase`).
_REQUIRED_CASE_FIELDS: tuple[str, ...] = (
    "id",
    "question",
    "tool",
    "tool_args",
    "expected_results",
    "expected_min_results",
    "category",
    "notes",
)

#: Which tool module registers each tool the corpus reaches, confirmed by
#: reading the ``@mcp.tool`` decorator sites. ``build_tool_map`` derives the
#: set of modules to register from the tool names the *selected* cases use,
#: mapping each name to its owner here -- so nothing is hardcoded beyond this
#: observed ownership. ``utility`` is listed for completeness (its tools are
#: not reached by the current corpus) so a future case naming one registers
#: cleanly rather than recording a spurious missing-tool error.
_MODULE_TOOLS: dict[str, tuple[str, ...]] = {
    "code_analysis": (
        "analyze_code_structure",
        "find_dependencies",
        "find_callers_callees",
        "trace_full_execution_chain",
    ),
    "semantic_search": (
        "search_documentation",
        "explain_with_context",
        "get_knowledge_base_status",
        "check_knowledge_integrity",
    ),
    "graph_rag": (
        "search_architecture",
        "get_code_context",
        "trace_data_flow",
    ),
    "ee2_compliance": (
        "search_ee2_standards",
    ),
    "operational": (
        "get_operational_guidance",
        "list_job_scripts",
        "get_job_details",
    ),
    "utility": (
        "get_server_info",
        "mcp_health_check",
        "get_health_trend",
        "get_quality_metrics",
    ),
}

#: Reverse of :data:`_MODULE_TOOLS`: a tool name to its owning module.
_TOOL_TO_MODULE: dict[str, str] = {
    tool: module
    for module, tools in _MODULE_TOOLS.items()
    for tool in tools
}

#: Modules whose ``register`` accepts a ``catalog`` keyword. Mirrors
#: ``mcp_server._TENANT_SCOPED_MODULES`` exactly, so the harness threads the
#: catalog the same way the served runtime does. ``catalog=None`` would make
#: every Tenant_Scoped_Case fail as if the router were broken (Decision 5), so
#: this must not drift from the server's list.
_TENANT_SCOPED_MODULES: frozenset[str] = frozenset(
    {
        "semantic_search",
        "code_analysis",
        "graph_rag",
        "operational",
        "ee2_compliance",
        "workflow_info",
    }
)

#: The ``version`` field the harness stamps on every Benchmark_Run_Record.
#: Matches the Node harness's ``'1.0.0'`` so the two records share the field.
HARNESS_VERSION: str = "1.0.0"


class CorpusError(Exception):
    """Raised when the Ground_Truth_Corpus is absent or malformed.

    A present-but-malformed case is an error (naming the case ``id`` and
    the offending field) rather than a case scored zero, because scoring
    an authoring mistake buries it inside a plausible-looking number. The
    CLI (Task 3.3) converts this into an ``[ERROR]`` line and exit status
    1; as a library function ``load_corpus`` simply raises it.
    """


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BenchmarkCase:
    """One corpus entry.

    Carries the eight declared Benchmark_Case fields plus ``tenant_scoped``,
    which is *derived* as ``"tenant_id" in tool_args`` rather than stored.
    Deriving it makes the Requirement 2 criterion 8 partition a function of
    the case data, so a case filed in the wrong container is still
    classified correctly.

    Attributes
    ----------
    id, question, tool, tool_args, expected_results, expected_min_results,
    category, notes
        The eight corpus fields, unchanged from the corpus shape.
    tenant_scoped
        ``True`` when ``tool_args`` carries a ``tenant_id`` key.

    Notes
    -----
    ``expected_min_results`` is carried for schema conformance and is read
    by neither harness -- it is absent from the Node harness's
    ``computeQueryMetrics``, ``aggregateMetrics``, and ``detectRegressions``.
    It is documentary; nothing gates on it.
    """

    id: str
    question: str
    tool: str
    tool_args: Mapping[str, Any]
    expected_results: Sequence[str]
    expected_min_results: int
    category: str
    notes: str
    tenant_scoped: bool


@dataclass(frozen=True)
class CaseResult:
    """The scored outcome of one Benchmark_Case.

    ``score_case`` fills the metric fields; the orchestration layer
    (Task 3.2) fills ``latency_ms`` and, on a failure, ``error``. A failed
    case still produces a ``CaseResult`` -- with the zero shape and an
    ``error`` -- so the aggregation denominator is never silently shrunk.
    """

    id: str
    precision: float
    recall: float
    mrr: float
    covered: bool
    matched_results: Sequence[str]
    expected_results: Sequence[str]
    latency_ms: int = 0
    tenant_id: str | None = None
    tenant_scoped: bool = False
    error: str | None = None


@dataclass(frozen=True)
class ScopeMetrics:
    """The six Quality_Metrics for one aggregation scope."""

    precision_at_k: float
    recall_at_k: float
    mrr: float
    coverage: float
    latency_p50_ms: int
    latency_p95_ms: int


@dataclass(frozen=True)
class Corpus:
    """A loaded Ground_Truth_Corpus.

    ``cases`` holds every Benchmark_Case across both containers, each
    already carrying its derived ``tenant_scoped`` flag. ``origins`` maps a
    case ``id`` to the container it was read from (``"categories"`` or
    ``"tenant_categories"``), so a later consumer can assert that the
    container and the derivation agree without re-reading the raw file.
    """

    version: str
    metrics_config: Mapping[str, Any]
    cases: tuple[BenchmarkCase, ...]
    origins: Mapping[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Numeric helpers -- each mirrors the Node harness exactly
# ---------------------------------------------------------------------------


def _clamp01(value: float) -> float:
    """Clamp ``value`` to ``[0, 1]`` (Node ``clamp01``)."""
    return max(0.0, min(1.0, value))


def _js_round(value: float) -> int:
    """Round half up to the nearest integer, matching JS ``Math.round``.

    Python's built-in ``round`` rounds half to even, so it cannot be used
    where byte-for-byte agreement with the Node harness is required. Every
    metric here is non-negative, for which ``Math.round(x)`` is
    ``floor(x + 0.5)``.
    """
    return math.floor(value + 0.5)


def _round4(value: float) -> float:
    """Round to four places the way the Node harness's ``round4`` does.

    ``round4(v)`` in ``run_benchmark.js`` is ``Math.round(v * 10000) /
    10000``; reproduced here with :func:`_js_round` so the two harnesses
    round identically and two log lines representing the same score
    compare equal.
    """
    return _js_round(value * 10000) / 10000


def _percentile(sorted_values: Sequence[int], p: float) -> int:
    """Return the ``p``-th percentile of ``sorted_values``.

    Mirrors the Node ``percentile`` helper's ``Math.ceil(p / 100 * n) - 1``
    index selection over an ascending-sorted array, clamped to a valid
    index. Latencies are
    integers, so the return type is ``int``.
    """
    n = len(sorted_values)
    if n == 0:
        return 0
    idx = math.ceil(p / 100 * n) - 1
    return sorted_values[max(0, idx)]


def score_counts(
    matched_count: int, expected_length: int, k: int
) -> tuple[float, float, float]:
    """Compute ``(precision, recall, mrr)`` from match counts alone.

    Factored out of :func:`score_case` so the incumbent-parity test can
    recompute the Node harness's per-case values from
    ``(len(matched_results), len(expected_results), k)`` with the exact
    same arithmetic.

    ``precision`` is ``matched / min(k, expected)`` clamped to ``[0, 1]``;
    ``recall`` is ``matched / expected`` clamped. An empty
    ``expected_results`` yields ``precision`` and ``recall`` of exactly
    ``0`` -- never ``ZeroDivisionError`` and never ``nan``, which would
    serialize as invalid JSON and take the wrapper's normalisation step
    down with it.

    ``mrr`` is the reciprocal of the 1-based position of the first response
    text containing a match. A Python Tool_Closure returns a single
    response text, so that position is always ``1`` when anything matched
    and the reciprocal collapses to ``1.0`` if ``matched_count > 0`` and
    ``0.0`` otherwise -- identical to the ``covered`` flag.
    """
    if expected_length > 0:
        precision = _clamp01(matched_count / min(k, expected_length))
        recall = _clamp01(matched_count / expected_length)
    else:
        precision = 0.0
        recall = 0.0
    mrr = 1.0 if matched_count > 0 else 0.0
    return precision, recall, mrr


def score_case(case: BenchmarkCase, response: str, k: int) -> CaseResult:
    """Score one Benchmark_Case against a single response text.

    An ``expected_results`` entry is counted as matched when it occurs as a
    substring of ``response`` under a case-insensitive comparison. The
    ``response`` is treated as one text block (a Python Tool_Closure
    returns ``str``); there is no ``content`` list to unwrap.

    Parameters
    ----------
    case
        The case whose ``expected_results`` drive the match.
    response
        The Tool_Closure's return value, as a single string.
    k
        The ``k`` from the corpus ``metrics_config``.

    Returns
    -------
    CaseResult
        With ``precision``/``recall``/``mrr``/``covered``/``matched_results``
        populated. ``latency_ms`` and ``error`` are left at their defaults
        for the orchestration layer to fill.
    """
    lowered = response.lower()
    matched = [
        kw for kw in case.expected_results if str(kw).lower() in lowered
    ]
    precision, recall, mrr = score_counts(
        len(matched), len(case.expected_results), k
    )
    return CaseResult(
        id=case.id,
        precision=precision,
        recall=recall,
        mrr=mrr,
        covered=len(matched) > 0,
        matched_results=matched,
        expected_results=list(case.expected_results),
        tenant_id=(
            case.tool_args.get("tenant_id") if case.tenant_scoped else None
        ),
        tenant_scoped=case.tenant_scoped,
    )


def aggregate(results: Sequence[CaseResult]) -> ScopeMetrics:
    """Aggregate scored cases into one scope's Quality_Metrics.

    Means of the per-case ``precision``, ``recall``, and ``mrr``;
    ``coverage`` as the covered-case count over the case count; integer
    ``latency_p50_ms`` and ``latency_p95_ms``. The four quality metrics are
    rounded to four places (:func:`_round4`); the latencies are integer
    percentiles. Mirrors the Node harness's ``aggregateMetrics``.
    """
    if not results:
        return ScopeMetrics(0.0, 0.0, 0.0, 0.0, 0, 0)

    n = len(results)
    precision_mean = sum(r.precision for r in results) / n
    recall_mean = sum(r.recall for r in results) / n
    mrr_mean = sum(r.mrr for r in results) / n
    covered = sum(1 for r in results if r.covered)
    latencies = sorted(r.latency_ms for r in results)
    return ScopeMetrics(
        precision_at_k=_round4(precision_mean),
        recall_at_k=_round4(recall_mean),
        mrr=_round4(mrr_mean),
        coverage=_round4(covered / n),
        latency_p50_ms=_js_round(_percentile(latencies, 50)),
        latency_p95_ms=_js_round(_percentile(latencies, 95)),
    )


# ---------------------------------------------------------------------------
# Corpus loader
# ---------------------------------------------------------------------------


def _build_case(raw: Any, origin: str) -> BenchmarkCase:
    """Validate one raw corpus entry and build a :class:`BenchmarkCase`.

    Raises :class:`CorpusError` naming the case ``id`` and the offending
    field when a required field is missing.
    """
    if not isinstance(raw, Mapping):
        raise CorpusError(
            f"corpus case in '{origin}' is not an object: {raw!r}"
        )
    case_id = raw.get("id", "<unknown>")
    for field_name in _REQUIRED_CASE_FIELDS:
        if field_name not in raw:
            raise CorpusError(
                f"corpus case '{case_id}' in '{origin}' is missing "
                f"required field '{field_name}'"
            )
    tool_args = raw["tool_args"]
    if not isinstance(tool_args, Mapping):
        raise CorpusError(
            f"corpus case '{case_id}' in '{origin}' has a non-object "
            "'tool_args'"
        )
    return BenchmarkCase(
        id=raw["id"],
        question=raw["question"],
        tool=raw["tool"],
        tool_args=dict(tool_args),
        expected_results=list(raw["expected_results"]),
        expected_min_results=raw["expected_min_results"],
        category=raw["category"],
        notes=raw["notes"],
        tenant_scoped="tenant_id" in tool_args,
    )


def _load_container(
    raw: Mapping[str, Any],
    key: str,
    *,
    required: bool,
) -> list[tuple[BenchmarkCase, str]]:
    """Read one category-keyed container into ``(case, origin)`` pairs.

    ``required`` distinguishes the two asymmetric conditions: an absent
    ``categories`` is a hard error (there is no case list without it), while
    an absent ``tenant_categories`` is treated as empty so a corpus
    predating this feature still runs.
    """
    container = raw.get(key)
    if container is None:
        if required:
            raise CorpusError(f"corpus is missing required '{key}' object")
        return []
    if not isinstance(container, Mapping):
        raise CorpusError(f"corpus '{key}' is not an object")

    pairs: list[tuple[BenchmarkCase, str]] = []
    for cat_cases in container.values():
        if not isinstance(cat_cases, Sequence) or isinstance(cat_cases, str):
            raise CorpusError(f"corpus '{key}' category is not a list")
        for raw_case in cat_cases:
            pairs.append((_build_case(raw_case, key), key))
    return pairs


def load_corpus(path: str) -> Corpus:
    """Load the Ground_Truth_Corpus from ``path``.

    Reads both the ``categories`` and ``tenant_categories`` containers,
    tagging each case with its origin. Two asymmetric conditions:

    - An absent ``tenant_categories`` is **not** an error -- it is treated
      as empty, so a corpus predating this feature still runs. That is what
      keeps the Node corpus and the Python harness independently
      versionable.
    - A present-but-malformed case **is** an error, raising
      :class:`CorpusError` naming the case ``id`` and the field.

    Raises
    ------
    FileNotFoundError
        If ``path`` does not exist (surfaced to the CLI as exit 1).
    json.JSONDecodeError
        If ``path`` is not valid JSON.
    CorpusError
        If ``categories`` is absent or not an object, or a case is
        malformed.
    """
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, Mapping):
        raise CorpusError("corpus root is not an object")

    pairs = _load_container(raw, "categories", required=True)
    pairs += _load_container(raw, "tenant_categories", required=False)

    cases = tuple(case for case, _origin in pairs)
    origins = {case.id: origin for case, origin in pairs}
    metrics_config = raw.get("metrics_config", {})
    if not isinstance(metrics_config, Mapping):
        raise CorpusError("corpus 'metrics_config' is not an object")

    return Corpus(
        version=raw.get("version", ""),
        metrics_config=dict(metrics_config),
        cases=cases,
        origins=origins,
    )


# ---------------------------------------------------------------------------
# Registration_Shim and closure collection (Task 3.1)
# ---------------------------------------------------------------------------


class _ToolShim:
    """Stand-in for a ``FastMCP`` server that collects tool closures.

    Each tool module's ``register(mcp, data, ...)`` defines its tools as
    inner ``async def`` functions and hands each to ``@mcp.tool(...)``.
    Passing an instance of this shim as ``mcp`` lets the module register
    normally while :attr:`tools` keeps the very function object it
    handed over, keyed by its registered name.

    The function is returned **unchanged** from the decorator: the module
    keeps its own reference to it and altering it would change the
    behaviour the harness exists to observe.
    """

    def __init__(self) -> None:
        self.tools: dict[str, Callable[..., Awaitable[str]]] = {}

    def tool(self, *args: Any, **kwargs: Any) -> Any:
        """Record a tool closure, handling both decorator idioms.

        Two forms appear in the tree and both are handled:

        * ``@mcp.tool(name="...")`` -- a decorator *factory*. ``tool`` is
          called first with the arguments and must return the actual
          decorator. The registered name is ``kwargs["name"]`` when given.
        * ``@mcp.tool`` with no parentheses -- ``tool`` receives the
          function directly as the sole positional argument.
          ``error_analysis`` uses ``@mcp.tool()`` today and a future
          module could drop the parentheses entirely, so the bare form is
          supported defensively.

        In both cases the registered name falls back to the function's own
        ``__name__`` when no ``name=`` is supplied.
        """
        # Bare-callable form: @mcp.tool with no parentheses.
        if len(args) == 1 and callable(args[0]) and not kwargs:
            fn = args[0]
            self.tools[getattr(fn, "__name__", repr(fn))] = fn
            return fn

        def _decorate(fn: Callable[..., Awaitable[str]]) -> Callable[
            ..., Awaitable[str]
        ]:
            name = kwargs.get("name") or getattr(fn, "__name__")
            self.tools[name] = fn
            return fn

        return _decorate

    async def list_tools(self, *args: Any, **kwargs: Any) -> list[Any]:
        """Return an empty tool list.

        ``utility.register`` reads the server for a tool-listing call
        *inside* one of its own closures (``get_server_info``), not at
        registration time. Exposing this async method lets that path
        degrade cleanly to an empty list if a future corpus case ever
        names ``get_server_info``.
        """
        return []


def _register_kwargs(
    module: str, catalog: Any, state_dir: str
) -> dict[str, Any]:
    """Build the module-specific ``register`` keyword arguments.

    Mirrors ``mcp_server`` where it matters: tenant-scoped modules get the
    real ``catalog`` (so tenant resolution works rather than raising), and
    the two modules that would otherwise write session/health state to the
    repository are pinned to a scratch directory instead.
    """
    kwargs: dict[str, Any] = {}
    if module in _TENANT_SCOPED_MODULES:
        kwargs["catalog"] = catalog
    if module == "graph_rag":
        # Pin the session manager to the scratch dir so registration does
        # not create session state under SDD_STATE_DIR in the repository.
        from src.sdd.session_manager import SessionManager

        kwargs["session_manager"] = SessionManager(state_dir)
    elif module == "utility":
        kwargs["state_dir"] = state_dir
    return kwargs


def build_tool_map(
    data: Any,
    catalog: Any,
    *,
    tool_names: "Sequence[str] | set[str]",
    state_dir: str,
) -> dict[str, Callable[..., Awaitable[str]]]:
    """Collect the Tool_Closures the selected cases need, keyed by name.

    The set of modules to register is derived from ``tool_names`` -- the
    tool values the selected cases use -- mapped through
    :data:`_TOOL_TO_MODULE`. Only the owning modules of those tools are
    registered; a tool name with no known owner is skipped, so the case
    that names it records a missing-tool error rather than aborting the
    run.

    Each closure closes over ``data`` and ``catalog`` at registration
    time. ``catalog`` must be the real catalog: with ``None`` every
    Tenant_Scoped_Case would raise inside the tenancy-scoping helper and
    the run would look exactly like a tenant routing bug (Decision 5).

    Parameters
    ----------
    data
        The data-access facade threaded into every module's ``register``.
    catalog
        The resolved tenant catalog, threaded into tenant-scoped modules.
    tool_names
        The tool names the selected cases use. Their owning modules are
        the ones registered.
    state_dir
        A scratch directory for ``graph_rag`` / ``utility`` state, so no
        session or health file is written into the repository (R3.6).

    Returns
    -------
    dict
        Mapping of registered tool name to the exact coroutine function
        the owning module registered.
    """
    required_modules: list[str] = []
    seen: set[str] = set()
    for name in tool_names:
        module = _TOOL_TO_MODULE.get(name)
        if module is None or module in seen:
            continue
        seen.add(module)
        required_modules.append(module)

    tool_map: dict[str, Callable[..., Awaitable[str]]] = {}
    for module in required_modules:
        shim = _ToolShim()
        mod = importlib.import_module(f"src.tools.{module}")
        mod.register(
            shim, data, **_register_kwargs(module, catalog, state_dir)
        )
        tool_map.update(shim.tools)
    return tool_map


# ---------------------------------------------------------------------------
# Invocation record (Task 3.2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BenchmarkRun:
    """The outcome of one scored run.

    Attributes
    ----------
    record
        The Benchmark_Run_Record dict written to the results directory.
    results
        The per-case :class:`CaseResult` values, in corpus order.
    results_path
        Absolute path of the written Benchmark_Run_Record.
    all_errored
        ``True`` when at least one case ran and every case recorded an
        ``error``. The CLI (Task 3.3) turns this into exit status 1 while
        still having written the record, so a wholly unreachable backend
        is a visible zero-coverage line in the history rather than a hole
        in it (R3.4).
    """

    record: Mapping[str, Any]
    results: tuple[CaseResult, ...]
    results_path: str
    all_errored: bool


def _select_cases(
    corpus: Corpus, category: str | None
) -> list[BenchmarkCase]:
    """Return the cases to execute, filtered by ``category`` when given.

    An unknown ``category`` yields an empty selection; distinguishing an
    unknown category (exit 1) from a valid-but-empty one (a zero-coverage
    record, exit 0) is the CLI's concern (Task 3.3), not this function's.
    """
    if category is None:
        return list(corpus.cases)
    return [c for c in corpus.cases if c.category == category]


def _corpus_k(corpus: Corpus) -> int:
    """Return the ``k`` from the corpus ``metrics_config`` (default 5)."""
    try:
        return int(corpus.metrics_config.get("k", 5))
    except (TypeError, ValueError):
        return 5


def _elapsed_ms(start: float) -> int:
    """Milliseconds since ``start`` (a ``time.perf_counter`` value)."""
    return _js_round((time.perf_counter() - start) * 1000)


def _error_result(
    case: BenchmarkCase, error: str, latency_ms: int
) -> CaseResult:
    """Build the zero-shaped :class:`CaseResult` for a case that failed.

    A failed case still produces exactly one entry -- with the zero shape,
    a real elapsed time, and an ``error`` -- so the aggregation
    denominator is never silently shrunk. A run that dropped a failing
    case would compute every average over a smaller set and report a
    *better* score for a *worse* system, the one failure a quality gate
    cannot have.
    """
    return CaseResult(
        id=case.id,
        precision=0.0,
        recall=0.0,
        mrr=0.0,
        covered=False,
        matched_results=[],
        expected_results=list(case.expected_results),
        latency_ms=latency_ms,
        tenant_id=(
            case.tool_args.get("tenant_id") if case.tenant_scoped else None
        ),
        tenant_scoped=case.tenant_scoped,
        error=error,
    )


async def _invoke_case(
    tool_map: Mapping[str, Callable[..., Awaitable[str]]],
    case: BenchmarkCase,
    k: int,
) -> CaseResult:
    """Invoke one case's Tool_Closure and score the result.

    The case's ``tool_args`` -- ``tenant_id`` included for a
    Tenant_Scoped_Case -- are passed to the closure as keyword arguments,
    so the tool's own tenancy-scoping wrapper binds the tenancy ContextVar
    and the attribution header is applied exactly as a consumer's call
    does. The Tool_Internal is never called directly and the ContextVar is
    never set here; doing either would skip the binding this harness exists
    to exercise.

    Both failure paths -- an absent closure and a raising closure --
    converge on the zero-shaped :class:`CaseResult` so the run continues.
    ``Exception`` is caught rather than ``BaseException`` so ``Ctrl-C``
    still stops a long run. A non-``str`` return is treated as a failure
    naming the observed type: no current tool does this, but a future one
    that did would otherwise score zero with no explanation.
    """
    start = time.perf_counter()
    closure = tool_map.get(case.tool)
    if closure is None:
        return _error_result(
            case,
            f"no closure registered for tool {case.tool!r}",
            _elapsed_ms(start),
        )
    try:
        response = await closure(**dict(case.tool_args))
    except Exception as exc:  # noqa: BLE001 - a failed case is recorded
        return _error_result(case, str(exc), _elapsed_ms(start))
    latency_ms = _elapsed_ms(start)
    if not isinstance(response, str):
        return _error_result(
            case,
            f"tool returned {type(response).__name__}, expected str",
            latency_ms,
        )
    # A Python Tool_Closure returns a single response text -- no content
    # list to unwrap (R1.5).
    return replace(score_case(case, response, k), latency_ms=latency_ms)


def _scope_dict(metrics: ScopeMetrics) -> dict[str, Any]:
    """Render one scope's :class:`ScopeMetrics` as the record's dict."""
    return {
        "precision_at_k": metrics.precision_at_k,
        "recall_at_k": metrics.recall_at_k,
        "mrr": metrics.mrr,
        "coverage": metrics.coverage,
        "latency_p50_ms": metrics.latency_p50_ms,
        "latency_p95_ms": metrics.latency_p95_ms,
    }


def _case_dict(result: CaseResult) -> dict[str, Any]:
    """Render one :class:`CaseResult` as a ``queries[]`` entry.

    Carries the Node record's per-case fields plus ``covered`` (asserted
    by Property 10 on the failure paths) and the per-case ``tenant_id`` so
    the Default_Tenant / Prefixed_Tenant partition is reconstructible from
    the record alone. ``error`` is present only when the case failed.
    """
    entry: dict[str, Any] = {
        "id": result.id,
        "precision": result.precision,
        "recall": result.recall,
        "mrr": result.mrr,
        "covered": result.covered,
        "latency_ms": result.latency_ms,
        "matched_results": list(result.matched_results),
        "expected_results": list(result.expected_results),
        "tenant_id": result.tenant_id,
    }
    if result.error is not None:
        entry["error"] = result.error
    return entry


# Friendly metric labels for the regression messages, matching the Node
# harness's ``friendlyNames`` map.
_FRIENDLY_METRIC: dict[str, str] = {
    "precision_at_k": "P@K",
    "recall_at_k": "R@K",
    "mrr": "MRR",
    "coverage": "Coverage",
}


def _detect_regressions(
    overall: Mapping[str, Any],
    categories: Mapping[str, Mapping[str, Any]],
    previous: Mapping[str, Any] | None,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Port of the Node harness ``detectRegressions``.

    Populated for shape parity with the Node record, using the corpus
    ``metrics_config`` thresholds -- the Node harness's own single-run
    basis. The Nightly_Wrapper owns the trailing-median verdict; this
    object does not feed it.
    """
    if not previous:
        return {"compared_to": None, "warnings": [], "errors": []}

    warn_pct = config.get("regression_threshold_pct", 5) / 100
    error_pct = config.get("critical_threshold_pct", 15) / 100
    min_cov_pct = config.get("minimum_coverage_pct", 80)
    min_cov = min_cov_pct / 100
    warnings: list[str] = []
    errors: list[str] = []

    prev_categories = previous.get("categories") or {}
    scopes: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = [
        ("Overall", overall, previous.get("overall") or {}),
    ]
    for cat, cur in categories.items():
        if cat in prev_categories:
            scopes.append((cat, cur, prev_categories[cat]))

    for label, cur, prev in scopes:
        for metric_key in ("precision_at_k", "recall_at_k", "mrr", "coverage"):
            cur_v = cur.get(metric_key, 0) or 0
            prev_v = prev.get(metric_key, 0) or 0
            if prev_v == 0:
                continue
            drop = (prev_v - cur_v) / prev_v
            if drop > error_pct:
                errors.append(
                    f"{label} {_FRIENDLY_METRIC[metric_key]} dropped "
                    f"{drop * 100:.0f}% ({prev_v:.2f} -> {cur_v:.2f})"
                )
            elif drop > warn_pct:
                warnings.append(
                    f"{label} {_FRIENDLY_METRIC[metric_key]} dropped "
                    f"{drop * 100:.0f}% ({prev_v:.2f} -> {cur_v:.2f})"
                )
        cur_cov = cur.get("coverage", 0) or 0
        if cur_cov < min_cov:
            errors.append(
                f"{label} Coverage {cur_cov * 100:.0f}% below minimum "
                f"{min_cov_pct}%"
            )

    return {
        "compared_to": previous.get("timestamp"),
        "warnings": warnings,
        "errors": errors,
    }


def _utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp with milliseconds and a ``Z``.

    Matches the Node harness's ``new Date().toISOString()`` shape
    (``YYYY-MM-DDTHH:MM:SS.mmmZ``) so a Quality_Metrics_Log line's
    timestamp reads the same regardless of which harness wrote it.
    """
    now = datetime.now(timezone.utc)
    millis = now.microsecond // 1000
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def _harness_id(config: Any) -> str:
    """Build the compound harness identifier for the record.

    ``runtime:script:backend:profile``. Backend and embedding profile are
    what a comparison window must never mix, so recording them in the
    provenance field is the cheap way to make a mixed history detectable
    later (Decision 6).
    """
    return (
        f"python:run_benchmark.py:{config.db_backend}:"
        f"{config.embedding_profile}"
    )


def _by_category(
    results: Sequence[CaseResult], cat_by_id: Mapping[str, str]
) -> dict[str, dict[str, Any]]:
    """Aggregate ``results`` into a per-category metric dict.

    Keyed by the six Benchmark_Category names in corpus order; a category
    with no result aggregates to zeros, matching the Node harness's
    iterate-all-categories behaviour.
    """
    return {
        name: _scope_dict(
            aggregate([r for r in results if cat_by_id.get(r.id) == name])
        )
        for name in CATEGORY_NAMES
    }


def _resolve_results_dir(results_dir: str | os.PathLike[str] | None) -> str:
    """Resolve the Benchmark_Run_Record output directory.

    Precedence: an explicit ``results_dir`` argument, then a non-empty
    ``MCP_BENCHMARK_RESULTS_DIR`` environment variable, then a directory
    under ``mcp_server_python`` that is deliberately **separate** from the
    Node harness's results folder. The Nightly_Wrapper defaults its
    results directory to the Node folder and picks up the freshest
    ``*.json`` there, so sharing it would let the wrapper normalise a
    stale Node record into the log as though it were a Python run -- a
    silent failure, which is why the default diverges rather than being
    shared.
    """
    if results_dir:
        return str(results_dir)
    env = os.environ.get("MCP_BENCHMARK_RESULTS_DIR")
    if env:
        return env
    return str(
        Path(__file__).resolve().parent.parent
        / "test"
        / "benchmark"
        / "results"
    )


def _load_previous_result(results_dir: str) -> dict[str, Any] | None:
    """Return the freshest prior Benchmark_Run_Record in ``results_dir``.

    Returns ``None`` when the directory is absent or holds no readable
    ``*.json``. Called before the current record is written, so it never
    reads the run in progress.
    """
    path = Path(results_dir)
    if not path.is_dir():
        return None
    files = sorted(p for p in path.glob("*.json"))
    if not files:
        return None
    try:
        with open(files[-1], encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_record(record: Mapping[str, Any], results_dir: str) -> str:
    """Write ``record`` as a JSON file and return its path.

    The filename derives from the record timestamp the same way the Node
    harness's ``saveResults`` does: colons become dashes and the
    fractional-second-plus-``Z`` suffix is dropped. The output directory
    is the only place the harness writes (R3.6).
    """
    path = Path(results_dir)
    path.mkdir(parents=True, exist_ok=True)
    stem = str(record["timestamp"]).replace(":", "-").rsplit(".", 1)[0]
    filepath = path / f"{stem}.json"
    with open(filepath, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2)
    return str(filepath)


def _build_record(
    corpus: Corpus,
    config: Any,
    results: Sequence[CaseResult],
    cat_by_id: Mapping[str, str],
    previous: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Assemble the Benchmark_Run_Record from the scored cases.

    ``overall`` and ``categories`` are computed from **Default_Tenant
    cases only** (R2.9), so the ``categories`` object stays comparable
    with the Node-harness lines already in the Quality_Metrics_Log and a
    deliberately-zero Tenant_Scoped_Case cannot move the number the
    benchmark gate reads. ``tenant_overall`` and ``tenant_categories`` are
    additive and carry the Prefixed_Tenant scores separately (R2.8).
    """
    default_results = [r for r in results if not r.tenant_scoped]
    tenant_results = [r for r in results if r.tenant_scoped]

    overall = _scope_dict(aggregate(default_results))
    categories = _by_category(default_results, cat_by_id)
    tenant_overall = _scope_dict(aggregate(tenant_results))
    tenant_categories = _by_category(tenant_results, cat_by_id)

    regression = _detect_regressions(
        overall, categories, previous, corpus.metrics_config
    )

    return {
        "timestamp": _utc_timestamp(),
        "version": HARNESS_VERSION,
        "harness": _harness_id(config),
        "corpus_version": corpus.version,
        "total_queries": len(results),
        "overall": overall,
        "categories": categories,
        "tenant_overall": tenant_overall,
        "tenant_categories": tenant_categories,
        "queries": [_case_dict(r) for r in results],
        "regression": regression,
    }


async def _run_benchmark_async(
    corpus: Corpus,
    *,
    data: Any,
    catalog: Any,
    category: str | None,
    results_dir: str | os.PathLike[str] | None,
) -> BenchmarkRun:
    """Async core of :func:`run_benchmark` (see that function's docstring)."""
    config = load_config()
    if catalog is None:
        # A catalog load failure is fatal here rather than degraded: a
        # benchmark that silently cannot express a tenant is worse than
        # one that did not run (Decision 5). The exception propagates for
        # the CLI to turn into exit 1.
        catalog = get_catalog()

    selected = _select_cases(corpus, category)
    k = _corpus_k(corpus)
    cat_by_id = {c.id: c.category for c in selected}
    tool_names = {c.tool for c in selected}
    state_dir = tempfile.mkdtemp(prefix="mcp_benchmark_state_")
    owns_data = data is None
    try:
        if owns_data:
            # Build the real facade the same way the server does. Only
            # reached when no facade was injected, so an injected run never
            # even imports the adapter chain -- zero backend traffic is
            # structural, not a matter of stub fidelity (R3.2).
            from src.data.backend_selector import create_data_access

            data = await create_data_access(config)
        tool_map = build_tool_map(
            data, catalog, tool_names=tool_names, state_dir=state_dir
        )
        results = [await _invoke_case(tool_map, case, k) for case in selected]
    finally:
        if owns_data and data is not None:
            try:
                await data.close()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass
        shutil.rmtree(state_dir, ignore_errors=True)

    resolved_dir = _resolve_results_dir(results_dir)
    previous = _load_previous_result(resolved_dir)
    record = _build_record(corpus, config, results, cat_by_id, previous)
    results_path = _write_record(record, resolved_dir)
    all_errored = bool(results) and all(r.error is not None for r in results)
    return BenchmarkRun(
        record=record,
        results=tuple(results),
        results_path=results_path,
        all_errored=all_errored,
    )


def run_benchmark(
    corpus: Corpus,
    *,
    data: Any = None,
    catalog: Any = None,
    category: str | None = None,
    results_dir: str | os.PathLike[str] | None = None,
) -> BenchmarkRun:
    """Score the corpus by invoking Tool_Closures and write the record.

    Two ways to get the data-access facade, and the difference is
    structural. With ``data=None`` the real facade is built the same way
    the server does -- ``load_config`` then ``create_data_access`` -- so
    the harness sees the backend the served runtime sees. With ``data``
    supplied it is used verbatim and ``create_data_access`` is never
    reached, which is what guarantees an injected layer issues no backend
    traffic: the code that opens a socket is not entered (R3.1, R3.2). No
    backend-selection environment variable is read here; being
    backend-agnostic comes from taking no backend argument.

    Every selected case produces exactly one entry. A case that could not
    run records zeros, a real elapsed time, and an ``error``, and the run
    continues -- the denominator is never shrunk. The overall and
    per-category figures come from Default_Tenant cases only;
    Tenant_Scoped_Case scores ride in their own two objects (R2.8, R2.9).

    Parameters
    ----------
    corpus
        A loaded :class:`Corpus`.
    data
        Optional injected data-access facade. When ``None`` a real facade
        is built from the environment.
    catalog
        Optional tenant catalog. When ``None`` it is resolved via
        :func:`src.tenancy.runtime.get_catalog`; a load failure is fatal.
    category
        Optional Benchmark_Category name; when given, only that category's
        cases run.
    results_dir
        Optional output directory override. See
        :func:`_resolve_results_dir` for the precedence.

    Returns
    -------
    BenchmarkRun
        The written record, the per-case results, the record path, and the
        all-errored flag the CLI uses to decide its exit status.

    Notes
    -----
    Synchronous by design: it drives its own event loop internally so the
    property tests and the CLI can call it without managing one. It must
    not be called from inside a running event loop.
    """
    return asyncio.run(
        _run_benchmark_async(
            corpus,
            data=data,
            catalog=catalog,
            category=category,
            results_dir=results_dir,
        )
    )


# ---------------------------------------------------------------------------
# CLI (Task 3.3)
# ---------------------------------------------------------------------------


def _default_corpus_path() -> Path:
    """Return the Ground_Truth_Corpus path relative to this repository.

    ``mcp_server_node/test/benchmark/ground_truth.json``, resolved from
    this file's location so ``main()`` works regardless of the caller's
    current working directory (R2.1 -- there is exactly one corpus file).
    """
    return (
        Path(__file__).resolve().parent.parent.parent
        / "mcp_server_node"
        / "test"
        / "benchmark"
        / "ground_truth.json"
    )


def _print_ascii(stream: Any, message: str) -> None:
    """Write ``message`` to ``stream`` with a trailing newline.

    All harness console output is ASCII-only (R1.10); callers pass an
    already-prefixed ``[OK]`` / ``[WARN]`` / ``[ERROR]`` message. This
    helper exists so every emission point is the same one line rather
    than a scattered ``print`` -- a future stream change (e.g. capturing
    output in a test) has one place to intercept.
    """
    print(message, file=stream)


def _plan_by_category(cases: Sequence[BenchmarkCase]) -> dict[str, int]:
    """Return ``{category_name: case_count}``, in ``CATEGORY_NAMES`` order."""
    counts: dict[str, int] = {name: 0 for name in CATEGORY_NAMES}
    for case in cases:
        if case.category in counts:
            counts[case.category] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point. Returns the process exit status.

    Modes and their exit status, per the design's Error Handling table --
    the real failure condition is an absent Benchmark_Run_Record, not a
    poor score:

    - ``--dry-run``: validates the corpus, prints the per-category case
      plan and the required tool names, invokes nothing, writes nothing,
      exits 0 (R1.7).
    - ``--category NAME`` with an unknown ``NAME``: prints a message
      naming all six Benchmark_Category names, writes nothing, exits 1
      (R1.9).
    - ``--category NAME`` with a valid but empty category: a ``[WARN]``
      plus a zero-coverage record over zero cases, exit 0 -- nothing
      failed, which is a different situation from everything failing.
    - Every selected case records an error: the record is still written
      (zero coverage), and the harness exits 1, so a wholly unreachable
      backend is a visible line in the quality history rather than a
      hole in it.
    - A scored run, however poor the score: exit 0. The Nightly_Wrapper's
      Regression_Check owns the quality verdict.
    - Corpus absent/malformed, or the tenant catalog fails to load:
      exit 1, nothing written.
    """
    parser = argparse.ArgumentParser(
        prog="run_benchmark.py",
        description=(
            "Python RAG benchmark harness "
            "(default-tenant-freeze-retirement)."
        ),
    )
    parser.add_argument(
        "--corpus",
        default=None,
        help="Path to the Ground_Truth_Corpus JSON file.",
    )
    parser.add_argument(
        "--category",
        default=None,
        help="Run only cases carrying this Benchmark_Category name.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Validate the corpus and print the per-category plan; "
            "invoke nothing and write nothing."
        ),
    )
    parser.add_argument(
        "--tenant-only",
        action="store_true",
        help="Run only Tenant_Scoped_Cases.",
    )
    parser.add_argument(
        "--default-only",
        action="store_true",
        help="Run only Default_Tenant cases.",
    )
    parser.add_argument(
        "--results-dir",
        default=None,
        help="Override the Benchmark_Run_Record output directory.",
    )
    args = parser.parse_args(argv)

    corpus_path = args.corpus or str(_default_corpus_path())
    try:
        corpus = load_corpus(corpus_path)
    except FileNotFoundError:
        _print_ascii(
            sys.stderr,
            f"[ERROR] corpus file not found: {corpus_path}",
        )
        return 1
    except json.JSONDecodeError as exc:
        _print_ascii(
            sys.stderr,
            f"[ERROR] corpus at {corpus_path} is not valid JSON: "
            f"line {exc.lineno}, column {exc.colno}: {exc.msg}",
        )
        return 1
    except CorpusError as exc:
        _print_ascii(sys.stderr, f"[ERROR] {exc}")
        return 1

    if args.category is not None and args.category not in CATEGORY_NAMES:
        _print_ascii(
            sys.stderr,
            "[ERROR] unknown --category "
            f"{args.category!r}; valid names are: "
            f"{', '.join(CATEGORY_NAMES)}",
        )
        return 1

    selected = _select_cases(corpus, args.category)
    if args.tenant_only:
        selected = [c for c in selected if c.tenant_scoped]
    if args.default_only:
        selected = [c for c in selected if not c.tenant_scoped]

    if args.dry_run:
        plan = _plan_by_category(selected)
        tool_names = sorted({c.tool for c in selected})
        _print_ascii(
            sys.stdout,
            f"[OK] dry run: {len(selected)} case(s) selected from "
            f"corpus version {corpus.version!r}",
        )
        for name in CATEGORY_NAMES:
            _print_ascii(sys.stdout, f"[OK]   {name}: {plan[name]} case(s)")
        _print_ascii(
            sys.stdout,
            f"[OK] required tool(s): {', '.join(tool_names)}",
        )
        return 0

    if not selected:
        _print_ascii(
            sys.stderr,
            f"[WARN] category {args.category!r} selected zero cases; "
            "writing a zero-coverage record",
        )

    try:
        catalog = get_catalog()
    except Exception as exc:  # noqa: BLE001 - fatal per Decision 5
        _print_ascii(
            sys.stderr,
            f"[ERROR] failed to load the tenant catalog: {exc}",
        )
        return 1

    empty_corpus = replace(corpus, cases=tuple(selected))
    run = run_benchmark(
        empty_corpus,
        catalog=catalog,
        results_dir=args.results_dir,
    )

    overall = run.record.get("overall", {})
    _print_ascii(
        sys.stdout,
        f"[OK] wrote {run.results_path}: "
        f"{run.record.get('total_queries', 0)} case(s), "
        f"coverage={overall.get('coverage', 0)}",
    )
    if run.all_errored:
        _print_ascii(
            sys.stderr,
            "[ERROR] every selected case recorded an error; "
            "coverage is 0 in the written record",
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
