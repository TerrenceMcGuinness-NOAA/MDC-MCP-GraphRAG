"""Property 7 -- write-read round trip.

# Feature: shared-scope-query-routing, Property 7: Write-read round trip

shared-scope-query-routing Task 12.2 (Requirements 1.6, 12.1, 12.3, 13.7).
For any manifest source with a ``collection_target`` and a ``scope``, and
any tenant for which it was ingested, the physical name
:func:`resolve_collection_name` produces is a member of
``resolve_read_targets(s.collection_target, T, profile=p)`` for the
profile that ingested it.

Why this property, and why it is not ceremony
-----------------------------------------------
This is exactly the property that would have caught the Task 6
profile-default defect: the Read_Router once pinned the literal
``"titan1024"`` while :mod:`src.data.collection_namer` defaulted to
``"mpnet768"``, so with ``MCP_EMBEDDING_PROFILE`` unset the read path
addressed ``mdc-code-context-titan1024`` for content the write path had
written to ``mdc-code-context-mpnet768``. That defect was found by hand in
review, before this test existed. To fail on that exact condition, the
profile generator drawn here includes the **no-env-var case** --
``profile=None`` with ``MCP_EMBEDDING_PROFILE`` unset -- as a first-class
member of the search space, not only the two explicit profile strings.

The claim this property establishes is the one that matters
operationally: every collection the write path created is reachable by
the read path for the tenant that owns it, so this change requires no
re-ingestion (Requirement 12.3). If P7 fails for any source, that
conclusion is false and the deploy plan changes.

Generators
----------
Manifest sources are parsed directly from
``src/config/unified_manifest.json`` (all 67 today), each carrying its own
``collection_target`` and ``scope``. Tenants and profiles are drawn from
``tests/properties/conftest.py`` so this module shares one definition
with every other property test rather than re-deriving the catalog or the
profile list.

Ingestion semantics
--------------------
``scope: "tenant"`` sources are ingested once per tenant that has
actually run the corresponding ingester -- but P7's claim does not depend
on *which* tenants have ingested a source, only on the round trip holding
for any tenant that *has*. Universally quantifying over every tenant in
the catalog is the correct generalisation: :func:`resolve_collection_name`
computes a physical name purely from ``(domain, scope, tenant, version,
profile)`` with no notion of "has this tenant ingested yet", so the round
trip holds identically whether or not a given tenant has actually run the
ingester for that source. ``scope: "shared"`` sources are ingested once,
under no tenant, and the write-side call passes ``tenant=None`` --
mirrored here by asserting against the unprefixed physical name only,
independent of which tenant is doing the reading (Requirement 2 criterion
3 / P6 territory, restated here from the write side).

Profile scope: mapped profiles only, plus the no-env-var case
----------------------------------------------------------------
P7's statement is "for the profile that ingested it" -- so it is only
meaningful for a profile something could plausibly have been ingested
under. ``nova1024`` has no entry in ``PRODUCTION_INDICES_BY_PROFILE``
("reserved for a future ingestion phase", per ``aws_config.py``), so
:func:`resolve_index` (and therefore ``resolve_read_targets``) passes the
logical identifier through UNCHANGED for it, while
``resolve_collection_name`` unconditionally builds ``mdc-{domain}-{profile}``
regardless of registration. Nothing has ever been ingested under
``nova1024``, so there is no write-side name to round-trip and the two
functions' differing treatment of an unmapped profile is not a defect --
it is Requirement 5 criterion 4's ``unmapped-profile`` passthrough,
exercised by :mod:`tests.properties.test_scope_routing`'s P1/P2/P6, not by
this property. Asserting P7 against ``nova1024`` would fail on that
divergence for a reason that has nothing to do with write-read routing,
so the profile generator here is restricted to profiles with a registered
index map (``titan1024``, ``mpnet768``) plus the ``profile=None``
no-env-var case that reproduces the Task 6 defect -- never the unmapped
``nova1024`` case.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from src.config.aws_config import get_production_indices
from src.data.collection_namer import resolve_collection_name
from src.data.read_router import resolve_read_targets
from tests.properties.conftest import profiles, tenants

pytestmark = pytest.mark.property

_MANIFEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "config"
    / "unified_manifest.json"
)

#: Logical_Collection identifier -> naming domain, matching the mapping
#: ``src/data/collection_namer.py`` and ``src/config/aws_config.py`` both
#: encode (verified directly, not inferred): ``mdc-{domain}-{profile}``
#: reproduces the registered ``PRODUCTION_INDICES_BY_PROFILE`` physical
#: name for every (collection, profile) pair in service today.
_DOMAIN_BY_TARGET: dict[str, str] = {
    "global-workflow-docs-v8-0-0": "workflow-docs",
    "code-with-context-v8-0-0": "code-context",
    "jjobs-v8-0-0": "jjobs",
    "ee2-standards-v5-0-0-enhanced": "ee2-standards",
    "community-summaries": "community-summaries",
}


def _load_manifest_sources() -> list[tuple[str, str]]:
    """Return the ``(collection_target, scope)`` pair of every source.

    Read directly with :func:`json.load` -- the same reason
    ``collection_scope.check_scope_consistency`` avoids
    ``src.manifest.loader.load_manifest``: this test's generator must
    see the real manifest content, not a degraded-boot fallback.
    """
    with open(_MANIFEST_PATH, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    pairs: list[tuple[str, str]] = []
    for entry in raw["sources"]:
        target = entry.get("collection_target")
        scope = entry.get("scope")
        if not target or scope not in ("shared", "tenant"):
            continue
        pairs.append((target, scope))
    return pairs


_MANIFEST_SOURCE_PAIRS: tuple[tuple[str, str], ...] = tuple(
    sorted(set(_load_manifest_sources()))
)

assert _MANIFEST_SOURCE_PAIRS, (
    "expected at least one (collection_target, scope) pair from the "
    "bundled unified_manifest.json"
)

_SOURCE_ST = st.sampled_from(_MANIFEST_SOURCE_PAIRS)
_TENANT_ST = st.sampled_from(tenants())

#: Profiles with a registered index map today -- the only profiles P7's
#: "for the profile that ingested it" can meaningfully range over (see
#: module docstring). Computed from the live registry rather than
#: hardcoded, so a future profile addition/removal cannot silently drift
#: this generator out of sync with ``PRODUCTION_INDICES_BY_PROFILE``.
_MAPPED_PROFILES: tuple[str, ...] = tuple(
    p for p in profiles() if get_production_indices(p)
)

assert _MAPPED_PROFILES, (
    "expected at least one profile with a registered "
    "PRODUCTION_INDICES_BY_PROFILE entry"
)

#: The no-env-var case is a first-class member of the profile search
#: space (see module docstring): ``None`` here means "call both
#: ``resolve_collection_name`` and ``resolve_read_targets`` with no
#: explicit profile argument and ``MCP_EMBEDDING_PROFILE`` unset", which
#: is exactly the condition the Task 6 defect required to reproduce. The
#: unmapped ``nova1024`` profile is deliberately excluded -- see module
#: docstring "Profile scope" section.
_PROFILE_ST = st.sampled_from((None,) + _MAPPED_PROFILES)


@pytest.fixture(autouse=True)
def _clear_profile_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure ``MCP_EMBEDDING_PROFILE`` starts unset for every example.

    Without this, whatever the outer test session happened to export
    would leak into the ``profile=None`` branch and silently mask the
    exact defect this property exists to catch.
    """
    monkeypatch.delenv("MCP_EMBEDDING_PROFILE", raising=False)


@given(
    source=_SOURCE_ST,
    tenant=_TENANT_ST,
    profile=_PROFILE_ST,
)
@settings(max_examples=150, deadline=None)
def test_p7_write_read_round_trip(source, tenant, profile) -> None:
    """The write-side physical name is always a read-side member.

    ``profile=None`` with ``MCP_EMBEDDING_PROFILE`` unset is drawn
    explicitly (not only the two named profiles) -- see module docstring
    for why that case is exactly the one that must not regress.
    """
    collection_target, scope = source
    domain = _DOMAIN_BY_TARGET[collection_target]

    write_side_tenant = tenant if scope == "tenant" else None
    physical = resolve_collection_name(
        domain=domain,
        scope=scope,
        tenant=write_side_tenant,
        profile=profile,
    )

    resolved = resolve_read_targets(
        collection_target, tenant, profile=profile
    )

    assert physical in resolved.physical_names, (
        f"write-side name {physical!r} for source "
        f"(collection_target={collection_target!r}, scope={scope!r}) "
        f"under tenant={getattr(tenant, 'tenant_id', None)!r} "
        f"profile={profile!r} is not reachable by the read path: "
        f"got {resolved.physical_names!r}"
    )


@given(source=_SOURCE_ST, profile=_PROFILE_ST)
@settings(max_examples=100, deadline=None)
def test_p7_shared_sources_reach_every_tenant(source, profile) -> None:
    """A ``shared`` source's physical name is reachable by EVERY tenant.

    Shared content is ingested once, under no tenant (``tenant=None`` on
    the write side); the round trip must hold for a reader passing any
    tenant in the catalog, restating Property 6 from the write side.
    """
    collection_target, scope = source
    # assume(), not pytest.skip(): inside @given, skip() aborts the whole
    # test on the first non-matching example, so a tenant-scoped draw would
    # end the run having asserted nothing and report SKIPPED forever.
    # assume() discards that example and lets Hypothesis draw another, so
    # the shared-scope assertion below actually executes.
    assume(scope == "shared")
    domain = _DOMAIN_BY_TARGET[collection_target]

    physical = resolve_collection_name(
        domain=domain, scope="shared", tenant=None, profile=profile
    )

    for tenant in tenants():
        resolved = resolve_read_targets(
            collection_target, tenant, profile=profile
        )
        assert physical in resolved.physical_names, (
            f"shared write-side name {physical!r} for "
            f"{collection_target!r} is unreachable under tenant "
            f"{tenant.tenant_id!r} (profile={profile!r}): "
            f"got {resolved.physical_names!r}"
        )
