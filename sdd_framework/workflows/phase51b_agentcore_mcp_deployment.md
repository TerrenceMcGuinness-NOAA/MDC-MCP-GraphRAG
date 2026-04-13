# Phase 51b: AgentCore MCP Server Deployment

## Overview

Deploy the MDC MCP RAG Server to AWS Bedrock AgentCore Runtime, replacing the
hand-rolled `mcp-http-server.js` wrapper with a managed AWS deployment. AgentCore
handles HTTP transport (Streamable HTTP), auth, scaling, and lifecycle via
CloudFormation — aligning with our IaC-first principle.

## Current State (Development Bridge)

- `mcp-http-server.js` — stateless HTTP wrapper on port 3000
- Manual `node src/mcp-http-server.js 3000 full` startup
- Security group hack for port 3000 from bastion
- Works but not production-ready, not IaC-managed

## Target State (AgentCore Runtime)

- MCP server deployed as AgentCore Runtime container
- Streamable HTTP at `0.0.0.0:8000/mcp` (AgentCore default)
- Auth via AgentCore Gateway (Cognito, IAM, or OAuth)
- Scaling and lifecycle managed by AgentCore
- Deployed via `agentcore launch` (CloudFormation under the hood)
- Kiro connects via AgentCore endpoint URL

## Prerequisites

- Phase 51 validation — COMPLETE (45/45 tools pass with DB_BACKEND=aws)
- Phase 50b — COMPLETE (Neptune + OpenSearch loaded)
- `bedrock-agentcore-starter-toolkit` installed
- AWS credentials with AgentCore permissions

## Steps

### Step 0: Install AgentCore toolkit
- Tag: configure
- `pip install bedrock-agentcore-starter-toolkit`
- Verify: `agentcore --version`

### Step 1: Wrap UnifiedMCPServer with BedrockAgentCoreApp
- Tag: implement
- Create `mcp_server_node/src/agentcore-entrypoint.py` (or .js equivalent)
- Wrap the MCP server with AgentCore's entrypoint pattern
- The server already uses Streamable HTTP — AgentCore expects this at 0.0.0.0:8000/mcp
- Pass DB_BACKEND=aws and endpoint env vars

### Step 2: Create AgentCore configuration
- Tag: configure
- `agentcore configure --entrypoint agentcore-entrypoint --non-interactive`
- Creates `.bedrock_agentcore.yaml`
- Configure environment variables for OpenSearch, Neptune endpoints

### Step 3: Test locally with AgentCore dev server
- Tag: validate
- `agentcore dev`
- `agentcore invoke --dev '{"prompt": "test"}'`
- Verify all 51 tools respond

### Step 4: Deploy to AgentCore Runtime
- Tag: implement
- `agentcore launch`
- Monitor deployment via `agentcore status`
- Verify endpoint URL

### Step 5: Configure Kiro to use AgentCore endpoint
- Tag: configure
- Update `.kiro/settings/mcp.json` with AgentCore endpoint URL
- Test connection from Kiro

### Step 6: Configure AgentCore Gateway (optional)
- Tag: configure
- Set up auth (Cognito or IAM) for multi-user access
- Configure rate limiting and access control

### Step 7: Remove development bridge
- Tag: implement
- Remove `mcp-http-server.js` (or keep as dev-only fallback)
- Remove port 3000 security group rule
- Update documentation

### Step 8: Update documentation and SDD
- Tag: document
- Update CHANGELOG, steering files, README
- Record SDD session completion

## Total Steps: 9 (Steps 0-8)

## Acceptance Criteria

1. MCP server deployed via `agentcore launch` (CloudFormation-managed)
2. Kiro connects to AgentCore endpoint (not localhost:3000)
3. All 51 tools respond correctly via AgentCore Runtime
4. No manual port forwarding or security group hacks required
5. Multi-user access via AgentCore Gateway auth

## Environment Variables

| Variable | Value | Purpose |
|----------|-------|---------|
| DB_BACKEND | aws | Route to OpenSearch + Neptune |
| OPENSEARCH_ENDPOINT | vpc-mdc-mcp-rag-search-*.es.amazonaws.com | Vector search |
| NEPTUNE_ENDPOINT | mdc-mcp-rag-neptune.*.neptune.amazonaws.com:8182 | Graph queries |
| AWS_REGION | us-east-1 | AWS region |

## Reference

- AgentCore docs: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-mcp.html
- Kiro Power: aws-agentcore (steering: getting-started.md)
- Current bridge: `mcp_server_node/src/mcp-http-server.js`
- CDK stacks: `infrastructure/cdk/lib/`

## Branch

`develop_aws`
