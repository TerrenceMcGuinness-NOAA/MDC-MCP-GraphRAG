# Onboard a Pillar Tenant

Checklist for onboarding a new pillar tenant (a branch of
`NOAA-EMC/global-workflow` served as a separate tenant on the
AgentCore MCP/RAG runtime).

## 1. Pre-flight Checks

- [ ] CDK access point exists: `fsap-03e641f056b341f29`
- [ ] IAM `efs-clientmount-workflow-ap` policy attached to
      `mdc-mcp-rag-ecs-task-role`
- [ ] EFS mounted at `/mnt/workflow` on the runtime (verify via
      `mcp_health_check(detailed=True)` → Workflow Filesystem section)
- [ ] Operator EC2 host is in the same VPC as the EFS file system

## 2. Catalog Entry Validation

Ensure the new tenant row exists in `mcp_server_python/src/config/tenants.yaml`
and passes validation:

```bash
python3.12 -m src.config.tenants validate \
    mcp_server_python/src/config/tenants.yaml
```

Exit 0 = valid. Exit 1 = structural error (fix before proceeding).

## 3. Decision Matrix: diff vs full Ingestion Mode

| Tenant divergence from develop | `lifecycle` | Recommended `--mode` |
|---|---|---|
| < 200 changed files | `experimental` | `diff` |
| 200–1500 changed files OR major version | `staging` | `full` |
| New release branch | `production` | `full` |
| Active feature branch in flux | `experimental` | `diff` |

When `--mode` is omitted, the scripts derive it from `tenant.lifecycle`:
- `experimental` → `diff`
- `staging` / `production` → `full`
- `merged` / `stale` → refused (must use explicit `--mode` override)

## 4. EFS Worktree Creation

From the operator EC2 host (NOT the AgentCore runtime):

```bash
bash mcp_server_python/scripts/populate_workflow_efs.sh
```

The script reads `tenants.yaml` and creates one worktree per tenant.
Existing worktrees are fast-forwarded; new ones are added. See
`mcp_server_python/scripts/README_populate_workflow_efs.md` for details.

Verify:

```bash
ls /mnt/efs-staging/supported_repos/global-workflow/<workflow_subdir>/
```

## 5. Ingestion Command

Run the three v8 entry scripts with `--tenant` and `--mode`:

```bash
python3.12 mcp_server_python/scripts/ingest_documentation_v8.py \
    --tenant <tenant_id> --mode full --tiers tier1_global_workflow

python3.12 mcp_server_python/scripts/ingest_code_v8.py \
    --tenant <tenant_id> --mode full

python3.12 mcp_server_python/scripts/ingest_jjobs_v8.py \
    --tenant <tenant_id> --mode full
```

Each script produces a JSON report under
`mcp_server_python/scripts/ingestion_reports/`.

## 6. Cost Validation

Read the JSON reports:

```bash
cat mcp_server_python/scripts/ingestion_reports/<tenant_id>_*.json | python3.12 -m json.tool
```

Check:
- `drift_flags` array is empty (or document the deviation)
- `dedupe_efficiency_pct` is in the expected `[20.0, 50.0]` range
- `warnings` array has no unexpected `[WARN]` entries

## 7. Smoke Probe Verification

From the MCP client:

```
mcp_health_check(functional=True)
```

Confirm `branch_isolation: [PASS]` (requires both `gw` and the new
tenant to be present in the catalog with ingested data).

## 8. Rollback Procedure

If the pilot reveals problems:

```bash
# 1. Review what would be deleted
python3.12 mcp_server_python/scripts/delete_tenant_indices.py \
    --tenant <tenant_id> --dry-run

# 2. Execute deletion (removes prefixed indices + Neptune nodes)
python3.12 mcp_server_python/scripts/delete_tenant_indices.py \
    --tenant <tenant_id>

# 3. Remove EFS worktree (manual — script cannot write to EFS)
git -C /mnt/efs-staging/.git worktree remove \
    /mnt/efs-staging/supported_repos/global-workflow/<workflow_subdir>

# 4. Remove catalog entry from tenants.yaml, redeploy runtime
```

The `gw` baseline is unaffected (empty-prefix protection in the
delete script refuses to touch unprefixed data).

## 9. Worked Example: v17 Pilot

TODO(Phase D): Fill with actual metrics after the v17 ingestion run.

- Tenant: `gw_v17`
- Branch: `dev/gfs.v17`
- Mode: `full`
- Documents created: TODO(Phase D)
- Documents deduped: TODO(Phase D)
- Dedupe efficiency: TODO(Phase D)
- Embedding calls (Bedrock invocations): TODO(Phase D)
- Estimated tokens: TODO(Phase D)
- Elapsed time (documentation): TODO(Phase D)
- Elapsed time (code): TODO(Phase D)
- Elapsed time (jjobs): TODO(Phase D)
- Drift flags: TODO(Phase D)
- Cost estimate: TODO(Phase D)

## 10. Phase 54 Wiki Cross-Reference

TODO(Phase D): Add link to the Phase 54 Initiative wiki page after
it is created. The wiki page should link back to this runbook.
