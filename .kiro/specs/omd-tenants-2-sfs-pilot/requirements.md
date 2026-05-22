# Requirements Document

## Introduction

This feature stands up `gw-sfs` as the second tenant on the AgentCore
MCP/RAG runtime, validating the multi-tenant foundation
(`omd-tenants-1-foundation` spec) end-to-end against the smallest
available divergent branch — `dev/sfs` of `NOAA-EMC/global-workflow`.
After this feature lands, an agent asking about
`JGLOBAL_ATMOS_POST` (a J-Job that exists only on `dev/sfs`) gets the
SFS-pillar answer when it queries `gw-sfs` and a "not found" response
when it queries the canonical `gw` (develop) tenant. The smoke suite
gains a branch-isolation probe that asserts this behaviour on every
health check.

This feature is a **proof-of-concept** for the larger `gw-v17-tenant`
work and beyond. The engineering decisions made here (ingestion
slicing, dedupe strategy, validation method, runtime cost) are the
template every subsequent pillar tenant will follow.

This feature **does not** implement shared-component inheritance
(`extends:`), tenant routing (`which_pillar`), lifecycle auto-
deprecation, or auth broker work — those are separate specs.

## Glossary

- **SFS_Pillar**: The Seasonal Forecast System development line,
  represented by the `dev/sfs` branch of
  `NOAA-EMC/global-workflow.git` and the local submodule
  `supported_repos/global-workflow_dev-sfs`.
- **Pillar_Tenant**: A tenant whose `repo_ref` is identical to
  another tenant's `repo_ref` and whose `branch` differs (i.e. two
  branches of the same repository served as separate tenants).
- **Diff_Slice**: The set of files that differ between a pillar's
  branch and `develop` (for `dev/sfs` today: 112 files / +3 829 /
  -145 lines).
- **Content_Addressed_Dedupe**: A storage pattern where two tenants
  share an identical document or graph node by SHA-keyed reference
  rather than by duplicating storage.
- **Branch_Isolation_Probe**: A smoke-suite query that requests a
  symbol known to exist in only one tenant and asserts the other
  tenant returns "not found." Validates that data does not leak
  between tenants.
- **Tenant_Aware_Ingestion**: An ingestion pipeline run that writes
  documents and graph nodes scoped to a specific Tenant_ID's
  `index_prefix` and `label_prefix`.

## Requirements

### Requirement 1: Catalog Entry for `gw-sfs`

**User Story:** As an OMD configuration manager, I want a `gw-sfs`
tenant declared in the catalog, so that the runtime can resolve
SFS-scoped requests.

#### Acceptance Criteria

1. THE Tenant_Catalog SHALL gain an entry `gw-sfs` with
   `tenant_id: gw_sfs`, `repo_ref: NOAA-EMC/global-workflow`,
   `branch: dev/sfs`, `index_prefix: gw_sfs_`, `label_prefix: GW_SFS_`,
   `lifecycle: experimental`, `description` referencing the SFS
   post-processing pipeline.
2. THE entry SHALL declare `extends: [gw]` for forward compatibility
   with workstream 54c (extends is parsed but not acted on by this
   feature).
3. THE catalog validator SHALL accept the new entry without errors.
4. `mcp_health_check(detailed=True)` SHALL list both `gw` and `gw-sfs`
   tenants after this feature lands.

### Requirement 2: Tenant-Aware Ingestion of the SFS Diff Slice

**User Story:** As an operator, I want only the files that differ
between dev/sfs and develop ingested under `gw-sfs`, so that
storage cost is proportional to divergence rather than to repo size.

#### Acceptance Criteria

1. THE ingestion pipeline SHALL accept a `--tenant gw_sfs` flag that
   scopes all writes to the `gw-sfs` tenant's `index_prefix` and
   `label_prefix`.
2. THE pipeline SHALL accept a `--diff-base develop` flag that scopes
   ingestion to the Diff_Slice between `dev/sfs` and `develop`.
3. THE Diff_Slice for the SFS pilot SHALL be at minimum: all files
   under `dev/jobs/JGLOBAL_*_POST`, `dev/scripts/exglobal_*_post.sh`,
   `ush/process_atmos_*.sh`, `ush/process_ocean_*.sh`,
   `ush/python/ocn_diag/*.py`, `dev/parm/config/sfs/*`,
   `parm/archive/*_mem*.yaml.j2`, `parm/stage/master_sfs.yaml.j2`,
   `dev/workflow/applications/sfs.py`,
   `dev/workflow/rocoto/sfs_tasks.py`, `dev/ci/cases/sfsv1/*`,
   plus the 7 platform module files under `modulefiles/gw_atmos_post.*`.
4. WHEN the Diff_Slice contains a file whose content hash matches a
   file already ingested under `gw`, the pipeline SHALL prefer
   Content_Addressed_Dedupe over duplicate ingestion (R5 of Phase 54
   workstream 54d).
5. AFTER the ingestion run completes, the OpenSearch index
   `gw_sfs_workflow-docs-titan1024` SHALL contain at minimum 1
   document per file in the Diff_Slice.
6. AFTER the ingestion run completes, the Neptune graph SHALL contain
   nodes with `GW_SFS_File` labels for every file in the Diff_Slice
   that has a graph representation.

### Requirement 3: Branch-Isolation Probe

**User Story:** As an operator, I want an automated check that
proves data does not leak between tenants, so that I can detect
regression in the foundation isolation guarantees.

#### Acceptance Criteria

1. THE functional smoke suite SHALL gain a probe `branch_isolation`
   that fires the following queries and asserts:
   - `find_dependencies("dev/jobs/JGLOBAL_ATMOS_POST", tenant_id="gw_sfs")`
     SHALL return at least one result.
   - `find_dependencies("dev/jobs/JGLOBAL_ATMOS_POST", tenant_id="gw")`
     SHALL return zero results (file does not exist on develop).
   - `search_documentation("MPAS Voronoi", tenant_id="gw")` SHALL
     return real MPAS hits (existing develop content).
   - `search_documentation("MPAS Voronoi", tenant_id="gw_sfs")` SHALL
     not return any document whose `metadata.source` indicates
     develop (because the gw_sfs tenant has not ingested MPAS
     content; isolation is per-tenant).
2. THE probe SHALL run as part of `mcp_health_check(functional=True)`
   when both `gw` and `gw_sfs` tenants are configured.
3. THE probe SHALL report `[PASS]` only when all four assertions
   above hold.

### Requirement 4: Cost & Storage Validation

**User Story:** As an operator, I want measurable evidence that
content-addressed dedupe is working, so that I can plan the rollout
to subsequent pillars confidently.

#### Acceptance Criteria

1. AFTER ingestion, the operator SHALL be able to compute and log:
   - Net new OpenSearch document count attributable to `gw-sfs`.
   - Net new Neptune node count attributable to `gw-sfs`.
   - Embedding-call count made to Bedrock during ingestion.
2. THE net new OpenSearch document count for the SFS pilot SHALL be
   bounded by the Diff_Slice plus a configurable per-file chunk
   ceiling; the operator SHALL log a `[WARN]` when the count exceeds
   3× the Diff_Slice file count (an indicator of chunking
   misconfiguration).
3. THE incremental cost of the SFS tenant SHALL be reportable as
   "additional Bedrock embeddings spent on dev/sfs ingestion" — the
   value SHALL be ≤ \$5 per the cost projections in the Phase 54 paper
   (the 112-file diff is small).

### Requirement 5: Tenant Attribution Verification

**User Story:** As a developer, I want to clearly see which tenant
produced an answer, so that I can trust the response is scoped to
my working branch.

#### Acceptance Criteria

1. EVERY response from the `gw-sfs` tenant SHALL include the marker
   `*Tenant: gw_sfs*` in its top-level rendered output (per
   foundation Requirement 5.1).
2. THE response SHALL also include the branch reference
   `*Branch: dev/sfs*` to disambiguate from develop.
3. WHEN the smoke suite runs `branch_isolation`, it SHALL assert
   the markers are present in both tenants' responses.

### Requirement 6: Rollback Path

**User Story:** As an operator, I want to be able to remove the
`gw-sfs` tenant cleanly if the pilot reveals problems, so that the
existing `gw` workflow is not disrupted.

#### Acceptance Criteria

1. WHEN the operator removes the `gw-sfs` entry from the catalog and
   restarts the runtime, the existing `gw` tenant SHALL continue to
   serve requests with no behavioural change.
2. WHEN the operator runs the dedupe-aware cleanup script
   `delete_tenant_indices.py --tenant gw_sfs`, the OpenSearch
   indices and Neptune labels prefixed by `gw_sfs_` / `GW_SFS_`
   SHALL be removed without affecting the `gw` data.
3. THE cleanup script SHALL refuse to remove a tenant whose
   `index_prefix` is empty (preventing accidental destruction of
   the `gw` baseline).

### Requirement 7: Documentation

**User Story:** As a future spec author preparing the v17 tenant
onboarding, I want the SFS pilot to leave behind a runbook, so that
the next pillar onboarding does not redo the same investigation.

#### Acceptance Criteria

1. THE feature SHALL produce `docs/runbooks/onboard-pillar-tenant.md`
   documenting the steps from "decide to onboard a pillar" to
   "branch-isolation probe passing": catalog entry, diff-slice
   computation, ingestion command, cost validation, smoke verification.
2. THE runbook SHALL be referenced from the Phase 54 wiki Initiative.
