# Requirements Document — SageMaker RAG Drift Remediation

> **Phase 2.** Requirements 3, 4 and 7 of this document were split out into
> `.kiro/specs/disk-priority-ingest/` as Phase 1 — the code changes that must
> land before the next re-ingest, plus the re-ingest itself. This spec retains
> the automation layer: platform dispatch (Req 1), profile uniformity (Req 2),
> deterministic drift detection (Req 5), and SageMaker orchestration (Req 6).
> Requirements 3, 4 and 7 stay here for context; Phase 1 owns their delivery.
>
> Phase 2 depends on Phase 1: drift detection needs the provenance stamps
> (commit SHA per document) that Phase 1 introduces. Without them, drift for
> disk-backed sources cannot be computed exactly.

## Introduction

Automated, scheduled remediation of RAG and GraphRAG drift, orchestrated on
Amazon SageMaker, platform-aware across the AWS and COTS backends, and
configurable per embedding profile.

This is deliberately **not** a Ralph loop. Ralph is agent-in-the-loop and
goal-seeking, which suits recursive self-improvement where the path is unknown.
Drift remediation is the opposite shape: drift is a measurable delta, the plan
follows mechanically from the delta, and completion is an assertable end-state.
No agent belongs in that control loop. The Ralph *substrate* is reused —
`reingest_stages.yaml` (stage catalog with `depends_on`, `source_precondition`,
`probe`, `destructive`, `optional`) and `reingest_state.py` (Work_Matrix,
attempt caps, durable state) — while the agent driver is replaced by a
deterministic pipeline.

### Empirical basis (audited 2026-08-05, `global-workflow_develop` on the dev host)

The manifest declares `local_path` on 12 sources. Actual on-disk state:

| Source | Declared `local_path` | Files on disk | Usable |
|---|---|---:|---|
| `ufs-weather-model` | `sorc/ufs_model.fd` | 3000+ | yes |
| `jedi-docs` | `sorc/gdas.cd` | 3000+ | yes |
| `pyioda` | `sorc/gdas.cd` | 3000+ | yes |
| `ww3-wiki` | `sorc/ufs_model.fd/WW3` | 3000+ | yes |
| `ufs-utils` | `sorc/ufs_utils.fd` | 1279 | yes |
| `global-workflow-rst` | `supported_repos/global-workflow_develop/docs` | 62 | path not tenant-portable |
| `gocart` | `sorc/ufs_model.fd/GOCART` | 181 | ambiguous |
| `gsi-user-guide` | `sorc/gsi.fd` | **path does not exist** | no — actual dir is `sorc/gsi_enkf.fd` (1900 files) |
| `cice` | `sorc/ufs_model.fd/CICE` | **0** | no — nested submodule uninitialized |
| `mom6` | `sorc/ufs_model.fd/MOM6` | **0** | no |
| `cdeps` | `sorc/ufs_model.fd/CDEPS` | **0** | no |
| `cmeps` | `sorc/ufs_model.fd/CMEPS` | **0** | no |

Five of twelve are cleanly usable. The failures fall into three distinct
classes, which is why a single "does the directory exist" test is insufficient:

1. **Empty submodule mount points** (CICE, MOM6, CDEPS, CMEPS). The directory
   exists; it contains zero files. A presence check passes, the ingest yields
   nothing, and nobody notices. This is the silent-failure mode the consistency
   gate exists to prevent.
2. **Stale declared path** (`gsi-user-guide` → `sorc/gsi.fd`). No such
   directory; `.gitmodules` maps GSI to `sorc/gsi_enkf.fd`. This source would
   fall back to crawl forever while appearing to be disk-backed in the manifest.
3. **Non-portable path** (`global-workflow-rst` → a path containing the
   `_develop` checkout directory name). Resolving this for `gw_v17` would read
   the `develop` tree. Same class as the Phase 67 path-rename defects.

Two further findings from the same audit, both blocking:

- **`/mnt/workflow` exists only inside the AgentCore microVM.** The Python
  ingesters default their root there, so a run on the dev host resolves to a
  nonexistent path and walks nothing. Host runs require
  `MCP_WORKFLOW_MOUNT=<repo>/.pw_workflow_mount`.
- **The Node URL crawler ignores `MCP_EMBEDDING_PROFILE`.** With
  `titan1024` exported it reported `Collection: global-workflow-docs-v8-0-0-mpnet768`
  / `all-mpnet-base-v2 (768 dimensions)`. The `--model` flag referenced in the
  May 2026 progress notes is no longer in its parser. So the crawler cannot
  currently write the `titan1024` serving index that AWS queries.

## Requirements

### Requirement 1: Platform-aware execution

The remediation pipeline SHALL target either backend from one definition.

#### Acceptance Criteria

1. Every stage SHALL accept a platform selector resolving to `aws` (OpenSearch +
   Neptune + Bedrock) or `cots` (ChromaDB + Neo4j + local sentence-transformers).
2. Stage definitions SHALL NOT hardcode backend-specific scripts. The current
   `reingest_stages.yaml` names `reset_tenant_cots.py`; the reset stage SHALL
   dispatch by platform instead.
3. `ralph_reingest_loop.sh`'s COTS-only env defaults (`DB_BACKEND=cots`,
   `NEO4J_URI`, `CHROMADB_HOST`) SHALL NOT be inherited by the remediation
   runner; platform env SHALL be derived from the selector.
4. A dry run SHALL report the resolved platform, target collection names, and
   graph label prefixes before any write.
5. Running the same plan against both platforms SHALL be supported without
   editing the plan.

### Requirement 2: Configurable embedding profile, uniformly honored

Profile selection SHALL be a first-class parameter respected by every ingester.

#### Acceptance Criteria

1. The pipeline SHALL accept a profile parameter with initial values
   `titan1024`, `mpnet768`, and `gemini*` (dimension per the provider registry).
2. Every ingester invoked by the pipeline SHALL resolve its embedding provider
   and target collection from that parameter. The Node crawler's current
   hardcoded mpnet768 behaviour SHALL be corrected or the crawler SHALL be
   replaced in the pipeline.
3. A dry run SHALL print the resolved provider, dimension, and target collection
   for each stage, so a profile mismatch is caught before writes.
4. The pipeline SHALL refuse to write into a collection whose declared dimension
   does not match the resolved provider's dimension.
5. Profile SHALL be recorded in the provenance stamp (Requirement 4) so a
   collection's embedding lineage is inspectable after the fact.
6. Adding the Gemini provider SHALL require no change to stage definitions —
   only a registry entry and a credential reference.

### Requirement 3: Disk-priority source resolution with a consistency gate

Where content exists on disk, the pipeline SHALL prefer it over crawling.
Crawling a site generated from a `docs/` tree already checked out is strictly
worse: broken relative TOCs, 404s, rate limits, and no commit provenance.

#### Acceptance Criteria

1. For a source declaring both `url` and `local_path`, the resolver SHALL probe
   the local path and prefer disk when the probe passes.
2. The probe SHALL require **all** of: path exists; file count meets a
   per-source `min_files` floor; the containing submodule is at the
   superproject's pinned commit; the worktree is clean.
3. A path that exists but contains zero files SHALL fail the probe (the CICE /
   MOM6 / CDEPS / CMEPS case) and SHALL be reported distinctly from "path
   absent".
4. A `local_path` that does not resolve SHALL be reported as a **manifest
   defect**, not silently degraded to crawl (the `gsi.fd` case).
5. A submodule that is initialized but off-pin or dirty SHALL fail the probe.
   Embedding a tree that corresponds to no released commit is worse than
   crawling, because the content matches no version.
6. `min_files` SHALL be per-source, not a single global threshold — GOCART at
   181 files and CICE at 0 require different verdicts.
7. Sources with no vendored counterpart (approximately 25: `spack`,
   `spack-stack`, `ecflow`, `rocoto`, `pyflow`, `metplus`, `upp`, `wgrib2`, the
   NCEPLIBS set, `kokkos`, `pep8`, the ESMF/NUOPC PDFs) SHALL remain URL-only
   and SHALL NOT be flagged as disk-resolution failures.
8. The resolution decision per source SHALL appear in the dry-run output.

### Requirement 4: Provenance stamping

Every ingested document and graph node SHALL record how it was obtained.

#### Acceptance Criteria

1. Disk-sourced content SHALL stamp `source=disk`, the resolved path, and the
   **commit SHA** of the containing repo or submodule.
2. Crawled content SHALL stamp `source=url`, the URL, and the crawl timestamp.
3. Both SHALL stamp the embedding profile and dimension.
4. Provenance SHALL be queryable per collection so drift detection can compare
   ingested state against current source state.
5. The stamp SHALL be written by the ingester at write time, not reconstructed
   later from manifest status.

### Requirement 5: Deterministic drift detection driving the plan

Drift SHALL be detected by comparison, and the remediation plan SHALL follow
from the comparison rather than from operator or agent judgment.

#### Acceptance Criteria

1. For disk-backed sources, drift SHALL be computed as ingested commit SHA vs
   current checkout SHA (plus dirty flag). This is exact, not heuristic.
2. For URL-only sources, drift SHALL fall back to a staleness threshold on the
   crawl timestamp, and the report SHALL mark that verdict as heuristic.
3. Optionally, semantic drift SHALL be computed by re-embedding a sample and
   comparing cosine similarity against stored vectors, reusing the approach in
   `mcp_server_node/scripts/drift_detector.py` (0.95 threshold), which was never
   ported to Python.
4. The detector SHALL emit a set of `(tenant, stage)` units to re-run, mapped
   through the existing Work_Matrix and its `depends_on` graph.
5. The plan SHALL be reproducible: the same source state and the same ingested
   state SHALL yield the same plan.
6. An empty plan SHALL be a valid, reportable outcome meaning "no drift".

### Requirement 6: SageMaker orchestration

#### Acceptance Criteria

1. Heavy batch work (re-embedding, cosine comparison, code and Fortran parsing)
   SHALL run as SageMaker **Processing Jobs** — ephemeral, right-sized, S3 in
   and out, with no long-running process on a dev host.
2. Stage sequencing SHALL be expressed as a SageMaker **Pipeline**, so
   dependency ordering, retries, and step caching are service features rather
   than maintained code. The `depends_on` relations in `reingest_stages.yaml`
   SHALL map onto pipeline step dependencies.
3. Scheduled execution SHALL be driven by **EventBridge**, satisfying the Tier C
   scheduled-consumer role described in steering file 09, with no systemd unit
   on the dev host.
4. Operator-induced execution SHALL be supported for the same pipeline, with
   parameter overrides for platform, profile, tenant, and stage subset.
5. Pipeline execution history SHALL be the run record; bespoke `PROGRESS.md`
   state SHALL NOT be required, though per-unit attempt caps SHALL be preserved.
6. Destructive stages SHALL remain gated by an explicit confirmation parameter,
   defaulting to refuse.
7. The final pipeline step SHALL run the benchmark harness so each remediation
   produces a measurable quality signal.

### Requirement 7: Manifest hygiene

The audit findings SHALL be corrected, and the corrections SHALL be enforceable.

#### Acceptance Criteria

1. `gsi-user-guide.local_path` SHALL be corrected from `sorc/gsi.fd` to the
   actual submodule path (`sorc/gsi_enkf.fd`).
2. `global-workflow-rst.local_path` SHALL be made tenant-portable (worktree-
   relative, e.g. `docs`) rather than embedding a checkout directory name.
3. A validator SHALL check every declared `local_path` against `.gitmodules` and
   the worktree, failing on paths that cannot resolve for any tenant.
4. The validator SHALL run in the pipeline's first step so manifest defects
   surface before any ingestion cost is incurred.
5. Per-source `min_files` floors SHALL be added to the manifest or the stage
   catalog for every source declaring a `local_path`.

## Non-Goals

- Porting the community-summaries pipeline (Gap J) — separate spec.
- Choosing the COTS primary embedding profile — deferred pending the Gemini key.
- Replacing `check_knowledge_integrity`; it remains the runtime spot-check while
  this pipeline owns scheduled remediation.
- Any agentic decision-making inside the remediation control loop.

## Open Questions

1. ~~Fix the Node crawler's mpnet768 binding, or port crawling into the Python
   ingester?~~ **Settled 2026-08-05 by inspection.** Line 25 of
   `mcp_server_node/scripts/ingest_documentation_v8.py` is
   `_args_model = "mpnet768"` — a hardcoded literal feeding a profile registry
   that already derives the model id, dimensions and collection name from it.
   Reading `MCP_EMBEDDING_PROFILE` there is a one-line change, delivered in
   Phase 1 (`disk-priority-ingest` Req 5). No port needed. Retiring the Node
   crawler remains possible later but is not required by anything.
2. Should nested submodules (CICE, MOM6, CDEPS, CMEPS) be initialized on the
   ingest host so those four sources become disk-backed, or do they stay
   URL-only? Initializing adds several GB per tenant. This is a genuine cost
   decision for an operator, not a code question — the consistency gate handles
   either answer.
3. Does GOCART at 181 files represent a complete docs subset or a partial
   checkout? Determines its `min_files` floor. Decidable during implementation.
