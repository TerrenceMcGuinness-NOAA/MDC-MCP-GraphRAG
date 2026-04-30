# Design Document: AgentCore MCP Deployment

## Overview

Deploy the MDC MCP RAG Server to AWS Bedrock AgentCore Runtime as a native MCP protocol server. AgentCore provides serverless microVM hosting with built-in session management, observability, and versioned deployments — replacing the hand-rolled `mcp-http-server.js` wrapper.

## Architecture

### Current State (Dev Bridge)

```
Kiro IDE → HTTP POST :3000/mcp → mcp-http-server.js → UnifiedMCPServer
                                        ↓
                              Neptune (graph) + OpenSearch (vectors)
```

- Manual `node src/mcp-http-server.js 3000 full` startup
- Security group hack for port 3000
- No scaling, no session management, no observability

### Target State (AgentCore Runtime)

```
Kiro IDE → AgentCore Runtime (MCP protocol, :8000/mcp)
                    ↓
           Isolated microVM session
                    ↓
           MCP Server (Node.js, 51+ tools)
                    ↓
           Neptune (graph) + OpenSearch (vectors)
           [VPC mode — private subnet connectivity]
```

- Deployed via `agentcore deploy` (CDK under the hood)
- MCP protocol native (JSON-RPC at :8000/mcp)
- Session isolation in microVMs
- Auto-scaling, observability via CloudWatch/X-Ray
- Versioned deployments with blue-green capability

## Key Design Decisions

### 1. MCP Protocol (Not HTTP)

AgentCore supports HTTP (:8080/invocations), MCP (:8000/mcp), and A2A (:9000/) protocols. Since our server is an MCP server consumed by Kiro, we use the native MCP protocol. This means:

- AgentCore handles MCP JSON-RPC transport
- Server listens on `0.0.0.0:8000/mcp`
- Must implement `/ping` returning `{"status": "Healthy"}`

### 2. VPC Network Mode

Neptune and OpenSearch are in private subnets with no internet access. The AgentCore runtime must be deployed in VPC mode to reach them:

```
AgentCore Runtime (VPC mode)
  ├── Subnet: same private subnets as Neptune/OpenSearch
  ├── Security Group: egress to Neptune :8182, OpenSearch :443
  └── No IGW/NAT required (all traffic stays in VPC)
```

### 3. Container Build (ARM64)

AgentCore requires ARM64 containers. The existing Dockerfile needs adaptation:

```dockerfile
FROM --platform=linux/arm64 node:20-slim

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --only=production

COPY src/ ./src/
COPY utils/ ./utils/
COPY config/ ./config/

ENV NODE_ENV=production
ENV DB_BACKEND=aws
ENV AWS_REGION=us-east-1

# MCP protocol: port 8000
EXPOSE 8000

# Health check for AgentCore
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD node -e "fetch('http://localhost:8000/ping').then(r=>r.ok?process.exit(0):process.exit(1)).catch(()=>process.exit(1))"

# MCP server entrypoint — must listen on 0.0.0.0:8000/mcp
CMD ["node", "src/mcp-agentcore-entrypoint.js"]
```

### 4. Entrypoint Adaptation

The current `mcp-http-server.js` uses Streamable HTTP on port 3000. For AgentCore MCP protocol, we need a thin entrypoint that:

1. Starts the MCP server on `0.0.0.0:8000/mcp` (JSON-RPC)
2. Implements `/ping` GET → `{"status": "Healthy"}`
3. Passes through to `UnifiedMCPServer` for all tool handling

File: `mcp_server_node/src/mcp-agentcore-entrypoint.js`

### 5. AgentCore CLI (npm, not pip)

Per the runtime guide, the pip-based `bedrock-agentcore-starter-toolkit` is deprecated. We use:

```bash
npm install -g @aws/agentcore
```

Configuration lives in `agentcore/agentcore.json`:

```json
{
  "agents": [{
    "name": "MdcMcpRagServer",
    "language": "Node",
    "framework": "Custom",
    "type": "create",
    "codeLocation": "mcp_server_node",
    "entrypoint": "src/mcp-agentcore-entrypoint.js",
    "build": "Container",
    "protocol": "MCP",
    "networkMode": "VPC"
  }]
}
```

## Components

### Component 1: MCP AgentCore Entrypoint

New file: `mcp_server_node/src/mcp-agentcore-entrypoint.js`

- Imports `UnifiedMCPServer` and initializes with `DB_BACKEND=aws`
- Starts MCP JSON-RPC server on `0.0.0.0:8000/mcp`
- Adds `/ping` health endpoint
- Passes environment variables for Neptune/OpenSearch endpoints

### Component 2: ARM64 Dockerfile

New file: `mcp_server_node/Dockerfile.agentcore`

- Based on `node:20-slim` for ARM64
- Copies server source, installs production deps
- Exposes port 8000, health check on `/ping`
- Entrypoint: `mcp-agentcore-entrypoint.js`

### Component 3: AgentCore Configuration

New file: `agentcore/agentcore.json`

- Defines the MdcMcpRagServer agent
- Container build type (ARM64 ECR image)
- MCP protocol, VPC network mode
- Environment variables for database endpoints

### Component 4: IAM Execution Role

Either auto-created by AgentCore or admin-created following the request pattern.

Trust: `bedrock-agentcore.amazonaws.com`

Permissions:
- ECR: `GetAuthorizationToken`, `BatchGetImage`, `GetDownloadUrlForLayer`
- CloudWatch Logs: `CreateLogGroup`, `CreateLogStream`, `PutLogEvents`
- X-Ray: `PutTraceSegments`, `PutTelemetryRecords`
- Neptune: `neptune-db:connect`
- OpenSearch: `es:ESHttp*` on `domain/mdc-mcp-rag-search/*`
- Secrets Manager: `GetSecretValue` on `mdc-mcp-rag/*`
- SSM: `GetParameter(s)` on `/mdc-mcp-rag/*`

### Component 5: Kiro MCP Client Update

Update `.kiro/settings/mcp.json`:

```json
{
  "mdc-mcp-rag-aws": {
    "type": "http",
    "url": "<agentcore-runtime-endpoint-url>/mcp",
    "disabled": false
  }
}
```

## Deployment Sequence

```
1. Install @aws/agentcore CLI
2. Build ARM64 container image
3. Push to ECR
4. Create agentcore/agentcore.json
5. agentcore deploy --plan (preview)
6. agentcore deploy (execute)
7. agentcore status (verify)
8. Update Kiro MCP config
9. Verify all tools via Kiro
10. Retire dev bridge
```

## Error Handling

| Error | Cause | Resolution |
|-------|-------|------------|
| `exec format error` | Container not ARM64 | Rebuild with `--platform linux/arm64` |
| `CREATE_FAILED` | IAM role or VPC issue | Check `agentcore status` for failureReason |
| Neptune timeout | Security group missing egress | Add egress rule for port 8182 |
| OpenSearch unreachable | Wrong subnet or SG | Verify VPC mode subnets match data subnets |
| 504 Gateway Timeout | Tool execution too slow | Check CloudWatch logs via `agentcore logs` |

## Testing Strategy

### Pre-deployment (local)
- Build container locally, run with `docker run --platform linux/arm64`
- Verify `/ping` returns healthy
- Verify MCP tools respond on port 8000

### Post-deployment
- `agentcore status` — runtime READY
- `agentcore invoke '{"prompt":"test"}'` — agent responds
- Kiro MCP client connects and lists all tools
- Representative tool invocations return valid results
- Compare results against dev bridge for parity

## Rollback Plan

AgentCore supports versioned deployments. If the new version fails:
1. Update the DEFAULT endpoint to point to the previous version
2. Or fall back to the dev bridge by re-enabling port 3000

## Data Safety

This deployment creates only AgentCore Runtime resources. It does NOT touch Neptune, OpenSearch, EFS, or S3. The CDK data safety rules in `.kiro/steering/05-cdk-data-safety.md` apply to any CDK operations triggered by `agentcore deploy`.
