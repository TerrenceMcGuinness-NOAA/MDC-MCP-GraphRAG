# SDD Workflow: macOS MCP Client Onboarding (Phase 54)

**Goal:** Enable a researcher on a personal macOS laptop (with brew, SSH, CAC, and IAM credentials) to access all 51 MCP tools from their local Kiro IDE — no SSH remote to EC2, no RDHPCS hop.

**Status:** Planning  
**Target:** May 5, 2026 (test on Terry's Mac)

---

## Context

- Researcher uses macOS with Homebrew
- Already authenticated to our IAM account (same as Terry)
- Has CAC-enabled SSH tools
- Does NOT want to SSH remote into the EC2 as a dev workspace
- Wants MCP tools available in local Kiro on his laptop
- The `agentcore-kiro-proxy.py` is a single Python file (stdlib + boto3, 280 lines)
- AgentCore Runtime v6 is operational with 51 tools, pre-warmed connections

## Architecture

```
macOS Laptop (researcher)
    │
    │  Kiro spawns local child process (stdio)
    ▼
agentcore-kiro-proxy.py
    │
    │  boto3 invoke_agent_runtime (HTTPS + SigV4)
    │  Credentials from ~/.aws/credentials or SSO
    ▼
AgentCore Runtime v6 (microVM in VPC)
    │
    ├── Neptune (148K nodes, 2.8M rels)
    └── OpenSearch (206K docs, 17 indices)
```

No SSH tunnel. No EC2 hop. Direct HTTPS from laptop to AWS API.

## Prerequisites (researcher's Mac)

1. Python 3.9+ (comes with macOS or `brew install python`)
2. boto3 (`pip3 install boto3`)
3. AWS credentials configured (`~/.aws/credentials` or `aws sso login`)
4. Kiro IDE installed
5. The proxy script (single file download)

## Steps

### Step 1: Verify AWS credentials work

```bash
aws sts get-caller-identity
# Should show the account 903050880929
```

### Step 2: Verify AgentCore access

```bash
aws bedrock-agentcore-control list-agent-runtimes --region us-east-1
# Should return mdc_mcp_rag_server
```

### Step 3: Get the proxy script

```bash
mkdir -p ~/tools
# Copy from repo or download
cp /path/to/agentcore-kiro-proxy.py ~/tools/
# Or: curl from a shared location
```

### Step 4: Test the proxy manually

```bash
echo '{"jsonrpc":"2.0","id":"1","method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' | \
  python3 ~/tools/agentcore-kiro-proxy.py \
    --runtime-id "arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/mdc_mcp_rag_server-TMXDllG2Wi"
```

Should return a JSON-RPC response with server capabilities.

### Step 5: Configure Kiro mcp.json

Create or edit `~/.kiro/settings/mcp.json` (user-level) or `.kiro/settings/mcp.json` (workspace-level):

```json
{
  "mcpServers": {
    "mdc-mcp-rag": {
      "type": "command",
      "command": "python3",
      "args": [
        "/Users/USERNAME/tools/agentcore-kiro-proxy.py",
        "--runtime-id",
        "arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/mdc_mcp_rag_server-TMXDllG2Wi"
      ],
      "env": {
        "AWS_REGION": "us-east-1"
      },
      "autoApprove": [
        "get_workflow_structure",
        "get_system_configs",
        "describe_component",
        "analyze_code_structure",
        "find_dependencies",
        "trace_execution_path",
        "find_callers_callees",
        "trace_full_execution_chain",
        "find_env_dependencies",
        "search_documentation",
        "find_related_files",
        "explain_with_context",
        "get_knowledge_base_status",
        "search_ee2_standards",
        "get_operational_guidance",
        "explain_workflow_component",
        "get_code_context",
        "search_architecture",
        "find_similar_code",
        "get_change_impact",
        "trace_data_flow",
        "get_server_info",
        "mcp_health_check"
      ]
    }
  }
}
```

### Step 6: Verify in Kiro

- Open Kiro
- Check MCP Servers panel — should show green check for `mdc-mcp-rag`
- Test: ask Kiro a question that triggers a tool call (e.g., "what calls setuprad?")

## Validation Criteria

- [ ] `aws sts get-caller-identity` returns account 903050880929
- [ ] `aws bedrock-agentcore-control list-agent-runtimes` returns the runtime
- [ ] Manual proxy test returns JSON-RPC initialize response
- [ ] Kiro MCP panel shows green check
- [ ] `get_server_info` returns 51 tools
- [ ] `get_code_context` returns Neptune graph data
- [ ] `search_documentation` returns OpenSearch results
- [ ] `mcp_health_check` returns 9/9 healthy

## Risks

1. **AWS credential expiry** — If using SSO, tokens expire. User needs to re-run `aws sso login` periodically.
2. **Network** — Laptop must have outbound HTTPS to AWS API endpoints (standard internet access). No VPN required for AgentCore API.
3. **First-call latency** — If the microVM session has expired (15 min idle), first call takes ~5-10s for microVM boot + pre-warm. Subsequent calls are sub-second.
4. **boto3 version** — Needs boto3 recent enough to have `bedrock-agentcore` service definition. `pip3 install --upgrade boto3` if needed.

## What This Proves

If this works on Terry's Mac, it validates the Phase 1 deployment model from the MCP Access Architecture Proposal: any IAM-authenticated user with Python + boto3 can access all 51 MCP tools without any infrastructure beyond the single proxy script. No EC2 SSH, no VPN, no RDHPCS hop needed for the MCP knowledge base.

---

*Created May 4, 2026 — to be executed May 5, 2026*
