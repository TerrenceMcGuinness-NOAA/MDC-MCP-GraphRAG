# AgentCore Execution Role Request

**Date**: 2026-04-23
**Requester**: terry.mcguinness@noaa.gov
**Account**: 903050880929 (us-east-1)
**Purpose**: Bedrock AgentCore Runtime execution role for MDC MCP RAG Server

## Option A (Preferred): Update existing role trust policy

Add `bedrock-agentcore.amazonaws.com` as a trusted principal to the existing
`mdc-mcp-rag-ecs-task-role`. This role already has the correct data access
permissions (Neptune, OpenSearch, Secrets Manager, SSM).

### Trust policy update

Add this statement to the existing trust policy:

```json
{
  "Sid": "AllowBedrockAgentCore",
  "Effect": "Allow",
  "Principal": {
    "Service": "bedrock-agentcore.amazonaws.com"
  },
  "Action": "sts:AssumeRole"
}
```

The full trust policy should be:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowAccessToECSForTaskExecutionRole",
      "Effect": "Allow",
      "Principal": {
        "Service": "ecs-tasks.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    },
    {
      "Sid": "AllowBedrockAgentCore",
      "Effect": "Allow",
      "Principal": {
        "Service": "bedrock-agentcore.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

### Additional permissions needed on the role

The existing inline policy covers data access. Add these for AgentCore operations:

```json
{
  "Sid": "agentcoreEcr",
  "Effect": "Allow",
  "Action": [
    "ecr:GetAuthorizationToken",
    "ecr:BatchGetImage",
    "ecr:GetDownloadUrlForLayer"
  ],
  "Resource": "*"
},
{
  "Sid": "agentcoreLogs",
  "Effect": "Allow",
  "Action": [
    "logs:CreateLogGroup",
    "logs:CreateLogStream",
    "logs:PutLogEvents"
  ],
  "Resource": "arn:aws:logs:us-east-1:903050880929:log-group:/aws/bedrock-agentcore/*"
},
{
  "Sid": "agentcoreXray",
  "Effect": "Allow",
  "Action": [
    "xray:PutTraceSegments",
    "xray:PutTelemetryRecords"
  ],
  "Resource": "*"
}
```

## Option B (Alternative): Create new dedicated role

If modifying the existing role is not preferred, create a new role:

**Role name**: `mdc-mcp-rag-agentcore-execution-role`

**Trust policy**: (bedrock-agentcore.amazonaws.com only)

**Permissions**: Combine the existing inline policy from `mdc-mcp-rag-ecs-task-role`
with the ECR/Logs/X-Ray permissions above.

## CLI commands (for admin)

### Option A:
```bash
aws iam update-assume-role-policy \
  --role-name mdc-mcp-rag-ecs-task-role \
  --policy-document file://trust-policy.json

aws iam put-role-policy \
  --role-name mdc-mcp-rag-ecs-task-role \
  --policy-name agentcore-permissions \
  --policy-document file://agentcore-permissions.json
```

### Option B:
```bash
aws iam create-role \
  --role-name mdc-mcp-rag-agentcore-execution-role \
  --assume-role-policy-document file://trust-policy-agentcore.json

aws iam put-role-policy \
  --role-name mdc-mcp-rag-agentcore-execution-role \
  --policy-name inline \
  --policy-document file://full-permissions.json
```

## Context

This role is needed for the Bedrock AgentCore Runtime to:
1. Pull the MCP server container image from ECR
2. Connect to Neptune (graph database) and OpenSearch (vector search)
3. Read configuration from SSM Parameter Store and Secrets Manager
4. Write logs to CloudWatch and traces to X-Ray

The AgentCore Runtime replaces the manual `mcp-http-server.js` process with
a managed serverless deployment (microVM isolation, auto-scaling, observability).
