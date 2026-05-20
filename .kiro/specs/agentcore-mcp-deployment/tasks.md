# Implementation Plan: AgentCore MCP Deployment

## Overview

Deploy the MDC MCP RAG Server to AgentCore Runtime as a native MCP protocol server. This plan uses the current `@aws/agentcore` npm CLI (not the deprecated pip toolkit) and incorporates the CDK data safety guardrails from the April 22 post-mortem.

## Tasks

- [x] 1. Install and verify AgentCore tooling ✅ (2026-04-23)
  - [x] 1.1 AgentCore Power MCP server connected (52 tools) — replaces both deprecated pip CLI and npm CLI
    - Verify: Power shows "Connected (52 tools)" in Kiro
    - Note: Using Power MCP tools (`create_agent_runtime`, etc.) instead of CLI commands — safer, API-direct
    - _Requirements: 1.1, 1.2, 1.3_

- [x] 2. Create MCP AgentCore entrypoint ✅ (2026-04-23)
  - [x] 2.1 Created `mcp_server_node/src/mcp-agentcore-entrypoint.js`
    - Streamable HTTP on `0.0.0.0:8000/mcp` (AgentCore MCP convention)
    - `/ping` GET endpoint returning `{"status": "Healthy"}`
    - Shared data access across stateless requests
    - _Requirements: 2.1, 2.2, 2.3_

- [x] 3. Create ARM64 Dockerfile ✅ (2026-04-23)
  - [x] 3.1 Created `mcp_server_node/Dockerfile.agentcore`
    - Base: `node:20-slim` with `--platform=linux/arm64`
    - Production deps only, 302MB compressed
    - Healthcheck on `/ping`, CMD `node src/mcp-agentcore-entrypoint.js`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [x] 4. Build and push container image ✅ (2026-04-23)
  - [x] 4.1 Built ARM64 image via `docker buildx`
    - Verified locally: `/ping` returns healthy, MCP server starts
    - _Requirements: 5.1, 5.2_
  - [x] 4.2 Pushed to ECR
    - `903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:agentcore`
    - _Requirements: 5.4_

- [x] 5. Create AgentCore configuration ✅ (2026-04-23)
  - [x] 5.1 Created `.bedrock_agentcore.yaml` with MCP protocol, VPC network mode, container build type
    - Agent name: `MdcMcpRagServer`
    - Protocol: `MCP`
    - Network mode: `VPC` with 3 private subnets and ECS security group
    - Execution role: `arn:aws:iam::903050880929:role/mdc-mcp-rag-ecs-task-role`
    - Lifecycle: idle 900s, max 28800s
    - _Requirements: 2.1, 3.1, 3.2, 3.3_

- [x] 6. Verify or create IAM execution role ✅ (2026-04-30)
  - [x] 6.1 IAM permissions resolved via admin requests
    - Trust policy updated: `bedrock-agentcore.amazonaws.com` added to `mdc-mcp-rag-ecs-task-role`
    - 4 service-linked roles created by admin (GatewayNetwork, Network, RuntimeIdentity, Identity)
    - Explicit deny on `bedrock-agentcore:*` removed (Option C)
    - Verified: `aws bedrock-agentcore-control list-agent-runtimes` returns `{"agentRuntimes": []}`
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

- [x] 7. Deploy to AgentCore Runtime (via Power MCP)
  - [x] 7.1 Call `create_agent_runtime` via AgentCore Power with parameters:
    - `agent_runtime_name`: `mdc_mcp_rag_server`
    - `container_uri`: `903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:agentcore`
    - `server_protocol`: `MCP`
    - `network_mode`: `VPC`
    - `subnets`: `["subnet-0e13af6b3a9a6416f", "subnet-024fd9b597b3075a5", "subnet-04447750c61bd7e06"]`
    - `security_groups`: `["sg-096489a0876cc78c1"]`
    - `role_arn`: `arn:aws:iam::903050880929:role/mdc-mcp-rag-ecs-task-role`
    - `idle_timeout`: 900
    - `max_lifetime`: 28800
  - [x] 7.2 Monitor: call `get_agent_runtime` until status is READY
    - Record the runtime ID and DEFAULT endpoint URL
    - CDK Safety: This only creates AgentCore Runtime resources — no Neptune/OpenSearch impact
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 10.1, 10.2, 10.4_

- [x] 8. Validate deployment
  - [x] 8.1 Verify health: call `invoke_agent_runtime` with a `/ping` equivalent
  - [x] 8.2 Verify tools: invoke representative set via `invoke_agent_runtime`:
    - `get_server_info`, `search_documentation`, `get_code_context`, `mcp_health_check`
    - Compare responses against dev bridge for parity
    - _Requirements: 7.1, 7.2, 7.3_
  - [x] 8.3 Check logs via CloudWatch for any errors
    - _Requirements: 6.5_

- [x] 9. Update Kiro MCP client configuration
  - [x] 9.1 Update `.kiro/settings/mcp.json` with AgentCore endpoint URL for `mdc-mcp-rag-aws`
    - Keep dev bridge config as disabled fallback
    - _Requirements: 8.1, 8.2, 8.3_
  - [x] 9.2 Verify Kiro connects and all tools are listed
    - _Requirements: 7.1_

- [x] 10. Retire development bridge
  - [x] 10.1 Stop `mcp-http-server.js` process on port 3000
  - [x] 10.2 Remove security group rule for port 3000 inbound
  - [x] 10.3 Keep `mcp-http-server.js` code as dev-only fallback (do not delete)
    - _Requirements: 11.1, 11.2, 11.3_

- [x] 11. Update documentation and SDD
  - [x] 11.1 Update `CHANGELOG.md` with AgentCore deployment entry
  - [x] 11.2 Update Phase 51b SDD spec with actual deployment details
  - [x] 11.3 Update steering files if endpoint or workflow changed
    - _Requirements: 9.1, 9.2, 9.3_

## Notes

- We deploy via the **AgentCore Kiro Power** MCP tools (52 tools) rather than either CLI. This is API-direct, safer (only touches AgentCore resources), and integrated into our IDE workflow.
- The `.bedrock_agentcore.yaml` serves as configuration reference but is not consumed by any CLI during deployment — the Power tools take explicit parameters.
- Task 4 (IAM) was the primary blocker — resolved via admin requests for trust policy update, service-linked roles, and explicit deny removal.
- The CDK data safety rules (`.kiro/steering/05-cdk-data-safety.md`) still apply conceptually — `create_agent_runtime` only creates AgentCore resources, but we verify this by checking that no Neptune/OpenSearch resources are affected.
- Session lifecycle: idle timeout 900s (15 min), max lifetime 28800s (8 hours). Use `stop_runtime_session` to terminate early and save costs.
- AWS CLI subcommand is `bedrock-agentcore-control` (NOT `bedrock-agentcore`) — IAM namespace differs from CLI subcommand.
