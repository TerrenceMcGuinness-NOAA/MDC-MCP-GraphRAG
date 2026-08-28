"""Default-tenant reporting-vs-query regression tests.

shared-scope-query-routing Requirements 6.2, 6.5, 13.3; and
default-tenant-freeze-retirement Requirements 10.5, 10.6, 13.4 (Task 6.3).

Each test renders a tool through the hermetic capture harness
(:mod:`tests.baselines.capture`) against the baseline captured from the
revision immediately preceding the Phase 79 read-path routing change. The
seven scenarios split by tool into two groups, compared under two relations:

* **Three reporting tools** -- ``get_knowledge_base_status``,
  ``check_knowledge_integrity``, ``mcp_health_check`` -- are compared under
  **Structural_Equivalence** (:mod:`tests.baselines.structural`): the same
  set of Physical_Collections, the same per-collection document count, and
  the same per-check verdict, with wording, line order, and whitespace free
  to change. Task 6.3 retires Byte_Equivalence for these three (Phase 79
  R6.3 superseded by default-tenant-freeze-retirement), so a correction to
  the ``gw`` status total or the integrity sampler is expressible rather
  than blocked. Masks are not consulted here -- the relation reads
  structure, not bytes.
* **Four query tools** -- ``search_documentation``, ``search_ee2_standards``,
  ``search_architecture``, ``get_operational_guidance`` -- are checked under a
  **structural addressed-set plus hit-provenance** relation
  (:mod:`tests.baselines.addressing`). Task 8.3 retires Byte_Equivalence for
  these four (Phase 79 R6.2 superseded by default-tenant-freeze-retirement),
  paired with the benchmark comparison the nightly Regression_Check performs.
  Each scenario asserts that the set of Physical_Collections the tool
  addresses under the Default_Tenant is unchanged from the recorded
  expectation in ``expected/addressed_sets.json``, and that every hit a real
  Vector_Adapter returns over those collections carries a non-empty
  ``physical_collection``. The physical collection a read addressed is not
  recoverable from the rendered bytes at all, so this half is not a text
  comparison and the masks do not govern it. One consequence is stated so it
  is not found later: a pure formatting change to Query_Tool output -- a
  relabelled field, a changed separator, reordered hit metadata -- now passes
  both halves. That is a deliberate reduction in what is gated; the
  Consumer_Audit (Task 10) is what makes it tolerable.

The two groups are derived from each scenario's own tool name (the reporting
set below, and its complement) rather than from a second hardcoded list, so a
scenario added later cannot land in neither group and silently escape both
comparisons.

Before a Follow_Up_Sequence change actually moves default-tenant reporter
output, the reporter scenarios pass under Structural_Equivalence exactly as
they passed under Byte_Equivalence: the same recorded responses render the
same bytes, so the same structure. A fifth suite failure at this stage is
therefore attributable, not expected -- it becomes expected only when a
follow-up changes the output and re-records the baseline in the same change.

This file also enforces the Task 6.2 earned-mask invariant (all five checks
retained): every committed mask must trace back to a recorded double-run
difference, so the mask mechanism cannot be misused to hide a real regression.
No scenario's comparison consults the masks any longer -- the reporters moved
to Structural_Equivalence (Task 6.3) and the query tools moved to the
addressed-set plus hit-provenance relation (Task 8.3) -- but the earned-mask
machinery is retained deliberately as an instrument for a future high-surface
refactor, as ``tests/baselines/README.md`` records. Retiring the last
comparison that consulted the masks is not a reason to delete the guarantee
that keeps a mask honest.
"""

from __future__ import annotations

import json
import os
import types
from pathlib import Path

import pytest

from src.data.chromadb_adapter import ChromaDBAdapter
from src.data.opensearch_adapter import OpenSearchAdapter
from src.data.read_router import resolve_read_targets
from tests.baselines import addressing, capture, structural
from tests.properties.conftest import (
    FakeChromaClient,
    FakeOpenSearchRawClient,
)

pytestmark = pytest.mark.unit

SCENARIO_IDS = capture.scenario_ids()

# The four tool modules Requirement 13.3 requires a regression for, mapped to
# the scenario that covers each, so a dropped scenario fails loudly here rather
# than silently shrinking coverage.
_REQUIRED_MODULES = {
    "semantic_search",
    "ee2_compliance",
    "graph_rag",
    "operational",
}
# Phase 79 R6.3 names these three reporting tools explicitly. Task 6.3 moves
# them to Structural_Equivalence; they are also the reporting/query partition
# key below.
_REQUIRED_R63_TOOLS = {
    "get_knowledge_base_status",
    "check_knowledge_integrity",
    "mcp_health_check",
}

# Partition the scenarios by their own tool name -- not by a second hardcoded
# list -- so a scenario added later cannot land in neither group. The three
# reporting tools move to Structural_Equivalence (Task 6.3); every other
# scenario is a Query_Tool checked under the addressed-set plus hit-provenance
# relation (Task 8.3).
_REPORTING_SCENARIO_IDS = [
    s
    for s in SCENARIO_IDS
    if capture.load_scenario_by_id(s).tool in _REQUIRED_R63_TOOLS
]
_QUERY_SCENARIO_IDS = [
    s
    for s in SCENARIO_IDS
    if capture.load_scenario_by_id(s).tool not in _REQUIRED_R63_TOOLS
]


# ── coverage guards ────────────────────────────────────────────────────────


def test_required_modules_are_covered() -> None:
    """R13.3: a regression scenario exists for each of the four modules."""
    covered = {capture.load_scenario_by_id(s).module for s in SCENARIO_IDS}
    missing = _REQUIRED_MODULES - covered
    assert not missing, f"no regression scenario for module(s) {missing}"


def test_required_r63_reporting_tools_are_covered() -> None:
    """R10.6: status, integrity, and health each have a no-tenant scenario.

    Relaxing the comparison to Structural_Equivalence must not become an
    opportunity to quietly shrink what is compared, so the coverage guard for
    the three reporting tools stays exactly as it was under byte-equivalence.
    """
    tools = {capture.load_scenario_by_id(s).tool for s in SCENARIO_IDS}
    missing = _REQUIRED_R63_TOOLS - tools
    assert not missing, f"missing R6.3 reporting scenario(s): {missing}"


def test_scenario_partition_is_total_and_disjoint() -> None:
    """Every scenario is compared under exactly one relation.

    Deriving the Query_Tool group as the complement of the reporting group
    guarantees a newly added scenario lands in exactly one partition rather
    than silently escaping both comparisons.
    """
    reporting = set(_REPORTING_SCENARIO_IDS)
    query = set(_QUERY_SCENARIO_IDS)
    assert reporting.isdisjoint(query)
    assert reporting | query == set(SCENARIO_IDS)
    assert reporting, "no reporting scenario found to compare structurally"
    assert query, (
        "no query scenario found to check for addressed-set + provenance"
    )


def test_no_scenario_declares_a_tenant_id() -> None:
    """R6.2/R6.3 compare the *default*-tenant response: no tenant_id set."""
    for scenario_id in SCENARIO_IDS:
        scenario = capture.load_scenario_by_id(scenario_id)
        assert "tenant_id" not in scenario.args, (
            f"{scenario_id}: default-tenant baseline must freeze no tenant_id"
        )


# ── reporting tools: Structural_Equivalence (Task 6.3) ───────────────────────


@pytest.mark.parametrize("scenario_id", _REPORTING_SCENARIO_IDS)
async def test_reporting_tools_structural_equivalence(
    scenario_id: str,
) -> None:
    """R10.5: reporter output is Structurally_Equivalent to the baseline.

    Task 6.3 supersedes Byte_Equivalence for the Status_Reporter, the
    Integrity_Checker, and the Health_Reporter (Phase 79 R6.3). Each of the
    three reporter scenarios is compared under the Requirement 9 relation --
    equal set of Physical_Collection names, equal per-collection document
    count, equal per-check verdict -- and is free to reword, reorder, and
    re-space. The masks are irrelevant to a structural comparison, so the
    reporting scenarios do not consult them.
    """
    scenario = capture.load_scenario_by_id(scenario_id)
    baseline = capture.load_baseline(scenario_id)

    candidate = await capture.render(scenario)

    findings = structural.compare_structural(
        structural.parse_structural(baseline),
        structural.parse_structural(candidate),
    )

    assert findings == [], (
        f"{scenario_id}: rendered output is not Structurally_Equivalent to "
        f"the pre-change baseline. Each finding names the diverging "
        f"Physical_Collection or check:\n" + "\n".join(findings)
    )


# ── query tools: addressed-set + hit-provenance (Task 8.3) ───────────────────
#
# Task 8.3 supersedes Byte_Equivalence for the four Query_Tool scenarios
# (Phase 79 R6.2, superseded by default-tenant-freeze-retirement). Two things
# replace it, and both are necessary:
#
#   * the addressed-set half catches a dropped collection -- a quality score
#     cannot, because the surviving member of a two-member set still answers
#     the corpus queries and coverage may not move; and
#   * the benchmark comparison (run by the nightly Regression_Check, not here)
#     catches degraded retrieval -- the addressed-set half cannot, because the
#     right collections can be addressed and still return worse hits.
#
# This module owns the addressed-set half and the paired hit-provenance check
# (R11.6). The benchmark half lives in the nightly wrapper. Neither half reads
# rendered text: physical addressing is not recoverable from a Query_Tool's
# rendered response, so `capture.render` is not used here (see
# tests/baselines/addressing.py, and Phase 79 finding 6).

_ADDRESSED_SETS_PATH = (
    Path(capture.__file__).resolve().parent
    / "expected"
    / "addressed_sets.json"
)


def _expected_addressed_sets() -> dict:
    """Load the recorded Default_Tenant addressed-set expectations.

    Recorded by Task 8.1 in ``expected/addressed_sets.json``, keyed tool
    name then Embedding_Profile short name. This is the "before the change"
    reference the R11.2 structural check compares against: a routing change
    that drops or adds a member fails against it.
    """
    return json.loads(_ADDRESSED_SETS_PATH.read_text(encoding="utf-8"))


def _build_vector_adapter(backend: str, profile: str):
    """Construct a real Vector_Adapter over a recording client double.

    The provenance half of Requirement 11 criterion 2 needs hits stamped
    with ``physical_collection``, and only the real adapters stamp it (their
    ``_stamp_provenance`` / merge paths). The capture stub replaces the
    adapter wholesale and receives the logical name, so it never stamps --
    which is exactly why this check drives the real adapter rather than
    re-rendering the scenario.

    The adapter is the one the scenario's Backend selects -- OpenSearch for
    ``aws``, ChromaDB otherwise -- so provenance is exercised on the same
    stamping path the frozen response used. Hermetic: the client is a canned
    recording double, the embedding function is a constant, and
    ``_connected`` is pinned True so no socket is opened.

    Returns
    -------
    tuple
        ``(adapter, fake_client)``. ``fake_client`` exposes ``add_index``
        (OpenSearch) or ``add_collection`` (ChromaDB) for seeding.
    """
    def _embed(texts: list[str]) -> list[list[float]]:
        return [[0.0, 0.0] for _ in texts]

    # The adapter reads MCP_EMBEDDING_PROFILE in __init__, so pin it for the
    # scope of construction and restore it -- the addressed-set half compares
    # against this same profile, keeping the seeded physical names and the
    # adapter's internal resolution in agreement.
    prior = os.environ.get("MCP_EMBEDDING_PROFILE")
    os.environ["MCP_EMBEDDING_PROFILE"] = profile
    try:
        if backend == "aws":
            adapter = OpenSearchAdapter(
                endpoint="https://example.invalid",
                embedding_function=_embed,
            )
            fake = FakeOpenSearchRawClient()
            adapter._client = types.SimpleNamespace(_client=fake)
            adapter._connected = True
        else:
            adapter = ChromaDBAdapter(embedding_function=_embed)
            fake = FakeChromaClient()
            adapter._client = fake
            adapter._connected = True
    finally:
        if prior is None:
            os.environ.pop("MCP_EMBEDDING_PROFILE", None)
        else:
            os.environ["MCP_EMBEDDING_PROFILE"] = prior
    return adapter, fake


async def _stamped_query_hits(
    tool: str, backend: str, profile: str
) -> list[dict]:
    """Return hits a real Vector_Adapter stamps over ``tool``'s collections.

    For each Logical_Collection ``tool`` reads (per
    :data:`addressing.TOOL_LOGICAL_COLLECTIONS`), the addressed
    Physical_Collection is seeded with one canned hit and queried through the
    adapter, which stamps ``physical_collection``. Mirrors the seeding of
    Property 13's provenance clause so the unit and property checks cannot
    drift in how they obtain stamped hits.
    """
    adapter, fake = _build_vector_adapter(backend, profile)
    canned = {"id": "probe-0", "content": "x", "score": 0.5}
    hits: list[dict] = []
    for logical in addressing.TOOL_LOGICAL_COLLECTIONS[tool]:
        resolved = resolve_read_targets(logical, None, profile=profile)
        physical = resolved.physical_names[0]
        if hasattr(fake, "add_collection"):
            fake.add_collection(
                physical,
                response={
                    "ids": [[canned["id"]]],
                    "documents": [[canned["content"]]],
                    "metadatas": [[{}]],
                    "distances": [[0.1]],
                },
            )
        else:
            fake.add_index(
                physical,
                hits=[
                    {
                        "_id": canned["id"],
                        "_score": 0.9,
                        "_source": {
                            "content": canned["content"],
                            "metadata": {},
                        },
                    }
                ],
            )
        hits.extend(await adapter.query(logical, "probe query", k=1))
    return hits


@pytest.mark.parametrize("scenario_id", _QUERY_SCENARIO_IDS)
async def test_query_tools_addressed_set_and_provenance(
    scenario_id: str,
) -> None:
    """R11.2/R11.6: Query_Tool addressing is unchanged and hits are stamped.

    Task 8.3 supersedes the Phase 79 R6.2 byte-freeze for the Query_Tools
    with a paired gate. This module owns the structural half; the benchmark
    half is the nightly Regression_Check's. Two assertions, kept distinct
    because they fail for different reasons a reviewer must tell apart:

    * **Addressed-set unchanged.** The set of Physical_Collections the tool
      addresses under the Default_Tenant equals the recorded expectation in
      ``expected/addressed_sets.json``. A routing change that drops or adds a
      member fails here with the differing member named -- the check a
      quality score structurally cannot make, since the surviving member of a
      two-member set still answers the corpus queries.
    * **Hits carry provenance.** Every hit a real Vector_Adapter returns over
      those collections carries a non-empty ``physical_collection`` that is a
      member of the addressed set. ``check_hit_provenance`` returns findings
      rather than raising, so its result is asserted, never discarded.
    """
    scenario = capture.load_scenario_by_id(scenario_id)
    backend = scenario.env.get("DB_BACKEND", "aws")
    profile = scenario.env.get("MCP_EMBEDDING_PROFILE", "titan1024")

    addressed = addressing.addressed_set(
        scenario.tool, tenant=None, profile=profile
    )
    expected = _expected_addressed_sets()
    expected_set = frozenset(expected[scenario.tool][profile])
    assert addressed == expected_set, (
        f"{scenario_id}: {scenario.tool} addresses "
        f"{sorted(addressed)} under the Default_Tenant, but the recorded "
        f"pre-change set is {sorted(expected_set)}. A member added or "
        f"dropped here is a routing change to the Default_Tenant read path."
    )

    hits = await _stamped_query_hits(scenario.tool, backend, profile)

    findings = addressing.check_hit_provenance(hits, addressed)
    assert findings == [], (
        f"{scenario_id}: one or more hits lack a valid physical_collection. "
        f"Each finding names the offending hit:\n" + "\n".join(findings)
    )


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_attribution_header_is_part_of_the_baseline(scenario_id: str) -> None:
    """R6.2: the ``*Tenant: gw*`` header is included in the compared bytes.

    Tenant-scoped tools carry it; the server-global ``mcp_health_check``
    does not. The header is retained in the comparison rather than stripped,
    so a change to the attribution lines is caught. This guard stays for
    every scenario it currently covers -- the addressed-set-checked query
    tools and the structural reporters alike -- since the attribution header
    is a property of the recorded baseline regardless of the comparison
    relation applied to the rest of the response.
    """
    scenario = capture.load_scenario_by_id(scenario_id)
    baseline = capture.load_baseline(scenario_id)
    if scenario.tenant_scoped:
        assert baseline.startswith("*Tenant: gw*\n"), (
            f"{scenario_id}: tenant-scoped baseline missing gw header"
        )
    else:
        assert not baseline.startswith("*Tenant:"), (
            f"{scenario_id}: server-global tool must carry no header"
        )


# ── earned-mask enforcement (Task 6.2, retained per R13.4) ───────────────────


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_every_committed_mask_is_earned(scenario_id: str) -> None:
    """R6.5/R13.4: each committed mask traces to a double-run difference.

    Re-derives the mask set from the two recorded runs (the ``.md``
    baseline and the ``.b.md`` evidence) and rejects any committed mask
    that does not match. A hand-added mask cannot survive this check. The
    guarantee is retained over every scenario -- retiring byte-equality for
    the three reporters does not retire the earned-mask guarantee that stops
    a mask being used to paper over a real regression.
    """
    run_a = capture.load_baseline(scenario_id)
    run_b = capture.load_evidence(scenario_id)
    masks = capture.load_masks(scenario_id)

    findings = capture.verify_masks_earned(masks, run_a, run_b)

    assert findings == [], (
        f"{scenario_id}: {len(findings)} unearned mask finding(s): {findings}"
    )


def test_hand_added_mask_over_identical_runs_is_rejected() -> None:
    """A fabricated mask with no underlying volatility must be rejected."""
    run_a = "Total Documents: 129013\nStatus: OK\n"
    run_b = "Total Documents: 129013\nStatus: OK\n"  # identical: no volatility
    bogus = [{"a": [0, 5], "b": [0, 5], "a_text": "Total", "b_text": "Total"}]

    findings = capture.verify_masks_earned(bogus, run_a, run_b)

    assert findings, "a mask over identical runs must fail the earned check"


def test_over_broad_hand_added_mask_is_rejected() -> None:
    """Masking a whole line when only a substring is volatile is rejected."""
    run_a = "latency 5ms done"
    run_b = "latency 9ms done"
    over_broad = [
        {
            "a": [0, len(run_a)],
            "b": [0, len(run_b)],
            "a_text": run_a,
            "b_text": run_b,
        }
    ]

    findings = capture.verify_masks_earned(over_broad, run_a, run_b)

    assert findings, "an over-broad line mask must fail the earned check"


# ── mask machinery sanity (real volatile span) ───────────────────────────────


def test_earned_mask_tolerates_only_the_volatile_span() -> None:
    """A correctly-earned substring mask passes and bounds its wildcard.

    Our seven scenarios are deterministic, so their mask sets are empty and
    the query-tool comparison is exact. This exercises the mask machinery on
    a genuine volatile span to prove it (a) accepts an earned mask, (b)
    tolerates a change inside the masked span, and (c) still rejects a change
    outside it.
    """
    run_a = "latency 5ms done"
    run_b = "latency 9ms done"

    masks = capture.derive_masks(run_a, run_b)

    assert masks, "a real character difference must yield at least one mask"
    assert capture.verify_masks_earned(masks, run_a, run_b) == []
    # Tolerates a different value in the volatile span ...
    assert capture.matches_baseline(run_a, masks, "latency 7ms done")
    # ... but not a change outside it.
    assert not capture.matches_baseline(run_a, masks, "latency 5ms FAIL")


def test_matches_baseline_is_exact_without_masks() -> None:
    """With no masks the comparison is exact string equality."""
    assert capture.matches_baseline("abc\n", [], "abc\n")
    assert not capture.matches_baseline("abc\n", [], "abd\n")
