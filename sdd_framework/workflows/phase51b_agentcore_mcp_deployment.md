# Phase 51b: AgentCore MCP Server Deployment

## Overview

Deploy the MDC MCP RAG Server to AWS Bedrock AgentCore Runtime, replacing the
hand-rolled `mcp-http-server.js` wrapper with a managed AWS deployment. AgentCore
handles MCP transport, session isolation (microVMs), scaling, and lifecycle —
aligning with our IaC-first principle.

## Current State (Development Bridge)

- `mcp-http-server.js` — stateless HTTP wrapper on port 3000
- Manual `node src/mcp-http-server.js 3000 full` startup
- Security group hack for port 3000 from bastion
- Works but not production-ready, not IaC-managed

## Target State (AgentCore Runtime)

- MCP server deployed as AgentCore Runtime container (ARM64 microVM)
- MCP protocol at `0.0.0.0:8000/mcp` (AgentCore MCP convention)
- Session isolation in microVMs with configurable lifecycle
- Auto-scaling managed by AgentCore
- Deployed via AgentCore Power MCP tools (`create_agent_runtime`)
- Kiro connects via AgentCore Runtime endpoint URL
- Observability via CloudWatch/X-Ray

## Prerequisites

- Phase 51 validation — COMPLETE (45/45 tools pass with DB_BACKEND=aws)
- Phase 50b — COMPLETE (Neptune + OpenSearch loaded)
- Phase 53 Track B — COMPLETE (full re-ingestion: 164,916 nodes, 2,941,593 rels)
- AgentCore Power MCP server connected (52 tools)
- AWS credentials with `bedrock-agentcore:*` permissions (explicit deny removed)
- Service-linked roles created (all 4)
- IAM trust policy updated on `mdc-mcp-rag-ecs-task-role`

## Tooling Note

The original SDD referenced `bedrock-agentcore-starter-toolkit` (pip) which is
**deprecated**. The replacement is `@aws/agentcore` (npm CLI). However, we are
using neither CLI directly — instead we deploy via the **AgentCore Kiro Power**
MCP tools which call the APIs programmatically. This is the safest path because
it only touches AgentCore resources and cannot modify Neptune/OpenSearch/VPC.

| Deprecated (pip) | Current (npm CLI) | Our Approach (Power MCP) |
|---|---|---|
| `pip install bedrock-agentcore-starter-toolkit` | `npm install -g @aws/agentcore` | Kiro Power: `aws-agentcore` |
| `agentcore launch` | `agentcore deploy` | `create_agent_runtime` tool |
| `agentcore configure` | `agentcore create` | `.bedrock_agentcore.yaml` (manual) |
| `agentcore status` | `agentcore status` | `get_agent_runtime` tool |
| `agentcore invoke` | `agentcore invoke` | `invoke_agent_runtime` tool |

## Steps

### Step 0: Install and configure AgentCore tooling ✅
- Tag: configure
- AgentCore Power MCP server installed and connected (52 tools)
- `.bedrock_agentcore.yaml` created with VPC/MCP/ARM64 configuration
- **Completed**: April 23, 2026

### Step 1: Create MCP AgentCore entrypoint ✅
- Tag: implement
- Created `mcp_server_node/src/mcp-agentcore-entrypoint.js`
- Streamable HTTP on `0.0.0.0:8000/mcp` (AgentCore MCP convention)
- `/ping` health endpoint returning `{"status": "Healthy"}`
- Shared data access across stateless requests
- **Completed**: April 23, 2026

### Step 2: Create ARM64 Dockerfile ✅
- Tag: implement
- Created `mcp_server_node/Dockerfile.agentcore`
- Base: `node:20-slim` for `linux/arm64`
- Production deps only, 302MB compressed
- Healthcheck on `/ping`, CMD `node src/mcp-agentcore-entrypoint.js`
- **Completed**: April 23, 2026

### Step 3: Build and push container image ✅
- Tag: implement
- Built ARM64 image via `docker buildx`
- Pushed to `903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:agentcore`
- Verified locally: `/ping` returns healthy, MCP server starts
- **Completed**: April 23, 2026

### Step 4: Resolve IAM permissions ✅
- Tag: configure
- Updated IAM trust policy: `bedrock-agentcore.amazonaws.com` added to `mdc-mcp-rag-ecs-task-role`
- Admin created all 4 service-linked roles:
  - `AWSServiceRoleForBedrockAgentCoreGatewayNetwork` (service: `bedrock-agentcore.amazonaws.com`)
  - `AWSServiceRoleForBedrockAgentCoreNetwork` (service: `network.bedrock-agentcore.amazonaws.com`)
  - `AWSServiceRoleForBedrockAgentCoreRuntimeIdentity` (service: `runtime-identity.bedrock-agentcore.amazonaws.com`)
  - `AWSServiceRoleForBedrockAgentCoreIdentity` (service: `identity-network.bedrock-agentcore.amazonaws.com`)
- Admin removed explicit deny on `bedrock-agentcore:*` (Option C from permissions request)
- Verified: `aws bedrock-agentcore-control list-agent-runtimes` returns empty list (no access denied)
- **Completed**: April 30, 2026

### Step 5: Deploy to AgentCore Runtime ⬜ (NEXT)
- Tag: implement
- Use AgentCore Power MCP tool: `create_agent_runtime`
- Parameters:
  ```json
  {
    "agent_runtime_name": "mdc_mcp_rag_server",
    "container_uri": "903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:agentcore",
    "server_protocol": "MCP",
    "network_mode": "VPC",
    "subnets": ["subnet-0e13af6b3a9a6416f", "subnet-024fd9b597b3075a5", "subnet-04447750c61bd7e06"],
    "security_groups": ["sg-096489a0876cc78c1"],
    "role_arn": "arn:aws:iam::903050880929:role/mdc-mcp-rag-ecs-task-role",
    "idle_timeout": 900,
    "max_lifetime": 28800
  }
  ```
- Verify: `get_agent_runtime` shows status READY
- Record the DEFAULT endpoint URL
- **CDK Safety**: This only creates AgentCore Runtime resources — no Neptune/OpenSearch impact

### Step 6: Validate deployment ⬜
- Tag: validate
- Verify health: invoke `/ping` on AgentCore endpoint
- Verify tools: invoke representative set via `invoke_agent_runtime`:
  - `get_server_info`, `search_documentation`, `get_code_context`, `mcp_health_check`
- Compare responses against dev bridge for parity
- Check CloudWatch logs for errors

### Step 7: Update Kiro MCP client configuration ⬜
- Tag: configure
- Update `.kiro/settings/mcp.json` with AgentCore Runtime endpoint URL
- Keep dev bridge config as disabled fallback
- Verify Kiro connects and all 51+ tools are listed

### Step 8: Retire development bridge ⬜
- Tag: implement
- Stop `mcp-http-server.js` process on port 3000
- Remove security group rule for port 3000 inbound
- Keep `mcp-http-server.js` code as dev-only fallback (do not delete)

### Step 9: Update documentation and SDD ⬜
- Tag: document
- Update CHANGELOG with deployment entry
- Update steering files if endpoint or workflow changed
- Record SDD session completion

## Total Steps: 10 (Steps 0-9)

## Completion Status

| Step | Status | Date |
|------|--------|------|
| 0 | ✅ Complete | 2026-04-23 |
| 1 | ✅ Complete | 2026-04-23 |
| 2 | ✅ Complete | 2026-04-23 |
| 3 | ✅ Complete | 2026-04-23 |
| 4 | ✅ Complete | 2026-04-30 |
| 5 | ⬜ Next | — |
| 6 | ⬜ Pending | — |
| 7 | ⬜ Pending | — |
| 8 | ⬜ Pending | — |
| 9 | ⬜ Pending | — |

## Acceptance Criteria

1. MCP server deployed via AgentCore Power `create_agent_runtime` (managed runtime)
2. Kiro connects to AgentCore endpoint (not localhost:3000)
3. All 51+ tools respond correctly via AgentCore Runtime
4. No manual port forwarding or security group hacks required
5. Session lifecycle: idle timeout 900s, max lifetime 28800s
6. Observability via CloudWatch/X-Ray

## Environment Variables (Container)

| Variable | Value | Purpose |
|----------|-------|---------|
| DB_BACKEND | aws | Route to Neptune + OpenSearch |
| OPENSEARCH_ENDPOINT | vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com | Vector search |
| NEPTUNE_ENDPOINT | wss://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182 | Graph queries |
| AWS_REGION | us-east-1 | AWS region |
| NODE_ENV | production | Production mode |

## AWS Resources

| Resource | ARN/ID | Purpose |
|----------|--------|---------|
| ECR Image | `903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:agentcore` | Container image |
| Execution Role | `arn:aws:iam::903050880929:role/mdc-mcp-rag-ecs-task-role` | Runtime permissions |
| Subnets | `subnet-0e13af6b3a9a6416f`, `subnet-024fd9b597b3075a5`, `subnet-04447750c61bd7e06` | Private VPC subnets |
| Security Group | `sg-096489a0876cc78c1` | Network access (Neptune 8182, OpenSearch 443) |

## CLI Reference

```bash
# Verify permissions (correct subcommand is bedrock-agentcore-control, NOT bedrock-agentcore)
aws bedrock-agentcore-control list-agent-runtimes --region us-east-1

# Check runtime status
aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id <ID> --region us-east-1
```

> **Note**: The AWS CLI subcommand is `bedrock-agentcore-control`, not `bedrock-agentcore`.
> The IAM action namespace (`bedrock-agentcore:*`) differs from the CLI subcommand name.

## Reference

- AgentCore docs: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-mcp.html
- Kiro Power: aws-agentcore (52 tools)
- Permissions request: `docs/agentcore-permissions-request.md`
- Service-linked role request: `docs/agentcore-service-linked-role-request.md`
- Current bridge: `mcp_server_node/src/mcp-http-server.js`
- Kiro Spec: `.kiro/specs/agentcore-mcp-deployment/`

## Branch

`develop_aws`
