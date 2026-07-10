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

## EXPDIR base mapping (fill in from COTS — R15.3)

| Tenant | EXPDIR base (path) | Materialized? |
|---|---|---|
| gw | _TBD (e.g. supported_repos/EXPDIR)_ | _TBD_ |
| gw_v17 | _TBD (e.g. supported_repos/EXPDIR_v17)_ | _TBD_ |
| gw_sfs / gw_jedi_gfs / gw_gefs_v12 | (expected: none → skip) | _TBD_ |

---

## COTS environment facts (verified 2026-07-09)

- ChromaDB `:8080` — ~15 live serving collections (doc collections **unprefixed**).
- Neo4j `:7687` — ≈343,363 nodes / ≈4,220,211 rels; **GDS 2.13.7 present**.
- `mpnet768` (all-mpnet-base-v2, 768-dim) functional.
- `DB_BACKEND=cots` env via `run_mcp_stdio.sh`; worktrees under `.pw_workflow_mount`.

## Baseline COTS counts (fill in at Task 0.4 — before any change)

| Probe | Baseline | Method (C1) |
|---|---|---|
| `get_knowledge_base_status` Total Documents | _TBD_ | _TBD_ |
| `check_knowledge_integrity` checks run / skipped | _TBD_ | _TBD_ |
| `mcp_health_check --functional` pass/skip | _TBD_ | _TBD_ |

---

## Progress log

| Date | Task | Result | Notes / Correction added |
|---|---|---|---|
| _pending_ | 0.x | — | Kickoff not yet run. |
