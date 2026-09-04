"""MCP Gateway Request Interceptor — Path C (AD-C2).

REQUEST interceptor Lambda for the AgentCore Gateway. Derives principal and
scope from the Gateway-validated JWT and injects Trusted_Context_Headers
that the MCP_Server reads for tool gating and audit attribution.

The Gateway already validated the JWT (signature, iss, aud, client_id, exp,
scope). This Lambda only reads claims to extract the scope → principal
mapping and the broker_request_id for attribution.

SECURITY:
  - NEVER log the Authorization header value or any raw token content (R4.4).
  - Injected headers overwrite any client-supplied same-named header (R4.3).
  - No principal derivable → return HTTP 403 (R4.6).

Event shape for HTTP/Runtime targets:
  {
    "http": {
      "gatewayRequest": {
        "path": "/{targetName}/invocations",
        "method": "POST",
        "headers": { ... },
        "body": "<base64-encoded-json-rpc>"
      }
    }
  }
"""

import base64
import json
import logging

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

# Scope → principal mapping (R5.1, R5.3)
SCOPE_TO_PRINCIPAL = {
    "mcp/ci-readonly": "ci-readonly",
    "mcp/hpc-user": "hpc-user",
}

# The header prefix for trusted context (AD-C2)
_CUSTOM_HEADER_PREFIX = "x-amzn-bedrock-agentcore-runtime-custom-"

# Trusted Context Header names
HEADER_PRINCIPAL = "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Principal"
HEADER_SCOPE = "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Scope"
HEADER_BROKER_REQUEST_ID = "X-Amzn-Bedrock-AgentCore-Runtime-Custom-BrokerRequestId"


def handler(event, context):
    """REQUEST interceptor entry point."""
    try:
        req = event["http"]["gatewayRequest"]
        headers = {k.lower(): v for k, v in (req.get("headers") or {}).items()}

        # The Gateway already validated signature, iss, aud, client_id, exp and scope.
        # Decode without verification purely to read claims. NEVER log the token.
        token = headers.get("authorization", "").removeprefix("Bearer ").strip()
        claims = _decode_unverified(token) if token else {}

        scope_claim = claims.get("scope", "")
        scope = next((s for s in scope_claim.split() if s in SCOPE_TO_PRINCIPAL), None)
        if scope is None:
            log.warning("NO_RECOGNIZED_SCOPE: claim=%r", scope_claim)
            return _deny(403, "no recognized scope")  # R4.6

        principal = SCOPE_TO_PRINCIPAL[scope]
        broker_request_id = (
            claims.get("broker_request_id")
            or headers.get("x-broker-request-id", "")
        )

        # Build injected headers
        injected = {
            HEADER_PRINCIPAL: principal,
            HEADER_SCOPE: scope,
            HEADER_BROKER_REQUEST_ID: broker_request_id,
        }

        # Strip any client-supplied Custom-* headers before merging (R4.3 — belt and braces)
        original_headers = dict(req.get("headers") or {})
        cleaned_headers = {
            k: v for k, v in original_headers.items()
            if not k.lower().startswith(_CUSTOM_HEADER_PREFIX)
        }
        cleaned_headers.update(injected)

        log.info(
            "INTERCEPTOR_OK: principal=%s scope=%s broker_request_id=%s",
            principal,
            scope,
            broker_request_id[:32] if broker_request_id else "<none>",
        )

        return {
            "interceptorOutputVersion": "1.0",
            "http": {
                "transformedGatewayRequest": {
                    "headers": cleaned_headers,
                    "body": req.get("body", ""),  # pass through untouched, still base64
                }
            },
        }

    except Exception as exc:
        log.error("INTERCEPTOR_ERROR: %s", str(exc))
        return _deny(500, "interceptor_error")


def _decode_unverified(token):
    """Decode JWT payload WITHOUT signature verification.

    Safe because the Gateway already validated the signature. We only need
    to read the claims (scope, broker_request_id).
    """
    if not token:
        return {}
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return {}
        # JWT payload is base64url-encoded; add padding if needed
        payload = parts[1]
        payload += "=" * (4 - len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded)
    except Exception:
        log.warning("JWT_DECODE_FAILED: malformed token payload")
        return {}


def _deny(code, reason):
    """Return a transformedGatewayResponse that short-circuits the request."""
    body = base64.b64encode(json.dumps({"error": reason}).encode()).decode()
    return {
        "interceptorOutputVersion": "1.0",
        "http": {
            "transformedGatewayResponse": {
                "statusCode": code,
                "contentType": "application/json",
                "body": body,
            }
        },
    }
