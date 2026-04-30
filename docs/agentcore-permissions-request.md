# AgentCore Permissions Request — bedrock-agentcore:* Actions

**Date**: 2026-04-28
**Requester**: terry.mcguinness@noaa.gov
**Account**: 903050880929 (us-east-1)
**Purpose**: Allow our IAM user to invoke Bedrock AgentCore APIs for deploying and managing the MCP server runtime

## Background

We are deploying the MDC MCP RAG Server (51 AI development tools for the Global Forecast System) to Amazon Bedrock AgentCore Runtime. This is a managed serverless hosting service for MCP protocol servers — it replaces our manual EC2 process with auto-scaling, session isolation, and CloudWatch observability.

We use the **AWS AgentCore Kiro Power** — an MCP tool set that provides programmatic access to AgentCore APIs directly from our development environment (Kiro IDE). This is safer than CDK/CloudFormation because it only creates AgentCore-specific resources and cannot modify existing infrastructure (Neptune, OpenSearch, etc.).

## What We're Trying to Do

Deploy our containerized MCP server to AgentCore Runtime using the `create_agent_runtime` API call:

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

## Error We're Hitting

```
User: arn:aws:iam::903050880929:user/terry.mcguinness@noaa.gov is not authorized
to perform: bedrock-agentcore:CreateWorkloadIdentity on resource:
arn:aws:bedrock-agentcore:us-east-1:903050880929:workload-identity-directory/default/workload-identity/*
with an explicit deny in an identity-based policy
```

## What's Needed

Our PowerUser policy has an explicit deny on `bedrock-agentcore:*` actions. We need permission to call AgentCore APIs.

### Option A (Recommended): Attach AWS Managed Policy

Attach the `BedrockAgentCoreFullAccess` managed policy to our user:

```bash
aws iam attach-user-policy \
  --user-name "terry.mcguinness@noaa.gov" \
  --policy-arn "arn:aws:iam::aws:policy/BedrockAgentCoreFullAccess"
```

### Option B: Minimal Custom Policy

If full access is too broad, a minimal policy for Runtime deployment:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowAgentCoreRuntime",
      "Effect": "Allow",
      "Action": [
        "bedrock-agentcore:CreateAgentRuntime",
        "bedrock-agentcore:GetAgentRuntime",
        "bedrock-agentcore:UpdateAgentRuntime",
        "bedrock-agentcore:DeleteAgentRuntime",
        "bedrock-agentcore:ListAgentRuntimes",
        "bedrock-agentcore:CreateAgentRuntimeEndpoint",
        "bedrock-agentcore:GetAgentRuntimeEndpoint",
        "bedrock-agentcore:ListAgentRuntimeEndpoints",
        "bedrock-agentcore:InvokeAgentRuntime",
        "bedrock-agentcore:StopRuntimeSession",
        "bedrock-agentcore:CreateWorkloadIdentity",
        "bedrock-agentcore:GetWorkloadIdentity",
        "bedrock-agentcore:ListWorkloadIdentities"
      ],
      "Resource": "*"
    }
  ]
}
```

### Option C: Remove Explicit Deny

If there's an explicit deny on `bedrock-agentcore:*` in the PowerUser boundary policy, remove that deny statement. The PowerUser policy already allows most AWS actions — AgentCore just needs to not be explicitly excluded.

## How We Use These Permissions (Kiro Power MCP Tools)

The AgentCore Kiro Power provides these MCP tools that map to the API actions:

| MCP Tool | API Action | What It Does |
|----------|-----------|--------------|
| `create_agent_runtime` | `CreateAgentRuntime` | Deploy our container to AgentCore (one-time setup) |
| `get_agent_runtime` | `GetAgentRuntime` | Check deployment status |
| `list_agent_runtimes` | `ListAgentRuntimes` | List deployed runtimes (read-only) |
| `invoke_agent_runtime` | `InvokeAgentRuntime` | Test the deployed MCP server |
| `stop_runtime_session` | `StopRuntimeSession` | Terminate idle sessions (cost control) |
| `update_agent_runtime` | `UpdateAgentRuntime` | Deploy new container versions |
| `delete_agent_runtime` | `DeleteAgentRuntime` | Clean up if needed |

These tools ONLY manage AgentCore resources. They cannot modify Neptune, OpenSearch, VPC, or any other existing infrastructure.

## What AgentCore Runtime Creates

When we call `create_agent_runtime`, AgentCore creates:
- A runtime definition (metadata only)
- A DEFAULT endpoint (URL for MCP clients to connect)
- ENIs in the specified subnets (managed by the service-linked role)

It does NOT create or modify:
- Neptune clusters or data
- OpenSearch domains or indices
- VPC, subnets, or route tables
- S3 buckets
- Any CDK/CloudFormation stacks

## Verification

After permissions are granted, we can verify with:
```bash
aws bedrock-agentcore-control list-agent-runtimes --region us-east-1
```

> **Note**: The AWS CLI subcommand is `bedrock-agentcore-control`, not `bedrock-agentcore`.
> The IAM action namespace (`bedrock-agentcore:*`) differs from the CLI subcommand name — this is standard AWS behavior (similar to `elasticloadbalancing:*` in IAM vs `elbv2` in CLI).

This should return an empty list (no runtimes yet) without an access denied error.
