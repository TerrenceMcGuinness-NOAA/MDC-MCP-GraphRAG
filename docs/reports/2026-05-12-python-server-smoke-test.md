# Python MCP Server — First Deployment Smoke Test

**Date:** 2026-05-12
**Operator:** terry.mcguinness@noaa.gov
**Scope:** Phase B4 + early B11 — deploy the Python MCP server (utility module
only) to a **new** AgentCore Runtime alongside the existing Node.js runtime
as a first-deployment smoke test. The existing Node.js runtime was not
modified.

## Runtime identity

| Field | Value |
|---|---|
| Runtime name | `mdc_mcp_rag_server_python` |
| Runtime ID | `mdc_mcp_rag_server_python-v5K2F8BGrN` |
| Runtime ARN | `arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/mdc_mcp_rag_server_python-v5K2F8BGrN` |
| Version | `2` (v1 was the initial deploy with stateful FastMCP; v2 after the stateless fix) |
| Status | `READY` |
| Protocol | `MCP` |
| Network | `VPC` — subnets `subnet-0e13af6b3a9a6416f` (us-east-1a), `subnet-04447750c61bd7e06` (us-east-1b); sg `sg-096489a0876cc78c1` |
| Execution role | `arn:aws:iam::903050880929:role/mdc-mcp-rag-ecs-task-role` |
| Lifecycle | `idleRuntimeSessionTimeout=900s`, `maxLifetime=28800s` (matches Node.js runtime) |
| Container URI | `903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:python-utility-v1` |
| Image digest (final v2) | `sha256:f02782c9b2cffe990878d9b478e2ca81fb5b5105d52493b94f538e2e104d6c7a` |
| Workload identity ARN | `arn:aws:bedrock-agentcore:us-east-1:903050880929:workload-identity-directory/default/workload-identity/mdc_mcp_rag_server_python-v5K2F8BGrN` |
| Existing Node.js runtime | `mdc_mcp_rag_server-TMXDllG2Wi` v10 READY — **unchanged** |

## Build / push / create timing

| Phase | Duration |
|---|---|
| Initial `docker build --platform linux/arm64` (v1) | 124 s |
| Initial `docker push` (v1 digest `sha256:fbfe71…`) | 16 s |
| `CreateAgentRuntime` → READY | 12 s |
| Rebuild after stateless-HTTP fix | 78 s |
| Repush (v2 digest `sha256:f02782…`) | 15 s |
| `UpdateAgentRuntime` v1 → v2 → READY | 18 s |

## Root-cause finding: stateless_http required

The v1 deployment surfaced an `-32010 "Received error (500) from runtime"`
from AgentCore on every `tools/call`. CloudWatch logs for the runtime showed
FastMCP returning `400 Bad Request` on the first of every pair of requests,
then `200 OK` on the second. Raw payload from `aws bedrock-agentcore
invoke-agent-runtime` confirmed:

```json
{"jsonrpc":"2.0","error":{"code":-32010,
 "message":"Received error (500) from runtime. …"}}
```

**Root cause:** FastMCP's `streamable-http` transport in version 3.2.4
defaults to **stateful** mode (`stateless_http=False`). In stateful mode, the
server generates its own `Mcp-Session-Id` on the initialize response and
rejects any other session ID on subsequent requests with `HTTP 400`. AgentCore,
per [runtime-mcp-protocol-contract](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-mcp-protocol-contract.html),
generates its **own** session ID per request and expects the server to accept
it. The 400 bubbles up to AgentCore as a 500-class runtime error.

**Fix:** `src/mcp_server.py` now passes `stateless_http=True` to `mcp.run()`
by default. An `MCP_STATELESS_HTTP=false` environment variable opts back into
stateful mode for local development (elicitation / sampling test flows). The
195-test suite continues to pass with the change.

## Step 6 — `mcp_health_check({})` — PASS

Invoked via `tools/agentcore-kiro-proxy.py --runtime-id <arn>`, returned
verbatim:

```markdown
# Server Health Check

**Overall Status**: HEALTHY (2/3 components healthy)

[OK] **Base Server**: healthy
[OK] **Utility Tools**: healthy
[OFF] **Data Access Layer**: disabled - No data access layer (degraded-mode boot)
```

Matches the acceptance criteria exactly:

- Overall Status = `HEALTHY` ✓
- Base Server row = `healthy` ✓
- Utility Tools row = `healthy` ✓
- Data Access Layer row = `disabled` with the documented degraded-mode
  explanation ✓
- 3 total component rows ✓ (not 9 — the utility-only build has no DB
  adapters, no semantic/code-analysis/etc. tool rows yet)

## Step 7 — `get_server_info({})` — PASS

Same invocation pattern, returned verbatim:

```markdown
# MDC MCP/RAG Server v1.0.0

**Total Tools**: 4
**Active Modules**: 1 of 9

## Active Modules
- `utility`

## Registered Tools
- `get_health_trend`
- `get_quality_metrics`
- `get_server_info`
- `mcp_health_check`
```

Matches expected: version **1.0.0**, **4** tools registered, active module
**`utility`**.

## Issues encountered

1. **FastMCP defaulting to stateful mode** — documented above. Detected by
   reading CloudWatch logs for the runtime (saw 400 pattern before the 200),
   then the raw `invoke-agent-runtime` response body (saw the -32010 wrapper
   around a 500). Fixed by setting `stateless_http=True`.
2. **`/ping` endpoint** — the user's runbook suggested a local
   `curl http://localhost:8000/ping` check. FastMCP's streamable-http
   transport does not expose `/ping`; the local boot test was reframed to a
   raw MCP `initialize` POST, which returned a valid `serverInfo` response.
   AgentCore's own health probe uses MCP protocol (not `/ping`) for MCP-mode
   runtimes, so the absence of `/ping` is not a deployment blocker.
3. **Proxy `stop_runtime_session` returns `ResourceNotFoundException`** —
   harmless, logged at WARNING. The microVM session is torn down by
   AgentCore between invocations when there is nothing to keep it alive;
   trying to stop it after it's gone produces the not-found error. This is
   the Phase-56 behaviour the proxy already handles gracefully.
4. **Proxy's `invoke` method is resilient to cold-start but not to
   server-level errors** — the proxy's `parse_sse` skips frames that don't
   have a `data:` prefix, which is what triggered the confusing
   `"Empty SSE response"` error when AgentCore returned a plain-JSON
   `-32010` envelope. Not a blocker here (the symptom led us to the right
   root cause), but a potential proxy improvement in a future session:
   surface the raw JSON-RPC error verbatim when the SSE parse returns empty
   but the HTTP body is non-empty.

## Configuration changes committed as part of this deploy

- `mcp_server_python/Dockerfile` — `CMD` now `python -m src.mcp_server --modules utility`.
- `mcp_server_python/src/mcp_server.py` — `mcp.run()` now passes
  `stateless_http=<MCP_STATELESS_HTTP, default True>`. Added `import os`.

## What was NOT changed

- `mcp_server_node/` — untouched. Node.js runtime `mdc_mcp_rag_server-TMXDllG2Wi`
  is still on v10 READY.
- `.kiro/settings/mcp.json` — still points at the Node.js runtime (operator
  will flip this manually once we're ready to cut over).
- ECR tags `latest`, `agentcore-v8`, `agentcore` — untouched.
- Any other AgentCore runtime.

## Rollback plan

If the Python runtime exhibits any issue during follow-on testing, it is
safe to delete entirely — the Node.js runtime is the production target and
was never touched. To remove the staging runtime:

```bash
aws bedrock-agentcore-control delete-agent-runtime \
    --region us-east-1 \
    --agent-runtime-id mdc_mcp_rag_server_python-v5K2F8BGrN
```

The ECR image tag `python-utility-v1` can remain in place; it will be
reused by the next staging deploy.

## Next steps (out of scope for this session)

1. Operator flips `.kiro/settings/mcp.json` to the new runtime ARN to
   exercise it end-to-end from Kiro.
2. Port Phase B5 (`semantic_search`) and rebuild the image to `python-v1`
   (or `python-utility-semantic-v1`) for the next smoke test.
3. Enable CloudWatch metrics dashboard for the Python runtime to track
   cold-start latency and invocation count in parallel with the Node.js
   runtime.
