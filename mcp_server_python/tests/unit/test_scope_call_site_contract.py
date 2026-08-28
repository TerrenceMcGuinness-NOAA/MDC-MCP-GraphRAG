"""Call-site contract for shared-scope-reachable adapter reads.

shared-scope-query-routing Task 7.7 (Requirements 2.5, 2.9). Every
shared-scope-reachable ``vector_db.query`` / ``multi_collection_query``
call site passes a Logical_Collection identifier that is a key of the
active profile's entry in ``PRODUCTION_INDICES_BY_PROFILE`` -- never a
physical index name. The identifiers are module-level constants, so this
asserts on the constants each site passes:

* ``semantic_search`` -- ``DEFAULT_SEARCH_COLLECTIONS`` (the
  ``multi_collection_query`` fan-out) and ``CONTEXT_TYPE_COLLECTIONS``.
  The explicit-collection ``query()`` branch forwards the caller's
  ``collection`` argument, whose help text enumerates the same logical
  keys.
* ``ee2_compliance`` -- ``EE2_COLLECTION`` (the three sites).
* ``graph_rag`` -- ``CODE_COLLECTION`` and ``COMMUNITY_COLLECTION``
  (``search_architecture``; ``_render_community_section`` feeding
  ``get_code_context``; ``_fetch_community_context`` feeding
  ``get_change_impact`` -- the requirements attribute both community
  sites to ``get_code_context``; the second actually feeds
  ``get_change_impact`` and both realign identically).
* ``operational`` -- ``WORKFLOW_DOCS_COLLECTION``, ``JJOBS_COLLECTION``,
  ``CODE_COLLECTION``.

It also asserts (at the routing level, R2.9) that the tenant-scoped tools
``find_similar_code`` (CODE_COLLECTION), ``get_job_details`` /
``list_job_scripts`` (JJOBS_COLLECTION) address only the prefixed member
under a prefixed tenant, so every hit they can return is prefixed-member
content -- correct today, and this guards it stays correct.
"""
from __future__ import annotations

import pytest

from src.config.aws_config import PRODUCTION_INDICES_BY_PROFILE
from src.config.tenants import load_catalog
from src.data.read_router import resolve_read_targets
from src.tools import ee2_compliance, graph_rag, operational, semantic_search

pytestmark = pytest.mark.unit

# The five Logical_Collection identifiers, per profile. Both mapped
# profiles register the same keys; either is a valid reference.
_LOGICAL_KEYS = set(PRODUCTION_INDICES_BY_PROFILE["titan1024"].keys())


def _assert_logical(identifier: str) -> None:
    assert identifier in _LOGICAL_KEYS, (
        f"{identifier!r} passed to a shared-scope-reachable adapter call "
        f"is not a Logical_Collection key of PRODUCTION_INDICES_BY_PROFILE "
        f"({sorted(_LOGICAL_KEYS)})"
    )


def test_semantic_search_call_sites_pass_logical_keys():
    for identifier in semantic_search.DEFAULT_SEARCH_COLLECTIONS:
        _assert_logical(identifier)
    for group in semantic_search.CONTEXT_TYPE_COLLECTIONS.values():
        for identifier in group:
            _assert_logical(identifier)


def test_ee2_call_sites_pass_logical_keys():
    _assert_logical(ee2_compliance.EE2_COLLECTION)


def test_graph_rag_call_sites_pass_logical_keys():
    _assert_logical(graph_rag.CODE_COLLECTION)
    _assert_logical(graph_rag.COMMUNITY_COLLECTION)


def test_operational_call_sites_pass_logical_keys():
    _assert_logical(operational.WORKFLOW_DOCS_COLLECTION)
    _assert_logical(operational.JJOBS_COLLECTION)
    _assert_logical(operational.CODE_COLLECTION)


def test_no_call_site_passes_a_physical_name():
    """A physical name carries the ``mdc-`` prefix; a logical key never
    does. None of the identifiers above may look physical."""
    identifiers = (
        set(semantic_search.DEFAULT_SEARCH_COLLECTIONS)
        | {c for g in semantic_search.CONTEXT_TYPE_COLLECTIONS.values()
           for c in g}
        | {ee2_compliance.EE2_COLLECTION}
        | {graph_rag.CODE_COLLECTION, graph_rag.COMMUNITY_COLLECTION}
        | {operational.WORKFLOW_DOCS_COLLECTION,
           operational.JJOBS_COLLECTION, operational.CODE_COLLECTION}
    )
    for identifier in identifiers:
        assert not identifier.startswith("mdc-"), (
            f"{identifier!r} looks like a physical index name"
        )
        assert "_mdc-" not in identifier


@pytest.mark.parametrize("profile", ["titan1024", "mpnet768"])
def test_tenant_scoped_tools_address_only_prefixed_members(profile):
    """R2.9: the collections that ``find_similar_code``,
    ``get_job_details``, and ``list_job_scripts`` query resolve, under a
    prefixed tenant, to exactly one prefixed member -- so every hit they
    can return is prefixed-member content."""
    catalog = load_catalog("src/config/tenants.yaml")
    v17 = catalog.by_id("gw_v17")
    for logical in (graph_rag.CODE_COLLECTION, operational.JJOBS_COLLECTION):
        resolved = resolve_read_targets(logical, v17, profile=profile)
        assert len(resolved.targets) == 1
        target = resolved.targets[0]
        assert target.prefixed is True
        assert target.physical.startswith("gw_v17_")
        assert target.scope == "tenant"
