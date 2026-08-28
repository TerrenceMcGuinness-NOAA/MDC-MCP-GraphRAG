"""Property tests for the Read_Router resolution algebra.

shared-scope-query-routing Tasks 2.6 and 2.7. Covers, over the five
Logical_Collections, the tenants in ``src/config/tenants.yaml``, and the
Embedding_Profiles from :func:`profiles`:

* P1 -- prefix applies exactly when scope is tenant (Task 2.6)
* P2 -- default-tenant identity (Task 2.6)
* P5 -- cross-tenant disjointness of tenant scope (Task 2.7)
* P6 -- universal reachability of shared scope (Task 2.7)
* P3 -- backend invariance, router half (Task 2.7)
* P9 -- router purity (Task 2.7)

All six are router-only: none constructs a Vector_Adapter, so none takes
the ``adapters()`` fixture. P3's substitutability half (that patching the
router changes what both adapters address identically) is a Task 7.3
concern and is not anticipated here.

Hermetic by construction -- ``resolve_read_targets`` issues no network
request, no collection-existence probe, and no filesystem read (P9
asserts exactly that, structurally).
"""

from __future__ import annotations

import builtins
import os
import socket
from unittest.mock import patch

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from src.config.aws_config import resolve_index
from src.config.tenants import load_catalog
from src.data.collection_scope import is_hybrid_domain, scope_of
from src.data.read_router import resolve_read_targets, tenant_collection_set
from tests.properties.conftest import (
    logical_collections,
    prefixed_tenants,
    profiles,
    tenants,
)

pytestmark = pytest.mark.property


# ---------------------------------------------------------------------------
# Strategies derived from the shared generators
# ---------------------------------------------------------------------------

_COLLECTIONS = st.sampled_from(logical_collections())
_TENANTS = st.sampled_from(tenants())
_PREFIXED = st.sampled_from(prefixed_tenants())
_PROFILES = st.sampled_from(profiles())

_SHARED_COLLECTIONS = st.sampled_from(
    [c for c in logical_collections() if scope_of(c) == "shared"]
)
_TENANT_COLLECTIONS = st.sampled_from(
    [c for c in logical_collections() if scope_of(c) == "tenant"]
)

#: The Default_Tenant object, read once from the bundled catalog so P2
#: asserts against the real ``gw`` entry (empty index_prefix) rather than
#: a synthesised stand-in.
_DEFAULT_TENANT = load_catalog("src/config/tenants.yaml").by_id("gw")


# ---------------------------------------------------------------------------
# P1 -- prefix applies exactly when scope is tenant
# ---------------------------------------------------------------------------


# Feature: shared-scope-query-routing, Property 1: Prefix applies exactly
# when scope is tenant
@pytest.mark.property
@settings(max_examples=200, deadline=None)
@given(collection=_COLLECTIONS, tenant=_TENANTS, profile=_PROFILES)
def test_p1_prefix_iff_tenant_scope(collection, tenant, profile):
    """A member carries the tenant's non-empty prefix iff scope is tenant.

    "Carries T.index_prefix" is realised by the ``prefixed`` flag, which
    is meaningfully True only under a non-empty prefix: under the
    empty-prefix Default_Tenant no member is prefixed regardless of
    scope, and P2 governs that identity case. For a Hybrid_Domain under a
    non-empty prefix the result has exactly two members, unprefixed
    first (R3.1).
    """
    rcs = resolve_read_targets(collection, tenant, profile=profile)
    sc = scope_of(collection)
    hybrid = is_hybrid_domain(collection)
    has_prefix = bool(tenant.index_prefix)

    if hybrid and has_prefix:
        # R3.1: exactly two members, unprefixed then prefixed.
        assert len(rcs.targets) == 2
        assert rcs.targets[0].prefixed is False
        assert rcs.targets[1].prefixed is True
    else:
        # Every other case is a single member.
        assert len(rcs.targets) == 1
        expected_prefixed = (sc == "tenant") and has_prefix
        assert rcs.targets[0].prefixed is expected_prefixed


# ---------------------------------------------------------------------------
# P2 -- default-tenant identity
# ---------------------------------------------------------------------------


# Feature: shared-scope-query-routing, Property 2: Default-tenant identity
@pytest.mark.property
@settings(max_examples=100, deadline=None)
@given(collection=_COLLECTIONS, profile=_PROFILES)
def test_p2_default_tenant_identity(collection, profile):
    """Under the Default_Tenant the set is exactly ``{resolve_index(c, p)}``.

    Holds for the Hybrid_Domain too: the empty index_prefix collapses the
    pair of Requirement 3 criterion 1 to the single unprefixed name.
    """
    rcs = resolve_read_targets(collection, _DEFAULT_TENANT, profile=profile)
    assert rcs.physical_names == (resolve_index(collection, profile),)


# ---------------------------------------------------------------------------
# P5 -- cross-tenant disjointness of tenant scope
# ---------------------------------------------------------------------------


# Feature: shared-scope-query-routing, Property 5: Cross-tenant
# disjointness of tenant scope
@pytest.mark.property
@settings(max_examples=100, deadline=None)
@given(
    tenant_a=_PREFIXED,
    tenant_b=_PREFIXED,
    collection=_TENANT_COLLECTIONS,
    profile=_PROFILES,
)
def test_p5_cross_tenant_disjointness(tenant_a, tenant_b, collection, profile):
    """Two tenants with distinct non-empty prefixes never share a member.

    Also, no physical name in one tenant's ``tenant_collection_set``
    carries another tenant's non-empty prefix.
    """
    assume(tenant_a.index_prefix != tenant_b.index_prefix)

    set_a = resolve_read_targets(collection, tenant_a, profile=profile)
    set_b = resolve_read_targets(collection, tenant_b, profile=profile)
    assert set(set_a.physical_names).isdisjoint(set_b.physical_names)

    # No member enumerated for A carries B's non-empty prefix (R8.1-8.2).
    tcs_a = tenant_collection_set(tenant_a, profile=profile)
    for name in tcs_a.physical_names:
        assert not name.startswith(tenant_b.index_prefix)


# ---------------------------------------------------------------------------
# P6 -- universal reachability of shared scope
# ---------------------------------------------------------------------------


# Feature: shared-scope-query-routing, Property 6: Universal reachability
# of shared scope
@pytest.mark.property
@settings(max_examples=100, deadline=None)
@given(tenant=_TENANTS, collection=_SHARED_COLLECTIONS, profile=_PROFILES)
def test_p6_universal_shared_reachability(tenant, collection, profile):
    """``resolve_index(c, p)`` is always a member of a shared resolution.

    Membership does not vary with provisioning state -- the router never
    consults it -- so a fixed ``(c, T, p)`` triple always reaches the
    unprefixed shared collection.
    """
    rcs = resolve_read_targets(collection, tenant, profile=profile)
    assert resolve_index(collection, profile) in rcs.physical_names


# ---------------------------------------------------------------------------
# P3 -- backend invariance (router half)
# ---------------------------------------------------------------------------


# Feature: shared-scope-query-routing, Property 3: Backend invariance
@pytest.mark.property
@settings(max_examples=100, deadline=None)
@given(collection=_COLLECTIONS, tenant=_TENANTS, profile=_PROFILES)
def test_p3_backend_invariance_router_half(collection, tenant, profile):
    """Resolved names under ``DB_BACKEND=aws`` equal those under ``cots``.

    Established structurally: the router takes no backend argument and
    reads no backend environment variable, so toggling ``DB_BACKEND``
    cannot change the resolution. Compared as case-sensitive exact
    strings without regard to ordering.
    """
    original = os.environ.get("DB_BACKEND")
    try:
        os.environ["DB_BACKEND"] = "aws"
        aws_names = resolve_read_targets(
            collection, tenant, profile=profile
        ).physical_names
        os.environ["DB_BACKEND"] = "cots"
        cots_names = resolve_read_targets(
            collection, tenant, profile=profile
        ).physical_names
    finally:
        if original is None:
            os.environ.pop("DB_BACKEND", None)
        else:
            os.environ["DB_BACKEND"] = original

    assert set(aws_names) == set(cots_names)


# ---------------------------------------------------------------------------
# P9 -- router purity
# ---------------------------------------------------------------------------


def _raise_on_io(*_args, **_kwargs):
    """Stand-in that fails if resolution attempts socket or file I/O."""
    raise AssertionError(
        "resolve_read_targets attempted I/O during resolution (P9 violation)"
    )


# Feature: shared-scope-query-routing, Property 9: Router purity
@pytest.mark.property
@settings(max_examples=100, deadline=None, database=None)
@given(collection=_COLLECTIONS, tenant=_TENANTS, profile=_PROFILES)
def test_p9_router_purity(collection, tenant, profile):
    """Repeated invocations are equal and issue no socket or file I/O.

    Asserted structurally, not by inspection: the scope table is warmed
    once, then ``socket.socket`` and ``builtins.open`` are replaced with
    raising doubles around the resolution calls. A resolution that
    touched either would raise; equal results across repeated calls
    confirm determinism (R5.1, R3.6).
    """
    # Warm the memoized scope table so its (one-time) override read does
    # not count against the purity assertion below.
    resolve_read_targets(collection, tenant, profile=profile)

    with patch.object(socket, "socket", side_effect=_raise_on_io), \
            patch.object(builtins, "open", side_effect=_raise_on_io):
        first = resolve_read_targets(collection, tenant, profile=profile)
        second = resolve_read_targets(collection, tenant, profile=profile)

    assert first == second
    assert first.physical_names == second.physical_names
