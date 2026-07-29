# Requirements Document

## Introduction

This feature adds a **nightly scheduled run** of the RAG benchmark harness on the
Parallel Works COTS host so quality regressions are detected the next morning, not
the next release. Today `get_quality_metrics` returns "No benchmark results found"
because nothing writes `quality_metrics.jsonl`, and `get_quality_metrics --compare`
cannot function without at least two snapshots.

A benchmark harness already exists (`mcp_server_node/scripts/benchmark_runner.py`,
ground truth in `config/benchmark_ground_truth.json`). This phase schedules it,
wires the output to the path the MCP tool reads, and adds fail-loud regression
detection.

Phase 71 from the SDD
(`sdd_framework/workflows/phase71_nightly_rag_benchmark_harness.md`), surfaced in
the 2026-07-20 gap analysis (Gap 4).

## Requirements

### Requirement 1: systemd oneshot service runs the benchmark

**User Story:** As an operator, I want a systemd service that runs the benchmark
harness end-to-end against the live Docker MCP Gateway.

#### Acceptance Criteria

1. A `mcp-benchmark.service` (Type=oneshot) SHALL source the shell secrets SPOT
   (`~/.config/eib-mcp/secrets.env`) and run the benchmark harness against the
   live `mcp-gateway.service` on `:18888` (Streamable HTTP).
2. THE service SHALL produce one JSONL line per benchmark category
   (`code_structure`, `semantic_search`, `architecture`, `ee2_compliance`,
   `operational`, `cross_language`) with a UTC ISO-8601 timestamp.
3. THE JSONL output SHALL be appended to
   `${MCP_HOST_STATE_DIR}/quality_metrics.jsonl` AND to the container-visible
   path (`/app/sdd_framework/execution_state/quality_metrics.jsonl`) via the
   existing read-write mount.
4. THE service SHALL exit 0 on success and non-zero on harness failure (so
   `systemctl status` and journal show failures clearly).

### Requirement 2: systemd timer fires nightly

**User Story:** As an operator, I want the benchmark to run automatically every
night so I have fresh regression data each morning.

#### Acceptance Criteria

1. A `mcp-benchmark.timer` SHALL fire at **02:30 UTC** daily (post low-traffic
   window, before US East morning standup).
2. THE timer SHALL be enabled and active after installation
   (`systemctl list-timers | grep mcp-benchmark` shows a next-run).
3. THE timer SHALL NOT overlap with `mcp-container-cleanup.timer` windows.

### Requirement 3: Snapshot rotation

**User Story:** As an operator, I want old snapshots rotated so the JSONL file
doesn't grow unbounded.

#### Acceptance Criteria

1. THE benchmark service SHALL retain the last **90 daily snapshots** in the
   JSONL file.
2. Lines older than 90 days SHALL be truncated (or moved to a compressed
   archive at `${MCP_HOST_STATE_DIR}/benchmark-archive/`).

### Requirement 4: `get_quality_metrics` populates

**User Story:** As a user of the MCP tools, I want `get_quality_metrics` to
return real data after the first nightly run.

#### Acceptance Criteria

1. AFTER the first successful run, `get_quality_metrics` SHALL return per-category
   metrics (not "No benchmark results found").
2. `get_quality_metrics --compare` SHALL return per-category deltas vs the prior
   snapshot once two snapshots exist.

### Requirement 5: Fail-loud regression detection

**User Story:** As an operator, I want to be alerted (in logs) when quality drops
so I don't miss a regression.

#### Acceptance Criteria

1. WHEN a category's score drops > 10% below the trailing 7-day median, THE
   service SHALL emit a structured JSON log entry at ERROR level (greppable,
   journal-visible).
2. THE regression entry SHALL name the category, the current score, and the
   7-day median it fell below.

### Requirement 6: Boundaries

#### Acceptance Criteria

1. THE feature SHALL NOT add new benchmark queries (uses the existing ground-truth
   set in `config/benchmark_ground_truth.json`).
2. THE feature SHALL NOT integrate with CI (runs on the host only).
3. THE feature SHALL NOT add alerting infrastructure (log-only; future n8n can
   parse the JSONL).
4. THE feature targets COTS/Parallel Works only — the AWS AgentCore path is a
   follow-up.
5. THE feature SHALL NOT auto-commit or auto-push.
