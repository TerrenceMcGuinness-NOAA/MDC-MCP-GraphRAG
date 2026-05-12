# SDD Workflow: OpenSearch Connection Pool Exhaustion Fix (Phase 56)

**Goal:** Prevent OpenSearch from hitting its 1000-connection cluster limit when multiple AgentCore microVM sessions accumulate stale HTTP connections, causing `get_knowledge_base_status` and all vector-backed tools to fail with "Max connection limit reached. Limit = 1000".

**Status:** Planning  
**Target:** May 2026

---

## Context

On May 11-12, 2026, `get_knowledge_base_status` began returning:
```
Error getting status: "Unexpected server exception 'Max connection limit reached. Limit = 1000'"
```

### Root Cause Analysis

The same class of bug was fixed for **Neptune** in commit `6ad5094` (May 6, 2026):
- Neptune's Bolt driver had `maxConnectionPoolSize: 50` per microVM
- Multiple microVMs left running (from test timeouts, Kiro reconnects) accumulated connections
- Fix: reduced pool to 10, added `stop_session()` cleanup to test scripts

The **OpenSearch** adapter (`OpenSearchAdapter.js`) has no equivalent protection:
- Creates a bare `@opensearch-project/opensearch` `Client()` with no HTTP agent configuration
- No `maxSockets`, no `keepAlive` timeout, no connection limit
- Each AgentCore microVM opens HTTP connections to OpenSearch that persist until the microVM's idle timeout (900s)
- Repeated Kiro reconnection attempts (cold-start timeouts → retry → new session → new microVM) accumulate connections
- OpenSearch Service has a hard cluster limit of 1000 concurrent connections

### Timeline (from logs)

| Date | AgentCore cold-start | OpenSearch status |
|------|---------------------|-------------------|
| May 6-8 | 2-10s (warm, v6 deployed) | Healthy |
| May 11 | 82s (cold, exceeds Kiro 60s timeout) | Degraded — connection limit hit |
| May 12 | 82s cold / 2s warm | "Max connection limit reached. Limit = 1000" |

### Why Cold Starts Returned

The v6 deployment (commit `ee7a2d2`) baked the ONNX model into the container and pre-warmed connections, reducing cold starts from 75-96s to <1s. However, between May 8 and May 11, something on the AgentCore platform side caused cold-start latency to regress to ~82s. The code and Runtime version (v7) did not change. This caused Kiro's 60s MCP timeout to fire repeatedly, spawning new proxy sessions, each triggering a new microVM with fresh OpenSearch connections.

## Prior Art

- `6ad5094` — Neptune pool size 50 → 10, added session cleanup (May 6)
- `ee7a2d2` — Pre-warm connections in entrypoint before listen (May 4)
- `4266089` — Shared `dataAccess` instance, eliminated 3x duplicate connections (April 10)

## Steps

### Step 1: Research — Audit OpenSearch connection lifecycle

- Examine `OpenSearchAdapter.js` `connect()` method
- Determine what HTTP agent the `@opensearch-project/opensearch` client uses
- Check if there's a `close()` or `disconnect()` method available
- Check `mcp-agentcore-entrypoint.js` for shutdown/cleanup hooks

**Acceptance:** Document the current connection lifecycle and identify where connections leak.

### Step 2: Implement — Add HTTP agent configuration to OpenSearchAdapter

Configure the OpenSearch client with explicit connection limits:
```javascript
import { Agent } from 'https';

const agent = new Agent({
  maxSockets: 10,        // Match Neptune's pool size
  maxFreeSockets: 5,
  keepAlive: true,
  keepAliveMsecs: 30000, // 30s keepalive
  timeout: 60000,        // 60s socket timeout
});

this.client = new Client({
  ...AwsSigv4Signer({ ... }),
  node: this.endpoint,
  agent: agent,
});
```

**Acceptance:** OpenSearch client created with bounded connection pool (max 10 sockets per microVM).

### Step 3: Implement — Add graceful shutdown to MCP server entrypoint

In `mcp-agentcore-entrypoint.js`, add SIGTERM/SIGINT handler that:
1. Closes the OpenSearch client (`client.close()`)
2. Closes the Neptune driver (`driver.close()`)
3. Exits cleanly

**Acceptance:** On microVM shutdown (idle timeout or explicit stop), all database connections are released.

### Step 4: Implement — Add connection cleanup to parity test scripts

Mirror the Neptune fix from `6ad5094` — ensure `tools/mcp-parity-test.py` calls `stop_session()` and the test harness cleans up even on timeout/error.

**Acceptance:** Parity tests cannot leak OpenSearch connections.

### Step 5: Validate — Verify connection count under load

1. Start fresh AgentCore session
2. Run `mcp_health_check({ deep: true })`
3. Run `get_knowledge_base_status()`
4. Check OpenSearch connection count via CloudWatch `ActiveConnectionCount` metric
5. Stop session, verify connections drop

**Acceptance:** Connection count stays below 20 per microVM session; `get_knowledge_base_status` returns successfully.

### Step 6: Validate — Simulate reconnection storm

1. Start 5 sequential proxy sessions (simulating Kiro reconnects)
2. Verify total OpenSearch connections stay bounded (5 × 10 = 50 max)
3. Wait for idle timeout, verify connections release

**Acceptance:** Even with 10 concurrent microVMs, total connections stay well under 1000.

### Step 7: Deploy — Update AgentCore Runtime

1. Build new container image with the fixes
2. Push to ECR
3. Update AgentCore Runtime (will become v8)
4. Verify with `mcp_health_check` and `get_knowledge_base_status`

**Acceptance:** Runtime v8 deployed, all 51 tools pass, no connection limit errors.

### Step 8: Document — Update CHANGELOG

Add entry under new version documenting:
- The OpenSearch connection pool fix
- The graceful shutdown handler
- The parity with the Neptune fix from `6ad5094`

**Acceptance:** CHANGELOG updated with fix details and root cause.

## Validation Criteria

- [ ] `get_knowledge_base_status()` returns successfully (no "Max connection limit" error)
- [ ] `mcp_health_check({ deep: true })` shows 9/9 healthy
- [ ] OpenSearch `ActiveConnectionCount` stays below 100 even after multiple reconnects
- [ ] Graceful shutdown releases all connections (verified via CloudWatch)
- [ ] Parity tests clean up connections on completion and on error/timeout

## Risks

1. **OpenSearch client `close()` behavior** — Need to verify `@opensearch-project/opensearch` supports explicit close. If not, rely on agent socket limits.
2. **SigV4 credential refresh** — Limiting keepAlive may interact with credential rotation. Test with long-running sessions.
3. **Performance impact** — Reducing max sockets from unlimited to 10 could bottleneck parallel queries. Unlikely given Node.js single-threaded nature, but benchmark.

## Relationship to Proxy Keepalive (v1.1.0)

The `agentcore-kiro-proxy.py` v1.1.0 patch (applied today, May 12) addresses the **Kiro-side** timeout by:
- Answering `initialize` locally (instant)
- Background-warming AgentCore before `tools/list` arrives
- Keepalive pings every 45s to prevent cold starts

This Phase 56 addresses the **server-side** connection accumulation that happens when cold starts DO occur and multiple microVMs pile up.

---

*Created May 12, 2026*
