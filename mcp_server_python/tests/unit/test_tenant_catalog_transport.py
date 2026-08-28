"""Unit tests for the content-carrying tenant catalog transport (Task 3.1).

shared-scope-query-routing Requirements: 5.3, 5.6, 5.7, 12.2.

Covers :func:`src.config.tenants.load_catalog_from_transport` and the
switch of :func:`src.tenancy.runtime.get_catalog` to it. The precedence
under test is inline ``MCP_TENANT_CATALOG_YAML`` content, then a
``MCP_TENANT_CATALOG_PATH`` file, then the bundled default -- one rule,
with no per-Form_Factor branching, per Requirement 5.7.

Also asserts :func:`src.config.tenants.load_catalog` (path-only) keeps
its existing signature and behaviour untouched, since the ingestion
scripts under ``mcp_server_python/scripts/`` import it directly and
Requirement 12.2 freezes that directory byte-for-byte.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

import src.tenancy.runtime as runtime
from src.config import tenants as tn

_REPO_ROOT = Path(__file__).resolve().parents[2]

_MINIMAL_CATALOG_YAML = """
schema_version: 1
defaults:
  tenant_id: gw
tenants:
  - tenant_id: gw
    repo_ref: NOAA-EMC/global-workflow
    branch: develop
    index_prefix: ""
    label_prefix: ""
    workflow_subdir: develop
    lifecycle: production
  - tenant_id: gw_v17
    repo_ref: NOAA-EMC/global-workflow
    branch: dev/gfs.v17
    index_prefix: "gw_v17_"
    label_prefix: "GW_V17_"
    workflow_subdir: dev-v17
    lifecycle: staging
"""

_ALTERNATE_CATALOG_YAML = """
schema_version: 1
defaults:
  tenant_id: gw
tenants:
  - tenant_id: gw
    repo_ref: NOAA-EMC/global-workflow
    branch: develop
    index_prefix: ""
    label_prefix: ""
    workflow_subdir: develop
    lifecycle: production
"""

_CORRUPT_CATALOG_YAML = "schema_version: [this is not a mapping"


@pytest.fixture(autouse=True)
def _clean_transport_env(monkeypatch):
    """Ensure no transport env var leaks between tests, and reset caches.

    Every test starts from a clean slate -- neither env var set, both
    module-level memoization caches cleared -- unless it explicitly sets
    an override, matching the pattern
    ``test_collection_scope.py::_clean_scope_env`` uses for the sibling
    transport.
    """
    monkeypatch.delenv(tn.ENV_TENANT_CATALOG_YAML, raising=False)
    monkeypatch.delenv(tn.ENV_TENANT_CATALOG_PATH, raising=False)
    tn._reset_transport_catalog_cache_for_tests()
    runtime.reset_catalog()
    yield
    tn._reset_transport_catalog_cache_for_tests()
    runtime.reset_catalog()


# ---------------------------------------------------------------------------
# load_catalog(path) is unchanged (Requirement 12.2)
# ---------------------------------------------------------------------------


def test_load_catalog_signature_and_behaviour_unchanged(tmp_path):
    """R12.2: load_catalog(path) keeps its existing signature/behaviour.

    The ingestion scripts under ``mcp_server_python/scripts/`` and
    ``src/tools/smoke_queries.py`` import ``load_catalog`` directly with
    a single positional ``path`` argument; this test pins that contract
    rather than relying on the byte-freeze test alone to catch drift.
    """
    catalog_path = tmp_path / "tenants.yaml"
    catalog_path.write_text(_MINIMAL_CATALOG_YAML, encoding="utf-8")

    catalog = tn.load_catalog(catalog_path)

    assert catalog.tenant_ids == ("gw", "gw_v17")
    assert catalog.by_id("gw_v17").index_prefix == "gw_v17_"


def test_load_catalog_accepts_str_and_path(tmp_path):
    """load_catalog accepts both str and Path, as it did before this task."""
    catalog_path = tmp_path / "tenants.yaml"
    catalog_path.write_text(_MINIMAL_CATALOG_YAML, encoding="utf-8")

    by_path = tn.load_catalog(catalog_path)
    by_str = tn.load_catalog(str(catalog_path))

    assert by_path.tenant_ids == by_str.tenant_ids


def test_load_catalog_raises_file_not_found_for_missing_path(tmp_path):
    """R12.2: FileNotFoundError is still the signal for a missing file."""
    missing = tmp_path / "does-not-exist.yaml"
    with pytest.raises(FileNotFoundError):
        tn.load_catalog(missing)


def test_load_catalog_raises_yaml_error_for_corrupt_content(tmp_path):
    """R12.2: corrupt YAML still raises yaml.YAMLError, not a new type."""
    bad_path = tmp_path / "bad.yaml"
    bad_path.write_text(_CORRUPT_CATALOG_YAML, encoding="utf-8")
    with pytest.raises(yaml.YAMLError):
        tn.load_catalog(bad_path)


# ---------------------------------------------------------------------------
# load_catalog_from_transport -- precedence (R5.7)
# ---------------------------------------------------------------------------


def test_builtin_default_used_when_neither_env_var_set(tmp_path):
    """With no override, the transport resolves the given default_path."""
    default_path = tmp_path / "tenants.yaml"
    default_path.write_text(_ALTERNATE_CATALOG_YAML, encoding="utf-8")

    catalog, transport = tn.load_catalog_from_transport(default_path)

    assert transport == "builtin"
    assert catalog.tenant_ids == ("gw",)


def test_file_transport_used_when_path_env_set(tmp_path, monkeypatch):
    """MCP_TENANT_CATALOG_PATH is honoured when set and no inline content."""
    override_path = tmp_path / "override.yaml"
    override_path.write_text(_MINIMAL_CATALOG_YAML, encoding="utf-8")
    unused_default = tmp_path / "unused-default.yaml"
    unused_default.write_text(_ALTERNATE_CATALOG_YAML, encoding="utf-8")

    monkeypatch.setenv(tn.ENV_TENANT_CATALOG_PATH, str(override_path))

    catalog, transport = tn.load_catalog_from_transport(unused_default)

    assert transport == "file"
    assert catalog.tenant_ids == ("gw", "gw_v17")


def test_env_yaml_transport_used_when_inline_content_set(
    monkeypatch, tmp_path
):
    """MCP_TENANT_CATALOG_YAML (inline content) is honoured when set."""
    unused_default = tmp_path / "unused-default.yaml"
    unused_default.write_text(_ALTERNATE_CATALOG_YAML, encoding="utf-8")

    monkeypatch.setenv(tn.ENV_TENANT_CATALOG_YAML, _MINIMAL_CATALOG_YAML)

    catalog, transport = tn.load_catalog_from_transport(unused_default)

    assert transport == "env"
    assert catalog.tenant_ids == ("gw", "gw_v17")


def test_inline_content_wins_over_file_path(monkeypatch, tmp_path):
    """R5.7: MCP_TENANT_CATALOG_YAML beats MCP_TENANT_CATALOG_PATH.

    One precedence rule with no per-environment branching: setting both
    resolves through the inline content, never the file.
    """
    file_override = tmp_path / "file-override.yaml"
    file_override.write_text(_ALTERNATE_CATALOG_YAML, encoding="utf-8")
    unused_default = tmp_path / "unused-default.yaml"
    unused_default.write_text(_ALTERNATE_CATALOG_YAML, encoding="utf-8")

    monkeypatch.setenv(tn.ENV_TENANT_CATALOG_PATH, str(file_override))
    monkeypatch.setenv(tn.ENV_TENANT_CATALOG_YAML, _MINIMAL_CATALOG_YAML)

    catalog, transport = tn.load_catalog_from_transport(unused_default)

    assert transport == "env"
    assert catalog.tenant_ids == ("gw", "gw_v17")


def test_both_env_vars_and_default_all_present_resolves_env_only(
    monkeypatch, tmp_path
):
    """All three sources present at once still resolves exactly one."""
    file_override = tmp_path / "file-override.yaml"
    file_override.write_text(_ALTERNATE_CATALOG_YAML, encoding="utf-8")
    default_path = tmp_path / "default.yaml"
    default_path.write_text(_ALTERNATE_CATALOG_YAML, encoding="utf-8")

    monkeypatch.setenv(tn.ENV_TENANT_CATALOG_PATH, str(file_override))
    monkeypatch.setenv(tn.ENV_TENANT_CATALOG_YAML, _MINIMAL_CATALOG_YAML)

    catalog, transport = tn.load_catalog_from_transport(default_path)

    assert transport == "env"
    assert catalog.tenant_ids == ("gw", "gw_v17")


# ---------------------------------------------------------------------------
# Byte-identical content -> equal catalog, across both transports (R5.3)
# ---------------------------------------------------------------------------


def test_byte_identical_content_yields_equal_catalog_across_transports(
    monkeypatch, tmp_path
):
    """R5.3: env content byte-identical to a mounted file yields an equal
    TenantCatalog, and therefore an equal index_prefix for every tenant.

    Both transports parse through the same
    :func:`tn._parse_catalog_yaml_text`, so this is a structural
    guarantee rather than an incidental match -- verified here with a
    per-field comparison rather than relying on dataclass ``__eq__``
    alone, so a future field addition without an ``__eq__`` override
    cannot silently pass this test without being compared.
    """
    mounted_file = tmp_path / "mounted.yaml"
    mounted_file.write_text(_MINIMAL_CATALOG_YAML, encoding="utf-8")
    unused_default = tmp_path / "unused-default.yaml"
    unused_default.write_text(_ALTERNATE_CATALOG_YAML, encoding="utf-8")

    monkeypatch.setenv(tn.ENV_TENANT_CATALOG_PATH, str(mounted_file))
    file_catalog, file_transport = tn.load_catalog_from_transport(
        unused_default
    )
    assert file_transport == "file"

    tn._reset_transport_catalog_cache_for_tests()
    monkeypatch.delenv(tn.ENV_TENANT_CATALOG_PATH, raising=False)
    monkeypatch.setenv(tn.ENV_TENANT_CATALOG_YAML, _MINIMAL_CATALOG_YAML)
    env_catalog, env_transport = tn.load_catalog_from_transport(
        unused_default
    )
    assert env_transport == "env"

    assert file_catalog == env_catalog
    assert file_catalog.schema_version == env_catalog.schema_version
    assert file_catalog.defaults == env_catalog.defaults
    assert file_catalog.tenant_ids == env_catalog.tenant_ids
    for tenant_id in file_catalog.tenant_ids:
        file_tenant = file_catalog.by_id(tenant_id)
        env_tenant = env_catalog.by_id(tenant_id)
        assert file_tenant == env_tenant
        assert file_tenant.index_prefix == env_tenant.index_prefix
        assert file_tenant.label_prefix == env_tenant.label_prefix


def test_byte_identical_content_yields_equal_catalog_file_vs_builtin(
    monkeypatch, tmp_path
):
    """The same equality holds between the file transport and the
    builtin/default-path transport when their content is identical."""
    shared_path = tmp_path / "shared.yaml"
    shared_path.write_text(_MINIMAL_CATALOG_YAML, encoding="utf-8")

    builtin_catalog, builtin_transport = tn.load_catalog_from_transport(
        shared_path
    )
    assert builtin_transport == "builtin"

    tn._reset_transport_catalog_cache_for_tests()
    monkeypatch.setenv(tn.ENV_TENANT_CATALOG_PATH, str(shared_path))
    file_catalog, file_transport = tn.load_catalog_from_transport(shared_path)
    assert file_transport == "file"

    assert builtin_catalog == file_catalog


# ---------------------------------------------------------------------------
# Hard-error path (R5.6): a named source that fails to read/parse raises,
# names the source, resolves nothing, and never degrades.
# ---------------------------------------------------------------------------


def test_corrupt_inline_yaml_raises_naming_source(monkeypatch, tmp_path):
    monkeypatch.setenv(tn.ENV_TENANT_CATALOG_YAML, _CORRUPT_CATALOG_YAML)
    default_path = tmp_path / "default.yaml"
    default_path.write_text(_ALTERNATE_CATALOG_YAML, encoding="utf-8")

    with pytest.raises(tn.CatalogConfigError) as excinfo:
        tn.load_catalog_from_transport(default_path)

    assert tn.ENV_TENANT_CATALOG_YAML in str(excinfo.value)


def test_corrupt_file_yaml_raises_naming_source(monkeypatch, tmp_path):
    bad_path = tmp_path / "bad.yaml"
    bad_path.write_text(_CORRUPT_CATALOG_YAML, encoding="utf-8")
    monkeypatch.setenv(tn.ENV_TENANT_CATALOG_PATH, str(bad_path))
    default_path = tmp_path / "default.yaml"
    default_path.write_text(_ALTERNATE_CATALOG_YAML, encoding="utf-8")

    with pytest.raises(tn.CatalogConfigError) as excinfo:
        tn.load_catalog_from_transport(default_path)

    assert str(bad_path) in str(excinfo.value)


def test_unreadable_file_path_raises_naming_source(monkeypatch, tmp_path):
    missing_path = tmp_path / "does-not-exist.yaml"
    monkeypatch.setenv(tn.ENV_TENANT_CATALOG_PATH, str(missing_path))
    default_path = tmp_path / "default.yaml"
    default_path.write_text(_ALTERNATE_CATALOG_YAML, encoding="utf-8")

    with pytest.raises(tn.CatalogConfigError) as excinfo:
        tn.load_catalog_from_transport(default_path)

    assert str(missing_path) in str(excinfo.value)


def test_corrupt_builtin_default_raises_naming_source(tmp_path):
    """A named default_path that cannot be parsed is also a hard error."""
    bad_default = tmp_path / "bad-default.yaml"
    bad_default.write_text(_CORRUPT_CATALOG_YAML, encoding="utf-8")

    with pytest.raises(tn.CatalogConfigError) as excinfo:
        tn.load_catalog_from_transport(bad_default)

    assert str(bad_default) in str(excinfo.value)


def test_structural_validation_failure_raises_catalog_config_error(
    monkeypatch, tmp_path
):
    """A structurally invalid catalog (e.g. duplicate tenant_id) is also
    wrapped as CatalogConfigError by the transport chain, naming the
    source, even though load_catalog itself raises the more specific
    TenantError subclass (R12.2 preserves that distinction for
    load_catalog callers only).
    """
    duplicate_ids_yaml = """
schema_version: 1
tenants:
  - tenant_id: gw
    repo_ref: NOAA-EMC/global-workflow
    branch: develop
    workflow_subdir: develop
    lifecycle: production
  - tenant_id: gw
    repo_ref: NOAA-EMC/global-workflow
    branch: develop
    workflow_subdir: develop2
    lifecycle: production
"""
    monkeypatch.setenv(tn.ENV_TENANT_CATALOG_YAML, duplicate_ids_yaml)
    default_path = tmp_path / "default.yaml"
    default_path.write_text(_ALTERNATE_CATALOG_YAML, encoding="utf-8")

    with pytest.raises(tn.CatalogConfigError) as excinfo:
        tn.load_catalog_from_transport(default_path)

    assert tn.ENV_TENANT_CATALOG_YAML in str(excinfo.value)


def test_hard_error_resolves_nothing_and_is_not_cached(monkeypatch, tmp_path):
    """A failed resolution must not memoize a partial/empty result, and
    a repeated call under the same broken env must raise again -- not
    silently fall through to the builtin default on a second attempt.
    """
    monkeypatch.setenv(tn.ENV_TENANT_CATALOG_YAML, _CORRUPT_CATALOG_YAML)
    default_path = tmp_path / "default.yaml"
    default_path.write_text(_ALTERNATE_CATALOG_YAML, encoding="utf-8")

    with pytest.raises(tn.CatalogConfigError):
        tn.load_catalog_from_transport(default_path)
    with pytest.raises(tn.CatalogConfigError):
        tn.load_catalog_from_transport(default_path)


# ---------------------------------------------------------------------------
# Memoization (read once)
# ---------------------------------------------------------------------------


def test_transport_content_is_memoized(monkeypatch, tmp_path):
    """The active catalog is read once; a later env change within the
    same process lifetime must not change the result without a cache
    reset, mirroring collection_scope.py's memoization guarantee.
    """
    default_path = tmp_path / "default.yaml"
    default_path.write_text(_ALTERNATE_CATALOG_YAML, encoding="utf-8")

    monkeypatch.setenv(tn.ENV_TENANT_CATALOG_YAML, _MINIMAL_CATALOG_YAML)
    first_catalog, _ = tn.load_catalog_from_transport(default_path)
    assert first_catalog.tenant_ids == ("gw", "gw_v17")

    monkeypatch.setenv(tn.ENV_TENANT_CATALOG_YAML, _ALTERNATE_CATALOG_YAML)
    # No cache reset here -- the memoized value must be reused.
    second_catalog, _ = tn.load_catalog_from_transport(default_path)
    assert second_catalog.tenant_ids == ("gw", "gw_v17")


# ---------------------------------------------------------------------------
# runtime.get_catalog() switches to the new transport (Task 3.1)
# ---------------------------------------------------------------------------


def test_runtime_get_catalog_resolves_bundled_default_with_no_env():
    """With neither env var set, runtime.get_catalog() still resolves
    the bundled src/config/tenants.yaml, unaffected by this change."""
    catalog = runtime.get_catalog()
    assert "gw" in catalog.tenant_ids


def test_runtime_get_catalog_honours_inline_yaml_env(monkeypatch):
    monkeypatch.setenv(tn.ENV_TENANT_CATALOG_YAML, _MINIMAL_CATALOG_YAML)
    catalog = runtime.get_catalog()
    assert catalog.tenant_ids == ("gw", "gw_v17")


def test_runtime_get_catalog_honours_path_env(monkeypatch, tmp_path):
    override_path = tmp_path / "override.yaml"
    override_path.write_text(_MINIMAL_CATALOG_YAML, encoding="utf-8")
    monkeypatch.setenv(tn.ENV_TENANT_CATALOG_PATH, str(override_path))
    catalog = runtime.get_catalog()
    assert catalog.tenant_ids == ("gw", "gw_v17")


def test_runtime_get_catalog_is_cached_across_calls(monkeypatch):
    monkeypatch.setenv(tn.ENV_TENANT_CATALOG_YAML, _MINIMAL_CATALOG_YAML)
    first = runtime.get_catalog()
    monkeypatch.setenv(tn.ENV_TENANT_CATALOG_YAML, _ALTERNATE_CATALOG_YAML)
    second = runtime.get_catalog()
    assert first is second
    assert second.tenant_ids == ("gw", "gw_v17")


def test_runtime_get_catalog_hard_error_propagates(monkeypatch):
    """A malformed inline catalog surfaces to runtime.get_catalog()'s
    caller as CatalogConfigError, never a silent fallback to the
    bundled default (R5.6)."""
    monkeypatch.setenv(tn.ENV_TENANT_CATALOG_YAML, _CORRUPT_CATALOG_YAML)
    with pytest.raises(tn.CatalogConfigError):
        runtime.get_catalog()


def test_reset_catalog_clears_both_module_caches(monkeypatch, tmp_path):
    """runtime.reset_catalog() must also clear tenants.py's transport
    cache, or a stale cross-module cache entry would survive the reset
    and the next get_catalog() call would not honour a changed env var.
    """
    monkeypatch.setenv(tn.ENV_TENANT_CATALOG_YAML, _MINIMAL_CATALOG_YAML)
    first = runtime.get_catalog()
    assert first.tenant_ids == ("gw", "gw_v17")

    runtime.reset_catalog()
    monkeypatch.setenv(tn.ENV_TENANT_CATALOG_YAML, _ALTERNATE_CATALOG_YAML)
    second = runtime.get_catalog()

    assert second.tenant_ids == ("gw",)


# ---------------------------------------------------------------------------
# Write-path import boundary: scripts/ and smoke_queries.py are untouched
# ---------------------------------------------------------------------------


def test_smoke_queries_still_imports_load_catalog_directly():
    """R12.2: src/tools/smoke_queries.py continues to call
    src.config.tenants.load_catalog(path) directly, not the new
    transport function. Checked via AST so this fails loudly if a
    future edit re-points that call.
    """
    module_path = (
        _REPO_ROOT / "src" / "tools" / "smoke_queries.py"
    )
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    found_import = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "src.config.tenants":
                names = {alias.name for alias in node.names}
                if "load_catalog" in names:
                    found_import = True

    assert found_import, (
        "src/tools/smoke_queries.py must still import load_catalog "
        "directly from src.config.tenants (R12.2)"
    )
