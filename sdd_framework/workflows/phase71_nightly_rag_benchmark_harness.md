# Phase 71 — Nightly RAG Benchmark Harness

**Version**: 0.1.0
**Created**: 2026-07-20
**Status**: draft (requirement captured; not scheduled)
**Estimated effort**: TBD (scoping needed — small)
**Depends on**: existing benchmark harness under `mcp_server_node/scripts/`
(Phase 22 `validation_benchmarking_subsystem`, Phase 24g `benchmark_validation`);
Phase 70 (`cots_backend_observability_parity`) is a soft dependency — the
benchmark can run without it, but regression signal will be sharper once the
COTS adapter reports document counts correctly.
**Kiro spec**: _(to be authored — `.kiro/specs/nightly-rag-benchmark-harness/`)_
**Owner**: TBD

---

## 1. Executive Summary

The MCP tool `get_quality_metrics` returns:

```
No benchmark results found.
Expected at /app/mcp_server_python/sdd_framework/execution_state/quality_metrics.jsonl.
Run the benchmark harness to generate results.
```

A benchmark harness already exists (`mcp_server_node/scripts/benchmark_runner.py`,
`mcp_server_node/scripts/run_benchmark.js`, ground truth in
`mcp_server_node/scripts/config/benchmark_ground_truth.json`), but nothing
schedules it. The `quality_metrics.jsonl` file has never been written on this
deployment, and `get_quality_metrics --compare` cannot function without at
least two snapshots.

This phase adds a **nightly** run so we detect RAG quality regressions the next
morning instead of the next release.

Observed on 2026-07-20 during the post-cutover full-sweep gap analysis (see
`supported_repos/global-workflow.wiki/Docker-MCP-Gateway-COTS-Gap-Analysis-2026-07-20.md`,
Gap 4).

## 2. Scope

### 2.1 In Scope

- A systemd `mcp-benchmark.service` (Type=oneshot) that:
  1. Sources the shell secrets SPOT (`~/.config/eib-mcp/secrets.env`).
  2. Runs the benchmark harness against the live `mcp-gateway.service` on
     `:18888` (Streamable HTTP), producing a snapshot for each category
     defined in `benchmark_ground_truth.json`: `code_structure`,
     `semantic_search`, `architecture`, `ee2_compliance`, `operational`,
     `cross_language`.
  3. Appends one JSONL line per category (with UTC ISO-8601 timestamp) to
     `${MCP_HOST_STATE_DIR}/quality_metrics.jsonl` **and** to the container-side
     path `/app/mcp_server_python/sdd_framework/execution_state/quality_metrics.jsonl`
     via the existing tenants read-write mount.
- A systemd `mcp-benchmark.timer` firing nightly at **02:30 UTC** (post-cron.d
  low-traffic window; before US East morning standup).
- Snapshot rotation: keep the last 90 daily snapshots; older lines truncated
  from the JSONL (or moved to a compressed archive).
- `get_quality_metrics --compare` regression detection: fail-loud when a
  category drops > 10% below the trailing 7-day median.
- Complete the Python-side port of `benchmark_runner.py` so both Node and
  Python versions run identically (if the Node version already suffices, this
  is a no-op).

### 2.2 Out of Scope

- Adding new benchmark queries (use the existing ground-truth set).
- CI integration (the harness runs on the host, not in GitHub Actions).
- Alerting infrastructure (log-only for this phase; future n8n workflow can
  parse the JSONL and route to Slack/email).
- The AWS/Neptune AgentCore deployment path — this phase targets the on-prem
  Parallel Works stack only. A follow-up will schedule the same harness inside
  AgentCore.

## 3. Success Criteria

1. `/app/mcp_server_python/sdd_framework/execution_state/quality_metrics.jsonl`
   contains at least one line per benchmark category within 24 h of merge.
2. `get_quality_metrics` no longer reports "No benchmark results found".
3. `get_quality_metrics --compare` returns per-category deltas vs the prior
   snapshot.
4. `systemctl list-timers | grep mcp-benchmark` shows the timer active with a
   next-run inside the following 24 h.
5. On day 8, a regression injected into any category triggers a fail-loud log
   entry (structured JSON, greppable).

## 4. Open Questions

- Should the timer schedule align with `mcp-container-cleanup.timer` (15-min
  cadence, Phase 23) or run independently? Nightly is proposed to avoid load
  during working hours.
- Does the harness need to be tenant-aware (run once per tenant), or is
  running against the default tenant `gw` sufficient for regression signal?
  (First cut: default tenant only; add per-tenant in a follow-up if drift
  emerges.)
- Where should archived snapshots live if we go beyond 90 days? Candidate:
  `/mcp_rag_eib/data/mcp-server/benchmark-archive/`.

## 5. Risks

- Nightly benchmark load could interact with the `mcp-container-cleanup.timer`
  30-min grace window. Mitigation: schedule benchmark run outside cleanup
  windows and add a `Before=mcp-container-cleanup.timer` where feasible.
- If the benchmark harness has never actually run end-to-end on this stack,
  the first run may surface latent bugs unrelated to this phase. Budget review
  time for triage.

## 6. References

- Gap Analysis wiki: `supported_repos/global-workflow.wiki/Docker-MCP-Gateway-COTS-Gap-Analysis-2026-07-20.md`
- Existing benchmark harness: `mcp_server_node/scripts/benchmark_runner.py`,
  `mcp_server_node/scripts/run_benchmark.js`,
  `mcp_server_node/scripts/config/benchmark_ground_truth.json`
- Phase 22 spec: `sdd_framework/workflows/phase22_validation_benchmarking_subsystem.md`
- Phase 24g spec: `sdd_framework/workflows/phase24g_benchmark_validation.md`
- MCP tool: `get_quality_metrics(category?, compare=false)`
