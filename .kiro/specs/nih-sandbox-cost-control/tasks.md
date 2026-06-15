# Implementation Plan — `nih-sandbox-cost-control`

## Overview

Build the `Cost_Control_System` in two cooperating subsystems: a declarative
CDK app (`SETUP_AWS/provisioning/cdk/`) that defines four layered stacks, and
an imperative Python orchestrator (`SETUP_AWS/provisioning/cost_control/`) that
sequences the sleep/wake AWS API calls. Delivered bottom-up: shared primitives
(state file, audit, costs) first, then per-tier sleep/wake logic with
moto-backed unit tests, then the state machine that composes them, then the CDK
stacks, then the IAM role generated from the finished orchestrator source, then
the gated live acceptance cycle.

Every code change carries unit tests. Property tests cover the seven
correctness properties from the design. Destructive live operations are
operator-gated. The orchestrator ships a `--dry-run` from the first wave so no
mutation can happen before the plan is reviewed.

All paths are relative to the workspace root `/mdc-mcp-rag/eib-mcp-rag-server/`.

## Tasks

- [ ] 1. Scaffold the orchestrator package and shared config
  - Create `SETUP_AWS/provisioning/cost_control/` with `__init__.py`,
    `config.py`, and a `tests/` subdir.
  - `config.py`: resolve `Environment_Name` → resource ids/ARNs (EC2 instance
    id, Neptune cluster id, OpenSearch domain name, AgentCore runtime ARN, NAT
    Gateway id, S3 bucket names, VPC/subnet/SG ids) from a per-env mapping plus
    env-var overrides. Reuse the `_ingest_common` boto3 session pattern for
    credential/region resolution.
  - Define the `valid_environments` allow-list (`dev`, `staging`, `prod`) and
    reject any other env value.
  - _Requirements: 13.1, 13.4, 16.1_

  - [ ]* 1.1 Config unit tests
    - Valid env resolves; invalid env is rejected; env-var override precedence.
    - _Requirements: 13.1, 13.4_

- [ ] 2. Implement the audit logger
  - `audit.py`: emit one JSON object per line with the R9 field set
    (`timestamp`, `event_type`, `operation_id`, `caller_arn`,
    `environment_name`, `state_before`, `state_after`, `tier`,
    `aws_resource_arns`, `snapshot_ids`, `elapsed_seconds`,
    `estimated_savings_usd_per_hour`, `error`).
  - Write to the CloudWatch log group `mdc-mcp-rag-cost-control-{env}` and
    buffer all records for one operation into a single S3 object
    `s3://<audit-bucket>/cost-control/<env>/<operation_id>.jsonl` flushed on
    completion or failure.
  - ASCII-only console mirror (`[OK]`/`[ERROR]`/`[WARN]`/`[INFO]`/`[SKIP]`).
  - _Requirements: 9.1, 9.2, 9.3, 9.4_

  - [ ]* 2.1 Audit unit tests
    - Record contains all required fields; failure records carry `error`;
      per-op S3 object written exactly once; ASCII-only assertion.
    - _Requirements: 9.1, 9.3_

- [ ] 3. Implement the state file with S3 optimistic locking
  - `state_file.py`: read the JSON object + ETag; write back with
    `IfMatch=<etag>`; map `PreconditionFailed` (412) to a typed
    `ConcurrentOperationError`.
  - Enforce the schema from the design (`schema_version`, `current_state`,
    `previous_state`, `last_transition_at`, `last_caller_arn`,
    `operation_counter`, `environment_name`, `latest_snapshots`, `manifest`).
  - Increment `operation_counter` by exactly 1 per write; refuse on counter
    mismatch.
  - Handle missing/corrupt/unknown-state object explicitly (typed error, no
    crash).
  - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [ ]* 3.1 State file unit tests + Property 7 (concurrency)
    - Stale-ETag write → `ConcurrentOperationError`; counter monotonicity;
      missing-object and corrupt-object handling; schema validation.
    - Property 7: two simulated racing writers, at most one succeeds.
    - _Requirements: 8.3, 8.4, 7.3, 7.4_

- [ ] 4. Implement the cost model
  - `costs.py`: per-resource USD/hr table for `Active_Mode` and `Sleep_State`
    (EC2, Neptune, OpenSearch active vs single-node, NAT). Compute hourly
    savings and total-window savings (fractional hours, 1-second precision).
  - Provide the savings figures the audit records consume.
  - _Requirements: 5.1, 5.3, 5.4_

  - [ ]* 4.1 Cost model unit tests + Property 5 (savings floor)
    - Sleep-state sum ≤ 20% of active sum; zero-resource edge case → `0.00`;
      window math at 1-second precision.
    - _Requirements: 5.1, 5.3_

- [ ] 5. Implement the snapshot manager
  - `snapshots.py`: per-tier create + wait-for-terminal-status + verify, with
    the design's per-tier timeouts and polling cadence:
    - Neptune `create_db_cluster_snapshot` → wait `available`.
    - OpenSearch manual snapshot to the registered S3 repo → wait `SUCCESS`.
    - EC2 root EBS snapshot (only if latest is older than max age) → wait
      `completed`.
  - Snapshot ID naming `cc-{env}-{op_short}-{utc_compact}-{tier}`.
  - On timeout or failure status: abort, return a typed error, do NOT proceed
    to the destructive call; leave the source tier untouched.
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [ ]* 5.1 Snapshot manager unit tests (botocore Stubber)
    - Success path reaches terminal status; timeout aborts before destructive
      call; failure status aborts; ID convention; retention tag applied.
    - _Requirements: 4.1, 4.2, 4.5_

- [ ] 6. Define the Tier protocol and implement the EC2 tier
  - `tiers/__init__.py`: `Tier` protocol with `plan(mode)`, `hibernate()`,
    `wake()`, `is_asleep()`, `capture_manifest()`.
  - `tiers/ec2_tier.py`: `stop_instances` / `start_instances`; pre-stop EBS
    snapshot via the snapshot manager only when stale; `is_asleep()` checks
    instance state; manifest captures instance id + root volume id.
  - _Requirements: 1.3, 2.x, 3.4, 4.3_

  - [ ]* 6.1 EC2 tier unit tests (botocore Stubber)
    - hibernate stops the instance; wake starts it; destructive call not issued
      before snapshot success; `is_asleep()` correctness.
    - _Requirements: 4.3_

- [ ] 7. Implement the Neptune tier
  - `tiers/neptune_tier.py`: snapshot → `stop_db_cluster` on hibernate;
    `start_db_cluster` → wait `available` on wake; `capture_manifest()` records
    per-tenant node/relationship counts (via the graph adapter) for the
    round-trip property; `is_asleep()` checks cluster status.
  - _Requirements: 1.3, 3.1, 4.1_

  - [ ]* 7.1 Neptune tier unit tests
    - snapshot-before-stop ordering; manifest count capture; wake start + wait;
      idempotent `is_asleep()`.
    - _Requirements: 3.1, 4.1_

- [ ] 8. Implement the Neptune 7-day re-sleep guard Lambda
  - `cost_control/lambdas/neptune_resleep.py`: if `State_File.current_state ==
    Sleep_State` and the cluster is found `available`, re-issue
    `stop_db_cluster` and emit a `Resleep_Triggered` audit record.
  - Packaged for the EventBridge daily rule (wired in the CDK Compute stack,
    Task 13).
  - _Requirements: 3.1 (Neptune caveat), 9.4_

  - [ ]* 8.1 Re-sleep guard unit tests
    - Re-stops only when asleep + cluster up; no-op otherwise.
    - _Requirements: 3.1_

- [ ] 9. Implement the OpenSearch tier (scale-down primary path)
  - `tiers/opensearch_tier.py`: manual snapshot (always, safety net) →
    `update_domain_config` to single `t3.small.search` on hibernate;
    `update_domain_config` back to production config on wake; wait for
    `Processing == false` between transitions; manifest captures per-index doc
    counts. Stub the deep-sleep delete+restore path behind a mode flag for a
    later wave (documented, not wired).
  - _Requirements: 1.3, 3.2, 4.2_

  - [ ]* 9.1 OpenSearch tier unit tests
    - snapshot-before-scale ordering; scale-down then scale-up config deltas;
      doc-count manifest capture; wait-for-processing gating.
    - _Requirements: 3.2, 4.2_

- [ ] 10. Implement the AgentCore and NAT tiers
  - `tiers/agentcore_tier.py`: no-op hibernate (definition is free); record
    runtime ARN + image digest in manifest; wake re-points DEFAULT endpoint via
    `update_agent_runtime` only if drift shows the runtime/image changed. Use
    the `aws-agentcore` power tools where possible.
  - `tiers/nat_tier.py`: delete NAT Gateway + release EIP on hibernate; wake is
    a no-op here because the CDK Compute deploy recreates NAT (Task 13). Record
    NAT id / EIP allocation in manifest.
  - _Requirements: 1.3, 2.x, 3.x_

  - [ ]* 10.1 AgentCore + NAT tier unit tests
    - AgentCore hibernate mutates nothing; NAT delete issued; manifest capture.
    - _Requirements: 3.3_

- [ ] 11. Implement drift detection
  - `drift.py`: capture the manifest at hibernate; at wake, diff the
    storage-tier reality (snapshot availability, ECR image digests, index list,
    bucket retention) against the manifest. Classify each delta as
    data-preserving (auto-reconcile + `Drift_Reconciled`) or data-destructive
    (`Drift_Detected`, refuse, exit before any compute creation unless
    `--force-drift`).
  - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [ ]* 11.1 Drift classification unit tests
    - Table-driven: added ECR tag → preserving; missing snapshot / deleted
      referenced image / changed retention → destructive; `--force-drift`
      override path.
    - _Requirements: 10.2, 10.3_

- [ ] 12. Implement the wake validation probe
  - `wake_probe.py`: for each tenant in `tenants.yaml`, call
    `mcp_health_check` and `get_knowledge_base_status` (via the AgentCore
    endpoint), assert gw reports `develop` with non-zero counts and each
    non-default tenant whose pre-sleep counts were non-zero reports its branch
    with non-zero counts. Retry per the design (5 attempts × 30 s) inside the
    wake budget.
  - _Requirements: 12.1, 12.2, 12.3, 12.4_

  - [ ]* 12.1 Wake probe unit tests
    - Mocked all-tenant responses: pass path; each fail mode (wrong
      attribution, zero counts, unreachable) routes to `Wake_Failed`.
    - _Requirements: 12.2, 12.3, 12.4_

- [ ] 13. Implement the state machine and CLI
  - `state_machine.py`: legal transition table; per-tier sequencing
    (hibernate order: EC2 → Neptune → OpenSearch → AgentCore → NAT; wake
    reversed); `--resume` from degraded states using per-tier `is_asleep()`
    idempotent skips; idempotent no-ops in terminal states; concurrency refusal
    via the state file lock.
  - `cli.py`: argparse `{hibernate|wake|status} [--env] [--yes] [--dry-run]
    [--resume] [--force-drift]`. `status` prints the parsed state file without
    locking. `--dry-run` prints every tier `plan()` with zero mutation.
    Interactive `Confirmation_Gate` (exact phrase) before any destructive call;
    `--yes` substitutes a recorded token.
  - Wire savings figures into `Sleep_Completed` / `Wake_Completed` records;
    enforce the wake wall-clock budget with per-tier progress records every ≤5
    min.
  - _Requirements: 1.1, 1.2, 1.4, 1.5, 2.1, 2.2, 2.4, 2.5, 6.1, 6.2, 6.3, 7.1, 7.2, 7.3, 7.4, 8.5, 15.1, 15.2, 15.3, 15.4_

  - [ ]* 13.1 State machine + CLI unit tests + Properties 3, 4, 6
    - Every legal/illegal transition; Property 3 (terminal no-op); Property 4
      (kill mid-transition leaves a defined state, `--resume` continues);
      Property 6 (no destructive call before confirmation/`--yes`); `--dry-run`
      mutates nothing; `status` does not lock.
    - _Requirements: 1.5, 2.5, 7.1, 7.2, 15.3_

  - [ ]* 13.2 Property 1 + Property 2 round-trip tests (moto)
    - Property 1: moto-backed hibernate→wake leaves per-tier manifest counts
      equal.
    - Property 2: assert no API call targets any Storage-stack ARN, EFS, or ECR
      tag during either transition.
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [ ] 14. Build the CDK app — Storage, IAM, Network stacks
  - `SETUP_AWS/provisioning/cdk/`: CDK app (TypeScript or Python — match repo
    convention) defining `MdcMcpRag-Storage-{env}` (EFS, ECR `RETAIN`, S3
    state/audit/snapshot buckets versioned + lifecycle, OpenSearch snapshot
    repo target), `MdcMcpRag-IAM-{env}` (placeholder orchestrator role refined
    in Task 16, OpenSearch snapshot role, re-sleep Lambda role), and
    `MdcMcpRag-Network-{env}` (VPC, subnets, route tables, SGs, VPC endpoints —
    NO NAT). Cross-stack exports per the design.
  - Validate every synthesized template with `validate_cloudformation_template`
    (cfn-lint) and `check_cloudformation_template_compliance` (cfn-guard) via
    the `aws-infrastructure-as-code` power. Fix findings.
  - _Requirements: 11.1, 11.2, 11.3, 11.4, 13.1, 13.2_

  - [ ]* 14.1 CDK assertion tests (Storage/IAM/Network)
    - `Template.fromStack` asserts Storage/Network declare no per-hour resource;
      IAM declares the required roles; env-suffixed names + environment tag.
    - _Requirements: 11.2, 11.3, 11.4, 13.2_

- [ ] 15. Build the CDK app — Compute stack
  - `MdcMcpRag-Compute-{env}`: EC2 instance, Neptune cluster + instance,
    OpenSearch domain, NAT Gateway, AgentCore runtime reference, EventBridge
    re-sleep rule + Lambda, optional Schedule_Mode rule (off by default behind
    `schedule_enabled` context). Imports Storage/IAM/Network exports.
  - cfn-lint + cfn-guard clean.
  - _Requirements: 11.5, 11.6, 14.1, 14.2, 14.3, 14.4_

  - [ ]* 15.1 CDK assertion tests (Compute)
    - Compute owns EC2 + Neptune + OpenSearch + NAT; imports (not redeclares)
      storage/network; Schedule_Mode disabled by default.
    - _Requirements: 11.5, 14.2_

- [ ] 16. Generate and apply the least-privilege orchestrator IAM policy
  - Run `iam-policy-autopilot-power.generate_application_policies` over the
    finished `cost_control/` source to derive the minimal action set
    (ec2:Stop/Start/CreateSnapshot, neptune:Stop/Start/CreateDBClusterSnapshot,
    es:UpdateDomainConfig/CreateSnapshot, cloudformation:* for NAT recreate,
    s3 on the three buckets, logs). Review, then wire the generated policy into
    `MdcMcpRag-IAM-{env}`.
  - _Requirements: 11.3 (IAM), design IAM section_

- [ ] 17. CHANGELOG and full-suite gate
  - CHANGELOG entry under the next minor version (new feature, not a patch).
  - `cd SETUP_AWS/provisioning && python3.12 -m pytest cost_control/tests/ -q`
    green; CDK assertion tests green; `py_compile` clean.
  - Deliver `SETUP_AWS/provisioning/RUNBOOK_cost_control.md` documenting
    hibernate/wake/status/drift-override/Schedule_Mode procedures and the
    per-resource cost table that justifies the 80% target (R5.2), modeled on
    `RUNBOOK_agentcore_creds.md`.
  - _Requirements: 5.2, 16.2_

- [ ] 18. Phase A — gated CDK deploy (Storage/IAM/Network first)
  - STOP-AND-CONFIRM before `cdk deploy`.
  - Deploy the three never-destroyed stacks for the `dev` env first; verify
    buckets versioned, OpenSearch snapshot repo registerable, roles present.
  - _Requirements: 11.1, 13.1_

- [ ] 19. Phase B — gated live hibernate → wake acceptance cycle
  - STOP-AND-CONFIRM before the first real `hibernate`.
  - On `dev`: `--dry-run` first; then `hibernate --env dev`; confirm
    `Sleep_State`, snapshots `available`, ≥80% savings figure in the audit
    record; then `wake --env dev`; confirm `Wake_State`, the
    `Wake_Validation_Probe` passes for all tenants, and Property 1 holds
    (post-wake counts equal the pre-sleep manifest). Measure wake wall-clock
    against the 60-min SLA.
  - Record runtime/snapshot ids and the savings figure. Rollback: `wake` if a
    hibernate half-completes.
  - _Requirements: 1.x, 2.x, 3.1, 3.2, 5.1, 6.1, 12.x (live)_

- [ ] 20. Final checkpoint
  - All unit + property + CDK tests green.
  - Phase A and Phase B live runs documented with audit captures.
  - Runbook posted; orchestrator IAM policy reviewed and applied.
  - Update `.kiro/steering/12-multi-tenant-gap-tracker.md` (or a cost-control
    note) with the deployed state and the measured savings.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "1.1"] },
    { "id": 1, "tasks": ["2", "2.1", "3", "3.1", "4", "4.1", "5", "5.1"] },
    { "id": 2, "tasks": ["6", "6.1", "7", "7.1", "8", "8.1", "9", "9.1", "10", "10.1", "11", "11.1", "12", "12.1"] },
    { "id": 3, "tasks": ["13", "13.1", "13.2"] },
    { "id": 4, "tasks": ["14", "14.1", "15", "15.1"] },
    { "id": 5, "tasks": ["16"] },
    { "id": 6, "tasks": ["17"] },
    { "id": 7, "tasks": ["18"] },
    { "id": 8, "tasks": ["19"] },
    { "id": 9, "tasks": ["20"] }
  ]
}
```

Wave 0 scaffolds the package. Wave 1 builds the shared primitives (audit,
state file, costs, snapshots) — all independent, parallelizable. Wave 2 builds
the per-tier sleep/wake logic on top of those primitives, plus drift and the
wake probe — independent per tier. Wave 3 composes them in the state machine +
CLI and lands the round-trip property tests. Wave 4 builds the CDK stacks
(validated with cfn-lint/cfn-guard). Wave 5 generates the orchestrator IAM
policy from the finished source. Wave 6 is the CHANGELOG + suite + runbook gate.
Waves 7-9 are the operator-gated live deploy, the live hibernate→wake
acceptance cycle, and the final checkpoint.

## Notes

- **Two subsystems**: CDK (`cdk/`) is declarative baseline + NAT recreate;
  the orchestrator (`cost_control/`) is the imperative sleep/wake engine. They
  share only the state/audit/snapshot S3 buckets and the resource ids in
  `config.py`.
- **Bottom-up with tests**: shared primitives → tiers → state machine → CDK →
  IAM → live. Every code task has a paired `*` test task. The seven correctness
  properties are covered in 3.1 (P7), 4.1 (P5), 13.1 (P3, P4, P6), 13.2 (P1,
  P2).
- **`--dry-run` from Wave 3**: no mutation can occur before the plan is
  reviewed. The first invocation in any env must be a dry-run.
- **Operator gates**: every `cdk deploy`, the first live `hibernate`, and the
  first live `wake` are STOP-AND-CONFIRM, per the existing provisioning
  convention.
- **Powers**: `aws-infrastructure-as-code` validates every CDK template
  (Tasks 14, 15); `iam-policy-autopilot` generates the orchestrator role
  (Task 16); `aws-agentcore` drives the AgentCore tier (Task 10);
  `opensearch-launchpad` is referenced for the deep-sleep restore path (stubbed
  in Task 9, deferred to a later wave per design Open Question 1).
- **No auto-commit**: CHANGELOG noted, commits only on operator request, per
  `08-git-operation-policy.md`.
- **Data preservation is the contract**: Property 1 (count round-trip) and
  Property 2 (storage immutability) gate the live acceptance in Task 19. A
  regression there is a fix-the-code moment, never a weaken-the-test moment.
