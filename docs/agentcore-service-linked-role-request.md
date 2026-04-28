# AgentCore Service-Linked Role Request

**Date**: 2026-04-28
**Requester**: terry.mcguinness@noaa.gov
**Account**: 903050880929 (us-east-1)
**Purpose**: One-time creation of the AgentCore service-linked role required for Bedrock AgentCore Runtime deployment

## What's Needed

Amazon Bedrock AgentCore requires a service-linked role (`AWSServiceRoleForBedrockAgentCore`) to manage runtime resources on behalf of the service. This role is created automatically by the AgentCore API, but our PowerUser restrictions block `iam:CreateServiceLinkedRole`.

This is a **one-time operation** per account. Once created, it persists and all future AgentCore deployments will use it.

## Command for Admin

```bash
aws iam create-service-linked-role --aws-service-name bedrock-agentcore.amazonaws.com
```

## Verification

After creation, verify with:
```bash
aws iam get-role --role-name AWSServiceRoleForBedrockAgentCore
```

## Context

- The IAM trust policy on `mdc-mcp-rag-ecs-task-role` was already updated (thank you!)
- This service-linked role is the last blocker before we can deploy the MCP server to AgentCore Runtime
- The deployment creates only AgentCore resources (runtime, endpoint) — no modifications to Neptune, OpenSearch, or existing infrastructure
- Once deployed, the MCP server will be managed by AgentCore with auto-scaling, session isolation, and CloudWatch observability

## Error We're Hitting

```
CreateAgentRuntime failed: Failed creating service linked role.
Please verify that the calling role has sufficient permissions
to create a service linked role.
```

## What This Role Does

The `AWSServiceRoleForBedrockAgentCore` service-linked role allows AgentCore to:
- Pull container images from ECR
- Create and manage microVM sessions
- Write logs to CloudWatch
- Manage VPC network interfaces in the specified subnets
- Route traffic through the specified security groups

It does NOT grant access to our data (Neptune, OpenSearch, S3). Data access is governed by the separate `mdc-mcp-rag-ecs-task-role` execution role.
