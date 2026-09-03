"""Property test P4 -- Form-factor and transport invariance (Task 3.2).

shared-scope-query-routing Requirements: 5.2, 5.3, 5.7, 13.7.

Full statement (design.md, "Correctness Properties"): for any
``(Logical_Collection, Tenant, Embedding_Profile)`` triple and any pair
of Configuration_Transports carrying byte-identical content -- inline
environment content versus a mounted file -- ``resolve_read_targets``
returns equal sets. Likewise equal across the simulated ``agentcore``
and ``container`` Form_Factors.

``resolve_read_targets`` is owned by Task 2 (``src/data/read_router.py``)
and does not exist yet at this step. Per the Task 3 instructions, this
module tests the transport layer alone: byte-identical tenant catalog
content, supplied through either Configuration_Transport, under either
simulated Form_Factor, produces an equal :class:`TenantCatalog` and
therefore an equal ``index_prefix`` for every tenant. The router-level
assertion -- that an equal ``index_prefix`` implies an equal
Resolved_Collection_Set -- is left as a TODO below and must not be
anticipated by importing or stubbing ``read_router`` here.
"""

from __future__ import annotations

import os
import shutil
import tempfile

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.config import tenants as tn

pytestmark = pytest.mark.property


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------

#: Simulated Form_Factor values (Requirement 5.2). The transport-precedence
#: rule under test applies identically to both -- this generator exists so
#: the property statement is over "any Form_Factor pair", not just the one
#: process happens to be running under.
_FORM_FACTORS = ("agentcore", "container")

#: A small, deliberately varied set of NON-default tenant_ids so the
#: generated catalog's second tenant entry never collides with the
#: hardcoded ``gw`` default tenant every generated catalog also
#: declares. Kept simple: this property is about transport equivalence,
#: not about catalog validation edge cases (those are covered by
#: test_tenants.py and the sibling test_tenant_catalog_transport.py).
_TENANT_ID_ALPHABET = st.sampled_from(
    ["gw_v17", "gw_sfs", "gw_jedi_gfs", "gw_gefs_v12"]
)


@st.composite
def _catalog_yaml_text(draw: st.DrawFn) -> str:
    """Generate byte-valid tenant catalog YAML content.

    Always includes the default ``gw`` tenant (empty prefixes) plus a
    generated non-default tenant with a generated prefix, so every
    example exercises both a shared-scope-relevant empty-prefix tenant
    and a non-empty-prefix tenant.
    """
    suffix = draw(
        st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789",
            min_size=1,
            max_size=8,
        )
    )
    other_tenant_id = f"gw_{suffix}"
    prefix = f"{other_tenant_id}_"
    subdir = f"dev-{suffix}"

    return (
        "schema_version: 1\n"
        "defaults:\n"
        "  tenant_id: gw\n"
        "tenants:\n"
        "  - tenant_id: gw\n"
        "    repo_ref: NOAA-EMC/global-workflow\n"
        "    branch: develop\n"
        "    index_prefix: \"\"\n"
        "    label_prefix: \"\"\n"
        "    workflow_subdir: develop\n"
        "    lifecycle: production\n"
        f"  - tenant_id: {other_tenant_id}\n"
        "    repo_ref: NOAA-EMC/global-workflow\n"
        f"    branch: dev/{suffix}\n"
        f"    index_prefix: \"{prefix}\"\n"
        f"    label_prefix: \"{prefix.upper()}\"\n"
        f"    workflow_subdir: {subdir}\n"
        "    lifecycle: experimental\n"
    )


# ---------------------------------------------------------------------------
# Hermetic env-var helper
# ---------------------------------------------------------------------------
#
# Hypothesis re-invokes the test body for every generated example within a
# single pytest function-test call. ``monkeypatch`` is function-scoped and
# is not reset between those internal re-invocations (a Hypothesis health
# check catches this and fails loudly rather than silently), so each
# property test below manages the two transport environment variables and
# a scratch directory itself, with an explicit save/restore around every
# example.


class _ScopedEnv:
    """Save and restore the two catalog transport env vars per example.

    Also owns a fresh scratch directory per example (created on
    ``__enter__``, removed on ``__exit__``), replacing the
    ``tmp_path``/``tmp_path_factory`` fixtures for the same reason
    ``monkeypatch`` is replaced here.
    """

    _KEYS = (tn.ENV_TENANT_CATALOG_YAML, tn.ENV_TENANT_CATALOG_PATH)

    def __enter__(self) -> str:
        self._saved = {k: os.environ.get(k) for k in self._KEYS}
        for k in self._KEYS:
            os.environ.pop(k, None)
        tn._reset_transport_catalog_cache_for_tests()
        self._tmp_dir = tempfile.mkdtemp(prefix="p4-transport-")
        return self._tmp_dir

    def __exit__(self, *exc_info) -> None:
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        tn._reset_transport_catalog_cache_for_tests()
        shutil.rmtree(self._tmp_dir, ignore_errors=True)


def _set_yaml_env(content: str) -> None:
    """Set the inline-YAML transport env var and reset the catalog cache."""
    os.environ[tn.ENV_TENANT_CATALOG_YAML] = content
    os.environ.pop(tn.ENV_TENANT_CATALOG_PATH, None)
    tn._reset_transport_catalog_cache_for_tests()


def _set_path_env(path: str) -> None:
    """Set the file-path transport env var and reset the catalog cache."""
    os.environ[tn.ENV_TENANT_CATALOG_PATH] = path
    os.environ.pop(tn.ENV_TENANT_CATALOG_YAML, None)
    tn._reset_transport_catalog_cache_for_tests()


# ---------------------------------------------------------------------------
# P4 -- transport-layer half
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
# Feature: shared-scope-query-routing, Property 4: Form-factor and transport invariance
@given(
    content=_catalog_yaml_text(), form_factor=st.sampled_from(_FORM_FACTORS)
)
def test_p4_env_and_file_transport_yield_equal_catalog(content, form_factor):
    """P4 (transport half): byte-identical content, inline vs mounted file,
    yields a structurally equal TenantCatalog -- regardless of the
    simulated Form_Factor, since neither transport reads a Form_Factor
    signal at all (Requirement 5.2's "no per-environment branching").

    An equal TenantCatalog implies an equal ``index_prefix`` for every
    tenant, verified per-tenant below rather than relying solely on
    dataclass ``__eq__`` so a future field addition without an updated
    ``__eq__`` cannot silently pass this test.
    """
    # The simulated Form_Factor is asserted to be irrelevant by never
    # being read: the transport functions take no form_factor argument
    # and consult no form_factor-specific environment variable. This
    # generator parameter exists so the property statement literally
    # ranges over both Form_Factors, per Requirement 5.2's phrasing,
    # even though the implementation is Form_Factor-blind by
    # construction.
    del form_factor

    with _ScopedEnv() as tmp_dir:
        unused_default = os.path.join(tmp_dir, "unused-default.yaml")
        with open(unused_default, "w", encoding="utf-8") as fh:
            fh.write(
                "schema_version: 1\ntenants:\n"
                "  - tenant_id: gw\n"
                "    repo_ref: NOAA-EMC/global-workflow\n"
                "    branch: develop\n"
                "    workflow_subdir: develop\n"
                "    lifecycle: production\n"
            )

        mounted_file = os.path.join(tmp_dir, "mounted.yaml")
        with open(mounted_file, "w", encoding="utf-8") as fh:
            fh.write(content)

        _set_path_env(mounted_file)
        file_catalog, file_transport = tn.load_catalog_from_transport(
            unused_default
        )
        assert file_transport == "file"

        _set_yaml_env(content)
        env_catalog, env_transport = tn.load_catalog_from_transport(
            unused_default
        )
        assert env_transport == "env"

        assert file_catalog.tenant_ids == env_catalog.tenant_ids
        for tenant_id in file_catalog.tenant_ids:
            file_tenant = file_catalog.by_id(tenant_id)
            env_tenant = env_catalog.by_id(tenant_id)
            assert file_tenant.index_prefix == env_tenant.index_prefix
            assert file_tenant.label_prefix == env_tenant.label_prefix
        assert file_catalog == env_catalog


@settings(max_examples=100, deadline=None)
# Feature: shared-scope-query-routing, Property 4: Form-factor and transport invariance
@given(
    tenant_id=_TENANT_ID_ALPHABET,
    form_factor_a=st.sampled_from(_FORM_FACTORS),
    form_factor_b=st.sampled_from(_FORM_FACTORS),
)
def test_p4_transport_resolution_is_form_factor_blind(
    tenant_id, form_factor_a, form_factor_b
):
    """P4 (Form_Factor half): resolving the SAME Configuration_Transport
    (the file transport here) under two simulated Form_Factors yields an
    equal catalog, because the resolution reads no Form_Factor-specific
    signal. ``form_factor`` is a bookkeeping label on the test, not a
    real input to :func:`load_catalog_from_transport` -- this is the
    structural proof that Requirement 5.2's invariance holds by
    construction rather than by coincidence.
    """
    with _ScopedEnv() as tmp_dir:
        catalog_path = os.path.join(tmp_dir, "tenants.yaml")
        with open(catalog_path, "w", encoding="utf-8") as fh:
            fh.write(
                "schema_version: 1\n"
                "tenants:\n"
                "  - tenant_id: gw\n"
                "    repo_ref: NOAA-EMC/global-workflow\n"
                "    branch: develop\n"
                "    workflow_subdir: develop\n"
                "    lifecycle: production\n"
                f"  - tenant_id: {tenant_id}\n"
                "    repo_ref: NOAA-EMC/global-workflow\n"
                "    branch: dev/example\n"
                f"    index_prefix: \"{tenant_id}_\"\n"
                "    workflow_subdir: dev-example\n"
                "    lifecycle: experimental\n"
            )

        _set_path_env(catalog_path)

        # Resolve once, "as" form_factor_a -- the environment carries no
        # form-factor signal, so this call and the next are identical in
        # every input that load_catalog_from_transport actually reads.
        del form_factor_a
        catalog_a, transport_a = tn.load_catalog_from_transport(
            catalog_path
        )

        tn._reset_transport_catalog_cache_for_tests()

        # Resolve again, "as" form_factor_b.
        del form_factor_b
        catalog_b, transport_b = tn.load_catalog_from_transport(
            catalog_path
        )

        assert transport_a == transport_b == "file"
        assert catalog_a == catalog_b
        assert tenant_id in catalog_a.tenant_ids
        assert (
            catalog_a.by_id(tenant_id).index_prefix
            == catalog_b.by_id(tenant_id).index_prefix
        )


# ---------------------------------------------------------------------------
# TODO(Task 2 / read_router.py): once resolve_read_targets exists, extend
# P4 with the router-level assertion the design and requirements actually
# describe --
#
#   for any (Logical_Collection, Tenant, Embedding_Profile) triple built
#   from a catalog resolved via the env transport and the SAME catalog
#   resolved via the file transport (byte-identical content),
#   resolve_read_targets(collection, tenant_from_env, profile=p)
#   == resolve_read_targets(collection, tenant_from_file, profile=p)
#
# as an unordered set of physical collection names. This file must not
# import or stub src.data.read_router in the meantime -- Task 2 owns
# that module's creation, per the standing "read path only, do not start
# the next step" scope discipline.
# ---------------------------------------------------------------------------
