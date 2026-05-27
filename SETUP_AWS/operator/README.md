# SETUP_AWS/operator — Operator-user scripts

Scripts in this directory run as **your operator user** — the AWS
principal with PowerUser-style permissions. They make AWS API calls
that require IAM permissions the EC2 instance role does not have
(e.g. `ec2:AuthorizeSecurityGroupIngress`).

**Do not run these with sudo.** Under sudo, the AWS CLI on this host
falls back to the EC2 instance role (e.g. `SSMrole`), which is
deliberately scoped narrowly and will fail with `UnauthorizedOperation`
on most EC2 mutating actions.

## When to run

- Once, after a fresh provisioning of this host
  (after `SETUP_AWS/provisioning/provision.sh` completes)
- Anytime the operator host needs to re-sync AWS-side state that
  isn't yet in CDK (see `SETUP_AWS/DRIFT_REGISTER.md`)
- Before running EFS-mounting operator scripts like
  `mcp_server_python/scripts/populate_workflow_efs*.sh`

All scripts here are idempotent — safe to re-run.

## Scripts

- `sync-aws-resources.sh` — Sync ad-hoc AWS-side state (currently:
  EFS SG ingress for this operator host). Use `--check` for a
  dry-run report.

## Future plan

Eventually these scripts should be unnecessary — promote the items
they manage into CDK (`infrastructure/cdk/`). See
`SETUP_AWS/DRIFT_REGISTER.md` for the per-item promotion plan.
