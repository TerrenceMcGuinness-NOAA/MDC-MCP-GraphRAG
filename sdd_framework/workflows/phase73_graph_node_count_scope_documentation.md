# Phase 73 — Graph Node-Count Scope Documentation

**Version**: 0.1.0
**Created**: 2026-07-20
**Status**: draft (requirement captured; not scheduled)
**Estimated effort**: TBD (small — docs + minor label tweaks)
**Depends on**: none
**Kiro spec**: _(to be authored — `.kiro/specs/graph-node-count-scope-documentation/`)_
**Owner**: TBD

---

## 1. Executive Summary

Three MCP tools each return a different Neo4j node count for the same graph,
none is wrong, but the scopes are undocumented:

| Reporter | Count (2026-07-20) | Scope |
|----------|--------------------:|-------|
| `cypher-shell MATCH (n) RETURN count(n)` | 344,604 | All labels, all tenant prefixes |
| `get_knowledge_base_status` (tenant `gw`) | 225,836 | Empty label_prefix (base develop tenant) |
| `mcp_health_check` "Graph Database" summary | 108,280 | Curated subset (stable across 10 snapshots) |

The 108,280 value has been rock-stable across every health snapshot since
2026-06-26 — it is not drift and not a bug. But without documentation, a
first-time reader looking at the health-status wiki page will (a) not know
which scope the number reflects, and (b) not trust the disagreement.

Observed on 2026-07-20 during the post-cutover full-sweep gap analysis (see
`supported_repos/global-workflow.wiki/Docker-MCP-Gateway-COTS-Gap-Analysis-2026-07-20.md`,
"Informational — Not a Gap" section).

## 2. Scope

### 2.1 In Scope

- Document the three node-count scopes in
  `docs/development/data_access_layer_design.md` (or a new
  `docs/development/graph_node_count_scopes.md`).
- Update each of the three tools' output to name its scope explicitly:
  - `mcp_health_check`: change `108280 nodes` → `108,280 nodes (health-check scope)`
    (or similar) and include a one-line note that the number is a curated
    subset.
  - `get_knowledge_base_status`: change `Total Nodes: 225836` →
    `Total Nodes (tenant scope): 225,836`.
  - Add a fourth tool or flag to expose the raw whole-graph count for
    troubleshooting parity.
- Cross-link between the three tools' output docstrings so a reader always
  finds the "why do these disagree?" answer within one hop.

### 2.2 Out of Scope

- Reconciling or unifying the three counts into a single canonical value.
  The scopes are legitimately different and should stay different.
- The ChromaDB adapter counting gap — that is Phase 70.
- The Fortran coverage-gap path — that is Phase 72.

## 3. Success Criteria

1. A new-to-the-codebase engineer can identify which scope any of the three
   counts belongs to within 60 seconds of reading the health-status wiki page.
2. All three tools include a `(scope: …)` annotation next to the count in
   both text and JSON output.
3. The `docs/development/` docs directory contains a single canonical page
   describing the scope model.

## 4. Open Questions

- Should the `mcp_health_check` count align with `get_knowledge_base_status`
  going forward, or is the curated 108,280 subset intentional (e.g. to remain
  stable through tenant additions)? — need input from the health-check
  implementer.
- Do we expose the whole-graph count as a new tool `graph.stats` or as an
  optional flag on `get_knowledge_base_status`? First cut: flag
  (`--all_tenants`).

## 5. Risks

- Minimal — this phase is primarily documentation and label additions. The
  main risk is downstream dashboards that grep specific text (e.g.
  `108280 nodes`) may break. Mitigation: keep the numeric value stable and
  add the scope annotation as a suffix, not a prefix.

## 6. References

- Gap Analysis wiki: `supported_repos/global-workflow.wiki/Docker-MCP-Gateway-COTS-Gap-Analysis-2026-07-20.md`
- Health history: `mcp_server_python/sdd_framework/execution_state/health_history.jsonl`
- Tools involved: `mcp_health_check`, `get_knowledge_base_status`, `get_health_trend`
