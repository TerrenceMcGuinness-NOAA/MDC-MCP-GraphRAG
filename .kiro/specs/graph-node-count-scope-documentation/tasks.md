# Implementation Plan: Graph Node-Count Scope Documentation

## Overview

Document the three graph-node-count scopes, annotate tool output, cross-link,
and add an optional `--all_tenants` flag. Primarily docs + minor label tweaks.

## Tasks

- [ ] 1. Scope documentation page
  - [ ] 1.1 Write `docs/development/graph_node_count_scopes.md`: the three scopes (whole-graph, tenant-scoped, health-check curated), their queries, purposes, current counts, and a "which count do I trust?" decision tree
    - _Requirements: 1.1, 1.2_
  - [ ] 1.2 Add cross-link from the wiki health-status reports to the scope page
    - _Requirements: 1.3, 3.2_

- [ ] 2. Annotate tool output
  - [ ] 2.1 `mcp_health_check`: add `(health-check scope)` suffix to the node count in the "Graph Database" line
    - _Requirements: 2.1, 5.4_
  - [ ] 2.2 `get_knowledge_base_status`: add `(tenant scope)` suffix to the "Total Nodes" line (or `(tenant <id>)`)
    - _Requirements: 2.2, 5.4_
  - [ ] 2.3 Verify numeric values unchanged (annotation additive only)
    - _Requirements: 2.3_

- [ ] 3. Cross-links in tool source
  - [ ] 3.1 Add `See docs/development/graph_node_count_scopes.md` reference in the docstrings of `mcp_health_check` and `get_knowledge_base_status`
    - _Requirements: 3.1_

- [ ] 4. `--all_tenants` flag
  - [ ] 4.1 Add `all_tenants: bool = False` parameter to `get_knowledge_base_status`; when true, run an unfiltered `MATCH (n) RETURN count(n)` and include the result labeled `Total Nodes (all tenants): N`
    - _Requirements: 4.1, 4.2_
  - [ ] 4.2 Verify default behavior (without `--all_tenants`) is unchanged
    - _Requirements: 4.2_

- [ ] 5. Testing
  - [ ] 5.1 Functional: run `get_knowledge_base_status` → confirm tenant-scope annotation visible; run with `all_tenants=True` → confirm whole-graph count ≥ tenant count
  - [ ] 5.2 Functional: run `mcp_health_check` → confirm `(health-check scope)` annotation visible
  - [ ] 5.3 Confirm downstream wiki reports link to the scope page

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1", "2.2", "4.1"] },
    { "id": 1, "tasks": ["1.2", "2.3", "3.1", "4.2"] },
    { "id": 2, "tasks": ["5.1", "5.2", "5.3"] }
  ]
}
```
