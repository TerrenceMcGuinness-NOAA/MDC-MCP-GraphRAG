# Kiro ↔ AgentCore — Native Connection Options (No Proxy)

**Date**: May 7, 2026
**Context**: Evaluating whether the `agentcore-kiro-proxy.py` stdio bridge can be
replaced with a native Kiro-to-AgentCore connection pattern.
**Status**: Research — no changes proposed yet

---

## 1. How Kiro Reaches This EC2 Instance (Current Setup)

Your local Kiro IDE is bridged to this EC2 through a layered tunnel:

```
[Your laptop Kiro]
   │
   │ Kiro SSH Remote Development (not VS Code tunnels / WSL)
   ▼
[localhost:2222]  ← port forwarded by SecureCRT
   │
   │ SSO-authenticated jump box (DevQ)
   │ forwards local 2222 → 10.40.136.39:22 (this EC2)
   ▼
[EC2 ec2-user@10.40.136.39]
   │
   │ Kiro agent runs here, reads .kiro/ + .github/ config from workspace
   │ Spawns MCP subprocesses (stdio) or opens HTTPS (remote MCP)
   ▼
[AWS APIs / MCP backends]
```

Your `~/.ssh/config` on the laptop:
```
Host AWS_jumpbox
    HostName localhost
    Port 2222
    User ec2-user
    IdentityFile ~/.ssh/awskeypairone.pem
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
```

The jump box is SSO-authenticated (IAM Identity Center), and port 2222 on your
laptop is forwarded to this EC2's port 22 via SecureCRT. So Kiro's credentials
inside the EC2 are the EC2 instance's IAM role — not your SSO identity.

---

## 2. Kiro's Two MCP Transport Modes

From `kiro.dev/docs/mcp/configuration`, Kiro supports two MCP transport types:

### A. Local (stdio)
```json
{
  "mcpServers": {
    "local-server": {
      "command": "python3",
      "args": ["proxy.py", "--runtime-id", "..."],
      "env": {"AWS_REGION": "us-east-1"}
    }
  }
}
```
This is what `agentcore-kiro-proxy.py` uses. Kiro spawns the Python process,
writes JSON-RPC to its stdin, reads responses from stdout.

### B. Remote (Streamable HTTP)
```json
{
  "mcpServers": {
    "remote-server": {
      "url": "https://endpoint.example.com/mcp",
      "headers": {
        "Authorization": "Bearer ${SECRET_TOKEN}"
      }
    }
  }
}
```
Added in October 2025 per the Kiro blog "Introducing remote MCP servers."
Kiro speaks MCP Streamable HTTP (Server-Sent Events) directly to the URL,
attaching the `headers` block to every request. Variable expansion via
`${ENV_VAR}` is supported.

**This is the native path.** No proxy, no subprocess.

---

## 3. AgentCore Runtime IS A Native MCP Streamable HTTP Endpoint

From the AWS docs (`runtime-mcp.html`):

> When you configure a Bedrock AgentCore Runtime with the MCP protocol, the
> service expects MCP server containers to be available at the path
> `0.0.0.0:8000/mcp` ... The platform automatically adds an `Mcp-Session-Id`
> header for any request without one, so MCP clients can maintain connection
> continuity to the same AgentCore Runtime session.

### The Public MCP URL Format

Any AgentCore Runtime configured with `protocol: MCP` is reachable at:

```
https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{ENCODED_ARN}/invocations?qualifier=DEFAULT
```

Where `{ENCODED_ARN}` is the runtime ARN with `:` → `%3A` and `/` → `%2F`.

For our runtime:
```
ARN:     arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/mdc_mcp_rag_server-TMXDllG2Wi
Encoded: arn%3Aaws%3Abedrock-agentcore%3Aus-east-1%3A903050880929%3Aruntime%2Fmdc_mcp_rag_server-TMXDllG2Wi
URL:     https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/arn%3A...TMXDllG2Wi/invocations?qualifier=DEFAULT
```

Any MCP-compliant Streamable HTTP client — Kiro, Cursor, Claude Desktop, MCP
Inspector — can speak this endpoint directly.

---

## 4. Authentication Requirements — The Critical Gap

AgentCore Runtime does NOT accept IAM SigV4 for MCP invocations. It accepts
**only two** inbound auth modes for MCP:

| Auth Mode | Accepted By AgentCore Runtime? | Works With Kiro Native? |
|-----------|--------------------------------|-------------------------|
| IAM SigV4 (`invoke_agent_runtime` API) | ✅ Yes, but via AWS SDK only | ❌ No — Kiro's remote MCP doesn't speak SigV4 |
| Bearer JWT (OAuth) — Cognito, Auth0 | ✅ Yes | ✅ Yes — via `Authorization: Bearer` header |
| None (public) | ❌ No, not supported for MCP | — |

**This is why we built the proxy.** The proxy uses boto3's `invoke_agent_runtime`
call, which signs with SigV4 using the EC2's IAM role. Kiro's native remote MCP
transport does not support SigV4 — it only supports static/Bearer `headers`.

### How Others Are Doing It (AWS re:Post Q&A)

The re:Post question "Exposing Bedrock AgentCore MCP runtime for external MCP
client access" (Feb 2026) confirms:

1. You must deploy the runtime with OAuth inbound auth (Cognito or Auth0)
2. You obtain a JWT Bearer token via the OAuth provider
3. You configure the MCP client with the runtime URL and
   `Authorization: Bearer <token>` header
4. Tokens are short-lived (Cognito: ~1 hour) — a wrapper script refreshes

---

## 5. Current Runtime Auth Mode — What We Have

From `mcp_server_node/.bedrock_agentcore.yaml`:

```yaml
authorizer_configuration: null
oauth_configuration: null
api_key_env_var_name: null
aws_jwt:
  enabled: false
```

→ Our runtime has **no inbound authorizer configured**, which means it falls
back to IAM auth — only callable via `invoke_agent_runtime` with SigV4. That's
why the proxy is necessary today.

---

## 6. Three Paths Forward (Listed, Not Yet Chosen)

### Path A — Keep the Python Proxy (Current State)
**Pros**:
- Works now
- Uses EC2 IAM role directly (no token management)
- Zero additional AWS resources or cost

**Cons**:
- Non-standard — not how AWS documents MCP client access
- Extra process per Kiro session
- Our maintenance burden (200 lines of Python)

### Path B — Configure Cognito Inbound Auth + Native Remote MCP
**Pros**:
- Idiomatic AWS/Kiro pattern — what re:Post experts recommend
- Kiro speaks MCP Streamable HTTP directly to AgentCore (no proxy)
- Standard OAuth Bearer token flow

**Cons**:
- Need to stand up a Cognito User Pool + App Client (CDK stack)
- Token refresh required every ~1 hour (wrapper script or long-lived token)
- Additional IaC to maintain (small)
- Kiro's `${ENV_VAR}` expansion in headers would reference a token env var
  — requires refresh mechanism

Configuration would look like:
```json
{
  "mcpServers": {
    "mdc-mcp-rag": {
      "url": "https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/arn%3A...TMXDllG2Wi/invocations?qualifier=DEFAULT",
      "headers": {
        "Authorization": "Bearer ${COGNITO_ACCESS_TOKEN}"
      }
    }
  }
}
```

### Path C — AgentCore Gateway In Front of the Runtime
AgentCore Gateway is a separate service. It provides:
- A single MCP endpoint that fronts multiple targets (Lambdas, API GW, other MCP servers)
- Built-in Cognito/custom JWT inbound auth
- Tool filtering, header propagation, interceptors, policy engine
- Cross-account resource policies

A Gateway target pointed at our runtime would give us:
- Auth at the Gateway, not the Runtime
- Observability and policy enforcement per request
- A stable MCP URL that survives runtime redeployments

**Pros**:
- Most AWS-native pattern for enterprise MCP exposure
- Centralized auth, policy, observability
- Tool-level access control via Cedar policies

**Cons**:
- Additional service ($ + latency)
- More moving parts than strictly needed for one runtime
- Overkill if we only have one MCP server

---

## 7. How the Four Installed Powers Connect (For Comparison)

All four Powers in your `.kiro/settings/mcp.json` use the **local stdio** pattern
via `uvx` — they are NOT remote MCPs:

| Power | Command | Transport |
|-------|---------|-----------|
| `iam-policy-autopilot` | `uvx iam-policy-autopilot@latest mcp-server` | stdio |
| `aws-iac-mcp-server` | `uvx awslabs.aws-iac-mcp-server@latest` | stdio |
| `agentcore-mcp-server` | `uvx awslabs.amazon-bedrock-agentcore-mcp-server@latest` | stdio |
| `opensearch-launchpad` | `bash ... uvx opensearch-launchpad@latest` | stdio |

These are published Python packages that Kiro spawns as subprocesses. They
authenticate to AWS using the EC2's IAM role credentials (via the standard
AWS SDK credential chain) — no proxy needed because the MCP server itself is
local and reads credentials from the environment.

**Key insight**: The Powers ARE running locally and using the EC2's IAM role
directly. They are not "connecting to AWS-hosted MCP servers" — they are
AWS-authored tools that happen to call AWS APIs. That's a different pattern
from what we're doing (hosting our own MCP server on AgentCore Runtime).

---

## 8. Ranked Recommendation Sketch

If the goal is "standard AWS/Kiro practice," the ranking is:

1. **Path B (Cognito + Native Remote MCP)** — idiomatic, documented, what AWS
   experts recommend on re:Post. The token refresh friction is real but solvable.
2. **Path C (AgentCore Gateway)** — richer features, right choice if we ever
   expose to multiple users or want policy enforcement per tool call.
3. **Path A (Keep Proxy)** — works, but non-standard. Fine for a single
   developer; does not scale to a team.

For a single developer environment on a dev EC2, Path A is pragmatic. For the
"10-user cohort Phase 1" in our architecture proposal
(`docs/mcp-access-architecture-proposal.md`), Path B or C becomes necessary.

---

## 9. Open Questions for You

1. **Who consumes this MCP?** Just you on this EC2, or the 10-user cohort from
   the architecture proposal? The answer drives the Path B vs C choice.
2. **Auth provider preference?** Cognito (we have an account) or Auth0 (supports
   DCR, simpler Kiro UX but external SaaS)?
3. **Is token refresh acceptable?** A 1-hour Cognito token means a wrapper
   script and some mild DevEx friction. Long-lived tokens have their own tradeoffs.
4. **Is the Gateway's extra cost justified** for a single runtime today, knowing
   we may add more MCP servers later?

---

## 10. References

- Kiro remote MCP blog: https://kiro.dev/blog/introducing-remote-mcp/
- Kiro MCP config: https://kiro.dev/docs/mcp/configuration
- AgentCore MCP Runtime deploy: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-mcp.html
- re:Post external MCP client access: https://www.repost.aws/questions/QUqqdbdQzhSQOyNTKrfDJ_Ow
- AgentCore Gateway overview: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html
- Our architecture proposal: `docs/mcp-access-architecture-proposal.md`
- Current proxy source: `tools/agentcore-kiro-proxy.py`
- Current runtime config: `mcp_server_node/.bedrock_agentcore.yaml`

*Content synthesized from multiple AWS and Kiro documentation pages; rephrased
for compliance with licensing restrictions.*
