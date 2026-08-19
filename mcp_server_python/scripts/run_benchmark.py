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

Scope note (Task 1.3)
---------------------
This module currently lands the data model and the pure scoring
arithmetic only -- ``BenchmarkCase``, ``CaseResult``, ``ScopeMetrics``,
``Corpus``, ``load_corpus``, ``score_case``, and ``aggregate``. Closure
collection (``build_tool_map``), the invocation orchestration
(``run_benchmark``), and the CLI (``main``) are added by later tasks
(3.1, 3.2, 3.3) and are deliberately absent here.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

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
