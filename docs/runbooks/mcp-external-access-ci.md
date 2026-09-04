# MCP External Access — CI (GitHub Actions)

How GitHub Actions CI workflows access the MCP-RAG tools through the
AgentCore Gateway.

**Spec:** `.kiro/specs/mcp-external-access-alternative-gateway/` (Path C)
**Requirement:** R9.1

---

## Overview

CI workflows query the MCP-RAG server through an AgentCore Gateway that
validates a Cognito JWT before forwarding the request to the AgentCore
Runtime. The flow:

```
GitHub Actions runner
  │  1. Assume OIDC-federated IAM role
  │  2. Invoke Token_Broker Lambda → short-lived JWT (scope: mcp/ci-readonly)
  ▼
AgentCore Gateway
  │  ─ Cognito customJWTAuthorizer validates the JWT
  │  ─ REQUEST interceptor Lambda injects principal/scope headers
  ▼
AgentCore Runtime (MCP_Server)
  │  ─ Reads Trusted_Context_Headers → principal "ci-readonly"
  │  ─ Enforces Allowed_Tool_Set (42 read-only tools)
  ▼
Tool response (JSON)
```

The developer SigV4 path (`tools/agentcore-kiro-proxy.py`) targets the
Runtime **directly** and does NOT traverse the Gateway. This runbook
covers the Gateway path only.

---

## Token Acquisition

CI uses the **Token_Broker Lambda** to exchange a federated identity for a
Cognito JWT. No long-lived secrets are stored in the repository or GitHub
Actions secrets.

### Steps

1. **Assume the OIDC-federated IAM role.** The workflow uses
   `aws-actions/configure-aws-credentials@v4` with the GitHub OIDC token.
   The role's trust policy restricts the `sub` claim to an allowlist of
   repository-and-ref patterns, so only permitted repos/branches can assume
   it.

2. **Invoke the Token_Broker Lambda.** The Lambda exchanges the federated
   identity for a Cognito `client_credentials` JWT with scope
   `mcp/ci-readonly`. It also stamps the JWT with a `broker_request_id`
   for audit attribution.

3. **Receive the JWT.** The token is short-lived (60 minutes). It is masked
   in workflow logs automatically by the composite action.

### Composite action

The project publishes a reusable composite action at
`.github/actions/mcp-token/action.yml` that wraps steps 1–3:

```yaml
- uses: ./.github/actions/mcp-token
  id: mcp-auth
  with:
    aws-region: us-east-1
    aws-role-arn: arn:aws:iam::<account>:role/mdc-mcp-ci-oidc-role
    token-broker-function: mdc-mcp-token-broker
```

**Outputs:**

| Output | Description |
|---|---|
| `bearer-token` | The Cognito JWT (masked in logs) |
| `expires-in` | Token lifetime in seconds |
| `mcp-url` | The Gateway endpoint URL |

---

## Gateway Endpoint

The endpoint URL is exported as the `McpEndpointUrl` CloudFormation output
from the `MdcMcpGatewayStack` CDK stack.

**Format:**

```
https://{gatewayId}.gateway.bedrock-agentcore.{region}.amazonaws.com/mdc-mcp-rag/invocations
```

The target name is `mdc-mcp-rag`. Consumers should read the exported value
rather than hard-coding the URL, since the `gatewayId` is generated at
creation time.

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
      "arguments": {"query": "EE2 error handling standards"}
    },
    "id": 1
  }'
```

### In a GitHub Actions workflow

```yaml
jobs:
  analyze:
    runs-on: ubuntu-latest
    permissions:
      id-token: write   # Required for OIDC
      contents: read
    steps:
      - uses: actions/checkout@v4

      - uses: ./.github/actions/mcp-token
        id: mcp-auth
        with:
          aws-region: us-east-1
          aws-role-arn: ${{ secrets.MCP_CI_ROLE_ARN }}
          token-broker-function: mdc-mcp-token-broker

      - name: Query MCP
        run: |
          curl -sf -X POST "${{ steps.mcp-auth.outputs.mcp-url }}" \
            -H "Authorization: Bearer ${{ steps.mcp-auth.outputs.bearer-token }}" \
            -H "Content-Type: application/json" \
            -d '{
              "jsonrpc": "2.0",
              "method": "tools/call",
              "params": {
                "name": "search_documentation",
                "arguments": {"query": "EE2 error handling"}
              },
              "id": 1
            }'
```

---

## Available Tools (CI Scope)

The `mcp/ci-readonly` scope grants access to **42 read-only tools** across
9 of the 10 MCP modules. The full enumeration is in
`mcp_server_python/src/auth/tool_scope_guard.py::CI_READONLY`.

### Included modules and tool counts

| Module | Tools | Count |
|---|---|---|
| Workflow Info | `get_workflow_structure`, `get_system_configs`, `describe_component` | 3 |
| Code Analysis | `analyze_code_structure`, `find_dependencies`, `trace_execution_path`, `find_callers_callees`, `trace_full_execution_chain`, `find_env_dependencies` | 6 |
| Semantic Search | `search_documentation`, `find_related_files`, `explain_with_context`, `get_knowledge_base_status`, `list_ingested_urls`, `get_ingested_urls_array`, `check_knowledge_integrity`, `list_all_sources` | 8 |
| EE2 Compliance | `search_ee2_standards`, `analyze_ee2_compliance`, `generate_compliance_report`, `scan_repository_compliance`, `extract_code_for_analysis` | 5 |
| Operational | `get_operational_guidance`, `explain_workflow_component`, `list_job_scripts`, `get_job_details` | 4 |
| GraphRAG (read-only) | `get_code_context`, `search_architecture`, `find_similar_code`, `get_change_impact`, `trace_data_flow` | 5 |
| SDD Workflows (read-only) | `list_sdd_workflows`, `get_sdd_workflow`, `get_sdd_session`, `get_sdd_execution_history`, `validate_sdd_compliance`, `get_sdd_framework_status` | 6 |
| Utility | `get_server_info`, `mcp_health_check`, `get_health_trend`, `get_quality_metrics` | 4 |
| Error Analysis | `extract_ci_error_signal` | 1 |
| **Total** | | **42** |

### Excluded from CI

- **Mutation tools (6):** `mark_as_modified`, `checkpoint_state`,
  `restore_checkpoint`, `start_sdd_session`, `record_sdd_step`,
  `complete_sdd_session` — these modify session state.
- **GitHub Integration (4):** `search_issues`, `get_pull_requests`,
  `analyze_workflow_dependencies`, `analyze_repository_structure` —
  available to `mcp/hpc-user` only.
- **Session context (1):** `get_session_context` — available to
  `mcp/hpc-user` only.

Invoking an excluded tool returns HTTP 403. The Allowed_Tool_Set is an
explicit enumeration with default-deny; any tool not listed is rejected.

---

## Attribution and Audit

Every CI invocation is attributable via the `broker_request_id`:

1. The **Token_Broker Lambda** generates a unique `broker_request_id` when
   issuing the JWT and logs it alongside the GitHub workflow metadata
   (`repository`, `run_id`, `ref`, `sha`, `actor`).

2. The **Request Interceptor** extracts `broker_request_id` from the JWT
   claims and injects it as
   `X-Amzn-Bedrock-AgentCore-Runtime-Custom-BrokerRequestId`.

3. The **MCP_Server audit writer** records the `broker_request_id` in every
   audit log entry alongside the principal, scope, tool name, outcome, and
   timestamp.

To trace a CI invocation: join the MCP audit log entry to the Token_Broker
CloudWatch log on `broker_request_id`, which gives you the GitHub
repository, run ID, commit SHA, and actor.

---

## Troubleshooting

### HTTP 401 at the Gateway

The Gateway rejected the JWT before it reached the Runtime.

- **Token expired.** JWTs are valid for 60 minutes. Re-acquire via the
  composite action.
- **Wrong audience.** The JWT's `aud` must match one of the Gateway's
  `allowedClients`. Check the Cognito CI app-client ID.
- **Wrong scope.** The JWT must carry a scope in the Gateway's
  `allowedScopes` list (`mcp/ci-readonly`).
- **Malformed Authorization header.** Must be `Bearer <token>` (capital B,
  single space).

### HTTP 403 from tool scoping

The Gateway admitted the request, but the MCP_Server rejected the tool
invocation.

- **Tool not in CI_READONLY.** Check the list above. Mutation tools and
  GitHub Integration tools are excluded.
- **Unrecognized scope.** The interceptor-injected scope was not in
  `KNOWN_SCOPES`. This should not happen for a valid CI JWT — indicates
  a configuration mismatch.

### Interceptor not firing

The Gateway forwarded the request but no Trusted_Context_Headers arrived at
the Runtime, so the MCP_Server treated it as `developer-sigv4`.

- **Response framing regression.** The MCP_Server must serve
  `json_response=True` for interceptors to run (buffered mode only). Check
  `MCP_JSON_RESPONSE` env var on the Runtime. A WARNING log at startup
  indicates this is disabled.
- **Interceptor Lambda error.** Check the `mdc-mcp-gateway-interceptor`
  CloudWatch log group for errors.

### Missing Trusted_Context_Headers

The interceptor ran (visible in CloudWatch) but the headers did not arrive
at the Runtime.

- **Headers not in allowedRequestHeaders.** The Runtime target's
  `metadataConfiguration.allowedRequestHeaders` must list all three
  `X-Amzn-Bedrock-AgentCore-Runtime-Custom-*` header names.
- **Header name mismatch.** Names are case-sensitive in the target
  configuration. Verify exact match.

### SSE-framing regression

The MCP_Server must serve `json_response=True` (buffered JSON framing) for
Gateway interceptors to fire. If the framing reverts to SSE
(`text/event-stream`), the Gateway path silently loses all principal/scope
enforcement, and the developer proxy may also break.

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
- **HPC runbook:** `docs/runbooks/mcp-external-access-hpc.md`
- **Gateway verification report:** `docs/reports/mcp-external-access-gateway-verification.md`
