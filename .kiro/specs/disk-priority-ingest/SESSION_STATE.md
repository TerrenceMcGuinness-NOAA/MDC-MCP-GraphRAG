# disk-priority-ingest — SESSION STATE / RESTART HANDOFF

**Saved**: 2026-08-06 ~00:50 UTC (connectivity loss expected)
**Branch**: `develop` (note: NOT `develop_aws`)
**Nothing committed.** No background jobs in flight (verified `pgrep` — none running).

---

## Where we are

Tasks **1, 2, 3, 4, 5, 5b, 5c, 5d, 5e, 6, 7, 8 are DONE**.
Task **7b is BLOCKED** on a design/reality mismatch (details below). Do not run it
until the decision below is made.

| Task | State | Evidence |
|---|---|---|
| 1 `_ingest_provenance.py` | DONE (+`source_name` added) | 7 unit tests pass |
| 2 `_ingest_sources.py` | DONE | 17 unit tests pass |
| 3 manifest + validator | DONE | validator rc=0 for gw |
| 4 wire into ingester | DONE | dry run 12 disk / 45 needs_crawl / 2235 |
| 5 regression guard | DONE | 4 tests pass (2063→2235 < 5000, no code exts) |
| 5b crawler profile unfreeze | DONE | both directions verified via real dry-run |
| 5c Gate 1 (index names) | RESOLVED | `--collection` override added |
| 5d Gate 3 (allowlist loss) | RESOLVED | accepted, no action (581 doc-like excluded) |
| 5e (a/b/c/d) | DONE | see below |
| 6 validate + dry run | DONE | rc=0, all 12 `disk/ok` |
| 7 Python write run | DONE ×2 | reports `gw_20260805T234531`, `gw_20260806T003723` |
| 8 verification | DONE | counts + provenance + CICE attribution |
| **7b Node crawler tiers** | **BLOCKED — NOT RUN** | see BLOCKER |
| 8 (post-7b) final backfill | NOT RUN | depends on 7b |

---

## BLOCKER — Task 7b would corrupt the live serving index

Read from source (`mcp_server_node/scripts/aws_backend.py`, `get_vector_client`):

```python
elif not embedding_function:
    p.add_argument("--model", default="mpnet768")
    a, _ = p.parse_known_args()
    if a.model != "mpnet768":        # keys ONLY on --model, NOT MCP_EMBEDDING_PROFILE
        client.set_embedding_function(provider.embed)
```

`ingest_documentation_v7.py` (~line 234) calls
`self.collection.add(ids=…, documents=…, metadatas=…)` with **no embeddings**, so
`_auto_embed` returns nothing and `_bulk_index` writes `"embedding": []`.

**Consequence** of design.md's 7b procedure as written (`MCP_EMBEDDING_PROFILE=titan1024`
+ `--collection mdc-workflow-docs-titan1024`, no `--model`): thousands of rows with
**EMPTY embeddings** into the live serving index (20,421 real docs) — unsearchable
junk, worse than the Gate 1 mismatch the override was meant to fix.

**Gate 1 itself is fine** — verified `_to_index()` passes the name through:
- `mdc-workflow-docs-titan1024` → `mdc-workflow-docs-titan1024`
- `global-workflow-docs-v8-0-0-titan1024` → `mdc-workflow-docs-titan1024`

**Proposed fix (no code change):** add **`--model titan1024`** to the 7b invocation.
That flag wires the Bedrock Titan provider; the crawler's own lines 26-28 already
scan `--model`, so the collection name/banner are identical.
design.md's 7b procedure needs that flag added.

**AWAITING USER DECISION.** Proposed plan on restart: run tier1_critical only,
verify a written doc has a populated 1024-dim embedding, then continue tiers.

---

## Open finding — 262 canonical embeds lack `source_name`

- 1,694 disk docs total; **1,432 have `source_name`**, **262 do not**; 0 of those 262
  are references → they are the 262 `doc_` embeds from the FIRST Task 7 run.
- Cause: once a SHA is registered, the ingester writes `ref_<sha>` and never
  upserts `doc_<sha>`. Reference rows got `source_name`; canonical embeds didn't.
- Recovery options (NOT done): targeted metadata update, or clear those 262
  registry keys and re-embed (~262 Bedrock calls).

## Open finding — `last_ingested` not refreshed by Python ingester

`backfill_manifest_status.py` filters `source_type == url_crawl` and counts by
`metadata.source.keyword == <source_name>`, but the ingester stamps
`metadata.source` = full file path. Dry-run showed ALL disk sources unchanged at
`2026-05-20`. **Deliberately NOT modified** (shared script; now a Phase 2 item in
requirements.md). Pre-7b backfill was skipped per user instruction.

---

## Files changed (all uncommitted)

**New (untracked):**
```
mcp_server_python/scripts/_ingest_provenance.py
mcp_server_python/scripts/_ingest_sources.py
mcp_server_python/scripts/validate_manifest_paths.py
mcp_server_python/tests/unit/test_ingest_provenance.py
mcp_server_python/tests/unit/test_ingest_sources.py
mcp_server_python/tests/unit/test_ingest_doc_regression.py
mcp_server_python/scripts/ingestion_reports/gw_20260805T234531.json
mcp_server_python/scripts/ingestion_reports/gw_20260806T003723.json
.kiro/specs/disk-priority-ingest/   (spec dir itself untracked)
```

**Modified:**
```
mcp_server_python/scripts/ingest_documentation_v8.py   (manifest-driven set, dry-run gate, provenance)
mcp_server_python/src/config/unified_manifest.json     (12 local_path/min_files edits)
mcp_server_node/scripts/ingest_documentation_v8.py     (line 25 env profile + --collection override)
.kiro/specs/disk-priority-ingest/design.md             (attribution note corrected)
```
NOTE: `.kiro/settings/mcp.json`, `mcp_server_python/Dockerfile`, and the
`supported_repos/*` entries were modified by OTHER work — **not** this spec. Do not
stage them with this spec's changes.

Manifest edits: `gsi-user-guide`→`sorc/gsi_enkf.fd`(200); `global-workflow-rst`→`docs`(10);
`cice`→`CICE-interface/CICE`(500); `mom6`→`MOM6-interface/MOM6`(500);
`cdeps`→`CDEPS-interface/CDEPS`(100); `cmeps`→`CMEPS-interface/CMEPS`(100);
plus floors ufs-utils 200, ufs-weather-model 500, jedi-docs 500, pyioda 500,
ww3-wiki 200, gocart 50.

---

## Live AWS state (as of save)

- `mdc-workflow-docs-titan1024`: **20,421** docs (was 20,155 pre-Task-7; +266)
- `mdc-content-sha-registry`: **53,016** (was 52,754; +262 = the new embeds)
- Run 1 (`gw_20260805T234531`): 2,234 processed / **262 embeds** / **1,972 refs** / 88.3% dedupe
- Run 2 (`gw_20260806T003723`): 2,234 processed / **0 embeds** / **2,234 refs** / 100% dedupe
- Provenance verified: all 7 fields present+populated on sampled docs
- `source_name` aggregation: ufs-weather-model 490, pyioda 382, gsi-user-guide 176,
  ufs-utils 125, cice 82, mom6 45, ww3-wiki 40, global-workflow-rst 29, cdeps 25,
  gocart 23, cmeps 15

**Submodule question SETTLED:** worktree HEAD = `6703c6973039aafc08f049fb593675f9feb6a91c`,
which is what `build_provenance` stamps uniformly for nested paths. 0 off-pin/dirty
across 10 superproject + 13 `ufs_model.fd` submodules → superproject SHA is a
sufficient repo-level drift signal. design.md corrected to say uniform-parent-SHA.

---

## Environment block (required for every run)

```bash
cd /mnt/mdc-mcp-rag/eib-mcp-rag-server
export DB_BACKEND=aws
export AWS_REGION=us-east-1
export OPENSEARCH_ENDPOINT=https://vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com
export NEPTUNE_ENDPOINT=https://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182
export MCP_EMBEDDING_PROFILE=titan1024
export MCP_WORKFLOW_MOUNT=/mnt/mdc-mcp-rag/eib-mcp-rag-server/.pw_workflow_mount
```
NOTE: mount is `/mnt/mdc-mcp-rag/...` on this host (design.md writes `/mdc-mcp-rag/...`).

## Reproduce / verify commands

```bash
# tests (28 pass)
cd mcp_server_python && python3.12 -m pytest tests/unit/test_ingest_provenance.py \
  tests/unit/test_ingest_sources.py tests/unit/test_ingest_doc_regression.py -q

# validator (expect rc=0, 12 disk/ok)
python3.12 mcp_server_python/scripts/validate_manifest_paths.py --tenant gw

# dry run (expect 12 disk / 45 needs_crawl / 2235, mdc-workflow-docs-titan1024, 1024-dim)
python3.12 mcp_server_python/scripts/ingest_documentation_v8.py --tenant gw --mode full --dry-run
```

## Task 7b command IF approved (note the added --model)

```bash
# one tier per invocation: tier1_critical tier2_workflow tier3_models tier4_build tier5_standards
nohup python3.12 mcp_server_node/scripts/ingest_documentation_v8.py \
  --tiers tier1_critical --model titan1024 \
  --collection mdc-workflow-docs-titan1024 --delay 1.0 \
  > logs/crawl_tier1_$(date +%Y%m%dT%H%M%S).log 2>&1 &
```
Tier sizes: tier1_critical 6, tier2_workflow 5, tier3_models 22, tier4_build 15,
tier5_standards 6. Known-zero set expected to fail, not blocking:
`cmeps`, `ecmwf-atlas`, `jedi-academy-2021-06`, `jedi-academy-2021-10`, `ufs-srweather-app`.

---

## Standing rules for this spec

1. Every symbol in design.md was read from source — if something differs, **STOP and
   report**, do not substitute.
2. **Shell exit codes are unreliable** here (often 1 on success) — judge from output only.
3. Anything >25 min must be **backgrounded and polled** (shell caps at 1800s).
4. **Do not commit without asking.**
5. Do not run Task 7b without explicit approval (it is a vector-store write).

## First actions on restart

1. Re-read `.kiro/specs/disk-priority-ingest/{requirements,design,tasks}.md` — the user
   updates them between sessions.
2. Re-read this file.
3. Confirm no stale ingester running: `pgrep -af ingest_documentation`.
4. Report the 7b blocker + the two open findings; get the `--model titan1024` decision.
