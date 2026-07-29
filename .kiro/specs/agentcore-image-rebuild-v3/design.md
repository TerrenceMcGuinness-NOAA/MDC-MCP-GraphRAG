# Design Document

## Overview

Rebuild the AgentCore runtime Docker image from current `develop` HEAD to carry
Phases 67–73 to the AWS serving path. Routine operator procedure: build → smoke
→ push → update-runtime → verify → log rollback. No schema, data, or
configuration changes.

## What the new image carries vs the current (`python-tenants-v2`)

| Phase | AWS Impact |
|---|---|
| 67 | Path rename conformance (default `WORKFLOW_ROOT` → `_develop`) |
| 68 | Manifest `scope: tenant\|shared` field + EXPDIR clarification |
| 70 | `VectorDBProtocol` explicit `count_documents` + `sample_metadata` (dormant on AWS — OpenSearch already had equivalents; now protocol-compliant) |
| 71 | Nightly benchmark wrapper script (dormant — systemd not installed on AgentCore) |
| 72 | Coverage Gap → `[OK] ... (graph-only)` instead of `[SKIP]` |
| 73 | Node-count scope annotations + `all_tenants` flag on `get_knowledge_base_status` |

Risk: **Low.** All changes are additive (new methods, annotations, parameters).
No existing behavior is removed or altered. Rollback is a single command.

## Procedure

```bash
# 1. Build (on the EC2 dev host)
cd /mdc-mcp-rag/eib-mcp-rag-server
SHORT_SHA=$(git rev-parse --short HEAD)
TAG="python-tenants-v3-${SHORT_SHA}"

docker build --platform linux/arm64 \
  -t 903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:python-tenants-v3 \
  -t 903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:${TAG} \
  -f mcp_server_python/Dockerfile .

# 2. Local smoke (optional — requires the proxy to reach AgentCore)
# The proxy validates the image's tool registration, not the stores.

# 3. Push to ECR
aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin \
      903050880929.dkr.ecr.us-east-1.amazonaws.com
docker push 903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:python-tenants-v3
docker push 903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:${TAG}

# 4. Update runtime
aws bedrock-agentcore-control update-agent-runtime \
  --region us-east-1 \
  --agent-runtime-id mdc_mcp_rag_server_python-v5K2F8BGrN \
  --agent-runtime-artifact "{\"containerConfiguration\":{\"containerUri\":\"903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:python-tenants-v3\"}}" \
  --role-arn arn:aws:iam::903050880929:role/mdc-mcp-rag-ecs-task-role \
  --network-configuration '{"networkMode":"VPC","networkModeConfig":{"subnets":["subnet-0e13af6b3a9a6416f","subnet-04447750c61bd7e06"],"securityGroups":["sg-096489a0876cc78c1"]}}' \
  --protocol-configuration '{"serverProtocol":"MCP"}' \
  --lifecycle-configuration '{"idleRuntimeSessionTimeout":900,"maxLifetime":28800}' \
  --environment-variables 'DB_BACKEND=aws,NEPTUNE_ENDPOINT=https://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182,OPENSEARCH_ENDPOINT=https://vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com,AWS_REGION=us-east-1,MCP_STATELESS_HTTP=true,MCP_WORKFLOW_ROOT=/app/supported_repos/global-workflow_develop'

# 5. Wait READY (poll ~5 min)
# Check: aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id ...

# 6. Verify (via the agentcore-mcp-rag MCP in Kiro)
# mcp_health_check, get_knowledge_base_status, check_knowledge_integrity

# ROLLBACK (if needed):
# aws bedrock-agentcore-control update-agent-runtime ... --agent-runtime-artifact
#   '{"containerConfiguration":{"containerUri":"...mdc-mcp-rag:python-tenants-v2"}}'
```

## Verification checklist

- [ ] `mcp_health_check --deep --detailed --functional` → HEALTHY 4/4
- [ ] `get_knowledge_base_status` → `Total Documents > 0`, `(tenant scope)` visible
- [ ] `check_knowledge_integrity` → Coverage Gap `[OK]` (graph-only), not `[SKIP]`
- [ ] `get_knowledge_base_status(all_tenants=True)` → whole-graph count ≥ tenant
- [ ] Rollback command recorded in run log
