# Phase 52: v17 Paradigm Coverage in EIB MCP/GraphRAG

**Version**: 0.1.0 (DESCRIPTOR — pre-spec)
**Status**: Proposed
**Created**: 2026-04-22
**Author**: Terry McGuinness + AI Assistant
**Dependency**: Phase 38 (KB data quality), Phase 46 (KB gap closure), Phase 24E (hierarchical communities)
**Related**: Phase 27 (J-job graph), Phase 39 (UFS Fortran graph), Phase 40 (config/CI ingestion), Phase 41 (external framework docs)
**Reference doc**: [`global-workflow.wiki/v17_paradigm_assessment.md`](../../supported_repos/global-workflow.wiki/v17_paradigm_assessment.md) (committed `b5ebfca`)

---

## 1. Executive Summary

Add first-class coverage for the **v17 `dev_gsiupd2`** (pre-coupled-modeling) divergent line of the global-workflow superproject so the EIB MCP/GraphRAG can answer questions about **both** the current `develop` paradigm and the parallel v17 paradigm without confusing the two.

Catherine Thomas's `dev_gsiupd2` branch (HEAD `fd237a4f9`, +21 / -0 commits vs forked `develop`, merge-base `94548bc4f`) carries the GSI-update DA work that culminates in a divergent trajectory away from the upcoming coupled-modeling paradigm shift. The current `code-with-context-v8-0-0` and `global-workflow-docs-v8-0-0` collections plus the Neo4j graph (2,758 files / 2.65M relationships) were ingested from a snapshot that predates v17-only additions, so any question about v17 today either silently returns develop-era answers or fails on path drift.

This phase introduces dual-branch ingestion with `branch` / `commit_sha` / `paradigm` metadata tagging, schema extensions for v17-only entities, and reconciliation of paths that have drifted since the v8 ingestion.

## 2. Background

The wiki anchor doc enumerates the full delta. Highlights driving this phase:

| Area | v17-only addition |
|------|-------------------|
| Application | `SFSAppConfig` (`dev/workflow/applications/sfs.py`) + full `parm/config/sfs/` config tree |
| Host | `DERECHO` added to `Host.SUPPORTED_HOSTS`, `dev/workflow/hosts/derecho.yaml`, `env/DERECHO.env`, modulefiles, versions, `parm/fetch/*_derecho.yaml.j2` |
| Rocoto | Exclusive-resource branch in `rocoto/tasks.py` (`CLUSTERS_EXCLUSIVE`, `PARTITION_EXCLUSIVE`, `QUEUE_EXCLUSIVE`, `CONSTRAINT_EXCLUSIVE`, `is_exclusive` task flag → `--exclusive` / `:exclhost`) |
| Workflow CLI | `generate_workflows.sh` `-S` (SFS) / `-C` (GCAFS) / `-I` (BASE_IC override) flags + per-app YAML iteration |
| ush refactor | `err_exit`, `set_strict`/`unset_strict`, `timer`, `wait_for_file`, `cpfsd`, `getdump`, `getioda`, `setup_data_dir`, `dataroot_com_path`; postamble-as-executable; module-loading hygiene |
| Templating | `.j2` migration of archive/fetch configs across gcafs/gfs/gefs/sfs |
| Submodule pins | `gdas.cd a6512d26`, `gsi_enkf.fd 005343a4` (`feature/llvm`), `gsi_monitor.fd 2d0b5ee5`, `gsi_utils.fd 0d6698c6`, `nexus.fd a89721aa`, `ufs_model.fd 163ba47b`, `ufs_utils.fd ae59bc7a` |

In addition, path-based graph lookups already drift today (e.g. graph expects `workflow_xml.py`, source has `rocoto_xml.py`); reconciliation must happen alongside dual-branch ingestion.

## 3. Objective

After this phase:

1. The MCP/GraphRAG can be queried with an explicit `paradigm` filter (`develop` | `v17_pre_coupled`) on code-bearing tools.
2. v17-only entities (SFS app, Derecho host, exclusive-resource fields, `-S/-C/-I` CLI surface, ush helpers) appear in graph and vector results when queried.
3. Cross-cutting collections (`community-summaries`, `ee2-standards-v5-0-0-enhanced`, `ci-test-cases-v1-0-0`) remain branch-agnostic and unduplicated.
4. Path-drift errors against the current `develop` snapshot are eliminated for the files renamed/removed since the v8 cut.

## 4. Scope (high-level — defer detail to spec phase)

1. **Dual-branch ingestion** — second snapshot of `dev_gsiupd2` with all submodules initialized at v17 pins; preserve the existing `develop` snapshot. Both indexed in parallel.
2. **Branch/commit metadata tagging** — every Chroma chunk and Neo4j node gets `branch`, `commit_sha`, `paradigm` properties so search/graph queries filter by paradigm.
3. **Schema extensions** for v17-only entities listed in §2.
4. **Path-drift reconciliation** — repair lookups for files renamed/removed since the v8 ingestion (e.g. `workflow_xml.py` → `rocoto_xml.py`, removed `ush/fv3gfs_remap_weights.sh`).
5. **Cross-cutting collections stay shared** — only code/docs collections are split.
6. **Reference deliverable** — wiki anchor doc `v17_paradigm_assessment.md` (already committed) becomes the inaugural paradigm-aware reference.

## 5. Out of Scope (for this descriptor)

Defer to the spec phase:

- Detailed Neo4j schema deltas and Chroma collection naming convention
- Ingestion-pipeline code changes
- Validation criteria and regression suite
- MCP tool API additions for `paradigm` filtering
- Whether to retire any v8 collections or only add new ones alongside

## 6. Inputs Already Captured

- 21-commit log of `dev_gsiupd2` atop forked `develop` (merge-base `94548bc4f`, HEAD `fd237a4f9`)
- Branch-superproject diff stat: 57 files +961 / -222 across `env/`, `modulefiles/`, `versions/`, `parm/`, `sorc/`, `ush/`
- `dev/workflow` infra diff stat: 47 files +489 / -169
- Submodule pin table (§2)
- 9 EXPDIR cases at `/gpfs/f6/gfs-cpu/world-shared/Catherine.Thomas/tmp/RUNTESTS_v17_gsiupd3/EXPDIR`
- Wiki reference doc `v17_paradigm_assessment.md` (committed `b5ebfca` to `global-workflow.wiki`)

## 7. Acceptance Criteria (placeholder — finalize in spec)

| # | Probe | Expected after phase |
|---|-------|----------------------|
| 1 | `find_dependencies` on `SFSAppConfig` with `paradigm=v17_pre_coupled` | non-empty results from `applications/sfs.py` |
| 2 | `explain_workflow_component({component:"DERECHO"})` | populated host config + env summary |
| 3 | `find_callers_callees` on `is_exclusive` | hits in `rocoto/tasks.py` exclusive branch |
| 4 | Same query without `paradigm` filter | clearly delineated `develop` vs `v17_pre_coupled` results, no silent mixing |
| 5 | `get_knowledge_base_status` | reports both branches, total docs ≈ 2× current code/docs counts (cross-cutting unchanged) |
| 6 | `find_related_files("rocoto_xml.py")` | resolves correctly on `develop` snapshot (path-drift fix) |

## 8. Open Questions for Spec Phase

1. Collection naming: parallel `*-v9-develop-*` and `*-v9-v17-*` collections, or single collection with `paradigm` metadata filter?
2. Graph: separate Neo4j databases per branch, or shared graph with `:Branch` label and `branch` property on every node?
3. Submodule snapshots: full clone of each submodule at v17 pin, or shallow checkout limited to ingested file types?
4. Refresh cadence: how often does `dev_gsiupd2` move, and should ingestion be triggered on tagged refs only?
5. Tool surface: add `paradigm` as an optional parameter on existing tools, or expose new paradigm-scoped variants?

---

**Next step**: Promote this descriptor to a spec by registering it via `mcp_eib-mcp-gatew_start_sdd_session` once the gateway SDD store is writable (currently EROFS on `active_session.json`), then expand §4–§7 with concrete schema/code/test deltas.
