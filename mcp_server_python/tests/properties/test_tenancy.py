"""Property-based tests for omd-tenants-1-foundation.

Feature: omd-tenants-1-foundation
Tests: P5 (Catalog round-trip), P6 (Workflow_root containment),
       Catalog rejection, Forward-compat warning.
"""
from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path

import pytest
import yaml
from hypothesis import assume, given, settings, HealthCheck
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Hypothesis settings profile
# ---------------------------------------------------------------------------
settings.register_profile(
    "tenancy_default",
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("tenancy_default")

# ---------------------------------------------------------------------------
# Reusable strategies
# ---------------------------------------------------------------------------

_SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_INDEX_PREFIX_RE = re.compile(r"^([a-z][a-z0-9_]*_)?$")
_LABEL_PREFIX_RE = re.compile(r"^([A-Z][A-Z0-9_]*_)?$")
_SUBDIR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@st.composite
def valid_tenant_id_strategy(draw):
    """Snake_case identifiers: 2-20 chars, [a-z][a-z0-9_]*."""
    first = draw(st.sampled_from("abcdefghijklmnopqrstuvwxyz"))
    rest = draw(st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz0123456789_",
        min_size=1, max_size=19,
    ))
    return first + rest


@st.composite
def valid_index_prefix_strategy(draw):
    """Matches ^([a-z][a-z0-9_]*_)?$ — empty or ends in '_'."""
    if draw(st.booleans()):
        return ""
    first = draw(st.sampled_from("abcdefghijklmnopqrstuvwxyz"))
    mid = draw(st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz0123456789_",
        min_size=0, max_size=10,
    ))
    return first + mid + "_"


@st.composite
def valid_label_prefix_strategy(draw):
    """Matches ^([A-Z][A-Z0-9_]*_)?$ — empty or ends in '_'."""
    if draw(st.booleans()):
        return ""
    first = draw(st.sampled_from("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
    mid = draw(st.text(
        alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_",
        min_size=0, max_size=10,
    ))
    return first + mid + "_"


@st.composite
def valid_workflow_subdir_strategy(draw):
    """Matches ^[A-Za-z0-9][A-Za-z0-9._-]*$."""
    first = draw(st.sampled_from(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    ))
    rest = draw(st.text(
        alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-",
        min_size=0, max_size=20,
    ))
    return first + rest


@st.composite
def valid_tenant_strategy(draw):
    """Compose a valid tenant dict (raw dict form)."""
    return {
        "tenant_id": draw(valid_tenant_id_strategy()),
        "repo_ref": "NOAA-EMC/global-workflow",
        "branch": draw(st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_.",
            min_size=1, max_size=20,
        )),
        "index_prefix": draw(valid_index_prefix_strategy()),
        "label_prefix": draw(valid_label_prefix_strategy()),
        "workflow_subdir": draw(valid_workflow_subdir_strategy()),
        "lifecycle": draw(st.sampled_from([
            "experimental", "staging", "production", "merged", "stale",
        ])),
        "description": "Test tenant",
        "extends": [],
    }


@st.composite
def valid_catalog_strategy(draw, min_size=1, max_size=4):
    """Compose a list of valid tenants with unique tenant_id and workflow_subdir."""
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    tenants = []
    seen_ids = set()
    seen_subdirs = set()
    for _ in range(n):
        t = draw(valid_tenant_strategy())
        # Ensure uniqueness by appending index suffix if needed
        base_id = t["tenant_id"]
        suffix = 0
        while t["tenant_id"] in seen_ids:
            suffix += 1
            t["tenant_id"] = f"{base_id}{suffix}"
        seen_ids.add(t["tenant_id"])
        base_subdir = t["workflow_subdir"]
        suffix = 0
        while t["workflow_subdir"] in seen_subdirs:
            suffix += 1
            t["workflow_subdir"] = f"{base_subdir}{suffix}"
        seen_subdirs.add(t["workflow_subdir"])
        tenants.append(t)
    return tenants


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_catalog_to_tmp(tenants_list: list[dict], tmp_path: Path) -> Path:
    """Write a catalog dict as YAML to a temp file and return the path."""
    catalog_dict = {
        "schema_version": 1,
        "defaults": {"tenant_id": tenants_list[0]["tenant_id"]},
        "tenants": tenants_list,
    }
    p = tmp_path / "tenants.yaml"
    p.write_text(yaml.dump(catalog_dict, default_flow_style=False), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Property tests (expected to FAIL until Task 2.5 lands)
# ---------------------------------------------------------------------------

class TestP5CatalogRoundTrip:
    """Property 5: Catalog round-trip.

    # Feature: omd-tenants-1-foundation, Property 5: Catalog round-trip
    # Validates: Requirements 1.1, 1.2, 9.2
    """

    @given(tenants=valid_catalog_strategy())
    def test_load_catalog_round_trips(self, tenants):
        from src.config.tenants import load_catalog

        with tempfile.TemporaryDirectory() as td:
            path = _serialize_catalog_to_tmp(tenants, Path(td))
            catalog = load_catalog(path)

        assert len(catalog.tenants) == len(tenants)
        for orig, loaded in zip(tenants, catalog.tenants):
            assert loaded.tenant_id == orig["tenant_id"]
            assert loaded.repo_ref == orig["repo_ref"]
            assert loaded.branch == orig["branch"]
            assert loaded.index_prefix == orig["index_prefix"]
            assert loaded.label_prefix == orig["label_prefix"]
            assert loaded.workflow_subdir == orig["workflow_subdir"]
            assert loaded.lifecycle == orig["lifecycle"]


class TestP6WorkflowRootContainment:
    """Property 6: Workflow_root containment.

    # Feature: omd-tenants-1-foundation, Property 6: Workflow_root containment
    # Validates: Requirements 1.11, 2.7
    """

    @given(tenant=valid_tenant_strategy())
    def test_workflow_root_is_contained(self, tenant):
        from src.config.tenants import Tenant

        t = Tenant(
            tenant_id=tenant["tenant_id"],
            repo_ref=tenant["repo_ref"],
            branch=tenant["branch"],
            index_prefix=tenant["index_prefix"],
            label_prefix=tenant["label_prefix"],
            workflow_subdir=tenant["workflow_subdir"],
            lifecycle=tenant["lifecycle"],
            description=tenant["description"],
            extends=tuple(tenant["extends"]),
        )
        assert t.workflow_root == Path("/mnt/workflow") / t.workflow_subdir
        # No path traversal
        assert ".." not in str(t.workflow_root)


class TestCatalogRejection:
    """Catalog rejection tests.

    # Feature: omd-tenants-1-foundation, Property: Catalog rejection
    # Validates: Requirements 1.7, 1.8, 1.9, 1.10, 1.11, 9.3
    """

    def test_duplicate_tenant_id(self, tmp_path):
        from src.config.tenants import load_catalog
        from src.tenancy.exceptions import DuplicateTenantError

        tenants = [
            {"tenant_id": "gw", "repo_ref": "R", "branch": "b",
             "index_prefix": "", "label_prefix": "", "workflow_subdir": "d1",
             "lifecycle": "production", "description": "", "extends": []},
            {"tenant_id": "gw", "repo_ref": "R", "branch": "b",
             "index_prefix": "", "label_prefix": "", "workflow_subdir": "d2",
             "lifecycle": "production", "description": "", "extends": []},
        ]
        path = _serialize_catalog_to_tmp(tenants, tmp_path)
        with pytest.raises(DuplicateTenantError):
            load_catalog(path)

    def test_unknown_tenant_reference(self, tmp_path):
        from src.config.tenants import load_catalog
        from src.tenancy.exceptions import UnknownTenantReferenceError

        tenants = [
            {"tenant_id": "gw", "repo_ref": "R", "branch": "b",
             "index_prefix": "", "label_prefix": "", "workflow_subdir": "dev",
             "lifecycle": "production", "description": "",
             "extends": ["nonexistent"]},
        ]
        path = _serialize_catalog_to_tmp(tenants, tmp_path)
        with pytest.raises(UnknownTenantReferenceError):
            load_catalog(path)

    def test_invalid_index_prefix(self, tmp_path):
        from src.config.tenants import load_catalog
        from src.tenancy.exceptions import InvalidPrefixError

        tenants = [
            {"tenant_id": "gw", "repo_ref": "R", "branch": "b",
             "index_prefix": "BAD!", "label_prefix": "", "workflow_subdir": "dev",
             "lifecycle": "production", "description": "", "extends": []},
        ]
        path = _serialize_catalog_to_tmp(tenants, tmp_path)
        with pytest.raises(InvalidPrefixError):
            load_catalog(path)

    def test_invalid_label_prefix(self, tmp_path):
        from src.config.tenants import load_catalog
        from src.tenancy.exceptions import InvalidPrefixError

        tenants = [
            {"tenant_id": "gw", "repo_ref": "R", "branch": "b",
             "index_prefix": "", "label_prefix": "bad_", "workflow_subdir": "dev",
             "lifecycle": "production", "description": "", "extends": []},
        ]
        path = _serialize_catalog_to_tmp(tenants, tmp_path)
        with pytest.raises(InvalidPrefixError):
            load_catalog(path)

    def test_duplicate_workflow_subdir(self, tmp_path):
        from src.config.tenants import load_catalog
        from src.tenancy.exceptions import DuplicateWorkflowSubdirError

        tenants = [
            {"tenant_id": "gw", "repo_ref": "R", "branch": "b",
             "index_prefix": "", "label_prefix": "", "workflow_subdir": "dev",
             "lifecycle": "production", "description": "", "extends": []},
            {"tenant_id": "sfs", "repo_ref": "R", "branch": "b",
             "index_prefix": "sfs_", "label_prefix": "SFS_",
             "workflow_subdir": "dev",
             "lifecycle": "production", "description": "", "extends": []},
        ]
        path = _serialize_catalog_to_tmp(tenants, tmp_path)
        with pytest.raises(DuplicateWorkflowSubdirError):
            load_catalog(path)

    @pytest.mark.parametrize("bad_subdir", [
        "../escape", "has/slash", "has\\backslash", ".hidden",
    ])
    def test_invalid_workflow_subdir(self, tmp_path, bad_subdir):
        from src.config.tenants import load_catalog
        from src.tenancy.exceptions import InvalidWorkflowSubdirError

        tenants = [
            {"tenant_id": "gw", "repo_ref": "R", "branch": "b",
             "index_prefix": "", "label_prefix": "",
             "workflow_subdir": bad_subdir,
             "lifecycle": "production", "description": "", "extends": []},
        ]
        path = _serialize_catalog_to_tmp(tenants, tmp_path)
        with pytest.raises(InvalidWorkflowSubdirError):
            load_catalog(path)

    def test_unsupported_schema_version(self, tmp_path):
        from src.config.tenants import load_catalog
        from src.tenancy.exceptions import UnsupportedSchemaVersionError

        catalog_dict = {
            "schema_version": 2,
            "defaults": {"tenant_id": "gw"},
            "tenants": [
                {"tenant_id": "gw", "repo_ref": "R", "branch": "b",
                 "index_prefix": "", "label_prefix": "",
                 "workflow_subdir": "dev", "lifecycle": "production",
                 "description": "", "extends": []},
            ],
        }
        p = tmp_path / "tenants.yaml"
        p.write_text(yaml.dump(catalog_dict), encoding="utf-8")
        with pytest.raises(UnsupportedSchemaVersionError):
            load_catalog(p)


class TestP4ResolutionDeterminism:
    """Property 4: Resolution determinism.

    # Feature: omd-tenants-1-foundation, Property 4: Resolution determinism
    # Validates: Requirements 2.1, 2.2, 2.3, 2.4, 6.1, 6.5
    """

    @given(tenants=valid_catalog_strategy(min_size=1, max_size=3))
    def test_repeated_calls_same_result(self, tenants):
        from src.config.tenants import TenantCatalog, CatalogDefaults, Tenant
        from src.tenancy.resolver import resolve_tenant

        catalog = TenantCatalog(
            schema_version=1,
            defaults=CatalogDefaults(tenant_id=tenants[0]["tenant_id"]),
            tenants=tuple(
                Tenant(
                    tenant_id=t["tenant_id"], repo_ref=t["repo_ref"],
                    branch=t["branch"], index_prefix=t["index_prefix"],
                    label_prefix=t["label_prefix"],
                    workflow_subdir=t["workflow_subdir"],
                    lifecycle=t["lifecycle"], description=t["description"],
                    extends=tuple(t["extends"]),
                )
                for t in tenants
            ),
        )
        # Pick a known tenant_id
        tid = tenants[0]["tenant_id"]
        ctx1 = resolve_tenant(request_tenant_id=tid, catalog=catalog, env={})
        ctx2 = resolve_tenant(request_tenant_id=tid, catalog=catalog, env={})
        assert ctx1.tenant_id == ctx2.tenant_id
        assert ctx1.tenant == ctx2.tenant

    @given(tenants=valid_catalog_strategy(min_size=1, max_size=3))
    def test_precedence_request_wins(self, tenants):
        """request_tenant_id takes precedence over env and defaults."""
        from src.config.tenants import TenantCatalog, CatalogDefaults, Tenant
        from src.tenancy.resolver import resolve_tenant

        catalog = TenantCatalog(
            schema_version=1,
            defaults=CatalogDefaults(tenant_id=tenants[0]["tenant_id"]),
            tenants=tuple(
                Tenant(
                    tenant_id=t["tenant_id"], repo_ref=t["repo_ref"],
                    branch=t["branch"], index_prefix=t["index_prefix"],
                    label_prefix=t["label_prefix"],
                    workflow_subdir=t["workflow_subdir"],
                    lifecycle=t["lifecycle"], description=t["description"],
                    extends=tuple(t["extends"]),
                )
                for t in tenants
            ),
        )
        tid = tenants[-1]["tenant_id"]
        env = {"MCP_DEFAULT_TENANT": tenants[0]["tenant_id"]}
        ctx = resolve_tenant(request_tenant_id=tid, catalog=catalog, env=env)
        assert ctx.tenant_id == tid

    @given(tenants=valid_catalog_strategy(min_size=2, max_size=3))
    def test_precedence_env_over_default(self, tenants):
        """MCP_DEFAULT_TENANT env wins over catalog.defaults.tenant_id."""
        from src.config.tenants import TenantCatalog, CatalogDefaults, Tenant
        from src.tenancy.resolver import resolve_tenant

        catalog = TenantCatalog(
            schema_version=1,
            defaults=CatalogDefaults(tenant_id=tenants[0]["tenant_id"]),
            tenants=tuple(
                Tenant(
                    tenant_id=t["tenant_id"], repo_ref=t["repo_ref"],
                    branch=t["branch"], index_prefix=t["index_prefix"],
                    label_prefix=t["label_prefix"],
                    workflow_subdir=t["workflow_subdir"],
                    lifecycle=t["lifecycle"], description=t["description"],
                    extends=tuple(t["extends"]),
                )
                for t in tenants
            ),
        )
        env_tid = tenants[1]["tenant_id"]
        env = {"MCP_DEFAULT_TENANT": env_tid}
        ctx = resolve_tenant(request_tenant_id=None, catalog=catalog, env=env)
        assert ctx.tenant_id == env_tid

    @given(tenants=valid_catalog_strategy(min_size=1, max_size=2))
    def test_precedence_catalog_default_over_hardcoded(self, tenants):
        """catalog.defaults.tenant_id wins over hardcoded 'gw'."""
        from src.config.tenants import TenantCatalog, CatalogDefaults, Tenant
        from src.tenancy.resolver import resolve_tenant

        default_tid = tenants[0]["tenant_id"]
        catalog = TenantCatalog(
            schema_version=1,
            defaults=CatalogDefaults(tenant_id=default_tid),
            tenants=tuple(
                Tenant(
                    tenant_id=t["tenant_id"], repo_ref=t["repo_ref"],
                    branch=t["branch"], index_prefix=t["index_prefix"],
                    label_prefix=t["label_prefix"],
                    workflow_subdir=t["workflow_subdir"],
                    lifecycle=t["lifecycle"], description=t["description"],
                    extends=tuple(t["extends"]),
                )
                for t in tenants
            ),
        )
        ctx = resolve_tenant(request_tenant_id=None, catalog=catalog, env={})
        assert ctx.tenant_id == default_tid


class TestAttributionHeaderWellFormedness:
    """Attribution header well-formedness.

    # Feature: omd-tenants-1-foundation, Property: Attribution header well-formedness
    # Validates: Requirements 5.1, 5.2
    """

    @given(
        tenant=valid_tenant_strategy(),
        body=st.text(min_size=0, max_size=200),
    )
    def test_header_present_and_stale_marker(self, tenant, body):
        from src.config.tenants import Tenant
        from src.tools._attribution import attribute

        t = Tenant(
            tenant_id=tenant["tenant_id"],
            repo_ref=tenant["repo_ref"],
            branch=tenant["branch"],
            index_prefix=tenant["index_prefix"],
            label_prefix=tenant["label_prefix"],
            workflow_subdir=tenant["workflow_subdir"],
            lifecycle=tenant["lifecycle"],
            description=tenant["description"],
            extends=tuple(tenant["extends"]),
        )
        result = attribute(body, t)
        assert result.startswith(f"*Tenant: {t.tenant_id}*")
        if t.lifecycle == "stale":
            assert "[STALE]" in result.split("\n")[0]
        else:
            assert "[STALE]" not in result.split("\n")[0]

    def test_non_string_passthrough(self):
        from src.config.tenants import Tenant
        from src.tools._attribution import attribute

        t = Tenant(
            tenant_id="gw", repo_ref="R", branch="b",
            index_prefix="", label_prefix="", workflow_subdir="dev",
            lifecycle="production", description="",
        )
        assert attribute(42, t) == 42
        assert attribute({"key": "val"}, t) == {"key": "val"}


class TestCatalogForwardCompat:
    """Catalog forward-compat warning.

    # Feature: omd-tenants-1-foundation, Property: Catalog forward-compat warning
    # Validates: Requirement 9.1
    """

    def test_unknown_fields_warn_but_succeed(self, tmp_path, caplog):
        from src.config.tenants import load_catalog

        tenants = [
            {"tenant_id": "gw", "repo_ref": "R", "branch": "b",
             "index_prefix": "", "label_prefix": "", "workflow_subdir": "dev",
             "lifecycle": "production", "description": "", "extends": [],
             "future_field": "hello", "another_unknown": 42},
        ]
        path = _serialize_catalog_to_tmp(tenants, tmp_path)
        with caplog.at_level(logging.WARNING, logger="src.config.tenants"):
            catalog = load_catalog(path)

        assert len(catalog.tenants) == 1
        assert catalog.tenants[0].tenant_id == "gw"
        # Should have logged warnings for unknown fields
        warn_messages = [r.message for r in caplog.records if "unknown field" in r.message]
        assert len(warn_messages) >= 2


# ---------------------------------------------------------------------------
# P1, P2, P3 — OpenSearch and Neptune isolation / passthrough
# ---------------------------------------------------------------------------

# Strategy: cypher fragments with :Label tokens inside and outside strings
@st.composite
def cypher_with_labels_strategy(draw):
    """Generate cypher containing :Label tokens both inside and outside strings.

    Ensures the PBT exercises the quoted-string preservation invariant.
    """
    labels = draw(st.lists(
        st.from_regex(r"[A-Z][A-Za-z0-9_]{0,10}", fullmatch=True),
        min_size=1, max_size=4,
    ))
    # Build a cypher fragment with labels in structural positions
    structural = " ".join(f"(n:{lbl})" for lbl in labels)
    # Optionally embed a label-like token inside a quoted string
    quote_char = draw(st.sampled_from(['"', "'"]))
    quoted_label = draw(st.from_regex(r"[A-Z][A-Za-z0-9_]{0,6}", fullmatch=True))
    quoted_str = f"{quote_char}:{quoted_label}{quote_char}"
    # Combine: MATCH <structural> WHERE n.name = <quoted_str> RETURN n
    cypher = f"MATCH {structural} WHERE n.name = {quoted_str} RETURN n"
    return cypher, labels, quoted_label, quote_char


@st.composite
def cypher_with_escaped_quotes_strategy(draw):
    """Generate cypher with escaped quotes inside strings to test state machine."""
    label = draw(st.from_regex(r"[A-Z][A-Za-z0-9_]{0,8}", fullmatch=True))
    inner_label = draw(st.from_regex(r"[A-Z][A-Za-z0-9_]{0,6}", fullmatch=True))
    # String with escaped quote: "some \":InnerLabel\" text"
    escaped = f'MATCH (n:{label}) WHERE n.x = "escaped \\":{inner_label}\\" end" RETURN n'
    return escaped, label, inner_label


class TestP1OpenSearchIsolation:
    """Property 1: Tenant isolation in OpenSearch.

    # Feature: omd-tenants-1-foundation, Property 1: Tenant isolation in OpenSearch
    # Validates: Requirements 3.1, 3.2
    """

    @given(
        prefix_a=st.from_regex(r"[a-z][a-z0-9_]*_", fullmatch=True).filter(lambda s: len(s) <= 12),
        prefix_b=st.from_regex(r"[a-z][a-z0-9_]*_", fullmatch=True).filter(lambda s: len(s) <= 12),
        collection=st.from_regex(r"[a-z][a-z0-9-]{1,20}", fullmatch=True),
    )
    def test_distinct_prefixes_yield_disjoint_indices(self, prefix_a, prefix_b, collection):
        from src.config.tenants import Tenant
        from src.data.opensearch_adapter import OpenSearchAdapter

        assume(prefix_a != prefix_b)

        tenant_a = Tenant(
            tenant_id="a", repo_ref="R", branch="b",
            index_prefix=prefix_a, label_prefix="",
            workflow_subdir="da", lifecycle="production",
        )
        tenant_b = Tenant(
            tenant_id="b", repo_ref="R", branch="b",
            index_prefix=prefix_b, label_prefix="",
            workflow_subdir="db", lifecycle="production",
        )
        idx_a = OpenSearchAdapter.resolve_tenant_index(collection, tenant_a)
        idx_b = OpenSearchAdapter.resolve_tenant_index(collection, tenant_b)
        assert idx_a != idx_b
        assert idx_a == f"{prefix_a}{collection}"
        assert idx_b == f"{prefix_b}{collection}"


class TestP3OpenSearchPassthrough:
    """Property 3: Empty-prefix passthrough (OpenSearch half).

    # Feature: omd-tenants-1-foundation, Property 3: Empty-prefix passthrough (OpenSearch)
    # Validates: Requirement 3.3
    """

    @given(collection=st.from_regex(r"[a-z][a-z0-9-]{1,30}", fullmatch=True))
    def test_empty_prefix_is_identity(self, collection):
        from src.config.tenants import Tenant
        from src.data.opensearch_adapter import OpenSearchAdapter

        tenant = Tenant(
            tenant_id="gw", repo_ref="R", branch="b",
            index_prefix="", label_prefix="",
            workflow_subdir="dev", lifecycle="production",
        )
        assert OpenSearchAdapter.resolve_tenant_index(collection, tenant) == collection


class TestP2NeptuneIsolation:
    """Property 2: Tenant isolation in Neptune.

    # Feature: omd-tenants-1-foundation, Property 2: Tenant isolation in Neptune
    # Validates: Requirements 4.1, 4.2
    """

    @given(
        data=cypher_with_labels_strategy(),
        prefix=st.from_regex(r"[A-Z][A-Z0-9_]*_", fullmatch=True).filter(lambda s: len(s) <= 12),
    )
    def test_rewrite_prefixes_structural_labels_only(self, data, prefix):
        from src.config.tenants import Tenant
        from src.data.neptune_adapter import NeptuneAdapter

        cypher, structural_labels, quoted_label, quote_char = data
        tenant = Tenant(
            tenant_id="t", repo_ref="R", branch="b",
            index_prefix="", label_prefix=prefix,
            workflow_subdir="d", lifecycle="production",
        )
        adapter = NeptuneAdapter.__new__(NeptuneAdapter)
        rewritten = adapter._rewrite_cypher(cypher, tenant)

        # Every structural label must be prefixed
        for lbl in structural_labels:
            assert f":{prefix}{lbl}" in rewritten

        # The quoted label must NOT be prefixed — it stays inside the string
        # Check the quoted string is preserved verbatim
        expected_quoted = f"{quote_char}:{quoted_label}{quote_char}"
        assert expected_quoted in rewritten

    @given(data=cypher_with_escaped_quotes_strategy(),
           prefix=st.from_regex(r"[A-Z][A-Z0-9_]*_", fullmatch=True).filter(lambda s: len(s) <= 12))
    def test_rewrite_handles_escaped_quotes(self, data, prefix):
        from src.config.tenants import Tenant
        from src.data.neptune_adapter import NeptuneAdapter

        cypher, structural_label, inner_label = data
        tenant = Tenant(
            tenant_id="t", repo_ref="R", branch="b",
            index_prefix="", label_prefix=prefix,
            workflow_subdir="d", lifecycle="production",
        )
        adapter = NeptuneAdapter.__new__(NeptuneAdapter)
        rewritten = adapter._rewrite_cypher(cypher, tenant)

        # Structural label is prefixed
        assert f":{prefix}{structural_label}" in rewritten
        # Inner label inside escaped quotes is NOT prefixed
        assert f'\\":{inner_label}\\"' in rewritten


class TestP3NeptunePassthrough:
    """Property 3: Empty-prefix passthrough (Neptune half).

    # Feature: omd-tenants-1-foundation, Property 3: Empty-prefix passthrough (Neptune)
    # Validates: Requirement 4.3
    """

    @given(data=cypher_with_labels_strategy())
    def test_empty_prefix_is_identity(self, data):
        from src.config.tenants import Tenant
        from src.data.neptune_adapter import NeptuneAdapter

        cypher, _, _, _ = data
        tenant = Tenant(
            tenant_id="gw", repo_ref="R", branch="b",
            index_prefix="", label_prefix="",
            workflow_subdir="dev", lifecycle="production",
        )
        adapter = NeptuneAdapter.__new__(NeptuneAdapter)
        assert adapter._rewrite_cypher(cypher, tenant) == cypher

    @given(labels=st.lists(
        st.from_regex(r"[A-Z][A-Za-z0-9_]{0,10}", fullmatch=True),
        min_size=1, max_size=5,
    ))
    def test_resolve_labels_empty_prefix_is_identity(self, labels):
        from src.config.tenants import Tenant
        from src.data.neptune_adapter import NeptuneAdapter

        tenant = Tenant(
            tenant_id="gw", repo_ref="R", branch="b",
            index_prefix="", label_prefix="",
            workflow_subdir="dev", lifecycle="production",
        )
        assert NeptuneAdapter.resolve_tenant_labels(labels, tenant) == list(labels)
