"""Parity test runner (Requirements 13.1 – 13.7).

Python port of the dual-server parity validation described in the design
document. Runs the same MCP tool call against the Node.js server (port
3000 or the live AgentCore proxy endpoint) and the Python server (port
8000), then compares the results under one of three comparison modes:

* ``exact`` — ordered document-ID match (e.g. ``search_documentation``
  top-k results must be identical).
* ``set_equality`` — order-insensitive match of graph node names
  (e.g. ``find_callers_callees`` returns the same set of functions).
* ``tolerance`` — numeric scores agree within a relative tolerance
  (default ±10 %).

The framework is transport-aware: tools can be called via a plain
Streamable HTTP MCP client, or via a custom callable passed by the
test author (useful when the Node.js server is reachable only through
an AgentCore proxy).

Usage from a pytest file::

    @pytest.mark.parity
    async def test_search_documentation_parity(parity_runner):
        result = await parity_runner.assert_parity(
            tool_name="search_documentation",
            arguments={"query": "GFS forecast job", "max_results": 5},
            comparison="exact",
            id_extractor=lambda r: [h["id"] for h in r["hits"]],
        )
        assert result.passed, result.describe()

Usage from the command line (once both servers are running)::

    python -m tests.parity.parity_runner \
        --module semantic_search \
        --nodejs-url http://localhost:3000/mcp \
        --python-url http://localhost:8000/mcp

This file does **not** start the servers or execute any live HTTP
calls by itself — it only provides the comparison framework and a
CLI entrypoint. The Python server is not yet deployed; see the
accompanying CHANGELOG entry for the deployment plan.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import sys
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Iterable, Sequence

log = logging.getLogger(__name__)


# ── comparison modes ────────────────────────────────────────────────────


class ComparisonMode(str, Enum):
    """Supported parity comparison strategies."""

    EXACT = "exact"
    SET_EQUALITY = "set_equality"
    TOLERANCE = "tolerance"


# Default numeric tolerance for ``ComparisonMode.TOLERANCE``. ±10% matches
# the design document's requirement for "relevance scores within 10%".
DEFAULT_TOLERANCE: float = 0.10


# ── result models ───────────────────────────────────────────────────────


@dataclass
class ParityResult:
    """Outcome of a single ``assert_parity`` call.

    Attributes
    ----------
    tool_name
        The tool that was executed on both servers.
    arguments
        Arguments passed to the tool. Useful when reporting a divergence
        so operators can reproduce the call locally.
    comparison
        Which comparison mode was applied.
    passed
        ``True`` if the two results agreed under ``comparison``.
    nodejs_result
        Raw result returned by the Node.js server (after any ``id_extractor``
        / ``score_extractor`` projection — the pre-projection result is
        available on ``nodejs_raw``).
    python_result
        Same, for the Python server.
    nodejs_raw
        Unprojected response, preserved for operators debugging a failure.
    python_raw
        Same, for the Python server.
    divergence
        Human-readable description of the first disagreement found, or
        ``None`` when ``passed`` is true.
    extra
        Optional side-channel metadata (e.g. per-index score deltas).
    """

    tool_name: str
    arguments: dict[str, Any]
    comparison: ComparisonMode
    passed: bool
    nodejs_result: Any = None
    python_result: Any = None
    nodejs_raw: Any = None
    python_raw: Any = None
    divergence: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def describe(self) -> str:
        """Return a multi-line diagnostic suitable for pytest failure output."""
        lines = [
            f"[{'PASS' if self.passed else 'FAIL'}] {self.tool_name}"
            f"  (comparison={self.comparison.value})",
            f"  arguments: {self.arguments}",
        ]
        if not self.passed:
            lines.append(f"  divergence: {self.divergence}")
            lines.append(f"    nodejs: {self.nodejs_result!r}")
            lines.append(f"    python: {self.python_result!r}")
        return "\n".join(lines)


@dataclass
class ParitySummary:
    """Aggregated result of multiple ``assert_parity`` calls.

    Produced by :pymeth:`ParityRunner.run_cases` or the CLI entrypoint
    so an operator can see per-tool pass/fail counts in one place.
    """

    total: int = 0
    passed: int = 0
    failed: int = 0
    results: list[ParityResult] = field(default_factory=list)

    @property
    def divergences(self) -> list[ParityResult]:
        return [r for r in self.results if not r.passed]

    def add(self, result: ParityResult) -> None:
        self.total += 1
        self.results.append(result)
        if result.passed:
            self.passed += 1
        else:
            self.failed += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "per_tool": Counter(r.tool_name for r in self.results),
            "divergences": [
                {
                    "tool": r.tool_name,
                    "arguments": r.arguments,
                    "comparison": r.comparison.value,
                    "divergence": r.divergence,
                }
                for r in self.divergences
            ],
        }

    def render_report(self) -> str:
        """Render a human-readable summary report."""
        lines = [
            "# Parity Test Summary",
            f"Total: {self.total}  Passed: {self.passed}  Failed: {self.failed}",
            "",
        ]
        if self.total == 0:
            lines.append("(no parity cases executed)")
            return "\n".join(lines)

        per_tool = Counter(r.tool_name for r in self.results)
        per_tool_passed = Counter(
            r.tool_name for r in self.results if r.passed
        )
        lines.append("## Per-tool")
        for tool, total in sorted(per_tool.items()):
            lines.append(f"- {tool}: {per_tool_passed[tool]}/{total}")
        if self.divergences:
            lines.append("")
            lines.append("## Divergences")
            for r in self.divergences:
                lines.append(f"- {r.tool_name} / {r.comparison.value}")
                lines.append(f"    arguments: {r.arguments}")
                lines.append(f"    {r.divergence}")
        return "\n".join(lines)


# ── tool-call transports ────────────────────────────────────────────────

# A ``ToolCaller`` is any async callable that takes a tool name + arguments
# dict and returns the tool's raw result. Tests construct a ``ParityRunner``
# with two of these — one pointed at Node.js, one at Python — which is how
# the framework decouples from the actual MCP client library.
ToolCaller = Callable[[str, dict[str, Any]], Awaitable[Any]]


class HTTPJSONRPCToolCaller:
    """Minimal Streamable-HTTP MCP ``tools/call`` client.

    Not used by the default test suite (which injects mock callers) but
    provided so operators can wire the framework against a live server
    without pulling in a full MCP SDK dependency. Uses ``httpx`` which is
    already in the Python port's runtime deps (Phase B1 ``pyproject.toml``).
    """

    def __init__(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._url = url
        self._headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **(headers or {}),
        }
        self._timeout = timeout_seconds
        self._request_id = 0

    async def __call__(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> Any:
        try:
            import httpx  # Imported lazily so tests w/o httpx still run.
        except ImportError as exc:  # pragma: no cover - deps are pinned
            raise RuntimeError(
                "httpx is required for HTTPJSONRPCToolCaller; install the "
                "runtime extras or inject a custom ToolCaller instead."
            ) from exc

        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                self._url, json=payload, headers=self._headers
            )
            resp.raise_for_status()
            data = resp.json()
        if "error" in data:
            raise RuntimeError(
                f"{tool_name} returned MCP error: {data['error']}"
            )
        return data.get("result")


# ── the runner itself ──────────────────────────────────────────────────


@dataclass
class ParityCase:
    """Declarative description of a single parity assertion.

    Useful for feeding batches of cases to :pymeth:`ParityRunner.run_cases`,
    e.g. from the CLI entrypoint's ``--cases-file`` option.
    """

    tool_name: str
    arguments: dict[str, Any]
    comparison: ComparisonMode = ComparisonMode.EXACT
    tolerance: float | None = None
    # Optional projections — let tests pull the comparable subset out of
    # a richer tool response without requiring every tool to share a shape.
    id_extractor: Callable[[Any], Sequence[Any]] | None = None
    score_extractor: Callable[[Any], Sequence[float]] | None = None
    name_extractor: Callable[[Any], Iterable[Any]] | None = None
    module: str | None = None  # for --module CLI filtering

    def effective_tolerance(self) -> float:
        return DEFAULT_TOLERANCE if self.tolerance is None else self.tolerance


class ParityRunner:
    """Run MCP tool calls against two servers and compare the results.

    Parameters
    ----------
    nodejs_caller
        Async callable ``(tool_name, arguments) -> result`` for the
        Node.js side.
    python_caller
        Same, for the Python server under test.
    default_tolerance
        Relative tolerance used by ``ComparisonMode.TOLERANCE`` when a
        case doesn't override it.

    Thread-safety
    -------------
    The runner is not thread-safe; dispatch each concurrent parity batch
    through a fresh instance or serialize calls on an asyncio event loop.
    """

    def __init__(
        self,
        nodejs_caller: ToolCaller,
        python_caller: ToolCaller,
        *,
        default_tolerance: float = DEFAULT_TOLERANCE,
    ) -> None:
        self._node = nodejs_caller
        self._py = python_caller
        self._default_tolerance = default_tolerance

    # ── public API ───────────────────────────────────────────────────

    async def assert_parity(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        comparison: str | ComparisonMode = ComparisonMode.EXACT,
        tolerance: float | None = None,
        id_extractor: Callable[[Any], Sequence[Any]] | None = None,
        score_extractor: Callable[[Any], Sequence[float]] | None = None,
        name_extractor: Callable[[Any], Iterable[Any]] | None = None,
    ) -> ParityResult:
        """Run ``tool_name`` on both servers and return a :class:`ParityResult`.

        The extractor callbacks let tests project the two responses to
        the comparable subset for the chosen mode:

        * ``id_extractor`` feeds :data:`ComparisonMode.EXACT`
        * ``name_extractor`` feeds :data:`ComparisonMode.SET_EQUALITY`
        * ``score_extractor`` feeds :data:`ComparisonMode.TOLERANCE`

        If no extractor is supplied for a given mode, the raw response
        is compared directly (useful for tools that already return a
        simple list of IDs / names / scores).
        """
        args = arguments or {}
        mode = ComparisonMode(comparison) if isinstance(comparison, str) else comparison
        tol = self._default_tolerance if tolerance is None else tolerance

        # Dispatch both calls concurrently so the worst-case latency is
        # max(node_ms, python_ms), not their sum.
        node_coro = self._safe_call(self._node, tool_name, args)
        python_coro = self._safe_call(self._py, tool_name, args)
        (node_raw, node_err), (python_raw, python_err) = await asyncio.gather(
            node_coro, python_coro
        )

        result = ParityResult(
            tool_name=tool_name,
            arguments=args,
            comparison=mode,
            passed=False,
            nodejs_raw=node_raw,
            python_raw=python_raw,
        )

        # Any call-side failure is itself a divergence — record which
        # server blew up so the operator can triage.
        if node_err is not None or python_err is not None:
            result.divergence = self._describe_call_failure(node_err, python_err)
            result.nodejs_result = node_err or node_raw
            result.python_result = python_err or python_raw
            return result

        # Project through extractors if provided.
        projected_node, projected_py = self._project(
            node_raw, python_raw, mode, id_extractor, name_extractor, score_extractor
        )
        result.nodejs_result = projected_node
        result.python_result = projected_py

        # Compare.
        if mode is ComparisonMode.EXACT:
            result.passed, result.divergence = self._compare_exact(
                projected_node, projected_py
            )
        elif mode is ComparisonMode.SET_EQUALITY:
            result.passed, result.divergence = self._compare_sets(
                projected_node, projected_py
            )
        elif mode is ComparisonMode.TOLERANCE:
            result.passed, result.divergence, extra = self._compare_tolerance(
                projected_node, projected_py, tol
            )
            result.extra.update(extra)
        else:  # pragma: no cover - ComparisonMode is exhaustive
            result.divergence = f"unknown comparison mode: {mode}"
        return result

    async def run_cases(
        self,
        cases: Iterable[ParityCase],
        *,
        module: str | None = None,
    ) -> ParitySummary:
        """Execute a sequence of :class:`ParityCase` and return a summary.

        Parameters
        ----------
        cases
            Cases to run.
        module
            Optional filter — only run cases whose ``case.module`` matches.
            Powers the ``--module`` CLI flag.
        """
        summary = ParitySummary()
        for case in cases:
            if module is not None and case.module != module:
                continue
            result = await self.assert_parity(
                case.tool_name,
                case.arguments,
                comparison=case.comparison,
                tolerance=case.effective_tolerance(),
                id_extractor=case.id_extractor,
                score_extractor=case.score_extractor,
                name_extractor=case.name_extractor,
            )
            summary.add(result)
        return summary

    # ── projection helpers ───────────────────────────────────────────

    @staticmethod
    def _project(
        node_raw: Any,
        python_raw: Any,
        mode: ComparisonMode,
        id_extractor: Callable[[Any], Sequence[Any]] | None,
        name_extractor: Callable[[Any], Iterable[Any]] | None,
        score_extractor: Callable[[Any], Sequence[float]] | None,
    ) -> tuple[Any, Any]:
        if mode is ComparisonMode.EXACT and id_extractor is not None:
            return list(id_extractor(node_raw)), list(id_extractor(python_raw))
        if mode is ComparisonMode.SET_EQUALITY and name_extractor is not None:
            return list(name_extractor(node_raw)), list(name_extractor(python_raw))
        if mode is ComparisonMode.TOLERANCE and score_extractor is not None:
            return (
                list(score_extractor(node_raw)),
                list(score_extractor(python_raw)),
            )
        # No projection — compare raw responses directly.
        return node_raw, python_raw

    # ── comparison helpers ───────────────────────────────────────────

    @staticmethod
    def _compare_exact(a: Any, b: Any) -> tuple[bool, str | None]:
        """Ordered deep-equals comparison."""
        if a == b:
            return True, None
        return False, f"not equal: nodejs={a!r} vs python={b!r}"

    @staticmethod
    def _compare_sets(a: Any, b: Any) -> tuple[bool, str | None]:
        """Order-insensitive multiset comparison.

        Uses :class:`collections.Counter` so duplicate names are compared
        faithfully (e.g. a tool that returns ``['foo', 'foo']`` should
        not pass parity against ``['foo']``).
        """
        try:
            ca, cb = Counter(a), Counter(b)
        except TypeError:
            return False, f"values are not hashable: nodejs={a!r} python={b!r}"
        if ca == cb:
            return True, None
        missing_in_python = ca - cb
        extra_in_python = cb - ca
        diffs = []
        if missing_in_python:
            diffs.append(f"missing in python: {dict(missing_in_python)}")
        if extra_in_python:
            diffs.append(f"extra in python: {dict(extra_in_python)}")
        return False, "; ".join(diffs)

    def _compare_tolerance(
        self, a: Any, b: Any, tol: float
    ) -> tuple[bool, str | None, dict[str, Any]]:
        """Element-wise relative tolerance comparison for numeric sequences.

        Both inputs must be sequences of the same length. A pair
        ``(x, y)`` is considered equal when
        ``|x - y| / max(|x|, |y|, 1) <= tol``. The ``max(..., 1)`` guard
        keeps near-zero values from producing spurious infinities.
        """
        try:
            seq_a = list(a)
            seq_b = list(b)
        except TypeError:
            return False, f"values are not sequences: nodejs={a!r} python={b!r}", {}

        if len(seq_a) != len(seq_b):
            return (
                False,
                f"length mismatch: nodejs={len(seq_a)} python={len(seq_b)}",
                {},
            )

        max_delta = 0.0
        violations: list[str] = []
        for i, (x, y) in enumerate(zip(seq_a, seq_b)):
            try:
                xf, yf = float(x), float(y)
            except (TypeError, ValueError):
                violations.append(f"index {i}: non-numeric ({x!r}, {y!r})")
                continue
            if not (math.isfinite(xf) and math.isfinite(yf)):
                violations.append(f"index {i}: non-finite ({xf}, {yf})")
                continue
            denom = max(abs(xf), abs(yf), 1.0)
            rel = abs(xf - yf) / denom
            max_delta = max(max_delta, rel)
            if rel > tol:
                violations.append(
                    f"index {i}: |{xf} - {yf}| / {denom} = {rel:.4f} > {tol}"
                )

        extra = {"max_relative_delta": max_delta, "tolerance": tol}
        if violations:
            # Keep the first few violations to avoid flooding the report.
            summary = "; ".join(violations[:3])
            if len(violations) > 3:
                summary += f" (+{len(violations) - 3} more)"
            return False, summary, extra
        return True, None, extra

    # ── transport wrappers ───────────────────────────────────────────

    @staticmethod
    async def _safe_call(
        caller: ToolCaller,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> tuple[Any, BaseException | None]:
        """Invoke ``caller`` and trap exceptions into a second return slot.

        Parity tests want to *report* a crash rather than fail the whole
        batch — an uncaught exception on one side is itself a divergence.
        """
        try:
            result = await caller(tool_name, arguments)
            return result, None
        except BaseException as exc:  # noqa: BLE001 — we intentionally catch all
            log.warning("tool %s raised %s: %s", tool_name, type(exc).__name__, exc)
            return None, exc

    @staticmethod
    def _describe_call_failure(
        node_err: BaseException | None, python_err: BaseException | None
    ) -> str:
        parts = []
        if node_err is not None:
            parts.append(f"nodejs raised {type(node_err).__name__}: {node_err}")
        if python_err is not None:
            parts.append(f"python raised {type(python_err).__name__}: {python_err}")
        return "; ".join(parts) or "both sides failed silently"


# ── CLI entrypoint ──────────────────────────────────────────────────────


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="parity_runner",
        description=(
            "Run declared parity cases against a Node.js + Python MCP server pair "
            "and print a summary report."
        ),
    )
    parser.add_argument(
        "--nodejs-url",
        default="http://localhost:3000/mcp",
        help="Streamable-HTTP MCP endpoint for the Node.js server "
        "(default: %(default)s).",
    )
    parser.add_argument(
        "--python-url",
        default="http://localhost:8000/mcp",
        help="Streamable-HTTP MCP endpoint for the Python server "
        "(default: %(default)s).",
    )
    parser.add_argument(
        "--module",
        default=None,
        help="Filter cases to a single module (e.g. semantic_search). "
        "If omitted, all cases in --cases-file are run.",
    )
    parser.add_argument(
        "--cases-file",
        default=None,
        help="Path to a JSON file containing an array of case descriptors "
        "(see ParityCase). If omitted, the CLI prints the report framework "
        "without running anything.",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=DEFAULT_TOLERANCE,
        help="Default relative tolerance for TOLERANCE-mode cases "
        "(default: %(default)s).",
    )
    parser.add_argument(
        "--nodejs-header",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Extra HTTP header for the Node.js transport; repeatable. "
        "Typically used for AgentCore bearer tokens.",
    )
    parser.add_argument(
        "--python-header",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Extra HTTP header for the Python transport; repeatable.",
    )
    return parser


def _parse_headers(pairs: Iterable[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"invalid header {pair!r}; expected KEY=VALUE")
        key, value = pair.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def _load_cases(path: str) -> list[ParityCase]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError(f"{path}: cases file must contain a JSON array")
    cases: list[ParityCase] = []
    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise ValueError(f"{path}[{i}]: case must be a JSON object")
        cases.append(
            ParityCase(
                tool_name=entry["tool_name"],
                arguments=entry.get("arguments") or {},
                comparison=ComparisonMode(entry.get("comparison", "exact")),
                tolerance=entry.get("tolerance"),
                module=entry.get("module"),
            )
        )
    return cases


async def _run_cli(args: argparse.Namespace) -> int:
    cases = _load_cases(args.cases_file) if args.cases_file else []
    if not cases:
        print(
            "No cases provided (pass --cases-file to execute parity "
            "checks). Framework is wired and ready."
        )
        return 0

    node_caller = HTTPJSONRPCToolCaller(
        args.nodejs_url,
        headers=_parse_headers(args.nodejs_header),
    )
    python_caller = HTTPJSONRPCToolCaller(
        args.python_url,
        headers=_parse_headers(args.python_header),
    )
    runner = ParityRunner(
        node_caller, python_caller, default_tolerance=args.tolerance
    )
    summary = await runner.run_cases(cases, module=args.module)
    print(summary.render_report())
    return 0 if summary.failed == 0 else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    return asyncio.run(_run_cli(args))


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    sys.exit(main())


# ── tenant header normalizer ────────────────────────────────────────────

import re

_TENANT_HEADER_RE = re.compile(r"^\*Tenant: [a-z][a-z0-9_]*\*\n\n")


def strip_tenant_header(text: str) -> str:
    """Remove the leading ``*Tenant: <id>*\\n\\n`` attribution header.

    Returns the body unchanged if no header is present.
    Used by self-parity tests so the attribution header (new in
    omd-tenants-1-foundation) doesn't cause false diffs against
    pre-tenancy baselines or between explicit/implicit tenant calls.
    """
    return _TENANT_HEADER_RE.sub("", text, count=1)


__all__ = [
    "ComparisonMode",
    "DEFAULT_TOLERANCE",
    "HTTPJSONRPCToolCaller",
    "ParityCase",
    "ParityResult",
    "ParityRunner",
    "ParitySummary",
    "ToolCaller",
    "main",
    "strip_tenant_header",
]
