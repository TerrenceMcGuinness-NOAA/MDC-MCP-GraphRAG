# Phase 57 — Manifest Status Writeback & Gap Report Fixes

**Version**: 1.0.0  
**Created**: 2026-05-18  
**Status**: ready  
**Estimated effort**: 2–3 hours  

---

## Problem Statement

`list_all_sources` (and the gap table it embeds) is the primary operator
view of knowledge-base health. It has three concrete bugs that make it
misleading:

### Bug 1 — `last_ingested` is always `null` (manifest never written back)

Every entry in `unified_manifest.json` has `"last_ingested": null`.
The `ManifestRegistry.update_source()` + `save()` methods exist and are
correct, but **no ingest script calls them**. The gap detector therefore
flags every enabled source as `never_ingested`, even sources whose docs
are demonstrably present in OpenSearch (e.g. 27,222 docs in
`mdc-workflow-docs-titan1024`).

**Root cause**: `mcp_server_node/scripts/ingest_documentation_v8.py` (and
the other ingest scripts) complete their work and exit without touching
the manifest. There is no post-ingest writeback hook.

**Fix**: Add a `update_manifest_after_ingest()` helper to
`mcp_server_python/src/manifest/registry.py` (or a new
`scripts/update_manifest_status.py` utility) that:
1. Loads the manifest from `MCP_UNIFIED_MANIFEST_PATH`.
2. Calls `registry.update_source(name, last_ingested=now_iso, doc_count=n)`.
3. Calls `registry.save()`.

The ingest scripts call this after a successful run. For the immediate
fix, a **standalone backfill script** (`scripts/backfill_manifest_status.py`)
queries OpenSearch for actual doc counts per index, maps them back to
source names via `resolve_index`, and writes `last_ingested` to the
manifest as the image build timestamp (a conservative lower bound).

---

### Bug 2 — Gap table `status` column always shows `missing`

The `GapDetector._lookup_actual_count()` correctly calls `resolve_index`
to translate `global-workflow-docs-v8-0-0` → `mdc-workflow-docs-titan1024`,
but `_get_actual_counts()` returns the raw `indices_detail` dict from
`health_check(deep=True)`. The OpenSearch adapter's `health_check` method
returns index names in the form `mdc-workflow-docs-titan1024` — which
**does** match the `resolve_index` output.

The actual failure is that `health_check(deep=True)` is called on the
`data.vector_db` adapter inside `_tool_list_all_sources`, but the
`indices_detail` key is only populated when `deep=True` is passed. The
call at line ~1274 of `semantic_search.py` passes `deep=True` correctly,
but the `actual_counts` dict is keyed by the raw OpenSearch response
field names. Tracing the OpenSearch adapter's `health_check` response
shape is needed to confirm whether the key is `indices_detail` or
something else (e.g. `index_stats`, `per_index`).

**Fix**: Add a debug log in `GapDetector._get_actual_counts()` that
prints the raw `health` dict keys when `actual_counts` resolves to `{}`.
Then align the key name with what the adapter actually returns. One-line
fix once the key name is confirmed.

---

### Bug 3 — `doc_count` in manifest is static hand-entered data

The `doc_count` field in `unified_manifest.json` was set when the
manifest was generated and never updated. It does not reflect the actual
number of documents ingested. This makes the "Declared" column in the
gap table unreliable.

**Fix**: The backfill script from Bug 1 also updates `doc_count` from
the live OpenSearch counts. Going forward, ingest scripts write back
both fields on completion.

---

## Fixes Catalogue

| # | File | Change | Effort |
|---|------|--------|--------|
| F1 | `mcp_server_python/src/manifest/registry.py` | Add `update_source_from_ingest(name, doc_count)` convenience wrapper that sets `last_ingested=utcnow()` automatically | 10 min |
| F2 | `scripts/backfill_manifest_status.py` (new) | Query OpenSearch for live doc counts, map to source names, write `last_ingested` + `doc_count` back to manifest | 45 min |
| F3 | `mcp_server_python/src/manifest/gap_detector.py` | Add debug logging in `_get_actual_counts()` to expose the raw health dict; fix the `indices_detail` key name if mismatched | 15 min |
| F4 | `mcp_server_python/src/tools/semantic_search.py` | Confirm `actual_counts` is populated before gap render; add fallback message if empty | 10 min |
| F5 | `mcp_server_python/src/config/unified_manifest.json` | Run backfill script to populate `last_ingested` + `doc_count` for all sources with live data | 5 min (script run) |
| F6 | `CHANGELOG.md` | Add `[8.23.0]` entry | 5 min |

---

## Steps

### Step 1 — Diagnose the `indices_detail` key mismatch (F3)

Add a single `log.debug` line in `GapDetector._get_actual_counts()` after
the `health_check` call to print `list(health.keys())` and
`list(detail.keys()) if detail else "no detail key"`. Call
`list_all_sources(include_gaps=True)` and read the server log to confirm
the exact key name the OpenSearch adapter uses.

**Test**: `list_all_sources(include_gaps=True)` — gap table `status`
column should change from `missing` to `healthy` or `gap` for collections
with real data.

---

### Step 2 — Fix the `indices_detail` key (F3 + F4)

Update `_get_actual_counts()` to use the confirmed key name. If the
adapter returns a nested structure, flatten it to `{index_name: count}`.
Add a guard in `_tool_list_all_sources` that logs a warning when
`actual_counts` is empty after a successful health check.

**Test**: `list_all_sources(include_gaps=True)` — `global-workflow-docs-v8-0-0`
should show `actual_count=27222`, `coverage_pct≈95.2%`, `status=missing`
(correct — data is present but `last_ingested` is still null at this point).

---

### Step 3 — Add `update_source_from_ingest` convenience wrapper (F1)

In `ManifestRegistry`, add:

```python
def update_source_from_ingest(self, name: str, doc_count: int) -> None:
    """Convenience wrapper: sets last_ingested=utcnow() + doc_count."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    self.update_source(name, last_ingested=now, doc_count=doc_count)
```

No new tests required — `update_source` is already tested; this is a
one-liner wrapper.

---

### Step 4 — Write and run the backfill script (F2 + F5)

Create `scripts/backfill_manifest_status.py`:

```
usage: python scripts/backfill_manifest_status.py \
    --manifest mcp_server_python/src/config/unified_manifest.json \
    --opensearch-endpoint $OPENSEARCH_ENDPOINT \
    --region us-east-1 \
    [--dry-run]
```

Logic:
1. Load manifest via `ManifestRegistry.load(path)`.
2. Call OpenSearch `_cat/indices?format=json` to get live doc counts.
3. For each enabled source, call `resolve_index(collection, profile)` to
   get the physical index name, look up the count.
4. Call `registry.update_source_from_ingest(name, doc_count=count)`.
5. Call `registry.save()` (unless `--dry-run`).

**Test**: Run with `--dry-run` first, inspect output. Then run live.
Verify with `list_all_sources(include_gaps=True)` — `last_ingested`
should now show a real timestamp for all sources with data, `status`
should flip from `missing` to `healthy` or `stale`.

---

### Step 5 — Update CHANGELOG (F6)

Add `[8.23.0]` entry documenting all three bugs and their fixes.

**Test**: `get_server_info` returns updated version.

---

## Acceptance Criteria

- `list_all_sources(include_gaps=True)` gap table shows correct `status`
  (`healthy`/`gap`/`stale`) — not `missing` for collections with real data.
- `last_ingested` is non-null for all sources that have docs in OpenSearch.
- `doc_count` in the manifest matches (within 5%) the live OpenSearch count.
- No regression in existing unit tests (`pytest mcp_server_python/tests/`).

---

## Files Touched

**Created**:
- `scripts/backfill_manifest_status.py`

**Modified**:
- `mcp_server_python/src/manifest/registry.py`
- `mcp_server_python/src/manifest/gap_detector.py`
- `mcp_server_python/src/tools/semantic_search.py`
- `mcp_server_python/src/config/unified_manifest.json`
- `CHANGELOG.md`
