# Implementation Plan: Functional Smoke Tests

## Overview

Implement per-tool-module functional validation smoke queries for the Python MCP/RAG server. This adds a shared `smoke_queries.py` module consumed by both `mcp_health_check(functional=True)` and a standalone CLI script. Each of the 9 tool modules gets one lightweight query exercising the real data path (OpenSearch or Neptune) and reporting pass/fail/skip with latency.

## Tasks

> **STATUS — DONE (2026-05-22).** Shipped via commit `212d951`
> (`feat(mcp): functional smoke tests (Phase B5+) — 9/9 pass live`).
> The smoke harness is live in v35: `mcp_health_check(functional=True)`
> returns the Functional Validation table with 10 modules including
> `branch_isolation` (added by `omd-tenants-2-v17-pilot` Group D —
> commit `606d671`). Sub-bugs in this surface (`_smoke_workflow_info`
> SKIP shape, github_tools Secrets Manager) were closed by
> `health-check-bugfixes` and the probe fix-ups in commits `404caa1`,
> `f5958c4`, `e910ca9`, `2dd1f15`.

- [x] 1. Create the shared smoke query module
  - [x] 1.1 Create `mcp_server_python/src/tools/smoke_queries.py` with dataclasses and registry
    - Define `SmokeQueryDef` dataclass with fields: `module`, `description`, `query_fn`, `requires`
    - Define `ModuleResult` dataclass with fields: `module`, `status` (pass/fail/skip), `latency_ms`, `error`, `description`
    - Implement `SmokeQueryRegistry` class with `QUERIES` dict, `TIMEOUT_MS=2000`, `TOTAL_TIMEOUT_MS=30000`
    - Implement `run_all(data, mcp=None, only=None)` — sequential execution with per-query timeout via `asyncio.wait_for`, total timeout tracking, skip-all when `data is None`
    - Implement `run_one(name, data, mcp=None)` — single module execution with timeout and error capture
    - Check `requires` env vars before execution; mark module `skip` with reason if missing
    - _Requirements: 6.1, 6.2, 6.3, 1.2, 1.5, 1.6, 3.1, 3.2, 3.3, 3.4_

  - [x] 1.2 Implement the 9 per-module smoke query functions in `smoke_queries.py`
    - `semantic_search`: `data.vector_db.query("global workflow forecast", index="mdc-workflow-docs-titan1024", k=1)` — pass if ≥1 hit
    - `code_analysis`: `data.graph_db.query("MATCH (f:File {name:'JGFS_FORECAST'})-[r]->(t) RETURN type(r), t.name LIMIT 3")` — pass if ≥1 row
    - `graph_rag`: `data.graph_db.query("MATCH (n {name:'JGFS_FORECAST'})-[r]-(m) RETURN n.name, type(r), m.name LIMIT 5")` — pass if ≥1 row
    - `ee2_compliance`: `data.vector_db.query("error handling", index="mdc-ee2-standards-titan1024", k=1)` — pass if ≥1 hit
    - `operational`: `data.vector_db.query("running forecast on hera", index="mdc-workflow-docs-titan1024", k=1)` — pass if ≥1 hit
    - `sdd_workflow`: Check `Path(state_dir / "active_session.json").exists()` or `history.jsonl` exists — pass if file exists
    - `workflow_info`: Check `Path(workflow_root / "jobs").is_dir()` — pass if directory exists
    - `github_tools`: `requires: ["GITHUB_TOKEN"]` — skipped when token absent
    - `utility`: Count tools via `mcp.list_tools()` if mcp provided, else return pass — pass if ≥50 tools
    - Register all 9 in `SmokeQueryRegistry.QUERIES`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9_

- [x] 2. Integrate smoke queries into the health check tool
  - [x] 2.1 Modify `mcp_server_python/src/tools/utility.py` to wire in `SmokeQueryRegistry`
    - Replace the placeholder block at lines 470–485 in `_render_health_check` with import and call to `SmokeQueryRegistry.run_all(data, mcp=mcp)`
    - Implement `_render_functional_results(results: list[ModuleResult]) -> list[str]` helper that produces a markdown table with columns: Module, Status, Latency, Error
    - Include a summary line: "X/9 passed, Y failed, Z skipped"
    - When `data is None`, keep existing message: "Functional tests skipped — no data access layer available."
    - Pass `mcp` instance to `run_all` so the utility module query can count tools
    - _Requirements: 1.1, 1.3, 1.4, 1.6, 4.1, 4.2_

- [x] 3. Checkpoint - Verify health check integration
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Create the standalone CLI script
  - [x] 4.1 Create `mcp_server_python/scripts/smoke_test_tools.py`
    - Add argparse with `--json-only` and `--module <name>` flags
    - Validate required env vars (`DB_BACKEND`, `OPENSEARCH_ENDPOINT`, `NEPTUNE_ENDPOINT`, `AWS_REGION`) — exit code 2 with descriptive error if missing when `DB_BACKEND=aws`
    - Initialize data access layer via `create_data_access(config)` from `src/data/backend_selector.py` (without starting MCP server)
    - Call `SmokeQueryRegistry().run_all(data, mcp=None, only=args.module)`
    - Output JSON result object to stdout with fields: `timestamp`, `total_duration_ms`, `summary` (passed/failed/skipped/total), `results` array
    - If not `--json-only`, print human-readable markdown table to stderr
    - Exit 0 when all non-skipped modules pass, exit 1 when any module fails
    - Make script executable with `python3.12 mcp_server_python/scripts/smoke_test_tools.py`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 4.3, 4.4, 4.5_

- [x] 5. Checkpoint - Run standalone script against live backends
  - Ensure all tests pass, ask the user if questions arise.
  - Verify with: `DB_BACKEND=aws OPENSEARCH_ENDPOINT=https://vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com NEPTUNE_ENDPOINT=https://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182 AWS_REGION=us-east-1 MCP_WORKFLOW_ROOT=/mdc-mcp-rag/eib-mcp-rag-server/supported_repos/global-workflow python3.12 mcp_server_python/scripts/smoke_test_tools.py`
  - Expected: exit 0, 8/9 pass, 1 skip (github_tools)

- [x] 6. End-to-end verification via MCP tool call
  - [x] 6.1 Verify `mcp_health_check(functional=True)` returns the Functional Validation section
    - Call `mcp_health_check(functional=True, detailed=True)` via the MCP tool interface
    - Confirm "Functional Validation" section appears with markdown table
    - Confirm summary line shows 8/9 passed, 0 failed, 1 skipped
    - _Requirements: 4.1, 4.2, 1.1, 1.3_

- [x] 7. Final checkpoint - All verification complete
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- No new unit tests required per user preference — verification is via live MCP calls and the standalone script
- The design explicitly states no property-based tests are applicable (smoke queries test external service reachability, not algorithmic correctness)
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Use `python3.12` for all commands
- AWS endpoints: OpenSearch `vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com`, Neptune `mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182`
- `MCP_WORKFLOW_ROOT` on EC2: `/mdc-mcp-rag/eib-mcp-rag-server/supported_repos/global-workflow`

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["2.1", "4.1"] },
    { "id": 3, "tasks": ["6.1"] }
  ]
}
```
