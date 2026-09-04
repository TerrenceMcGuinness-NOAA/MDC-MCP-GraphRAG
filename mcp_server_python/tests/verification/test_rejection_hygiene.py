"""Task 6.5 — Rejection hygiene.

Missing, expired, wrong-audience, and wrong-scope tokens all yield rejection
with no claim values or tool metadata in the response body (R2.2).

What is testable here vs at deploy time
----------------------------------------
The Gateway itself handles JWT signature validation, expiry checks, audience
matching, and scope validation — those produce HTTP 401 **before** the
interceptor Lambda runs. We cannot test the actual Gateway's JWT authorizer in
unit tests (it is an AWS-managed service).

What we **can** test:

1. The **interceptor Lambda** rejects requests it cannot derive a principal from
   (missing, empty, malformed, or unrecognized tokens) with HTTP 403 via
   ``transformedGatewayResponse``.
2. The **403 response body** is clean: it contains only ``{"error": "..."}`` and
   never leaks claim values (``scope``, ``sub``, ``aud``, ``iss``) or tool
   metadata (``tool``, ``tools``).
3. The **MCP_Server middleware** raises ``ForbiddenError`` on unrecognized
   scopes (default-deny).

Real 401 responses (expired, wrong-audience, wrong-signature) are handled by
the Gateway's ``customJWTAuthorizer`` before the interceptor runs. Those are
verified at deploy time as part of the live integration test described in
``docs/reports/mcp-external-access-gateway-verification.md``.

Run::

    cd /mdc-mcp-rag/eib-mcp-rag-server
    python -m pytest mcp_server_python/tests/verification/test_rejection_hygiene.py -v

Requirements: R2.2; Property 11 (unforgeability complement — rejection side).
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

from src.auth.middleware import ForbiddenError, derive_principal  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Claim / tool metadata keys that must NEVER appear in a rejection body.
_SENSITIVE_KEYS = frozenset({
    "scope", "sub", "aud", "iss", "client_id", "exp", "iat",
    "token_use", "auth_time", "cognito:groups",
    "tool", "tools", "tool_name", "method", "params",
})


def _make_jwt(claims: dict) -> str:
    """Create a structurally valid JWT (header.payload.signature) for testing.

    The interceptor performs unverified decode (the Gateway already validated
    the signature), so we only need a correctly base64url-encoded payload.
    """
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "RS256", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps(claims).encode()
    ).rstrip(b"=").decode()
    signature = base64.urlsafe_b64encode(b"fakesig").rstrip(b"=").decode()
    return f"{header}.{payload}.{signature}"


def _gateway_event(
    headers: dict[str, str] | None = None,
) -> dict:
    """Build a Gateway REQUEST interceptor event with the given headers.

    Parameters
    ----------
    headers : dict, optional
        Request headers. If ``None``, the event is sent with no headers at all.
    """
    body_json = json.dumps({"jsonrpc": "2.0", "method": "tools/list", "id": 1})
    return {
        "http": {
            "gatewayRequest": {
                "path": "/mdc-mcp-rag/invocations",
                "method": "POST",
                "headers": headers or {},
                "body": base64.b64encode(body_json.encode()).decode(),
            }
        }
    }


class _Ctx:
    """Minimal Lambda context stub."""
    function_name = "gateway_interceptor"
    aws_request_id = "req-rejection-hygiene"


def _assert_deny_response(result: dict, expected_code: int = 403) -> dict:
    """Assert the interceptor returned a ``transformedGatewayResponse`` deny
    and return the decoded JSON body for further assertion.

    Parameters
    ----------
    result : dict
        The interceptor handler return value.
    expected_code : int
        The expected HTTP status code.

    Returns
    -------
    dict
        The decoded body JSON.
    """
    http = result.get("http", {})
    assert "transformedGatewayResponse" in http, (
        "Expected a deny response (transformedGatewayResponse), but interceptor "
        "returned a transformedGatewayRequest (pass-through). Full result: "
        f"{json.dumps(result, indent=2)}"
    )
    resp = http["transformedGatewayResponse"]
    assert resp["statusCode"] == expected_code, (
        f"Expected HTTP {expected_code}, got {resp['statusCode']}"
    )
    # Decode the base64-encoded body.
    body_raw = base64.b64decode(resp["body"])
    body = json.loads(body_raw)
    return body


def _assert_body_clean(body: dict) -> None:
    """Assert the rejection body contains no claim values or tool metadata.

    The body should contain ONLY ``{"error": "<reason>"}`` — nothing else.
    """
    # Must have "error" key.
    assert "error" in body, f"Rejection body missing 'error' key: {body}"

    # Must not contain any sensitive keys.
    leaked = _SENSITIVE_KEYS & set(body.keys())
    assert not leaked, (
        f"Rejection body leaks sensitive keys: {leaked}. Body: {body}"
    )

    # Must contain ONLY the "error" key — nothing extra.
    assert set(body.keys()) == {"error"}, (
        f"Rejection body has unexpected extra keys: "
        f"{set(body.keys()) - {'error'}}. Body: {body}"
    )


# ---------------------------------------------------------------------------
# Tests — Interceptor rejection scenarios
# ---------------------------------------------------------------------------


class TestInterceptorNoAuthorization:
    """Test 1: No Authorization header → interceptor cannot derive scope → 403."""

    def test_no_auth_header_returns_403(self):
        """Request with no Authorization header → 403 deny."""
        event = _gateway_event(headers={"Content-Type": "application/json"})
        result = interceptor.handler(event, _Ctx())
        body = _assert_deny_response(result, 403)
        _assert_body_clean(body)

    def test_empty_headers_returns_403(self):
        """Request with completely empty headers → 403 deny."""
        event = _gateway_event(headers={})
        result = interceptor.handler(event, _Ctx())
        body = _assert_deny_response(result, 403)
        _assert_body_clean(body)


class TestInterceptorEmptyBearerToken:
    """Test 2: Empty Bearer token → decode yields {} → no scope → 403."""

    def test_empty_bearer_token_returns_403(self):
        """Authorization: Bearer (empty) → 403."""
        event = _gateway_event(headers={"Authorization": "Bearer "})
        result = interceptor.handler(event, _Ctx())
        body = _assert_deny_response(result, 403)
        _assert_body_clean(body)

    def test_bare_bearer_keyword_returns_403(self):
        """Authorization: Bearer (no space, no token) → 403."""
        event = _gateway_event(headers={"Authorization": "Bearer"})
        result = interceptor.handler(event, _Ctx())
        body = _assert_deny_response(result, 403)
        _assert_body_clean(body)


class TestInterceptorMalformedJWT:
    """Test 3: Malformed JWT (wrong number of parts) → decode returns {} → 403."""

    def test_two_part_jwt_returns_403(self):
        """JWT with only header.payload (no signature) → malformed → 403."""
        header = base64.urlsafe_b64encode(
            json.dumps({"alg": "RS256"}).encode()
        ).rstrip(b"=").decode()
        payload = base64.urlsafe_b64encode(
            json.dumps({"scope": "mcp/ci-readonly"}).encode()
        ).rstrip(b"=").decode()
        two_part_token = f"{header}.{payload}"
        event = _gateway_event(headers={"Authorization": f"Bearer {two_part_token}"})
        result = interceptor.handler(event, _Ctx())
        body = _assert_deny_response(result, 403)
        _assert_body_clean(body)

    def test_single_part_token_returns_403(self):
        """Single string (not a JWT at all) → 403."""
        event = _gateway_event(headers={"Authorization": "Bearer not-a-jwt"})
        result = interceptor.handler(event, _Ctx())
        body = _assert_deny_response(result, 403)
        _assert_body_clean(body)

    def test_four_part_token_returns_403(self):
        """JWT with 4 dot-separated parts → _decode_unverified returns {} → 403."""
        event = _gateway_event(
            headers={"Authorization": "Bearer a.b.c.d"}
        )
        result = interceptor.handler(event, _Ctx())
        body = _assert_deny_response(result, 403)
        _assert_body_clean(body)


class TestInterceptorUnrecognizedScope:
    """Test 4: JWT with an unrecognized scope → no match in SCOPE_TO_PRINCIPAL → 403."""

    def test_unknown_scope_returns_403(self):
        """scope 'mcp/admin-nuke' is not in SCOPE_TO_PRINCIPAL → 403."""
        token = _make_jwt({"scope": "mcp/admin-nuke", "sub": "evil-user"})
        event = _gateway_event(headers={"Authorization": f"Bearer {token}"})
        result = interceptor.handler(event, _Ctx())
        body = _assert_deny_response(result, 403)
        _assert_body_clean(body)

    def test_arbitrary_scope_returns_403(self):
        """scope 'openid profile email' (standard OIDC, not MCP) → 403."""
        token = _make_jwt({"scope": "openid profile email"})
        event = _gateway_event(headers={"Authorization": f"Bearer {token}"})
        result = interceptor.handler(event, _Ctx())
        body = _assert_deny_response(result, 403)
        _assert_body_clean(body)

    def test_empty_scope_string_returns_403(self):
        """scope: '' (empty string) → 403."""
        token = _make_jwt({"scope": ""})
        event = _gateway_event(headers={"Authorization": f"Bearer {token}"})
        result = interceptor.handler(event, _Ctx())
        body = _assert_deny_response(result, 403)
        _assert_body_clean(body)


class TestInterceptorNoScopeClaim:
    """Test 5: JWT with no scope claim at all → 403."""

    def test_missing_scope_claim_returns_403(self):
        """JWT payload has no 'scope' field → 403."""
        token = _make_jwt({"sub": "some-user", "aud": "some-audience"})
        event = _gateway_event(headers={"Authorization": f"Bearer {token}"})
        result = interceptor.handler(event, _Ctx())
        body = _assert_deny_response(result, 403)
        _assert_body_clean(body)

    def test_empty_claims_returns_403(self):
        """JWT payload is {} → no scope → 403."""
        token = _make_jwt({})
        event = _gateway_event(headers={"Authorization": f"Bearer {token}"})
        result = interceptor.handler(event, _Ctx())
        body = _assert_deny_response(result, 403)
        _assert_body_clean(body)


class TestRejectionBodyCleanliness:
    """Test 6: Rejection response body contains no claim values or tool metadata.

    This is the core R2.2 assertion: even when the JWT contains rich claims,
    the deny body MUST expose only ``{"error": "<reason>"}``.
    """

    def test_rich_claims_not_leaked_in_403_body(self):
        """JWT with many claims (sub, aud, iss, client_id) but invalid scope.
        None of those claim values appear in the 403 body."""
        token = _make_jwt({
            "sub": "user-12345",
            "aud": "mcp-pool-client-id",
            "iss": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_POOL",
            "client_id": "client-abc-123",
            "scope": "mcp/admin-nuke",
            "exp": 9999999999,
            "iat": 1700000000,
            "token_use": "access",
        })
        event = _gateway_event(headers={"Authorization": f"Bearer {token}"})
        result = interceptor.handler(event, _Ctx())
        body = _assert_deny_response(result, 403)
        _assert_body_clean(body)

        # Additionally verify that the claim VALUES don't appear in the error string.
        error_msg = body["error"]
        for val in ("user-12345", "mcp-pool-client-id", "client-abc-123",
                     "us-east-1_POOL", "mcp/admin-nuke"):
            assert val not in error_msg, (
                f"Claim value {val!r} leaked into error message: {error_msg!r}"
            )

    def test_body_has_only_error_key(self):
        """The denial body must be exactly {"error": "..."} — no extras."""
        token = _make_jwt({"scope": "mcp/unknown-scope"})
        event = _gateway_event(headers={"Authorization": f"Bearer {token}"})
        result = interceptor.handler(event, _Ctx())
        body = _assert_deny_response(result, 403)
        assert list(body.keys()) == ["error"]

    def test_no_tool_metadata_in_body(self):
        """Even when the request body is a tools/call JSON-RPC payload, the
        reject response does not echo tool information."""
        body_json = json.dumps({
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": "search_documentation"},
            "id": 42,
        })
        event = {
            "http": {
                "gatewayRequest": {
                    "path": "/mdc-mcp-rag/invocations",
                    "method": "POST",
                    "headers": {"Authorization": "Bearer invalid.not.jwt"},
                    "body": base64.b64encode(body_json.encode()).decode(),
                }
            }
        }
        result = interceptor.handler(event, _Ctx())
        body = _assert_deny_response(result, 403)
        _assert_body_clean(body)
        assert "search_documentation" not in body["error"]
        assert "tools/call" not in body["error"]


# ---------------------------------------------------------------------------
# Test — Middleware: ForbiddenError on unknown scope (R5.4)
# ---------------------------------------------------------------------------


class TestMiddlewareForbiddenError:
    """Test 7: derive_principal raises ForbiddenError for unrecognized scopes.

    This is the server-side defense-in-depth: even if an unrecognized scope
    somehow bypasses the Gateway and the interceptor, the middleware rejects it.
    """

    def test_unknown_scope_raises_forbidden(self):
        """Unrecognized scope in Custom-Scope header → ForbiddenError."""
        with pytest.raises(ForbiddenError) as exc_info:
            derive_principal({
                "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Principal": "attacker",
                "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Scope": "mcp/admin-nuke",
            })
        assert exc_info.value.scope == "mcp/admin-nuke"

    def test_empty_scope_raises_forbidden(self):
        """Empty-string scope in Custom-Scope header → ForbiddenError."""
        with pytest.raises(ForbiddenError) as exc_info:
            derive_principal({
                "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Principal": "someone",
                "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Scope": "",
            })
        assert exc_info.value.scope == ""

    def test_none_scope_raises_forbidden(self):
        """Principal header present but Scope header absent → scope is None →
        ForbiddenError (default-deny)."""
        with pytest.raises(ForbiddenError):
            derive_principal({
                "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Principal": "someone",
                # No Scope header — _get_header returns None, which is not in KNOWN_SCOPES.
            })

    def test_forbidden_error_message_does_not_leak_sensitive_data(self):
        """ForbiddenError message contains the scope but not claim/token data."""
        with pytest.raises(ForbiddenError) as exc_info:
            derive_principal({
                "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Principal": "secret-sub",
                "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Scope": "mcp/evil",
            })
        msg = str(exc_info.value)
        # Should mention the bad scope for diagnostics.
        assert "mcp/evil" in msg
        # Should NOT contain the principal header value.
        assert "secret-sub" not in msg


# ---------------------------------------------------------------------------
# Test — Interceptor internal error handling
# ---------------------------------------------------------------------------


class TestInterceptorInternalError:
    """Edge case: if the interceptor encounters an unexpected error (e.g.,
    malformed event structure), it returns HTTP 500 — never passes through."""

    def test_missing_http_key_returns_500(self):
        """Event without 'http' key → interceptor catches exception → 500."""
        result = interceptor.handler({"not_http": {}}, _Ctx())
        body = _assert_deny_response(result, 500)
        _assert_body_clean(body)

    def test_missing_gateway_request_returns_500(self):
        """Event with 'http' but no 'gatewayRequest' → 500."""
        result = interceptor.handler({"http": {"other": "data"}}, _Ctx())
        body = _assert_deny_response(result, 500)
        _assert_body_clean(body)
