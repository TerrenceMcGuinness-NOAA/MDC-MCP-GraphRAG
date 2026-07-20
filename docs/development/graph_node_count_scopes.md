# Graph Node-Count Scopes

Three MCP tools each report a different Neo4j / Neptune **node count** for the
same graph. None is wrong — they answer different questions. This page explains
the three scopes so a first-time reader can tell which number to trust.

> SDD Phase 73 (`.kiro/specs/graph-node-count-scope-documentation/`). Surfaced in
> the 2026-07-20 Docker MCP Gateway gap analysis ("Informational — Not a Gap").

## The three scopes

| Scope | Query | Reporter | What it answers |
|-------|-------|----------|-----------------|
| **Whole-graph** | `MATCH (n) RETURN count(n)` (no label filter) | manual Cypher; `get_knowledge_base_status(all_tenants=True)` | "How many nodes exist in the entire store, across every tenant?" |
| **Tenant-scoped** | nodes whose labels match the active tenant's prefix (empty prefix = the `gw` / `develop` baseline) | `get_knowledge_base_status` (default) | "How many nodes belong to the branch I'm querying?" |
| **Health-check curated** | a fixed set of primary labels the health probe tracks | `mcp_health_check` "Graph Database" | "Is the graph's core code-structure population stable (drift signal)?" |

### Illustrative counts (point-in-time, 2026-07-20)

These are example magnitudes from the gap-analysis snapshot, not live values
(the live numbers grow as branches are ingested):

| Reporter | Count | Scope |
|----------|------:|-------|
| `cypher-shell MATCH (n) RETURN count(n)` | 344,604 | whole-graph (all labels, all tenant prefixes) |
| `get_knowledge_base_status` (tenant `gw`) | 225,836 | tenant-scoped (empty label prefix = `develop` baseline) |
| `mcp_health_check` "Graph Database" | 108,280 | health-check curated subset (stable across 10+ snapshots) |

## Why they differ

- **Whole-graph (largest)** includes every tenant's prefixed labels
  (`GW_V17_*`, `GW_SFS_*`, `GW_GEFS_V12_*`, …) plus placeholder / bridge nodes
  created during ingestion. It is the sum across all branches the platform
  knows about.
- **Tenant-scoped (`gw`)** counts only the unprefixed labels — the `develop`
  baseline. It excludes the other tenants' prefixed nodes. For a non-default
  tenant (e.g. `gw_v17`) it counts only that tenant's `GW_V17_*` labels. This
  is the number that matches "the branch I passed `tenant_id` for".
- **Health-check curated (smallest)** is a deliberately narrow, fixed set of
  primary code-structure labels (files, functions, modules, subroutines, …)
  that the health probe was calibrated against. It excludes legacy/migration
  labels and intermediate-processing nodes, so it stays **stable** across
  tenant additions and is a clean drift signal — a sudden change means real
  ingestion drift, not just "another branch was added".

## Which count do I trust?

```
Are you comparing branches / auditing the whole store?
   → whole-graph:  get_knowledge_base_status(all_tenants=True)
Are you asking about ONE branch's code awareness?
   → tenant-scoped: get_knowledge_base_status(tenant_id="…")   (default = gw)
Are you monitoring for drift / "did the graph change unexpectedly"?
   → health-check curated: mcp_health_check
```

They are **not** reconciled into one number on purpose — the scopes are
legitimately different and each tool needs its own.

## Tenant prefixing ↔ count scoping

Tenant isolation in the graph is by **label prefix** (`GW_V17_File` vs the
unprefixed `File`). Because the tenant-scoped count filters on that prefix, the
default `gw` count is "everything unprefixed" and each non-default tenant's
count is "everything with my prefix". The whole-graph count ignores prefixes
entirely. See `.kiro/steering/09-agentcore-mcp-for-global-workflow.md` (tenant
model) and `.kiro/steering/12-multi-tenant-gap-tracker.md` (Gap E — label-based
scoping) for the isolation mechanics.

## Tool output annotations

Each tool now names its scope inline so the number is self-describing:

- `mcp_health_check` → `… - <N> nodes (health-check scope), <M> relationships`
- `get_knowledge_base_status` → `- **Total Nodes (tenant <id>):** <N>`, and with
  `all_tenants=True` an extra `- **Total Nodes (all tenants, all labels):** <N>`

The numeric values are unchanged; the scope label is an additive suffix so
downstream parsers that grep the number keep working.
