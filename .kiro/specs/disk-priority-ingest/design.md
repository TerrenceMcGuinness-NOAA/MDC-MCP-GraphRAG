# Design Document — Disk-Priority Documentation Ingest

> Every symbol named here was read from source on 2026-08-05. Do not add flags or
> functions to this document from a manifest description — the predecessor spec
> failed a CLI handoff that way.

## Current code, as it exists

### `scripts/ingest_documentation_v8.py` (142 lines)

```
main()
  build_ingestion_parser("Tenant-aware documentation ingestion (v8)")
  load_catalog(MCP_TENANT_CATALOG_PATH | src/config/tenants.yaml)
  resolve_tenant_and_mode(args, catalog)        -> (tenant, mode)
  resolve_worktree_root(tenant)                 -> Path
  if args.dry_run: print + return 0             # <-- resolves nothing further
  build_ingestion_data_access()                 -> (uda, raw_os_client)
  SHAIndex(client=raw_os_client)
  resolve_collection_version(args)
  resolve_collection_name(domain="workflow-docs", scope="shared",
                          tenant=..., version=...)
  files = files_for_diff(root) if mode=="diff" else files_for_full_branch(root)
  for path in files:
      content = path.read_text(errors="strict")   # binary/undecodable -> skip
      sha = sha_index.hash_file(path)
      lookup -> duplicate ? make_reference_document(...) : embed + write_vector_doc(...)
```

`doc_meta` today:

```python
doc_meta = {
    "tenant_id": tenant.tenant_id,
    "source": str(path),
    "content_sha256": sha,
}
```

### `scripts/_ingest_walkers.py`

```python
def files_for_full_branch(worktree_root: Path) -> Iterator[Path]:
    for p in worktree_root.rglob("*"):
        if p.is_file() and ".git" not in p.parts:
            yield p
```

No extension filter. This is blocking defect 1.

### Root resolution

```python
# scripts/_ingest_common.py
def resolve_worktree_root(tenant) -> Path:
    override = os.environ.get("MCP_WORKTREE_ROOT_OVERRIDE")
    if override:
        return Path(override) / tenant.workflow_subdir
    return tenant.workflow_root

# src/config/tenants.py
@property
def workflow_root(self) -> Path:
    base = os.environ.get("MCP_WORKFLOW_MOUNT", _DEFAULT_WORKFLOW_MOUNT)  # /mnt/workflow
    return Path(base) / self.workflow_subdir
```

### Shared parser

`_ingest_common.build_ingestion_parser` provides `--tenant`, `--mode {diff,full}`,
`--tiers`, `--dry-run`, `--delay`, `--only`, `--collection-version`. `--tiers` is
parsed but unused by this ingester. There is no `--model`; profile comes from
`MCP_EMBEDDING_PROFILE`.

## Changes

### New: `scripts/_ingest_sources.py`

Owns source-set resolution and the consistency gate. Pure functions, no I/O to
the vector store, so it is unit-testable and usable by the validator.

```
load_doc_sources(manifest_path) -> list[DocSource]
    DocSource: name, url|None, local_path|None, min_files, extensions

probe_local(source, worktree_root, repo_root) -> LocalProbe
    LocalProbe: usable: bool
                reason: "ok" | "path_absent" | "path_empty"
                        | "below_min_files" | "submodule_off_pin"
                        | "worktree_dirty" | "manifest_defect"
                resolved_path: Path | None
                commit_sha: str | None
                dirty: bool

resolve_doc_file_set(sources, worktree_root, repo_root)
    -> (files: list[tuple[Path, DocSource, LocalProbe]],
        decisions: list[SourceDecision])   # one per source, disk | needs_crawl
```

Probe order matters — report the most specific reason:
`path_absent` → `manifest_defect` if `.gitmodules` has no such submodule and the
path is under `sorc/`; else `path_empty` → `below_min_files` →
`submodule_off_pin` → `worktree_dirty` → `ok`.

Pin check: `git -C <worktree> ls-tree HEAD <local_path>` gives the gitlink SHA;
`git -C <local_path> rev-parse HEAD` gives the checked-out SHA. Equal → at pin.
Dirty check: `git -C <local_path> status --porcelain` non-empty.
Both wrapped with a timeout, matching the 30s guard already used in
`files_for_diff`.

### New: `scripts/_ingest_provenance.py`

```
build_provenance(*, source_name, source_kind, resolved_path, commit_sha, dirty,
                 profile, dimension) -> dict
```

`source_name` is the manifest source that owns the file (e.g. `cice`,
`ufs-utils`). It was missing from the first draft of this design, which was a
real omission: without it a document records where the file lives but not which
source owns it, so nothing downstream can attribute a write to a source.

`resolve_doc_file_set` already returns `(Path, DocSource, LocalProbe)` triples, so
the value is in hand at write time and needs only to be threaded through.

Two consequences of the omission, both observed live on 2026-08-05:

- `backfill_manifest_status.py` counts per source via
  `metadata.source.keyword == <source_name>`, but the ingester stamps
  `metadata.source` as the full file path. None of the 1,580 `source_kind=disk`
  documents matched any source name, so the backfill reported every disk-backed
  source unchanged at `2026-05-20`.
- Where source subtrees overlap (CICE, MOM6, CDEPS, CMEPS inside
  `sorc/ufs_model.fd`), attribution was only inferable by prefix matching.

Returns only the additive keys. Callers merge into their existing metadata dict
so nothing existing changes:

```python
doc_meta = {
    "tenant_id": tenant.tenant_id,
    "source": str(path),
    "content_sha256": sha,
    **build_provenance(source_kind="disk", resolved_path=path,
                       commit_sha=sha_of_containing_repo, dirty=False,
                       profile=profile, dimension=dim),
}
```

The same merge applies to the dict returned by `make_reference_document` before
it is indexed, so deduped references carry provenance too (Requirement 3.3).

Profile and dimension come from the already-resolved embedding provider rather
than being re-read from the environment, so the stamp records what was actually
used.

### Modified: `scripts/ingest_documentation_v8.py`

1. Replace the `files_for_diff` / `files_for_full_branch` call with
   `resolve_doc_file_set(...)`. In `diff` mode, intersect the resolved set with
   the changed-file list rather than replacing it.
2. Move the `--dry-run` early return to **after** source resolution, and print:
   resolved index name, profile and dimension, per-source decision with reason,
   per-source file count, total. This is the review gate in Requirement 5.2.
3. Merge provenance into `doc_meta` and into the reference document.
4. Leave dedupe, cost reporting, and `write_vector_doc` untouched.

### New: `scripts/validate_manifest_paths.py`

Consumes `load_doc_sources` + `probe_local`. Prints a table of
source / declared path / verdict / reason, exits non-zero if any verdict is
`manifest_defect`. No network, no embedding.

### Manifest edits — `src/config/unified_manifest.json`

| Source | Field | From | To |
|---|---|---|---|
| `gsi-user-guide` | `local_path` | `sorc/gsi.fd` | `sorc/gsi_enkf.fd` |
| `global-workflow-rst` | `local_path` | `supported_repos/global-workflow_develop/docs` | `docs` |
| `cice` | `local_path` | `sorc/ufs_model.fd/CICE` | `sorc/ufs_model.fd/CICE-interface/CICE` |
| `mom6` | `local_path` | `sorc/ufs_model.fd/MOM6` | `sorc/ufs_model.fd/MOM6-interface/MOM6` |
| `cdeps` | `local_path` | `sorc/ufs_model.fd/CDEPS` | `sorc/ufs_model.fd/CDEPS-interface/CDEPS` |
| `cmeps` | `local_path` | `sorc/ufs_model.fd/CMEPS` | `sorc/ufs_model.fd/CMEPS-interface/CMEPS` |
| all 12 with `local_path` | `min_files` | absent | per-source floor |

The four coupled-model corrections come from `sorc/ufs_model.fd/.gitmodules`,
which maps those submodules to `<NAME>-interface/<NAME>` paths. Verified
populated on `global-workflow_develop`: CICE 967 files / 87 doc files, MOM6
830 / 45, CDEPS 162 / 25, CMEPS 147 / 15. `WW3` and `GOCART` are top-level in
that `.gitmodules` and their existing manifest paths are already correct.

**These fixes add no unique content.** An earlier draft of this document claimed
171 previously-unreachable doc files; that was wrong, and gate 5d disproved it —
the unique resolved set stayed at 1,562. Those files already fall inside
`ufs-weather-model`'s `sorc/ufs_model.fd` subtree, so the whole-subtree rglob was
picking them up regardless of the four stale paths.

The fixes are still required, for two reasons that are not content volume:
the tightened validator (Gate 5e-c) fails on unresolvable paths, so the stale
values now block; and correct paths mean files are **attributed** to the source
that owns them rather than to `ufs-weather-model`.

Attribution is worth recording as a Phase 2 refinement, not a defect. Where a
source's `local_path` is nested inside another submodule (the coupled-model
paths under `sorc/ufs_model.fd`, and plain directories such as `docs`), the
superproject tree does not enumerate inside the submodule, so the probe resolves
the path as a plain directory and `build_provenance` stamps the
**worktree-root (superproject) HEAD uniformly** — deterministically the same SHA
for every such file, not the nearest submodule's SHA. Verified on
`global-workflow_develop`: those files carry the worktree HEAD `6703c697…`
rather than the CICE / MOM6 / icepack submodule SHAs. Top-level submodule
sources (`ufs_utils.fd`, `gdas.cd`, `gsi_enkf.fd`, …) are enumerated by the
superproject tree and are stamped with their own submodule HEAD.

This is a sufficient repo-level drift signal, not a loss. The consistency gate
verifies every submodule is **at-pin** at ingest time (confirmed:
`git submodule status` at both the superproject and `sorc/ufs_model.fd` levels
shows no `+`, `-`, or `U` markers), so the superproject commit fully pins every
submodule — any submodule pointer bump changes the superproject SHA, and an
off-pin local checkout is caught by the pin check (`submodule_off_pin`) rather
than needing to be encoded in the stamp. Requirement 3.1's wording, "the commit
SHA of the containing repo **or** submodule", already permits the containing-repo
(superproject) reading, so uniform parent-SHA stamping is a valid Phase 1 choice.
A Phase 2 refinement could stamp the nearest owning submodule's SHA for
finer-grained, submodule-level drift; because `resolved_path` always records the
specific file, that refinement is recoverable later. It is not a Phase 1 blocker.

Floors: `cice` 500, `mom6` 500, `cdeps` 100, `cmeps` 100.

Suggested floors from the audit: `ufs-weather-model` 500, `jedi-docs` 500,
`pyioda` 500, `ww3-wiki` 200, `ufs-utils` 200, `gsi-user-guide` 200,
`global-workflow-rst` 10, `gocart` 50, and `cice` / `mom6` / `cdeps` / `cmeps`
50 each — those four currently sit at 0 files and will correctly report
`path_empty`.

## Run procedure

```bash
cd /mnt/mdc-mcp-rag/eib-mcp-rag-server

export DB_BACKEND=aws
export AWS_REGION=us-east-1
export OPENSEARCH_ENDPOINT=https://vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com
export NEPTUNE_ENDPOINT=https://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182
export MCP_EMBEDDING_PROFILE=titan1024
export MCP_WORKFLOW_MOUNT=/mnt/mdc-mcp-rag/eib-mcp-rag-server/.pw_workflow_mount

# 1. validate
python3.12 mcp_server_python/scripts/validate_manifest_paths.py --tenant gw

# 2. dry run — review the printed source set before proceeding
python3.12 mcp_server_python/scripts/ingest_documentation_v8.py \
  --tenant gw --mode full --dry-run

# 3. write run — backgrounded, polled
nohup python3.12 mcp_server_python/scripts/ingest_documentation_v8.py \
  --tenant gw --mode full --delay 0.5 \
  > logs/doc_ingest_$(date +%Y%m%dT%H%M%S).log 2>&1 &
```

`--tiers` is deliberately omitted: this ingester does not read it.

### Task 7b — Node crawler, one tier per invocation

```bash
# tiers: tier1_critical(6) tier2_workflow(5) tier3_models(22) tier4_build(15) tier5_standards(6)
nohup python3.12 mcp_server_node/scripts/ingest_documentation_v8.py \
  --tiers tier1_critical \
  --model titan1024 \
  --collection mdc-workflow-docs-titan1024 \
  --delay 1.0 \
  > logs/crawl_tier1_$(date +%Y%m%dT%H%M%S).log 2>&1 &
```

**`--model titan1024` is mandatory, not redundant with `MCP_EMBEDDING_PROFILE`.**
`aws_backend.get_vector_client()` wires the Bedrock embedding provider only when
the `--model` argv flag is present and non-`mpnet768`; it does **not** read
`MCP_EMBEDDING_PROFILE`. `ingest_documentation_v7` calls `collection.add(...)`
without explicit embeddings, so with no provider wired `_bulk_index` writes
`"embedding": []` — vectorless rows straight into the serving index. The env var
alone drives the collection name and banner but not the embedder.

`--collection mdc-workflow-docs-titan1024` targets the serving index (Gate 1).
Verified: `_to_index()` passes that name through unchanged.

**Guard for every tier**: count documents lacking an `embedding` field before and
after. The expected steady-state value is the reference-row count (references
carry `embedding: None` by design). If it rises, the tier wrote vectorless rows —
stop and do not run the remaining tiers.

```bash
# vectorless-row census (must not increase across a tier)
# body: {"query":{"bool":{"must_not":[{"exists":{"field":"embedding"}}]}}}
```

## Gates — do not write past these

### Gate 1: target index must be the serving index

The Node crawler names collections with the v8 scheme
(`global-workflow-docs-v8-0-0-<profile>`, confirmed by its dry-run banner). The
Python side uses `resolve_collection_name(domain="workflow-docs", scope="shared")`
which yields the `mdc-` scheme. **AWS's 16 indices are all `mdc-*`; there is no
`global-workflow-docs-*` index on AWS.**

Consequence if unchecked: the crawler creates a new index, embeds ~46 sources
into it at full Bedrock cost, and `search_documentation` returns exactly what it
returned before, because the server never queries that name.

Before any crawler write run, confirm the resolved target name appears in
`get_knowledge_base_status`. If it does not, either align the crawler's collection
name to the serving index or add an explicit target override. Do not proceed on
the assumption that a new index will be picked up.

**Resolved 2026-08-05 by gate 5c.** The mismatch was confirmed live: the Python
ingester resolves `mdc-workflow-docs-titan1024` (exists, 20,155 docs, serving);
the crawler resolves `global-workflow-docs-v8-0-0-titan1024` (does not exist on
AWS). Decision: add an explicit `--collection` target override to the crawler and
use it for this run. The crawler's default naming is left unchanged so COTS —
which holds the `global-workflow-docs-v8-*` collections and is not reachable from
the AWS dev host to verify — is unaffected. Unifying the two naming schemes is a
follow-up, not part of this spec.

### Gate 2: mapping must be knn_vector before first write

If a target index does not exist, OpenSearch auto-creates it with dynamic
mapping and types the embedding field as `float`, not `knn_vector`. Mapping type
cannot be changed on a live index. This is Gap I, already paid for once on the
`gw_v17_*` indices (see steering file 12).

Any index that will receive writes SHALL be confirmed to exist with a
`knn_vector` embedding field, or pre-created with the correct mapping, before the
write run.

### Gate 3: allowlist must not lose content

The scoping change replaces "everything" with an allowlist, so it can
under-include. Before the write run, print the set of files the old walker would
have taken but the new resolver excludes, and review it for anything doc-like
(unusual extensions, extension-less READMEs, notebooks, generated HTML). Losing
indexed content is as much a new gap as never having had it.

### Gate 4: dedupe registry must not be poisoned

`SHAIndex.register` keys on `(collection, sha)`. If a write run targets the wrong
collection, the registry records that SHA as ingested there, and a later correct
run will treat the content as a duplicate and write only a reference document.
Verify Gates 1 and 2 before writing, or a mis-targeted run costs more than the
wasted embeddings — it makes the correct run look complete when it is not.

## Verification

- `validate_manifest_paths.py` exits 0 after the manifest edits.
- Dry run reports a documentation file count in the low thousands, not ~17,000
  (Requirement 1.6). If it reports ~17,000 the scoping change did not take.
- Dry run shows all 12 `local_path` sources as `disk / ok` after the 5e-a path
  fixes, including `gsi-user-guide` and the four coupled-model sources. (An
  earlier draft predicted `needs_crawl / path_empty` for the four; that
  prediction was based on the stale manifest paths and no longer applies.)
- Post-run, fetch a written document and confirm `source_kind`, `commit_sha`,
  `embedding_profile`, and `dimension` are present.
- `get_knowledge_base_status` shows the shared `workflow-docs` count changed as
  expected; `list_all_sources --include_gaps` shows refreshed `last_ingested`.

## Rollback

Writes are SHA-keyed upserts into the shared `workflow-docs` collection. If the
scoping change is wrong and source files land in the docs index, the recovery is
a delete-by-query on `source_kind=disk` plus a re-run — which is only possible
because provenance is being stamped. Land Requirement 3 before Requirement 1's
write run, not after.
