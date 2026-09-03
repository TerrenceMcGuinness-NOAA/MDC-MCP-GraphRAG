"""Unit tests for the Read_Router (shared-scope-query-routing Task 2).

Covers the routing data models (Task 2.1), :func:`resolve_read_targets`
(Task 2.2, including the R13.1 matrix, R13.2, and the R1.5 / R2.8 / R7.5
paths), and :func:`tenant_collection_set` (Task 2.3).

Hermetic: no network, no backend, no live config. The Scope_Authority
table and the ``PRODUCTION_INDICES_BY_PROFILE`` map are both in-process
literals; the tenant catalog is read from the bundled ``tenants.yaml``.
"""

from __future__ import annotations

import logging

import pytest

from src.config.aws_config import resolve_index
from src.config.tenants import load_catalog
from src.data import read_router as rr
from src.data.collection_namer import (
    DEFAULT_EMBEDDING_PROFILE,
    active_embedding_profile,
)
from src.data.collection_scope import logical_collections
from src.data.read_router import (
    CLASSIFICATION_ROUTING_MISCONFIGURATION,
    CLASSIFICATION_TENANT_FALLBACK,
    CLASSIFICATION_UNMAPPED_PROFILE,
    CollectionCondition,
    ResolvedCollectionSet,
    ResolvedTarget,
    RoutingDiagnostic,
    resolve_read_targets,
    tenant_collection_set,
)

_TENANTS_YAML = "src/config/tenants.yaml"

# The four non-hybrid Logical_Collections and their scope, for the R13.1
# matrix. The Hybrid_Domain (docs) is exercised separately in R13.2.
_SHARED_NON_HYBRID = ("ee2-standards-v5-0-0-enhanced", "community-summaries")
_TENANT_COLLECTIONS = ("code-with-context-v8-0-0", "jjobs-v8-0-0")
_HYBRID_COLLECTION = "global-workflow-docs-v8-0-0"


@pytest.fixture(scope="module")
def catalog():
    """The bundled tenant catalog (read once for the module)."""
    return load_catalog(_TENANTS_YAML)


@pytest.fixture(scope="module")
def gw(catalog):
    """The Default_Tenant ``gw`` (empty index_prefix)."""
    tenant = catalog.by_id("gw")
    assert tenant is not None and tenant.index_prefix == ""
    return tenant


@pytest.fixture(scope="module")
def gw_v17(catalog):
    """A prefixed tenant, ``gw_v17`` (index_prefix ``gw_v17_``)."""
    tenant = catalog.by_id("gw_v17")
    assert tenant is not None and tenant.index_prefix == "gw_v17_"
    return tenant


# ── Task 2.1: data models ───────────────────────────────────────────────


class TestModels:
    """The frozen routing data models and RoutingDiagnostic.render()."""

    def test_resolved_collection_set_rejects_duplicate_physical(self):
        dup = ResolvedTarget(physical="x", scope="shared", prefixed=False)
        dup2 = ResolvedTarget(physical="x", scope="shared", prefixed=True)
        with pytest.raises(ValueError):
            ResolvedCollectionSet(
                logical="c",
                scope="shared",
                hybrid=False,
                tenant_id="gw",
                index_prefix="",
                profile="titan1024",
                targets=(dup, dup2),
            )

    def test_physical_names_property_preserves_order(self):
        first = ResolvedTarget(physical="a", scope="shared", prefixed=False)
        second = ResolvedTarget(physical="b", scope="shared", prefixed=True)
        rcs = ResolvedCollectionSet(
            logical="c",
            scope="shared",
            hybrid=True,
            tenant_id="gw_v17",
            index_prefix="gw_v17_",
            profile="titan1024",
            targets=(first, second),
        )
        assert rcs.physical_names == ("a", "b")

    def test_collection_condition_values(self):
        assert CollectionCondition.UNPROVISIONED == "unprovisioned"
        assert CollectionCondition.PROVISIONED_EMPTY == "provisioned-empty"
        assert (
            CollectionCondition.PROVISIONED_POPULATED
            == "provisioned-populated"
        )

    def test_render_is_ascii_and_bounded_for_non_ascii_fields(self):
        # Non-ASCII in every free-text field plus a 10 KB collection name.
        big_name = "\u00e9" + ("z" * 10_000)
        diag = RoutingDiagnostic(
            tenant_id="t\u00e9nant",
            logical="log\u00edcal",
            profile="prof\u00edle",
            members=((big_name, "shared", False),),
            transport="builtin",
            classification="unmapped-profile",
        )
        rendered = diag.render()
        # ASCII only.
        rendered.encode("ascii")  # raises if any non-ASCII leaked
        # Bounded at 1000 chars with the truncation marker.
        assert len(rendered) <= 1000
        assert rendered.endswith("...[truncated]")
        # One line.
        assert "\n" not in rendered and "\r" not in rendered

    def test_render_short_line_is_not_truncated(self):
        diag = RoutingDiagnostic(
            tenant_id="gw_v17",
            logical="ee2-standards-v5-0-0-enhanced",
            profile="titan1024",
            members=(("mdc-ee2-standards-titan1024", "shared", False),),
            transport="builtin",
        )
        rendered = diag.render()
        assert not rendered.endswith("...[truncated]")
        assert "tenant=gw_v17" in rendered
        assert "mdc-ee2-standards-titan1024(shared,unprefixed)" in rendered

    def test_render_carries_no_query_or_document_field(self):
        # The record has no query/content field; a value that looks like
        # query text can only appear if a caller smuggled it into a
        # whitelisted field, which the field set structurally prevents.
        diag = RoutingDiagnostic(
            tenant_id="gw",
            logical="community-summaries",
            profile="titan1024",
            members=(("mdc-community-summaries-titan1024", "shared", False),),
            transport="builtin",
        )
        rendered = diag.render()
        assert "SELECT" not in rendered  # nothing query-like leaks
        # Only the whitelisted tokens are present.
        for token in ("tenant=", "logical=", "profile=", "transport=",
                      "members="):
            assert token in rendered


# ── Task 2.2: resolve_read_targets ──────────────────────────────────────


class TestResolveReadTargetsMatrix:
    """The R13.1 matrix plus the R13.2 Hybrid_Domain case."""

    @pytest.mark.parametrize("profile", ["titan1024", "mpnet768"])
    @pytest.mark.parametrize("collection", _SHARED_NON_HYBRID)
    def test_shared_non_hybrid_is_single_unprefixed_every_tenant(
        self, collection, profile, gw, gw_v17
    ):
        expected = (resolve_index(collection, profile),)
        for tenant in (gw, gw_v17):
            rcs = resolve_read_targets(collection, tenant, profile=profile)
            assert rcs.physical_names == expected
            assert rcs.scope == "shared"
            assert rcs.targets[0].prefixed is False

    @pytest.mark.parametrize("profile", ["titan1024", "mpnet768"])
    @pytest.mark.parametrize("collection", _TENANT_COLLECTIONS)
    def test_tenant_scope_prefix_depends_on_tenant(
        self, collection, profile, gw, gw_v17
    ):
        base = resolve_index(collection, profile)
        # Default tenant: single unprefixed member == resolve_index.
        gw_set = resolve_read_targets(collection, gw, profile=profile)
        assert gw_set.physical_names == (base,)
        assert gw_set.targets[0].prefixed is False
        # Prefixed tenant: single prefixed member only.
        v17_set = resolve_read_targets(collection, gw_v17, profile=profile)
        assert v17_set.physical_names == (f"gw_v17_{base}",)
        assert v17_set.targets[0].prefixed is True
        assert v17_set.scope == "tenant"

    @pytest.mark.parametrize("profile", ["titan1024", "mpnet768"])
    def test_hybrid_domain_two_members_under_prefixed_tenant(
        self, profile, gw_v17
    ):
        base = resolve_index(_HYBRID_COLLECTION, profile)
        rcs = resolve_read_targets(
            _HYBRID_COLLECTION, gw_v17, profile=profile
        )
        # Exactly two members, unprefixed first, prefixed second (R3.1).
        assert rcs.physical_names == (base, f"gw_v17_{base}")
        assert rcs.hybrid is True
        assert rcs.targets[0].prefixed is False
        assert rcs.targets[1].prefixed is True
        assert [t.prefixed for t in rcs.targets].count(True) == 1
        assert [t.prefixed for t in rcs.targets].count(False) == 1

    @pytest.mark.parametrize("profile", ["titan1024", "mpnet768"])
    def test_hybrid_domain_collapses_under_default_tenant(self, profile, gw):
        base = resolve_index(_HYBRID_COLLECTION, profile)
        rcs = resolve_read_targets(_HYBRID_COLLECTION, gw, profile=profile)
        # Empty prefix collapses the pair to one member (R6.7, P2).
        assert rcs.physical_names == (base,)


class TestResolveReadTargetsDefaultAndPurity:
    """Default-tenant identity and the no-argument default path."""

    def test_none_tenant_is_unprefixed_default(self):
        # tenant=None resolves to the unprefixed default, byte-equal to
        # the gw resolution.
        for collection in _SHARED_NON_HYBRID + _TENANT_COLLECTIONS + (
            _HYBRID_COLLECTION,
        ):
            rcs = resolve_read_targets(collection, None, profile="titan1024")
            assert rcs.physical_names == (
                resolve_index(collection, "titan1024"),
            )
            assert rcs.index_prefix == ""

    def test_profile_default_matches_write_side_default(self, monkeypatch):
        # No profile argument and no env var: the router's default must
        # agree with the WRITE side's default, not with resolve_index's.
        #
        # resolve_index defaults to titan1024 because it is an OpenSearch
        # name translator; inheriting that made the router AWS-biased and
        # broke P7 (write-read round trip) on COTS, where the writer
        # defaults to mpnet768. Both must name the same collection or a
        # read addresses content the write path never wrote there.
        #
        # P2 is unaffected either way: it is stated over an explicit
        # profile p, and the router always passes its resolved profile to
        # resolve_index explicitly. So the assertion below compares
        # against resolve_index(c, resolved) rather than resolve_index(c).
        monkeypatch.delenv("MCP_EMBEDDING_PROFILE", raising=False)
        rcs = resolve_read_targets("ee2-standards-v5-0-0-enhanced", None)
        assert rcs.profile == active_embedding_profile()
        assert rcs.profile == DEFAULT_EMBEDDING_PROFILE
        assert rcs.physical_names == (
            resolve_index("ee2-standards-v5-0-0-enhanced", rcs.profile),
        )

    def test_profile_default_agrees_with_writer_on_every_domain(
        self, monkeypatch
    ):
        # The round-trip guard generalised: with no env var set, every
        # logical collection resolves under the writer's default profile.
        monkeypatch.delenv("MCP_EMBEDDING_PROFILE", raising=False)
        for logical in logical_collections():
            rcs = resolve_read_targets(logical, None)
            assert rcs.profile == DEFAULT_EMBEDDING_PROFILE, logical

    def test_env_profile_is_honoured(self, monkeypatch):
        monkeypatch.setenv("MCP_EMBEDDING_PROFILE", "mpnet768")
        rcs = resolve_read_targets("code-with-context-v8-0-0", None)
        assert rcs.profile == "mpnet768"
        assert rcs.physical_names == (
            resolve_index("code-with-context-v8-0-0", "mpnet768"),
        )

    def test_repeated_calls_are_equal(self, gw_v17):
        a = resolve_read_targets(
            _HYBRID_COLLECTION, gw_v17, profile="titan1024"
        )
        b = resolve_read_targets(
            _HYBRID_COLLECTION, gw_v17, profile="titan1024"
        )
        assert a == b


class TestResolveReadTargetsFallback:
    """R1.5 unknown-identifier fallback."""

    def test_unknown_identifier_takes_tenant_fallback(self, gw_v17, caplog):
        with caplog.at_level(logging.INFO, logger="src.data.read_router"):
            rcs = resolve_read_targets(
                "not-a-logical-collection", gw_v17, profile="titan1024"
            )
        # Treated as tenant: one prefixed member of the passthrough name.
        assert rcs.fallback_applied is True
        assert rcs.scope == "tenant"
        assert rcs.physical_names == ("gw_v17_not-a-logical-collection",)
        # Diagnostic names the tenant-fallback classification.
        assert any(
            CLASSIFICATION_TENANT_FALLBACK in rec.getMessage()
            for rec in caplog.records
        )

    def test_unknown_identifier_default_tenant_unprefixed(self, gw):
        rcs = resolve_read_targets("mystery-name", gw, profile="titan1024")
        assert rcs.fallback_applied is True
        assert rcs.physical_names == ("mystery-name",)

    def test_fallback_never_raises_and_never_empty(self, gw_v17):
        rcs = resolve_read_targets("", gw_v17, profile="titan1024")
        assert rcs.fallback_applied is True
        assert len(rcs.targets) == 1


class TestResolveReadTargetsUnmappedProfile:
    """R2.8 unmapped profile (nova1024 -> resolve_index passthrough)."""

    def test_unmapped_profile_keeps_scope_and_cardinality(
        self, gw_v17, caplog
    ):
        with caplog.at_level(logging.INFO, logger="src.data.read_router"):
            rcs = resolve_read_targets(
                "ee2-standards-v5-0-0-enhanced", gw_v17, profile="nova1024"
            )
        # Passthrough identifier, same scope decision, cardinality 1
        # (shared non-hybrid), classification unmapped-profile.
        assert rcs.unmapped_profile is True
        assert rcs.scope == "shared"
        assert rcs.physical_names == ("ee2-standards-v5-0-0-enhanced",)
        assert any(
            CLASSIFICATION_UNMAPPED_PROFILE in rec.getMessage()
            for rec in caplog.records
        )

    def test_unmapped_profile_hybrid_keeps_two_members(self, gw_v17):
        rcs = resolve_read_targets(
            _HYBRID_COLLECTION, gw_v17, profile="nova1024"
        )
        # Cardinality unchanged from the mapped case: still two members.
        assert rcs.unmapped_profile is True
        assert rcs.physical_names == (
            _HYBRID_COLLECTION,
            f"gw_v17_{_HYBRID_COLLECTION}",
        )

    def test_mapped_profile_is_not_flagged_unmapped(self, gw_v17):
        rcs = resolve_read_targets(
            "code-with-context-v8-0-0", gw_v17, profile="titan1024"
        )
        assert rcs.unmapped_profile is False


class TestResolveReadTargetsMisconfiguration:
    """R7.5 shared set with no unprefixed member (post-condition)."""

    def test_shared_without_unprefixed_member_is_flagged(
        self, gw_v17, caplog, monkeypatch
    ):
        # Normal construction always adds the unprefixed member for a
        # shared collection, so the R7.5 post-condition is only reachable
        # by injecting a malformed target set. Substitute the builder.
        def _all_prefixed(scope, hybrid, physical_base, index_prefix):
            return (
                ResolvedTarget(
                    physical=f"{index_prefix}{physical_base}",
                    scope="shared",
                    prefixed=True,
                ),
            )

        monkeypatch.setattr(rr, "_build_targets", _all_prefixed)
        with caplog.at_level(logging.INFO, logger="src.data.read_router"):
            rcs = resolve_read_targets(
                "ee2-standards-v5-0-0-enhanced", gw_v17, profile="titan1024"
            )
        # The read still proceeds over the remaining members (R7.5).
        assert rcs.physical_names == (
            "gw_v17_mdc-ee2-standards-titan1024",
        )
        assert any(
            CLASSIFICATION_ROUTING_MISCONFIGURATION in rec.getMessage()
            for rec in caplog.records
        )


class TestDiagnosticEmission:
    """Exactly one diagnostic per resolution, on the log channel only."""

    def test_exactly_one_diagnostic_per_resolution(self, gw_v17, caplog):
        with caplog.at_level(logging.INFO, logger="src.data.read_router"):
            resolve_read_targets(
                "community-summaries", gw_v17, profile="titan1024"
            )
        routing_lines = [
            r for r in caplog.records if r.getMessage().startswith("[routing]")
        ]
        assert len(routing_lines) == 1


# ── Task 2.3: tenant_collection_set ─────────────────────────────────────


class TestTenantCollectionSet:
    """Union of resolve_read_targets over the five Logical_Collections."""

    def test_prefixed_tenant_holds_six_members(self, gw_v17):
        tcs = tenant_collection_set(gw_v17, profile="titan1024")
        # Five logical collections; the Hybrid_Domain contributes two.
        assert len(tcs.targets) == 6
        assert len(tcs.by_logical) == 5

    def test_default_tenant_holds_five_members(self, gw):
        tcs = tenant_collection_set(gw, profile="titan1024")
        assert len(tcs.targets) == 5
        assert len(tcs.by_logical) == 5

    def test_by_logical_maps_each_collection_to_its_physical_names(
        self, gw_v17
    ):
        tcs = tenant_collection_set(gw_v17, profile="titan1024")
        docs = tcs.by_logical[_HYBRID_COLLECTION]
        assert docs == (
            "mdc-workflow-docs-titan1024",
            "gw_v17_mdc-workflow-docs-titan1024",
        )
        assert tcs.by_logical["code-with-context-v8-0-0"] == (
            "gw_v17_mdc-code-context-titan1024",
        )
        assert tcs.by_logical["ee2-standards-v5-0-0-enhanced"] == (
            "mdc-ee2-standards-titan1024",
        )

    def test_enumeration_order_is_stable(self, gw_v17):
        first = tenant_collection_set(gw_v17, profile="titan1024")
        second = tenant_collection_set(gw_v17, profile="titan1024")
        assert first.physical_names == second.physical_names

    def test_members_are_distinct_by_physical_name(self, gw_v17):
        tcs = tenant_collection_set(gw_v17, profile="titan1024")
        names = tcs.physical_names
        assert len(names) == len(set(names))

    def test_none_tenant_matches_default_tenant(self, gw):
        none_set = tenant_collection_set(None, profile="titan1024")
        gw_set = tenant_collection_set(gw, profile="titan1024")
        assert none_set.physical_names == gw_set.physical_names
