# Design Document

## Overview

Schedule the existing RAG benchmark harness as a nightly systemd timer on the
Parallel Works COTS host, writing results to the path `get_quality_metrics`
reads, with snapshot rotation and fail-loud regression detection.

## Architecture

```
mcp-benchmark.timer (02:30 UTC daily)
        │
        ▼
mcp-benchmark.service (Type=oneshot)
        │
        ├─ source ~/.config/eib-mcp/secrets.env
        ├─ run benchmark_runner.py against localhost:18888 (MCP Gateway)
        │     queries: config/benchmark_ground_truth.json (6 categories)
        │     output: per-category P@5, P@10, MRR, nDCG + timestamp
        ├─ append JSONL to quality_metrics.jsonl (host + container path)
        ├─ rotate: keep last 90 lines per category
        └─ regression check: score < (7-day median × 0.90) → ERROR log
```

## Files

| New file | Purpose |
|---|---|
| `SETUP/systemd/mcp-benchmark.service` | oneshot service definition |
| `SETUP/systemd/mcp-benchmark.timer` | nightly timer (02:30 UTC) |
| `mcp_server_python/scripts/run_benchmark_nightly.sh` | Wrapper: env setup, harness invoke, rotation, regression check |

## Benchmark runner

The existing `mcp_server_node/scripts/benchmark_runner.py` already:
- Reads `benchmark_ground_truth.json` (24 queries across 6 categories)
- Queries the MCP server via HTTP (Streamable HTTP on `:18888`)
- Computes P@5, P@10, MRR, nDCG per category
- Outputs structured JSON

The nightly wrapper (`run_benchmark_nightly.sh`) orchestrates:
1. Sources env (secrets, `MCP_HOST_STATE_DIR`)
2. Invokes the runner
3. Appends results to JSONL
4. Rotates (keep 90 days)
5. Regression check (compare latest vs 7-day median; log ERROR if > 10% drop)

## Rotation strategy

JSONL is append-only; rotation = `tail -n $((90 * 6))` (90 days × 6 categories
per day) into a temp file + atomic rename. Older lines go to
`${MCP_HOST_STATE_DIR}/benchmark-archive/quality_metrics_$(date).jsonl.gz`.

## Regression detection

```python
median_7d = median(scores[-7:])
if latest < median_7d * 0.90:
    log_error({"event": "rag_quality_regression", "category": cat,
               "score": latest, "median_7d": median_7d})
```

No external alerting — journal only. Future n8n or Lambda can tail the journal.

## Testing

- Smoke: `systemctl start mcp-benchmark.service` produces a non-empty JSONL
  line within 5 minutes.
- Timer: `systemctl list-timers | grep mcp-benchmark` shows next-run < 24h.
- Metrics: `get_quality_metrics` returns data (not "not found").
- Compare: after 2 runs, `get_quality_metrics --compare` returns deltas.
- Regression: inject a 50% score drop → ERROR log entry appears in journal.
