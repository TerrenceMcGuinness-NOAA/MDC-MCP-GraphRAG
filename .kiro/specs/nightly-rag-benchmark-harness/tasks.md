# Implementation Plan: Nightly RAG Benchmark Harness

## Overview

Schedule the existing benchmark harness as a nightly systemd timer on COTS,
writing to `quality_metrics.jsonl` so `get_quality_metrics` returns real data.

## Tasks

- [ ] 1. Nightly wrapper script
  - [ ] 1.1 Write `mcp_server_python/scripts/run_benchmark_nightly.sh`: source secrets, invoke `benchmark_runner.py` against `:18888`, append JSONL to both host and container paths
    - _Requirements: 1.1, 1.2, 1.3, 1.4_
  - [ ] 1.2 Add snapshot rotation (keep last 90 days × 6 categories; archive older to `.gz`)
    - _Requirements: 3.1, 3.2_
  - [ ] 1.3 Add regression detection: latest vs 7-day median; structured ERROR log if > 10% drop
    - _Requirements: 5.1, 5.2_

- [ ] 2. systemd service + timer
  - [ ] 2.1 Write `SETUP/systemd/mcp-benchmark.service` (Type=oneshot, ExecStart=wrapper)
    - _Requirements: 1.1, 1.4_
  - [ ] 2.2 Write `SETUP/systemd/mcp-benchmark.timer` (OnCalendar=*-*-* 02:30:00 UTC)
    - _Requirements: 2.1, 2.3_
  - [ ] 2.3 Add install instructions to `SETUP/README.md` (symlink + enable + start)
    - _Requirements: 2.2_

- [ ] 3. Verify `get_quality_metrics` populates
  - [ ] 3.1 Manual run: `systemctl start mcp-benchmark.service`; confirm JSONL written
    - _Requirements: 4.1_
  - [ ] 3.2 Confirm `get_quality_metrics` returns per-category data (not "not found")
    - _Requirements: 4.1_
  - [ ] 3.3 Run a second time; confirm `get_quality_metrics --compare` returns deltas
    - _Requirements: 4.2_

- [ ] 4. Regression detection test
  - [ ] 4.1 Inject a synthetic 50% score drop into the JSONL; re-run the regression check; confirm ERROR log entry in journal
    - _Requirements: 5.1, 5.2_

- [ ] 5. Timer activation
  - [ ] 5.1 Enable + start the timer; `systemctl list-timers | grep mcp-benchmark` shows next-run
    - _Requirements: 2.2_

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
