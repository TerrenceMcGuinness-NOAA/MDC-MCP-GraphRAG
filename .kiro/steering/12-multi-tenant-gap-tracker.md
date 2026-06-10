# Multi-Tenant Gap Tracker

Living document tracking the remaining gaps between the `gw` (develop) baseline
and non-default tenants (primarily `gw_v17`). Updated as gaps are resolved.

Last updated: 2026-06-10

## Summary Table

| # | Gap | Priority | Tenant(s) | Status | Spec / Fix | Notes |
|---|-----|----------|-----------|--------|------------|-------|
| A | `tenant_id` not exposed on tool schemas | HIGH | all | RESOLVED | `tenant-id-tool-exposure` [8.28.0] | Deployed v22, 2026-06-03 |
| B | Shell graph relationships incomplete for non-gw | MEDIUM | gw_v17 | PARTIAL | `graph-port-shell-ops` (req+design done) | v17 DOES have shell rels (SOURCES 928, INVOKES 1.7K, EXPORTS 6K, DEPENDS_ON_ENV 20K, DEFINES 337, EXECUTES 11) — but counts are lower than gw; a full shell ingest run may add more. Fortran rels are complete (CALLS 738K, USES 167K). Re-assessed after Gap D fix. |
| C | Graph queries used hardcoded labels / no tenant= | HIGH | all non-gw | RESOLVED | [8.30.0] commit `9c66084` | Deployed v29, 2026-06-08. |
| D | Rewriter mangled relationship types for non-gw | HIGH | all non-gw | RESOLVED | [8.31.0] commit `a8f76ec` | `_rewrite_cypher` prefixed `:CALLS` → `:GW_V17_CALLS`. Now bracket-aware. Was the real root cause behind much of what looked like "Gap B empty results". Deployed v30, 2026-06-08. Verified: v17 shows 934,873 rels; find_callers_callees works. |
| E | Label-less graph queries leak across tenants | LOW | all non-gw | RESOLVED | [8.32.0] commit `9d64b53` | `tenant_label_predicate()` scopes label-less / name-anchored queries via `labels(n)` (tenant_id property is unreliable — null on placeholder nodes). Applied to ~16 queries in graph_rag.py + code_analysis.py. Deployed v31, 2026-06-08. Verified: setuprad resolves to GW_V17_File for v17, FortranSubroutine for gw. |
| F | Fortran parse failures (15% / 1,020 files) | MEDIUM | gw_v17 | RESOLVED | `fortran-parse-fallback` [8.33.0] `7c77ffd` + parallel/streaming [8.34.0] `1520577` | Regex fallback + parallel streaming ingest. Live ingest run 2026-06-10: 6,926/6,935 parsed (99.9%), 45,155 nodes + 297,712 rels written, 0 errors, ~3.2h. v17 graph now 80,996 nodes / 1,278,330 rels (CALLS 1.02M, USES 229K). No deploy — offline script. |
| G | Deep traversal OOMs on Neptune | MEDIUM | gw (JGLOBAL_FORECAST) | OPEN | — | Highly-connected nodes (JGLOBAL_FORECAST, 500+ edges) cause timeout/OOM on multi-hop traversal. Needs depth-limit + fan-out cap in traversal tools. |
| H | No tenant-specific docs collection | BY DESIGN | non-gw | N/A | — | All tenants share the documentation vector indices. Code embeddings are tenant-prefixed. Docs are branch-agnostic (RTD, EE2 standards, etc.). |

## Detail: Open Gaps

### Gap B — Shell graph relationships for v17

**What's missing:** The shell graph ingester (`ingest_shell_graph_v8.py`) creates
SOURCES, INVOKES, EXECUTES, DEFINES, IMPORTS, EXPORTS, and DEPENDS_ON_ENV edges
by parsing shell scripts. This has run for `gw` (the develop baseline) but NOT
for `gw_v17`.

**Impact:** `find_dependencies`, `find_callers_callees`, `trace_execution_path`,
`trace_full_execution_chain` all return empty for shell-script relationships in
v17. Fortran CALLS/USES/CONTAINS edges DO exist (230K from the 37-hour Fortran
ingestion run) — but the shell→Fortran bridge (EXECUTES) only has 15 edges
(from a quick bridge run).

**Fix:** Run `ingest_shell_graph_v8.py --tenant gw_v17 --mode full`. The spec
`graph-port-shell-ops` has requirements and design complete; tasks are pending.

**ETA:** ~4-8 hours runtime (1,401 shell scripts to parse).

---

### Gap D — Rewriter mangled relationship types (RESOLVED 2026-06-08)

**Symptom:** `get_knowledge_base_status(tenant_id="gw_v17")` reported
`Total Relationships: 0` even though Neptune has 738K+ CALLS edges for
`GW_V17_FortranSubroutine` nodes.

**Actual root cause:** The `_rewrite_cypher` label rewriter in `neptune_adapter.py`
used a regex (`:([A-Za-z_]...)`) that matched ALL colon-tokens — including
relationship types inside `[...]`. So `MATCH (s:File)-[r:CALLS]->()` was rewritten
to `MATCH (s:GW_V17_File)-[r:GW_V17_CALLS]->()`. Neptune only prefixes node labels,
not relationship types, so `:GW_V17_CALLS` matched nothing → count 0.

**Confirmed via debug harness:** running `_safe_relationship_counts` against live
Neptune returned `[]` in 0.5s (not a timeout — a logic bug). The Neptune MCP server
confirmed the *correct* (unmangled) queries return 738K in ~1.2s.

**Fix:** Made `_label_token_offsets` bracket-aware via a new `_square_bracket_mask`
helper. Tokens inside `[...]` (relationship types) are skipped; only node labels
get prefixed. [8.31.0].

**Broader impact:** This bug silently broke ALL relationship-traversal queries for
non-gw tenants (`find_related_files`, `find_callers_callees`, `trace_execution_path`,
etc.), not just the count display. Much of what was attributed to "Gap B — missing
relationships" was actually this rewriter bug masking relationships that DO exist.

---

### Gap E — Label-less queries (RESOLVED in code 2026-06-08)

**Symptom:** Label-less queries (`MATCH (n) WHERE n.name = $name`) and
name-anchored relationship queries matched nodes from ANY tenant — the
label-prefix rewriter only acts on `:Label` tokens, of which these have none.
A `gw_v17` lookup could surface `gw` baseline nodes and vice versa.

**Why not tenant_id property:** The obvious fix (filter `n.tenant_id = $tid`)
is unreliable. Confirmed in Neptune: 4,168 of 29,605 `GW_V17_FortranSubroutine`
nodes have `tenant_id = null` (placeholder nodes the Fortran ingester's CALLS
MERGE creates without the property), and several label types
(`GW_V17_EnvironmentVariable`, `GW_V17_ShellFunction`, `GW_V17_DataDependency`)
carry no `tenant_id` at all. All gw baseline nodes also have null. The **label**
is the only reliable discriminator.

**Fix:** `tenant_label_predicate(var)` in `resolver.py` builds a `labels(n)`-based
WHERE fragment using Neptune's list-comprehension `size([l IN labels(n) WHERE
l STARTS WITH '<prefix>'])`:
- Non-default tenant: `... > 0` (node owns a label with the tenant's prefix).
- Default gw: `... = 0` over all OTHER tenant prefixes (node is base/unprefixed).

Applied via a `_scope_and(var)` helper to ~16 leaky queries across
`graph_rag.py` and `code_analysis.py`. For name-anchored relationship queries,
only the named anchor needs scoping (edges are within-tenant). [8.32.0].

**Verified live:** the `setuprad` lookup that returned 5 nodes across both tenants
now returns 2 (v17) or 3 (gw) correctly.

---

### Gap F — Fortran parse fallback

**Problem:** fparser2 fails on 15% of Fortran files (1,020 of 6,935 in v17).
Common failure modes: deeply nested preprocessor logic, non-standard extensions,
OpenMP directives, C interop patterns.

**Impact:** ~50K potential CALL/USE relationships unextracted from those files.

**Proposed fix:** Regex-based fallback that scans for `CALL subroutine_name` and
`USE module_name` patterns when fparser2 returns None. Won't get line numbers or
containment, but captures the relationship edges.

**Spec status:** Directory exists at `.kiro/specs/fortran-parse-fallback/` but
requirements.md not yet written.

---

### Gap G — Deep traversal OOM / timeout

**Problem:** `trace_execution_path` and `trace_full_execution_chain` with
highly-connected nodes (JGLOBAL_FORECAST has 500+ direct edges) can cause Neptune
to timeout or return massive result sets that blow the MCP response size.

**Fix:** Add configurable `max_fan_out` (default 50) and `max_depth` cap (default 3)
in the traversal queries. Drop to summary mode when a node exceeds the fan-out
threshold.

---

## Resolved Gaps (for reference)

### Gap A — tenant_id tool exposure (RESOLVED 2026-06-03)

24 tenant-scoped tools now expose `tenant_id: str | None = None` in their FastMCP
schema. Commit `ca44057`, version [8.28.0], deployed as v22.

### Gap C — Label-prefix scoping in graph queries (RESOLVED 2026-06-08)

Graph tools (get_knowledge_base_status, list_job_scripts, get_job_details,
explain_workflow_component) were returning gw baseline data regardless of tenant.
Fixed by adding `tenant=` passing and restructuring label-less queries to use
proper MATCH labels. Commit `9c66084`, version [8.30.0], deployed as v29.
