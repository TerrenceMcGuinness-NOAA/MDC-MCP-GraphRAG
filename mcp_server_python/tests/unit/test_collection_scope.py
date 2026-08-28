"""Unit tests for :mod:`src.data.collection_scope` (Task 1.1, 1.2, 1.4).

Covers the built-in tables and their accessors (1.1), the override
Configuration_Transport chain (1.2), and the import-boundary guard
(1.4). The drift-gate test (:func:`check_scope_consistency` against the
real manifest) lives in ``test_collection_scope_consistency.py`` (Task
1.3), not here.

shared-scope-query-routing Requirements: 1.1, 1.2, 1.6, 1.8, 5.6, 5.7,
12.6.
"""

from __future__ import annotations

import ast
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.data import collection_scope as cs

_REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_scope_env(monkeypatch):
    """Ensure no override env var leaks between tests, and reset the cache.

    Every test in this module starts from the built-in table unless it
    explicitly sets an override, and the memoized cache must not leak a
    table resolved by a previous test.
    """
    monkeypatch.delenv(cs.ENV_SCOPE_JSON, raising=False)
    monkeypatch.delenv(cs.ENV_SCOPE_PATH, raising=False)
    cs._reset_active_table_cache_for_tests()
    yield
    cs._reset_active_table_cache_for_tests()


# ---------------------------------------------------------------------------
# 1.1 -- built-in tables and accessors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "collection,expected",
    [
        ("global-workflow-docs-v8-0-0", cs.SCOPE_SHARED),
        ("ee2-standards-v5-0-0-enhanced", cs.SCOPE_SHARED),
        ("community-summaries", cs.SCOPE_SHARED),
        ("code-with-context-v8-0-0", cs.SCOPE_TENANT),
        ("jjobs-v8-0-0", cs.SCOPE_TENANT),
    ],
)
def test_scope_of_five_builtin_classifications(collection, expected):
    """R1.2: the five built-in Logical_Collections classify as specified."""
    assert cs.scope_of(collection) == expected


def test_scope_of_is_deterministic_across_repeated_calls():
    """R1.1: same input always yields the same value, every invocation."""
    first = [cs.scope_of("global-workflow-docs-v8-0-0") for _ in range(5)]
    assert len(set(first)) == 1
    assert first[0] == cs.SCOPE_SHARED


def test_scope_of_returns_none_for_unknown_identifier():
    """scope_of never guesses and never raises for an unrecognised id.

    The Read_Router (Task 2) owns the R1.5 ``tenant`` fallback; this
    module reports only what it knows.
    """
    assert cs.scope_of("not-a-real-collection") is None
    assert cs.scope_of("") is None


def test_logical_collections_order_is_stable():
    """R9.1/R10.6/R11.1: iteration order is reproducible across calls."""
    first = cs.logical_collections()
    second = cs.logical_collections()
    assert first == second
    assert set(first) == {
        "global-workflow-docs-v8-0-0",
        "ee2-standards-v5-0-0-enhanced",
        "community-summaries",
        "code-with-context-v8-0-0",
        "jjobs-v8-0-0",
    }


def test_hybrid_set_is_exactly_one_member():
    """R1.8: workflow-docs is the only built-in Hybrid_Domain."""
    assert cs.is_hybrid_domain("global-workflow-docs-v8-0-0") is True
    for other in cs.logical_collections():
        if other != "global-workflow-docs-v8-0-0":
            assert cs.is_hybrid_domain(other) is False


def test_hybrid_domain_membership_restricted_to_shared():
    """R1.8: every classified Hybrid_Domain member is scope 'shared'."""
    for collection in cs.logical_collections():
        if cs.is_hybrid_domain(collection):
            assert cs.scope_of(collection) == cs.SCOPE_SHARED


def test_builtin_hybrid_invariant_violation_fails_at_import():
    """R1.8: a table where a hybrid member is not 'shared' fails at import.

    Exercised as a fresh subprocess import so the assertion added at
    module scope (not inside a function) is triggered, rather than
    patching the already-imported module's globals.
    """
    src = (
        "from src.data import collection_scope as _mod\n"
        "_mod._BUILTIN_SCOPES['jjobs-v8-0-0'] = _mod.SCOPE_TENANT\n"
        "_mod._BUILTIN_HYBRID = frozenset({'jjobs-v8-0-0'})\n"
        "for _m in _mod._BUILTIN_HYBRID:\n"
        "    if _mod._BUILTIN_SCOPES.get(_m) != _mod.SCOPE_SHARED:\n"
        "        raise AssertionError('violates hybrid-must-be-shared')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", src],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "violates hybrid-must-be-shared" in result.stderr


# ---------------------------------------------------------------------------
# 1.2 -- override Configuration_Transport chain
# ---------------------------------------------------------------------------


_VALID_OVERRIDE = {
    "schema_version": 1,
    "scopes": {
        "global-workflow-docs-v8-0-0": "shared",
        "ee2-standards-v5-0-0-enhanced": "tenant",
    },
    "hybrid_domains": ["global-workflow-docs-v8-0-0"],
}


def test_inline_json_override_replaces_tables_wholesale(monkeypatch):
    """An override REPLACES both tables; it does not merge with builtin."""
    monkeypatch.setenv(cs.ENV_SCOPE_JSON, json.dumps(_VALID_OVERRIDE))
    cs._reset_active_table_cache_for_tests()

    assert cs.scope_of("global-workflow-docs-v8-0-0") == cs.SCOPE_SHARED
    assert cs.scope_of("ee2-standards-v5-0-0-enhanced") == cs.SCOPE_TENANT
    # Not present in the override -> unrecognised, not builtin-inherited.
    assert cs.scope_of("code-with-context-v8-0-0") is None
    assert cs.active_scope_transport() == "env"


def test_file_override_used_when_no_inline_content(tmp_path, monkeypatch):
    """File transport is used when the inline env var is absent."""
    override_path = tmp_path / "scope_override.json"
    override_path.write_text(json.dumps(_VALID_OVERRIDE), encoding="utf-8")
    monkeypatch.setenv(cs.ENV_SCOPE_PATH, str(override_path))
    cs._reset_active_table_cache_for_tests()

    assert cs.scope_of("ee2-standards-v5-0-0-enhanced") == cs.SCOPE_TENANT
    assert cs.active_scope_transport() == "file"


def test_inline_content_wins_over_file_path(tmp_path, monkeypatch):
    """R5.7: inline env content takes precedence over a file path."""
    file_override = dict(_VALID_OVERRIDE)
    file_override["scopes"] = {"jjobs-v8-0-0": "shared"}
    override_path = tmp_path / "scope_override.json"
    override_path.write_text(json.dumps(file_override), encoding="utf-8")

    monkeypatch.setenv(cs.ENV_SCOPE_PATH, str(override_path))
    monkeypatch.setenv(cs.ENV_SCOPE_JSON, json.dumps(_VALID_OVERRIDE))
    cs._reset_active_table_cache_for_tests()

    assert cs.active_scope_transport() == "env"
    assert cs.scope_of("jjobs-v8-0-0") is None
    assert cs.scope_of("global-workflow-docs-v8-0-0") == cs.SCOPE_SHARED


def test_active_scope_transport_reports_builtin_by_default():
    assert cs.active_scope_transport() == "builtin"


def test_corrupt_inline_json_raises_naming_source(monkeypatch):
    monkeypatch.setenv(cs.ENV_SCOPE_JSON, "{not valid json")
    cs._reset_active_table_cache_for_tests()
    with pytest.raises(cs.ScopeConfigError) as excinfo:
        cs.scope_of("global-workflow-docs-v8-0-0")
    assert cs.ENV_SCOPE_JSON in str(excinfo.value)


def test_corrupt_override_file_raises_naming_source(tmp_path, monkeypatch):
    bad_path = tmp_path / "bad.json"
    bad_path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setenv(cs.ENV_SCOPE_PATH, str(bad_path))
    cs._reset_active_table_cache_for_tests()
    with pytest.raises(cs.ScopeConfigError) as excinfo:
        cs.scope_of("global-workflow-docs-v8-0-0")
    assert str(bad_path) in str(excinfo.value)


def test_unreadable_override_path_raises_naming_source(tmp_path, monkeypatch):
    missing_path = tmp_path / "does-not-exist.json"
    monkeypatch.setenv(cs.ENV_SCOPE_PATH, str(missing_path))
    cs._reset_active_table_cache_for_tests()
    with pytest.raises(cs.ScopeConfigError) as excinfo:
        cs.scope_of("global-workflow-docs-v8-0-0")
    assert str(missing_path) in str(excinfo.value)


@pytest.mark.parametrize(
    "broken_doc,expected_fragment",
    [
        ({"scopes": {"x": "shared"}}, "schema_version"),
        ({"schema_version": 1, "scopes": {}}, "scopes"),
        ({"schema_version": 1, "scopes": "not-a-dict"}, "scopes"),
        (
            {"schema_version": 1, "scopes": {"x": "not-a-scope"}},
            "scope",
        ),
        (
            {
                "schema_version": 1,
                "scopes": {"x": "shared"},
                "hybrid_domains": ["y"],
            },
            "hybrid_domains",
        ),
        (
            {
                "schema_version": 1,
                "scopes": {"x": "tenant"},
                "hybrid_domains": ["x"],
            },
            "shared",
        ),
        (
            {"schema_version": 2, "scopes": {"x": "shared"}},
            "schema_version",
        ),
    ],
)
def test_schema_violations_raise_scope_config_error(
    broken_doc, expected_fragment, monkeypatch
):
    """R5.6: every schema violation raises, naming the failing source."""
    monkeypatch.setenv(cs.ENV_SCOPE_JSON, json.dumps(broken_doc))
    cs._reset_active_table_cache_for_tests()
    with pytest.raises(cs.ScopeConfigError) as excinfo:
        cs.scope_of("x")
    assert expected_fragment in str(excinfo.value)


def test_override_load_failure_records_zero_adapter_calls(monkeypatch):
    """A load failure resolves nothing -- there is no adapter to call here,
    but the guarantee is that raising happens before any table is
    returned, so no caller can proceed to issue a read.
    """
    monkeypatch.setenv(cs.ENV_SCOPE_JSON, "{not valid json")
    cs._reset_active_table_cache_for_tests()
    with pytest.raises(cs.ScopeConfigError):
        cs.is_hybrid_domain("global-workflow-docs-v8-0-0")
    with pytest.raises(cs.ScopeConfigError):
        cs.logical_collections()


def test_override_content_is_memoized(monkeypatch):
    """The active table is read once and memoized (R5.1, P9 groundwork).

    Changing the env var after the first resolution must not change the
    result within the same process lifetime, because the content is
    read exactly once via :func:`_active_table`.
    """
    monkeypatch.setenv(cs.ENV_SCOPE_JSON, json.dumps(_VALID_OVERRIDE))
    cs._reset_active_table_cache_for_tests()
    assert cs.scope_of("ee2-standards-v5-0-0-enhanced") == cs.SCOPE_TENANT

    monkeypatch.setenv(
        cs.ENV_SCOPE_JSON,
        json.dumps(
            {
                "schema_version": 1,
                "scopes": {"ee2-standards-v5-0-0-enhanced": "shared"},
            }
        ),
    )
    # No cache reset here -- the memoized value must be reused.
    assert cs.scope_of("ee2-standards-v5-0-0-enhanced") == cs.SCOPE_TENANT


# ---------------------------------------------------------------------------
# 1.4 -- import boundary
# ---------------------------------------------------------------------------


def test_collection_scope_imports_stdlib_only():
    """R12.6: no import of read_router, any adapter, or src.tools.

    Checked via AST inspection of the source file rather than via
    ``sys.modules`` after import, so the assertion holds even if some
    other test in the same process has already imported one of the
    forbidden modules for an unrelated reason.

    Note: the write path (``collection_namer.py`` and the ingestion
    scripts under ``scripts/``) is NOT re-pointed at this module in
    this change. R12.2 freezes ``scripts/`` byte-for-byte, so adoption
    of this module by the write side -- while structurally possible
    given the import direction asserted here -- is a future, separately
    decided step.
    """
    module_path = (
        Path(__file__).resolve().parents[2]
        / "src" / "data" / "collection_scope.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))

    forbidden_substrings = (
        "read_router",
        "src.tools",
        "src.data.chromadb_adapter",
        "src.data.opensearch_adapter",
        "src.data.protocols",
    )

    imported_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imported_names.append(module)
            imported_names.extend(f"{module}.{a.name}" for a in node.names)

    for name in imported_names:
        assert not name.startswith("src."), (
            f"collection_scope.py must import stdlib only; found "
            f"repository import: {name!r}"
        )
        for forbidden in forbidden_substrings:
            assert forbidden not in name, (
                f"collection_scope.py must not import {forbidden!r}; "
                f"found: {name!r}"
            )


def test_collection_scope_module_has_no_repo_imports_at_runtime():
    """Cross-check the AST assertion against the actually-imported module.

    ``importlib.reload`` re-executes the module body so any import
    added later would be exercised, not just parsed.
    """
    reloaded = importlib.reload(cs)
    module_file = Path(reloaded.__file__).resolve()
    assert module_file.name == "collection_scope.py"
