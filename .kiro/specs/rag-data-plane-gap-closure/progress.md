# Progress — RAG Data-Plane Gap Closure (Phase 68)

Working memory for the kiro-cli engagement on the **COTS host**. The agent reads
this at kickoff and updates it after every task. Durable file, not chat memory, is
the source of truth on resume.

**Spec:** `.kiro/specs/rag-data-plane-gap-closure/`
**Execution:** kiro-cli on COTS, inline on the head node (no Slurm — bounded local
code work). SDD-tracked, resumable. No auto-commit / no auto-push.
**Status:** NOT STARTED — kickoff pending (Task 0).

---

## Corrections (PoC learnings — pre-seeded; ❌ mistake → ✅ rule)

| # | ❌ Mistake / trap | ✅ Correction for this engagement |
|---|---|---|
| C1 | Trusting a green `mcp_health_check` / `get_knowledge_base_status` that actually queried **AWS** (`agentcore-mcp-rag` / `eib-mcp-rag-full`). | **Verify COTS-truthfully**: run the probes via a `DB_BACKEND=cots` stdio server (`run_mcp_stdio.sh`) or an in-process harness. AWS results prove nothing about COTS (R13). |
| C2 | Relying on the remote `eib-mcp-gateway` (Docker MCP Gateway dev tunnel). | It is **blocked** (dev-tunnel URL keeps rotating: `blp11zs1`→`wj9z45s5`→`qp20b20k`). Do not depend on it; work against local stores. |
| C3 | Assuming docs are tenant-scoped and prefixing them. | Docs/EE2/community summaries are **shared** (unprefixed, one embedding space, one ingest). Only code/jjobs/config-derived graph are **tenant** (prefixed). This is the whole point of the `scope` field. |
| C4 | Editing a hand-written `unified_ingest_manifest.yaml`. | The manifest SPOT is `generate_unified_manifest.py::KNOWN_SOURCES` → regenerate `src/config/unified_manifest.json`. Model is `src/manifest/models.py`. |
| C5 | The `mpnet768` "sentence-transformers is not installed" warning read as fatal. | It is a **false warning** — the provider imports and embeds (768-dim). Do not chase it (framework Concern 6). |
| C6 | Live ChromaDB doc collections found unprefixed and treated as "wrong". | They are **already** unprefixed — the fix aligns the ingester name with reality, not the other way around. |
| C7 | Changing default (serving) collection names while adding versioning. | Default serving names must stay **byte-for-byte** unchanged: the version suffix is empty for the default version (R9). |
| C8 | Naming collections `mdc-{domain}-titan1024` on COTS (hardcoded profile). | On COTS the profile is `mpnet768`; the namer is **profile-derived** (`mdc-{domain}-{profile}{-ver}`). This also resolves the framework's titan1024→mpnet768 reconcile. |
| C9 | Committing/pushing when done. | Stage only; commits/pushes are human-gated (`08-git-operation-policy.md`). |
| C10 | Treating EXPDIR like static repo config, or resolving one fixed EXPDIR path for all tenants. | EXPDIR is **realtime** experiment data (resolved `config.*` + Rocoto XML from `setup_expt`), **tenant-localized to gw + gw_v17**. `resolve_expdir_base` must be **tenant-derived** (per-tenant base — confirm the mapping on COTS), `skip` (not fail) when absent, and **never** fall back to another tenant's tree. The manifest `expdir-configs` base is the runtime `supported_repos/EXPDIR` tree, NOT `parm/config`. Write-side isolation stays the `{prefix}Experiment`/`{prefix}EXPDIRConfig` label. (R15) |
| C11 | Assuming `generate_unified_manifest.py` regeneration is lossless and re-running it to add `scope`. | The generator seeds url_crawl sources from `documentation_sources.json` (**42** entries), but the committed manifest carries **58** url_crawl (16 augmented beyond the seed: mpas-atmosphere, hafs, jedi-academy, uwtools, cdeps, land-da, gsi-user-guide, ecmwf-atlas, ufs-srweather-app, catchem, cece, esm*-pdf, nuopc). Regenerating **drops those 16**. For Task 1.5, `scope` was **backfilled in place** on the existing 67-source manifest (all preserved). The generator code (`_default_scope` + constructor wiring) is correct for future lossless regen once its seed is reconciled — reconciling the seed is out of this phase's scope (a url-crawl-gap / Phase 58 concern). |

---

## Codebase Patterns (authoritative for this phase)

- **Single naming authority** — `resolve_collection_name(source, tenant, version)`
  (Task 3): shared → `mdc-{domain}-{profile}{suffix}`; tenant →
  `{tenant.index_prefix}mdc-{domain}-{profile}{suffix}`; `suffix=""` for the
  default version. All ingesters, `write_vector_doc`, and `reset_tenant_cots.py`
  route through it. **This is the hand-off to framework Task 2.3.**
- **Scope drives the matrix** — `reingest_state.py init`: `shared` stage → 1 unit
  (`__global__`); `tenant` stage → N units. `documentation` becomes shared →
  62→58 units for the current 5-tenant catalog.
- **Idempotent `init`** — preserves terminal (`done`/`skipped`/`blocked`)
  statuses; only regenerates non-terminal units. The 5 per-tenant `documentation`
  units collapse to 1 shared unit; the PoC's 2,518-doc partial is a valid
  checkpoint (it landed in the shared `mdc-workflow-docs-*` collection).
- **Tenant-resolved paths** — tools resolve `ctx.tenant.workflow_root` (default →
  `.pw_workflow_mount/develop`); never hard-code `supported_repos/global-workflow*`.
- **Graceful adapter** — `chromadb_adapter.sample_metadata(collection, n)` returns
  `[]` on empty/missing (never raises), so integrity checks degrade, not crash.
- **EXPDIR is realtime + tenant-derived** — its source base is per-tenant (not a
  fixed path); write-side isolation stays the graph label prefix; absent EXPDIR →
  `skip`, never fall back to another tenant. The manifest source base is the
  runtime EXPDIR tree, not the repo `parm/config`. Confirm the per-tenant base
  mapping on COTS before wiring (gw / gw_v17 today).

## EXPDIR base mapping (confirmed from COTS 2026-07-10 — R15.3)

| Tenant | EXPDIR base (path) | Materialized? |
|---|---|---|
| gw | `supported_repos/EXPDIR` | YES — 17 experiment dirs (e.g. C48_ATM, C96_atm3DVar); sample dir has 54 config.* + 1 .xml |
| gw_v17 | `supported_repos/EXPDIR_v17` | YES — 9 experiment dirs (e.g. C48mx500_hybAOWCDA); sample dir has 106 config.* + 1 .xml |
| gw_sfs / gw_jedi_gfs / gw_gefs_v12 | (none present) | NO → `skip` (never fall back to gw/gw_v17 tree) |

Derivation rule (Task 9.2): base = `supported_repos/EXPDIR` for the default `gw`
tenant, `supported_repos/EXPDIR{_<upper-suffix>}` for others — concretely
`EXPDIR_v17` for `gw_v17`. `MCP_EXPDIR_BASE_OVERRIDE` remains the explicit
per-run override. Absent base → return None (skip), never another tenant's tree.

---

## COTS environment facts (verified 2026-07-09)

- ChromaDB `:8080` — ~15 live serving collections (doc collections **unprefixed**).
- Neo4j `:7687` — ≈343,363 nodes / ≈4,220,211 rels; **GDS 2.13.7 present**.
- `mpnet768` (all-mpnet-base-v2, 768-dim) functional.
- `DB_BACKEND=cots` env via `run_mcp_stdio.sh`; worktrees under `.pw_workflow_mount`.

## Baseline COTS counts (Task 0.4 — before any change; via COTS stdio server)

**Verification method (R13.3):** COTS-local **stdio MCP server** launched via
`mcp_server_python/scripts/run_mcp_stdio.sh` (`DB_BACKEND=cots`, `mpnet768`,
ChromaDB `localhost:8080`, Neo4j `bolt://localhost:7687`), driven over
newline-delimited JSON-RPC by `/tmp/cots_probe.py` (initialize →
notifications/initialized → tools/call). This exercises the real server + tool
code path end-to-end against the live COTS stores. **NOT** the AWS
`agentcore-mcp-rag` and **NOT** the blocked `eib-mcp-gateway`. Smoke-tested with
`get_server_info` → `mdc-mcp-rag` v1.0.0, 53 tools, 5 tenants (default `gw`).

| Probe | Baseline | Method (C1) |
|---|---|---|
| `get_knowledge_base_status` Total Documents | **0** → `[ERROR] Unhealthy` (vector); graph `[OK]` 225,836 nodes / 4,051,374 rels (gw-scoped) | COTS stdio |
| `check_knowledge_integrity` checks run / skipped | 4 checks: 1 run (Orphaned Graph Nodes `[OK]`), **3 SKIP** — Path Consistency + Stale Embeddings ("no metadata sampler"), Coverage Gap ("no Fortran files found in `supported_repos/global-workflow`" — stale hard-coded path) | COTS stdio |
| `mcp_health_check --functional --detailed` pass/skip | **11/11 pass**, 0 skip; `workflow_info` already `[OK] pass`; all 5 tenant roots reachable under `.pw_workflow_mount/*`; default gw → `.pw_workflow_mount/develop` | COTS stdio |

**Root causes identified from baseline:**
- **Gap 6:** ChromaDB `health_check(deep=True)` returns `collections_detail`
  (dict, 17 collections, `total_documents=223148`) but
  `_filter_indices_by_tenant` only recognizes `indices_detail`/`indices` →
  falls to the flat-names branch and **zeroes** the total whenever any
  collection is filtered out (the 2 `gw_v17_*` collections are excluded for the
  default gw scope, so `len(names)=15 != len(raw)=17` → total forced to 0).
- **Gap 4.2:** `_resolve_repo_base` defaults to a hard-coded
  `supported_repos/global-workflow` (resolved once at register time, not
  tenant-aware). `.pw_workflow_mount/develop` has **7,336 Fortran files**, so a
  tenant-resolved base makes the coverage-gap check execute.
- **Gap 5:** `ChromaDBAdapter` has no `sample_metadata`, so `_build_vector_sampler`
  returns None → Path Consistency + Stale Embeddings SKIP.
- **Gap 4.1 (workflow_info):** already tenant-resolved via
  `_resolve_workflow_root_with_tenant()` → functional probe already passes;
  verify/align only.

Manifest baseline: `unified_manifest.json` v9.0.0, **67 sources** (58 url_crawl,
1 on_disk_submodule, 3 code_parse, 2 config_parse, 1 standards, 1
community_summary, 1 jjob_docs). Scope split (R1.4): **61 shared** (url_crawl +
on_disk_submodule + standards + community_summary), **6 tenant** (code_parse +
config_parse + jjob_docs).

Live COTS serving doc collections are the profile-derived **`mdc-{domain}-mpnet768`**
set (unprefixed = shared), confirming C6/C8.

---

## Progress log

| Date | Task | Result | Notes / Correction added |
|---|---|---|---|
| 2026-07-10 | 0.1 | DONE | COTS runtime confirmed: kiro-cli present, python 3.11.14 (spack), ChromaDB :8080 (v2 API), Neo4j :7687 open, GDS n/a-here. |
| 2026-07-10 | 0.2 | DONE | COTS-truthful stdio path stood up (`/tmp/cots_probe.py` → `run_mcp_stdio.sh`, DB_BACKEND=cots). Smoke: `get_server_info` = mdc-mcp-rag v1.0.0, 53 tools, 5 tenants. NOT AWS, NOT gateway. |
| 2026-07-10 | 0.3 | DONE | SDD session started (session_2026-07-10). progress.md seeded (pre-existing corrections retained). |
| 2026-07-10 | 0.4 | DONE | Baseline recorded above. EXPDIR base mapping confirmed (gw→EXPDIR, gw_v17→EXPDIR_v17). |
| 2026-07-10 | 1.1 | DONE | `SourceEntry.scope` required common field; from_dict rejects missing/invalid (ValueError names source); to_dict emits scope after description; common_keys includes scope. |
| 2026-07-10 | 1.2 | DONE | `_default_scope(source_type)` helper + wired into both builders in generate_unified_manifest.py. See C11: regen is lossy (seed drift), so scope backfilled in place on the 67-source manifest. |
| 2026-07-10 | 1.3 | DONE | Manifest version 9.0.0 → 9.1.0 with dated schema note (generator default + description). |
| 2026-07-10 | 1.4 | DONE | New `tests/unit/test_manifest_scope.py` (5 tests): round-trip, missing/unknown scope raise, scope not in type_fields, live manifest carries scope on all 67. All pass. Existing 10 manifest/model tests still pass. |
| 2026-07-10 | 2.1 | DONE | `scope:` added to all 14 stages in reingest_stages.yaml (documentation/ee2_standards/community_summaries=shared, rest=tenant); documentation depends_on→[] and dropped from validate depends_on (R2.5). `_build_matrix` routes by scope (shared→1 __global__ unit, tenant→N). Backward-compat defaults keep old fixtures at 10 units. |
| 2026-07-10 | 2.2 | DONE | Migrated live v9-0-0 state via `init`: 62→58 units, documentation 5→1 (`__global__:documentation` pending), all 18 terminal (15 done+3 skipped) preserved. PoC 2518-doc partial untouched in ChromaDB (no re-ingest). Backup at /tmp/state_backup.json. |
| 2026-07-10 | 2.3 | DONE | PROGRESS.md regenerated: 18/58 terminal, __global__ section shows collapsed documentation. |
| 2026-07-10 | 2.4/2.5 | DONE | +3 tests in test_reingest_state.py: shared-stage→1 __global__ unit; production matrix = 55 tenant+3 shared=58; migration preserves terminal + collapses documentation. 19/19 pass. |
| 2026-07-10 | 3.1 | DONE | New `src/data/collection_namer.py::resolve_collection_name(domain,scope,tenant,version,profile)`. shared→`mdc-{domain}-{profile}{suffix}`; tenant→`{prefix}mdc-...`; suffix empty for default version; profile from MCP_EMBEDDING_PROFILE (mpnet768 COTS) — fixes titan1024 hardcode (C8). |
| 2026-07-10 | 3.2 | DONE | 4 ingesters routed through namer (docs=workflow-docs/shared; code=code-context/tenant; jjobs=jjobs/tenant; config=code-context/tenant — fixes mdc-code→mdc-code-context mismatch). reset_tenant_cots uses namer over tenant-scoped domains only (docs excluded=shared). `_ingest_common` imports DEFAULT_COLLECTION_VERSION + resolve_collection_name from collection_namer (single source). Verified: reset dry-run targets gw_v17_mdc-code-context-mpnet768-v9-0-0 + gw_v17_mdc-jjobs-mpnet768-v9-0-0; namer reproduces serving names byte-for-byte at default version. |
| 2026-07-10 | 3.3 | DONE | New test_collection_namer.py (13 tests, all pass): 8-case matrix, default-version stability, serving-name alignment, None-tenant, invalid-scope, env-derived profile. |
| 2026-07-10 | TEST-BASELINE | NOTE | Full unit suite: 1283 passed / 26 failed. **All 26 pre-existing, 0 in touched modules**: (a) opensearch-py not installed on COTS → delete_tenant_indices + *_missing_index + tool_common_helpers import failures (AWS-path tests); (b) stale assertions — test_workflow_info default-root (`global-workflow` vs Phase-67 `global-workflow_develop`), test_environment KNOWN_MODULES==9 (now 10 with error_analysis), test_error_analysis taxonomy_class output shape. My new tests (manifest_scope 5, reingest_state +3, collection_namer 13) all pass. |
| 2026-07-10 | 4.1 | DONE (verified) | `workflow_info._resolve_workflow_root_with_tenant()` already resolves `ctx.workflow_root` (env/HOMEgfs fallback). Baseline functional probe already `[OK] pass`; gw→`.pw_workflow_mount/develop`. No code change needed. |
| 2026-07-10 | 4.2 | DONE | Added `semantic_search._resolve_repo_base_with_tenant(override)`: override→tenant ctx workflow_root→MCP_REPO_BASE→default. `check_knowledge_integrity` resolves repo_base at call time inside tenant scope. Live: Coverage Gap now RUNS (7242 Fortran files on disk via `.pw_workflow_mount/develop`); Stale Embeddings git-source comparison works. |
| 2026-07-10 | 5.1/5.2/5.3 | DONE | `ChromaDBAdapter.sample_metadata(collection=None, n=20)` (async, get(limit), []-on-missing, all-collections when None). `_build_vector_sampler` calls it with keyword `n` (compatible with existing mocks). Live: Path Consistency + Stale Embeddings now RUN (0 SKIP). +4 sampler tests pass. |
| 2026-07-10 | 6.1/6.2/6.3 | DONE | `_filter_indices_by_tenant` now recognizes ChromaDB `collections_detail` (root cause: only `indices_detail` was checked → names-branch zeroed total when the 2 gw_v17_ collections were filtered). `_render_vector_status_block` healthy when count>0 OR zero applicable collections. Live: Total Documents=**220538** `[OK] Healthy` (was 0/Unhealthy). +2 tests pass. |
| 2026-07-10 | TEST-RECHECK | NOTE | After Tasks 4/6 edits, test_semantic_search_tools + test_workflow_info: same 3 pre-existing failures (2 opensearchpy missing_index + 1 workflow rename), no new. integrity 16/16, kb_status_and_sampler 6/6 pass. |
| 2026-07-10 | 7.1/7.2 | DONE | Added "Two-Axis Tenant Model (scope × repo)" + worked `pw_mcp` non-global-workflow example to `.kiro/steering/11-tenant-roadmap.md`; clarified workflow_subdir is a repo-relative anchor (no schema change). (On-disk file lacked this; steering context showed a target version — now reconciled.) |
| 2026-07-10 | 8.1/8.2 | DONE | framework progress.md: titan1024 correction marked RESOLVED-by-Phase-68 + new Codebase-Pattern for resolve_collection_name (unblocks Task 2.3). framework design.md: added Phase-68 dependency note (scope model + R3 namer, 58-unit matrix). |
| 2026-07-10 | 9.1 | DONE | Manifest `expdir-configs` reconciled (KNOWN_SOURCES + in-place): scope=tenant, realtime annotation, config_root→`supported_repos/EXPDIR` (runtime tree, not parm/config), file_patterns +*.xml, realtime/materialized_by/tenant_localized fields. Manifest v9.2.0. |
| 2026-07-10 | 9.2 | DONE | `resolve_expdir_base(tenant)` now tenant-derived: gw→EXPDIR, gw_v17→EXPDIR_v17, others→None; MCP_EXPDIR_BASE_OVERRIDE wins for any tenant (dir-checked); never falls back. Returns Path\|None. |
| 2026-07-10 | 9.3 | DONE | expdir + rocoto main() handle None→[SKIP] return 0 (not fail). Verified: gw=17 exps, gw_v17 EXPDIR_v17, gw_sfs/gw_jedi_gfs/gw_gefs_v12 SKIP exit 0. Write-side {prefix}Experiment/{prefix}EXPDIRConfig labels untouched. |
| 2026-07-10 | 9.4 | DONE | Steering EXPDIR note added to 11-tenant-roadmap.md; C10 Correction + EXPDIR base-mapping table already in progress.md. |
| 2026-07-10 | 9.5 | DONE | New test_expdir_base.py (4 tests): override-wins, override-nonexistent→None, unmapped→None, mapped-distinct-trees. All pass. |
| 2026-07-10 | 10.1 | PASS | `mcp_health_check --deep --detailed --functional` (COTS stdio) → **11/11 pass, 0 skip**; workflow_info `[OK] pass`; all 5 tenant roots reachable; health snapshot persisted. |
| 2026-07-10 | 10.2 | PASS | `check_knowledge_integrity` → **4/4 checks run, 0 SKIP**: Path Consistency [OK] 0/50, Orphaned [OK], Stale Embeddings [OK] 50/50 (git compare), Coverage Gap [OK] (106608 symbols / 7242 files). |
| 2026-07-10 | 10.3 | PASS | `get_knowledge_base_status` → **Total Documents 220538, [OK] Healthy** (was 0/Unhealthy). Same 15 in-scope serving collections listed. |
| 2026-07-10 | 10.4 | PASS | `list_all_sources` → v9.2.0, 67 sources; new **By Scope** section (61 shared / 6 tenant); detailed view shows per-source scope; expdir-configs config_root=`supported_repos/EXPDIR` (realtime). Gap-detector actual=n/a on COTS (its actual-count path targets OpenSearch, absent here — expected). |
| 2026-07-10 | 10.5 | PASS | Full unit suite: **1293 passed / 26 failed** — 26 all pre-existing (opensearchpy-missing + stale asserts), **0 regressions**. Fixed 1 existing test (test_expdir_writes::test_default_supported_repos → tenant-derived, my intended R15.3 contract change). Serving names byte-for-byte unchanged: `aws_config.py` (resolve_index / PRODUCTION_INDICES_BY_PROFILE) NOT modified; same physical `mdc-*-mpnet768` collections served. **Before/after COTS store counts UNCHANGED (no ingest ran)**: ChromaDB 223148 docs / 17 colls; Neo4j ~225836 nodes / ~4.05M rels (gw-scoped). Only reporting changed (Total Documents 0→220538; 3 integrity SKIP→run). |
| 2026-07-10 | 11.1 | DONE | CHANGELOG `[Unreleased]` Phase 68 entry added (scope schema, EXPDIR realtime/tenant-derived, path-leak fix, ChromaDB sample_metadata, KB-status count fix, namer, framework cross-ref, verification results). **Staged 28 files** (specs/steering/code/tests + CHANGELOG) via `git add <paths>`. Left unstaged: SDD session-state (`history.jsonl`/`health_history.jsonl`/`active_session.json`), editor artifacts (`.vscode-cli/*`, `.vscode/mcp.json_org`), `supported_repos/parallel-works-mcp` submodule pointer, `tests/slurm_test_job.sh` — not part of this deliverable. **No commit, no push** (human-gated). Temp probe harness (/tmp/cots_probe.py) removed. |
