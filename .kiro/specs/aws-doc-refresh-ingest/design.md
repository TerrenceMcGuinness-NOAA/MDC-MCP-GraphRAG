# Design Document

## Overview

Run a full documentation re-ingest against the AWS backend to refresh the 44
stale URL-crawl sources, attempt the 14 never-ingested sources, and resolve the
two integrity WARNs (Stale Embeddings, Path Consistency).

## Procedure

```bash
# Environment (on the EC2 dev host)
export DB_BACKEND=aws
export OPENSEARCH_ENDPOINT=https://vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com
export NEPTUNE_ENDPOINT=https://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182
export AWS_REGION=us-east-1
export MCP_EMBEDDING_PROFILE=titan1024

# Run (detached for 2-4h runtime)
nohup python3.12 mcp_server_python/scripts/ingest_documentation_v8.py \
  --mode full --tiers all --delay 0.5 \
  > logs/aws_doc_refresh_$(date +%Y%m%dT%H%M%S).log 2>&1 &

# Monitor
tail -f logs/aws_doc_refresh_*.log
```

## How it works

The v8 documentation ingester:
1. Iterates all enabled URL-crawl + on_disk_submodule sources from the manifest.
2. For each source: crawls the URL (or reads from disk), extracts text chunks.
3. For each chunk: computes SHA-256 → checks the `mdc-content-sha-registry`.
   - SHA exists (unchanged) → skip embedding (cost-free).
   - SHA new/changed → embed via Bedrock Titan → write to OpenSearch.
4. Updates `last_ingested` + `doc_count` in the manifest status registry.

This means: unchanged documentation costs nothing; only new/modified pages
trigger Bedrock InvokeModel calls (~$2 total for the full corpus).

## The 14 never-ingested sources

These sources have `last_ingested: null` in the manifest status. Root causes
(documented in prior phases):

| Source | Likely cause |
|---|---|
| `rocoto` | URL may not be RTD-hosted; possibly needs `path_prefix` |
| `cmeps` | CESM coupling framework; URL possibly restructured |
| `nceplibs-nemsio`, `-sfcio`, `-sigio` | Small libraries; URLs may be GitHub READMEs only |
| `kokkos-api` | External project; URL may not be a Sphinx site |
| `google-shell-style`, `pep8`, `numpy-docstrings` | Coding standards; non-standard site layouts |
| `ufs-srweather-app` | RTD-hosted; previously failed (path_prefix issue?) |
| `global-workflow-rst` | on_disk_submodule; `docs/` dir must be present |
| `ecmwf-atlas` | External project; URL may need path_prefix |
| `jedi-academy-2021-10`, `-2021-06` | Workshop materials; possibly archived/moved |

The ingest run will attempt each; failures get logged with HTTP status/error. We
document the outcome and optionally disable truly-dead sources.

## Verification

- `list_all_sources --include_gaps` → 0 stale; ≤14 "never" (document which are dead)
- `check_knowledge_integrity` → Stale Embeddings `[OK]`, Path Consistency `[OK]`
- `get_knowledge_base_status` → `mdc-workflow-docs-titan1024` count ≥ 20,155

## Cost and risk

- **Cost**: ~$2 Titan embed (only new/changed docs; unchanged docs dedupe-skip).
- **Runtime**: 2–4 hours (network-bound crawling + rate-limiting delays).
- **Risk**: None. SHA-keyed upsert is idempotent; no deletes; serving index
  remains live throughout. Re-running is always safe.
- **Rollback**: Not needed (append-only), but a pre-run index snapshot could be
  taken via `_snapshot` API if desired.
