"""MCP Token_Broker Lambda (Path B, simplified — AD-3).

Exchanges a GitHub-OIDC-federated caller's identity for a Cognito CI access
token (client-credentials, scope ``mcp/ci-readonly``) and returns it, keyed by
this invocation's request id. The request id is the attribution join key: the
Token_Broker log line and the MCP_Server audit log line are joined on it
(R3.12, R13.3).

There is deliberately NO DynamoDB table and NO Cognito Pre-Token-Generation
trigger (AD-3, R9.10). The issued Cognito token is a plain M2M access token
with no injected custom claims. GitHub attribution travels out-of-band as MCP
Request_Metadata; it is recorded here only in the structured log.

Environment
-----------
ALLOWED_SUB_PATTERNS_JSON : JSON array of anchored regex strings; the assumed
    role's ``github_claims.sub`` must match at least one (R3.10).
COGNITO_TOKEN_ENDPOINT : the Cognito Hosted-UI ``/oauth2/token`` URL.
CI_CLIENT_SECRET_ARN : Secrets Manager ARN holding ``{client_id, client_secret}``.
"""

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import boto3

ALLOWED_SUB_PATTERNS = [
    re.compile(p) for p in json.loads(os.environ["ALLOWED_SUB_PATTERNS_JSON"])
]
COGNITO_TOKEN_ENDPOINT = os.environ["COGNITO_TOKEN_ENDPOINT"]
CI_CLIENT_SECRET_ARN = os.environ["CI_CLIENT_SECRET_ARN"]
SLO_MS = 5000  # R3.3 end-to-end SLO (soft — a breach warns, still returns 200)

_secrets = boto3.client("secretsmanager")


def handler(event: dict, context: Any) -> dict:
    """Broker a Cognito CI access token for an allowlisted GitHub OIDC caller."""
    request_id = context.aws_request_id  # THE attribution join key (R3.6, R13.3)
    t0 = time.monotonic()

    gh = event.get("github_claims", {}) or {}
    github_sub = gh.get("sub", "") or ""
    run_id = gh.get("run_id", "") or ""
    repository = gh.get("repository", "") or ""
    ref = gh.get("ref", "") or ""

    # 1. Enforce the repo/ref allowlist BEFORE any Cognito call (R3.10).
    if not any(p.match(github_sub) for p in ALLOWED_SUB_PATTERNS):
        _attrib_log(request_id, run_id, repository, ref, event_type="forbidden_repository")
        return _respond(403, {"error": "forbidden_repository", "request_id": request_id})

    # 2. Read the CI client secret (no DynamoDB, no other secret).
    try:
        secret = json.loads(
            _secrets.get_secret_value(SecretId=CI_CLIENT_SECRET_ARN)["SecretString"]
        )
    except Exception as exc:  # defensive — secret unreadable
        _attrib_log(request_id, run_id, repository, ref, event_type="secret_read_failure")
        return _respond(500, {"error": "secret_read_failed", "request_id": request_id, "detail": str(exc)})

    # 3. Mint a PLAIN client-credentials access token (no custom claims — AD-3).
    body = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "scope": "mcp/ci-readonly",
            "client_id": secret["client_id"],
            "client_secret": secret["client_secret"],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        COGNITO_TOKEN_ENDPOINT,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            token_body = json.loads(resp.read())
    except Exception as exc:  # network/timeout/HTTP error — R3.11
        _attrib_log(request_id, run_id, repository, ref, event_type="upstream_failure")
        return _respond(
            502,
            {"error": "upstream_token_issuance_failed", "detail": str(exc), "request_id": request_id},
        )

    # 4. Emit the ATTRIBUTION-ANCHOR log line — keyed by request_id, NEVER the
    #    token (R3.6, R13.3).
    _attrib_log(request_id, run_id, repository, ref, event_type="token_issued")

    elapsed_ms = int((time.monotonic() - t0) * 1000)  # R3.3 soft SLO
    if elapsed_ms > SLO_MS:
        print(json.dumps({"warn": "slo_breach", "request_id": request_id, "elapsed_ms": elapsed_ms}))

    # 5. Return the token AND request_id so the caller can forward the id as
    #    MCP Request_Metadata (R3.7).
    return _respond(
        200,
        {
            "access_token": token_body["access_token"],
            "expires_in": token_body.get("expires_in"),
            "token_type": token_body.get("token_type"),
            "request_id": request_id,
        },
    )


def _attrib_log(request_id: str, run_id: str, repository: str, ref: str, event_type: str) -> None:
    """Emit one structured JSON attribution line — never token material (R3.6)."""
    print(
        json.dumps(
            {
                "event": event_type,
                "request_id": request_id,
                "github_run_id": run_id,
                "github_repository": repository,
                "github_ref": ref,
            }
        )
    )


def _respond(status: int, body: dict) -> dict:
    return {"statusCode": status, "body": json.dumps(body)}
