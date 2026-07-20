# Requirements Document

## Introduction

The AWS OpenSearch `mdc-workflow-docs-titan1024` serving index has 20,155
documents but should have ~21,248 (manifest declared). 44 of 58 URL-crawl
sources are **stale** (last ingested >30 days ago) and 14 have **never been
ingested**. This staleness triggers two integrity WARNs:

- **Stale Embeddings** — 12/12 sampled docs have embeddings older than the 30-day
  threshold.
- **Path Consistency** — 2/34 sampled docs carry old `supported_repos/global-workflow`
  path prefixes from a pre-Phase-67 ingestion.

A full documentation re-ingest resolves both: the SHA-keyed upsert overwrites stale
docs with fresh metadata (fixing path prefixes) and embeds any new/changed content
(fixing staleness). Unchanged docs skip embedding via the dedupe registry (cost
efficient).

This is the `url-crawl-gap-closure` follow-up (Phase 58 series), now scoped as a
concrete runnable spec.

## Requirements

### Requirement 1: Full documentation re-ingest against AWS backend

#### Acceptance Criteria

1. THE ingest SHALL run `ingest_documentation_v8.py --mode full --tiers all`
   against `DB_BACKEND=aws` (OpenSearch + Bedrock Titan).
2. THE target collection SHALL be `mdc-workflow-docs-titan1024` (the serving
   index; `MCP_EMBEDDING_PROFILE=titan1024`).
3. ALL 58 enabled URL-crawl sources + 1 `on_disk_submodule` source SHALL be
   processed (65 enabled sources less the non-doc types).
4. THE ingester SHALL use SHA-keyed upsert: unchanged docs skip embedding
   (dedupe registry); changed/new docs get embedded + written.

### Requirement 2: Stale sources refreshed

#### Acceptance Criteria

1. AFTER the run, `list_all_sources --include_gaps` SHALL show 0 **stale**
   sources (all `last_ingested` within the current date).
2. ANY of the 14 "never ingested" sources that succeed SHALL show a non-null
   `last_ingested` and a positive `doc_count`.
3. ANY of the 14 that fail (dead URL, rate-limited, unreachable) SHALL be
   **documented** with the failure reason and optionally disabled in the manifest.

### Requirement 3: Integrity WARNs resolved

#### Acceptance Criteria

1. `check_knowledge_integrity` → Stale Embeddings shows `[OK]` (sampled docs
   have embeddings < 30 days old).
2. `check_knowledge_integrity` → Path Consistency shows `[OK]` (0/N sampled docs
   with old path prefixes — fresh docs carry the correct Phase-67 paths).

### Requirement 4: Document count maintained or increased

#### Acceptance Criteria

1. `get_knowledge_base_status` → `mdc-workflow-docs-titan1024` document count ≥
   20,155 (current baseline; should increase toward 21,248).
2. No documents SHALL be deleted (the ingester is append/upsert only).

### Requirement 5: Boundaries and safety

#### Acceptance Criteria

1. No code changes — uses existing ingesters as-is.
2. No graph mutations — documentation is vector-only.
3. The existing serving collection is updated in-place (SHA-keyed upsert is safe
   and idempotent — re-running is always safe).
4. Estimated runtime: 2–4 hours. Estimated cost: ~$2 Titan embed.
5. Can run detached (`nohup`) overnight.
6. No auto-commit or auto-push.
