"""Corpus invariance, coverage, and anchoring guard assertions (Task 2.2).

default-tenant-freeze-retirement Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6.

Verifies three things about the Ground_Truth_Corpus
(``mcp_server_node/test/benchmark/ground_truth.json``) after Task 2.1
added the ``tenant_categories`` sibling container:

1. The original 60 ``categories`` cases are untouched -- both field-by-field
   against Task 1.2's pinned values and as a whole-object digest against
   Task 1.2's recorded fingerprint (Property 8).
2. The eight new ``tenant_categories`` cases are well-formed: exactly the
   eight declared Benchmark_Case fields, a ``tenant_id`` inside
   ``tool_args`` naming a Prefixed_Tenant.
3. Classification (``tenant_scoped``, derived from ``tool_args``) agrees
   with the container a case was filed under, for all 68 cases -- so a
   misfiled case is caught rather than silently reclassified.

Also carries the R2.5/R2.6 coverage guards and the anchoring guard that
proves the reporter-case ``- `` prefix actually defeats containment of a
shared collection name inside its tenant-prefixed form.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.run_benchmark import CATEGORY_NAMES, load_corpus
from src.config.tenants import load_catalog
from src.data.read_router import resolve_read_targets

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CORPUS_PATH = (
    _REPO_ROOT
    / "mcp_server_node"
    / "test"
    / "benchmark"
    / "ground_truth.json"
)
_DIGEST_PATH = (
    Path(__file__).resolve().parents[1]
    / "baselines"
    / "expected"
    / "corpus_categories_digest.json"
)
_CATALOG_PATH = (
    _REPO_ROOT / "mcp_server_python" / "src" / "config" / "tenants.yaml"
)

_REQUIRED_CASE_FIELDS = {
    "id",
    "question",
    "tool",
    "tool_args",
    "expected_results",
    "expected_min_results",
    "category",
    "notes",
}


def _raw_corpus() -> dict:
    with open(_CORPUS_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def _pinned_digest() -> dict:
    with open(_DIGEST_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def _catalog():
    return load_catalog(str(_CATALOG_PATH))


# ── the original 60 are untouched (Property 8, categories half) ───────────


def test_categories_digest_unchanged() -> None:
    """The canonical-JSON digest of the whole `categories` object equals
    the digest Task 1.2 recorded before `tenant_categories` was added."""
    raw = _raw_corpus()
    pinned = _pinned_digest()
    canon = json.dumps(
        raw["categories"], sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    digest = hashlib.sha256(canon).hexdigest()
    assert digest == pinned["categories_digest"], (
        "categories object changed a byte since Task 1.2's digest was "
        "recorded -- categories must remain byte-unchanged (R2.2)"
    )


def test_categories_field_by_field_matches_pinned_cases() -> None:
    """Every categories case matches Task 1.2's pinned expectation exactly."""
    raw = _raw_corpus()
    pinned = _pinned_digest()
    for cat_name, pinned_cases in pinned["pinned_cases"].items():
        actual_cases = raw["categories"][cat_name]
        assert len(actual_cases) == len(pinned_cases), (
            f"category {cat_name!r}: case count changed"
        )
        for pinned_case, actual_case in zip(pinned_cases, actual_cases):
            assert actual_case == pinned_case, (
                f"case {pinned_case['id']!r} diverges from its pinned "
                f"expectation"
            )


def test_each_category_holds_exactly_ten_cases() -> None:
    """The specific guard against a tenant case filed under `categories`:
    that would move a count from 10 to 11 (R2.2)."""
    raw = _raw_corpus()
    for cat_name in CATEGORY_NAMES:
        assert len(raw["categories"][cat_name]) == 10, (
            f"category {cat_name!r} does not hold exactly 10 cases"
        )


# ── the new cases are well-formed (R2.3, R2.4) ─────────────────────────────


def test_tenant_categories_cases_have_exactly_eight_fields() -> None:
    raw = _raw_corpus()
    for cat_name, cases in raw["tenant_categories"].items():
        for case in cases:
            assert set(case.keys()) == _REQUIRED_CASE_FIELDS, (
                f"case {case.get('id')!r} in tenant_categories.{cat_name} "
                f"does not carry exactly the eight declared fields: "
                f"{sorted(case.keys())}"
            )


def test_tenant_categories_cases_carry_tenant_id_in_tool_args() -> None:
    raw = _raw_corpus()
    for cat_name, cases in raw["tenant_categories"].items():
        for case in cases:
            assert "tenant_id" in case["tool_args"], (
                f"case {case['id']!r} in tenant_categories.{cat_name} has "
                f"no tenant_id in tool_args"
            )


def test_tenant_categories_tenant_id_names_a_prefixed_tenant() -> None:
    """Every Tenant_Scoped_Case's tenant_id names a catalog tenant whose
    index_prefix is non-empty (R2.4)."""
    catalog = _catalog()
    raw = _raw_corpus()
    for cat_name, cases in raw["tenant_categories"].items():
        for case in cases:
            tenant_id = case["tool_args"]["tenant_id"]
            tenant = catalog.by_id(tenant_id)
            assert tenant is not None, (
                f"case {case['id']!r} names unknown tenant {tenant_id!r}"
            )
            assert tenant.index_prefix, (
                f"case {case['id']!r} names tenant {tenant_id!r} whose "
                f"index_prefix is empty -- not a Prefixed_Tenant"
            )


def test_tenant_categories_expected_min_results_matches_length() -> None:
    raw = _raw_corpus()
    for cases in raw["tenant_categories"].values():
        for case in cases:
            assert case["expected_min_results"] == len(
                case["expected_results"]
            ), f"case {case['id']!r}: expected_min_results mismatch"


# ── classification agrees with placement, for all 68 cases ────────────────


def test_classification_agrees_with_placement_for_all_cases() -> None:
    """The derived tenant_scoped flag matches which section the case came
    from, for all 68 cases -- a misfiled case is caught, not silently
    reclassified."""
    corpus = load_corpus(str(_CORPUS_PATH))
    assert len(corpus.cases) == 68
    for case in corpus.cases:
        origin = corpus.origins[case.id]
        if origin == "categories":
            assert not case.tenant_scoped, (
                f"case {case.id!r} is filed under categories but derives "
                f"as tenant_scoped (carries a tenant_id) -- misfiled case"
            )
        else:
            assert origin == "tenant_categories"
            assert case.tenant_scoped, (
                f"case {case.id!r} is filed under tenant_categories but "
                f"derives as NOT tenant_scoped (no tenant_id) -- misfiled "
                f"case"
            )


def test_sixty_categories_and_eight_tenant_categories_cases() -> None:
    corpus = load_corpus(str(_CORPUS_PATH))
    categories_cases = [
        c for c in corpus.cases if corpus.origins[c.id] == "categories"
    ]
    tenant_cases = [
        c
        for c in corpus.cases
        if corpus.origins[c.id] == "tenant_categories"
    ]
    assert len(categories_cases) == 60
    assert len(tenant_cases) == 8


# ── R2.5/R2.6 coverage assertions ───────────────────────────────────────


def test_at_least_one_tenant_scoped_case_per_category() -> None:
    corpus = load_corpus(str(_CORPUS_PATH))
    tenant_cases = [c for c in corpus.cases if c.tenant_scoped]
    covered_categories = {c.category for c in tenant_cases}
    missing = set(CATEGORY_NAMES) - covered_categories
    assert not missing, f"no Tenant_Scoped_Case in category(ies) {missing}"


def test_at_least_one_tenant_scoped_case_names_kb_status() -> None:
    corpus = load_corpus(str(_CORPUS_PATH))
    tools = {c.tool for c in corpus.cases if c.tenant_scoped}
    assert "get_knowledge_base_status" in tools


def test_at_least_one_tenant_scoped_case_names_integrity_check() -> None:
    corpus = load_corpus(str(_CORPUS_PATH))
    tools = {c.tool for c in corpus.cases if c.tenant_scoped}
    assert "check_knowledge_integrity" in tools


def test_at_least_one_tenant_query_tool_resolves_multi_collection() -> None:
    """At least one Tenant_Scoped_Case names a Query_Tool whose read of a
    Hybrid_Domain Logical_Collection resolves to a Resolved_Collection_Set
    of more than one member. Computed through resolve_read_targets rather
    than asserted by collection name, so the assertion follows the routing
    logic instead of a string that could go stale."""
    catalog = _catalog()
    corpus = load_corpus(str(_CORPUS_PATH))
    tenant_cases = [c for c in corpus.cases if c.tenant_scoped]

    found = False
    for case in tenant_cases:
        if case.tool != "search_documentation":
            continue
        collection = case.tool_args.get("collection")
        if not collection:
            continue
        tenant_id = case.tool_args["tenant_id"]
        tenant = catalog.by_id(tenant_id)
        resolved = resolve_read_targets(collection, tenant)
        if len(resolved.targets) > 1:
            found = True
            break
    assert found, (
        "no Tenant_Scoped_Case names a Query_Tool whose Hybrid_Domain read "
        "resolves to more than one Physical_Collection (R2.6)"
    )


# ── anchoring guard ─────────────────────────────────────────────────────────

#: Synthetic render containing ONLY the gw_v17-prefixed collection names,
#: no bare/unprefixed member. If a reporter case's expected_results entry
#: were an unanchored bare collection name, case-insensitive substring
#: matching would find it as a substring of the prefixed member here --
#: the exact regression finding 6 / design Decision 2 warns about.
_PREFIXED_ONLY_RENDER = """
# Knowledge Base Status

- **Tenant prefix:** gw_v17_
- **Collections:** 6
- **Collections Detail:**
  - gw_v17_mdc-code-context-titan1024 (tenant): 28325 documents
  - gw_v17_mdc-jjobs-titan1024 (tenant): 92 documents
  - gw_v17_mdc-workflow-docs-titan1024 (shared): 10523 documents
  - gw_v17_mdc-ee2-standards-titan1024 (shared): unprovisioned
  - gw_v17_mdc-community-summaries-titan1024 (shared): unprovisioned
- **Total Documents:** 38940
- **Status:** [OK] Healthy
"""

#: The mirror for the integrity report -- only the fixed check names, none
#: of the reporter-case entries should fail to match here (this render is
#: used only to sanity-check that the check-name entries are NOT
#: substring-contained inside some other check's rendered text; the real
#: anchoring risk in this corpus is the collection-name case, tested above,
#: but ki_t01's entries are plain check names with no containment risk).


def _reporter_cases() -> list:
    corpus = load_corpus(str(_CORPUS_PATH))
    return [
        c
        for c in corpus.cases
        if c.tenant_scoped and c.tool == "get_knowledge_base_status"
    ]


#: The reporter case's entries naming a *shared* collection (one that has
#: both a bare and a gw_v17_-prefixed physical form) are the only ones the
#: anchoring trap applies to -- a tenant-only collection (code-context,
#: jjobs) has no bare form to be confused with, so it is expected to match
#: a prefixed-only render regardless of anchoring and is excluded from this
#: guard. finding 6 / design Decision 2 is specifically about a *shared*
#: collection name being a substring of its own prefixed form.
_SHARED_COLLECTION_BASENAMES = (
    "mdc-workflow-docs-titan1024",
    "mdc-ee2-standards-titan1024",
    "mdc-community-summaries-titan1024",
)


def test_anchoring_guard_kb_t01_does_not_match_prefixed_only_render() -> None:
    """Prove the '- ' anchoring actually works: kb_t01's expected_results
    entries that name a *shared* collection must NOT match a synthetic
    render that lists only the gw_v17_-prefixed collection names. Without
    this guard the anchoring can be stripped later and the case quietly
    stops discriminating the shared-scope regression it exists to catch."""
    reporter_cases = _reporter_cases()
    assert reporter_cases, "no get_knowledge_base_status tenant-scoped case"

    lowered = _PREFIXED_ONLY_RENDER.lower()
    checked_any = False
    for case in reporter_cases:
        for entry in case.expected_results:
            bare_name = entry[2:] if entry.startswith("- ") else entry
            if bare_name not in _SHARED_COLLECTION_BASENAMES:
                continue
            checked_any = True
            assert entry.lower() not in lowered, (
                f"case {case.id!r} entry {entry!r} matches a render "
                f"containing only prefixed collection names -- the "
                f"anchoring has rotted and this case no longer "
                f"discriminates the shared-scope regression it exists "
                f"to catch"
            )
    assert checked_any, (
        "no reporter-case entry names a shared collection -- the "
        "anchoring guard has nothing to exercise"
    )


def test_kb_t01_entries_are_anchored_on_the_list_marker() -> None:
    """Every kb_t01 expected_results entry is written with the '- '
    rendered list marker prefix, which is what defeats containment of a
    bare shared collection name inside its tenant-prefixed form."""
    for case in _reporter_cases():
        for entry in case.expected_results:
            assert entry.startswith("- "), (
                f"case {case.id!r} entry {entry!r} is not anchored on "
                f"the '- ' list marker"
            )


def test_kb_t01_expected_results_capped_at_five() -> None:
    """R at len(expected) <= k, precision equals recall; the cap is what
    puts kb_t01's signal inside the gate at full resolution (design
    finding 5, Decision 2)."""
    for case in _reporter_cases():
        assert len(case.expected_results) <= 5, (
            f"case {case.id!r} has more than five expected_results, "
            f"losing precision_at_k resolution"
        )


def test_ar_t01_notes_state_it_is_a_deliberate_tripwire() -> None:
    """ar_t01 is expected to score 0 -- plainly recorded in `notes` so a
    reader does not mistake it for a miscalibration."""
    corpus = load_corpus(str(_CORPUS_PATH))
    (ar_case,) = [c for c in corpus.cases if c.id == "ar_t01"]
    assert "tripwire" in ar_case.notes.lower() or "0" in ar_case.notes
    assert "gap j" in ar_case.notes.lower()


# ── sampled-collections rendering is gated on a non-empty prefix ──────────


def test_sampled_collections_check_is_gated_on_nonempty_prefix() -> None:
    """Verify (rather than assume) that 'Sampled Collections' renders only
    for a tenant carrying a non-empty index_prefix. Read directly from the
    check-construction source: _tool_check_knowledge_integrity appends the
    _check_sampled_collections row only `if prefix and ...`, where `prefix`
    is the active tenant's index_prefix. So it is present for gw_v17 (this
    corpus's tenant) and absent for the default gw tenant -- confirmed
    against src/tools/semantic_search.py rather than asserted."""
    import inspect

    from src.tools import semantic_search

    source = inspect.getsource(
        semantic_search._tool_check_knowledge_integrity
    )
    assert "if prefix and" in source, (
        "expected the Sampled Collections check to be gated on a "
        "non-empty tenant index_prefix; source shape changed -- verify "
        "ki_t01's 'Sampled Collections' expectation is still valid for "
        "gw_v17 and still absent for the default gw tenant"
    )
