# Requirements Document

## Introduction

Three MCP tools each report a different Neo4j/Neptune node count for the same
graph. None is wrong, but the scopes are undocumented:

| Reporter | Count (2026-07-20) | Scope |
|---|---:|---|
| `cypher-shell MATCH (n) RETURN count(n)` | 344,604 | All labels, all tenant prefixes |
| `get_knowledge_base_status` (tenant `gw`) | 225,836 | Empty label_prefix (base develop tenant) |
| `mcp_health_check` "Graph Database" summary | 108,280 | Curated subset (stable across 10+ snapshots) |

Without documentation, a first-time reader sees three disagreeing numbers and
cannot tell which to trust. This phase documents the scopes, annotates each
tool's output so the scope is self-describing, and adds a cross-link so the
answer is always one hop away.

Phase 73 from the SDD
(`sdd_framework/workflows/phase73_graph_node_count_scope_documentation.md`),
surfaced in the 2026-07-20 gap analysis ("Informational — Not a Gap" section).

## Requirements

### Requirement 1: Scope documentation page

**User Story:** As a new-to-the-codebase engineer, I want a single page that
explains why three tools report three different node counts.

#### Acceptance Criteria

1. A new doc SHALL exist at `docs/development/graph_node_count_scopes.md`
   explaining the three scopes (whole-graph, tenant-scoped, health-check curated
   subset) with the current counts and the rationale for each.
2. THE doc SHALL include a table mapping each reporting tool to its scope and
   why that scope is appropriate for that tool's purpose.
3. THE doc SHALL be discoverable within one hop from the wiki health-status
   reports (cross-linked in the "Informational" or "Known differences" section).

### Requirement 2: Tool output annotates its scope

**User Story:** As an operator reading tool output, I want the count labeled so
I immediately know which scope I'm looking at.

#### Acceptance Criteria

1. `mcp_health_check` SHALL annotate its graph-node count with a scope label,
   e.g. `108,280 nodes (health-check curated subset)`.
2. `get_knowledge_base_status` SHALL annotate its node count with a scope label,
   e.g. `Total Nodes (tenant gw): 225,836`.
3. THE numeric values SHALL remain unchanged (annotation is additive — suffix,
   not prefix — so downstream parsers that grep the number still work).

### Requirement 3: Cross-links between tools

**User Story:** As a reader, I want a one-hop path from any of the three count
outputs to the explanation page.

#### Acceptance Criteria

1. Each tool's output docstring (in the tool's Python source) SHALL reference
   `docs/development/graph_node_count_scopes.md` or a stable URL/path for the
   scope explanation.
2. THE wiki health-status reports SHALL link to the scope page in their "graph
   database" sections.

### Requirement 4: Optional whole-graph count exposure

**User Story:** As an operator troubleshooting parity, I want access to the raw
whole-graph count without running a manual Cypher query.

#### Acceptance Criteria

1. `get_knowledge_base_status` SHALL accept an optional `--all_tenants` flag
   (or equivalent parameter) that returns the whole-graph count (all labels,
   all prefixes) alongside the tenant-scoped count.
2. THE whole-graph count SHALL be clearly labeled `(all tenants, all labels)` to
   distinguish it from the per-tenant default.

### Requirement 5: Boundaries

#### Acceptance Criteria

1. THE feature SHALL NOT reconcile or unify the three counts into one (the scopes
   are legitimately different and should stay different).
2. THE feature SHALL NOT change the ChromaDB adapter (Phase 70) or the coverage-gap
   path (Phase 72).
3. THE feature SHALL NOT auto-commit or auto-push.
4. THE numeric values in existing output SHALL remain stable (annotations are
   additive only — no downstream parsing breakage).
