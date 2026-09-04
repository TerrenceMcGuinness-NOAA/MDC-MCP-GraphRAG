"""Task 6.6 — Large-response safety.

Verify that the Gateway interceptor's payload filter excludes RESPONSE_BODY,
preventing Lambda's 6 MB synchronous invoke limit from being breached by large
RAG responses. Also verify the interceptor Lambda itself handles large request
bodies without size-related issues.

The defense has two layers:
  1. **CDK configuration** — the ``interceptorConfiguration`` on the Runtime
     target sets ``payloadFilter: { exclude: ['RESPONSE_BODY'] }`` so that the
     Gateway never sends the response body to the interceptor Lambda.
  2. **Interceptor handler** — the handler passes the request body through
     unchanged (base64, opaque). This test verifies that even with a large body
     (≥ 1 MB), the handler does not truncate, corrupt, or fail.

The actual live test — invoking a tool that returns multi-MB data through the
Gateway and confirming the response arrives intact — is performed at deploy time
as part of the Gateway acceptance test (see §12 in design.md). It cannot be
automated here because it requires:
  - A running AgentCore Gateway and Runtime
  - A real Cognito JWT
  - A tool that produces multi-MB output (e.g., ``search_documentation`` with a
    very broad query, or ``get_knowledge_base_status`` with ``all_tenants=True``)

Requirements: R6.3, design §4.4.

Run:
    cd /mdc-mcp-rag/eib-mcp-rag-server
    python -m pytest mcp_server_python/tests/verification/test_large_response_safety.py -v
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import textwrap

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


# ---------------------------------------------------------------------------
# Path to the CDK stack source (for static analysis tests)
# ---------------------------------------------------------------------------

_CDK_STACK_PATH = os.path.normpath(os.path.join(
    os.path.dirname(__file__),
    os.pardir, os.pardir, os.pardir,
    "infrastructure", "cdk", "lib", "mdc-mcp-gateway-stack.ts",
))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_jwt(claims: dict) -> str:
    """Create a structurally valid JWT for testing."""
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "RS256", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps(claims).encode()
    ).rstrip(b"=").decode()
    signature = base64.urlsafe_b64encode(b"fakesig").rstrip(b"=").decode()
    return f"{header}.{payload}.{signature}"


class _Ctx:
    """Minimal Lambda context stub."""
    function_name = "gateway_interceptor"
    aws_request_id = "req-large-001"


def _gateway_event(token: str, body_b64: str) -> dict:
    """Build a Gateway REQUEST interceptor event with a custom body."""
    return {
        "http": {
            "gatewayRequest": {
                "path": "/mdc-mcp-rag/invocations",
                "method": "POST",
                "headers": {"Authorization": f"Bearer {token}"},
                "body": body_b64,
            }
        }
    }


# ---------------------------------------------------------------------------
# 1. CDK source-level assertion: payload filter excludes RESPONSE_BODY
# ---------------------------------------------------------------------------


class TestCdkPayloadFilterExcludesResponseBody:
    """Verify that the CDK stack source configures the interceptor with
    ``payloadFilter: { exclude: ['RESPONSE_BODY'] }``.

    This is a static source analysis test. The CDK stack uses
    ``AwsCustomResource`` (not a native CloudFormation resource) to call
    ``createGatewayTarget``. The parameters — including
    ``interceptorConfiguration`` — are serialized as JSON inside the
    ``Custom::AWS`` resource's ``Create`` property. We verify the source
    directly because the serialized form includes CloudFormation tokens
    (``Fn::Join`` intrinsics) that make template-level JSON parsing fragile.

    The companion CDK-level test in
    ``infrastructure/cdk/test/mdc-mcp-gateway-stack.test.ts`` verifies the
    same property through the synthesized template.
    """

    @pytest.fixture(autouse=True)
    def _read_source(self) -> None:
        """Read the CDK stack source once for all tests in this class."""
        assert os.path.isfile(_CDK_STACK_PATH), (
            f"CDK stack source not found at {_CDK_STACK_PATH}"
        )
        with open(_CDK_STACK_PATH) as f:
            self.source = f.read()

    def test_interceptor_configuration_has_payload_filter(self):
        """The interceptorConfiguration block includes a payloadFilter."""
        assert "payloadFilter" in self.source, (
            "CDK stack source does not contain payloadFilter — "
            "large responses will breach the Lambda 6 MB limit (R6.3)"
        )

    def test_payload_filter_excludes_response_body(self):
        """The payloadFilter.exclude list includes 'RESPONSE_BODY'."""
        assert "'RESPONSE_BODY'" in self.source or '"RESPONSE_BODY"' in self.source, (
            "CDK stack source payloadFilter does not exclude RESPONSE_BODY — "
            "large RAG responses will breach the Lambda 6 MB limit (R6.3, design §4.4)"
        )

    def test_interceptor_type_is_request(self):
        """The interceptor type is REQUEST (not RESPONSE), confirming it runs
        on the inbound path where RESPONSE_BODY exclusion is meaningful."""
        # Match the interceptor config block — type: 'REQUEST'
        assert re.search(
            r"type:\s*['\"]REQUEST['\"]", self.source,
        ), "Interceptor type should be 'REQUEST'"

    def test_pass_request_headers_is_true(self):
        """passRequestHeaders: true — required for the interceptor to read the
        Authorization header and derive principal/scope (R4.5)."""
        assert re.search(
            r"passRequestHeaders:\s*true", self.source,
        ), "passRequestHeaders should be true"

    def test_payload_filter_and_interceptor_in_same_block(self):
        """The payloadFilter and the interceptor type/lambdaArn are in the same
        ``interceptors`` array entry, not split across resources."""
        # Extract the interceptorConfiguration block.
        match = re.search(
            r"interceptorConfiguration:\s*\{([\s\S]*?)\n\s{4}\};",
            self.source,
        )
        assert match, "Could not find interceptorConfiguration block"
        block = match.group(1)
        assert "payloadFilter" in block, (
            "payloadFilter is not inside the interceptorConfiguration block"
        )
        assert "'REQUEST'" in block or '"REQUEST"' in block, (
            "Interceptor type is not inside the interceptorConfiguration block"
        )


# ---------------------------------------------------------------------------
# 2. Interceptor handler: large body passthrough
# ---------------------------------------------------------------------------


class TestInterceptorLargeBodyPassthrough:
    """Verify the interceptor handler passes large request bodies through
    unchanged — no truncation, corruption, or size-related failure.

    The handler receives the body as a base64-encoded string and is expected
    to forward it byte-identical. This test uses a 1 MB body to confirm no
    issues at scale. The actual Lambda 6 MB limit is a Gateway-side concern
    mitigated by the payloadFilter; this test ensures the handler code itself
    introduces no additional constraint.
    """

    @pytest.fixture
    def token(self) -> str:
        """Valid CI-scoped JWT."""
        return _make_jwt({
            "scope": "mcp/ci-readonly",
            "broker_request_id": "br-large-body",
        })

    def _make_large_body_b64(self, size_bytes: int) -> str:
        """Create a base64-encoded JSON-RPC body of approximately ``size_bytes``."""
        # Build a JSON-RPC tools/call with a large argument value.
        padding = "x" * size_bytes
        body = json.dumps({
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "search_documentation",
                "arguments": {"query": padding},
            },
            "id": 1,
        })
        return base64.b64encode(body.encode()).decode()

    def test_1mb_body_passes_through_unchanged(self, token: str):
        """A ~1 MB body is forwarded byte-identical by the interceptor."""
        body_b64 = self._make_large_body_b64(1_000_000)
        event = _gateway_event(token, body_b64)

        resp = interceptor.handler(event, _Ctx())

        assert "transformedGatewayRequest" in resp.get("http", {}), (
            "Interceptor did not return transformedGatewayRequest for 1 MB body"
        )
        out_body = resp["http"]["transformedGatewayRequest"]["body"]
        assert out_body == body_b64, (
            f"Body was altered — input length {len(body_b64)}, "
            f"output length {len(out_body)}"
        )

    def test_2mb_body_passes_through_unchanged(self, token: str):
        """A ~2 MB body — still under the 6 MB limit — passes through."""
        body_b64 = self._make_large_body_b64(2_000_000)
        event = _gateway_event(token, body_b64)

        resp = interceptor.handler(event, _Ctx())

        assert "transformedGatewayRequest" in resp.get("http", {})
        out_body = resp["http"]["transformedGatewayRequest"]["body"]
        assert out_body == body_b64

    def test_empty_body_still_works(self, token: str):
        """Edge case: empty body still produces a valid response."""
        event = _gateway_event(token, "")
        resp = interceptor.handler(event, _Ctx())

        assert "transformedGatewayRequest" in resp.get("http", {})
        assert resp["http"]["transformedGatewayRequest"]["body"] == ""

    def test_headers_correct_for_large_body(self, token: str):
        """Principal, scope, and broker_request_id headers are correctly set
        even when the body is large — body size does not interfere with
        header derivation."""
        body_b64 = self._make_large_body_b64(1_000_000)
        event = _gateway_event(token, body_b64)

        resp = interceptor.handler(event, _Ctx())

        out_headers = resp["http"]["transformedGatewayRequest"]["headers"]
        assert out_headers[interceptor.HEADER_PRINCIPAL] == "ci-readonly"
        assert out_headers[interceptor.HEADER_SCOPE] == "mcp/ci-readonly"
        assert out_headers[interceptor.HEADER_BROKER_REQUEST_ID] == "br-large-body"


# ---------------------------------------------------------------------------
# 3. Deploy-time live test documentation
# ---------------------------------------------------------------------------


class TestDeployTimeLargeResponseDocumented:
    """Verify that the design document and/or runbooks reference the deploy-time
    live test for large responses. This is a documentation-level check — the
    actual live test is performed by an operator during Gateway acceptance.

    The live test procedure:
      1. Acquire a CI-scoped JWT from the Token_Broker.
      2. Invoke a tool known to return multi-MB output through the Gateway
         endpoint (e.g., ``search_documentation`` with a broad query).
      3. Confirm the response arrives intact (HTTP 200, parseable JSON-RPC).
      4. Confirm no Lambda payload-limit error appears in the interceptor
         CloudWatch logs.
    """

    def test_design_references_payload_filter(self):
        """Design document mentions the RESPONSE_BODY payload filter (§4.4)."""
        design_path = os.path.normpath(os.path.join(
            os.path.dirname(__file__),
            os.pardir, os.pardir, os.pardir,
            ".kiro", "specs", "mcp-external-access-alternative-gateway",
            "design.md",
        ))
        assert os.path.isfile(design_path), (
            f"Design document not found at {design_path}"
        )
        with open(design_path) as f:
            content = f.read()
        assert "RESPONSE_BODY" in content, (
            "Design document does not mention RESPONSE_BODY payload filter"
        )
        assert "6 MB" in content or "6MB" in content, (
            "Design document does not mention the Lambda 6 MB payload limit"
        )

    def test_requirements_reference_payload_filter(self):
        """Requirements R6.3 explicitly requires excluding RESPONSE_BODY."""
        req_path = os.path.normpath(os.path.join(
            os.path.dirname(__file__),
            os.pardir, os.pardir, os.pardir,
            ".kiro", "specs", "mcp-external-access-alternative-gateway",
            "requirements.md",
        ))
        assert os.path.isfile(req_path)
        with open(req_path) as f:
            content = f.read()
        assert "RESPONSE_BODY" in content, (
            "Requirements do not mention RESPONSE_BODY payload filter"
        )
