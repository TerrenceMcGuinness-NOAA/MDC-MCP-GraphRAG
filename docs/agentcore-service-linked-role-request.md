# AgentCore Service-Linked Role Request

**Date**: 2026-04-28 (Updated)
**Requester**: terry.mcguinness@noaa.gov
**Account**: 903050880929 (us-east-1)
**Purpose**: One-time creation of AgentCore service-linked roles required for Bedrock AgentCore Runtime deployment

## What's Needed

Amazon Bedrock AgentCore uses **multiple service-linked roles** for different capabilities. For our VPC-mode Runtime deployment, we need the **Network** role. The full set of AgentCore service-linked roles is:

| Role Name | Service Name | Purpose |
|-----------|-------------|---------|
| `AWSServiceRoleForBedrockAgentCoreNetwork` | `agentcore.network.bedrock.amazonaws.com` | **Required** — VPC networking for Runtime (ENI management in subnets) |
| `AWSServiceRoleForBedrockAgentCoreRuntimeIdentity` | `agentcore.runtime-identity.bedrock.amazonaws.com` | Runtime identity management |
| `AWSServiceRoleForBedrockAgentCoreGatewayNetwork` | `agentcore.gateway-network.bedrock.amazonaws.com` | Gateway VPC networking |
| `AWSServiceRoleForBedrockAgentCoreIdentity` | `agentcore.identity.bedrock.amazonaws.com` | AgentCore Identity service |

## Commands for Admin

**Required for our deployment (VPC-mode Runtime):**
```bash
aws iam create-service-linked-role --aws-service-name agentcore.network.bedrock.amazonaws.com
```

**Optional (create all four for future use):**
```bash
aws iam create-service-linked-role --aws-service-name agentcore.network.bedrock.amazonaws.com
aws iam create-service-linked-role --aws-service-name agentcore.runtime-identity.bedrock.amazonaws.com
aws iam create-service-linked-role --aws-service-name agentcore.gateway-network.bedrock.amazonaws.com
aws iam create-service-linked-role --aws-service-name agentcore.identity.bedrock.amazonaws.com
```

## Verification

After creation, verify with:
```bash
aws iam list-roles --query "Roles[?starts_with(RoleName, 'AWSServiceRoleForBedrockAgentCore')].RoleName" --output table
```

Expected output should include at minimum:
```
AWSServiceRoleForBedrockAgentCoreNetwork
```

## Context

- The IAM trust policy on `mdc-mcp-rag-ecs-task-role` was already updated (thank you!)
- The `AWSServiceRoleForBedrockAgentCoreGatewayNetwork` role was already created (from the first attempt) — thank you!
- We specifically need the **Network** variant (`agentcore.network.bedrock.amazonaws.com`) for VPC-mode Runtime deployment
- The deployment creates only AgentCore resources (runtime, endpoint) — no modifications to Neptune, OpenSearch, or existing infrastructure

## Error We're Hitting

```
CreateAgentRuntime failed: Failed creating service linked role.
Please verify that the calling role has sufficient permissions
to create a service linked role.
```

This occurs because our PowerUser policy blocks `iam:CreateServiceLinkedRole`. The AgentCore API tries to auto-create the role on first deployment.

## Reference

AWS Documentation: [Using service-linked roles for Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/service-linked-roles.html)
