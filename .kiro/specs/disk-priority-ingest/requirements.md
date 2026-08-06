# Requirements Document — Disk-Priority Documentation Ingest

## Introduction

Phase 1 of the drift work: make the documentation ingester correct, then run the
re-ingest. Scoped to the code changes that must land **before** any re-ingest.

Phase 2 — drift detection, platform dispatch, profile uniformity, and SageMaker
orchestration — stays in `.kiro/specs/sagemaker-drift-remediation/`. That spec
holds the full audit table this one refers to.

Two defects found while reading the code are blocking and are included here even
though they were not in the original requirement set.

### Blocking defect 1: the documentation ingester has no notion of documentation

`_ingest_walkers.files_for_full_branch(worktree_root)` yields **every file** under
the worktree except `.git/`. `ingest_documentation_v8.main()` consumes that list
directly, skipping only files that fail `read_text(errors="strict")` or are
whitespace-only. There is no extension allowlist and no `docs/` scoping.

Consequence: a full run embeds the entire text corpus of the repo — all of
`sorc/`, every `.F90`, `.yaml`, `.sh` — into the **shared, unprefixed**
`workflow-docs` collection that every tenant queries. That is roughly 17,000
files of source code landing in the documentation index, at Bedrock cost, where
it competes with real documentation in every `search_documentation` call. Code
already has its own collection (`code-context`).

This must be fixed before the re-ingest, not after.

### Blocking defect 2: worktree root resolves to a path that does not exist on the ingest host

`Tenant.workflow_root` returns `Path(os.environ.get("MCP_WORKFLOW_MOUNT",
"/mnt/workflow")) / workflow_subdir`. `/mnt/workflow` is the AgentCore EFS
mount and exists only inside the runtime microVM. On the dev host a run resolves
to a nonexistent path and walks zero files, reporting success.

`resolve_worktree_root` also honours `MCP_WORKTREE_ROOT_OVERRIDE`, which takes
precedence. Either variable fixes it; the run procedure must set one.

## Requirements

### Requirement 1: Scope documentation ingestion to documentation

#### Acceptance Criteria

1. Documentation file selection SHALL be driven by an explicit source set, not by
   walking the whole worktree.
2. The source set SHALL be built from the manifest: each source's `local_path`
   subtree, plus the tenant's own `docs/` tree.
3. An extension allowlist SHALL apply (`.rst`, `.md`, `.txt`, and the doc
   formats already present under `docs/`). Source files SHALL be excluded.
4. `files_for_full_branch` SHALL NOT be used unfiltered by the documentation
   ingester. Its behaviour SHALL be left unchanged for other callers.
5. A dry run SHALL print the resolved file count per source and the total, so the
   blast radius is visible before any write.
6. Regression guard: a dry run against `global-workflow_develop` SHALL report a
   documentation file count in the low thousands at most, not ~17,000.

### Requirement 2: Disk-priority resolution with a consistency gate

#### Acceptance Criteria

1. For a source declaring both `url` and `local_path`, the resolver SHALL probe
   the local path and prefer disk when the probe passes.
2. The probe SHALL require all of: path exists; file count meets the source's
   `min_files` floor; containing submodule at the superproject's pinned commit;
   worktree clean.
3. A path that exists but is empty SHALL fail the probe and SHALL be reported
   distinctly from "path absent" — this is the CICE / MOM6 / CDEPS / CMEPS case.
4. A `local_path` that cannot resolve SHALL be reported as a manifest defect
   (the `gsi-user-guide` → `sorc/gsi.fd` case), not silently degraded.
5. An initialized-but-off-pin or dirty submodule SHALL fail the probe.
6. `min_files` SHALL be per-source.
7. When the probe fails, the resolver SHALL record `needs_crawl` with a reason.
   Those sources are refreshed by the crawler under Requirement 5 — roughly 46
   of ~58 documentation sources are URL-only and have no on-disk counterpart, so
   disk-priority alone would leave the stale corpus stale.
8. The per-source decision and reason SHALL appear in the dry-run output.

### Requirement 3: Provenance stamping

#### Acceptance Criteria

1. `doc_meta` in `ingest_documentation_v8.main()` currently carries
   `tenant_id`, `source`, `content_sha256`. It SHALL additionally carry:
   `source_kind` (`disk`), the resolved path, the **commit SHA** of the
   containing repo or submodule, a dirty flag, the embedding profile, and the
   vector dimension.
2. Provenance SHALL be written at write time through the existing
   `write_vector_doc(..., metadata=doc_meta, ...)` path — no separate pass.
3. Reference documents produced by `make_reference_document` for deduped content
   SHALL carry the same provenance fields.
4. Provenance SHALL be queryable per collection, so Phase 2 can compute drift as
   ingested SHA vs current SHA.
5. Stamping SHALL be additive — existing metadata keys and their meanings SHALL
   NOT change.

### Requirement 4: Manifest hygiene and a validator

#### Acceptance Criteria

1. `gsi-user-guide.local_path` SHALL be corrected from `sorc/gsi.fd` to
   `sorc/gsi_enkf.fd` (verified: `sorc/gsi.fd` does not exist; `.gitmodules`
   maps `sorc/gsi_enkf.fd` → `NOAA-EMC/GSI.git`; 1,900 files on disk).
2. `global-workflow-rst.local_path` SHALL become worktree-relative (`docs`)
   rather than embedding the `global-workflow_develop` checkout directory name,
   which is not portable to other tenants.
3. Per-source `min_files` floors SHALL be added for every source declaring a
   `local_path`.
4. A validator (`scripts/validate_manifest_paths.py`) SHALL check every declared
   `local_path` against `.gitmodules` and the worktree, exiting non-zero on any
   path that cannot resolve for the given tenant.
5. The validator SHALL run before the ingest and SHALL be cheap enough to run
   routinely (no network, no embedding).

### Requirement 5: Unfreeze the crawler's embedding profile

The URL crawler is the only path that can refresh the ~46 URL-only sources, and
it currently cannot write the profile AWS serves.

#### Acceptance Criteria

1. `mcp_server_node/scripts/ingest_documentation_v8.py` line 25 sets
   `_args_model = "mpnet768"` as a hardcoded literal. It SHALL instead read
   `MCP_EMBEDDING_PROFILE`, defaulting to `mpnet768` so current behaviour is
   preserved when the variable is unset.
2. No other change to that script is required: the profile registry lookup,
   collection namer, `EMBEDDING_MODEL`, and `EMBEDDING_DIMENSIONS` on lines 29-33
   already derive from `_args_model`.
3. With `MCP_EMBEDDING_PROFILE=titan1024`, a `--dry-run` SHALL report a
   titan1024 collection name and 1024 dimensions — not the
   `global-workflow-docs-v8-0-0-mpnet768` / 768 it reports today.
4. With the variable unset, the dry run SHALL report exactly what it reports
   today, proving the change is non-breaking for COTS.

### Requirement 6: Run the re-ingest

#### Acceptance Criteria

1. The run SHALL set `MCP_WORKFLOW_MOUNT` (or `MCP_WORKTREE_ROOT_OVERRIDE`) so
   the worktree root resolves on the ingest host.
2. A dry run SHALL precede the write run and SHALL be reviewed: resolved source
   set, per-source disk/needs-crawl decision, file counts, target index, profile.
3. The write run SHALL target the shared `workflow-docs` collection at profile
   `titan1024` against `DB_BACKEND=aws`.
4. Any command exceeding 25 minutes SHALL be backgrounded and polled — the shell
   tool caps at 1800s.
5. Success SHALL be judged from command output and from
   `get_knowledge_base_status` / `list_all_sources --include_gaps`, never from
   the shell exit code, which is unreliable in this environment.
6. Post-run, provenance SHALL be spot-checked on a sample of written documents.

## Deferred to Phase 2 — cross-tenant dedupe makes 1,432 gw rows unretrievable (HIGH)

**Priority: HIGH.** Discovered 2026-08-06 while reconciling the Task 7 run
accounting. Cross-tenant content dedupe, combined with the absence of any
reference-resolution step in the query path, means **1,432 gw documentation rows
are present in the serving index but cannot return their content**.

### Evidence

1. `SHAIndex` keys the registry on `(collection, sha)` — `collection` is the
   logical token `"documentation"` and is **tenant-agnostic**. The class docstring
   states this is deliberate: "Cross-tenant SHA lookup avoids re-embedding files
   that are identical between tenants."
2. Live registry census for `collection=documentation` (26,593 entries):
   - **26,331** registered before the gw run, all with
     `index = gw_v17_mdc-workflow-docs-titan1024`
   - 262 registered by the gw run, with `index = mdc-workflow-docs-titan1024`
   So the gw run's lookups matched SHAs owned by the **gw_v17 tenant index**, and
   wrote reference rows whose `canonical_index` points there.
3. `grep -rn` over `mcp_server_python/src/` finds **zero** occurrences of
   `canonical_index`, `canonical_id`, or `is_reference` (contrast:
   `mcp_server_python/scripts/` has 11 / 10 / 1). The writers create references;
   **no reader ever chases them.** A search hit on a reference row returns the
   placeholder string `"<reference: see canonical doc>"`, not the real content.
4. Net effect in the shared docs index: 1,432 of 21,849 rows (~6.6%) are inert
   placeholders with `embedding: None`, so they are also invisible to k-NN and
   only reachable by BM25 on their metadata.

### Scope inversion (the structural half of the bug)

Documentation is `scope: shared` — its canonical rows belong in the
**unprefixed** `mdc-workflow-docs-<profile>` collection that every tenant queries.
But because gw_v17 was ingested first, the canonical copies live in the
**tenant-prefixed** `gw_v17_mdc-workflow-docs-titan1024`, and the shared
collection holds the references. Shared content is canonically owned by a tenant
index — exactly backwards. A tenant-scoped teardown of `gw_v17_*` would strand
every one of those references.

### Candidate fixes (not chosen — Phase 2 decides)

1. **Prefer-shared-index for canonical placement.** When a source's scope is
   `shared`, force the canonical row into the unprefixed collection and let
   tenant indices hold references (or nothing). Fixes the inversion at the root;
   requires a re-ingest or a migration of existing canonical rows.
2. **Per-index registry keys.** Extend the dedupe key from `(collection, sha)` to
   include the target index/tenant, so a SHA registered under one index never
   suppresses the embedding of the same content into another. Simplest change;
   costs the cross-tenant embedding savings the current design buys.
3. **Query-path reference resolution.** Teach the read path to detect
   `is_reference` and fetch `canonical_index` / `canonical_id`, splicing in the
   real content. Preserves the storage savings; adds a second round-trip per
   reference hit and a cross-index read dependency between tenants.

Not attempted in Phase 1 — no fix was made in this pass. Phase 1's writes are
unaffected in correctness terms (nothing is corrupt; the 262 canonical gw embeds
and all crawler-written rows are fully retrievable).

## Deferred to Phase 2 — disk-source status tracking

`backfill_manifest_status.py` filters on `source_type == url_crawl` and counts by
source name. That is correct for what it does, and it is shared with other flows,
so it is not changed here.

Consequence: `last_ingested` for disk-backed sources is **not** updated by a
Python-ingester run, even with `source_name` stamped. `global-workflow-rst`
(`on_disk_submodule`, no URL) can never be updated by that script at all.

For Phase 1, disk-source freshness is evidenced by the in-index
`source_kind=disk` provenance plus the run's ingestion report under
`mcp_server_python/scripts/ingestion_reports/`. Requirement 6.6's "refreshed
`last_ingested`" applies only to the URL-crawled sources refreshed under
Requirement 5.

Phase 2 owns reconciling the two status models: either extend the backfill to
handle non-`url_crawl` source types keyed on the stamped `source_name`, or record
disk-source status at ingest time and stop inferring it from the index.

## Non-Goals

- Crawl fallback execution (Requirement 2.7).
- Platform dispatch, profile uniformity, drift detection, SageMaker — Phase 2.
- Initializing the four empty nested submodules. The gate handles them as
  `needs_crawl`; whether to populate them is an operator decision, not a
  code change.
- Any change to the code, jjobs, config, or graph ingesters.
