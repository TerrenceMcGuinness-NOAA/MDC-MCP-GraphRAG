---
inclusion: auto
---

# Phase 48 Progress — AWS Infrastructure Port

## Current State (2026-03-30)

**SDD Session**: `session_2026-03-30_phase48` — 4/25 steps complete
**Branch**: `develop_aws`
**Last Commit**: `4831b6a` — "Phase 48 Steps 6,8,10,11: Adapter pattern + SDD spec for AWS port"

## Completed Steps — DO NOT REDO

| Step | Tag | What Was Built | Commit |
|------|-----|----------------|--------|
| 6 | design | `VectorDatabaseAdapter.js` (16 methods), `GraphDatabaseAdapter.js` (34 methods) | 4831b6a |
| 8 | implement | `ChromaDBLegacyAdapter.js` — passthrough wrapper around VectorDatabase | 4831b6a |
| 10 | implement | `Neo4jLegacyAdapter.js` — passthrough wrapper around GraphDatabase | 4831b6a |
| 11 | implement | `backend-selector.js` + 3-line change to `UnifiedDataAccess.js` | 4831b6a |

All adapter files are in `mcp_server_node/src/data/adapters/`.
`UnifiedDataAccess.js` now calls `selectDatabaseBackend()` in its constructor.

## Next Steps — Ready to Execute

### Phase 48A: CDK Infrastructure (Steps 1–5)

**Step 1** — Scaffold CDK project and VPC stack:
- `cdk init app --language typescript` in `infrastructure/cdk/`
- `MdcVpcStack`: VPC, 2 AZs, public/private subnets, NAT Gateway
- 4 VPC endpoints: Secrets Manager, SSM, CloudWatch, S3

**Step 2** — Security stack (`MdcSecurityStack`):
- Secrets Manager: `mdc-mcp-rag/neptune/credentials`, `mdc-mcp-rag/github/token`
- SSM: `/mdc-mcp-rag/neptune/endpoint`, `/mdc-mcp-rag/opensearch/endpoint`
- Cognito user pool, WAF web ACL, IAM roles for ECS
- No secrets in CloudFormation outputs

**Step 3** — Data stack (`MdcDataStack`):
- Neptune cluster (openCypher, IAM auth, private subnets, KMS)
- OpenSearch domain (k-NN plugin, nmslib, HNSW, 768-dim)
- EFS filesystem (`/mdc-mcp-rag`)
- S3 bucket `mdc-mcp-rag-migration`
- Security groups: ECS→Neptune (8182), ECS→OpenSearch (443)

**Step 4** — Validate: `cdk synth` must succeed for all 3 stacks

**Step 5** — `resolveConfig()` in `mcp_server_node/src/config/aws-config.js`:
- Fetch from Secrets Manager + SSM Parameter Store
- Cache for process lifetime
- Fall back to env vars with warning log
- Never log secret values

### Phase 48B: Remaining Adapter + Server Work (Steps 7, 9, 12–14)

**Step 7** — OpenSearch adapter (`OpenSearchAdapter.js`):
- k-NN search with 768-dim embeddings
- AWS SigV4 auth
- Metadata filter → OpenSearch bool query
- Score normalization to [0,1]

**Step 9** — Neptune adapter (`NeptuneAdapter.js`) + APOC transform:
- openCypher queries via Neptune bolt endpoint
- `apoc-transform.js`: 5 APOC procedure replacements
- `apoc.algo.dijkstra` is HIGHEST RISK — needs Gremlin fallback
- Throw `UnsupportedQueryError` for unknown APOC

**Step 12** — Property tests (P1–P3, P7) for adapter output compatibility

**Step 13** — `MdcServerStack`: ECS Fargate (1 vCPU, 2GB), ALB, API Gateway, CloudFront + WAF

**Step 14** — Health check (healthy/degraded), graceful degradation, exponential backoff retry

## Merge Strategy (CRITICAL — lesson from Phase 47)

Phase 47 Rocoto work lost code when `develop` was merged into a feature branch,
silently reverting prior work. For `develop_aws`:

- **NEVER merge `develop` into `develop_aws`** without reviewing the diff for removals
- Push completed phases from `develop_aws` → `develop` as finished units
- AWS-specific code lives exclusively on `develop_aws` until cutover

## Data Migration Overview (Phase 48C, Steps 15–19)

Migration uses S3 as a staging area:
```
Legacy (PW VM)                    AWS
ChromaDB → export → S3 bucket → OpenSearch bulk API
Neo4j    → export → S3 bucket → Neptune bulk loader
```

5 ChromaDB collections (~85K docs, ~380MB):
| Collection | OpenSearch Index | Docs |
|------------|-----------------|------|
| `code-with-context-v8-0-0` | `mdc-code-context` | ~58,761 |
| `global-workflow-docs-v8-0-0` | `mdc-workflow-docs` | ~3,514 |
| `jjobs-v8-0-0` | `mdc-jjobs` | ~700 |
| `community-summaries` | `mdc-community-summaries` | ~828 |
| `ee2-standards-v5-0-0-enhanced` | `mdc-ee2-standards` | ~34 |

Embeddings transfer bitwise (768-dim MPNet) — no re-generation needed.

## Reference Files

| File | Purpose |
|------|---------|
| `sdd_framework/workflows/phase48_aws_infrastructure_port.md` | Full SDD spec (25 steps) |
| `.kiro/specs/aws-infrastructure-port/requirements.md` | 17 requirements (design authority) |
| `.kiro/specs/aws-infrastructure-port/design.md` | AWS topology + component mapping |
| `.kiro/specs/aws-infrastructure-port/tasks.md` | Kiro task breakdown (uses "Phase 46" numbering) |
| `sdd_framework/execution_state/active_session.json` | Live session state |
| `sdd_framework/execution_state/history.jsonl` | Audit trail |
