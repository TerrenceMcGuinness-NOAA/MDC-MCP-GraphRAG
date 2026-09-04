"""Unit tests for the Gateway Request Interceptor.

Task 4.4: Ensure no code path logs the Authorization header or any token
value; add a test asserting this.

Task 4.7: Unit-test the handler against the documented `http` interceptor
payload shape (base64 body, `/{targetName}/invocations` path).
Requirements: R4.1, R4.3, R4.4, R4.6.

Run: python -m pytest infrastructure/cdk/lambda/gateway_interceptor/test_index.py -v
"""

import base64
import io
import json
import logging
import os
import re
import sys
import unittest

# Ensure the interceptor module is importable.
sys.path.insert(0, os.path.dirname(__file__))
import index  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_test_jwt(claims):
    """Create a fake JWT with the given payload claims (no signature verification in handler)."""
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "RS256", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps(claims).encode()
    ).rstrip(b"=").decode()
    signature = base64.urlsafe_b64encode(b"fakesig").rstrip(b"=").decode()
    return f"{header}.{payload}.{signature}"


# A distinctive token value that is easy to search for in log output.
_CI_TOKEN = _make_test_jwt({
    "scope": "mcp/ci-readonly",
    "broker_request_id": "br-42",
    "sub": "ci-client",
})

# A token with an unrecognized scope — triggers the 403 path.
_BAD_SCOPE_TOKEN = _make_test_jwt({
    "scope": "mcp/admin-nuke",
    "sub": "bad-actor",
})

# A deliberately malformed token (only two parts, no payload).
_MALFORMED_TOKEN = "eyJhbGciOiJSUzI1NiJ9.INVALID"


def _gateway_event(token=None, extra_headers=None):
    """Build a minimal Gateway REQUEST interceptor event."""
    headers = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
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
    aws_request_id = "req-test-001"


def _invoke_capturing_logs(event):
    """Invoke the handler and return (response, combined_log_output)."""
    # Capture everything the handler's logger emits.
    buf = io.StringIO()
    handler_logger = logging.getLogger(index.__name__)
    stream_handler = logging.StreamHandler(buf)
    stream_handler.setLevel(logging.DEBUG)  # capture ALL levels
    handler_logger.addHandler(stream_handler)
    try:
        resp = index.handler(event, _Ctx())
    finally:
        handler_logger.removeHandler(stream_handler)
    return resp, buf.getvalue()


# ---------------------------------------------------------------------------
# Tests — R4.4: no code path logs the Authorization header or token value
# ---------------------------------------------------------------------------

class TestNoTokenInLogs(unittest.TestCase):
    """R4.4 — the Request_Interceptor SHALL NOT log the inbound Authorization
    header or any raw token value."""

    def test_no_authorization_header_in_logs(self):
        """Happy path: valid CI-scoped JWT. Token value MUST NOT appear in logs."""
        resp, logs = _invoke_capturing_logs(_gateway_event(token=_CI_TOKEN))

        # Sanity: the call succeeded (interceptor returned transformed request).
        self.assertIn("transformedGatewayRequest", resp.get("http", {}))

        # The raw token string must never appear in any log line.
        self.assertNotIn(
            _CI_TOKEN, logs,
            "Raw token value leaked into log output on the happy path",
        )
        # "Bearer <token>" must not appear either.
        self.assertNotIn(
            f"Bearer {_CI_TOKEN}", logs,
            "'Bearer <token>' string leaked into log output",
        )
        # The Authorization header value must not appear.
        self.assertNotIn(
            "Authorization", logs,
            "Authorization header name logged (risk of value correlation)",
        )

    def test_no_token_in_error_logs(self):
        """Malformed JWT (2 parts). Token value MUST NOT appear in warning/error logs."""
        resp, logs = _invoke_capturing_logs(_gateway_event(token=_MALFORMED_TOKEN))

        # The malformed token triggers JWT_DECODE_FAILED + NO_RECOGNIZED_SCOPE,
        # ending in a 403.
        self.assertIn("transformedGatewayResponse", resp.get("http", {}))
        self.assertEqual(
            resp["http"]["transformedGatewayResponse"]["statusCode"], 403,
        )

        # The raw token value must never appear in any log line.
        self.assertNotIn(
            _MALFORMED_TOKEN, logs,
            "Malformed token value leaked into error/warning logs",
        )
        # Partial token segments must not appear either.
        for part in _MALFORMED_TOKEN.split("."):
            if len(part) > 8:  # skip very short segments that could match legitimately
                self.assertNotIn(
                    part, logs,
                    f"Token segment '{part[:16]}...' leaked into logs",
                )

    def test_no_token_in_403_response(self):
        """Unrecognized scope → 403. Response body MUST NOT contain token material."""
        resp, logs = _invoke_capturing_logs(_gateway_event(token=_BAD_SCOPE_TOKEN))

        self.assertIn("transformedGatewayResponse", resp.get("http", {}))
        gateway_resp = resp["http"]["transformedGatewayResponse"]
        self.assertEqual(gateway_resp["statusCode"], 403)

        # Decode the base64 response body and check for token leakage.
        body_raw = base64.b64decode(gateway_resp["body"]).decode()
        self.assertNotIn(
            _BAD_SCOPE_TOKEN, body_raw,
            "Token value leaked into 403 response body",
        )
        # The response should be a simple error, not contain JWT claims.
        body_json = json.loads(body_raw)
        self.assertIn("error", body_json)
        self.assertNotIn("scope", body_json)
        self.assertNotIn("sub", body_json)

        # Logs must also be clean.
        self.assertNotIn(
            _BAD_SCOPE_TOKEN, logs,
            "Token value leaked into logs on the 403 path",
        )

    def test_no_authorization_logging_in_source(self):
        """Static source analysis: no log statement references authorization/token/bearer
        in a way that would log the header value."""
        source_path = os.path.join(os.path.dirname(__file__), "index.py")
        with open(source_path) as f:
            source = f.read()

        # Pattern: log.(info|warning|error|debug|critical|exception) followed by
        # any reference to authorization, token, or bearer in the format string.
        # This catches e.g. log.info("auth header: %s", headers["authorization"]).
        dangerous_pattern = re.compile(
            r'log\.\s*(?:info|warning|error|debug|critical|exception)\s*\('
            r'[^)]*(?:authorization|\.token|bearer)',
            re.IGNORECASE,
        )

        matches = dangerous_pattern.findall(source)
        self.assertEqual(
            matches, [],
            f"Source contains log statements that may leak token material: {matches}",
        )



# ---------------------------------------------------------------------------
# Tests — Task 4.7 / R4.1: handler against documented http interceptor payload
# ---------------------------------------------------------------------------

class TestHandlerHappyPath(unittest.TestCase):
    """R4.1 — REQUEST interceptor derives principal from scope, injects
    Trusted_Context_Headers, and passes body through unchanged."""

    def test_ci_readonly_scope(self):
        """Valid JWT with mcp/ci-readonly → principal ci-readonly, correct headers."""
        token = _make_test_jwt({
            "scope": "mcp/ci-readonly",
            "broker_request_id": "br-ci-99",
        })
        event = _gateway_event(token=token)
        resp = index.handler(event, _Ctx())

        self.assertIn("transformedGatewayRequest", resp.get("http", {}))
        out_headers = resp["http"]["transformedGatewayRequest"]["headers"]

        self.assertEqual(
            out_headers[index.HEADER_PRINCIPAL], "ci-readonly",
            "Principal should be ci-readonly for mcp/ci-readonly scope",
        )
        self.assertEqual(
            out_headers[index.HEADER_SCOPE], "mcp/ci-readonly",
        )
        self.assertEqual(
            out_headers[index.HEADER_BROKER_REQUEST_ID], "br-ci-99",
        )

    def test_hpc_user_scope(self):
        """Valid JWT with mcp/hpc-user → principal hpc-user."""
        token = _make_test_jwt({
            "scope": "mcp/hpc-user",
            "broker_request_id": "br-hpc-01",
        })
        event = _gateway_event(token=token)
        resp = index.handler(event, _Ctx())

        out_headers = resp["http"]["transformedGatewayRequest"]["headers"]
        self.assertEqual(out_headers[index.HEADER_PRINCIPAL], "hpc-user")
        self.assertEqual(out_headers[index.HEADER_SCOPE], "mcp/hpc-user")

    def test_interceptor_output_version(self):
        """Response envelope includes interceptorOutputVersion 1.0."""
        token = _make_test_jwt({"scope": "mcp/ci-readonly"})
        resp = index.handler(_gateway_event(token=token), _Ctx())
        self.assertEqual(resp["interceptorOutputVersion"], "1.0")


class TestHandlerDeny(unittest.TestCase):
    """R4.6 — handler returns 403 via transformedGatewayResponse when no
    principal can be derived."""

    def test_no_recognized_scope_returns_403(self):
        """JWT has scope but not a recognized one → HTTP 403."""
        token = _make_test_jwt({"scope": "mcp/unknown-scope"})
        resp = index.handler(_gateway_event(token=token), _Ctx())

        gw_resp = resp["http"]["transformedGatewayResponse"]
        self.assertEqual(gw_resp["statusCode"], 403)
        body = json.loads(base64.b64decode(gw_resp["body"]))
        self.assertIn("error", body)

    def test_missing_authorization_header_returns_403(self):
        """No Authorization header at all → no token → no scope → 403."""
        event = _gateway_event(token=None)
        resp = index.handler(event, _Ctx())

        gw_resp = resp["http"]["transformedGatewayResponse"]
        self.assertEqual(gw_resp["statusCode"], 403)

    def test_malformed_jwt_two_parts_returns_403(self):
        """Malformed JWT (only 2 parts) → _decode_unverified returns {} → 403."""
        event = _gateway_event(token="part1.part2")
        resp = index.handler(event, _Ctx())

        gw_resp = resp["http"]["transformedGatewayResponse"]
        self.assertEqual(gw_resp["statusCode"], 403)

    def test_empty_scope_claim_returns_403(self):
        """JWT with empty scope string → no recognized scope → 403."""
        token = _make_test_jwt({"scope": ""})
        resp = index.handler(_gateway_event(token=token), _Ctx())

        gw_resp = resp["http"]["transformedGatewayResponse"]
        self.assertEqual(gw_resp["statusCode"], 403)


class TestHeaderStripping(unittest.TestCase):
    """R4.3 — client-supplied Custom-* headers are overwritten by interceptor."""

    def test_forged_principal_header_is_overwritten(self):
        """A client-supplied X-Amzn-Bedrock-AgentCore-Runtime-Custom-Principal
        MUST be overwritten with the interceptor-derived value."""
        token = _make_test_jwt({"scope": "mcp/ci-readonly"})
        forged_headers = {
            "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Principal": "forged-admin",
            "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Scope": "mcp/hpc-user",
            "X-Amzn-Bedrock-AgentCore-Runtime-Custom-BrokerRequestId": "forged-id",
        }
        event = _gateway_event(token=token, extra_headers=forged_headers)
        resp = index.handler(event, _Ctx())

        out_headers = resp["http"]["transformedGatewayRequest"]["headers"]
        # Interceptor-derived values win, not the forged ones.
        self.assertEqual(out_headers[index.HEADER_PRINCIPAL], "ci-readonly")
        self.assertEqual(out_headers[index.HEADER_SCOPE], "mcp/ci-readonly")
        self.assertNotEqual(out_headers[index.HEADER_BROKER_REQUEST_ID], "forged-id")

    def test_all_custom_prefix_headers_are_stripped(self):
        """Any header starting with the custom prefix is removed before merge."""
        token = _make_test_jwt({"scope": "mcp/hpc-user"})
        forged_headers = {
            "x-amzn-bedrock-agentcore-runtime-custom-Evil": "injected",
        }
        event = _gateway_event(token=token, extra_headers=forged_headers)
        resp = index.handler(event, _Ctx())

        out_headers = resp["http"]["transformedGatewayRequest"]["headers"]
        # The forged custom header must not survive.
        for key in out_headers:
            if key.lower().startswith(index._CUSTOM_HEADER_PREFIX):
                # Only the three Trusted_Context_Headers should be present.
                self.assertIn(key, {
                    index.HEADER_PRINCIPAL,
                    index.HEADER_SCOPE,
                    index.HEADER_BROKER_REQUEST_ID,
                })


class TestBodyPassthrough(unittest.TestCase):
    """R4.1 — base64-encoded body is passed through unchanged."""

    def test_body_passthrough_unchanged(self):
        """The request body (base64 JSON-RPC) must appear unchanged in output."""
        token = _make_test_jwt({"scope": "mcp/ci-readonly"})
        body_json = json.dumps({
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": "search_documentation", "arguments": {"query": "test"}},
            "id": 42,
        })
        b64_body = base64.b64encode(body_json.encode()).decode()

        event = {
            "http": {
                "gatewayRequest": {
                    "path": "/mdc-mcp-rag/invocations",
                    "method": "POST",
                    "headers": {"Authorization": f"Bearer {token}"},
                    "body": b64_body,
                }
            }
        }
        resp = index.handler(event, _Ctx())

        out_body = resp["http"]["transformedGatewayRequest"]["body"]
        self.assertEqual(out_body, b64_body, "Body must pass through byte-identical")

    def test_empty_body_passthrough(self):
        """An empty body field is passed through as empty string."""
        token = _make_test_jwt({"scope": "mcp/ci-readonly"})
        event = {
            "http": {
                "gatewayRequest": {
                    "path": "/mdc-mcp-rag/invocations",
                    "method": "POST",
                    "headers": {"Authorization": f"Bearer {token}"},
                    "body": "",
                }
            }
        }
        resp = index.handler(event, _Ctx())
        self.assertEqual(resp["http"]["transformedGatewayRequest"]["body"], "")


class TestBrokerRequestId(unittest.TestCase):
    """R6.1 — broker_request_id from JWT claims or x-broker-request-id header."""

    def test_broker_request_id_from_jwt_claims(self):
        """When the JWT payload includes broker_request_id, it appears in the header."""
        token = _make_test_jwt({
            "scope": "mcp/ci-readonly",
            "broker_request_id": "br-from-claims-777",
        })
        resp = index.handler(_gateway_event(token=token), _Ctx())

        out_headers = resp["http"]["transformedGatewayRequest"]["headers"]
        self.assertEqual(
            out_headers[index.HEADER_BROKER_REQUEST_ID],
            "br-from-claims-777",
        )

    def test_broker_request_id_fallback_to_header(self):
        """When broker_request_id is NOT in JWT claims, fall back to
        x-broker-request-id request header."""
        token = _make_test_jwt({"scope": "mcp/ci-readonly"})  # no broker_request_id
        event = _gateway_event(
            token=token,
            extra_headers={"x-broker-request-id": "br-from-header-888"},
        )
        resp = index.handler(event, _Ctx())

        out_headers = resp["http"]["transformedGatewayRequest"]["headers"]
        self.assertEqual(
            out_headers[index.HEADER_BROKER_REQUEST_ID],
            "br-from-header-888",
        )

    def test_broker_request_id_missing_everywhere(self):
        """When broker_request_id is absent from both claims and headers,
        the header is present but empty."""
        token = _make_test_jwt({"scope": "mcp/ci-readonly"})
        resp = index.handler(_gateway_event(token=token), _Ctx())

        out_headers = resp["http"]["transformedGatewayRequest"]["headers"]
        self.assertEqual(out_headers[index.HEADER_BROKER_REQUEST_ID], "")


class TestTokenNotLogged(unittest.TestCase):
    """R4.4 — Authorization header value never appears in logs (integration check
    across all paths exercised above, using caplog-style capture)."""

    def _assert_token_not_in_logs(self, token, event):
        """Helper: invoke handler and assert the raw token is absent from logs."""
        _, logs = _invoke_capturing_logs(event)
        self.assertNotIn(token, logs, "Raw token value leaked into logs")

    def test_happy_path_no_token_logged(self):
        token = _make_test_jwt({"scope": "mcp/ci-readonly", "broker_request_id": "br-x"})
        self._assert_token_not_in_logs(token, _gateway_event(token=token))

    def test_denied_path_no_token_logged(self):
        token = _make_test_jwt({"scope": "mcp/unknown"})
        self._assert_token_not_in_logs(token, _gateway_event(token=token))


class TestMultipleScopesInClaim(unittest.TestCase):
    """Edge case: scope claim contains multiple space-separated scopes.
    The handler picks the first recognized one."""

    def test_first_recognized_scope_wins(self):
        """scope='openid mcp/ci-readonly mcp/hpc-user' → ci-readonly (first match)."""
        token = _make_test_jwt({"scope": "openid mcp/ci-readonly mcp/hpc-user"})
        resp = index.handler(_gateway_event(token=token), _Ctx())

        out_headers = resp["http"]["transformedGatewayRequest"]["headers"]
        self.assertEqual(out_headers[index.HEADER_PRINCIPAL], "ci-readonly")
        self.assertEqual(out_headers[index.HEADER_SCOPE], "mcp/ci-readonly")

    def test_unrecognized_scopes_only_returns_403(self):
        """scope='openid profile email' → no recognized scope → 403."""
        token = _make_test_jwt({"scope": "openid profile email"})
        resp = index.handler(_gateway_event(token=token), _Ctx())

        gw_resp = resp["http"]["transformedGatewayResponse"]
        self.assertEqual(gw_resp["statusCode"], 403)


if __name__ == "__main__":
    unittest.main()
