# Phase 78 — MCP Tool Gaps: Config-Flow Liveness and Env-Dependency Coverage

**Version**: 0.1.0
**Created**: 2026-08-11
**Status**: draft (requirements captured from a live analysis session; not scheduled)
**Estimated effort**: TBD (A + D small; B large; C medium)
**Depends on**: Phase 73 (scope documentation, for the diagnostic-message pattern)
**Kiro spec**: _(to be authored — candidates listed per item below)_
**Owner**: TBD

---

## 1. Executive Summary

Captured during the ESMF-alarm / restart-trigger analysis on 2026-08-11
(wiki: [[ESMF-Alarm-Cycling-Explained]]). That session produced two successive
**incorrect** published answers before reaching ground truth. Both errors were
traceable to specific limits in the MCP toolset, not to operator error, which makes
them worth capturing as requirements rather than as anecdote.

The session's own tool tally is in the wiki page. This phase extracts the five items
that imply code changes.

| # | Gap | Severity | Effort | Tool(s) |
|---|-----|----------|--------|---------|
| A | `find_env_dependencies` under-reports real dependencies | **High** | Small | `find_env_dependencies` |
| B | Template-rendered config flow is unmodeled (reachability ≠ liveness) | **High** | Large | graph ingest, `find_env_dependencies`, `trace_data_flow` |
| C | `search_architecture` returns unlabeled community IDs | Medium | Medium | `search_architecture` |
| D | Not-found responses cannot distinguish "absent" from "external" | Low-Med | Small | `get_code_context`, `analyze_code_structure` |
| E | `find_callers_callees` times out on hub symbols when `cross_language=true` | Medium | Small | `find_callers_callees` |

Items A and B are the ones that materially changed the outcome of the session. C, D,
and E cost time but did not produce a wrong answer.

## 2. Gap Detail

### 2.1 Gap A — `find_env_dependencies` returns zero for variables that demonstrably exist

**Observed.** Three calls, all returning `Total dependencies: 0 scripts` and
`Impact level: LOW`:

| Query | Reality on disk |
|-------|-----------------|
| `restart_interval` | read at `ush/forecast_postdet.sh:349`, `:353`, `:362-372` |
| `FHOUT` | used across forecast/post config |
| `restart_interval_gfs` | read at `ush/python/pygfs/utils/archive_tar_vars.py:236,383` |

The graph reports 31,601 `DEPENDS_ON_ENV` edges for tenant `gw`, so the edge type is
populated — these specific variables are missing from it.

**Two suspected causes**, both needing confirmation against the parser:

1. **Parameter-expansion-with-default reads are not extracted.** The canonical
   workflow idiom is
   ```bash
   restart_interval=${restart_interval:-${FHMAX}}     # forecast_postdet.sh:349
   ```
   which both *reads* and *writes* the name. A regex matching `${VAR}` or `$VAR`
   should catch this; a regex anchored on `export VAR=` will not.

2. **Shell `local` assignments are not captured at all.** `parsing_ufs_configure.sh`
   sets its entire configuration surface with `local`:
   ```bash
   local RESTART_N=999999
   local MED_history_n=1000000
   ```
   These never become environment variables — they are consumed by `atparse` in the
   same shell. No `EXPORTS` edge is correct in the strict sense, but the operator
   asking "what sets `RESTART_N`?" gets nothing.

3. **Python config-dict reads produce no edge.** The workflow's configuration flow is
   YAML → dict, not environment:
   ```python
   enkf_vars['restart_interval'] = config_dict.get('restart_interval_enkfgfs', None)
   ```
   Arguably correct — it is not `os.environ` access — but it makes the tool blind to
   the mechanism the workflow actually uses for configuration. This is the class of
   variable an operator most wants to trace.

**Requirement.** `find_env_dependencies` should report a variable as depended-upon when
it is read via any of: `$VAR`, `${VAR}`, `${VAR:-default}`, `${VAR:=default}`,
`${VAR:?msg}`, `${VAR}` inside arithmetic or test contexts. Shell `local VAR=` and
Python config-dict access should surface under a distinguishable edge type (see Gap B)
rather than being silently absent.

**Acceptance.** `find_env_dependencies("restart_interval")` returns a non-empty
dependents list including `ush/forecast_postdet.sh`.

**Candidate spec**: `.kiro/specs/env-dependency-extraction-coverage/`

---

### 2.2 Gap B — Template-rendered configuration is invisible to the graph

**This is the gap that caused a wrong published answer.**

The question was: what triggers ocean/ice/mediator restarts in the workflow? The graph
showed `ESMF_AlarmIsRinging` called in `mom_cap.F90`, `ice_comp_nuopc.F90`,
`wav_comp_nuopc.F90`, and `med_phases_restart_mod.F90`. Every one of those call sites
is real and reachable. The published conclusion — that restarts are alarm-driven — was
still wrong, because `ush/parsing_ufs_configure.sh:64` sets `RESTART_N=999999`, arming
the alarm ~114 years out so it never rings.

The evidence chain crosses three boundaries the graph does not model:

```
local RESTART_N=999999               (1) shell local, not export → no edge
  └─ atparse < template              (2) template substitution → not a modeled relation
       └─ ufs.configure in DATA/      (3) runtime-only artifact → nothing to ingest
            └─ NUOPC_CompAttributeGet(gcomp, name='restart_n', ...)
                                         string-keyed runtime lookup → no static edge
```

No combination of `find_callers_callees`, `find_dependencies`, `find_env_dependencies`,
or `trace_data_flow` can bridge that. Worse, `search_documentation` correctly returned
the *documented* `restart_option`/`restart_n` semantics from the CDEPS docs — which
describe the CESM behavior — and that correct documentation is precisely what made the
wrong answer plausible.

**The general statement: the graph answers reachability, not liveness.** For a system
whose behavior is determined by rendered configuration, code reachability is necessary
but not sufficient. Any tool that presents a reachable call path as an explanation of
runtime behavior can mislead in exactly this way.

**Two candidate mitigations**, in increasing cost:

1. **Model the template pairs.** Ingest `*.IN` / `*.tmpl` templates together with the
   script that renders them, as a `RENDERS` (script → template) and `POPULATES`
   (variable → template placeholder) edge pair. The `atparse` convention makes this
   tractable: placeholders are `@[VAR]` and the renderer is a single well-known
   function. Workflow templates affected include `ufs.configure`, `model_configure`,
   `ww3_shel.nml`, and the `parsing_namelists_*` family.

2. **Add a `SETS_CONFIG` edge for shell locals in config-generation scripts.** Scoped
   narrowly — `ush/parsing_*.sh`, `SETUP*/provisioning/*.sh` — extract `local VAR=value`
   and `VAR=value` assignments as config-setting relationships distinct from
   `EXPORTS`. This alone would have answered "what sets `RESTART_N`?".

**Cheaper interim mitigation (recommended first cut).** Rather than modeling the flow,
make the tools *say* they cannot see it. When a query resolves into a component whose
behavior is attribute- or namelist-driven, append a diagnostic:

> `[NOTE] Behavior here may be gated by rendered configuration not present in the
> graph. Check the generating script (ush/parsing_*.sh) and the rendered artifact in
> the run directory before concluding this path is live.`

That is a docstring-and-diagnostic change, not an ingest change, and it directly
targets the failure mode. It follows the Phase 73 pattern of annotating output with
its own scope.

**Acceptance (interim).** A `find_callers_callees` or `get_code_context` result that
lands in a NUOPC cap carries the liveness caveat. **Acceptance (full)**: a query for
`RESTART_N` returns `ush/parsing_ufs_configure.sh` as the setter and `ufs.configure` as
the rendered consumer.

**Candidate spec**: `.kiro/specs/config-flow-liveness-modeling/`

---

### 2.3 Gap C — `search_architecture` returns unlabeled community IDs

**Observed.** Query `"ESMF time manager alarm clock subsystem forecast model driver"`
returned five results of the form:

```
## 1. Community 3827 (relevance: 0.529)
Community L3_3827: 2 nodes across 1 sub-communities (Mixed).
Sub-communities: Community_L2_1847 (2 nodes)
```

No semantic summary, no nameable subsystem. Relevance scores clustered 0.525–0.529 —
undifferentiated, i.e. the ranking carried no signal. Tenant `gw` has 2,113 documents
in `mdc-community-summaries-titan1024`, so summaries exist; they did not surface here.

**Suspected causes**, needing confirmation:

- The matched communities are 2–5 nodes at levels L2/L3. A 2-node community has no
  meaningful prose description, so either no summary was generated for it or the
  generated summary is vacuous. The gw benchmark ground truth contains recognizable
  names ("GSI EnKF", "atmospheric forecast model"), so *some* communities are well
  summarized — the retrieval picked the wrong ones.
- Possible that the vector match runs against community *metadata* rather than the
  summary text, which would explain both the missing prose and the flat scores.

**Requirement.** `search_architecture` should either return communities that carry a
real summary, or state that the matched communities have no summary and suggest
`search_documentation` instead. A minimum node-count floor for inclusion is the
simplest lever.

**Acceptance.** The same query returns at least one named subsystem with prose, or an
explicit `[INFO]` that no summarized community matched.

**Candidate spec**: `.kiro/specs/search-architecture-summary-quality/`

---

### 2.4 Gap D — Not-found responses conflate "absent" with "external"

**Observed.** `get_code_context("ESMF_Alarm")` returned:

```
Symbol "ESMF_Alarm" not found in graph.
No similar symbols found.
```

Factually correct — `ESMF_Alarm` is an external library type, not a workflow symbol.
But the response is indistinguishable from a typo or an ingest gap, and it gives no
next step. During the session this cost a detour before pivoting to
`find_similar_code`, which succeeded immediately.

**Requirement.** When a symbol is absent from the graph but appears in the vector
corpus (docs or code-context collections), say so and route the caller:

> `[INFO] "ESMF_Alarm" is not a graph symbol in tenant gw. It appears in the
> documentation corpus, which suggests an external library type. Try
> search_documentation or find_similar_code.`

This is a cheap cross-check — the vector store is already reachable from the same tool
context.

**Acceptance.** The `ESMF_Alarm` query returns the external-symbol hint rather than a
bare not-found.

**Candidate spec**: fold into `.kiro/specs/graceful-missing-index-handling/` if that
spec is still open, otherwise a small standalone.

---

### 2.5 Gap E — `find_callers_callees` times out on hub symbols with `cross_language=true`

**Observed.** `find_callers_callees("ESMF_AlarmIsRinging", cross_language=true)` →
`query exceeded 30.0s statement timeout`.

Expected for a symbol called from a dozen component caps — this is the Gap G fan-out
case. Phase G (`bounded-graph-traversal`) landed a pre-flight degree probe plus a 30 s
statement-timeout backstop. Here the backstop fired but the probe apparently did not
short-circuit, so the caller waited the full 30 s and got nothing usable.

**Requirement.** Confirm whether the `cross_language=true` path bypasses the degree
probe added in Gap G. If so, apply the probe before the cross-language expansion and
return a `Degraded_Result` (one-hop summary) rather than timing out.

**Acceptance.** The same call returns a bounded one-hop result with a degradation
notice, in under 5 s.

**Candidate spec**: extension to the existing `bounded-graph-traversal` spec.

## 3. Scope

### 3.1 In Scope

- Shell/Python env-read extraction coverage (Gap A).
- Liveness caveat diagnostics on config-gated results (Gap B, interim).
- Community-summary quality floor in `search_architecture` (Gap C).
- External-symbol routing hint on not-found (Gap D).
- Degree-probe coverage for the `cross_language` path (Gap E).

### 3.2 Out of Scope

- Full template/config-flow graph modeling (Gap B, full). Large enough to be its own
  phase; captured here as a requirement, not scheduled.
- Re-ingest of any collection. All five items are query-side or extractor-side; only
  Gap A and Gap B-full would require re-ingest, and neither is scheduled here.
- The community-summaries pipeline port (Gap J in the multi-tenant tracker) — related
  to Gap C but a separate, larger effort.
- Rewriting `sdd_framework/CURRENT_ROADMAP.md`, which is stale (reports 51 tools and
  pre-Titan node counts against a live 53 tools). Noted for a separate cleanup.

## 4. Success Criteria

1. `find_env_dependencies` resolves the three variables that returned zero during the
   session (`restart_interval`, `FHOUT`, `restart_interval_gfs`).
2. A result that lands in configuration-gated code carries an explicit liveness caveat,
   so a future analysis cannot repeat the Rev 2 error by reading reachability as
   behavior.
3. `search_architecture` never returns a bare unlabeled community ID with no summary
   and no explanation.
4. A not-found symbol lookup that has vector-corpus presence routes the caller instead
   of dead-ending.
5. No graph traversal returns a bare timeout where a bounded degraded result is
   possible.

## 5. Open Questions

- Is the `${VAR:-default}` miss in Gap A a regex limitation or a deliberate exclusion?
  Needs a look at the shell extractor before scoping.
- For Gap B, is the `atparse` template surface stable enough across the workflow to
  make `RENDERS` edges worth ingesting, or is the interim diagnostic sufficient
  indefinitely? Recommend shipping the diagnostic first and revisiting with usage data.
- For Gap C, do vacuous summaries exist in the index for small communities, or were no
  summaries generated for them? Determines whether the fix is a retrieval filter or a
  generation-side floor.
- Should the liveness caveat be tool-wide or scoped to files matching known
  cap/component patterns? Tool-wide risks caveat fatigue.

## 6. Risks

- **Gap A over-extraction.** Loosening the read regex may create edges for variables
  mentioned in comments or heredocs, inflating `DEPENDS_ON_ENV` and degrading the
  `Impact level` heuristic. Mitigation: exclude comment lines and validate the total
  edge-count delta before accepting.
- **Gap B caveat fatigue.** A liveness note appended too broadly will be ignored,
  reproducing the original failure with extra text. Mitigation: scope to component
  caps and attribute-driven code, and keep it one line.
- **Gap C floor set too high.** Filtering small communities could hide legitimately
  small-but-meaningful subsystems. Mitigation: return them with an explicit
  "no summary available" rather than dropping them.

## 7. Provenance

Every item above was observed in a single session on 2026-08-11 analyzing ESMF alarm
usage and restart triggering in the UFS. The session is documented in the wiki page
[[ESMF-Alarm-Cycling-Explained]], which includes the full MCP tool tally and a
"Why the MCP tools could not have caught the Rev 2 error" section.

Sequence worth preserving, because it is the argument for Gap B:

1. Rev 1 quoted `ESMF_AlarmMod.F90` as authoritative. It is a vendored WRF-lineage
   shim under `MPAS-Model/src/external/esmf_time_f90/` with zero importers on the FV3
   path. `find_dependencies` had the signal ("No importers found") and it was not
   weighed.
2. Rev 2 corrected that, then asserted MOM6/CICE/WW3/CMEPS restarts are alarm-driven
   because the caps call `ESMF_AlarmIsRinging`. True and reachable, still wrong —
   `RESTART_N=999999` makes the path dead.
3. Rev 3 reached ground truth only via terminal `grep` on
   `ush/parsing_ufs_configure.sh`.

Two wrong answers, both from treating graph reachability as evidence of runtime
behavior. That is the requirement Gap B exists to address.

## 8. References

- Wiki analysis: `supported_repos/MDC-MCP-GraphRAG.wiki/ESMF-Alarm-Cycling-Explained.md`
- Steering (tool catalog): `.kiro/steering/10-agentcore-mcp-tool-guide.md`
- Steering (multi-tenant gaps, incl. Gap G bounded traversal, Gap J communities):
  `.kiro/steering/12-multi-tenant-gap-tracker.md`
- Prior scope-annotation precedent: `sdd_framework/workflows/phase73_graph_node_count_scope_documentation.md`
- Evidence files (tenant `gw`, branch `develop`):
  - `ush/parsing_ufs_configure.sh:45,64,71` — the disabling assignments
  - `ush/forecast_postdet.sh:349` — the `${VAR:-default}` read Gap A misses
  - `ush/python/pygfs/utils/archive_tar_vars.py:236` — the config-dict read Gap A misses
  - `sorc/ufs_model.fd/CDEPS-interface/ufs/cdeps_share/shr_is_restart_fh_mod.F90` — the actual trigger
