# Implementation Plan: Graph Node-Count Scope Documentation

## Overview

Document the three graph-node-count scopes, annotate tool output, cross-link,
and add an optional `--all_tenants` flag. Primarily docs + minor label tweaks.

## Tasks

- [x] 1. Scope documentation page
  - [x] 1.1 Wrote `docs/development/graph_node_count_scopes.md`: the three scopes (whole-graph, tenant-scoped, health-check curated), their queries, purposes, counts, and a "which count do I trust?" decision tree
    - _Requirements: 1.1, 1.2_
  - [~] 1.2 Cross-link from the wiki health-status reports — the wiki lives in the `supported_repos/global-workflow.wiki` **submodule** (a separate repo); editing it is an operator step. The doc itself cross-links to the steering tenant docs, and both tools' output/docstrings now point at the doc (R3.1), so the answer is one hop from tool output.
    - _Requirements: 1.3, 3.2_

- [x] 2. Annotate tool output
  - [x] 2.1 `mcp_health_check`: `… <N> nodes (health-check scope), <M> relationships`
    - _Requirements: 2.1, 5.4_
  - [x] 2.2 `get_knowledge_base_status`: `- **Total Nodes (tenant scope):** <N>` (or `(tenant <id>)` when a tenant id is resolved)
    - _Requirements: 2.2, 5.4_
  - [x] 2.3 Numeric values unchanged (additive suffix only) — verified live: tenant count renders `225836` (no comma, greppable), scope added to the label only
    - _Requirements: 2.3_

- [x] 3. Cross-links in tool source
  - [x] 3.1 Both `mcp_health_check` and `get_knowledge_base_status` tool descriptions reference `docs/development/graph_node_count_scopes.md`; `_whole_graph_node_count` docstring too
    - _Requirements: 3.1_

- [x] 4. `all_tenants` flag
  - [x] 4.1 Added `all_tenants: bool = False` to `get_knowledge_base_status`; when true runs an unfiltered `MATCH (n) RETURN count(n)` (via `_whole_graph_node_count`, not tenant-scoped) and appends `- **Total Nodes (all tenants, all labels):** N`; graceful `[unavailable]` on query failure (Neptune full-scan timeout)
    - _Requirements: 4.1, 4.2_
  - [x] 4.2 Default (without `all_tenants`) unchanged — no whole-graph line; verified live + unit test
    - _Requirements: 4.2_

- [x] 5. Testing
  - [x] 5.1 Functional (live Neo4j): `get_knowledge_base_status` → `Total Nodes (tenant scope): 225836`; `all_tenants=True` → adds `Total Nodes (all tenants, all labels): 344604` (whole 344604 ≥ tenant 225836 ✓) — matches the spec's documented values
  - [x] 5.2 `mcp_health_check` → `(health-check scope)` annotation present (unit test `test_health_check_annotates_graph_node_scope`, detailed mode)
  - [~] 5.3 Wiki reports link to the scope page — operator step (wiki submodule; see 1.2)

## Verification status

- **Unit**: full suite 1329 passed / 26 failed (all 26 pre-existing; 0
  regressions; was 1322/26 after Phase 72). New: `test_node_count_scopes.py` (6),
  `test_health_check_annotates_graph_node_scope`, `all_tenants` default assertion,
  and the tool-schema test updated to include `all_tenants`.
- **Live functional** (read-only, Neo4j `bolt://localhost:7687`): see 5.1 / 5.2.
- **Operator step**: cross-linking the `global-workflow.wiki` submodule to the
  new doc page (tasks 1.2 / 5.3) — not editable from this repo autonomously.

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
