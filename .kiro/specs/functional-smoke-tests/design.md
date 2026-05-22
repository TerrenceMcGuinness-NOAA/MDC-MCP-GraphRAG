# Technical Design Document

## Overview

This design implements per-tool-module functional validation smoke queries for the Python MCP/RAG server. The implementation adds a shared `smoke_queries.py` module that both the existing `mcp_health_check(functional=True)` tool and a new standalone script consume. Each of the 9 tool modules gets one lightweight query that exercises the real data path (OpenSearch or Neptune) and reports pass/fail/skip with latency.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Invocation Contexts                                │
│                                                                       │
│  ┌──────────────────────┐       ┌──────────────────────────────┐    │
│  │ mcp_health_check     │       │ scripts/smoke_test_tools.py  │    │
│  │ (functional=True)    │       │ (standalone CLI)             │    │
│  └──────────┬───────────┘       └──────────────┬───────────────┘    │
│             │                                   │                    │
│             ▼                                   ▼                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │              src/tools/smoke_queries.py                        │   │
│  │                                                                │   │
│  │  SmokeQueryRegistry                                            │   │
│  │    ├── QUERIES: dict[str, SmokeQueryDef]                       │   │
│  │    └── run_all(data, mcp?) → list[ModuleResult]                │   │
│  │                                                                │   │
│  │  SmokeQueryDef (dataclass)                                     │   │
│  │    ├── module: str                                             │   │
│  │    ├── query_fn: Callable[[DataAccess], Awaitable[bool]]       │   │
│  │    ├── description: str                                        │   │
│  │    └── requires: list[str]  (e.g. ["GITHUB_TOKEN"])            │   │
│  │                                                                │   │
│  │  ModuleResult (dataclass)                                      │   │
│  │    ├── module: str                                             │   │
│  │    ├── status: "pass" | "fail" | "skip"                       │   │
│  │    ├── latency_ms: int                                         │   │
│  │    └── error: str                                              │   │
│  └──────────────────────────────────────────────────────────────┘   │
│             │                                                        │
│             ▼                                                        │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │              Data Access Layer                                  │   │
│  │  UnifiedDataAccess (src/data/unified_data_access.py)           │   │
│  │    ├── vector_db (OpenSearchAdapter)                           │   │
│  │    └── graph_db  (NeptuneAdapter)                              │   │
│  └──────────────────────────────────────────────────────────────┘   │
│             │                          │                             │
│             ▼                          ▼                             │
│  ┌────────────────────┐    ┌────────────────────────┐               │
│  │ OpenSearch          │    │ Neptune                 │               │
│  │ (mdc-workflow-docs  │    │ (105K+ nodes,           │               │
│  │  -titan1024, etc.)  │    │  2.9M+ relationships)   │               │
│  └────────────────────┘    └────────────────────────┘               │
└─────────────────────────────────────────────────────────────────────┘
```

## Components and Interfaces

### 1. SmokeQueryDef (dataclass)

Defines a single module's smoke query.

```python
@dataclass(frozen=True)
class SmokeQueryDef:
    module: str
    description: str
    query_fn: Callable[[Any, Any | None], Awaitable[bool]]
    requires: list[str] = field(default_factory=list)
```

- `module` — one of the 9 module names from `ALL_TOOL_MODULES`
- `description` — human-readable label (e.g. "search_documentation: global workflow forecast")
- `query_fn` — async callable `(data, mcp) -> bool`. Returns `True` on pass, raises on fail.
- `requires` — env vars that must be set for this query to run. If any are missing, the module is skipped.

### 2. ModuleResult (dataclass)

Result of executing one smoke query.

```python
@dataclass
class ModuleResult:
    module: str
    status: Literal["pass", "fail", "skip"]
    latency_ms: int
    error: str = ""
    description: str = ""
```

### 3. SmokeQueryRegistry

Central registry and runner.

```python
class SmokeQueryRegistry:
    QUERIES: dict[str, SmokeQueryDef]  # module_name → definition
    TIMEOUT_MS: int = 2000
    TOTAL_TIMEOUT_MS: int = 30000

    async def run_all(
        self,
        data: Any | None,
        mcp: FastMCP | None = None,
        only: str | None = None,
    ) -> list[ModuleResult]: ...

    async def run_one(
        self,
        name: str,
        data: Any,
        mcp: FastMCP | None = None,
    ) -> ModuleResult: ...
```

**Behaviour:**
- If `data is None`, returns all modules as `skip` with reason "data layer unavailable".
- If `only` is set, runs only that module's query.
- Each query is wrapped in `asyncio.wait_for(timeout=TIMEOUT_MS/1000)`.
- Queries run sequentially (Req 3.4).
- Total elapsed time is tracked; if it exceeds `TOTAL_TIMEOUT_MS`, remaining modules are marked `skip` with "total timeout exceeded".

### 4. Smoke Query Implementations

Each query function follows the same pattern: call the data layer directly (not through the MCP tool surface) to isolate the data-path test from tool-registration concerns.

| Module | Query | Pass Condition | Backend |
|--------|-------|----------------|---------|
| `semantic_search` | `data.vector_db.query("global workflow forecast", index="mdc-workflow-docs-titan1024", k=1)` | ≥1 hit | OpenSearch |
| `code_analysis` | `data.graph_db.query("MATCH (f:File {name:'JGFS_FORECAST'})-[r]->(t) RETURN type(r), t.name LIMIT 3")` | ≥1 row | Neptune |
| `graph_rag` | `data.graph_db.query("MATCH (n {name:'JGFS_FORECAST'})-[r]-(m) RETURN n.name, type(r), m.name LIMIT 5")` | ≥1 row | Neptune |
| `ee2_compliance` | `data.vector_db.query("error handling", index="mdc-ee2-standards-titan1024", k=1)` | ≥1 hit | OpenSearch |
| `operational` | `data.vector_db.query("running forecast on hera", index="mdc-workflow-docs-titan1024", k=1)` | ≥1 hit | OpenSearch |
| `sdd_workflow` | Check `Path(state_dir / "active_session.json").exists()` or `history.jsonl` exists | File exists | Filesystem |
| `workflow_info` | Check `Path(workflow_root / "jobs").is_dir()` | Directory exists | Filesystem |
| `github_tools` | `requires: ["GITHUB_TOKEN"]` — skipped when token absent | N/A (skip) | GitHub API |
| `utility` | Count tools via `mcp.list_tools()` (if mcp provided) or return pass (standalone) | ≥50 tools | In-process |

**Design decision:** Queries hit the data layer directly rather than invoking the MCP tool functions. This isolates the smoke test from tool-level bugs (which are caught by parity tests) and focuses on the "can the backend respond?" question. It also avoids circular dependency (health check calling itself).

### 5. Integration into `utility.py`

The existing placeholder in `_render_health_check`:

```python
if functional:
    lines.append("_Functional tests not yet implemented..._")
```

Becomes:

```python
if functional:
    from src.tools.smoke_queries import SmokeQueryRegistry
    registry = SmokeQueryRegistry()
    results = await registry.run_all(data, mcp=mcp)
    lines.extend(_render_functional_results(results))
```

The `_render_functional_results` helper produces:

```markdown
## Functional Validation

| Module | Status | Latency | Error |
|--------|--------|---------|-------|
| semantic_search | [OK] pass | 142ms | |
| code_analysis | [OK] pass | 89ms | |
| graph_rag | [OK] pass | 112ms | |
| ee2_compliance | [OK] pass | 95ms | |
| operational | [OK] pass | 78ms | |
| sdd_workflow | [OK] pass | 2ms | |
| workflow_info | [OK] pass | 1ms | |
| github_tools | [SKIP] skip | 0ms | GITHUB_TOKEN not set |
| utility | [OK] pass | 5ms | |

**Summary**: 8/9 passed, 0 failed, 1 skipped
```

### 6. Standalone Script (`scripts/smoke_test_tools.py`)

```
Usage:
  python3.12 scripts/smoke_test_tools.py [OPTIONS]

Options:
  --json-only       Output JSON only (no markdown table)
  --module NAME     Run only the named module's smoke query
  --help            Show this help

Environment:
  DB_BACKEND=aws
  OPENSEARCH_ENDPOINT=https://vpc-mdc-mcp-rag-search-...
  NEPTUNE_ENDPOINT=https://mdc-mcp-graprag-neptune-1...
  AWS_REGION=us-east-1
  MCP_WORKFLOW_ROOT=/app/supported_repos/global-workflow  (or local path)

Exit codes:
  0  All non-skipped modules passed
  1  One or more modules failed
  2  Missing required environment variables
```

**Initialization flow:**
1. Parse args, validate env vars (exit 2 if missing).
2. Call `create_data_access(config)` from `src/data/backend_selector.py`.
3. Instantiate `SmokeQueryRegistry()`.
4. Call `registry.run_all(data, mcp=None, only=args.module)`.
5. Render JSON to stdout. If not `--json-only`, render markdown table to stderr.
6. Exit 0 or 1.

**JSON output schema:**

```json
{
  "timestamp": "2026-05-22T14:30:00Z",
  "total_duration_ms": 1247,
  "summary": {
    "passed": 8,
    "failed": 0,
    "skipped": 1,
    "total": 9
  },
  "results": [
    {
      "module": "semantic_search",
      "status": "pass",
      "latency_ms": 142,
      "error": "",
      "description": "search_documentation: global workflow forecast"
    }
  ]
}
```

## Data Models

### ModuleResult (repeated for clarity)

| Field | Type | Description |
|-------|------|-------------|
| `module` | `str` | Module name from `ALL_TOOL_MODULES` |
| `status` | `Literal["pass", "fail", "skip"]` | Outcome |
| `latency_ms` | `int` | Wall-clock time in milliseconds |
| `error` | `str` | Error message (empty on pass/skip-by-design) |
| `description` | `str` | Human-readable query description |

### SmokeQueryDef (repeated for clarity)

| Field | Type | Description |
|-------|------|-------------|
| `module` | `str` | Target module name |
| `description` | `str` | What the query does |
| `query_fn` | `Callable` | `async (data, mcp) -> bool` |
| `requires` | `list[str]` | Env vars required (skip if missing) |

## Error Handling

| Scenario | Behaviour |
|----------|-----------|
| Data layer unavailable (`data is None`) | All modules marked `skip`, reason: "data layer unavailable" |
| Individual query raises exception | Module marked `fail`, exception message captured in `error` |
| Individual query times out (>2s) | Module marked `fail`, error: "timeout after {elapsed}ms" |
| Total suite exceeds 30s | Remaining modules marked `skip`, reason: "total timeout exceeded" |
| Neptune/OpenSearch connection refused | Query raises, caught as `fail` with connection error message |
| `GITHUB_TOKEN` not set | github_tools marked `skip`, reason: "GITHUB_TOKEN not set" |
| `MCP_WORKFLOW_ROOT` not set or path missing | workflow_info/sdd_workflow marked `fail` with path error |
| Standalone script missing env vars | Exit code 2, descriptive error to stderr |

## Testing Strategy

### Unit Tests (`tests/unit/test_smoke_queries.py`)

- Mock `data.vector_db.query` and `data.graph_db.query` to return controlled responses.
- Test each query function: pass case (returns True), fail case (returns 0 results → raises), exception case.
- Test timeout handling: mock a query that sleeps > 2s, verify `fail` with timeout message.
- Test skip logic: unset `GITHUB_TOKEN`, verify github_tools is `skip`.
- Test `run_all` with `only=<module>` filter.
- Test `run_all` with `data=None` → all skip.
- Test total timeout: mock all queries to sleep 4s each, verify later modules are `skip`.

### Integration Verification (via standalone script)

After implementation, run:
```bash
DB_BACKEND=aws \
  OPENSEARCH_ENDPOINT=https://vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com \
  NEPTUNE_ENDPOINT=https://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182 \
  AWS_REGION=us-east-1 \
  MCP_WORKFLOW_ROOT=/mdc-mcp-rag/eib-mcp-rag-server/supported_repos/global-workflow \
  python3.12 mcp_server_python/scripts/smoke_test_tools.py
```

Expected: exit 0, 8/9 pass, 1 skip (github_tools).

Then verify via MCP:
```
mcp_health_check(functional=True, detailed=True)
```

Expected: "Functional Validation" section appears with the same 8/9 pass result.

## File Layout

```
mcp_server_python/
├── src/
│   └── tools/
│       ├── utility.py              (modified — wire in smoke_queries)
│       └── smoke_queries.py        (new — shared registry + query defs)
├── scripts/
│   └── smoke_test_tools.py         (new — standalone CLI)
└── tests/
    └── unit/
        └── test_smoke_queries.py   (new — unit tests)
```

## Traceability Matrix

| Requirement | Design Component |
|-------------|-----------------|
| 1.1 (one query per module) | `SmokeQueryRegistry.QUERIES` has exactly 9 entries |
| 1.2 (ModuleResult structure) | `ModuleResult` dataclass |
| 1.3 (pass on valid result) | Each `query_fn` returns `True` on success |
| 1.4 (fail on exception/zero) | `run_one` catches exceptions → `fail` |
| 1.5 (skip on missing cred) | `requires` field checked before execution |
| 1.6 (skip when no data layer) | `run_all` short-circuits when `data is None` |
| 2.1–2.9 (per-module queries) | Query table in section 4 |
| 3.1 (2s per query) | `asyncio.wait_for(timeout=2.0)` |
| 3.2 (30s total) | `TOTAL_TIMEOUT_MS = 30000` with elapsed tracking |
| 3.3 (timeout → fail) | `asyncio.TimeoutError` caught → `fail` |
| 3.4 (sequential) | `for` loop in `run_all`, no `gather` |
| 4.1 (markdown table) | `_render_functional_results` in utility.py |
| 4.2 (summary line) | Summary line in render function |
| 4.3 (JSON output) | Standalone script JSON schema |
| 4.4 (markdown to stderr) | Standalone prints table to stderr |
| 4.5 (exit codes) | 0/1/2 in standalone script |
| 5.1–5.6 (standalone script) | `scripts/smoke_test_tools.py` design |
| 6.1 (shared module) | `src/tools/smoke_queries.py` |
| 6.2 (parameterized) | `run_all(data, mcp)` signature |
| 6.3 (extensible) | Add one `SmokeQueryDef` to `QUERIES` dict |


## Correctness Properties

This feature is primarily integration-level validation — it fires real queries against live backends and checks for non-empty responses. The acceptance criteria are SMOKE and EXAMPLE classifications, not pure-function properties amenable to property-based testing.

**Rationale:** The 9 smoke queries test external service reachability and data presence, not algorithmic correctness. Running 100 Hypothesis iterations against the same OpenSearch endpoint would not find more bugs than 1 iteration. The unit tests use mocked backends to verify the runner logic (timeout handling, skip logic, result aggregation) which *is* deterministic and testable without PBT.
