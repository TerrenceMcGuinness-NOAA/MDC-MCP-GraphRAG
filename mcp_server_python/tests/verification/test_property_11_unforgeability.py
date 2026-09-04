"""Property 11 — Unforgeability of Trusted_Context_Headers.

For any client-supplied value of a Trusted_Context_Header, the value observed
by the MCP_Server equals the interceptor-derived value (design §8, Property 11).

This test verifies the end-to-end chain: interceptor Lambda → MCP_Server middleware.

Chain under test
----------------
1. A client sends a Gateway request with **forged** Custom-* headers alongside
   a valid JWT whose ``scope`` claim is ``mcp/ci-readonly``.
2. The Request_Interceptor (``infrastructure/cdk/lambda/gateway_interceptor/index.py``)
   strips all ``X-Amzn-Bedrock-AgentCore-Runtime-Custom-*`` headers and injects its
   own based on the JWT claims.
3. The MCP_Server middleware (``src/auth/middleware.py::derive_principal``) reads those
   headers and produces a ``PrincipalContext``.
4. Property 11 holds if the ``PrincipalContext`` contains the interceptor-derived values
   and **never** the forged ones.

Run:
    cd mcp_server_python
    python -m pytest tests/verification/test_property_11_unforgeability.py -v

Requirements: R4.3; Property 11.
"""
from __future__ import annotations

import base64
import json
import os
import sys

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap — the interceptor Lambda lives outside mcp_server_python
# ---------------------------------------------------------------------------

_INTERCEPTOR_DIR = os.path.join(
    os.path.dirname(__file__),
    os.pardir, os.pardir, os.pardir,
    "infrastructure", "cdk", "lambda", "gateway_interceptor",
)
_INTERCEPTOR_DIR = os.path.normpath(_INTERCEPTOR_DIR)
if _INTERCEPTOR_DIR not in sys.path:
    sys.path.insert(0, _INTERCEPTOR_DIR)

import index as interceptor  # noqa: E402

from src.auth.middleware import PrincipalContext, derive_principal  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_jwt(claims: dict) -> str:
    """Create a structurally valid JWT (header.payload.signature) for testing.

    The interceptor performs unverified decode (the Gateway already validated the
    signature), so we only need a correctly base64url-encoded payload section.
    """
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "RS256", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps(claims).encode()
    ).rstrip(b"=").decode()
    signature = base64.urlsafe_b64encode(b"fakesig").rstrip(b"=").decode()
    return f"{header}.{payload}.{signature}"


def _gateway_event(token: str, extra_headers: dict[str, str] | None = None) -> dict:
    """Build a Gateway REQUEST interceptor event.

    Parameters
    ----------
    token : str
        The JWT to place in the Authorization header.
    extra_headers : dict, optional
        Additional headers the *attacker* injects (forged Custom-* values).
    """
    headers: dict[str, str] = {"Authorization": f"Bearer {token}"}
    if extra_headers:
        headers.update(extra_headers)
    body_json = json.dumps({"jsonrpc": "2.0", "method": "tools/list", "id": 1})
    return {
        "http": {
            "gatewayRequest": {
                "path": "/mdc-mcp-rag/invocations",
                "method": "POST",
                "headers": headers,
                "body": base64.b64encode(body_json.encode()).decode(),
            }
        }
    }


class _Ctx:
    """Minimal Lambda context stub."""
    function_name = "gateway_interceptor"
    aws_request_id = "req-prop11-001"


def _run_chain(
    jwt_claims: dict,
    forged_headers: dict[str, str],
) -> tuple[dict[str, str], PrincipalContext]:
    """Run the full interceptor → middleware chain.

    Returns the output headers from the interceptor AND the PrincipalContext
    derived by the MCP_Server middleware, so tests can assert on both.
    """
    token = _make_jwt(jwt_claims)
    event = _gateway_event(token, extra_headers=forged_headers)
    resp = interceptor.handler(event, _Ctx())

    # The interceptor must have passed the request through (not denied it).
    assert "transformedGatewayRequest" in resp.get("http", {}), (
        "Interceptor unexpectedly denied the request"
    )
    out_headers = resp["http"]["transformedGatewayRequest"]["headers"]

    # Feed the interceptor's output headers into the MCP_Server middleware.
    ctx = derive_principal(out_headers)
    return out_headers, ctx


# ---------------------------------------------------------------------------
# The three Trusted_Context_Header names (canonical casing)
# ---------------------------------------------------------------------------

H_PRINCIPAL = interceptor.HEADER_PRINCIPAL
H_SCOPE = interceptor.HEADER_SCOPE
H_BROKER = interceptor.HEADER_BROKER_REQUEST_ID


# ---------------------------------------------------------------------------
# Tests — Property 11: individual header forgery
# ---------------------------------------------------------------------------


class TestForgedPrincipalHeader:
    """A client forges the Principal header; the interceptor overwrites it."""

    def test_forged_principal_replaced_by_interceptor(self):
        """Forged 'admin-superuser' principal → interceptor writes 'ci-readonly'."""
        _, ctx = _run_chain(
            jwt_claims={"scope": "mcp/ci-readonly", "broker_request_id": "br-1"},
            forged_headers={H_PRINCIPAL: "admin-superuser"},
        )
        assert ctx.principal == "ci-readonly", (
            "MCP_Server saw the forged principal instead of the interceptor-derived one"
        )
        assert ctx.scope == "mcp/ci-readonly"

    def test_forged_hpc_principal_when_scope_is_ci(self):
        """Forged 'hpc-user' principal but the JWT has ci-readonly scope."""
        _, ctx = _run_chain(
            jwt_claims={"scope": "mcp/ci-readonly"},
            forged_headers={H_PRINCIPAL: "hpc-user"},
        )
        assert ctx.principal == "ci-readonly"
        assert ctx.scope == "mcp/ci-readonly"


class TestForgedScopeHeader:
    """A client forges the Scope header; the interceptor overwrites it."""

    def test_forged_scope_escalation_denied(self):
        """Forged 'mcp/hpc-user' scope but JWT is ci-readonly → ci-readonly wins."""
        _, ctx = _run_chain(
            jwt_claims={"scope": "mcp/ci-readonly", "broker_request_id": "br-2"},
            forged_headers={H_SCOPE: "mcp/hpc-user"},
        )
        assert ctx.scope == "mcp/ci-readonly", (
            "MCP_Server saw the forged scope (privilege escalation!)"
        )
        assert ctx.principal == "ci-readonly"

    def test_forged_developer_scope_denied(self):
        """Forged 'developer-sigv4' scope but JWT is ci-readonly → ci-readonly wins."""
        _, ctx = _run_chain(
            jwt_claims={"scope": "mcp/ci-readonly"},
            forged_headers={H_SCOPE: "developer-sigv4"},
        )
        assert ctx.scope == "mcp/ci-readonly"
        assert ctx.principal == "ci-readonly"


class TestForgedBrokerRequestId:
    """A client forges the BrokerRequestId header; the interceptor overwrites it."""

    def test_forged_broker_id_replaced(self):
        """Forged broker ID → interceptor writes the JWT claim's value."""
        _, ctx = _run_chain(
            jwt_claims={
                "scope": "mcp/ci-readonly",
                "broker_request_id": "real-broker-abc",
            },
            forged_headers={H_BROKER: "forged-broker-xyz"},
        )
        assert ctx.broker_request_id == "real-broker-abc", (
            "MCP_Server saw the forged broker_request_id"
        )

    def test_forged_broker_id_with_no_jwt_claim(self):
        """JWT has no broker_request_id claim; forged header has one → still None."""
        headers, ctx = _run_chain(
            jwt_claims={"scope": "mcp/ci-readonly"},
            forged_headers={H_BROKER: "forged-broker-sneaky"},
        )
        # The interceptor falls back to the x-broker-request-id header (not the
        # Custom-* one) when the JWT claim is absent. Since we didn't supply that
        # fallback header, the value is empty string → middleware treats as None.
        assert ctx.broker_request_id is None or ctx.broker_request_id != "forged-broker-sneaky", (
            "MCP_Server saw the forged broker_request_id despite no JWT claim"
        )


# ---------------------------------------------------------------------------
# Tests — Property 11: all three headers forged simultaneously
# ---------------------------------------------------------------------------


class TestAllHeadersForgedSimultaneously:
    """A client forges ALL three Trusted_Context_Headers at once."""

    def test_all_forged_headers_overwritten(self):
        """All three forged values → interceptor overwrites all three."""
        headers, ctx = _run_chain(
            jwt_claims={
                "scope": "mcp/ci-readonly",
                "broker_request_id": "real-br-999",
            },
            forged_headers={
                H_PRINCIPAL: "forged-admin",
                H_SCOPE: "mcp/hpc-user",
                H_BROKER: "forged-br-000",
            },
        )
        # Verify interceptor output headers
        assert headers[H_PRINCIPAL] == "ci-readonly"
        assert headers[H_SCOPE] == "mcp/ci-readonly"
        assert headers[H_BROKER] == "real-br-999"

        # Verify MCP_Server middleware derived the correct principal
        assert ctx.principal == "ci-readonly"
        assert ctx.scope == "mcp/ci-readonly"
        assert ctx.broker_request_id == "real-br-999"

    def test_hpc_scope_all_forged(self):
        """HPC JWT with all three headers forged to CI values → HPC wins."""
        headers, ctx = _run_chain(
            jwt_claims={
                "scope": "mcp/hpc-user",
                "broker_request_id": "hpc-br-42",
            },
            forged_headers={
                H_PRINCIPAL: "ci-readonly",
                H_SCOPE: "mcp/ci-readonly",
                H_BROKER: "forged-ci-br",
            },
        )
        assert ctx.principal == "hpc-user"
        assert ctx.scope == "mcp/hpc-user"
        assert ctx.broker_request_id == "hpc-br-42"


# ---------------------------------------------------------------------------
# Tests — arbitrary Custom-* headers are stripped entirely
# ---------------------------------------------------------------------------


class TestArbitraryCustomHeadersStripped:
    """Client-injected Custom-* headers that are NOT Trusted_Context_Headers
    must be stripped by the interceptor and never reach the middleware."""

    def test_custom_evil_header_stripped(self):
        """A forged 'Custom-Evil' header must not survive the interceptor."""
        evil_header = "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Evil"
        headers, ctx = _run_chain(
            jwt_claims={"scope": "mcp/ci-readonly"},
            forged_headers={evil_header: "injected-malice"},
        )
        # The evil header must not be present in the output.
        for key in headers:
            if key.lower() == evil_header.lower():
                pytest.fail(f"Forged header {evil_header!r} survived the interceptor")

        # The legitimate principal derivation must still work.
        assert ctx.principal == "ci-readonly"
        assert ctx.scope == "mcp/ci-readonly"

    def test_multiple_arbitrary_custom_headers_stripped(self):
        """Several forged Custom-* headers — all stripped."""
        forged = {
            "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Token": "stolen-token",
            "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Role": "admin",
            "x-amzn-bedrock-agentcore-runtime-custom-bypass": "true",
        }
        headers, ctx = _run_chain(
            jwt_claims={"scope": "mcp/ci-readonly", "broker_request_id": "br-clean"},
            forged_headers=forged,
        )
        # Only the three Trusted_Context_Headers with the Custom- prefix should survive.
        custom_prefix = interceptor._CUSTOM_HEADER_PREFIX
        surviving_custom = {
            k for k in headers if k.lower().startswith(custom_prefix)
        }
        expected_custom = {H_PRINCIPAL, H_SCOPE, H_BROKER}
        assert surviving_custom == expected_custom, (
            f"Unexpected custom headers survived: "
            f"{surviving_custom - expected_custom}"
        )

        # Middleware must see clean values.
        assert ctx.principal == "ci-readonly"
        assert ctx.broker_request_id == "br-clean"

    def test_forged_custom_plus_legitimate_non_custom_headers(self):
        """Non-Custom-* headers (Content-Type, etc.) pass through; Custom-* are stripped."""
        headers, ctx = _run_chain(
            jwt_claims={"scope": "mcp/hpc-user"},
            forged_headers={
                "Content-Type": "application/json",
                "X-Request-Id": "req-abc",
                "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Bypass": "yes",
            },
        )
        # Non-custom headers survive.
        assert "Content-Type" in headers or "content-type" in {k.lower() for k in headers}
        # Custom-Bypass must be gone.
        for key in headers:
            if "custom-bypass" in key.lower():
                pytest.fail("Custom-Bypass header survived the interceptor")

        assert ctx.principal == "hpc-user"


# ---------------------------------------------------------------------------
# Tests — chain integrity: interceptor output is valid middleware input
# ---------------------------------------------------------------------------


class TestChainIntegrity:
    """Verify that the interceptor's output header format is correctly consumed
    by derive_principal — i.e., the two components agree on header names and
    value semantics."""

    def test_header_names_match_middleware_expectations(self):
        """The interceptor's injected header names must match what the middleware
        looks for (case-insensitive)."""
        headers, ctx = _run_chain(
            jwt_claims={"scope": "mcp/ci-readonly", "broker_request_id": "chain-br"},
            forged_headers={},
        )
        # The middleware found the principal (not developer-sigv4 default).
        assert ctx.principal != "developer-sigv4", (
            "Middleware fell through to developer default — header name mismatch"
        )
        assert ctx.principal == "ci-readonly"
        assert ctx.scope == "mcp/ci-readonly"
        assert ctx.broker_request_id == "chain-br"

    def test_no_forged_headers_baseline(self):
        """Without any forgery, the chain produces the expected result — baseline."""
        headers, ctx = _run_chain(
            jwt_claims={
                "scope": "mcp/hpc-user",
                "broker_request_id": "baseline-br-1",
            },
            forged_headers={},
        )
        assert ctx.principal == "hpc-user"
        assert ctx.scope == "mcp/hpc-user"
        assert ctx.broker_request_id == "baseline-br-1"
