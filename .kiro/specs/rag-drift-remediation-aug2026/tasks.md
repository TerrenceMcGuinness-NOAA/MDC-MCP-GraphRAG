# Task List — RAG & Graph Drift Remediation (August 2026)

> **Revision 2.** Commands corrected against live `--help`; tasks split by host
> capability. Every command lives in `design.md` — run it verbatim. If a command
> is rejected for an unrecognized argument, **stop and report**; do not guess a
> corrected form.

## Phase A — AWS, runnable from the EC2 dev host

- [ ] A1. **Dry-run the URL crawler** (Req 1)
  `--dry-run --tiers tier1_critical` against the Node crawler. Confirms source
  resolution and the embedding profile before any writes. No data written.

- [ ] A2. **URL re-crawl, tier1_critical** (Req 1)
  Verify: `list_all_sources --include_gaps` shows `2026-08-05` for tier-1 sources.

- [ ] A3. **URL re-crawl, tier2_workflow** (Req 1)

- [ ] A4. **URL re-crawl, tier3_models** (Req 1)
  Largest tier. Expect the known-zero sources (`cmeps`, `ecmwf-atlas`,
  `jedi-academy-2021-06`, `jedi-academy-2021-10`, `ufs-srweather-app`) to fail
  again — record them, do not treat as blocking.

- [ ] A5. **URL re-crawl, tier4_build** (Req 1)

- [ ] A6. **URL re-crawl, tier5_standards** (Req 1)

- [ ] A7. **Fortran graph re-ingest** (Req 3)
  Record `FortranSubroutine` count before and after via
  `get_knowledge_base_status`. If the count does not move materially, the regex
  fallback is not in this script: record both numbers, mark Req 3 as needing a
  code-port spec, and stop this task.

- [ ] A8. **AWS quality baseline** (Req 5)
  Positional ground-truth file is required. Expect `get_quality_metrics` to
  still report no results — the runner writes to S3, not `quality_metrics.jsonl`.
  Capture the markdown table in the report instead.

- [ ] A9. **AWS verification report** (Req 6)
  Re-run `mcp_health_check(deep, detailed, functional)`,
  `get_knowledge_base_status`, `check_knowledge_integrity`,
  `list_all_sources --include_gaps` on `agentcore-mcp-rag`. Write a before/after
  page into `supported_repos/MDC-MCP-GraphRAG.wiki/` and link it from `Home.md`
  under Health, Parity & Status Reports. Commit and push the wiki only.

## Phase B — COTS, requires the Parallel Works host

Not runnable from the EC2 dev host: `localhost:8000` (ChromaDB) and
`bolt://localhost:7687` (Neo4j) are not here.

- [ ] B1. **COTS URL re-crawl** (Req 1.4)
  Same Node crawler, `DB_BACKEND=cots`, `MCP_EMBEDDING_PROFILE=mpnet768`.

- [ ] B2. **COTS v17 tenant ingest** (Req 4)
  `ingest_code_v8.py --tenant gw_v17 --mode full` plus the repo-local docs
  ingester, both with `MCP_EMBEDDING_PROFILE=mpnet768`.

- [ ] B3. **COTS quality baseline** (Req 5)

## Deferred

- [ ] D1. **COTS code-context embedding strategy** (Req 2)
  Deferred to next week. Superseded by the Gemini embedding-2 evaluation: the
  question is no longer "backfill titan1024" but "adopt a multimodal primary for
  COTS." Revisit when the Google API key lands. See
  `Gemini-Embedding-Provider-Evaluation-and-Key-Request` on the wiki.

- [ ] D2. **Wire benchmark output into `quality_metrics.jsonl`**
  `benchmark_runner.py` writes S3 + markdown; `get_quality_metrics` reads
  `sdd_framework/execution_state/quality_metrics.jsonl`. Nothing bridges them,
  so the tool reports "no benchmark results found" even after a successful run.
  Small code task, own spec.
