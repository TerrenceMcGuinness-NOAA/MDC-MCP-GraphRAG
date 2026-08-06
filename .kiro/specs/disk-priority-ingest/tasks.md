# Task List — Disk-Priority Documentation Ingest

> Rules for this spec. (1) Every symbol in `design.md` was read from source — use
> those names, do not invent flags or functions. If something does not exist as
> described, STOP and report rather than substituting. (2) Shell exit codes are
> unreliable in this environment and often report 1 on success — judge from output
> only. (3) Anything expected to exceed 25 minutes must be backgrounded and
> polled. (4) No writes to the vector store until Task 7 is approved.

## Code

- [ ] 1. **`_ingest_provenance.py`** (Req 3)
  `build_provenance(...)` returning only additive keys: `source_kind`,
  `resolved_path`, `commit_sha`, `dirty`, `embedding_profile`, `dimension`.
  Unit test: returns every key; omits nothing; changes no existing key.
  Land this first — it is the rollback lever for Task 4 (see design.md Rollback).

- [ ] 2. **`_ingest_sources.py`** (Req 1, 2)
  `load_doc_sources`, `probe_local`, `resolve_doc_file_set` per design.md.
  Probe reasons must be distinguishable, in the specificity order given.
  Pin check via `git ls-tree HEAD <path>` vs `git -C <path> rev-parse HEAD`;
  dirty via `git status --porcelain`; both timeout-guarded like `files_for_diff`.
  Unit tests: `path_absent`, `path_empty`, `below_min_files`,
  `submodule_off_pin`, `worktree_dirty`, `ok`. The four empty submodules give
  real fixtures for `path_empty`.

- [ ] 3. **Manifest edits + validator** (Req 4)
  Fix `gsi-user-guide.local_path` → `sorc/gsi_enkf.fd`. Make
  `global-workflow-rst.local_path` → `docs`. Add per-source `min_files` using
  the floors in design.md. Add `scripts/validate_manifest_paths.py`.
  Verify: validator exits 0 for tenant `gw`, and exits non-zero if you
  temporarily reintroduce the `sorc/gsi.fd` value.

- [ ] 4. **Wire into `ingest_documentation_v8.py`** (Req 1, 2, 3)
  Replace the walker call with `resolve_doc_file_set`; in `diff` mode intersect
  rather than replace. Move the `--dry-run` return to after resolution and print
  index, profile, dimension, and the per-source decision table. Merge provenance
  into `doc_meta` and into the `make_reference_document` result. Leave dedupe,
  cost reporting, and `write_vector_doc` alone.

- [ ] 5. **Regression guard** (Req 1.6)
  A test asserting the resolved documentation set for `global-workflow_develop`
  is far below the whole-tree count — the bug being guarded is a ~17,000-file
  walk into the shared docs collection. Assert the source-code extensions are
  absent from the resolved set.

## Run

- [ ] 5b. **Unfreeze the crawler profile** (Req 5)
  `mcp_server_node/scripts/ingest_documentation_v8.py` line 25:
  `_args_model = "mpnet768"` → read `MCP_EMBEDDING_PROFILE` with `"mpnet768"` as
  the default. Change nothing else — lines 29-33 already derive the model id,
  dimensions and collection name from that value.
  Verify both directions with `--dry-run --tiers tier1_critical`: with
  `MCP_EMBEDDING_PROFILE=titan1024` the banner must show a titan1024 collection
  and 1024 dimensions; with the variable unset it must show
  `global-workflow-docs-v8-0-0-mpnet768` and 768, unchanged from today.

- [ ] 5c. **Resolve target index names and check them against reality** (Gates 1, 2)
  For both writers, print the collection name that would be written at
  `MCP_EMBEDDING_PROFILE=titan1024`, then compare against the index list from
  `get_knowledge_base_status` on `agentcore-mcp-rag`.
  Known state: AWS holds only `mdc-*` indices; the Node crawler emits the
  `global-workflow-docs-v8-0-0-*` scheme. Expect a mismatch on the crawler side.
  Report the mismatch and the proposed resolution — align the name or add a
  target override — and **STOP**. Do not write to a name the server does not
  query, and do not let OpenSearch auto-create an index (it will type the
  embedding field `float`, not `knn_vector`, and that cannot be changed later).

- [ ] 5d. **Allowlist loss review** (Gate 3)
  Print files the old whole-tree walker would take that the new resolver
  excludes. Review for doc-like content: unusual extensions, extension-less
  READMEs, notebooks, generated HTML. Report anything questionable before the
  write run.

- [ ] 5e. **Apply the gate decisions** (resolves 5c and 5d)
  Three changes, all approved 2026-08-05:

  a. **Fix the four coupled-model paths** in the manifest, per the table in
     design.md: `cice` → `sorc/ufs_model.fd/CICE-interface/CICE`, `mom6` →
     `MOM6-interface/MOM6`, `cdeps` → `CDEPS-interface/CDEPS`, `cmeps` →
     `CMEPS-interface/CMEPS`. Source of truth is
     `sorc/ufs_model.fd/.gitmodules`. Add floors: cice 500, mom6 500,
     cdeps 100, cmeps 100. Expected effect: the four sources resolve `disk / ok`
     instead of failing the tightened validator, and their files are attributed
     to the owning source. Unique content is unchanged — those paths sit inside
     `ufs-weather-model`'s subtree and were already being reached.

  b. **Add a `--collection` target override to the Node crawler.** Default
     behaviour unchanged when the flag is absent, so COTS is unaffected. Used
     for the AWS run to target the serving `mdc-workflow-docs-titan1024`.
     Do not change the crawler's default namer.

  c. **Tighten the validator**: any declared `local_path` that does not resolve
     SHALL be reported as `manifest_defect` and exit non-zero, regardless of
     whether `.gitmodules` knows the path. The four broken paths above passed
     Task 3 as `path_absent`, which is the hole that let them through.
     After tightening, the validator must exit 0 only once all paths resolve.

  d. **Allowlist losses: accepted, no action.** The 143 LaTeX files, 14
     notebooks, 2 release-notes `.txt` and root `README.md` stay excluded —
     each exists in better form via the URL-crawled corpus.

  Then re-run gates 5c and 5d and report the deltas.

- [ ] 6. **Validate + dry run** (Req 6.1, 6.2)
  Export the environment block from design.md, including
  `MCP_WORKFLOW_MOUNT=/mnt/mdc-mcp-rag/eib-mcp-rag-server/.pw_workflow_mount`
  (without it the root resolves to `/mnt/workflow`, which does not exist on this
  host, and the walk silently yields nothing).
  Run the validator, then the dry run. Report: total file count, per-source
  decisions, resolved index, profile and dimension.
  Expected: `cice` / `mom6` / `cdeps` / `cmeps` → `needs_crawl / path_empty`;
  `gsi-user-guide` → `disk / ok`.
  **STOP here for approval before Task 7.**

- [ ] 7. **Write run — disk-backed sources** (Req 6.3, 6.4)
  The Python ingester, backgrounded with polling. Target the shared
  `workflow-docs` collection at `titan1024` against `DB_BACKEND=aws`. Omit
  `--tiers`.

- [ ] 7b. **Write run — URL-only sources** (Req 5, 6.3, 6.4)
  The Node crawler with `MCP_EMBEDDING_PROFILE=titan1024`, one tier per
  invocation (`tier1_critical` … `tier5_standards`), each backgrounded and
  polled. Per-tier runs keep one failing tier from costing the others. Record
  which sources fail; the known-zero set (`cmeps`, `ecmwf-atlas`,
  `jedi-academy-2021-06`, `jedi-academy-2021-10`, `ufs-srweather-app`) is
  expected to fail again and is not blocking.

- [ ] 8. **Post-run verification** (Req 6.5, 6.6)
  `get_knowledge_base_status` for the docs count delta;
  `list_all_sources --include_gaps` for refreshed `last_ingested`;
  fetch a sample document and confirm the provenance fields are present and
  populated. Record the numbers.

## Out of scope

Crawl fallback execution, platform dispatch, profile uniformity across the Node
crawler, drift detection, SageMaker orchestration — all Phase 2, in
`.kiro/specs/sagemaker-drift-remediation/`. Do not begin them from this spec.
