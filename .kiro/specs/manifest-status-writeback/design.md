# Design Document: Manifest Status Writeback

## Overview

This feature closes three operational bugs in the unified manifest system: `last_ingested` is always null, `doc_count` values are stale hand-entered numbers, and the gap detector misreads the OpenSearch adapter's health-check response keys. The fix adds a convenience writeback API on `ManifestRegistry`, a standalone backfill script that queries OpenSearch for live counts, and corrects the key-handling logic in `GapDetector._get_actual_counts()`.

## Architecture

The feature touches four components in a linear data-flow:

```
OpenSearch cluster
    │
    ▼  (_cat/indices?format=json)
backfill_manifest_status.py
    │
    ▼  (update_source_from_ingest)
ManifestRegistry
    │
    ▼  (save → unified_manifest.json)
GapDetector / list_all_sources tool
```

No new dependencies are introduced. The backfill script reuses the existing `ManifestRegistry` and `resolve_index` from `src.config.aws_config`. OpenSearch access uses `requests` with AWS SigV4 signing via `requests_aws4auth` (already in the dependency tree for the OpenSearch adapter).

## Components and Interfaces

### Component 1: `ManifestRegistry.update_source_from_ingest`

**Location:** `mcp_server_python/src/manifest/registry.py`

A one-liner convenience method that delegates to the existing `update_source()`:

```python
from datetime import datetime, timezone

def update_source_from_ingest(self, name: str, doc_count: int) -> None:
    """Stamp last_ingested=now and doc_count after a successful ingest.

    Raises KeyError if *name* is not a registered source.
    """
    self.update_source(
        name,
        last_ingested=datetime.now(timezone.utc).isoformat(),
        doc_count=doc_count,
    )
```

**Interface:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | `str` | Source name as declared in `unified_manifest.json` |
| `doc_count` | `int` | Live document count from OpenSearch |

**Returns:** `None`  
**Raises:** `KeyError` if `name` is not in the registry.  
**Side effects:** Mutates the in-memory registry (sets `last_ingested` and `doc_count`). Does NOT call `save()` — the caller is responsible for persistence.

**Rationale:** Ingest scripts should not need to know about ISO formatting or the `update_source` kwargs. A single call with `(name, count)` is the minimal API surface.

### Component 2: `scripts/backfill_manifest_status.py`

**Location:** `mcp_server_python/scripts/backfill_manifest_status.py`

A standalone CLI script that:

1. Parses `--manifest`, `--opensearch-endpoint`, `--region`, and `--dry-run` arguments.
2. Queries `GET {endpoint}/_cat/indices?format=json` with AWS SigV4 signing.
3. Builds a reverse map from physical index names back to manifest source names by iterating all sources and calling `resolve_index(source.collection_target, source.embedding_profile)`.
4. For each source whose resolved physical index appears in the live data with `doc_count > 0`, calls `registry.update_source_from_ingest(source.name, live_count)`.
5. In `--dry-run` mode, prints proposed changes to stdout without calling `registry.save()`.
6. Otherwise, calls `registry.save()` to persist.

```python
#!/usr/bin/env python3
"""Backfill manifest last_ingested + doc_count from live OpenSearch indices."""

import argparse
import json
import logging
import sys
from pathlib import Path

import requests
from requests_aws4auth import AWS4Auth
import boto3

# Add the src package to the path so we can import manifest modules.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from manifest.registry import ManifestRegistry
from config.aws_config import resolve_index

log = logging.getLogger(__name__)


def build_reverse_index_map(registry: ManifestRegistry) -> dict[str, str]:
    """Map physical OpenSearch index name → manifest source name.

    Iterates all sources, resolves each to its physical index via
    resolve_index, and builds the reverse lookup. First-match wins
    when multiple sources map to the same physical index.
    """
    reverse: dict[str, str] = {}
    for entry in registry.get_sources(enabled_only=False):
        physical = resolve_index(
            entry.collection_target, entry.embedding_profile
        )
        # Only map if resolve_index actually translated (not passthrough).
        if physical != entry.collection_target or physical.startswith("mdc-"):
            reverse.setdefault(physical, entry.name)
    return reverse


def fetch_live_counts(endpoint: str, region: str) -> dict[str, int]:
    """Query _cat/indices and return {index_name: doc_count}.

    Uses AWS SigV4 signing for authenticated access to the
    OpenSearch cluster.
    """
    credentials = boto3.Session().get_credentials().get_frozen_credentials()
    auth = AWS4Auth(
        credentials.access_key,
        credentials.secret_key,
        region,
        "es",
        session_token=credentials.token,
    )
    url = f"https://{endpoint}/_cat/indices?format=json"
    resp = requests.get(url, auth=auth, timeout=30)
    resp.raise_for_status()

    counts: dict[str, int] = {}
    for idx in resp.json():
        name = idx.get("index", "")
        if name.startswith("."):
            continue
        doc_count = int(idx.get("docs.count") or 0)
        counts[name] = doc_count
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill manifest status from live OpenSearch indices."
    )
    parser.add_argument(
        "--manifest", required=True, type=Path,
        help="Path to unified_manifest.json",
    )
    parser.add_argument(
        "--opensearch-endpoint", required=True,
        help="OpenSearch cluster hostname (without https://)",
    )
    parser.add_argument(
        "--region", default="us-east-1",
        help="AWS region for SigV4 signing",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print proposed changes without modifying the manifest",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(message)s",
    )

    registry = ManifestRegistry.load(args.manifest)
    reverse_map = build_reverse_index_map(registry)
    live_counts = fetch_live_counts(args.opensearch_endpoint, args.region)

    updated = 0
    for index_name, doc_count in sorted(live_counts.items()):
        source_name = reverse_map.get(index_name)
        if source_name is None or doc_count == 0:
            continue

        if args.dry_run:
            print(f"  [dry-run] {source_name} <- {index_name} ({doc_count} docs)")
        else:
            registry.update_source_from_ingest(source_name, doc_count)
            log.info("Updated %s <- %s (%d docs)", source_name, index_name, doc_count)
        updated += 1

    if not args.dry_run and updated > 0:
        registry.save()
        log.info("Saved manifest (%d sources updated)", updated)
    elif not args.dry_run:
        log.info("No sources matched - manifest unchanged")


if __name__ == "__main__":
    main()
```

### Component 3: `GapDetector._get_actual_counts` Fix

**Location:** `mcp_server_python/src/manifest/gap_detector.py`

The current implementation only checks for `indices_detail`. The OpenSearch adapter always returns this key, but the value may be empty if the `cat.indices` call fails silently, or a different adapter shape may use alternative keys. The fix:

1. Logs the top-level keys of the health dict at DEBUG level for diagnostics.
2. Checks `indices_detail` first (primary path).
3. Falls back to constructing the dict from alternative key names (`index_details`, `index_counts`, `per_index_counts`).
4. Logs a WARNING when the result is empty despite a successful health check, listing the available keys.

```python
async def _get_actual_counts(
    self, vector_db: Any
) -> dict[str, int] | None:
    """Return {index_name: doc_count} from the adapter health check."""
    try:
        health = await vector_db.health_check(deep=True)
    except Exception as exc:
        log.warning(
            "GapDetector._get_actual_counts: health_check failed: %s", exc,
        )
        return None

    if not isinstance(health, dict):
        log.warning(
            "GapDetector._get_actual_counts: health_check returned %s, "
            "expected dict", type(health).__name__,
        )
        return {}

    # Diagnostic: log available keys so operators can debug key mismatches.
    log.debug(
        "GapDetector._get_actual_counts: health dict keys: %s",
        list(health.keys()),
    )

    # Primary path: indices_detail is the canonical key from OpenSearchAdapter.
    detail = health.get("indices_detail")
    if isinstance(detail, dict) and detail:
        return {str(k): int(v) for k, v in detail.items()}

    # Fallback: some adapter versions or wrappers may return the data
    # under alternative key names.
    for alt_key in ("index_details", "index_counts", "per_index_counts"):
        alt = health.get(alt_key)
        if isinstance(alt, dict) and alt:
            log.debug(
                "GapDetector._get_actual_counts: using fallback key %r",
                alt_key,
            )
            return {str(k): int(v) for k, v in alt.items()}

    # Warn when we got a successful response but no index data.
    if health.get("status") in ("healthy", "degraded"):
        log.warning(
            "GapDetector._get_actual_counts: health check succeeded but "
            "no index counts found. Available keys: %s",
            list(health.keys()),
        )

    return {}
```

### Component 4: `_tool_list_all_sources` Warning Log

**Location:** `mcp_server_python/src/tools/semantic_search.py`

Add a warning log after the `actual_counts` resolution block when the dict is empty despite a successful health check:

```python
actual_counts: dict[str, int] = {}
if data is not None and getattr(data, "vector_db", None) is not None:
    try:
        health = await data.vector_db.health_check(deep=True)
        detail = health.get("indices_detail") or {}
        if isinstance(detail, dict):
            actual_counts = {str(k): int(v) for k, v in detail.items()}
        if not actual_counts and isinstance(health, dict):
            log.warning(
                "list_all_sources: health_check succeeded but actual_counts "
                "is empty. Health keys: %s", list(health.keys()),
            )
    except Exception as exc:
        log.debug("list_all_sources: health_check failed: %s", exc)
```

And in the gap detection rendering section, when `include_gaps` is true and gap reports are empty with empty actual_counts, render a notice:

```python
if include_gaps:
    # ... existing gap detection block ...
    if not reports and not actual_counts:
        lines.append(
            "_⚠️ Actual index counts unavailable — gap status may be "
            "inaccurate. Run `backfill_manifest_status.py` or check "
            "OpenSearch connectivity._"
        )
```

## Data Models

No new data models are introduced. The existing `SourceEntry` dataclass already has `last_ingested: str | None` and `doc_count: int` fields. The `update_source_from_ingest` method writes to these existing fields via the established `update_source()` → replacement-entry pattern.

### Health Check Response Shape (Reference)

The `OpenSearchAdapter.health_check(deep=True)` returns:

```python
{
    "status": "healthy" | "degraded" | "unhealthy",
    "connected": bool,
    "endpoint": str,
    "metrics": dict,
    "cluster_status": "green" | "yellow" | "red",
    "indices": ["mdc-code-context-titan1024", ...],       # list of names
    "indices_detail": {"mdc-code-context-titan1024": 42000, ...},  # canonical
    "total_documents": int,
}
```

The gap detector's primary lookup key is `indices_detail`. The fallback keys (`index_details`, `index_counts`, `per_index_counts`) handle potential adapter wrappers or future refactors.

## Error Handling

| Scenario | Behavior |
|----------|----------|
| `update_source_from_ingest` with unknown name | Raises `KeyError` with descriptive message |
| Backfill script cannot reach OpenSearch | `requests` raises `ConnectionError`; script exits with non-zero status |
| Backfill script gets HTTP 4xx/5xx | `resp.raise_for_status()` raises `HTTPError`; script exits with traceback |
| Gap detector health_check raises | Returns `None` (short-circuits to empty report list) |
| Gap detector health_check returns non-dict | Returns `{}` with WARNING log |
| Gap detector gets empty counts from healthy cluster | Returns `{}` with WARNING log listing available keys |
| `list_all_sources` gets empty actual_counts | Logs WARNING; renders notice in gap section |

## Testing Strategy

### Unit Tests

- **`update_source_from_ingest`**: Verify correct field updates with known source names, verify `KeyError` for unknown names.
- **`build_reverse_index_map`**: Verify mapping against known production index configurations.
- **`_get_actual_counts`**: Verify extraction from `indices_detail`, fallback keys, and empty/missing key scenarios.
- **`_tool_list_all_sources` warning**: Verify warning log and notice rendering when actual_counts is empty.
- **Backfill CLI**: Verify argument parsing, dry-run non-modification, and save-on-update behavior with mocked OpenSearch responses.

### Property Tests

Property-based tests validate the universal invariants identified in the Correctness Properties section below. Each property test runs a minimum of 100 iterations with randomly generated inputs (source names, doc counts, health-check response shapes, manifest configurations).

### Integration Tests

- End-to-end backfill against a local OpenSearch instance (if available in CI) to verify SigV4 signing and `_cat/indices` parsing.

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: update_source_from_ingest sets both fields atomically

*For any* valid source name in the registry and *for any* non-negative integer `doc_count`, calling `update_source_from_ingest(name, doc_count)` SHALL result in the source's `doc_count` field equaling the provided value AND the source's `last_ingested` field being a valid ISO-8601 UTC timestamp within 2 seconds of the call time.

**Validates: Requirements 1.2, 1.3**

### Property 2: Unknown source name raises KeyError

*For any* string that is not a registered source name in the manifest, calling `update_source_from_ingest(name, doc_count)` SHALL raise a `KeyError` whose message contains the unknown source name, and the registry state SHALL remain unchanged.

**Validates: Requirements 1.4**

### Property 3: Dry-run is non-destructive

*For any* manifest file and *for any* set of live OpenSearch index data, executing the backfill script with `--dry-run` SHALL leave the manifest file byte-identical to its state before execution.

**Validates: Requirements 2.4, 2.8**

### Property 4: Backfill propagates live counts to all matched sources

*For any* manifest containing sources whose `resolve_index(collection_target, embedding_profile)` maps to a physical index present in the live OpenSearch data with `doc_count > 0`, after backfill execution (without `--dry-run`) the manifest SHALL contain `doc_count` equal to the live count AND `last_ingested` non-null for each matched source.

**Validates: Requirements 2.7, 5.1, 5.2, 5.3**

### Property 5: Gap detector extracts counts from any recognized key

*For any* health-check response dict that contains per-index document counts under either `indices_detail`, `index_details`, `index_counts`, or `per_index_counts`, the `_get_actual_counts` method SHALL return a dictionary with the same index names as keys and the same integer counts as values.

**Validates: Requirements 3.2, 3.4**

### Property 6: Reverse index map is consistent with resolve_index

*For any* source entry in the manifest, `build_reverse_index_map` SHALL map `resolve_index(entry.collection_target, entry.embedding_profile)` back to `entry.name`, provided no earlier source already claimed that physical index.

**Validates: Requirements 2.6**
