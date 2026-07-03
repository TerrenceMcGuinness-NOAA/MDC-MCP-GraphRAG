# Tasks: Tenant Status Honesty

Ordered smallest-first so an implementer can land each independently and
verify with unit tests before rebuilding the container.

- [ ] **1. Add `_probe_tenant_data` helper + unit tests**
  - Location: `mcp_server_python/src/tools/utility.py`
    (private module-level, near `_render_functional_results`).
  - Returns one of: `populated`, `graph-only`, `vector-only`, `empty`,
    `probe-error`.
  - Cheap queries: `MATCH (n:{prefix}File) RETURN n LIMIT 1` + prefix-filtered
    `list_collections()`.
  - Unit tests: `tests/unit/test_probe_tenant_data.py` (fixture-driven,
    monkeypatch the two adapters). ~40 lines.
  - _Satisfies half of Requirement 1._

- [ ] **2. Wire `data` column into `mcp_health_check`'s tenants table**
  - Loop calls `_probe_tenant_data` for each Catalog_Tenant; append
    `data` column to the existing table rendering; update the section
    header to include the summary count line
    `## Tenants (5 — populated: 1, graph-only: 1, empty: 3)`.
  - Timing: 10 cheap queries total; measured latency < 100 ms.
  - Unit test extension: `tests/unit/test_mcp_health_check.py` add a case
    for the new column.
  - _Satisfies Requirement 1._

- [ ] **3. Fix `get_knowledge_base_status` status-label triage**
  - Location: wherever `[OK] Healthy` / `[ERROR] Unhealthy` currently
    render in `get_knowledge_base_status` (start with
    `semantic_search.py`, else `utility.py` — locate on read).
  - Add the four-way triage from design.md §"Status label triage".
  - Reserve `[ERROR] Unhealthy — <ExcClass>` for genuine exceptions only.
  - Unit test: `tests/unit/test_kb_status_triage.py`.
  - _Satisfies Requirement 2._

- [ ] **4. Add `_smoke_tenant_coverage` probe**
  - Location: `mcp_server_python/src/tools/smoke_queries.py`.
  - Reuses `_probe_tenant_data` from Task 1.
  - Registered in the module's `SmokeQueryRegistry` alongside the existing
    11 probes.
  - Emits per-tenant `[SKIP] never-ingested` rows in the renderer output
    (extend `_render_functional_results` to inline them).
  - Unit test: `tests/unit/test_smoke_tenant_coverage.py`.
  - _Satisfies Requirement 3._

- [ ] **5. Steering + changelog update**
  - `.kiro/steering/07-tenant-usability-gaps.md` — append Gap C section
    (per design.md §"Steering update").
  - `CHANGELOG.md` — add `## [Unreleased] - Phase 63d — Tenant Status
    Honesty (2026-07-04+)` entry when tasks 1–4 land.
  - _Satisfies Requirement 4._

- [ ] **6. Native-mode verification**
  - `eib-mcp-rag-full` (stdio) automatically runs live source; call
    `mcp_health_check` via that server and confirm the new column
    reports `populated / graph-only / empty / empty / empty` for the
    five COTS tenants (matching the ground truth we established with
    direct cypher-shell + curl probes).
  - Call `get_knowledge_base_status(tenant_id="gw_sfs")` via the same
    server; confirm the status field reads `[INFO] Empty (never ingested)`.
  - Call `mcp_health_check(functional=true)` via the same server; confirm
    the new `tenant_coverage` line appears in the functional table with
    per-tenant rows.
  - _Gates Task 7._

- [ ] **7. Gateway rebuild + restart** _(operator-run, sudo)_
  ```bash
  docker build -f SETUP/dockerfiles/Dockerfile.mcp-python \
      -t eib-mcp-rag-python:latest .
  sudo systemctl restart mcp-gateway.service
  ```
  - Verify via `eib-mcp-gateway` (Devtunnel): the same three tool calls
    from Task 6 return the same output shape.
  - _Ships Requirements 1–3 to remote clients._
