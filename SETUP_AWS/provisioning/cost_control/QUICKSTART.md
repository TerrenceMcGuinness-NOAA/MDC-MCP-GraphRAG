# Quickstart -- Sandbox sleep / wake wrappers

Lightweight bash wrappers for hibernating and waking the **NIH Sandbox
prototype** compute footprint. Designed for the simple case where you just
want to pause the sandbox over a weekend / overnight / for funding-stretch
purposes without the full state-machine + CDK orchestration that
`RUNBOOK_cost_control.md` describes.

If you have the four CDK stacks deployed and want audit logging, drift
detection, and the 7-day Neptune auto-restart guard, use the full CLI
documented in `RUNBOOK_cost_control.md` instead.

## Scripts

| Script | What it does | Mutation |
|---|---|---|
| `quickstart-status.sh` | Reports state + per-resource hourly cost estimate | none |
| `quickstart-sleep.sh`  | Snapshots Neptune, stops it, scales OpenSearch down | destructive (after confirm) |
| `quickstart-wake.sh`   | Starts Neptune, scales OpenSearch back to production shape | non-destructive |
| `quickstart-config.sh` | Shared resource ids (sourced by the other three) | none -- config only |

## Usage

```bash
cd SETUP_AWS/provisioning/cost_control

./quickstart-status.sh                    # check current state
./quickstart-sleep.sh                     # interactive (type 'sleep' to confirm)
./quickstart-sleep.sh --yes               # non-interactive
./quickstart-wake.sh                      # waits for both to be awake
./quickstart-wake.sh --no-wait            # fire-and-forget
```

## What gets put to sleep

| Resource | Sleep action | Wake action | Daily savings |
|---|---|---|---|
| Neptune cluster `mdc-mcp-graprag-neptune-1` | Snapshot to `prehibernate-...` then `stop_db_cluster` | `start_db_cluster`, wait `available` | ~$39 |
| OpenSearch `mdc-mcp-rag-search` | Scale to `t3.small.search` x 1, single-AZ | Scale to `r6g.large.search` x 2, multi-AZ | ~$7 |
| **Total** | | | **~$46/day** |

What is **not** touched:
- AgentCore Runtime (`mdc_mcp_rag_server_python-...`) -- bills near-zero when
  idle, no benefit to deleting.
- EC2 host (`i-0907ea89fb15fd90a`) -- this is the dev box you run the
  scripts from. Stop it manually from your laptop's CLI if you want to save
  the $1.43/day.
- VPC endpoints, S3 buckets, EFS access points -- minimal cost and required
  on wake.

## Day-7 Neptune caveat

AWS automatically restarts stopped Neptune clusters after 7 days regardless
of operator intent. If the sandbox is still hibernated on day 6, re-run
`./quickstart-sleep.sh --yes` to put it back to sleep.

The full `cost_control` package ships a `lambdas/neptune_resleep.py` Lambda
that automates this guard, but it requires the CDK stacks to be deployed.
For the quickstart wrappers the manual day-6 re-stop is the workaround.

## Snapshots

Neptune snapshots taken by `quickstart-sleep.sh` use the id pattern:

```
prehibernate-mdc-mcp-graprag-neptune-1-<UTC-timestamp>
```

These persist as standard cluster snapshots in AWS, retrievable via:

```bash
aws neptune describe-db-cluster-snapshots \
  --snapshot-type manual \
  --db-cluster-identifier mdc-mcp-graprag-neptune-1 \
  --region us-east-1
```

OpenSearch manual snapshots to a customer S3 bucket are NOT created by
these wrappers because the IAM role required is currently blocked by
`PowerUserRestrictions` (see `docs/opensearch-snapshot-role-request.md` for
the admin request). The AWS-managed automated daily snapshot in
AWS-managed S3 is the fallback for OpenSearch.

## Override defaults

Every resource id in `quickstart-config.sh` honours an environment-variable
override of the same name. Example, to point at a hypothetical second
sandbox:

```bash
NEPTUNE_CLUSTER_ID=other-neptune \
OPENSEARCH_DOMAIN_NAME=other-os-domain \
./quickstart-status.sh
```

## When to graduate to the full CLI

Switch from these wrappers to `python3.12 -m cost_control.cli` when any
of these matter:

- Multiple environments (`dev` + `staging` + `prod`).
- Audit log of every transition (CloudWatch Logs + S3).
- Drift detection on wake (catches snapshot deletes, label-prefix changes,
  index settings drift, AgentCore container changes).
- 7-day Neptune auto-restart guard via Lambda.
- Recoverable-state tracking for partial-failure resume.

The full CLI requires the four CDK stacks deployed first
(`MdcMcpRag-{Storage,IAM,Network,Compute}-<env>`) -- see
`RUNBOOK_cost_control.md`.
