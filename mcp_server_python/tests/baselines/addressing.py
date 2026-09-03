"""Addressed-set and hit-provenance checks for Query_Tool output.

Feature: default-tenant-freeze-retirement (SDD Phase 80), Task 8.1.

The Requirement 11 criterion 2 structural half. Unlike the
Structural_Equivalence relation in ``tests/baselines/structural.py``, this
check cannot be a text
parser over rendered output. Two independent facts make physical addressing
unrecoverable from a Query_Tool's rendered response:

1. **The rendered collection field carries the logical name, not the
   physical one.** ``semantic_search`` renders ``| **Collection:**
   {name}`` from the logical identifier. Phase 79 deliberately added
   ``physical_collection`` as a *new* result key rather than repurposing
   that field, precisely so the rendered bytes would not move. So the
   physical collection a read addressed is not in the text.
2. **The capture harness cannot see it either.** ``_StubVectorDB``
   (``tests/baselines/capture.py``) replaces the adapter wholesale, and it
   receives the *logical* name -- the real adapter is what calls the
   Read_Router internally. So the recorded scenarios have no view of
   physical addressing.

This module therefore works against the Read_Router directly
(:func:`addressed_set`) and against both real adapters through a stubbed
client (:func:`check_hit_provenance`'s caller, via the ``adapters()``
fixture in ``tests/properties/conftest.py``), never against rendered text.

Nothing under ``src/`` imports this module (Requirement 15 criteria 1-3):
it has exactly one caller, a test, matching the placement rationale already
recorded for ``structural.py``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from src.data.read_router import resolve_read_targets
from src.tools import ee2_compliance, graph_rag, operational, semantic_search

if TYPE_CHECKING:  # pragma: no cover - typing only
    from src.config.tenants import Tenant


#: Each Query_Tool's Logical_Collection fan-out, read from the modules'
#: own constants rather than restated as literal strings here. A copy
#: would silently drift from the code it claims to describe -- exactly the
#: failure mode this check exists to prevent. Verified against each tool's
#: ``_tool_*`` internal:
#:
#: * ``search_documentation`` (``collection=None`` path, the scenario this
#:   check exercises): ``multi_collection_query`` over the full
#:   ``DEFAULT_SEARCH_COLLECTIONS`` fan-out.
#: * ``search_ee2_standards``: a single ``query`` against ``EE2_COLLECTION``.
#: * ``search_architecture``: a single ``query`` against
#:   ``COMMUNITY_COLLECTION`` (not ``CODE_COLLECTION`` -- that constant is
#:   read by ``get_code_context`` and ``get_change_impact``, not by this
#:   tool).
#: * ``get_operational_guidance``: a single ``query`` against
#:   ``WORKFLOW_DOCS_COLLECTION``.
TOOL_LOGICAL_COLLECTIONS: Mapping[str, tuple[str, ...]] = {
    "search_documentation": tuple(semantic_search.DEFAULT_SEARCH_COLLECTIONS),
    "search_ee2_standards": (ee2_compliance.EE2_COLLECTION,),
    "search_architecture": (graph_rag.COMMUNITY_COLLECTION,),
    "get_operational_guidance": (operational.WORKFLOW_DOCS_COLLECTION,),
}


def addressed_set(
    tool_name: str,
    *,
    tenant: "Tenant | None" = None,
    profile: str | None = None,
) -> frozenset[str]:
    """Return the Physical_Collections ``tool_name`` addresses for ``tenant``.

    The union of :func:`resolve_read_targets` over every Logical_Collection
    ``tool_name`` reads, per :data:`TOOL_LOGICAL_COLLECTIONS`. Pure: no
    network request, no filesystem read, and no collection-existence probe
    -- it is exactly as pure as ``resolve_read_targets`` itself (Phase 79
    R5.1), since this function does nothing but call it and union the
    results.

    Parameters
    ----------
    tool_name : str
        A key of :data:`TOOL_LOGICAL_COLLECTIONS`.
    tenant : Tenant | None
        The active Tenant, or ``None`` for the unprefixed Default_Tenant
        (``gw``). Passed straight through to ``resolve_read_targets``.
    profile : str | None
        Embedding_Profile short name. Passed straight through; ``None``
        defers to ``resolve_read_targets``'s own default resolution.

    Returns
    -------
    frozenset[str]
        The Physical_Collection names ``tool_name`` addresses. A change
        that drops one member of a multi-member Resolved_Collection_Set
        changes this set and names the dropped member -- the check a
        quality score cannot make, because the surviving member can still
        answer every corpus query and leave ``coverage`` untouched.

    Raises
    ------
    KeyError
        When ``tool_name`` is not a key of :data:`TOOL_LOGICAL_COLLECTIONS`.
    """
    logical_collections = TOOL_LOGICAL_COLLECTIONS[tool_name]
    members: set[str] = set()
    for collection in logical_collections:
        resolved = resolve_read_targets(collection, tenant, profile=profile)
        members.update(resolved.physical_names)
    return frozenset(members)


def check_hit_provenance(
    hits: Iterable[Mapping[str, Any]], addressed: frozenset[str]
) -> list[str]:
    """Return findings where a hit's provenance is missing or stray.

    Named ``check_`` and not ``assert_`` on purpose. It **returns** findings
    rather than raising, matching :func:`tests.baselines.structural.
    compare_structural`'s convention, and a name beginning ``assert_`` invites
    a caller to write it as a bare statement and discard the result -- a
    silent no-op that looks like an enforced check. That mistake was made
    while reviewing this module, which is why the name changed.

    Every hit a read returns must carry a non-empty ``physical_collection``
    whose value is a member of ``addressed``. This is the provenance half of
    Requirement 11 criterion 2, kept as a separate function from
    :func:`addressed_set` because the two fail for different reasons and a
    reviewer needs to know which: "you dropped a collection" (the set
    changed) is a different investigation from "a hit lost its provenance"
    (the set is right but the stamping broke).

    Parameters
    ----------
    hits : Iterable[Mapping[str, Any]]
        Rows returned by ``ChromaDBAdapter.query`` or
        ``OpenSearchAdapter.query`` (or ``multi_collection_query``). Both
        adapters stamp ``row["physical_collection"]`` in their single-member
        identity path and again in their merge path.
    addressed : frozenset[str]
        The expected addressed set, typically from :func:`addressed_set`.

    Returns
    -------
    list[str]
        One finding per divergent hit; empty means every hit carries valid
        provenance. A hit is identified by its 0-based position in ``hits``
        and, when present, its ``id``.
    """
    findings: list[str] = []
    for index, hit in enumerate(hits):
        physical = hit.get("physical_collection")
        hit_id = hit.get("id", "<no id>")
        if not physical:
            findings.append(
                f"addressing: hit {index} (id={hit_id!r}) carries no "
                f"physical_collection"
            )
            continue
        if physical not in addressed:
            findings.append(
                f"addressing: hit {index} (id={hit_id!r}) carries "
                f"physical_collection {physical!r}, which is not a member "
                f"of the addressed set {sorted(addressed)}"
            )
    return findings
