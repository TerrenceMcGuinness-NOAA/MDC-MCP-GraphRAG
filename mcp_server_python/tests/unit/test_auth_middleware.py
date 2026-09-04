"""Unit tests for src/auth/middleware.py — principal derivation from Trusted_Context_Headers.

Validates Requirements R5.1, R5.2, R5.4.
"""
from __future__ import annotations

import pytest

from src.auth.middleware import (
    KNOWN_SCOPES,
    ForbiddenError,
    PrincipalContext,
    derive_principal,
)

# Header names (various casings to exercise case-insensitive lookup)
_H_PRINCIPAL = "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Principal"
_H_SCOPE = "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Scope"
_H_BROKER = "X-Amzn-Bedrock-AgentCore-Runtime-Custom-BrokerRequestId"


# ---------------------------------------------------------------------------
# Developer SigV4 path (R5.2): no Trusted_Context_Headers → developer-sigv4
# ---------------------------------------------------------------------------


class TestDeveloperSigV4Path:
    """When no Trusted_Context_Headers are present, the caller is a developer
    reaching the Runtime directly over SigV4."""

    def test_empty_headers(self):
        ctx = derive_principal({})
        assert ctx.principal == "developer-sigv4"
        assert ctx.scope == "developer-sigv4"
        assert ctx.broker_request_id is None

    def test_unrelated_headers_ignored(self):
        ctx = derive_principal({
            "Content-Type": "application/json",
            "Authorization": "Bearer some-token",
        })
        assert ctx.principal == "developer-sigv4"
        assert ctx.scope == "developer-sigv4"
        assert ctx.broker_request_id is None


# ---------------------------------------------------------------------------
# CI principal derivation (R5.1)
# ---------------------------------------------------------------------------


class TestCIPrincipal:
    """Gateway-admitted CI caller with mcp/ci-readonly scope."""

    def test_ci_readonly_scope(self):
        ctx = derive_principal({
            _H_PRINCIPAL: "ci-readonly",
            _H_SCOPE: "mcp/ci-readonly",
            _H_BROKER: "broker-abc-123",
        })
        assert ctx.principal == "ci-readonly"
        assert ctx.scope == "mcp/ci-readonly"
        assert ctx.broker_request_id == "broker-abc-123"


# ---------------------------------------------------------------------------
# HPC principal derivation (R5.1)
# ---------------------------------------------------------------------------


class TestHPCPrincipal:
    """Gateway-admitted HPC caller with mcp/hpc-user scope."""

    def test_hpc_user_scope(self):
        ctx = derive_principal({
            _H_PRINCIPAL: "hpc-user",
            _H_SCOPE: "mcp/hpc-user",
            _H_BROKER: "broker-xyz-789",
        })
        assert ctx.principal == "hpc-user"
        assert ctx.scope == "mcp/hpc-user"
        assert ctx.broker_request_id == "broker-xyz-789"


# ---------------------------------------------------------------------------
# Unknown scope → ForbiddenError (R5.4)
# ---------------------------------------------------------------------------


class TestUnknownScope:
    """Default-deny when the scope is not recognized."""

    def test_unknown_scope_raises(self):
        with pytest.raises(ForbiddenError) as exc_info:
            derive_principal({
                _H_PRINCIPAL: "attacker",
                _H_SCOPE: "mcp/admin-all",
            })
        assert exc_info.value.scope == "mcp/admin-all"

    def test_missing_scope_with_principal_raises(self):
        """Principal header present but scope header absent → ForbiddenError."""
        with pytest.raises(ForbiddenError) as exc_info:
            derive_principal({
                _H_PRINCIPAL: "some-principal",
            })
        assert exc_info.value.scope == ""

    def test_empty_scope_raises(self):
        with pytest.raises(ForbiddenError) as exc_info:
            derive_principal({
                _H_PRINCIPAL: "some-principal",
                _H_SCOPE: "",
            })
        assert exc_info.value.scope == ""


# ---------------------------------------------------------------------------
# Case-insensitive header lookup
# ---------------------------------------------------------------------------


class TestCaseInsensitiveHeaders:
    """HTTP headers are case-insensitive — the middleware must handle any casing."""

    def test_all_lowercase_headers(self):
        ctx = derive_principal({
            "x-amzn-bedrock-agentcore-runtime-custom-principal": "ci-readonly",
            "x-amzn-bedrock-agentcore-runtime-custom-scope": "mcp/ci-readonly",
            "x-amzn-bedrock-agentcore-runtime-custom-brokerrequestid": "req-1",
        })
        assert ctx.principal == "ci-readonly"
        assert ctx.scope == "mcp/ci-readonly"
        assert ctx.broker_request_id == "req-1"

    def test_all_uppercase_headers(self):
        ctx = derive_principal({
            "X-AMZN-BEDROCK-AGENTCORE-RUNTIME-CUSTOM-PRINCIPAL": "hpc-user",
            "X-AMZN-BEDROCK-AGENTCORE-RUNTIME-CUSTOM-SCOPE": "mcp/hpc-user",
            "X-AMZN-BEDROCK-AGENTCORE-RUNTIME-CUSTOM-BROKERREQUESTID": "req-2",
        })
        assert ctx.principal == "hpc-user"
        assert ctx.scope == "mcp/hpc-user"
        assert ctx.broker_request_id == "req-2"

    def test_mixed_case_headers(self):
        ctx = derive_principal({
            "x-Amzn-Bedrock-AgentCore-Runtime-Custom-PRINCIPAL": "ci-readonly",
            "x-amzn-BEDROCK-agentcore-RUNTIME-custom-SCOPE": "mcp/ci-readonly",
        })
        assert ctx.principal == "ci-readonly"
        assert ctx.scope == "mcp/ci-readonly"
        assert ctx.broker_request_id is None


# ---------------------------------------------------------------------------
# broker_request_id propagation
# ---------------------------------------------------------------------------


class TestBrokerRequestIdPropagation:
    """broker_request_id is optional — may be present, absent, or empty."""

    def test_present(self):
        ctx = derive_principal({
            _H_PRINCIPAL: "ci-readonly",
            _H_SCOPE: "mcp/ci-readonly",
            _H_BROKER: "abc-123",
        })
        assert ctx.broker_request_id == "abc-123"

    def test_absent(self):
        ctx = derive_principal({
            _H_PRINCIPAL: "hpc-user",
            _H_SCOPE: "mcp/hpc-user",
        })
        assert ctx.broker_request_id is None

    def test_empty_string_treated_as_none(self):
        ctx = derive_principal({
            _H_PRINCIPAL: "ci-readonly",
            _H_SCOPE: "mcp/ci-readonly",
            _H_BROKER: "",
        })
        assert ctx.broker_request_id is None


# ---------------------------------------------------------------------------
# KNOWN_SCOPES completeness
# ---------------------------------------------------------------------------


class TestKnownScopes:
    """Verify KNOWN_SCOPES contains exactly the expected values."""

    def test_expected_scopes(self):
        assert KNOWN_SCOPES == frozenset({
            "mcp/ci-readonly",
            "mcp/hpc-user",
            "developer-sigv4",
        })


# ---------------------------------------------------------------------------
# PrincipalContext is frozen
# ---------------------------------------------------------------------------


class TestPrincipalContextImmutability:
    """PrincipalContext is a frozen dataclass — no accidental mutation."""

    def test_frozen(self):
        ctx = PrincipalContext(
            principal="ci-readonly",
            scope="mcp/ci-readonly",
            broker_request_id="abc",
        )
        with pytest.raises(AttributeError):
            ctx.principal = "hacked"  # type: ignore[misc]
