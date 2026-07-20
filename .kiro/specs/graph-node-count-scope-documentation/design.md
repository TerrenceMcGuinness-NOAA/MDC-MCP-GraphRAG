# Design Document

## Overview

Document the three graph-node-count scopes, annotate each tool's output so it's
self-describing, cross-link them, and optionally expose the whole-graph count via
a flag. Primarily a docs + minor label-tweak phase.

## The three scopes

| Scope | Query | Purpose | Reporter |
|---|---|---|---|
| **Whole-graph** | `MATCH (n) RETURN count(n)` | Platform-wide total including all tenants | manual Cypher; new `--all_tenants` flag |
| **Tenant-scoped** | Labels matching the active tenant's prefix (empty for `gw`) | Per-branch code awareness | `get_knowledge_base_status` |
| **Health-check curated** | A fixed set of primary labels the health probe tracks for stability signal | Drift detection (stable baseline) | `mcp_health_check` |

Why they differ:
- **344,604** (whole-graph) includes all tenant prefixes (`GW_V17_*`, `GW_SFS_*`, etc.) + placeholder/bridge nodes.
- **225,836** (tenant `gw`) includes only unprefixed labels (the `develop` baseline) — which itself includes both the primary code-graph AND legacy/migration nodes.
- **108,280** (health-check) is a curated subset of the `gw` tenant: specifically the labels that the health probe was calibrated against for drift detection. It excludes legacy labels and intermediate-processing nodes.

## Changes

### 1. Documentation page (`docs/development/graph_node_count_scopes.md`)

New markdown file explaining:
- The three scopes + their queries + their purposes
- A "which count do I trust?" decision tree
- The relationship between tenant prefixing and count scoping
- Example output from each tool (current numbers)

### 2. Tool output annotations

**`mcp_health_check`** (in `src/tools/utility.py` or the health-check renderer):
```
[OK] **Graph Database**: healthy - 108,280 nodes (health-check scope), 4,229,217 relationships
```

**`get_knowledge_base_status`** (in `src/tools/semantic_search.py`):
```
- **Total Nodes (tenant scope):** 225,836
```

Additive suffix — the numeric value stays in the same position for parsers.

### 3. Cross-links

- Tool source docstrings: add `See docs/development/graph_node_count_scopes.md`
- Wiki health reports: add a one-line note in the graph section linking to the
  scope page

### 4. `--all_tenants` flag on `get_knowledge_base_status`

Add an optional boolean parameter `all_tenants: bool = False`. When true:
- Run `MATCH (n) RETURN count(n)` (no label filter)
- Return the whole-graph count labeled `Total Nodes (all tenants): N`
  alongside the normal tenant-scoped count

This is a simple additive parameter — does not change the default behavior.

## Testing

- Unit: mock graph returning known counts; assert the scope annotations appear
  in the rendered text; assert `all_tenants=True` returns a larger count.
- Functional: run both tools; confirm the annotations are visible in output;
  confirm `--all_tenants` returns a count ≥ the tenant-scoped count.
- Regression: default output (without `--all_tenants`) byte-identical to
  pre-change modulo the added scope annotation suffix.
