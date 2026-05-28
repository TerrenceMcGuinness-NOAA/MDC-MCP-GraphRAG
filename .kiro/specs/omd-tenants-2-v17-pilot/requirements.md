# Requirements Document

## Introduction

This feature stands up `gw_v17` as the first production-track pillar
tenant on the AgentCore MCP/RAG runtime, validating the multi-tenant
foundation (`omd-tenants-1-foundation` spec) end-to-end against the
next operational GFS version — `dev/gfs.v17` of
`NOAA-EMC/global-workflow`. After this feature lands, an agent asking
about `JGDAS_ATMOS_ANALYSIS_WDQMS` (a J-Job that exists only on
`dev/gfs.v17`) gets the v17-pillar answer when it queries `gw_v17`
and a "not found" response when it queries the canonical `gw`
(develop) tenant. The smoke suite gains a branch-isolation probe that
asserts this behaviour on every health check.

Unlike the SFS pilot (experimental lifecycle, 112-file diff-slice),
the v17 tenant is **staging lifecycle** — it represents the next
operational GFS and carries a higher quality bar. The diff between
`dev/gfs.v17` and `develop` is substantially larger (major version
upgrade spanning jobs, scripts, parm, ush, sorc, and workflow
directories). Consequently, this pilot uses **full-branch ingestion**
rather than diff-only slicing: all code and documentation on
`dev/gfs.v17` is ingested under the `gw_v17` tenant scope.

This feature produces the **onboarding runbook**
(`docs/runbooks/onboard-pillar-tenant.md`) that subsequent tenants
(SFS, JEDI-GFS, GEFS v12) will follow.

This feature **does not** implement shared-component inheritance
(`extends:`), tenant routing (`which_pillar`), lifecycle auto-
deprecation, or auth broker work — those are separate specs.

## Glossary

- **V17_Pillar**: The GFS v17 development line, represented by the
  `dev/gfs.v17` branch of `NOAA-EMC/global-workflow.git` and the
  local submodule `supported_repos/global-workflow_dev-v17`.
- **Pillar_Tenant**: A tenant whose `repo_ref` is identical to
  another tenant's `repo_ref` and whose `branch` differs (i.e. two
  branches of the same repository served as separate tenants).
- **Full_Branch_Ingestion**: An ingestion strategy where the entire
  content of a branch is ingested under a tenant's scope, rather
  than only the diff against `develop`. Appropriate for staging-
  lifecycle tenants with large divergence from the baseline.
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
- **EFS_Worktree**: A git worktree on the shared EFS mount
  (`/mnt/workflow`) that provides the runtime with read access to a
  specific branch's file tree. The v17 worktree path is
  `/mnt/workflow/dev-v17`.

## Requirements

### Requirement 1: Catalog Entry Verification for `gw_v17`

**User Story:** As an OMD configuration manager, I want the existing
`gw_v17` catalog entry validated as correct, so that the runtime can
resolve v17-scoped requests without modification.

#### Acceptance Criteria

1. THE Tenant_Catalog SHALL contain an entry with `tenant_id: gw_v17`,
   `repo_ref: NOAA-EMC/global-workflow`, `branch: dev/gfs.v17`,
   `index_prefix: "gw_v17_"`, `label_prefix: "GW_V17_"`,
   `workflow_subdir: dev-v17`, `lifecycle: staging`, and a
   `description` referencing the next operational GFS version.
2. THE entry SHALL declare `extends: []` (no inheritance in this
   pilot; forward compatibility with workstream 54c).
3. THE catalog validator SHALL accept the entry without errors; IF
   the entry has malformed syntax or missing required fields, THEN
   the catalog validator SHALL have already rejected it at server
   startup (per foundation R1.6) before this feature's scope begins.
   This requirement assumes the entry is pre-validated and always
   passes catalog validation.
4. `mcp_health_check(detailed=True)` SHALL list both `gw` and
   `gw_v17` tenants after this feature lands.

### Requirement 2: EFS Worktree for `dev-v17`

**User Story:** As an operator, I want the `dev/gfs.v17` branch
available as a worktree on the shared EFS mount, so that the
ingestion pipeline and runtime can access v17 files at
`/mnt/workflow/dev-v17`.

#### Acceptance Criteria

1. THE `populate_workflow_efs.sh` script SHALL create a git worktree
   at `/mnt/workflow/dev-v17` tracking the `dev/gfs.v17` branch of
   `NOAA-EMC/global-workflow`.
2. AFTER the worktree is created, the path
   `/mnt/workflow/dev-v17/dev/jobs/JGDAS_ATMOS_ANALYSIS_WDQMS` SHALL
   exist and be readable.
3. THE worktree SHALL be refreshable via `git -C /mnt/workflow/dev-v17
   pull --ff-only` without manual intervention.
4. IF the worktree already exists at the target path, THEN THE script
   SHALL skip creation and log an informational message rather than
   failing.

### Requirement 3: Tenant-Aware Full-Branch Ingestion of v17

**User Story:** As an operator, I want the full content of the
`dev/gfs.v17` branch ingested under the `gw_v17` tenant scope, so
that agents querying v17 get comprehensive answers covering all
jobs, scripts, configuration, and workflow definitions.

#### Acceptance Criteria

1. THE ingestion pipeline SHALL accept a `--tenant gw_v17` flag that
   scopes all writes to the `gw_v17` tenant's `index_prefix`
   (`gw_v17_`) and `label_prefix` (`GW_V17_`).
2. THE pipeline SHALL accept a `--mode full` flag that ingests the
   entire branch content rather than a diff-slice.
3. THE full-branch ingestion for v17 SHALL cover at minimum:
   - All J-Job scripts under `dev/jobs/` (approximately 90 files)
   - All ex-scripts under `dev/scripts/`
   - All utility scripts under `ush/` and `dev/ush/`
   - All parameter files under `parm/` and `dev/parm/`
   - All workflow definitions under `dev/workflow/`
   - All CI test cases under `dev/ci/`
   - All ecFlow definitions under `ecf/`
   - All modulefiles under `modulefiles/`
   - All version files under `versions/`
   - Source code metadata under `sorc/` (build manifests, not
     compiled binaries)
4. WHEN the full-branch ingestion encounters a file whose content
   hash matches a file already ingested under `gw`, the pipeline
   SHALL prefer Content_Addressed_Dedupe over duplicate ingestion
   (R5 of Phase 54 workstream 54d).
5. AFTER the ingestion run completes, the OpenSearch index
   `gw_v17_workflow-docs-titan1024` SHALL contain documents covering
   the full branch content.
6. AFTER the ingestion run completes, the Neptune graph SHALL contain
   nodes with `GW_V17_File` labels for every file in the branch that
   has a graph representation.
7. THE ingestion pipeline SHALL log a summary report including:
   total files processed, documents created, documents deduped,
   embedding calls made, and elapsed time.

### Requirement 4: Branch-Isolation Probe

**User Story:** As an operator, I want an automated check that
proves data does not leak between tenants, so that I can detect
regression in the foundation isolation guarantees.

#### Acceptance Criteria

1. THE functional smoke suite SHALL gain a probe `branch_isolation`
   that fires the following queries and asserts:
   - `find_dependencies("dev/jobs/JGDAS_ATMOS_ANALYSIS_WDQMS", tenant_id="gw_v17")`
     SHALL return at least one result (file exists only on
     `dev/gfs.v17`).
   - `find_dependencies("dev/jobs/JGDAS_ATMOS_ANALYSIS_WDQMS", tenant_id="gw")`
     SHALL return zero results (file does not exist on develop).
   - `search_documentation("MPAS Voronoi", tenant_id="gw")` SHALL
     return real MPAS hits (existing develop content).
   - `search_documentation("MPAS Voronoi", tenant_id="gw_v17")` SHALL
     not return any document whose `metadata.source` indicates
     develop-only content (isolation is per-tenant; v17 has its own
     ingested corpus).
2. THE probe SHALL run as part of `mcp_health_check(functional=True)`
   when both `gw` and `gw_v17` tenants are configured.
3. THE probe SHALL report `[PASS]` only when all four assertions
   above hold.
4. THE probe SHALL use an operationally meaningful v17-unique symbol
   (`JGDAS_ATMOS_ANALYSIS_WDQMS` — the WDQMS quality-monitoring
   job added in v17) rather than a trivial test fixture.

### Requirement 5: Cost & Storage Validation

**User Story:** As an operator, I want measurable evidence of the
storage and cost impact of full-branch ingestion for a staging
tenant, so that I can plan capacity for subsequent pillar rollouts.

#### Acceptance Criteria

1. AFTER ingestion, the operator SHALL be able to compute and log:
   - Net new OpenSearch document count attributable to `gw_v17`.
   - Net new Neptune node count attributable to `gw_v17`.
   - Embedding-call count made to Bedrock during ingestion.
   - Deduplicated document count (files shared with `gw` that were
     not re-embedded).
2. THE net new OpenSearch document count for the v17 pilot SHALL be
   bounded by the total branch file count multiplied by a
   configurable per-file chunk ceiling; the operator SHALL log a
   `[WARN]` when the count exceeds 3× the branch file count (an
   indicator of chunking misconfiguration).
3. THE incremental cost of the v17 tenant SHALL be reportable as
   "additional Bedrock embeddings spent on dev/gfs.v17 ingestion."
   Given full-branch ingestion of approximately 500+ files, the
   projected cost SHALL be documented and compared against the
   Phase 54 cost model.
4. THE cost report SHALL include a dedupe efficiency metric:
   `(files_deduped / total_files_processed) × 100%` — representing
   the percentage of files that did not require new embeddings due
   to content-addressed sharing with the `gw` tenant.

### Requirement 6: Tenant Attribution Verification

**User Story:** As a developer, I want to clearly see which tenant
produced an answer, so that I can trust the response is scoped to
the v17 branch.

#### Acceptance Criteria

1. EVERY response from the `gw_v17` tenant SHALL include the marker
   `*Tenant: gw_v17*` in its top-level rendered output (per
   foundation Requirement 5.1).
2. THE response SHALL also include the branch reference
   `*Branch: dev/gfs.v17*` to disambiguate from develop.
3. WHEN the smoke suite runs `branch_isolation`, it SHALL assert
   the markers are present in both tenants' responses.

### Requirement 7: Rollback Path

**User Story:** As an operator, I want to be able to remove the
`gw_v17` tenant cleanly if the pilot reveals problems, so that the
existing `gw` workflow is not disrupted.

#### Acceptance Criteria

1. WHEN the operator removes the `gw_v17` entry from the catalog and
   restarts the runtime, the existing `gw` tenant SHALL continue to
   serve requests with no behavioural change.
2. WHEN the operator runs the dedupe-aware cleanup script
   `delete_tenant_indices.py --tenant gw_v17`, the OpenSearch
   indices and Neptune labels prefixed by `gw_v17_` / `GW_V17_`
   SHALL be removed without affecting the `gw` data.
3. THE cleanup script SHALL refuse to remove a tenant whose
   `index_prefix` is empty (preventing accidental destruction of
   the `gw` baseline).
4. WHEN the operator removes the EFS worktree via
   `git worktree remove /mnt/workflow/dev-v17`, the remaining
   worktrees (`/mnt/workflow/develop` and any others) SHALL be
   unaffected.

### Requirement 8: Onboarding Runbook Documentation

**User Story:** As a future spec author preparing subsequent tenant
onboardings (SFS, JEDI-GFS, GEFS v12), I want the v17 pilot to
leave behind a runbook, so that the next pillar onboarding follows
a proven, repeatable process.

#### Acceptance Criteria

1. THE feature SHALL produce `docs/runbooks/onboard-pillar-tenant.md`
   documenting the steps from "decide to onboard a pillar" to
   "branch-isolation probe passing": catalog entry validation, EFS
   worktree creation, ingestion mode selection (diff-slice vs
   full-branch), ingestion command, cost validation, smoke
   verification, and rollback procedure.
2. WHERE the runbook is produced (per criterion 8.1), THE runbook
   SHALL include a decision matrix for choosing between diff-slice
   and full-branch ingestion based on tenant lifecycle
   (experimental → diff-slice, staging/production → full-branch)
   and branch divergence size.
3. THE runbook SHALL be referenced from the Phase 54 wiki Initiative.
4. THE runbook SHALL include the v17 pilot as a worked example with
   actual cost and storage metrics from the ingestion run.
