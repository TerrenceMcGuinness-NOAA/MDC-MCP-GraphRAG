# Requirements Document — RAG & Graph Drift Remediation (August 2026)

## Introduction

The Aug 5, 2026 parity analysis (`Deep-Parity-Analysis-AWS-vs-COTS-2026-08-05`)
identified 77-day stale documentation embeddings on both platforms, a 29,561-doc
code-context gap on COTS, missing regex-fallback Fortran nodes on AWS, and no
quality baseline on either platform. This spec orchestrates the ingestion runs
needed to close the drift and establish measurable baselines.

Reference: `supported_repos/MDC-MCP-GraphRAG.wiki/Deep-Parity-Analysis-AWS-vs-COTS-2026-08-05.md`

> **Revision 2 (2026-08-05).** Amended after a failed Kiro CLI run. Three
> corrections to the original premises, all verified against live `--help`:
> (a) URL crawling is a **Node**-script operation — the Python
> `ingest_documentation_v8.py` walks the repo worktree and does not crawl;
> (b) there is no `--fallback` flag on the Fortran ingester because the regex
> fallback is unconditional as of `[8.33.0]`, so Req 3 is a re-run with a
> verify-or-escalate outcome; (c) `benchmark_runner.py` writes to S3, not to the
> `quality_metrics.jsonl` that `get_quality_metrics` reads, so Req 5 cannot make
> that tool report results. Req 2 is deferred pending the Gemini embedding
> evaluation.

## Requirements

### Requirement 1: Re-crawl stale documentation (both platforms)

All 44 stale URL-crawl sources have `last_ingested: 2026-05-20` or earlier.
Upstream ReadTheDocs and GitHub Pages sites have evolved; the embeddings are stale.

#### Acceptance Criteria

1. `mcp_server_node/scripts/ingest_documentation_v8.py` SHALL run against the
   AWS backend (`DB_BACKEND=aws`, `MCP_EMBEDDING_PROFILE=titan1024`), once per
   tier, refreshing all enabled URL-crawl sources. The Node script owns URL
   crawling; the Python script of the same name walks the repo worktree instead.
2. After completion, `list_all_sources --include_gaps` SHALL show `last_ingested`
   dates of 2026-08-xx for at least 40 of 44 stale sources (some may still fail
   due to upstream issues — document those as known).
3. Sources that returned 0 docs previously (`cmeps`, `nceplibs-sfcio`,
   `ufs-srweather-app`, `kokkos-api`, `ecmwf-atlas`, `jedi-academy-*`) SHALL be
   attempted; failures recorded but not blocking.
4. The COTS mpnet768 docs collection SHALL be refreshed separately with
   `MCP_EMBEDDING_PROFILE=mpnet768` and `DB_BACKEND=cots`, from the Parallel
   Works host (not reachable from the AWS dev host).

### Requirement 2: Close the COTS code-context gap (29,561 docs) — DEFERRED

COTS has 60,574 code-context docs (mpnet768 only). AWS has 90,135 (titan1024).
The delta is the titan1024 embedding of the same code that COTS embedded in
mpnet768.

#### Acceptance Criteria

**Deferred by decision, 2026-08-05.** The gap is real in a counting sense but is
not a functional deficit: COTS serves mpnet768 locally with no external
dependency, which is the point of that deployment. Forcing titan1024 onto COTS
would make query embedding depend on Bedrock.

More importantly the question is being superseded. A Google API key for
`gemini-embedding-2` (multimodal, text + image in one vector space) is expected
next week, which reframes the decision from "backfill titan1024" to "choose the
COTS primary profile." Revisit then.

#### Acceptance Criteria

1. This requirement SHALL take no action in the current pass.
2. The rationale above SHALL be recorded so the deferral is a decision rather
   than an omission.
3. Re-evaluation SHALL be scoped against
   `Gemini-Embedding-Provider-Evaluation-and-Key-Request` rather than against
   titan1024 parity.

### Requirement 3: Load regex-fallback Fortran output into Neptune

COTS Neo4j has 76,860 more Fortran nodes than AWS Neptune due to the Phase F
regex-fallback parser. AWS has the deeper AST relationships but misses entities
from files fparser2 rejects (~15% of the Fortran tree).

#### Acceptance Criteria

1. `ingest_fortran_graph_v8.py --tenant gw --mode full` SHALL run against
   Neptune (`DB_BACKEND=aws`). There is no `--fallback` flag: the regex fallback
   is unconditional as of `[8.33.0]` (`fortran-parse-fallback`, `7c77ffd`), so a
   plain full re-run is the correct invocation.
2. `FortranSubroutine` count SHALL be captured before and after via
   `get_knowledge_base_status`.
3. Existing relationships produced by fparser2 SHALL NOT be duplicated or
   corrupted (nodes merge on a composite key, so re-runs are idempotent).
4. IF the count does not rise materially from 27,941 toward the COTS figure
   (~80,745), THEN the fallback is not present in this script and this
   requirement SHALL be reclassified as a code-port spec rather than an
   operational task, with both counts recorded as evidence.

### Requirement 4: Populate COTS v17 tenant vector content

COTS has only 2,610 v17 docs vs AWS's 56,876. The code-context and full
workflow-docs collections are empty on COTS for gw_v17.

#### Acceptance Criteria

1. `ingest_code_v8.py --tenant gw_v17 --model mpnet768 --mode full` SHALL run
   against COTS ChromaDB.
2. `ingest_documentation_v8.py --tenant gw_v17 --model mpnet768` SHALL run
   against COTS ChromaDB (repo-local docs from the v17 worktree).
3. After completion, COTS `get_knowledge_base_status(tenant_id="gw_v17")` SHALL
   report >= 25,000 total vector documents.

### Requirement 5: Establish quality baselines on both platforms

Neither platform has run `benchmark_runner.py`. Without a baseline, embedding
drift and retrieval regressions are undetectable.

#### Acceptance Criteria

1. `mcp_server_node/scripts/benchmark_runner.py` SHALL run on AWS with the
   required positional ground-truth file
   (`mcp_server_node/scripts/config/benchmark_ground_truth.json`) and
   `--search-modes vector hybrid bm25`.
2. The same SHALL run on COTS from the Parallel Works host with
   `MCP_EMBEDDING_PROFILE=mpnet768`.
3. Each run SHALL produce a markdown metrics table and an S3 report object under
   `benchmark-reports/<timestamp>.json`.
4. `get_quality_metrics` SHALL NOT be expected to return results: the runner
   writes to S3, while the tool reads
   `sdd_framework/execution_state/quality_metrics.jsonl`. Bridging the two is a
   separate code task (tracked as deferred item D2), not part of this
   requirement.
5. The markdown tables SHALL be captured in the verification report for
   regression tracking.

### Requirement 6: Verify parity improvements

After all ingestion runs complete, a re-run of the parity analysis tools should
show the drift has narrowed.

#### Acceptance Criteria

1. AWS `check_knowledge_integrity` Coverage Gap SHALL be re-evaluated now that
   `/mnt/workflow` is mounted (runtime v36). Whether it moves from `[SKIP]` to
   `[OK]` depends on which path the check inspects; the observed result SHALL be
   recorded either way rather than asserted in advance.
2. AWS `mcp_health_check(functional=True)` SHALL report >= 10/11 pass.
3. AWS Stale Embeddings SHALL improve from 12/12 sampled docs flagged toward a
   majority-fresh sample; the exact ratio SHALL be recorded.
4. A follow-up parity report SHALL be generated and pushed to the
   MDC-MCP-GraphRAG wiki, linked from `Home.md`.
5. The report SHALL state plainly which requirements were completed, deferred,
   or reclassified, including any that failed.
