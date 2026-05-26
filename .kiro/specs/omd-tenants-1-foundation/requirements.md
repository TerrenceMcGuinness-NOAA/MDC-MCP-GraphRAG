# Requirements Document

## Introduction

This feature lays the foundation for the OMD Multi-Pillar MCP Initiative
(Phase 54) by introducing a tenant catalog and per-tenant data isolation
to the AgentCore MCP/RAG server. After this feature lands, the existing
runtime serves the same 52 tools but every response carries a
`tenant_id`, every OpenSearch query is scoped to a tenant index prefix,
every Neptune query is scoped to a tenant label prefix, and every
filesystem-backed tool reads from a tenant-specific subdirectory of a
shared EFS mount. The existing service surface is preserved as the
canonical tenant `gw` (the `develop` branch of `NOAA-EMC/global-workflow`);
no other tenants are configured by this feature, but the plumbing
required to add them is fully in place. Subsequent features
(`omd-tenants-2-sfs-pilot`, `gw-v17-tenant`, etc.) build on the
foundation defined here.

Because all currently planned tenants are branches of the same
`NOAA-EMC/global-workflow` repository, the foundation also introduces a
shared workflow filesystem: a single git bare clone with one `git
worktree` per tenant branch, served from the AWS EFS filesystem
`fs-032d52e4677000758` (already provisioned via `mdc-data-stack.ts`)
mounted into the AgentCore runtime at `/mnt/workflow`. Each tenant's
catalog entry names a `workflow_subdir` under that mount (e.g.
`develop`, `dev-sfs`) which contains the worktree for that tenant's
branch. This replaces the previous per-container `MCP_WORKFLOW_ROOT`
env var with a per-tenant resolved path and removes the need for
per-tenant container rebuilds.

Adding the EFS mount also resolves the current `workflow_info` health
check failure. The smoke probe `_smoke_workflow_info` looks for a
`jobs/` directory beneath the resolved workflow root; today the
container has no `global-workflow` checkout at any of the expected
paths, so the probe reports the module unhealthy. With the worktree
under `/mnt/workflow/develop/jobs` (or `/mnt/workflow/develop/dev/jobs`),
the smoke probe finds a real directory and the Default_Tenant smoke run
passes.

This feature **does not** ingest any new branch data, **does not**
introduce shared-component inheritance (`extends:`), **does not**
implement cross-tenant routing or `which_pillar` recommendation, and
**does not** implement lifecycle/staleness markers. Those are tracked
separately under workstreams 54c, 54d, 54e, and 54g of Phase 54. This
feature also **does not** include the ingestion-side helper that
populates the EFS bare clone and worktrees from the host's existing
`supported_repos/global-workflow/` checkout — that helper is called out
in Requirement 12 but its implementation lives outside the runtime.

## Glossary

- **Tenant**: A logical scope that maps a (repo_ref, branch) pair to an
  isolated data view inside the shared MCP server.
- **Tenant_Catalog**: A YAML configuration file declaring the set of
  tenants and their per-tenant settings (index prefix, label prefix,
  branch, lifecycle state, workflow subdirectory, etc.).
- **Tenant_ID**: A short snake_case identifier (e.g. `gw`, `gw_sfs`)
  uniquely naming a tenant in the catalog. Maps 1:1 to `index_prefix`,
  `label_prefix`, and `workflow_subdir`.
- **Index_Prefix**: A string prepended to every OpenSearch index name
  for documents written or read on behalf of a tenant (e.g. `gw_` →
  `gw_workflow_docs`).
- **Label_Prefix**: A string prepended to every Neptune node label for
  graph data written or read on behalf of a tenant (e.g. `GW_` →
  `GW_File`).
- **Default_Tenant**: The tenant that requests with no explicit
  `tenant_id` resolve to. For backward compatibility this defaults to
  `gw` (the existing develop-branch data view).
- **Tenant_Aware_Tool**: A tool whose data-access calls have been
  modified to scope queries by tenant; equivalently, a tool that can
  serve different tenants without code changes.
- **Tenant_Resolution**: The process by which an incoming request is
  mapped to a Tenant_ID, by reading either an explicit `tenant_id`
  field in the request, an `MCP_DEFAULT_TENANT` env var, or the
  Default_Tenant fallback.
- **Migration_Mode**: A transitional configuration in which the
  OpenSearch indices and Neptune labels still use their unprefixed
  names but the tools accept and propagate `tenant_id` for forward
  compatibility. Used during data backfill.
- **Workflow_EFS**: The shared `mdc-mcp-rag-efs` filesystem
  (`fs-032d52e4677000758`, us-east-1) that backs all tenants' workflow
  worktrees and is mounted into the AgentCore runtime at
  `/mnt/workflow`.
- **Workflow_Subdir**: The per-tenant subdirectory name under the
  Workflow_EFS mount that contains the git worktree for that tenant's
  branch (e.g. `develop` for tenant `gw`, `dev-sfs` for tenant
  `gw_sfs`). A single-segment name with no path separators.
- **Workflow_Bare_Repo**: The single shared bare clone of
  `NOAA-EMC/global-workflow` at `<EFS>/.git` whose object store backs
  every tenant's worktree. Lives outside the EFS_Access_Point root and
  is therefore not visible to the AgentCore runtime.
- **EFS_Access_Point**: The AWS EFS access point that mounts a chosen
  root directory into AgentCore with a fixed POSIX UID/GID. For this
  feature the access point pins root path
  `/supported_repos/global-workflow` and POSIX UID/GID `1000:1000` to
  match the container's `app` user.
- **Workflow_Root**: The per-tenant resolved filesystem path
  `Path("/mnt/workflow") / tenant.workflow_subdir` exposed on the
  request-scoped tenant context object as `ctx.tenant.workflow_root`.

## Requirements

### Requirement 1: Tenant Catalog Schema

**User Story:** As an OMD configuration manager, I want a single
declarative file that defines all tenants, so that adding a new
tenant is a configuration change rather than a code change.

#### Acceptance Criteria

1. THE Tenant_Catalog SHALL be a YAML file at
   `mcp_server_python/src/config/tenants.yaml` declaring a `tenants`
   list and a `defaults` block.
2. EACH entry in the `tenants` list SHALL contain at minimum:
   `tenant_id`, `repo_ref`, `branch`, `index_prefix`, `label_prefix`,
   `workflow_subdir`, `lifecycle` (one of `experimental`, `staging`,
   `production`, `merged`, `stale`), and `description`.
3. EACH entry MAY contain an `extends` list of Tenant_ID values
   declaring inheritance (parsed and validated by this feature; not
   acted on — that is workstream 54c).
4. EACH entry MAY contain `staleness_threshold_days` overriding the
   `defaults.staleness_threshold_days` (used by 54g; declared here).
5. THE Tenant_Catalog SHALL include exactly one `gw` tenant configured
   for the `develop` branch of `NOAA-EMC/global-workflow` with
   `index_prefix: ""`, `label_prefix: ""`, and
   `workflow_subdir: develop` (preserving existing index and label
   names for backward compatibility — see Requirement 7 — and matching
   the seed worktree on EFS — see Requirement 12).
6. THE Tenant_Catalog SHALL be validated at server startup; an invalid
   catalog SHALL cause the server to refuse to start with a structured
   error message naming the offending field.
7. WHEN two tenants declare the same `tenant_id`, the catalog
   validator SHALL raise a `DuplicateTenantError`.
8. WHEN a tenant declares `extends: [foo]` and `foo` is not a known
   `tenant_id`, the catalog validator SHALL raise an
   `UnknownTenantReferenceError`.
9. WHEN a tenant declares an `index_prefix` or `label_prefix` that is
   not a valid OpenSearch index name component / valid Neptune label
   prefix (alphanumeric + underscore + final underscore), the catalog
   validator SHALL raise an `InvalidPrefixError`.
10. WHEN two tenants declare the same `workflow_subdir` value, the
    catalog validator SHALL raise a `DuplicateWorkflowSubdirError`
    naming both conflicting tenants.
11. WHEN a tenant declares a `workflow_subdir` value containing a path
    separator (`/` or `\`), a leading dot, or any character outside
    the set `[A-Za-z0-9._-]`, the catalog validator SHALL raise an
    `InvalidWorkflowSubdirError`.

### Requirement 2: Tenant Resolution

**User Story:** As a developer using the MCP server, I want my
requests to default to the canonical tenant when I do not specify
one, so that the existing single-tenant workflow continues to work.

#### Acceptance Criteria

1. WHEN an incoming MCP tool request includes a `tenant_id` field
   matching a known tenant, THE server SHALL resolve the request to
   that tenant.
2. WHEN an incoming request does not include a `tenant_id`, THE server
   SHALL resolve to the value of the `MCP_DEFAULT_TENANT` environment
   variable.
3. WHEN `MCP_DEFAULT_TENANT` is unset, THE server SHALL resolve to
   the catalog's `defaults.tenant_id` value.
4. WHEN `defaults.tenant_id` is unset, THE server SHALL resolve to
   `gw`.
5. WHEN an incoming request specifies a `tenant_id` that is not in the
   catalog, THE server SHALL return a structured error
   `UnknownTenantError` with the offending value and a list of known
   tenants.
6. THE resolved tenant SHALL be made available to every tool through a
   request-scoped context object (e.g. `ctx.tenant`).
7. THE request-scoped tenant context object SHALL expose a
   `workflow_root` property whose value equals
   `Path("/mnt/workflow") / tenant.workflow_subdir`.
8. WHERE a tool previously read the `MCP_WORKFLOW_ROOT` environment
   variable to locate the workflow filesystem, THE tool SHALL instead
   read `ctx.tenant.workflow_root`.

### Requirement 3: Per-Tenant OpenSearch Isolation

**User Story:** As a configuration manager, I want each tenant's
documents stored in its own set of indices, so that one tenant's
data cannot leak into another tenant's search results.

#### Acceptance Criteria

1. WHEN the OpenSearch adapter receives a query call from a
   Tenant_Aware_Tool, THE adapter SHALL prepend the tenant's
   `index_prefix` to the requested index name before executing the
   query.
2. WHEN the OpenSearch adapter writes a document, THE adapter SHALL
   prepend the tenant's `index_prefix` to the target index name.
3. WHEN a tenant's `index_prefix` is the empty string, THE adapter
   SHALL pass the index name through unchanged (preserving backward
   compatibility for the `gw` tenant during migration).
4. THE OpenSearch adapter SHALL expose a method
   `resolve_tenant_index(collection, tenant)` that returns the final
   index name for a given (collection, tenant) pair; the same method
   SHALL be reused by the manifest registry and the gap detector.
5. THE per-tenant resolution SHALL be applied uniformly across all 7
   semantic_search tools, all 5 ee2_compliance tools, all 4
   operational tools, and the GraphRAG `find_similar_code` tool — i.e.
   every tool that touches OpenSearch.

### Requirement 4: Per-Tenant Neptune Isolation

**User Story:** As a configuration manager, I want each tenant's
graph nodes scoped by label, so that graph queries cannot return
nodes from another tenant.

#### Acceptance Criteria

1. WHEN the Neptune adapter receives a Cypher query from a
   Tenant_Aware_Tool, THE adapter SHALL rewrite each node label
   reference to include the tenant's `label_prefix`.
2. WHEN the Neptune adapter writes a node, THE adapter SHALL prepend
   the tenant's `label_prefix` to each label in the node's label set.
3. WHEN a tenant's `label_prefix` is the empty string, THE adapter
   SHALL pass labels through unchanged (preserving backward
   compatibility for the `gw` tenant during migration).
4. THE Neptune adapter SHALL expose a method
   `resolve_tenant_labels(labels, tenant)` that returns the prefixed
   labels for a given (labels, tenant) pair.
5. THE per-tenant label resolution SHALL be applied uniformly across
   all 6 code_analysis tools and the GraphRAG tools that use Neptune.

### Requirement 5: Tenant Attribution in Responses

**User Story:** As a developer using the agent, I want every
response to declare which tenant produced it, so that I can audit
which branch's code I am reasoning about.

#### Acceptance Criteria

1. EVERY response from a Tenant_Aware_Tool SHALL include the resolved
   `tenant_id` in its top-level rendered output (markdown header
   line: `*Tenant: <tenant_id>*`).
2. WHEN the resolved tenant has `lifecycle: stale` or its
   `staleness_threshold_days` has been exceeded, the response SHALL
   prepend a `[STALE]` marker (full implementation deferred to 54g;
   the field SHALL be present and respected here).
3. THE health check tool (`mcp_health_check`) SHALL list the active
   tenants and the resolved default tenant.
4. THE `get_server_info` tool SHALL report the count of registered
   tenants.

### Requirement 6: Tool Surface Backward Compatibility

**User Story:** As an existing user of the AgentCore MCP, I want my
current Kiro IDE workflow to keep working unchanged, so that
multi-tenancy can be deployed without forcing client updates.

#### Acceptance Criteria

1. WHEN a client sends an MCP tool call with no `tenant_id` field,
   the call SHALL succeed and SHALL resolve to the Default_Tenant
   (`gw` for the canonical setup).
2. THE 52 tools that exist before this feature lands SHALL remain in
   the catalog with unchanged names, behaviour, and interfaces. The
   catalog MAY grow beyond 52 tools — i.e. this feature MAY add new
   tenant-management tools — but SHALL NOT remove or alter any
   existing tool.
3. THE input schemas of the 52 tools SHALL gain an optional
   `tenant_id` parameter; absence SHALL not affect existing client
   behaviour.
4. THE output of any tool SHALL be byte-equal to the pre-feature
   output for the `gw` tenant when migration is complete and indices
   / labels are unprefixed (the `gw` tenant has empty prefixes per
   Requirement 1.5).
5. WHEN a client sends a request with no `tenant_id`, THE server
   SHALL resolve `ctx.tenant.workflow_root` to `/mnt/workflow/develop`
   (the `gw` tenant's `workflow_subdir`), preserving identical
   filesystem-backed responses for `describe_component`,
   `get_system_configs`, and `get_workflow_structure`.

### Requirement 7: Migration Mode for the `gw` Tenant

**User Story:** As an operator, I want to deploy multi-tenancy
without re-ingesting the existing 199K documents and 149K nodes, so
that the rollout is reversible and low-cost.

#### Acceptance Criteria

1. THE `gw` tenant SHALL be configured with empty `index_prefix` and
   empty `label_prefix` so that the existing OpenSearch indices
   (`mdc-workflow-docs-titan1024`, etc.) and Neptune labels (`File`,
   `FortranSubroutine`, etc.) remain in place unchanged.
2. NO ingestion run is required by this feature; existing data is
   served from existing indices and labels under the canonical `gw`
   tenant.
3. WHEN a future feature adds a tenant with non-empty prefixes, that
   feature SHALL be responsible for the new tenant's ingestion.
4. THE gap detector SHALL be modified to report per-tenant rather than
   global gap counts, with the existing `gw` data showing under
   `gw` and zero gaps reported for tenants with no ingested data.
5. THE `gw` tenant SHALL be configured with `workflow_subdir: develop`
   so that its `Workflow_Root` resolves to `/mnt/workflow/develop`,
   matching the seed worktree populated from the EC2 host's existing
   `supported_repos/global-workflow/` checkout (see Requirement 12).

### Requirement 8: Configuration & Observability

**User Story:** As an operator, I want to see the tenant catalog
status and the resolved-tenant count in the existing health output,
so that I can confirm multi-tenant routing is working without
adding new monitoring tooling.

#### Acceptance Criteria

1. `mcp_health_check(detailed=True)` SHALL include a "Tenants" section
   listing each tenant with its `tenant_id`, branch, lifecycle,
   index/label prefix, and `workflow_subdir`.
2. `mcp_health_check(functional=True)` SHALL run the existing per-
   module smoke queries against the Default_Tenant.
3. The new functional smoke `tenant_routing` SHALL be added: a query
   sent with `tenant_id: gw` and the same query sent with no
   `tenant_id` SHALL return identical results when migration is
   complete.
4. The standalone `smoke_test_tools.py` script SHALL accept a
   `--tenant <tenant_id>` flag scoping its smoke runs to a specific
   tenant; default behaviour is to test all configured tenants.
5. `mcp_health_check(detailed=True)` SHALL include for each tenant a
   per-tenant filesystem-reachability indicator that reports the
   result of `Path(ctx.tenant.workflow_root).is_dir()`.
6. `mcp_health_check(detailed=True)` SHALL include a new component
   `Workflow Filesystem` reporting whether `/mnt/workflow` is mounted
   (i.e. exists and is a directory) and listing the immediate
   subdirectories present beneath it.

### Requirement 9: Schema Evolution Safety

**User Story:** As a future spec author, I want the catalog schema
to be extensible without breaking existing deployments, so that
adding lifecycle states, staleness thresholds, and `extends:` fields
is incremental.

#### Acceptance Criteria

1. UNKNOWN top-level fields in a tenant entry SHALL be ignored with a
   `[WARN]` log line, not raise an error (forward compatibility).
2. THE catalog schema version SHALL be encoded in the YAML as
   `schema_version: 1`; future schema changes increment this.
3. THE catalog loader SHALL accept `schema_version: 1` for this
   release and SHALL refuse a higher version with a clear "this
   server is older than the catalog" error.

### Requirement 10: Validation Surface

**User Story:** As a developer authoring a downstream tenant spec,
I want a validation entry point I can call to check my catalog
edit, so that I catch schema errors before deploying.

#### Acceptance Criteria

1. THE module SHALL expose a CLI entry point
   `python3.12 -m src.config.tenants validate <path>` that loads,
   validates, and prints a summary of the catalog.
2. THE CLI SHALL exit 0 on a structurally valid catalog, 1 on a
   structurally invalid catalog, and 2 on an unreachable file.
3. WHERE non-structural issues are detected (unknown forward-compat
   fields per Requirement 9.1, deprecation warnings, or other
   advisory diagnostics), THE CLI SHALL print them as `[WARN]` lines
   AND SHALL exit 0; exit code 1 is reserved for structural
   violations only.
4. THE validation summary SHALL list each tenant's resolved
   `index_prefix`, `label_prefix`, `workflow_subdir`, `lifecycle`, and
   an inheritance chain (when `extends:` is set).

### Requirement 11: Shared Workflow Filesystem Mount

**User Story:** As an OMD operator, I want a single shared EFS volume
mounted into the AgentCore runtime, so that all tenants' branch
worktrees are served from one place without per-tenant container
rebuilds.

#### Acceptance Criteria

1. THE EFS_Access_Point SHALL be created on the Workflow_EFS
   filesystem `fs-032d52e4677000758` with POSIX UID `1000`, POSIX GID
   `1000`, and root path `/supported_repos/global-workflow`.
2. THE AgentCore runtime `mdc_mcp_rag_server_python-v5K2F8BGrN` SHALL
   be configured via `--filesystem-configurations` on
   `update-agent-runtime` to mount the EFS_Access_Point at
   `/mnt/workflow`.
3. THE AgentCore filesystem mount SHALL be configured read-only.
4. THE execution role `mdc-mcp-rag-ecs-task-role` SHALL include an
   inline policy granting `elasticfilesystem:ClientMount` on the
   EFS_Access_Point ARN, gated by an `ArnEquals` condition on
   `elasticfilesystem:AccessPointArn`.
5. THE execution role SHALL NOT be granted
   `elasticfilesystem:ClientWrite` on the EFS_Access_Point (the mount
   is read-only and the runtime never writes to it).
6. WHILE the runtime is active, THE container's `app` user (UID 1000,
   GID 1000) SHALL be able to read every file beneath
   `/mnt/workflow/<workflow_subdir>/` for every tenant in the
   catalog.
7. THE Workflow_EFS SHALL have a mount target in each subnet used by
   the AgentCore runtime; specifically:
   - `subnet-0e13af6b3a9a6416f` → mount target `fsmt-0dde562311128b447`
   - `subnet-04447750c61bd7e06` → mount target `fsmt-0ecbb5f8abd5b4b5f`
   - `subnet-024fd9b597b3075a5` → mount target `fsmt-09e82de3fa561101b`
8. IF the EFS mount target Availability Zones do not overlap the
   runtime's subnet Availability Zones, THEN the deployment validation
   SHALL fail with a clear `EFSMountTargetAZMismatchError` naming the
   missing AZ.
9. THE EFS security group `sg-04bd2b41beecd1201` SHALL permit inbound
   TCP 2049 from the AgentCore security group `sg-096489a0876cc78c1`,
   AND the AgentCore security group SHALL permit outbound TCP 2049 to
   the EFS security group.

### Requirement 12: Per-Tenant Git Worktree Layout

**User Story:** As an OMD operator, I want each tenant's branch served
from a git worktree of a single shared bare clone, so that disk usage
is minimized and branch updates are atomic.

#### Acceptance Criteria

1. THE Workflow_EFS SHALL contain a single Workflow_Bare_Repo at
   `<EFS>/.git`, initialized as a bare clone of
   `https://github.com/NOAA-EMC/global-workflow.git`.
2. EACH tenant in the catalog SHALL have exactly one git worktree at
   `<EFS>/<workflow_subdir>` checked out at that tenant's `branch`.
3. EACH worktree's files and directories SHALL be readable by UID
   `1000` and GID `1000` (i.e. owned by, or group-readable to, the
   container's `app` user) so that AgentCore can serve them under the
   read-only EFS mount.
4. THE Workflow_Bare_Repo at `<EFS>/.git` SHALL reside outside the
   EFS_Access_Point root path `/supported_repos/global-workflow` (or
   the access point root SHALL be configured so the bare repo is not
   visible inside the mount), so that the AgentCore runtime never
   sees a `.git/` directory at `/mnt/workflow/.git`.
5. THE feature SHALL document an ingestion-time helper script
   (implementation out of scope for the runtime) that:
   - initializes the Workflow_Bare_Repo on first run;
   - creates each tenant's worktree via `git worktree add
     <EFS>/<workflow_subdir> <branch>`;
   - updates each worktree via `git -C <EFS>/<workflow_subdir> pull
     --ff-only`;
   - chowns the resulting files to `1000:1000`.
6. THE seed content for the `gw` tenant's worktree
   (`/mnt/workflow/develop`) SHALL be the EC2 host's existing
   `supported_repos/global-workflow/` checkout, and the seed content
   for any future `gw_sfs` tenant's worktree (`/mnt/workflow/dev-sfs`)
   SHALL be the host's existing `supported_repos/global-workflow_dev-sfs/`
   checkout.
7. THE feature SHALL NOT require runtime-side write access to the
   Workflow_EFS; all worktree mutations occur through the helper
   script run from the operator host.

### Requirement 13: workflow_info Smoke Health Restoration

**User Story:** As an operator monitoring the runtime, I want
`mcp_health_check(functional=True)` to report `workflow_info` as
healthy, so that operational dashboards reflect the true state of the
runtime.

#### Acceptance Criteria

1. WHEN `mcp_health_check(functional=True)` is invoked with no
   `tenant_id`, THE `_smoke_workflow_info` probe SHALL execute against
   the Default_Tenant's `Workflow_Root` (which resolves to
   `/mnt/workflow/develop` for the canonical `gw` tenant) and SHALL
   return a healthy status.
2. THE `_smoke_workflow_info` probe SHALL accept either
   `<workflow_root>/jobs` or `<workflow_root>/dev/jobs` as a directory
   for the healthy condition (preserving the existing dual-path
   behaviour).
3. WHEN `mcp_health_check(functional=True, tenant=<tenant_id>)` is
   invoked, THE `_smoke_workflow_info` probe SHALL execute against
   the named tenant's `Workflow_Root` rather than the Default_Tenant's.
4. IF the resolved `Workflow_Root` does not exist or contains neither
   `jobs/` nor `dev/jobs/`, THEN `_smoke_workflow_info` SHALL report
   the module unhealthy with a structured error naming the resolved
   path and the missing subdirectory.
5. THE Default_Tenant smoke run SHALL pass after this feature lands;
   this acceptance criterion is the regression test for the
   pre-feature `workflow_info` health-check failure described in the
   Introduction.
