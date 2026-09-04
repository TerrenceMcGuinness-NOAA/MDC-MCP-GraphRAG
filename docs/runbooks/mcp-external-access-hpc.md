# MCP External Access — HPC (RDHPC / Gaea)

How HPC researchers on RDHPC clusters (Hera, Hercules, Orion) and NOAA
systems (Gaea, WCOSS2) access the MCP-RAG tools through the AgentCore
Gateway.

**Spec:** `.kiro/specs/mcp-external-access-alternative-gateway/` (Path C)
**Requirement:** R9.1

---

## Overview

HPC researchers query the MCP-RAG server through the same AgentCore Gateway
that CI uses, with a different scope (`mcp/hpc-user`) and a different token
acquisition flow (interactive PKCE or SRP, rather than CI's federated OIDC).

```
HPC researcher (Hera, Gaea, etc.)
  │  1. Run `mdc-mcp-jwt` CLI helper
  │     → Authorization Code + PKCE (primary)
  │     → or SRP username/password (fallback)
  │  2. Receive short-lived JWT (scope: mcp/hpc-user)
  ▼
AgentCore Gateway
  │  ─ Cognito customJWTAuthorizer validates the JWT
  │  ─ REQUEST interceptor Lambda injects principal/scope headers
  ▼
AgentCore Runtime (MCP_Server)
  │  ─ Reads Trusted_Context_Headers → principal "hpc-user"
  │  ─ Enforces Allowed_Tool_Set (50 tools)
  ▼
Tool response (JSON)
```

The developer SigV4 path (`tools/agentcore-kiro-proxy.py`) targets the
Runtime **directly** and does NOT traverse the Gateway. This runbook
covers the Gateway path only.

---

## Token Acquisition

HPC users authenticate interactively through the `mdc-mcp-jwt` CLI helper.
Two flows are supported:

### Primary: Authorization Code + PKCE

The preferred flow for environments where a browser redirect is possible
(X11 forwarding, SSH tunnel with port forwarding, or a local terminal that
can open a browser).

```bash
mdc-mcp-jwt auth --flow pkce
```

The helper opens a Cognito-hosted login page, handles the callback, and
writes the JWT to a local credential cache.

### Fallback: SRP (username/password)

For headless environments where browser redirect is not feasible.

```bash
mdc-mcp-jwt auth --flow srp
```

Prompts for Cognito username and password. The token is cached locally with
the same lifetime as the PKCE path.

### Token lifetime

JWTs are valid for 60 minutes. The CLI helper caches the token and
transparently refreshes it when expired.

---

## Gateway Endpoint

The endpoint URL is exported as the `McpEndpointUrl` CloudFormation output
from the `MdcMcpGatewayStack` CDK stack.

**Format:**

```
https://{gatewayId}.gateway.bedrock-agentcore.{region}.amazonaws.com/mdc-mcp-rag/invocations
```

The target name is `mdc-mcp-rag`. Use the exported value rather than
hard-coding the URL.

---

## Making a Request

Requests are JSON-RPC 2.0 over HTTPS. The JWT goes in the `Authorization`
header as a Bearer token.

### List available tools

```bash
curl -s -X POST "${MCP_URL}" \
  -H "Authorization: Bearer ${JWT}" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "method": "tools/list", "id": 1}'
```

### Call a tool

```bash
curl -s -X POST "${MCP_URL}" \
  -H "Authorization: Bearer ${JWT}" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "search_documentation",
      "arguments": {"query": "FV3 atmospheric model configuration"}
    },
    "id": 1
  }'
```

### Using the CLI helper

```bash
# The mdc-mcp-jwt helper manages token acquisition and injection:
mdc-mcp-jwt call search_documentation --query "GDAS analysis cycle"
```

---

## Available Tools (HPC Scope)

The `mcp/hpc-user` scope grants access to **50 tools** across all 10 MCP
modules. This is the CI_READONLY set (42 tools) plus 8 additional tools.
The full enumeration is in
`mcp_server_python/src/auth/tool_scope_guard.py::HPC_USER`.

### Additional tools beyond CI scope

| Module | Tools | Notes |
|---|---|---|
| GraphRAG (session) | `mark_as_modified`, `checkpoint_state`, `restore_checkpoint` | Session continuity for multi-step research |
| GraphRAG (read) | `get_session_context` | View session state |
| GitHub Integration | `search_issues`, `get_pull_requests`, `analyze_workflow_dependencies`, `analyze_repository_structure` | Repository-level queries |

### Excluded from HPC

- **SDD session management (3):** `start_sdd_session`, `record_sdd_step`,
  `complete_sdd_session` — reserved for `developer-sigv4` only.

Invoking an excluded tool returns HTTP 403. The Allowed_Tool_Set is an
explicit enumeration with default-deny; any tool not listed is rejected.

---

## Attribution and Audit

Every HPC invocation is attributable via the `broker_request_id`, following
the same pattern as CI. See the CI runbook's "Attribution and Audit" section
for the full flow.

---

## Troubleshooting

### HTTP 401 at the Gateway

The Gateway rejected the JWT before it reached the Runtime.

- **Token expired.** JWTs are valid for 60 minutes. Re-authenticate via
  `mdc-mcp-jwt auth`. If using a cached token, force refresh with
  `mdc-mcp-jwt auth --force`.
- **Wrong audience.** The JWT's `aud` must match one of the Gateway's
  `allowedClients`. Check the Cognito HPC app-client ID.
- **Wrong scope.** The JWT must carry a scope in the Gateway's
  `allowedScopes` list (`mcp/hpc-user`). If you see 401 after a successful
  login, the Cognito app client may be misconfigured.
- **Malformed Authorization header.** Must be `Bearer <token>` (capital B,
  single space). The `mdc-mcp-jwt` CLI handles this automatically; this
  is only relevant for direct `curl` usage.
- **Network egress blocked.** HPC clusters route through NAT gateways or
  proxy servers. If `curl` to the Gateway endpoint hangs or returns a
  connection error (not an HTTP error), check the cluster's outbound
  firewall rules for `bedrock-agentcore.us-east-1.amazonaws.com:443`.
  RDHPC egress was verified working on 2026-08-06 from gaea64.

### HTTP 403 from tool scoping

The Gateway admitted the request, but the MCP_Server rejected the tool
invocation.

- **Tool not in HPC_USER.** SDD session management tools
  (`start_sdd_session`, `record_sdd_step`, `complete_sdd_session`) are
  excluded from the HPC scope. Check the tool list above.
- **Unrecognized scope.** The interceptor-injected scope was not in
  `KNOWN_SCOPES`. This should not happen for a valid HPC JWT — indicates
  a configuration mismatch between the Cognito resource server and the
  MCP_Server's `KNOWN_SCOPES`.

### Interceptor not firing

The Gateway forwarded the request but no Trusted_Context_Headers arrived at
the Runtime, so the MCP_Server treated it as `developer-sigv4`.

**How to detect:** the audit log shows `principal: developer-sigv4` for a
request that came through the Gateway (identifiable by the presence of
Gateway-specific headers like `X-Forwarded-For`).

- **Response framing regression.** The MCP_Server must serve
  `json_response=True` for interceptors to run (buffered mode only). Check
  `MCP_JSON_RESPONSE` env var on the Runtime. A WARNING log at startup
  indicates this is disabled. See "SSE-framing regression" below.
- **Interceptor Lambda error.** Check the `mdc-mcp-gateway-interceptor`
  CloudWatch log group for errors. Common causes: Lambda timeout (budget
  is 2 seconds), malformed JWT payload, or missing Lambda permissions.
- **Gateway execution role missing `lambda:InvokeFunction`.** The Gateway
  requires both the Lambda's resource-based policy AND the execution
  role's identity-based policy to invoke the interceptor (dual
  authorization model). Check the execution role's inline policies.

### Missing Trusted_Context_Headers

The interceptor ran (visible in CloudWatch) but the headers did not arrive
at the Runtime.

- **Headers not in allowedRequestHeaders.** The Runtime target's
  `metadataConfiguration.allowedRequestHeaders` must list all three
  `X-Amzn-Bedrock-AgentCore-Runtime-Custom-*` header names. Check the
  target configuration via `get-gateway-target`.
- **Header name mismatch.** Names are case-sensitive in the target
  configuration. Verify exact match against:
  - `X-Amzn-Bedrock-AgentCore-Runtime-Custom-Principal`
  - `X-Amzn-Bedrock-AgentCore-Runtime-Custom-Scope`
  - `X-Amzn-Bedrock-AgentCore-Runtime-Custom-BrokerRequestId`
- **Gateway execution role missing `InvokeAgentRuntime`.** If the
  Gateway→Runtime forwarding hop fails with a 403
  `AccessDeniedException`, the interceptor ran correctly but the
  transformed request was never delivered. Add
  `bedrock-agentcore:InvokeAgentRuntime` to the execution role.

### SSE-framing regression

The MCP_Server must serve `json_response=True` (buffered JSON framing) for
Gateway interceptors to fire. If the framing reverts to SSE
(`text/event-stream`), the Gateway path silently loses all principal/scope
enforcement.

**Symptoms:**

- Gateway-routed requests arrive at the Runtime without
  Trusted_Context_Headers — the MCP_Server treats every external request as
  `developer-sigv4` (full tool access, no audit attribution).
- The developer proxy emits `-32603 "Empty SSE response"` on every tool
  call if running proxy versions **before v1.2.0** (which lack
  framing tolerance).

**Common causes:**

- **`MCP_JSON_RESPONSE` set to `false` or removed.** Check the Runtime's
  environment variables. The startup log emits a `[WARN] json_response
  disabled` line when this happens.
- **`update-agent-runtime` with a partial payload.** The API is
  full-replacement — a call that omits `--environment-variables` silently
  wipes all env vars, including `MCP_JSON_RESPONSE`. Always use the full
  payload template from the deploy runbook.
- **Container image downgrade.** An older image that predates the
  `json_response` code path will default to SSE. Verify the image tag
  includes the Path C changes.

**Recovery:**

1. Run `GetAgentRuntime` and confirm `MCP_JSON_RESPONSE` is present and set
   to `true` in the environment variables.
2. If missing, re-apply via `update-agent-runtime` with the **full lossless
   payload** (all 7 env vars, network config, EFS mount, etc.).
3. After the Runtime reaches READY, verify with a developer proxy call
   (`get_server_info`) — if it returns normally, framing is correct.

### Empty or error response

- **6 MB payload limit** — the interceptor is configured with
  `payloadFilter: { exclude: ['RESPONSE_BODY'] }` to avoid this. If a
  large-response error occurs, verify the payload filter is still set on
  the target's interceptor configuration.

---

## Reference

- **Spec:** `.kiro/specs/mcp-external-access-alternative-gateway/`
- **Design:** `design.md` in the spec directory (architecture, decision log)
- **Tool scope source:** `mcp_server_python/src/auth/tool_scope_guard.py`
- **Auth middleware:** `mcp_server_python/src/auth/middleware.py`
- **Interceptor Lambda:** `infrastructure/cdk/lambda/gateway_interceptor/index.py`
- **CDK stack:** `infrastructure/cdk/lib/mdc-mcp-gateway-stack.ts`
- **CI runbook:** `docs/runbooks/mcp-external-access-ci.md`
- **Gateway verification report:** `docs/reports/mcp-external-access-gateway-verification.md`
