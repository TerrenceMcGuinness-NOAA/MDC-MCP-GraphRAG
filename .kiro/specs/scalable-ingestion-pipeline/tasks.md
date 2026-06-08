# Implementation Plan: scalable-ingestion-pipeline

## Overview

Refactor the ingestion pipeline from serial single-host execution into a
parallelized, SageMaker-backed batch system. Delivered in four phases that
each provide incremental value:

- **Phase 1** (Parallelism): ProcessPoolExecutor + timeout → 37h Fortran drops to ~2h
- **Phase 2** (Orchestration): Checkpoint/resume + multi-stage coordination
- **Phase 3** (SageMaker): Offload to large instances, multi-tenant concurrent jobs
- **Phase 4** (Observability): CloudWatch metrics, alerting, drift triggers

TDD ordering within each phase. Pure-test tasks are `[ ]*`. All paths
relative to `/mdc-mcp-rag/eib-mcp-rag-server/`.

References:
- Requirements: `.kiro/specs/scalable-ingestion-pipeline/requirements.md` (R1–R9)
- Design: `.kiro/specs/scalable-ingestion-pipeline/design.md` (components 1–7, Properties P1–P7)
- Existing scripts: `mcp_server_python/scripts/ingest_fortran_graph_v8.py`, `ingest_shell_graph_v8.py`

## Tasks

### Phase 1 — Parallelism Refactor (immediate speedup)

- [ ] 1. Implement `_parallel_runner.py`
  - Per design §2. New file: `mcp_server_python/scripts/_parallel_runner.py`
  - `ParallelConfig` dataclass (workers, timeout, progress_interval)
  - `FileResult` dataclass (path, success, result, elapsed, error)
  - `ParallelStats` dataclass (parsed, failed, timed_out, total_elapsed)
  - `run_parallel_parse(files, parse_fn, config)` — uses `concurrent.futures.ProcessPoolExecutor`
  - Per-file timeout via `future.result(timeout=config.timeout)` — on timeout: log, record FileResult(success=False), continue
  - Progress aggregation: unified progress lines at config.progress_interval
  - parse_fn must be picklable (module-level function, not lambda/closure)
  - **Implements: R1.1, R1.3, R1.4, R1.5, R1.6**

  - [ ]* 1.1 Unit tests for `_parallel_runner.py`
    - Synthetic parse function (sleep + return) with configurable delay
    - --workers 1 vs --workers 4: same results (P1 correctness)
    - Timeout: file that sleeps > timeout is marked failed with error="timeout"
    - All fast files succeed regardless of slow-file presence
    - Progress lines emitted at correct intervals
    - File: `mcp_server_python/tests/unit/test_parallel_runner.py` (new)
    - **Validates: R1.1, R1.3, R1.4, R1.5, R1.6**

- [ ] 2. Refactor `ingest_fortran_graph_v8.py` to use `_parallel_runner`
  - Replace the serial `for filepath in files: parse_file(filepath)` loop with `run_parallel_parse(files, fortran_parser.parse_file, config)`
  - Add `--workers` and `--timeout` CLI flags (default: cpu_count-1, 120s)
  - Extract `parse_file` as a module-level picklable function (move out of class if needed)
  - Phase 1 (parsing) uses parallel runner; Phase 2 (node writes) and Phase 3 (rel writes) remain serial (Neptune writes are I/O-bound, not CPU-bound)
  - **Implements: R1.1, R1.2, R8.1, R8.2**

  - [ ]* 2.1 Backward compatibility test
    - Run existing `test_fortran_parser.py` and `test_fortran_graph_writes.py` — all pass unchanged
    - Run with `--workers 1`: identical behavior to pre-refactor
    - **Validates: R8.3**

- [ ] 3. Refactor `ingest_shell_graph_v8.py` to use `_parallel_runner`
  - Same pattern: replace serial parse loop with `run_parallel_parse()`
  - Add `--workers` and `--timeout` CLI flags
  - Shell parsing is fast (no timeout issues expected) but parallelism still helps on large worktrees
  - **Implements: R1.2, R8.1, R8.2**

- [ ]* 4. Write property tests P1 + P2 (parallelism correctness + timeout safety)
  - **Property 1: Parallelism Correctness** — same parse results regardless of worker count
  - **Property 2: Timeout Safety** — timed-out files marked correctly, fast files succeed, no corrupt results
  - Hypothesis-driven: random file lists × random worker counts × random timeouts
  - File: `mcp_server_python/tests/properties/test_scalable_ingestion_props.py` (new)
  - **Validates: R1.3, R1.4, R1.5**

- [ ] 5. Phase 1 Checkpoint — parallel parsing works on EC2
  - Run `ingest_fortran_graph_v8.py --tenant gw_v17 --mode full --workers 3 --timeout 120 --dry-run` on the 4-core EC2
  - Verify: completes in <4 hours (vs 37h serial), all existing tests pass
  - Compare parse results to the serial run (same files parsed, same success rate ~85%)
  - **Validates: R1, R8**

### Phase 2 — Checkpoint + Orchestrator (resumability)

- [ ] 6. Implement `_checkpoint.py`
  - Per design §3. New file: `mcp_server_python/scripts/_checkpoint.py`
  - `StageCheckpoint` and `RunCheckpoint` dataclasses
  - `CheckpointManager(tenant_id, run_id, s3_bucket)` with `load()`, `save()`, `is_stage_complete()`, `mark_stage_complete()`, `mark_stage_failed()`
  - S3 storage: `s3://mdc-mcp-rag-artifacts/checkpoints/{tenant_id}/{run_id}.json`
  - Fallback to local file when S3 unavailable (for --backend local without S3 access)
  - **Implements: R5.1, R5.2, R5.3**

  - [ ]* 6.1 Unit tests for `_checkpoint.py`
    - Round-trip: create → save → load → verify all fields preserved
    - `is_stage_complete`: returns True for completed, False for pending/running/failed
    - `mark_stage_complete` updates status and saves
    - Resume logic: N stages, K complete → only N-K remaining execute
    - File: `mcp_server_python/tests/unit/test_checkpoint.py` (new)
    - **Validates: R5.1, R5.2, R5.3**

- [ ] 7. Implement `_drift_detector.py`
  - Per design §4. New file: `mcp_server_python/scripts/_drift_detector.py`
  - `TenantIngestionState` dataclass
  - `DriftDetector(s3_bucket)` with `get_state()`, `has_drift()`, `update_state()`
  - Compares worktree HEAD (via `git rev-parse HEAD`) to last_commit_sha in state
  - S3 storage: `s3://mdc-mcp-rag-artifacts/ingestion-state/{tenant_id}.json`
  - **Implements: R4.4, R4.5**

  - [ ]* 7.1 Unit tests for `_drift_detector.py`
    - Same SHA → has_drift() returns False
    - Different SHA → has_drift() returns True
    - No state file → has_drift() returns True (first run)
    - update_state round-trip
    - File: `mcp_server_python/tests/unit/test_drift_detector.py` (new)
    - **Validates: R4.4, R4.5**

- [ ] 8. Implement `orchestrate_ingestion.py` (local backend)
  - Per design §1. New file: `mcp_server_python/scripts/orchestrate_ingestion.py`
  - CLI: --tenants, --backend (default: local), --mode, --stages, --resume, --max-concurrent, --workers, --timeout, --dry-run
  - Local backend: runs stages sequentially per the dependency graph (S1 → {S2-S6} → S7)
  - Integrates CheckpointManager for --resume
  - Integrates DriftDetector for --mode diff (skip if no drift)
  - Multi-tenant with asyncio.Semaphore(max_concurrent) — even locally, serializes to avoid overwhelming Neptune
  - Produces summary JSON report
  - **Implements: R2.1, R3.1, R3.2, R3.3, R3.4, R3.5, R4.4, R4.5, R5.1, R5.3, R8.1**

  - [ ]* 8.1 Unit tests for orchestrator (local backend)
    - --tenants all resolves to full catalog
    - --resume skips completed stages
    - --mode diff with no drift → exit early
    - Stage ordering: S1 before S2-S6, S7 after S2+S3
    - --dry-run: plans printed, no execution
    - Concurrency limit respected (mock timing)
    - File: `mcp_server_python/tests/unit/test_orchestrator.py` (new)
    - **Validates: R2.1, R3.1–R3.5, R5.3, R8.4**

- [ ]* 9. Write property tests P5 + P6 + P7 (drift, checkpoint, idempotence)
  - **Property 5: Drift Detection Correctness** — correct SHA comparison
  - **Property 6: Checkpoint/Resume Correctness** — resumed run executes only remaining stages
  - **Property 7: Stage Idempotence** — double-run = single-run via MERGE
  - File: `mcp_server_python/tests/properties/test_scalable_ingestion_props.py`
  - **Validates: R4.4, R5.1, R5.3, R5.4**

### Phase 3 — SageMaker Integration (production scale-out)

- [ ] 10. Implement `_sagemaker_submitter.py`
  - Per design §5. New file: `mcp_server_python/scripts/_sagemaker_submitter.py`
  - `SageMakerJobConfig` dataclass (instance_type, role_arn, image_uri, subnets, security_groups, efs config, max_runtime)
  - `SageMakerSubmitter(config)` with `submit_job()`, `wait_for_completion()`, `get_job_status()`
  - Job container entrypoint: `python scripts/orchestrate_ingestion.py --backend local --tenants {tid} ...` (recursion into local mode inside the container)
  - **Implements: R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.7**

  - [ ]* 10.1 Unit tests for SageMaker submitter
    - Mock boto3.client('sagemaker') — verify create_processing_job call shape
    - VPC config includes correct subnets + SG
    - EFS filesystem config correct
    - Instance type passed through
    - File: `mcp_server_python/tests/unit/test_sagemaker_submitter.py` (new)
    - **Validates: R2.2–R2.7**

- [ ] 11. Create IAM role for SageMaker Processing (GATED — admin action)
  - STOP-AND-CONFIRM before IAM changes
  - Create `mdc-mcp-rag-sagemaker-processing-role` with trust policy for sagemaker.amazonaws.com
  - Permissions: Neptune, OpenSearch, S3 (mdc-mcp-rag-artifacts bucket), EFS mount, CloudWatch, ECR pull, Secrets Manager (GitHub token)
  - No IAM write, no infrastructure create/delete
  - File: `infrastructure/iam/sagemaker-processing-role.json` (policy document)
  - **Implements: R9.1, R9.2, R9.3, R9.4**

- [ ] 12. Wire SageMaker backend into orchestrator
  - Extend `orchestrate_ingestion.py`: when `--backend sagemaker`, use SageMakerSubmitter instead of local execution
  - One SageMaker job per tenant (concurrent via asyncio.Semaphore)
  - Wait for all jobs to complete, collect results, produce summary
  - **Implements: R2.1, R3.1, R3.2, R3.3, R6.1, R6.2**

- [ ]* 13. Write property tests P3 + P4 (concurrency limit + failure isolation)
  - **Property 3: Concurrency Limit** — never exceeds --max-concurrent
  - **Property 4: Tenant Failure Isolation** — one failure doesn't cascade
  - Mock SageMaker submission (controlled timing + random failures)
  - File: `mcp_server_python/tests/properties/test_scalable_ingestion_props.py`
  - **Validates: R3.3, R3.4**

### Phase 4 — Observability + Hardening

- [ ] 14. Implement `_metrics.py` (CloudWatch custom metrics)
  - Per design §6. New file: `mcp_server_python/scripts/_metrics.py`
  - `MetricsEmitter` class with `emit_stage_complete()`, `emit_run_complete()`, `emit_alert()`
  - Namespace: `MDC-MCP-RAG/Ingestion`
  - Dimensions: TenantId, Stage, Backend
  - Wire into orchestrator: emit metrics after each stage and at run completion
  - **Implements: R7.1, R7.2**

- [ ] 15. Implement SNS alerting
  - Create SNS topic `mdc-mcp-rag-ingestion-alerts`
  - Publish when: job failure, parse_success_rate < 80%, stage timeout
  - Wire into orchestrator's error handling
  - **Implements: R7.3**

- [ ] 16. Implement webhook handler (Lambda trigger)
  - Per design §7. New file: `lambda/ingestion_trigger.py`
  - Receives branch push event (API Gateway or EventBridge)
  - Resolves branch → tenant_id from catalog
  - Checks drift (compare HEAD to last-ingested SHA)
  - If drift: triggers orchestrator (invoke SageMaker job for --mode diff)
  - **Implements: R4.1, R4.2, R4.3**

### Phase A — Gated Operational Validation

- [ ] 17. Phase A — Validate parallel Fortran on EC2 (GATED)

  - [ ] 17.1 Run parallel Fortran dry-run for gw_v17
    - `python3.12 scripts/ingest_fortran_graph_v8.py --tenant gw_v17 --mode full --workers 3 --timeout 120 --dry-run`
    - Compare: same file count + parse success rate as the 37h run (~85%)
    - Verify: completes in <4 hours on 4-core EC2
    - **Validates: R1 (live)**

  - [ ] 17.2 Validate orchestrator local mode (all stages)
    - `python3.12 scripts/orchestrate_ingestion.py --tenants gw_v17 --backend local --mode full --workers 3 --dry-run`
    - Verify: all 7 stages planned in correct order
    - **Validates: R2.1, R8.1 (live)**

- [ ] 18. Phase B — Validate SageMaker (GATED — requires Phase 3 IAM role)

  - [ ] 18.1 STOP-AND-CONFIRM before SageMaker job submission
    - Writes to Neptune/OpenSearch from a SageMaker instance
    - Costs real compute time ($)
    - Confirm instance type + max runtime

  - [ ] 18.2 Submit single-tenant SageMaker job for gw_v17
    - `python3.12 scripts/orchestrate_ingestion.py --tenants gw_v17 --backend sagemaker --mode full --workers 15`
    - Monitor via CloudWatch Logs
    - Verify: completes in <2 hours on ml.m5.4xlarge
    - **Validates: R2, R6 (live)**

  - [ ] 18.3 Submit multi-tenant concurrent job
    - `python3.12 scripts/orchestrate_ingestion.py --tenants gw_v17,gw_sfs --backend sagemaker --max-concurrent 2`
    - Verify: both tenants process concurrently, independent results
    - **Validates: R3 (live)**

- [ ] 19. Final Checkpoint — spec complete
  - All unit + property tests green
  - Parallel Fortran validated (Phase A)
  - SageMaker validated (Phase B)
  - CloudWatch metrics visible, SNS alerts firing on failure
  - Ask the user if questions arise

## Notes

- **Phase 1 is the highest-value, lowest-risk work** — pure Python refactoring, no AWS
  infra changes, immediately testable on the current EC2. It alone solves the 37h→2h
  problem for the common case (running on a SageMaker 16-core is Phase 3 gravy).
- **Phase 2 adds coordination** without requiring SageMaker — the orchestrator's
  `--backend local` mode works on the EC2 for quick ingestions and testing.
- **Phase 3 is the infrastructure phase** — IAM role creation (admin action), VPC/EFS
  config for SageMaker. Has external dependencies (admin approval for IAM).
- **Phase 4 is hardening** — not strictly needed for the system to work, but necessary
  for production confidence (alerting on failures, drift monitoring).
- **The _parallel_runner is the linchpin** — it's used by Fortran, shell, and
  potentially config/EXPDIR stages. Getting it right (especially the timeout mechanism)
  is critical.
- **Backward compatibility is non-negotiable** — `--workers 1 --timeout 0` must produce
  identical behavior to the current serial scripts.
- **SageMaker job = orchestrator in local mode inside a container** — the SageMaker job's
  entrypoint is just `orchestrate_ingestion.py --backend local`. This keeps the code
  unified and testable locally.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "1.1"] },
    { "id": 1, "tasks": ["2", "2.1", "3"] },
    { "id": 2, "tasks": ["4"] },
    { "id": 3, "tasks": ["5"] },
    { "id": 4, "tasks": ["6", "6.1", "7", "7.1"] },
    { "id": 5, "tasks": ["8", "8.1"] },
    { "id": 6, "tasks": ["9"] },
    { "id": 7, "tasks": ["10", "10.1"] },
    { "id": 8, "tasks": ["11"] },
    { "id": 9, "tasks": ["12", "13"] },
    { "id": 10, "tasks": ["14", "15", "16"] },
    { "id": 11, "tasks": ["17.1", "17.2"] },
    { "id": 12, "tasks": ["18.1"] },
    { "id": 13, "tasks": ["18.2", "18.3"] },
    { "id": 14, "tasks": ["19"] }
  ]
}
```
