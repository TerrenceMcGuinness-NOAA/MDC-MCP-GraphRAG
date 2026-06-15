# Runbook -- Cost_Control_System (hibernate / wake)

Operator runbook for the `Cost_Control_System`, the sleep/wake automation that
hibernates the MDC MCP-RAG platform's per-hour compute footprint to a near-zero
hourly cost and later restores it to a fully query-serving state, preserving
all ingested data. Spec: `.kiro/specs/nih-sandbox-cost-control/`.

Two cooperating subsystems, both under `SETUP_AWS/provisioning/`:

- `cost_control/` -- the imperative Python orchestrator (the sleep/wake engine).
- `cdk/` -- the declarative four-stack CDK app (Storage / IAM / Network /
  Compute) that defines the baseline and recreates the NAT Gateway on wake.

> Modeled on `SETUP_AWS/provisioning/RUNBOOK_agentcore_creds.md`.

## Prerequisites

- The four CDK stacks are deployed for the target environment (see "CDK
  deploy", below). Stacks are env-suffixed: `MdcMcpRag-Storage-dev`, etc.
- The operator (or CI role) can assume the orchestrator role
  `mdc-mcp-rag-cost-control-orchestrator-{env}` (least-privilege action set in
  `cdk/lib/orchestrator-policy.ts`).
- Python 3.12 with `boto3`. Run from `SETUP_AWS/provisioning/`.

## State model

The platform is always in exactly one of seven states, recorded in the S3
State_File (`s3://mdc-mcp-rag-cost-control-state-{env}/cost-control/{env}/state.json`):

```
Active_Mode --hibernate--> Sleeping --> Sleep_State
Sleep_State --wake--------> Waking ----> Wake_State (== Active_Mode)
  failure after destruction begins   -> Active_Mode_Degraded  (hibernate --resume)
  probe fail / wake timeout           -> Sleep_State_Degraded  (wake --resume)
  Sleeping / Waking + new command     -> Concurrent_Operation_Refused (exit non-zero)
```

Re-issuing `hibernate` while asleep, or `wake` while awake, is a safe no-op
(exit 0).

## Commands

All commands run from `SETUP_AWS/provisioning/`:

```bash
python3.12 -m cost_control.cli status   --env dev
python3.12 -m cost_control.cli hibernate --env dev [--dry-run] [--yes] [--resume]
python3.12 -m cost_control.cli wake      --env dev [--dry-run] [--yes] [--resume] [--force-drift]
```

### status (read-only, never locks)

```bash
python3.12 -m cost_control.cli status --env dev
```

Prints the parsed State_File (current/previous state, last transition, caller,
operation counter, latest snapshots). Acquires no lock and mutates nothing.

### Dry run first (mandatory on a new environment)

```bash
python3.12 -m cost_control.cli hibernate --env dev --dry-run
```

Prints every tier's planned actions (destructive steps flagged) with **zero
mutation**. Always dry-run before the first real transition in any environment.

### hibernate (Active_Mode -> Sleep_State)

```bash
python3.12 -m cost_control.cli hibernate --env dev
```

Sequence (dependency order): EC2 -> Neptune -> OpenSearch -> AgentCore -> NAT.
For each data tier a snapshot is taken and confirmed in a terminal success
status **before** the destructive call:

- EC2: pre-stop EBS root snapshot only if the latest is stale, then
  `stop_instances`.
- Neptune: `create_db_cluster_snapshot` -> wait `available` -> `stop_db_cluster`.
- OpenSearch: manual snapshot (always) -> wait `SUCCESS` -> scale down to a
  single `t3.small.search` -> wait `Processing == false`.
- AgentCore: no-op (the runtime definition is free when idle).
- NAT: `delete_nat_gateway` + release the Elastic IP.

You will be shown the resolved environment, the resources affected, and the
snapshots that will be created, then prompted for the exact confirmation
phrase:

```
hibernate dev
```

`Sleep_Completed` records the estimated USD/hr savings. On failure after the
destructive transition begins, the State_File goes to `Active_Mode_Degraded`;
recover with `hibernate --resume`.

### wake (Sleep_State -> Wake_State)

```bash
python3.12 -m cost_control.cli wake --env dev
```

Drift detection runs first (see below). Then tiers wake in reverse order
(NAT -> AgentCore -> OpenSearch -> Neptune -> EC2); the NAT Gateway is recreated
by `cdk deploy MdcMcpRag-Compute-{env}` (run that before/with wake). After all
compute is up, the `Wake_Validation_Probe` confirms every tenant in
`tenants.yaml` resolves with non-zero counts. Confirmation phrase: `wake dev`.

`Wake_Completed` records the total USD saved over the sleep window. A probe
failure or budget overrun leaves `Sleep_State_Degraded`; recover with
`wake --resume`.

### Non-interactive (CI / scheduled)

`--yes` substitutes a recorded confirmation token for the interactive prompt
and is logged in the audit trail. Use only from trusted CI / the Schedule_Mode
Lambda.

## Drift override

On wake, `Drift_Reconciliation` compares the storage tier against the manifest
captured at the last hibernate. Data-preserving differences (e.g. a new ECR
image tag) are auto-reconciled (`Drift_Reconciled`). A data-destructive
difference (missing snapshot, deleted runtime-referenced image, disappeared
index, changed bucket retention) emits `Drift_Detected`, leaves the State_File
in `Sleep_State`, and exits non-zero **before any compute is created**.

After investigating and confirming the drift is safe, override with:

```bash
python3.12 -m cost_control.cli wake --env dev --force-drift
```

`--force-drift` proceeds despite detected drift; the override and the resolved
differences are recorded in the audit trail.

## Schedule_Mode (off by default)

Recurring sleep/wake is disabled by default. To enable it, deploy the Compute
stack with the schedule context values:

```bash
cd SETUP_AWS/provisioning/cdk
npx cdk deploy MdcMcpRag-Compute-dev \
  -c env=dev \
  -c schedule_enabled=true \
  -c 'sleep_cron=cron(0 0 ? * MON-FRI *)' \
  -c 'wake_cron=cron(0 12 ? * MON-FRI *)'
```

This registers EventBridge rules that invoke the same hibernate/wake code path
as the CLI (with the `--yes` token). The idempotency and concurrency-refusal
rules still apply. Omitting `schedule_enabled=true` leaves only the always-on
daily Neptune re-sleep guard rule.

## Neptune 7-day re-sleep guard

Neptune force-starts a stopped cluster after 7 days. A daily EventBridge rule
invokes the `mdc-mcp-rag-cost-control-resleep-{env}` Lambda, which re-issues
`stop_db_cluster` iff the State_File says `Sleep_State` and the cluster is found
`available` (emitting `Resleep_Triggered`). No action needed from the operator.

## Per-resource cost table (justifies the >=80% target -- R5.2)

Reference figures (us-east-1, on-demand) from `cost_control/costs.py`. Storage
GB-month and one-time request charges are excluded per R5.1.

| Resource | Active_Mode USD/hr | Sleep_State USD/hr | Sleep mechanism |
|----------|-------------------:|-------------------:|-----------------|
| EC2 (t3.large) | 0.0832 | 0.0000 | `stop_instances` |
| Neptune (db.r5.large) | 0.3480 | 0.0000 | `stop_db_cluster` |
| OpenSearch (r6g.large.search x1 vs t3.small.search x1) | 0.8000 | 0.0360 | scale down |
| NAT Gateway | 0.0450 | 0.0000 | delete + recreate on wake |
| **Total** | **1.2762** | **0.0360** | |

Savings = 1.2762 - 0.0360 = **1.2402 USD/hr**, a **97.2%** reduction --
comfortably above the 80% floor. The single Sleep_State residual is the
scaled-down OpenSearch node; the deep-sleep delete+restore path (documented,
not wired) drives it to ~0 for multi-week windows at the cost of a longer wake.

`Property 5` (savings floor) is asserted in
`cost_control/tests/test_costs.py::test_property5_savings_floor_default_table`.

## CDK deploy (operator-gated -- Wave 7, run separately)

```bash
cd SETUP_AWS/provisioning/cdk
npm ci                                  # or reuse infrastructure/cdk node_modules
npx cdk synth --all -c env=dev          # review templates
npx cdk diff  MdcMcpRag-Storage-dev -c env=dev   # MANDATORY: review for [-] deletions
npx cdk deploy MdcMcpRag-Network-dev MdcMcpRag-Storage-dev MdcMcpRag-IAM-dev -c env=dev
npx cdk deploy MdcMcpRag-Compute-dev -c env=dev
```

Per CDK data-safety rule 05: every stateful resource carries
`DeletionPolicy: Retain`; always run `cdk diff` and review for unintended
deletions before `cdk deploy`. The re-sleep Lambda's inline placeholder code is
replaced at deploy time by the packaged `cost_control/lambdas/` asset.

## Audit trail

Every step emits a one-line JSON `Audit_Log_Record` to the CloudWatch log group
`mdc-mcp-rag-cost-control-{env}` and, on completion/failure, a consolidated S3
object `s3://mdc-mcp-rag-cost-control-audit-{env}/cost-control/{env}/<operation_id>.jsonl`.
Console output is ASCII-only (`[OK]` / `[ERROR]` / `[WARN]` / `[INFO]` /
`[SKIP]`).
