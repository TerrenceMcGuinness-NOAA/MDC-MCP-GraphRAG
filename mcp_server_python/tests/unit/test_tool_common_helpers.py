"""Unit tests for the shared tool-layer helpers in ``src.tools._common``.

Spec: ``.kiro/specs/graceful-missing-index-handling/`` — Task 1.1.

Covers the Detect_Helper (``_is_missing_index_exc``) detection matrix
(Requirements 1.1-1.3), the Render_Helper (``_missing_index_skip``)
format invariants (Requirements 2.1-2.5), and the ``_tenant_id_or_none``
accessor. No live AWS calls.
"""

from __future__ import annotations

import pytest

from src.tools._common import (
    _is_missing_index_exc,
    _missing_index_skip,
    _tenant_id_or_none,
)

pytestmark = pytest.mark.unit


# ── _is_missing_index_exc (R1) ──────────────────────────────────────────


def test_detect_structured_notfound_index_missing_true() -> None:
    """opensearchpy NotFoundError with error.type=index_not_found_exception."""
    from opensearchpy.exceptions import NotFoundError

    exc = NotFoundError(
        404,
        "index_not_found_exception",
        {"error": {"type": "index_not_found_exception"}},
    )
    assert _is_missing_index_exc(exc) is True


def test_detect_structured_path_when_str_lacks_token() -> None:
    """Structured branch fires even when str() does not carry the token."""
    from opensearchpy.exceptions import NotFoundError

    exc = NotFoundError(
        404, "boom", {"error": {"type": "index_not_found_exception"}}
    )
    assert "index_not_found_exception" not in str(exc)
    assert _is_missing_index_exc(exc) is True


def test_detect_structured_other_error_type_false() -> None:
    """A 404 with a different error.type is not a missing-index condition."""
    from opensearchpy.exceptions import NotFoundError

    exc = NotFoundError(
        404,
        "document_missing_exception",
        {"error": {"type": "document_missing_exception"}},
    )
    assert _is_missing_index_exc(exc) is False


def test_detect_string_fallback_true() -> None:
    """Generic exception whose str() carries the token -> True."""
    exc = Exception(
        "OpenSearch search on index='x' failed: "
        "NotFoundError(404, 'index_not_found_exception', ...)"
    )
    assert _is_missing_index_exc(exc) is True


def test_detect_generic_transport_error_false() -> None:
    assert _is_missing_index_exc(RuntimeError("transport boom")) is False


def test_detect_base_exception_false() -> None:
    assert _is_missing_index_exc(BaseException("nothing relevant")) is False


# ── _missing_index_skip (R2) ────────────────────────────────────────────


def test_skip_block_starts_with_info() -> None:
    out = _missing_index_skip(
        tool="search_architecture",
        query="ocean modeling",
        collection="community-summaries",
        tenant_id="gw_v17",
    )
    assert out.startswith("[INFO]")
    assert "[ERROR]" not in out


def test_skip_block_contains_collection_tenant_and_advisory() -> None:
    out = _missing_index_skip(
        tool="search_architecture",
        query="ocean modeling",
        collection="community-summaries",
        tenant_id="gw_v17",
    )
    assert "community-summaries" in out
    assert "gw_v17" in out
    assert "get_knowledge_base_status" in out


def test_skip_block_strips_collection_path_prefix() -> None:
    out = _missing_index_skip(
        tool="t", query="q", collection="a/b/community-summaries",
        tenant_id="gw_v17",
    )
    assert "community-summaries" in out
    assert "a/b/community-summaries" not in out


def test_skip_block_defaults_tenant_to_gw() -> None:
    out = _missing_index_skip(
        tool="t", query="q", collection="c", tenant_id=None
    )
    assert "'gw'" in out


def test_skip_block_is_ascii_only() -> None:
    out = _missing_index_skip(
        tool="find_similar_code", query="q",
        collection="code-with-context-v8-0-0", tenant_id="gw_v17",
    )
    # Must not raise — ASCII-only (R2.5).
    out.encode("ascii")
    assert "\n" in out  # multi-line block


# ── _tenant_id_or_none ──────────────────────────────────────────────────


def test_tenant_id_or_none_outside_scope_is_none() -> None:
    # No active tenant scope in a bare unit test -> None.
    assert _tenant_id_or_none() is None
