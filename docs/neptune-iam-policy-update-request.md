# IAM Policy Update Request — Neptune Data Plane Access for AgentCore Runtime

**Date**: May 1, 2026
**Requester**: terry.mcguinness@noaa.gov
**Account**: 903050880929 (us-east-1)
**Role**: `mdc-mcp-rag-ecs-task-role`

---

## Summary

Our AgentCore Runtime MCP server can now reach Neptune over the network (security group rules are in place), but the IAM execution role lacks the Neptune data plane permissions needed to run openCypher queries. The role currently has `neptune-db:connect` only — Neptune IAM authentication requires additional actions for query execution.

## What's Working

- ✅ AgentCore Runtime deployed and READY (version 2)
- ✅ MCP server starts, registers 51 tools, responds to static queries
- ✅ Security groups updated — microVM can reach Neptune (port 8182) and OpenSearch (port 443)
- ✅ Environment variables set (NEPTUNE_ENDPOINT, OPENSEARCH_ENDPOINT, DB_BACKEND)

## What's Failing

When the MCP server inside the AgentCore microVM tries to query Neptune:

```
User: arn:aws:sts::903050880929:assumed-role/mdc-mcp-rag-ecs-task-role/BedrockAgentCore-a4eea8f2-...
is not authorized to perform one or more of the actions:
  neptune-db:DeleteDataViaQuery,
  neptune-db:ReadDataViaQuery,
  neptune-db:WriteDataViaQuery
on resource: arn:aws:neptune-db:us-east-1:903050880929:cluster-WVIKLHKJQGRZJK5ZYOL3M4ZO2U/*
```

## What Needs to Change

Update the `neptune` statement in the **inline policy** (named `inline`) on role `mdc-mcp-rag-ecs-task-role`.

### Current Statement (insufficient)

```json
{
  "Sid": "neptune",
  "Effect": "Allow",
  "Action": "neptune-db:connect",
  "Resource": "arn:aws:neptune-db:us-east-1:903050880929:/"
}
```

**Two problems:**
1. Only `connect` action — missing the query execution actions
2. Resource ARN is generic (`/`) — should target our specific cluster

### Replacement Statement

```json
{
  "Sid": "neptune",
  "Effect": "Allow",
  "Action": [
    "neptune-db:connect",
    "neptune-db:ReadDataViaQuery",
    "neptune-db:WriteDataViaQuery",
    "neptune-db:DeleteDataViaQuery",
    "neptune-db:GetQueryStatus",
    "neptune-db:CancelQuery"
  ],
  "Resource": "arn:aws:neptune-db:us-east-1:903050880929:cluster-WVIKLHKJQGRZJK5ZYOL3M4ZO2U/*"
}
```

**All other statements in the policy remain unchanged** (secretsmanager, ssm, es, ecr, logs, xray).

## How to Apply

**Option A — Replace just the neptune statement** (edit in console):

1. Go to IAM → Roles → `mdc-mcp-rag-ecs-task-role` → Permissions → `inline` policy
2. Edit the `neptune` statement: replace the Action and Resource as shown above
3. Save

**Option B — Replace the full inline policy via CLI:**

```bash
aws iam put-role-policy \
  --role-name mdc-mcp-rag-ecs-task-role \
  --policy-name inline \
  --policy-document '{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "secretsmanager",
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "arn:aws:secretsmanager:us-east-1:903050880929:secret:mdc-mcp-rag/*"
    },
    {
      "Sid": "ssm",
      "Effect": "Allow",
      "Action": ["ssm:GetParameter", "ssm:GetParameters"],
      "Resource": "arn:aws:ssm:us-east-1:903050880929:parameter/mdc-mcp-rag/*"
    },
    {
      "Sid": "neptune",
      "Effect": "Allow",
      "Action": [
        "neptune-db:connect",
        "neptune-db:ReadDataViaQuery",
        "neptune-db:WriteDataViaQuery",
        "neptune-db:DeleteDataViaQuery",
        "neptune-db:GetQueryStatus",
        "neptune-db:CancelQuery"
      ],
      "Resource": "arn:aws:neptune-db:us-east-1:903050880929:cluster-WVIKLHKJQGRZJK5ZYOL3M4ZO2U/*"
    },
    {
      "Sid": "es",
      "Effect": "Allow",
      "Action": ["es:ESHttpGet", "es:ESHttpPost", "es:ESHttpPut"],
      "Resource": "arn:aws:es:us-east-1:903050880929:domain/mdc-mcp-rag-search/*"
    },
    {
      "Sid": "agentcoreEcr",
      "Effect": "Allow",
      "Action": ["ecr:GetAuthorizationToken", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
      "Resource": "*"
    },
    {
      "Sid": "agentcoreLogs",
      "Effect": "Allow",
      "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
      "Resource": "arn:aws:logs:us-east-1:903050880929:log-group:/aws/bedrock-agentcore/*"
    },
    {
      "Sid": "agentcoreXray",
      "Effect": "Allow",
      "Action": ["xray:PutTraceSegments", "xray:PutTelemetryRecords"],
      "Resource": "*"
    }
  ]
}'
```

## Verification

After the policy update, we can verify by reconnecting the AgentCore MCP server in Kiro and running a graph query. The MCP server will query Neptune via openCypher and return code analysis results.

## Context

This role is used by the AgentCore Runtime to host our 51-tool MCP server for the Global Forecast System. The MCP server queries Neptune (164,916 nodes, 2.9M relationships) for code analysis, execution tracing, and dependency mapping. Without the data plane permissions, only static tools (no database) work — the graph and vector tools all fail.
