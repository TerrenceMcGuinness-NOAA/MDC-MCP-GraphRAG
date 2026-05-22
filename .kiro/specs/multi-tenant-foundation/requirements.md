# Requirements Document

## Introduction

This feature lays the foundation for the OMD Multi-Pillar MCP Initiative
(Phase 54) by introducing a tenant catalog and per-tenant data isolation
to the AgentCore MCP/RAG server. After this feature lands, the existing
runtime serves the same 52 tools but every response carries a
`tenant_id`, every OpenSearch query is scoped to a tenant index prefix,
and every Neptune query is scoped to a tenant label prefix. The existing
service surface is preserved as the canonical tenant `gw` (the
`develop` branch of `NOAA-EMC/global-workflow`); no other tenants are
configured by this feature, but the plumbing required to add them is
fully in place. Subsequent features (`gw-sfs-tenant-pilot`,
`gw-v17-tenant`, etc.) build on the foundation defined here.

This feature **does not** ingest any new branch data, **does not**
introduce shared-component inheritance (`extends:`), **does not**
implement cross-tenant routing or `which_pillar` recommendation, and
**does not** implement lifecycle/staleness markers. Those are tracked
separately under workstreams 54c, 54d, 54e, and 54g of Phase 54.

## Glossary

- **Tenant**: A logical scope that maps a (repo_ref, branch) pair to an
  isolated data view inside the shared MCP server.
- **Tenant_Catalog**: A YAML configuration file declaring the set of
  tenants and their per-tenant settings (index prefix, label prefix,
  branch, lifecycle state, etc.).
- **Tenant_ID**: A short snake_case identifier (e.g. `gw`, `gw_sfs`)
  uniquely naming a tenant in the catalog. Maps 1:1 to `index_prefix`
  and `label_prefix`.
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
   `lifecycle` (one of `experimental`, `staging`, `production`,
   `merged`, `stale`), and `description`.
3. EACH entry MAY contain an `extends` list of Tenant_ID values
   declaring inheritance (parsed and validated by this feature; not
   acted on — that is workstream 54c).
4. EACH entry MAY contain `staleness_threshold_days` overriding the
   `defaults.staleness_threshold_days` (used by 54g; declared here).
5. THE Tenant_Catalog SHALL include exactly one `gw` tenant configured
   for the `develop` branch of `NOAA-EMC/global-workflow` with
   `index_prefix: ""` and `label_prefix: ""` (preserving existing
   index and label names for backward compatibility — see Requirement 7).
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
   validator SHALL raise a `InvalidPrefixError`.

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
2. THE 52-tool catalog SHALL be unchanged — no tool is added or
   removed by this feature.
3. THE input schemas of the 52 tools SHALL gain an optional
   `tenant_id` parameter; absence SHALL not affect existing client
   behaviour.
4. THE output of any tool SHALL be byte-equal to the pre-feature
   output for the `gw` tenant when migration is complete and indices
   / labels are unprefixed (the `gw` tenant has empty prefixes per
   Requirement 1.5).

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

### Requirement 8: Configuration & Observability

**User Story:** As an operator, I want to see the tenant catalog
status and the resolved-tenant count in the existing health output,
so that I can confirm multi-tenant routing is working without
adding new monitoring tooling.

#### Acceptance Criteria

1. `mcp_health_check(detailed=True)` SHALL include a "Tenants" section
   listing each tenant with its `tenant_id`, branch, lifecycle, and
   index/label prefix.
2. `mcp_health_check(functional=True)` SHALL run the existing per-
   module smoke queries against the Default_Tenant.
3. The new functional smoke `tenant_routing` SHALL be added: a query
   sent with `tenant_id: gw` and the same query sent with no
   `tenant_id` SHALL return identical results when migration is
   complete.
4. The standalone `smoke_test_tools.py` script SHALL accept a
   `--tenant <tenant_id>` flag scoping its smoke runs to a specific
   tenant; default behaviour is to test all configured tenants.

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
2. THE CLI SHALL exit 0 on a valid catalog, 1 on a structurally
   invalid catalog, 2 on an unreachable file.
3. THE validation summary SHALL list each tenant's resolved
   `index_prefix`, `label_prefix`, `lifecycle`, and an inheritance
   chain (when `extends:` is set).
