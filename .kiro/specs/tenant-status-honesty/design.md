# Design: Tenant Status Honesty

## Scope

Two source files, one steering file, one changelog entry. No new dependencies.

- `mcp_server_python/src/tools/utility.py` — add per-tenant data column to the
  tenants table (Req 1); adjust status labels in the kb-status render (Req 2).
- `mcp_server_python/src/tools/smoke_queries.py` — add `_smoke_tenant_coverage`
  probe (Req 3).
- `mcp_server_python/src/tools/semantic_search.py` (`get_knowledge_base_status`
  render path) — status label triage (Req 2, may live here rather than
  utility.py; TBD in Task 2 during read).
- `.kiro/steering/07-tenant-usability-gaps.md` — Gap C section (Req 4).
- `CHANGELOG.md` — Phase 63d entry (Req 4).

## Per-tenant probe (Req 1) — implementation shape

```python
async def _probe_tenant_data(
    tenant: Tenant,
    data: DataAccessLayer,
) -> str:
    """Return one of: 'populated', 'graph-only', 'vector-only', 'empty',
    'probe-error'."""
    try:
        # Cheap probes: LIMIT 1 on graph, list_collections + startswith on vector.
        graph_hit = await data.graph_db.query(
            f"MATCH (n:{tenant.label_prefix}File) RETURN n LIMIT 1",
            tenant=tenant,
        )
        vector_hits = [
            c for c in await data.vector_db.list_collections()
            if c.startswith(tenant.index_prefix or "") and not (
                tenant.index_prefix == "" and any(
                    c.startswith(p) for p in _OTHER_PREFIXES
                )
            )
        ]
    except Exception:
        return "probe-error"

    has_graph = bool(graph_hit)
    has_vector = bool(vector_hits)
    if has_graph and has_vector: return "populated"
    if has_graph:                return "graph-only"
    if has_vector:               return "vector-only"
    return "empty"
```

For the default (unprefixed) tenant, "vector collections that start with `''`"
matches every collection, so we must exclude collections that start with any
OTHER tenant's prefix — the `_OTHER_PREFIXES` set derived from the catalog.

Latency budget: 5 tenants × 2 probes each = 10 cheap queries, sub-100 ms
total on a warm backend. Acceptable for a `mcp_health_check` default call.

## Rendering (Req 1)

Existing tenants table gets one more column. Sample after-change output:

```
## Tenants (5 — populated: 1, graph-only: 1, empty: 3)

| tenant_id     | data        | branch          | lifecycle    | ... |
|---------------|-------------|-----------------|--------------|-----|
| gw            | populated   | develop         | production   | ... |
| gw_sfs        | empty       | dev/sfs         | experimental | ... |
| gw_jedi_gfs   | empty       | dev/jedi-gfs    | experimental | ... |
| gw_v17        | graph-only  | dev/gfs.v17     | staging      | ... |
| gw_gefs_v12   | empty       | release/gefs_v12| production   | ... |
```

The header line gains a summary count so a reader who skims only the section
title still sees the real state.

## Status label triage (Req 2)

`get_knowledge_base_status` render path currently treats `collections == 0`
as `[ERROR] Unhealthy`. Change to:

```python
if collections == 0 and node_count == 0:
    status = "[INFO] Empty (never ingested)"
elif collections == 0:
    status = "[INFO] Partial: graph"
elif node_count == 0:
    status = "[INFO] Partial: vector"
else:
    status = "[OK] Healthy"
# reserved for real adapter errors:
# status = "[ERROR] Unhealthy — <exception class>"
```

## New smoke probe (Req 3)

```python
async def _smoke_tenant_coverage(data, _mcp):
    """Per-tenant data-presence probe. One entry per catalog tenant.
    Emits '[SKIP] never-ingested' rows for empty tenants without failing
    the probe (SkipProbe reserved for prerequisite-missing)."""
    from src.config.tenants import load_catalog
    catalog = load_catalog(os.environ["MCP_TENANT_CATALOG_PATH"])

    rows = []
    for t in catalog.tenants:
        status = await _probe_tenant_data(t, data)  # reuse Req 1's probe
        rows.append((t.tenant_id, status))

    populated = [r for r in rows if r[1] == "populated"]
    if not populated:
        raise RuntimeError("tenant_coverage: no tenant is populated on this backend")

    # Emit rows as a side-effect (through the module's log/return channel)
    _tenant_coverage_last_rows[:] = rows  # picked up by the render path
    return True
```

The renderer (`_render_functional_results`) gets a small extension to inline
the per-tenant rows underneath the `tenant_coverage` line, keeping the
existing `Module | Status | Latency | Error` table shape.

## Steering update (Req 4)

Append a Gap C section to `.kiro/steering/07-tenant-usability-gaps.md`:

- **Gap C — reporting hazard**: "Tenants: 5" is a catalog count, not a
  data count. Reference this spec and the two tool locations that answer
  the real question (`mcp_health_check` now, or
  `get_knowledge_base_status(tenant_id=X)` per tenant).

## Test plan

Unit tests only. No integration tests needed — the smoke probe is itself the
integration check.

- `test_health_tenants_data_column.py`:
  - fixture with populated `gw`, graph-only `gw_v17`, empty `gw_sfs` →
    rendered table has correct `data` values.
  - probe raises → cell renders `probe-error`, overall status still HEALTHY.
- `test_smoke_tenant_coverage.py`:
  - all-empty catalog → probe returns FAIL with the "no tenant populated" message.
  - mixed catalog → probe returns pass, per-tenant rows recorded.
- `test_kb_status_triage.py`:
  - empty tenant → `[INFO] Empty (never ingested)`.
  - graph-only → `[INFO] Partial: graph`.
  - populated → `[OK] Healthy`.
  - adapter raises → `[ERROR] Unhealthy — <ExcClass>`.

## Deployment (COTS gateway)

Two options, both operator-run:

1. **Rebuild-and-restart** (matches Phase 63b/63c pattern):
   ```bash
   docker build -f SETUP/dockerfiles/Dockerfile.mcp-python \
       -t eib-mcp-rag-python:latest .
   sudo systemctl restart mcp-gateway.service
   ```
2. **Native only** (skip rebuild): verify via `eib-mcp-rag-full` stdio path
   which runs live source. Useful for dev iteration; the gateway continues
   serving the old rendering until step 1 runs.

## Rollback

`git revert` the implementation commit; rebuild + restart per step 1 above.
No live-config edits to reverse (no systemd, cron, or docker-mcp changes
in this phase).
