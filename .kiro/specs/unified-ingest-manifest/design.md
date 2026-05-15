# Design Document: Unified Ingest Manifest

## Overview

This design extends the SPOT protocol from a URL-only `documentation_sources.json` to a unified manifest (`unified_manifest.json`) that registers all 7 source types feeding the knowledge base. The implementation adds a `ManifestRegistry` class, a `GapDetector` component, a new `list_all_sources` MCP tool, and a bootstrap generation script — all within the existing `mcp_server_python/` package.

## Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│  MCP Server (src/mcp_server.py)                                 │
│                                                                 │
│  ┌──────────────────┐   ┌──────────────────────────────────┐   │
│  │ ManifestRegistry │◄──│ src/config/unified_manifest.json  │   │
│  │  (in-memory)     │   │ (or MCP_UNIFIED_MANIFEST_PATH)   │   │
│  └────────┬─────────┘   └──────────────────────────────────┘   │
│           │                                                     │
│  ┌────────▼─────────┐   ┌──────────────────────────────────┐   │
│  │   GapDetector    │──►│ OpenSearchAdapter.health_check()  │   │
│  └────────┬─────────┘   └──────────────────────────────────┘   │
│           │                                                     │
│  ┌────────▼─────────────────────────────────────────────────┐   │
│  │ MCP Tools                                                │   │
│  │  • list_all_sources (NEW)                                │   │
│  │  • list_ingested_urls (UPDATED — reads from registry)    │   │
│  │  • get_ingested_urls_array (UPDATED — reads from registry│   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  CLI Scripts (scripts/)                                          │
│  • generate_unified_manifest.py  — bootstrap from current state │
│  • validate_manifest.py          — schema + index validation    │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Boot**: `mcp_server.py` → `ManifestRegistry.load()` → reads `unified_manifest.json` (or falls back to legacy `documentation_sources.json`)
2. **Tool call** (`list_all_sources`): → `ManifestRegistry.get_sources(filters)` → optionally `GapDetector.detect(registry, vector_db)` → render markdown
3. **Tool call** (`list_ingested_urls`): → `ManifestRegistry.get_url_sources()` → render (backward-compatible)
4. **Ingestion complete**: ingestion script → `ManifestRegistry.update_source(name, last_ingested, doc_count)` → writes back to JSON

## Data Models

### Unified Manifest JSON Schema

```json
{
  "version": "9.0.0",
  "description": "Unified ingest manifest — all knowledge base sources",
  "generated_at": "2026-05-15T18:00:00Z",
  "sources": [
    {
      "name": "global-workflow",
      "source_type": "url_crawl",
      "collection_target": "global-workflow-docs-v8-0-0",
      "embedding_profile": "titan1024",
      "enabled": true,
      "description": "Main global-workflow documentation",
      "last_ingested": "2026-04-14T21:02:29Z",
      "ingestion_script": "scripts/ingest_documentation.py",
      "doc_count": 234,
      "url": "https://global-workflow.readthedocs.io/en/latest/",
      "crawl_type": "readthedocs",
      "max_pages": 150,
      "tier": "tier1_critical"
    },
    {
      "name": "global-workflow-rst",
      "source_type": "on_disk_submodule",
      "collection_target": "global-workflow-docs-v8-0-0",
      "embedding_profile": "titan1024",
      "enabled": true,
      "description": "Local .rst docs from global-workflow submodule",
      "last_ingested": "2026-05-14T18:00:00Z",
      "ingestion_script": "scripts/ingest_local_docs.py",
      "doc_count": 1759,
      "local_path": "supported_repos/global-workflow/docs",
      "file_patterns": ["**/*.rst"],
      "parser": "rst_sphinx"
    },
    {
      "name": "fortran-code-context",
      "source_type": "code_parse",
      "collection_target": "code-with-context-v8-0-0",
      "embedding_profile": "titan1024",
      "enabled": true,
      "description": "Fortran subroutines/functions with context",
      "last_ingested": "2026-04-14T21:41:48Z",
      "ingestion_script": "scripts/ingest_code_context.py",
      "doc_count": 77613,
      "root_path": "supported_repos/global-workflow/sorc",
      "languages": ["fortran"],
      "chunk_strategy": "function_boundary"
    }
  ]
}
```

### Python Dataclasses

```python
# src/manifest/models.py

@dataclass(frozen=True)
class SourceEntry:
    """Common fields for all source types."""
    name: str
    source_type: SourceType  # Enum
    collection_target: str
    embedding_profile: str
    enabled: bool
    description: str
    last_ingested: str | None  # ISO 8601
    ingestion_script: str | None
    doc_count: int
    # Type-specific fields stored as a dict
    type_fields: dict[str, Any] = field(default_factory=dict)

class SourceType(str, Enum):
    URL_CRAWL = "url_crawl"
    ON_DISK_SUBMODULE = "on_disk_submodule"
    CODE_PARSE = "code_parse"
    CONFIG_PARSE = "config_parse"
    STANDARDS = "standards"
    COMMUNITY_SUMMARY = "community_summary"
    JJOB_DOCS = "jjob_docs"

@dataclass
class UnifiedManifest:
    version: str
    description: str
    generated_at: str | None
    sources: list[SourceEntry]
```

## Module Design

### `src/manifest/__init__.py`

Exports: `ManifestRegistry`, `GapDetector`, `SourceEntry`, `SourceType`, `UnifiedManifest`

### `src/manifest/registry.py` — ManifestRegistry

```python
class ManifestRegistry:
    """In-memory registry loaded from unified_manifest.json."""

    def __init__(self, manifest: UnifiedManifest):
        self._manifest = manifest
        self._by_name: dict[str, SourceEntry] = {s.name: s for s in manifest.sources}

    @classmethod
    def load(cls, path: Path | None = None) -> "ManifestRegistry":
        """Load from path, env var, or fallback to legacy."""

    def get_sources(
        self,
        *,
        source_type: SourceType | None = None,
        collection: str | None = None,
        enabled_only: bool = True,
    ) -> list[SourceEntry]:
        """Filter sources by type and/or collection."""

    def get_url_sources(self) -> list[SourceEntry]:
        """Backward-compatible: return only url_crawl entries."""

    def get_legacy_format(self) -> dict[str, Any]:
        """Return the documentation_sources.json-compatible dict."""

    def update_source(
        self, name: str, *, last_ingested: str, doc_count: int
    ) -> None:
        """Update metadata after successful ingestion."""

    def save(self, path: Path | None = None) -> None:
        """Persist current state back to JSON."""

    @property
    def version(self) -> str: ...

    @property
    def total_sources(self) -> int: ...

    @property
    def enabled_sources(self) -> int: ...
```

### `src/manifest/gap_detector.py` — GapDetector

```python
@dataclass
class GapReport:
    collection: str
    declared_count: int
    actual_count: int
    coverage_pct: float
    stale_sources: list[str]
    never_ingested: list[str]
    status: Literal["healthy", "gap", "stale", "missing"]

class GapDetector:
    """Compares manifest declarations against OpenSearch reality."""

    COVERAGE_THRESHOLD: float = 0.90
    STALE_DAYS: int = 30

    async def detect(
        self,
        registry: ManifestRegistry,
        vector_db: Any,
    ) -> list[GapReport]:
        """Run gap detection across all collections."""

    async def _get_actual_counts(
        self, vector_db: Any
    ) -> dict[str, int]:
        """Query OpenSearch cat.indices for real doc counts."""
```

### `src/manifest/loader.py` — Loading Logic

```python
def resolve_manifest_path() -> Path | None:
    """Resolve path: env var → bundled → legacy fallback → None."""

def load_manifest(path: Path | None = None) -> ManifestRegistry:
    """Load and validate the manifest, with fallback chain."""

def _migrate_legacy(legacy_path: Path) -> UnifiedManifest:
    """Convert documentation_sources.json to UnifiedManifest shape."""
```

### Tool Registration Changes

#### `src/tools/semantic_search.py` — Updated `register()`

The `register()` function gains a `manifest_registry` parameter:

```python
def register(
    mcp: FastMCP,
    data: Any = None,
    *,
    manifest_registry: ManifestRegistry | None = None,  # NEW
    documentation_sources_path: ...,  # PRESERVED for fallback
    ...
) -> None:
```

#### New tool: `list_all_sources`

```python
@mcp.tool(name="list_all_sources", description="...")
async def list_all_sources(
    source_type: Literal[...] | None = None,
    collection: str | None = None,
    format: Literal["summary", "detailed"] = "summary",
    include_gaps: bool = False,
) -> str:
```

#### Updated: `list_ingested_urls`

Internal implementation changes from reading `documentation_sources.json` directly to calling `registry.get_url_sources()`. External interface unchanged.

#### Updated: `get_ingested_urls_array`

Same pattern — reads from registry instead of file. External interface unchanged.

## File Layout

```
mcp_server_python/
├── src/
│   ├── config/
│   │   ├── unified_manifest.json          # NEW — the manifest file
│   │   └── documentation_sources.json     # PRESERVED — legacy fallback
│   ├── manifest/                          # NEW package
│   │   ├── __init__.py
│   │   ├── models.py                      # SourceEntry, SourceType, UnifiedManifest
│   │   ├── registry.py                    # ManifestRegistry
│   │   ├── gap_detector.py                # GapDetector, GapReport
│   │   └── loader.py                      # resolve_manifest_path, load_manifest
│   └── tools/
│       └── semantic_search.py             # MODIFIED — uses ManifestRegistry
├── scripts/
│   ├── generate_unified_manifest.py       # NEW — bootstrap script
│   └── validate_manifest.py              # NEW — schema validator
└── tests/
    └── unit/
        ├── test_manifest_registry.py      # NEW
        ├── test_gap_detector.py           # NEW
        └── test_manifest_loader.py        # NEW
```

## Integration Points

### Server Boot (`src/mcp_server.py`)

```python
# In initialize():
from src.manifest.loader import load_manifest

registry = load_manifest()  # handles env var, fallback, logging
# Pass to semantic_search.register(mcp, data, manifest_registry=registry)
```

### Ingestion Script Post-Hook

Each ingestion script calls a shared helper after successful completion:

```python
# At end of any ingest_*.py script:
from src.manifest.registry import ManifestRegistry

registry = ManifestRegistry.load()
registry.update_source(
    "fortran-code-context",
    last_ingested=datetime.now(timezone.utc).isoformat(),
    doc_count=len(ingested_docs),
)
registry.save()
```

## Validation Rules

The `validate_manifest.py` script checks:

1. **Schema**: All required common fields present on every entry
2. **Type fields**: Type-specific required fields present per `source_type`
3. **Collection targets**: Each `collection_target` resolves to a known OpenSearch index via `resolve_index(collection, embedding_profile)`
4. **Uniqueness**: No duplicate `name` values
5. **Embedding profiles**: Each `embedding_profile` is a registered profile in `EmbeddingModelRegistry`

## Migration Strategy

1. Run `generate_unified_manifest.py` to bootstrap from current state (queries OpenSearch, scans ingestion scripts)
2. Manual review + enrichment of generated manifest (add descriptions, verify ingestion_script paths)
3. Deploy updated server image with `ManifestRegistry` loader
4. Existing tools continue working via fallback chain — zero downtime
5. New `list_all_sources` tool becomes available immediately

## Requirements Traceability

| Requirement | Components |
|-------------|-----------|
| R1: Unified Manifest Schema | `models.py` (dataclasses), `unified_manifest.json` (file) |
| R2: Backward Compatibility | `registry.get_url_sources()`, `registry.get_legacy_format()`, `loader._migrate_legacy()` |
| R3: list_all_sources Tool | `semantic_search.py` new tool registration |
| R4: Updated Existing Tools | `semantic_search.py` internal refactor to use registry |
| R5: Per-Source Metadata | `SourceEntry.last_ingested`, `.ingestion_script`, `.doc_count`; `registry.update_source()` |
| R6: Gap Detection | `gap_detector.py` (`GapDetector`, `GapReport`) |
| R7: Generation & Validation | `scripts/generate_unified_manifest.py`, `scripts/validate_manifest.py` |
| R8: File Location & Loading | `loader.py` (`resolve_manifest_path`, `load_manifest`, fallback chain) |

## Components and Interfaces

### ManifestRegistry (src/manifest/registry.py)

**Interface:**
- `load(path: Path | None = None) -> ManifestRegistry` — class method, loads from disk
- `get_sources(*, source_type, collection, enabled_only) -> list[SourceEntry]` — filtered query
- `get_url_sources() -> list[SourceEntry]` — backward-compatible URL-only view
- `get_legacy_format() -> dict[str, Any]` — returns `documentation_sources.json`-shaped dict
- `update_source(name, *, last_ingested, doc_count) -> None` — post-ingestion metadata update
- `save(path: Path | None = None) -> None` — persist to disk

**Consumed by:** `semantic_search.py` tools, `mcp_server.py` boot, ingestion scripts

### GapDetector (src/manifest/gap_detector.py)

**Interface:**
- `detect(registry: ManifestRegistry, vector_db: Any) -> list[GapReport]` — async, queries OpenSearch

**Consumed by:** `list_all_sources` tool (when `include_gaps=True`)

### Loader (src/manifest/loader.py)

**Interface:**
- `resolve_manifest_path() -> Path | None` — env var → bundled → None
- `load_manifest(path: Path | None = None) -> ManifestRegistry` — full load with fallback
- `_migrate_legacy(legacy_path: Path) -> UnifiedManifest` — converts old format

**Consumed by:** `mcp_server.py` at boot time

### MCP Tool: list_all_sources

**Interface (MCP schema):**
- `source_type: str | None` — filter by SourceType enum value
- `collection: str | None` — filter by collection_target
- `format: "summary" | "detailed"` — output verbosity
- `include_gaps: bool` — trigger gap detection

**Returns:** Markdown string with source listing and optional gap report

## Correctness Properties

### Property 1: Manifest Round-Trip Fidelity
`load()` → `save()` → `load()` produces an identical `UnifiedManifest` object (no data loss on serialization). Field ordering in JSON output is deterministic (sorted keys).
**Validates: Requirements 1.1, 1.2, 8.1**

### Property 2: Legacy Equivalence
`registry.get_legacy_format()` output is structurally identical to the current `documentation_sources.json` for all `url_crawl` entries — same field names, same value types, same ordering.
**Validates: Requirements 2.1, 2.3, 2.4**

### Property 3: Filter Completeness
`get_sources(source_type=X)` returns exactly the set of entries where `entry.source_type == X` and `entry.enabled == True` (when `enabled_only=True`). No entries are dropped or duplicated.
**Validates: Requirements 3.2, 3.3**

### Property 4: Gap Detection Monotonicity
If actual doc count ≥ declared doc count for all collections, `GapDetector.detect()` returns zero gap reports with status `"healthy"`.
**Validates: Requirements 6.1, 6.2**

### Property 5: Fallback Safety
If `unified_manifest.json` is missing or malformed, the server boots successfully with legacy-only sources, all existing tools function, and a WARNING is logged.
**Validates: Requirements 8.3, 8.5**

## Error Handling

| Scenario | Behavior |
|----------|----------|
| `unified_manifest.json` missing | Fall back to `documentation_sources.json`; log WARNING |
| `unified_manifest.json` invalid JSON | Fall back to legacy; log ERROR with parse details |
| Source_Entry missing required field | `validate_manifest.py` reports error; `load_manifest()` skips entry with WARNING |
| `collection_target` doesn't resolve to known index | Validation warning; entry still loaded (may be a future index) |
| OpenSearch unreachable during gap detection | `GapDetector.detect()` returns empty list; tool reports "gap detection unavailable" |
| `update_source()` called with unknown name | Raises `KeyError`; ingestion script logs and continues |
| Concurrent `save()` calls | Last-writer-wins (acceptable for single-runtime deployment) |

## Testing Strategy

### Unit Tests (`tests/unit/test_manifest_*.py`)

- **test_manifest_registry.py** (~20 tests):
  - Load from valid JSON, verify all fields parsed
  - `get_sources` with each filter combination
  - `get_url_sources` returns only `url_crawl` entries
  - `get_legacy_format` matches expected structure
  - `update_source` modifies in-memory state
  - `save` + `load` round-trip preserves data
  - Empty manifest (no sources) handled gracefully

- **test_gap_detector.py** (~12 tests):
  - All collections at 100% coverage → no gaps
  - One collection at 85% → gap reported
  - Source with `last_ingested` > 30 days → stale
  - Source with `last_ingested` = null → never ingested
  - OpenSearch unreachable → empty report, no crash
  - Per-collection summary math is correct

- **test_manifest_loader.py** (~10 tests):
  - Env var path takes precedence
  - Bundled path used when env var unset
  - Legacy fallback when unified missing
  - Malformed JSON → fallback + error log
  - Legacy migration produces valid UnifiedManifest

### Integration Tests (gated on `RUN_INTEGRATION=1`)

- Load manifest → call `list_all_sources` → verify response includes all source types
- Call `list_ingested_urls` → verify backward-compatible output
- Call `list_all_sources(include_gaps=True)` with live OpenSearch → verify gap report
