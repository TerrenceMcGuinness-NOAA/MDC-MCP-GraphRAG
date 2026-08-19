"""Default-tenant byte-equivalence capture harness (Task 6.1 / 6.2).

shared-scope-query-routing Requirements 6.5 and 13.3.

Why this file lives under ``tests/`` and not ``scripts/``
--------------------------------------------------------
Requirement 12.2 freezes ``mcp_server_python/scripts/`` byte-for-byte, and
a test enforces it. A capture harness placed there would violate the very
requirement it exists to help verify. It therefore lives under
``tests/baselines/``.

What the harness does
---------------------
For each scenario declared in ``recorded_backend/*.json`` it:

1. Builds a :class:`_StubDataAccess` whose vector and graph adapters replay
   a *recorded* response rather than hitting a live backend. That freezes
   store content by construction, so a later comparison isolates
   *rendering* from *data drift* -- the same recorded responses feed both
   the pre-change and the post-change run (R13.3).
2. Registers the owning tool module on a fresh ``FastMCP`` server with that
   stub injected as the data-access facade.
3. Invokes the frozen tool with the frozen argument set (never a
   ``tenant_id``, so resolution lands on the default ``gw`` tenant) and
   returns the complete rendered response, attribution header included.

Every environment input that steers rendering is frozen per scenario:
``DB_BACKEND`` (selects the backend label), ``MCP_EMBEDDING_PROFILE``
(selects the physical-name map), and ``PYTEST_CURRENT_TEST``. The last is
pinned deliberately: ``graph_rag.search_architecture`` and
``graph_rag.get_change_impact`` branch on ``"pytest" in sys.modules or
PYTEST_CURRENT_TEST`` (an in-tree testing affordance), so a baseline
captured from the command line would otherwise take a different code path
than the pytest-hosted regression test that re-renders against it. Pinning
the variable makes both contexts take the same branch.

Volatility masks (Task 6.2)
---------------------------
``main()`` renders each scenario *twice* over identical inputs and diffs
the two outputs with :func:`derive_masks`. Any character span that differs
between two runs of the *same* code is volatile (a generated timestamp is
the archetype). Each such span is recorded as a mask. A mask cannot be
added by hand: :func:`verify_masks_earned` re-derives the mask set from the
two recorded runs and rejects any committed mask that does not trace back
to a demonstrated double-run difference. See
``tests/unit/test_default_tenant_byte_equivalence.py``.

Header handling
---------------
The rendered baseline retains the ``*Tenant: gw*`` / ``*Branch: develop*``
attribution header, because Requirement 6.2 requires byte-equivalence
*including* the attribution header lines. :func:`strip_tenant_header` from
the tenancy parity suite is reused for header-aware handling so treatment
stays consistent with that suite; note it is applied only for the
diagnostic ``header``/``body`` split, never to remove the header from the
authoritative comparison.

Regenerating the baselines
---------------------------
::

    cd mcp_server_python
    python3.12 -m tests.baselines.capture

This rewrites ``pre_change/<scenario>.md`` (run A, the canonical
baseline), ``pre_change/<scenario>.b.md`` (run B, the volatility
evidence), and ``pre_change/<scenario>.masks.json`` (the earned masks).
"""

from __future__ import annotations

import asyncio
import copy
import difflib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from tests.parity.parity_runner import strip_tenant_header

# ── paths ────────────────────────────────────────────────────────────────

BASELINE_DIR: Path = Path(__file__).resolve().parent
RECORDED_DIR: Path = BASELINE_DIR / "recorded_backend"
PRE_CHANGE_DIR: Path = BASELINE_DIR / "pre_change"

#: One shared scratch directory for SessionManager / health-snapshot state so
#: rendering a scenario never writes into the repo tree. Created lazily.
_STATE_ROOT: Path | None = None


def _state_root() -> Path:
    global _STATE_ROOT
    if _STATE_ROOT is None:
        _STATE_ROOT = Path(tempfile.mkdtemp(prefix="baseline-state-"))
    return _STATE_ROOT


# ── recorded-response stubs ───────────────────────────────────────────────


class _StubVectorDB:
    """Replay a recorded vector-adapter response.

    The stub returns the recorded payload regardless of the collection
    name or query text it is handed: store content is frozen by
    construction, so the only thing that can vary between the pre-change
    and post-change runs is the rendering. A deep copy is returned on
    every call so a tool that mutates a hit in place cannot leak state
    into the second run of a double-capture.
    """

    def __init__(self, spec: dict[str, Any]) -> None:
        self._spec = spec
        self.connected = True

    async def connect(self) -> None:  # pragma: no cover - never reached
        self.connected = True

    async def close(self) -> None:  # pragma: no cover - never reached
        self.connected = False

    async def query(
        self,
        collection: str,
        query_text: str,
        *,
        k: int = 10,
        similarity_threshold: float = 0.0,
        where: dict[str, Any] | None = None,
        include_graph: bool = True,
        tenant: Any = None,
    ) -> list[dict[str, Any]]:
        return copy.deepcopy(self._spec.get("query", []))

    async def multi_collection_query(
        self,
        collections: list[str],
        query_text: str,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        payload = self._spec.get("multi_collection_query")
        if payload is None:
            payload = self._spec.get("query", [])
        return copy.deepcopy(payload)

    async def list_collections(self) -> list[str]:
        return list(self._spec.get("list_collections", []))

    async def count_documents(self, collection: str) -> int:
        counts = self._spec.get("count_documents")
        if isinstance(counts, dict):
            return int(counts.get(collection, 0))
        return int(counts or 0)

    async def sample_metadata(
        self,
        collection: str | None = None,
        limit: int = 50,
        *,
        n: int | None = None,
    ) -> list[dict[str, Any]]:
        return copy.deepcopy(self._spec.get("sample_metadata", []))

    async def health_check(self, *, deep: bool = False) -> dict[str, Any]:
        default = {
            "status": "healthy",
            "connected": True,
            "indices": [],
            "collections": [],
            "total_documents": 0,
            "latency_ms": 5,
        }
        return copy.deepcopy(self._spec.get("health_check", default))


class _StubGraphDB:
    """Replay recorded graph-adapter responses, dispatched by cypher shape.

    ``query`` recognises the small, fixed family of read queries the
    status and integrity paths issue -- per-label node counts, per-type
    relationship counts, the orphaned-node File probe, and the
    coverage-gap multi-label count -- and returns the recorded number for
    each. It never opens a socket.
    """

    _LABEL_COUNT_RE = re.compile(r"\(n:(\w+)\)\s*RETURN count\(n\) AS count")
    _REL_COUNT_RE = re.compile(r"\[r:(\w+)\]")
    _COVERAGE_LABEL_RE = re.compile(r"WHERE\s+n:(\w+)")

    def __init__(self, spec: dict[str, Any]) -> None:
        self._spec = spec

    async def connect(self) -> None:  # pragma: no cover - never reached
        pass

    async def close(self) -> None:  # pragma: no cover - never reached
        pass

    async def query(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
        tenant: Any = None,
        *,
        timeout: float | None = None,
    ) -> list[dict[str, Any]]:
        # Explicit fragment overrides win first.
        for fragment, rows in (self._spec.get("fragments") or {}).items():
            if fragment and fragment in cypher:
                return copy.deepcopy(rows)

        m = self._LABEL_COUNT_RE.search(cypher)
        if m:
            counts = self._spec.get("label_counts", {})
            return [{"count": int(counts.get(m.group(1), 0))}]

        if "count(r) AS count" in cypher:
            m = self._REL_COUNT_RE.search(cypher)
            if m:
                counts = self._spec.get("rel_counts", {})
                return [{"count": int(counts.get(m.group(1), 0))}]

        if "count(n) AS total" in cypher and "WHERE" in cypher:
            m = self._COVERAGE_LABEL_RE.search(cypher)
            key = m.group(1) if m else ""
            counts = self._spec.get("coverage_counts", {})
            return [{"total": int(counts.get(key, 0))}]

        if "count(f) AS total" in cypher:
            return [{"total": int(self._spec.get("file_total", 0))}]

        if "f.name AS name" in cypher:
            return copy.deepcopy(self._spec.get("file_sample", []))

        if "count(n) AS total" in cypher:  # whole-graph probe (all_tenants)
            return [{"total": int(self._spec.get("whole_total", 0))}]

        return copy.deepcopy(self._spec.get("default", []))

    async def get_statistics(self) -> dict[str, Any]:
        return copy.deepcopy(self._spec.get("statistics", {}))

    async def health_check(self) -> dict[str, Any]:
        default = {
            "status": "healthy",
            "connected": True,
            "nodes": 0,
            "relationships": 0,
            "latency_ms": 12,
        }
        return copy.deepcopy(self._spec.get("health", default))


class _StubDataAccess:
    """``UnifiedDataAccess``-shaped facade over the recorded stubs."""

    def __init__(self, recorded: dict[str, Any]) -> None:
        self.vector_db = (
            _StubVectorDB(recorded["vector"])
            if "vector" in recorded
            else None
        )
        self.graph_db = (
            _StubGraphDB(recorded["graph"])
            if "graph" in recorded
            else None
        )
        self._data_health = recorded.get("data_health")

    async def connect(self) -> None:  # pragma: no cover - never reached
        pass

    async def close(self) -> None:  # pragma: no cover - never reached
        pass

    async def health_check(
        self, *, deep: bool = False, min_indices: int = 5
    ) -> dict[str, Any]:
        return copy.deepcopy(self._data_health)


# ── scenario loading ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class Scenario:
    """One frozen capture scenario from ``recorded_backend/<id>.json``."""

    scenario_id: str
    module: str
    tool: str
    args: dict[str, Any]
    env: dict[str, str]
    tenant_scoped: bool
    recorded: dict[str, Any] = field(repr=False)


def load_scenario(path: Path) -> Scenario:
    """Load and validate one scenario file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return Scenario(
        scenario_id=data["scenario_id"],
        module=data["module"],
        tool=data["tool"],
        args=data["args"],
        env=data.get("env", {}),
        tenant_scoped=bool(data.get("tenant_scoped", False)),
        recorded=data,
    )


def scenario_files() -> list[Path]:
    """Return the recorded scenario files, name-sorted for reproducibility."""
    return sorted(RECORDED_DIR.glob("*.json"))


def scenario_ids() -> list[str]:
    """Return every scenario id, sorted."""
    return [load_scenario(p).scenario_id for p in scenario_files()]


def load_scenario_by_id(scenario_id: str) -> Scenario:
    """Load a single scenario by its id."""
    path = RECORDED_DIR / f"{scenario_id}.json"
    return load_scenario(path)


# ── environment freezing ─────────────────────────────────────────────────


class _frozen_env:
    """Context manager that pins the scenario's environment inputs.

    Sets ``DB_BACKEND`` and ``MCP_EMBEDDING_PROFILE`` from the scenario,
    pins ``PYTEST_CURRENT_TEST`` (so the ``is_testing`` branch in
    ``graph_rag`` is taken in both the CLI capture and the pytest
    regression run), and redirects ``SDD_STATE_DIR`` to a scratch
    directory so no scenario writes into the repo tree. Prior values are
    restored on exit.
    """

    _KEYS = ("DB_BACKEND", "MCP_EMBEDDING_PROFILE",
             "PYTEST_CURRENT_TEST", "SDD_STATE_DIR")

    def __init__(self, scenario: Scenario) -> None:
        self._scenario = scenario
        self._saved: dict[str, str | None] = {}

    def __enter__(self) -> "_frozen_env":
        for key in self._KEYS:
            self._saved[key] = os.environ.get(key)
        os.environ["DB_BACKEND"] = self._scenario.env.get("DB_BACKEND", "aws")
        os.environ["MCP_EMBEDDING_PROFILE"] = self._scenario.env.get(
            "MCP_EMBEDDING_PROFILE", "titan1024"
        )
        os.environ["PYTEST_CURRENT_TEST"] = "baseline-capture"
        os.environ["SDD_STATE_DIR"] = str(_state_root())
        return self

    def __exit__(self, *exc: Any) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# ── server construction and invocation ─────────────────────────────────────


def _build_server(module: str, data: _StubDataAccess) -> FastMCP:
    """Register ``module``'s tools on a fresh server with ``data`` injected."""
    mcp = FastMCP("baseline-capture", version="1.0.0")
    no_repo = _state_root() / "no_such_repo"
    if module == "semantic_search":
        from src.tools import semantic_search
        # A non-existent repo_base pins the integrity coverage-gap check to
        # its graph-only branch and the stale-embeddings check to the
        # 30-day-threshold method, both of which are deterministic.
        semantic_search.register(mcp, data=data, repo_base=no_repo)
    elif module == "ee2_compliance":
        from src.tools import ee2_compliance
        ee2_compliance.register(mcp, data=data)
    elif module == "graph_rag":
        from src.tools import graph_rag
        graph_rag.register(mcp, data=data)
    elif module == "operational":
        from src.tools import operational
        operational.register(mcp, data=data)
    elif module == "utility":
        from src.tools import utility
        utility.register(mcp, data=data, state_dir=_state_root())
    else:  # pragma: no cover - guarded by scenario validation
        raise ValueError(f"unknown module: {module!r}")
    return mcp


async def _invoke(mcp: FastMCP, tool_name: str, args: dict[str, Any]) -> str:
    tool = await mcp.get_tool(tool_name)
    result = await tool.run(args)
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text is not None:
            return text
    return str(result)


async def render(scenario: Scenario) -> str:
    """Render one scenario's complete tool response (header included).

    Hermetic: the data-access facade is a recorded-response stub, so no
    OpenSearch, Neptune, or Bedrock call is made.
    """
    with _frozen_env(scenario):
        data = _StubDataAccess(scenario.recorded)
        mcp = _build_server(scenario.module, data)
        return await _invoke(mcp, scenario.tool, dict(scenario.args))


def header_and_body(text: str) -> tuple[str, str]:
    """Split an attribution header from the body using the parity utility.

    Reuses :func:`tests.parity.parity_runner.strip_tenant_header` so header
    handling matches the tenancy parity suite. Diagnostic only -- the
    authoritative byte-equivalence comparison is over the full text,
    because Requirement 6.2 includes the attribution header lines.
    """
    body = strip_tenant_header(text)
    header = text[: len(text) - len(body)]
    return header, body


# ── volatility masks (Task 6.2) ───────────────────────────────────────────


def derive_masks(run_a: str, run_b: str) -> list[dict[str, Any]]:
    """Return the volatile spans between two runs of the same code.

    Each mask is a character span that differs between ``run_a`` and
    ``run_b`` -- i.e. a span that is volatile under a fixed input and must
    be tolerated by the byte-equivalence comparison (R6.5). The diff is
    computed at character granularity so a mask covers only the volatile
    substring, never a whole line when a single token varies.

    Returns
    -------
    list of dict
        One entry per differing span with keys ``a`` (``[start, end]`` in
        ``run_a``), ``b`` (``[start, end]`` in ``run_b``), ``a_text``, and
        ``b_text``. Ordered by position in ``run_a``.
    """
    matcher = difflib.SequenceMatcher(None, run_a, run_b, autojunk=False)
    masks: list[dict[str, Any]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        masks.append(
            {
                "a": [i1, i2],
                "b": [j1, j2],
                "a_text": run_a[i1:i2],
                "b_text": run_b[j1:j2],
            }
        )
    return masks


def verify_masks_earned(
    masks: list[dict[str, Any]], run_a: str, run_b: str
) -> list[str]:
    """Return findings if any mask is not earned by the recorded double-run.

    A mask is *earned* only when it appears in the character diff between
    the two recorded runs of the pre-change code. This re-derives the mask
    set from ``run_a`` and ``run_b`` and reports any committed mask that
    does not match, and any mask whose two spans are textually identical
    (which is not a real difference and so cannot have been produced by the
    diff). An empty list means every mask is earned.
    """
    findings: list[str] = []
    expected = derive_masks(run_a, run_b)

    def _key(m: dict[str, Any]) -> tuple[Any, ...]:
        return (
            tuple(m["a"]),
            tuple(m["b"]),
            m.get("a_text"),
            m.get("b_text"),
        )

    expected_keys = {_key(m) for m in expected}
    for mask in masks:
        if mask.get("a_text") == mask.get("b_text"):
            findings.append(
                "unearned mask: a_text equals b_text (no real difference) "
                f"at a-span {mask.get('a')}"
            )
            continue
        if _key(mask) not in expected_keys:
            findings.append(
                "unearned mask: does not trace to a recorded double-run "
                f"difference at a-span {mask.get('a')}"
            )
    committed_keys = {_key(m) for m in masks}
    for missing in expected_keys - committed_keys:
        findings.append(
            f"undeclared volatile span not masked: a-span {list(missing[0])}"
        )
    return findings


def masks_to_regex(baseline: str, masks: list[dict[str, Any]]) -> str:
    """Build an anchored regex from ``baseline`` with masks as wildcards.

    Non-masked regions are matched literally (``re.escape``); each masked
    span becomes a minimal ``[\\s\\S]*?`` wildcard. Because every literal
    region is exact and anchored, a regression outside a mask changes a
    literal region and fails the match; only the earned volatile spans are
    tolerated.
    """
    spans = sorted(tuple(m["a"]) for m in masks)
    parts: list[str] = []
    pos = 0
    for start, end in spans:
        parts.append(re.escape(baseline[pos:start]))
        parts.append(r"[\s\S]*?")
        pos = end
    parts.append(re.escape(baseline[pos:]))
    return "^" + "".join(parts) + "$"


def matches_baseline(
    baseline: str, masks: list[dict[str, Any]], candidate: str
) -> bool:
    """True if ``candidate`` equals ``baseline`` outside the masked spans.

    With no masks this is exact string equality -- the strongest guard.
    """
    if not masks:
        return baseline == candidate
    return re.fullmatch(masks_to_regex(baseline, masks), candidate) is not None


# ── baseline file layout helpers ────────────────────────────────────────────


def baseline_path(scenario_id: str) -> Path:
    """Path to the canonical run-A baseline (``pre_change/<id>.md``)."""
    return PRE_CHANGE_DIR / f"{scenario_id}.md"


def evidence_path(scenario_id: str) -> Path:
    """Path to the run-B volatility evidence (``pre_change/<id>.b.md``)."""
    return PRE_CHANGE_DIR / f"{scenario_id}.b.md"


def masks_path(scenario_id: str) -> Path:
    """Path to the earned masks (``pre_change/<id>.masks.json``)."""
    return PRE_CHANGE_DIR / f"{scenario_id}.masks.json"


def load_baseline(scenario_id: str) -> str:
    return baseline_path(scenario_id).read_text(encoding="utf-8")


def load_evidence(scenario_id: str) -> str:
    return evidence_path(scenario_id).read_text(encoding="utf-8")


def load_masks(scenario_id: str) -> list[dict[str, Any]]:
    return json.loads(masks_path(scenario_id).read_text(encoding="utf-8"))


# ── regeneration entrypoint ────────────────────────────────────────────────


async def _capture_one(
    scenario: Scenario,
) -> tuple[str, str, list[dict[str, Any]]]:
    run_a = await render(scenario)
    run_b = await render(scenario)
    masks = derive_masks(run_a, run_b)
    return run_a, run_b, masks


def regenerate() -> int:
    """Recapture every scenario and rewrite the ``pre_change/`` artefacts."""
    PRE_CHANGE_DIR.mkdir(parents=True, exist_ok=True)
    total_masks = 0
    for path in scenario_files():
        scenario = load_scenario(path)
        run_a, run_b, masks = asyncio.run(_capture_one(scenario))
        baseline_path(scenario.scenario_id).write_text(run_a, encoding="utf-8")
        evidence_path(scenario.scenario_id).write_text(run_b, encoding="utf-8")
        masks_path(scenario.scenario_id).write_text(
            json.dumps(masks, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        total_masks += len(masks)
        print(
            f"[capture] {scenario.scenario_id}: "
            f"{len(run_a)} bytes, {len(masks)} mask(s)"
        )
    print(
        f"[capture] {len(scenario_files())} scenario(s), "
        f"{total_masks} earned mask(s) total"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - regeneration entrypoint
    raise SystemExit(regenerate())
