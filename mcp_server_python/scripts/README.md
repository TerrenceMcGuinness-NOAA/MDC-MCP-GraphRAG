# MCP Server Python — Scripts

Operator-side tools for the AgentCore MCP/RAG runtime. These scripts
run from the EC2 operator host (not inside the runtime container).

## Tenant Onboarding

See **[Onboard a Pillar Tenant](../../docs/runbooks/onboard-pillar-tenant.md)**
for the full checklist covering EFS provisioning, ingestion, verification,
and rollback.

## Key Scripts

| Script | Purpose |
|--------|---------|
| `populate_workflow_efs.sh` | Multi-tenant EFS worktree provisioning |
| `ingest_documentation_v8.py` | Tenant-aware documentation ingestion |
| `ingest_code_v8.py` | Tenant-aware code metadata ingestion |
| `ingest_jjobs_v8.py` | Tenant-aware J-Job ingestion |
| `delete_tenant_indices.py` | Rollback — remove a tenant's prefixed data |

## Internal Modules

| Module | Purpose |
|--------|---------|
| `_ingest_common.py` | Shared CLI helpers (argparse, mode derivation) |
| `_ingest_cost_model.py` | JSON report writer + drift detection |
| `_ingest_dedupe.py` | Cross-tenant SHA-256 content-addressed dedupe |
| `_ingest_walkers.py` | File enumeration (full-branch, diff) |
| `_populate_worktrees.py` | Testable git worktree management logic |
