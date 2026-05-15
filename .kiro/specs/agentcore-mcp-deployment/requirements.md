# Requirements Document

## Introduction

Deploy the MDC MCP RAG Server (51+ tools, Node.js) to AWS Bedrock AgentCore Runtime as an MCP protocol server, replacing the hand-rolled `mcp-http-server.js` development bridge. AgentCore handles transport, scaling, session lifecycle, and observability via CloudFormation — aligning with the project's IaC-first principle.

This spec supersedes the original Phase 51b SDD (`sdd_framework/workflows/phase51b_agentcore_mcp_deployment.md`) with corrections based on the current AgentCore platform capabilities discovered via the `aws-agentcore` Kiro Power.

## Key Discovery: Toolkit Migration

The original SDD spec references `bedrock-agentcore-starter-toolkit` (pip) and `agentcore launch`. Per the AgentCore Runtime guide (retrieved April 23, 2026), the pip-based toolkit is **deprecated**. The replacement is `@aws/agentcore` (npm):

| Deprecated (pip) | Current (npm) |
|---|---|
| `pip install bedrock-agentcore-starter-toolkit` | `npm install -g @aws/agentcore` |
| `.bedrock_agentcore.yaml` | `agentcore/agentcore.json` |
| `agentcore launch` | `agentcore deploy` |
| `agentcore configure` | `agentcore create` or manual `agentcore.json` |
| CodeBuild-based deployment | CDK-based deployment |

The existing `HelloAgent/` project uses the deprecated toolkit and will need migration.

## Glossary

- **AgentCore_Runtime**: AWS Bedrock AgentCore's serverless hosting environment for AI agents and tools, running in isolated microVMs
- **MCP_Server**: The MDC MCP RAG Server — a Node.js application exposing 51+ AI-powered tools via the Model Context Protocol
- **Dev_Bridge**: The current `mcp-http-server.js` process running on port 3000 on the EC2 instance
- **AgentCore_CLI**: The `@aws/agentcore` npm package providing `agentcore` CLI commands
- **Runtime_Session**: An isolated microVM session created per invocation, with configurable idle timeout and max lifetime
- **DEFAULT_Endpoint**: The auto-created endpoint that always points to the latest runtime version

## Requirements

### Requirement 1: Install Current AgentCore CLI

**User Story:** As a developer, I want the current (non-deprecated) AgentCore CLI installed, so that deployments use the supported toolchain.

#### Acceptance Criteria

1. THE `@aws/agentcore` npm package SHALL be installed globally via `npm install -g @aws/agentcore`
2. THE `agentcore` CLI SHALL respond to `agentcore --version` with a version number
3. THE deprecated `bedrock-agentcore-starter-toolkit` pip package MAY remain installed but SHALL NOT be used for new deployments

### Requirement 2: MCP Protocol Server Configuration

**User Story:** As a platform engineer, I want the MCP server deployed with the MCP protocol (not HTTP), so that AgentCore handles MCP transport natively at `0.0.0.0:8000/mcp`.

#### Acceptance Criteria

1. THE AgentCore runtime SHALL be configured with `protocol: "MCP"` in `agentcore.json`
2. THE MCP_Server SHALL listen on port 8000 at path `/mcp` (AgentCore MCP protocol default)
3. THE MCP_Server SHALL implement a `/ping` GET endpoint returning `{"status": "Healthy"}`
4. THE container image SHALL be built for ARM64 architecture (AgentCore requirement)
5. THE MCP_Server SHALL pass `DB_BACKEND=aws`, `AWS_REGION=us-east-1`, and database endpoint environment variables

### Requirement 3: VPC Network Mode

**User Story:** As a security engineer, I want the AgentCore runtime deployed in VPC mode, so that it can reach Neptune and OpenSearch in the private subnets without internet exposure.

#### Acceptance Criteria

1. THE AgentCore runtime SHALL use `networkMode: "VPC"` (not PUBLIC)
2. THE VPC configuration SHALL specify the private subnets where Neptune and OpenSearch reside
3. THE VPC configuration SHALL specify security groups allowing egress to Neptune (port 8182) and OpenSearch (port 443)
4. THE runtime SHALL NOT require an Internet Gateway or NAT Gateway for database connectivity

### Requirement 4: IAM Execution Role

**User Story:** As a developer with PowerUser permissions, I want the AgentCore execution role documented, so that an admin can create it if needed.

#### Acceptance Criteria

1. THE execution role SHALL trust `bedrock-agentcore.amazonaws.com` as the service principal
2. THE execution role SHALL include permissions for: ECR image pull, CloudWatch Logs, X-Ray trace segments, Neptune connect, OpenSearch HTTP operations, Secrets Manager read, and SSM Parameter Store read
3. IF the role cannot be auto-created due to PowerUserRestrictions, THEN an admin request document SHALL be generated following the pattern in `docs/ecs-roles-request.txt`
4. THE role permissions SHALL follow least-privilege principles

### Requirement 5: Container Image Build and Push

**User Story:** As a developer, I want the MCP server container image built for ARM64 and pushed to ECR, so that AgentCore Runtime can pull and run it.

#### Acceptance Criteria

1. THE container image SHALL be built for `linux/arm64` platform
2. THE container image SHALL expose port 8000 (MCP protocol default)
3. THE container image SHALL include a `/ping` health check endpoint
4. THE container image SHALL be pushed to the `mdc-mcp-rag` ECR repository
5. THE Dockerfile SHALL set `DB_BACKEND=aws` and `NODE_ENV=production`

### Requirement 6: AgentCore Deployment via CLI

**User Story:** As a developer, I want to deploy the MCP server using `agentcore deploy`, so that the deployment is reproducible and IaC-managed.

#### Acceptance Criteria

1. THE deployment SHALL use `agentcore deploy` (not the deprecated `agentcore launch`)
2. THE deployment SHALL be previewable via `agentcore deploy --plan` before execution
3. THE deployment SHALL create a DEFAULT endpoint accessible from within the VPC
4. THE deployment status SHALL be verifiable via `agentcore status`
5. THE deployment logs SHALL be accessible via `agentcore logs`

### Requirement 7: Tool Functional Parity

**User Story:** As an MCP tool consumer, I want all 51+ tools to work identically after deployment, so that the migration from the Dev_Bridge is transparent.

#### Acceptance Criteria

1. WHEN the MCP_Server is deployed to AgentCore Runtime, THE MCP_Server SHALL register all tools with identical names and input schemas as the Dev_Bridge
2. WHEN any tool is invoked through the AgentCore endpoint, THE tool SHALL return results consistent with the Dev_Bridge responses
3. IF a tool invocation fails due to a connectivity issue, THEN THE MCP_Server SHALL return a structured error message identifying the failing backend

### Requirement 8: Kiro MCP Client Configuration

**User Story:** As a developer using Kiro, I want the MCP client configuration updated to point to the AgentCore endpoint, so that Kiro connects to the production MCP service.

#### Acceptance Criteria

1. THE Kiro MCP configuration for `mdc-mcp-rag-aws` SHALL be updated with the AgentCore Runtime endpoint URL
2. THE configuration SHALL use the AgentCore endpoint format (runtime ARN-based invocation)
3. THE Dev_Bridge configuration SHALL be retained as a disabled fallback

### Requirement 9: Session Lifecycle Management

**User Story:** As a cost-conscious operator, I want session lifecycle configured appropriately, so that idle sessions don't accumulate charges.

#### Acceptance Criteria

1. THE idle session timeout SHALL be configured to 900 seconds (15 minutes, the default)
2. THE max session lifetime SHALL be configured to 28800 seconds (8 hours)
3. DOCUMENTATION SHALL include instructions for using `stop_runtime_session` to terminate sessions early

### Requirement 10: Data Safety During Deployment

**User Story:** As a data steward, I want deployment to have zero impact on Neptune and OpenSearch data, so that the graph and vector stores are preserved.

#### Acceptance Criteria

1. THE AgentCore deployment SHALL NOT modify, delete, or recreate Neptune or OpenSearch resources
2. THE deployment SHALL only create AgentCore Runtime resources (runtime definition, endpoint, IAM role)
3. THE CDK data safety steering rules (`.kiro/steering/05-cdk-data-safety.md`) SHALL be followed for any infrastructure changes
4. A `cdk diff` review SHALL be performed before any CDK-based deployment step

### Requirement 11: Dev Bridge Retirement

**User Story:** As a platform engineer, I want the development bridge retired after production deployment is validated, so that no unnecessary network exposure remains.

#### Acceptance Criteria

1. WHEN all tools are verified working through AgentCore, THE Dev_Bridge process SHALL be stopped
2. WHEN the Dev_Bridge is retired, THE security group rule allowing inbound traffic on port 3000 SHALL be removed
3. THE Dev_Bridge code SHALL be retained as a development-only fallback (not deleted)
