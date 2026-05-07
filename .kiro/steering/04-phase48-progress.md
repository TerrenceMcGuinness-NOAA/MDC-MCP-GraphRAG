---
inclusion: auto
---

# SDD Phase Progress — AWS Infrastructure Port & Beyond

## Phase Summary (as of May 2026)

| Phase | Name | Status | Key Outcome |
|-------|------|--------|-------------|
| 48 | AWS Infrastructure Port | ✅ COMPLETE | CDK stacks, adapters, migration scripts |
| 49 | Ingestion Pipeline Restructure | ✅ COMPLETE | Model-aware embeddings, registry, search builders |
| 50/50b | S3 Migration Export + Neptune Bulk Load | ✅ COMPLETE | Data migrated to AWS (OpenSearch + Neptune) |
| 51 | Gateway Health/Explain/Search Fixes | ✅ COMPLETE | 3 defects patched, 45/45 tools pass with DB_BACKEND=aws |
| 51b | AgentCore MCP Deployment | 🔶 IN PROGRESS (Step 5+) | Runtime deployed, proxy built, VPC connectivity pending |
| 53 | Neptune Recovery + Re-Ingestion | ✅ COMPLETE (Track A+B) | 164,916 nodes, 2,941,593 rels in Neptune |

## Current Live State (AWS)

| Resource | Endpoint | Data |
|----------|----------|------|
| Neptune | `mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182` | 164,916 nodes, 2,941,593 rels |
| OpenSearch | `vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com` | 85,921+ docs, 17 indices |
| AgentCore Runtime | `mdc_mcp_rag_server-TMXDllG2Wi` (READY, version 2) | 51 tools, MCP protocol |
| ECR Image | `903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:agentcore` | ARM64, node:20-slim |
| S3 Migration | `s3://mdc-mcp-rag-migration/` | Bulk load CSVs, export archives |

## Phase 51b: AgentCore MCP Deployment — Current Focus

**Steps 0–4**: ✅ Complete (tooling, entrypoint, Dockerfile, ECR push, IAM)
**Step 5**: ✅ Runtime deployed (`create_agent_runtime` via Kiro Power)
**Steps 6–9**: ⬜ Pending — VPC connectivity validation, Kiro config switch, bridge retirement

### Blocking Issue
AgentCore microVM needs security group update to reach Neptune (port 8182) and
OpenSearch (port 443) within the VPC. Static tools work; graph/vector tools pending.

### AgentCore Kiro Proxy
- `tools/agentcore-kiro-proxy.py` — stdio MCP bridge (Kiro ↔ AgentCore Runtime via boto3)
- Configured in `.kiro/settings/mcp.json` as `agentcore-mcp-rag`
- 51 tools visible alongside legacy `eib-mcp-gateway`

## Phase 53: Neptune Recovery — COMPLETE (Track A+B)

After the April 22, 2026 Neptune data loss (CDK `removalPolicy: DESTROY` default),
recovery was executed in two tracks:

- **Track A**: S3 bulk load restored the April 7 baseline (~59K nodes)
- **Track B**: Full re-ingestion from current source tree brought the graph to
  164,916 nodes and 2,941,593 relationships (surpassing the original 59K/2.6M
  due to deduplication cleanup and new code merged since April 7)

Track C (automated incremental ingestion) is designed but not yet implemented.

## Next Steps (Priority Order)

1. **Resolve AgentCore ↔ Neptune/OpenSearch VPC connectivity** (security group egress)
2. **Validate all 51 tools through AgentCore** (graph + vector tools)
3. **Switch Kiro MCP config** from legacy `eib-mcp-gateway` to `agentcore-mcp-rag`
4. **Retire dev bridge** (`mcp-http-server.js` on port 3000)
5. **Phase 52**: Bedrock embedding re-ingestion (SageMaker fine-tuning pipeline)
6. **Phase 53 Track C**: Automated incremental ingestion pipeline

## Reference Files

| File | Purpose |
|------|---------|
| `sdd_framework/workflows/phase48_aws_infrastructure_port.md` | CDK + adapters spec |
| `sdd_framework/workflows/phase49_ingestion_pipeline_restructure.md` | Embedding registry + search |
| `sdd_framework/workflows/phase51_gateway_health_explain_search_fixes.md` | 3-defect patch |
| `sdd_framework/workflows/phase51b_agentcore_mcp_deployment.md` | AgentCore deployment |
| `sdd_framework/workflows/phase53_neptune_recovery_incremental_ingestion.md` | Neptune recovery |
| `.kiro/specs/agentcore-mcp-deployment/` | Kiro spec for AgentCore |
| `.kiro/specs/agentcore-kiro-proxy/` | Kiro spec for proxy bridge |
| `docs/postmortem/2026-04-22-neptune-data-loss.md` | CDK data loss post-mortem |
| `docs/mcp-access-architecture-proposal.md` | Two-phase deployment strategy |
