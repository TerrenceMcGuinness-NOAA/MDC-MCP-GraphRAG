"""Unit tests for _attribution.py branch-line extension.

Feature: omd-tenants-2-v17-pilot, Requirements 6.1, 6.2, 6.3
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.tools._attribution import attribute


@dataclass(frozen=True)
class _Tenant:
    tenant_id: str
    branch: str
    lifecycle: str


class TestBranchLineEdgeCases:
    """Edge cases for the *Branch: <branch>* line in attribution headers."""

    def test_empty_branch_no_branch_line(self):
        """Empty-string branch → no branch line emitted."""
        t = _Tenant(tenant_id="gw_future", branch="", lifecycle="production")
        result = attribute("hello", t)
        assert result == "*Tenant: gw_future*\n\nhello"
        assert "*Branch:" not in result

    def test_branch_with_slashes_preserved(self):
        """Branch containing slashes is preserved verbatim."""
        t = _Tenant(tenant_id="gw_v17", branch="dev/gfs.v17", lifecycle="staging")
        result = attribute("body", t)
        lines = result.split("\n")
        assert lines[0] == "*Tenant: gw_v17*"
        assert lines[1] == "*Branch: dev/gfs.v17*"
        assert lines[2] == ""
        assert lines[3] == "body"

    def test_branch_release_tag_style(self):
        """Branch with release-style path preserved."""
        t = _Tenant(tenant_id="gw_gefs", branch="release/2026q3", lifecycle="production")
        result = attribute("x", t)
        assert "*Branch: release/2026q3*" in result

    def test_stale_plus_branch_ordering(self):
        """[STALE] suffix on tenant line, branch line follows."""
        t = _Tenant(tenant_id="old", branch="legacy/v15", lifecycle="stale")
        result = attribute("data", t)
        lines = result.split("\n")
        assert lines[0] == "*Tenant: old* [STALE]"
        assert lines[1] == "*Branch: legacy/v15*"
        assert lines[2] == ""
        assert lines[3] == "data"

    def test_non_string_passthrough(self):
        """Non-string body passes through unchanged."""
        t = _Tenant(tenant_id="gw", branch="develop", lifecycle="production")
        assert attribute(42, t) == 42
        assert attribute({"key": "val"}, t) == {"key": "val"}
        assert attribute(None, t) is None

    def test_develop_branch(self):
        """The gw tenant with branch=develop emits *Branch: develop*."""
        t = _Tenant(tenant_id="gw", branch="develop", lifecycle="production")
        result = attribute("content", t)
        assert result.startswith("*Tenant: gw*\n*Branch: develop*\n\ncontent")
