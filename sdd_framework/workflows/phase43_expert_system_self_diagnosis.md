# Phase 43: Expert System Self-Diagnosis & Health Observability

**Version**: 1.0.0
**Status**: Planned
**Created**: 2026-03-06
**Author**: AI Assistant + Terry McGuinness
**Dependency**: None (standalone — can proceed in parallel with Phases 38-42)
**Archaeology**: Legacy capabilities from `bootstrap_capability_demo`, `test_health_check_workflow`, Phase 4B (ISD approval gates), Phase 4C (code snippet extractor), Phase 19 (content abstraction), Phase 22 (validation benchmarking)

---

## 1. Executive Summary

The MCP-RAG server currently has **diagnostic tools** (`mcp_health_check`, `analyze_ee2_compliance`, `scan_repository_compliance`) but lacks **observability** — the ability to track its own health over time, detect degradation, and suggest remediation. An expert system that cannot monitor its own knowledge quality is not yet a true expert system.

This phase transforms the server from "diagnose on demand" to "continuously self-aware" by adding:

1. **Health trending** — persist health check results to track degradation over time
2. **Knowledge base integrity monitoring** — detect stale/missing/orphaned data proactively
3. **Auto-remediation suggestions** — compliance and analysis tools emit fix suggestions, not just findings
4. **Session introspection audit** — SDD session history analytics for process improvement

### Motivation

The legacy workflow archaeology (March 6, 2026) revealed 8 self-help capabilities were designed across early phases (4B, 4C, 8, 9, 19, 22) but only **one shipped fully** (Phase 4C LLM passthrough). The remaining 7 capabilities represent the gap between "tool server" and "expert system." This phase addresses the most actionable subset.

### What This Phase Does NOT Cover

- RAG quality metrics benchmark harness (→ Phase 44)
- CI/CD pipeline integration (→ Phase 44, notional)
- Autonomous code generation iteration loops (→ future, requires Phase 44 evaluation framework)
- Per-user session isolation (→ Phase 33)

---

## 2. Current State vs Target State

| Capability | Current | Target |
|-----------|---------|--------|
| Health check | On-demand, ephemeral | Persistent, trending, alerting |
| Knowledge base monitoring | Manual `get_knowledge_base_status` | Proactive integrity checks with drift detection |
| Compliance findings | Flag-only ("ERROR: missing set -eu") | Flag + suggested fix + confidence score |
| Session analytics | Raw JSONL append log | Queryable history with process metrics |
| Stale data detection | None | Automatic detection of orphaned nodes, broken paths, stale embeddings |

---

## 3. Technical Specification

### 3.1 Health Trending Store

**Implementation**: Append health snapshots to `sdd_framework/execution_state/health_history.jsonl`

Each snapshot captures:
```json
{
  "timestamp": "2026-03-06T20:00:00Z",
  "source": "scheduled|manual|tool_call",
  "neo4j": { "status": "ok", "nodes": 13537, "relationships": 45221, "latency_ms": 42 },
  "chromadb": { "status": "ok", "collections": 4, "total_docs": 58761, "latency_ms": 120 },
  "drift": {
    "neo4j_node_delta": 0,
    "chromadb_doc_delta": -15,
    "new_stale_files": 0
  }
}
```

**Actionable step**: Extend `mcp_health_check` handler in `src/tools/UtilityTools.js` to:
1. Append snapshot to `health_history.jsonl` on every `deep: true` call
2. Compare current counts against last snapshot to compute `drift`
3. Emit `[WARN] ChromaDB document count decreased by 15 since last check` if drift is negative

**New tool**: `get_health_trend` — reads last N snapshots and reports:
- Count trends (up/down/stable)
- Latency trends (improving/degrading)
- Anomalies (>10% change between consecutive checks)

### 3.2 Knowledge Base Integrity Monitor

**Implementation**: New tool `check_knowledge_integrity` in `src/tools/SemanticSearchTools.js`

Checks:
1. **Path consistency** — query ChromaDB for documents whose `file_path` metadata starts with `global-workflow/` and count them (should be 0 after Phase 38)
2. **Orphaned graph nodes** — Cypher query for `File` nodes whose `absolutePath` does not match any ChromaDB document
3. **Stale embeddings** — compare `lastModified` metadata in ChromaDB against `git log --format=%H -1 -- <path>` for a sample of documents
4. **Missing coverage** — compare `find supported_repos/global-workflow -name '*.f90' | wc -l` against Neo4j `FortranSub` + `FortranModule` count

Returns structured report:
```
Knowledge Base Integrity Report
================================
Path Consistency:  [OK] 0/58761 docs have checkout-specific prefix
Orphaned Nodes:    [WARN] 12 File nodes with no ChromaDB match
Stale Embeddings:  [OK] 50/50 sampled docs match current git HEAD
Coverage Gap:      [WARN] 3503 Fortran files on disk, 847 in graph (24.2%)
```

**Actionable step**: Wire this as a tool that can be called manually or referenced by `mcp_health_check` when `functional: true` is passed.

### 3.3 Auto-Remediation Suggestions

**Implementation**: Extend `analyze_ee2_compliance` response format in `src/tools/EE2ComplianceTools.js`

Current output:
```
[ERROR] Missing error handling: no set -eu or err_chk
```

Enhanced output:
```
[ERROR] Missing error handling: no set -eu or err_chk
  → Suggested fix: Add 'source "${USHgfs}/preamble.sh"' after shebang (provides err_chk, err_exit)
  → Confidence: HIGH (pattern matches 94% of compliant scripts in graph)
  → Reference: EE2 Standard §4.2.1, see search_ee2_standards({ query: "error handling" })
```

**Actionable step**: Build a mapping table (`phase2_anti_patterns.json` already has 18 anti-patterns) that maps each anti-pattern to:
- A suggested fix template
- Confidence level (HIGH/MEDIUM/LOW based on how many compliant scripts follow the pattern)
- A reference to the relevant EE2 standard section

### 3.4 Session History Analytics

**Implementation**: Enhance `get_sdd_execution_history` in `src/tools/SDDWorkflowTools.js`

New optional parameter: `analytics: true`

When enabled, computes from `history.jsonl`:
- **Phases by status**: completed / abandoned / in-progress counts
- **Step tag distribution**: how many research / design / implement / validate / document / ingest steps across all sessions
- **Average session duration**: time from start to complete
- **Velocity trend**: steps per session over last 10 sessions
- **Most common blockers**: parsed from blocker notes

This gives the framework self-awareness about _how it's being used_ — which step types dominate, where sessions stall, what velocity looks like.

---

## 4. Implementation Steps

### ACTIONABLE (can be built now)

| Step | Name | Tag | Description |
|------|------|-----|-------------|
| 1 | Health snapshot persistence | implement | Extend `mcp_health_check` to append snapshots to `health_history.jsonl` on `deep: true` calls |
| 2 | Health drift detection | implement | Compare current snapshot to previous; emit `[WARN]` on >10% changes |
| 3 | `get_health_trend` tool | implement | New tool: read last N snapshots, report trends and anomalies |
| 4 | Knowledge integrity checker | implement | New tool `check_knowledge_integrity`: path consistency, orphaned nodes, stale embeddings, coverage gap |
| 5 | Wire integrity into health check | implement | `mcp_health_check({ functional: true })` calls integrity checker |
| 6 | Auto-remediation mapping table | implement | Extend `phase2_anti_patterns.json` with fix templates, confidence, references |
| 7 | Remediation suggestions in compliance output | implement | Extend `analyze_ee2_compliance` response with suggested fix, confidence, reference |
| 8 | Session analytics parameter | implement | Add `analytics: true` to `get_sdd_execution_history` with process metrics |
| 9 | Validate all new tools | validate | Test health trending, integrity check, remediation suggestions end-to-end |
| 10 | Update tool instruction files | document | Add new tools to `eib-mcp-tools.instructions.md` and `mcp.instructions.md` |

### NOTIONAL (requires design decisions or infrastructure)

| Item | Description | Prerequisite | Notes |
|------|-------------|-------------|-------|
| A | Scheduled health snapshots (cron/systemd timer) | Step 1 above | Run `mcp_health_check({ deep: true })` every 6 hours via cron |
| B | Health alerting (email/Slack on anomaly) | Item A | Emit alert when drift exceeds threshold |
| C | Automated stale embedding refresh | Phase 38 complete | Re-embed documents where git hash mismatches |
| D | Self-triggered re-ingestion on coverage gap | Phase 39 complete | If coverage % drops, queue missing files for ingestion |
| E | Approval gate re-enablement (ISD mode) | Phase 33 (per-user sessions) | Restore Phase 4B approval infrastructure for supervised execution |

---

## 5. Success Criteria

| Metric | Target |
|--------|--------|
| Health snapshots persisted | `health_history.jsonl` grows on each `deep: true` call |
| Drift detection works | `[WARN]` emitted when node/doc counts change >10% |
| Integrity check catches known issues | Detects Phase 38's path prefix problem if run before fix |
| Remediation suggestions present | ≥80% of anti-pattern findings include a suggested fix |
| Session analytics computes | Phase/tag/velocity metrics returned on `analytics: true` |

---

## 6. Architecture Notes

### Tool Count Impact

| Change | Tools |
|--------|-------|
| New: `get_health_trend` | +1 |
| New: `check_knowledge_integrity` | +1 |
| Enhanced: `mcp_health_check` | (existing, extended) |
| Enhanced: `analyze_ee2_compliance` | (existing, extended) |
| Enhanced: `get_sdd_execution_history` | (existing, extended) |
| **Net new tools** | **+2 (48 → 50)** |

### File Changes

| File | Changes |
|------|---------|
| `src/tools/UtilityTools.js` | Health snapshot persistence, drift detection, `get_health_trend` tool |
| `src/tools/SemanticSearchTools.js` | `check_knowledge_integrity` tool |
| `src/tools/EE2ComplianceTools.js` | Remediation suggestions in compliance output |
| `src/tools/SDDWorkflowTools.js` | `analytics` parameter for `get_sdd_execution_history` |
| `phase2_anti_patterns.json` | Add fix templates, confidence, references to each pattern |
| `sdd_framework/execution_state/health_history.jsonl` | New file, append-only health snapshots |

### Relationship to Legacy Specs

This phase consolidates unrealized capabilities from:
- `bootstrap_capability_demo.md` → self-assessment concept (Step 3 health trend)
- `test_health_check_workflow.md` → health check persistence (Steps 1-2)
- Phase 22 → metrics/regression concept (deferred to Phase 44)
- Phase 4B → approval gates (deferred, notional Item E)
- Phase 4C → remediation pattern (Steps 6-7 extend the LLM passthrough with fix suggestions)
- Phase 9 → metrics framework concept (deferred to Phase 44)

---

## 7. Implementation Order Context

This phase can proceed **in parallel** with the ingestion pipeline (Phases 38-42):

```
Phase 38 (data quality) ─────→ Phase 39 (UFS Fortran) ─→ Phase 40-42
        │                              │
        └── Phase 43 (self-diagnosis)──┘── Phase 44 (quality framework)
              can start immediately         needs data from 38-39
```

Recommended execution order within this phase: Steps 1-3 (health trending), then 4-5 (integrity), then 6-7 (remediation), then 8-9 (analytics + validation), then 10 (docs).
