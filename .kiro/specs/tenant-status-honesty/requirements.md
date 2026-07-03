# Requirements: Tenant Status Honesty in Health Reporting

## Introduction

Phase 63c retirement surfaced a recurring reporting hazard: the string
`Tenants: 5` produced by `get_server_info` and `mcp_health_check` counts
catalog entries, not populated tenants. On the COTS Parallel Works host,
only two of the five configured tenants are actually queryable end-to-end:

| Tenant | ChromaDB (local) | Neo4j (local) |
|---|---|---|
| `gw` | 15 collections / 220,538 docs | 17,273 files / full graph |
| `gw_v17` | (empty — vector lives on AWS OpenSearch) | 30,221 files graph-only |
| `gw_sfs` | empty | empty |
| `gw_jedi_gfs` | empty | empty |
| `gw_gefs_v12` | empty | empty |

The empirical smoke queries in `mcp_server_python/src/tools/smoke_queries.py`
DO run against real data and DO include a tenant-isolation probe
(`_smoke_branch_isolation`) — but that probe is hard-scoped to `gw` and
`gw_v17` (explicit guard: `if "gw" not in tids or "gw_v17" not in tids:
raise SkipProbe`). The other three tenants have no smoke coverage. The v17
pilot spec (`omd-tenants-2-v17-pilot`) was the last one that landed a smoke
probe; the sfs pilot spec is requirements-only, and jedi_gfs / gefs_v12 have
no pilot spec at all.

Result: reports read as "multi-tenant healthy" while three of five stores
are silently empty. This spec adds the two smallest fixes that would have
caught the state before it required a live cypher-shell drill-down to detect.

## Glossary

- **Catalog_Tenant**: A tenant defined in `mcp_server_python/src/config/tenants.yaml`.
- **Populated_Tenant**: A Catalog_Tenant whose configured backend stores contain
  at least one document (vector) OR at least one prefixed node (graph).
- **Empty_Tenant**: A Catalog_Tenant with zero documents AND zero prefixed
  nodes. Not a fault — just never ingested.
- **Health_Tool**: `mcp_health_check` (`mcp_server_python/src/tools/utility.py`).
- **Server_Info_Tool**: `get_server_info` (same module).
- **Smoke_Registry**: The list of `SmokeQueryDef` objects in
  `mcp_server_python/src/tools/smoke_queries.py` that
  `mcp_health_check(functional=True)` iterates.
- **Data_Probe**: A smoke query that issues a real ChromaDB or Neo4j query
  and asserts non-empty result. Contrast with a plumbing check (import
  resolves, catalog loads, filesystem path exists).

## Requirements

### Requirement 1: Per-tenant data-status column in the health tenants table

**User Story:** As an operator running `mcp_health_check`, I want the tenants
table to show whether each tenant has data on the current backend, so that
"5 tenants" cannot be misread as "5 populated tenants".

#### Acceptance Criteria

1. THE Health_Tool tenants table SHALL gain a new column `data` with value
   `populated`, `graph-only`, `vector-only`, or `empty` for each row.
2. THE `populated` value SHALL indicate BOTH `collections > 0` in the vector
   store (with tenant prefix) AND `File`-labelled nodes > 0 in the graph
   store (with tenant prefix).
3. THE `graph-only` value SHALL indicate graph nodes > 0 AND vector
   collections == 0. (Current state of `gw_v17` on COTS.)
4. THE `vector-only` value SHALL indicate vector collections > 0 AND graph
   nodes == 0.
5. THE `empty` value SHALL indicate BOTH stores are empty for the tenant's
   prefix.
6. THE per-tenant probe SHALL execute against the same adapters
   `mcp_health_check` already holds a reference to (no new dependencies).
7. IF an adapter probe raises, THE cell SHALL render `probe-error` (never
   silently downgrade to `empty`), and THE overall status SHALL stay
   `HEALTHY` (probe failure ≠ server failure).
8. THE row SHALL be produced by the base `mcp_health_check()` call — i.e.
   WITHOUT requiring `functional=True` — because the plumbing-vs-data trap
   fires on the base call.

### Requirement 2: Fix the misleading `[ERROR] Unhealthy` label in `get_knowledge_base_status`

**User Story:** As an operator running `get_knowledge_base_status(tenant_id=X)`
for an Empty_Tenant, I want the tool to say "empty" not "unhealthy", so that
an untriaged report does not send someone chasing a nonexistent fault.

#### Acceptance Criteria

1. WHEN `get_knowledge_base_status(tenant_id=X)` finds zero collections AND
   zero graph nodes, THE Status field SHALL render `[INFO] Empty (never
   ingested)`.
2. WHEN it finds partial data (graph-only or vector-only), THE Status field
   SHALL render `[INFO] Partial: <populated-half>` (e.g. `[INFO] Partial: graph`).
3. WHEN it finds data in both halves, THE Status field SHALL render `[OK]
   Healthy` (unchanged from today).
4. `[ERROR] Unhealthy` SHALL be reserved for genuine adapter errors (query
   raised, connection failed, prefix routing broken).

### Requirement 3: Broaden `_smoke_branch_isolation` to every catalog tenant

**User Story:** As a spec-first maintainer, I want the branch-isolation smoke
probe to iterate every Catalog_Tenant and record per-tenant coverage, so that
adding a new tenant to the catalog automatically extends the empirical check.

#### Acceptance Criteria

1. THE Smoke_Registry SHALL add a new probe `tenant_coverage` that, for each
   Catalog_Tenant, asserts at least one of the following:
   - `File`-labelled nodes exist under the tenant's label prefix, OR
   - at least one collection matches the tenant's index prefix.
2. WHEN a tenant satisfies neither, THE probe SHALL emit a per-tenant
   `[SKIP] never-ingested` line — a distinct status from `SkipProbe` (which
   means "prerequisite not met"). The overall probe SHALL still return
   `pass` unless ALL tenants are empty.
3. THE existing `_smoke_branch_isolation` probe SHALL remain unchanged
   (still hard-scoped to `gw` + `gw_v17`) — this requirement adds a sibling,
   it does not modify the existing one.
4. THE new probe SHALL appear in the `mcp_health_check(functional=True)`
   output alongside the existing 11 probes.

### Requirement 4: Documentation

**User Story:** As a reader of the changelog and steering, I want the
plumbing-vs-data distinction called out, so that future summaries don't
recreate the confusion.

#### Acceptance Criteria

1. `.kiro/steering/07-tenant-usability-gaps.md` SHALL gain a Gap C section
   describing the plumbing-vs-data reporting hazard, referencing the tool
   locations that need to be read for actual per-tenant status.
2. `CHANGELOG.md` SHALL gain a Phase 63d entry when this spec's tasks land.

## Non-Goals

- Ingesting data into the empty tenants. That is a separate, larger effort
  (per-tenant COTS ingestion pipelines) that would land under a
  `phase63e_cots_tenant_ingest_*` series.
- Changing the `[8.22.0]` cosmetic aggregation bug in
  `get_knowledge_base_status` where the default-tenant total incorrectly
  sums across prefixes. Related but out of scope.
- Modifying `mcp_health_check`'s existing 4-component summary. Only the
  tenants table gains a column.
- Touching the AWS side. This is COTS-only.
