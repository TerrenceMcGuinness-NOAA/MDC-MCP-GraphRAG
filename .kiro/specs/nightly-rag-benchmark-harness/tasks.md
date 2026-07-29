# Implementation Plan: Nightly RAG Benchmark Harness

## Overview

Schedule the existing benchmark harness as a nightly systemd timer on COTS,
writing to `quality_metrics.jsonl` so `get_quality_metrics` returns real data.

## Tasks

- [x] 1. Nightly wrapper script
  - [x] 1.1 Write `mcp_server_python/scripts/run_benchmark_nightly.sh`: source secrets, invoke the harness, append the run as one compacted JSONL line to both host and container-visible paths
    - _Requirements: 1.1, 1.2, 1.3, 1.4_
  - [x] 1.2 Add snapshot rotation (keep last `KEEP_RUNS`=90 **runs**; archive older lines to `.gz`) — corrected from "90 x 6 (per category)" since the reader treats one line = one run
    - _Requirements: 3.1, 3.2_
  - [x] 1.3 Add regression detection: latest vs trailing N-run median per category (mrr/precision/coverage); structured JSON ERROR log if > `REGRESSION_PCT`=10% drop
    - _Requirements: 5.1, 5.2_

- [x] 2. systemd service + timer
  - [x] 2.1 Write `SETUP/systemd/mcp-benchmark.service` (Type=oneshot, ExecStart=wrapper, TimeoutStartSec=1800, runs as gateway user)
    - _Requirements: 1.1, 1.4_
  - [x] 2.2 Write `SETUP/systemd/mcp-benchmark.timer` (OnCalendar=*-*-* 02:30:00 UTC, Persistent, jitter)
    - _Requirements: 2.1, 2.3_
  - [x] 2.3 Add install instructions to `SETUP/README.md` + `SETUP/systemd/install-benchmark-timer.sh` (install/enable/start/uninstall)
    - _Requirements: 2.2_

- [~] 3. Verify `get_quality_metrics` populates — **operator-gated** (needs `systemctl` + live ChromaDB/Neo4j on the host; not run autonomously per safety policy). Wrapper append logic verified end-to-end with a stubbed harness.
  - [ ] 3.1 Manual run: `systemctl start mcp-benchmark.service`; confirm JSONL written
    - _Requirements: 4.1_
  - [ ] 3.2 Confirm `get_quality_metrics` returns per-category data (not "not found")
    - _Requirements: 4.1_
  - [ ] 3.3 Run a second time; confirm `get_quality_metrics --compare` returns deltas
    - _Requirements: 4.2_

- [x] 4. Regression detection test
  - [x] 4.1 Injected a synthetic 60% mrr drop through the wrapper (stubbed harness, temp dirs); confirmed structured `[ERROR] {"event":"rag_quality_regression","category":...,"metric":"mrr","score":0.4,"median_7run":0.8,"drop_pct":50.0}` on stderr (journal-visible)
    - _Requirements: 5.1, 5.2_

- [~] 5. Timer activation — **operator-gated** (needs root `systemctl enable/start`)
  - [ ] 5.1 Enable + start the timer; `systemctl list-timers | grep mcp-benchmark` shows next-run

## Verification status

- **Autonomously verified**: wrapper syntax (`bash -n`), and full append / dual-path
  write / rotation (keep-N + `.gz` archive) / regression-detection logic via a
  stubbed benchmark command over temp dirs (6 logic checks pass).
- **Operator-gated (root / live services)**: installing + enabling the systemd
  timer and running the real Node harness against live ChromaDB + Neo4j.
  Documented in `SETUP/README.md`. Not executed autonomously — modifying live
  host systemd units is a high-risk action reserved for an operator.

## Deviations from the draft design (intentional, code-truthful)

1. **JSONL granularity**: one line per **run** (nested `categories` + `overall`),
   not "one line per category". The `get_quality_metrics` reader
   (`_render_quality_metrics`) and `--compare` diff the last two *runs*; a
   per-category line would break comparison. Rotation keeps the last 90 runs.
2. **Harness**: `run_benchmark.js` (in-process tool calls, emits the exact
   reader schema across the 6-category `test/benchmark/ground_truth.json`) is
   the harness, not the AWS-only `config/benchmark_runner.py` (OpenSearch/S3,
   different `model×mode` schema) that the draft also referenced.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "2.1", "2.2", "2.3"] },
    { "id": 2, "tasks": ["3.1"] },
    { "id": 3, "tasks": ["3.2", "3.3", "4.1"] },
    { "id": 4, "tasks": ["5.1"] }
  ]
}
```
