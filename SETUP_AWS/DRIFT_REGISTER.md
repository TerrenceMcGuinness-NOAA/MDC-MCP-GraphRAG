# SETUP_AWS Drift Register

This file tracks AWS-side state that has been **captured in
`SETUP_AWS/provisioning/`** but has **not yet been promoted to CDK**
(`infrastructure/cdk/`). It is a working register of operational
drift items. Entries should either:

1. Get promoted to CDK and removed from this register, or
2. Be revoked (removed from both AWS and the script) and removed
   from this register.

The register exists because `SETUP_AWS` is currently a **bootstrap
provisioning system** — it sets up a fresh EC2 host on first run.
It is **not a continuously-enforced configuration management system**
(no Ansible/Salt/Puppet/SSM State Manager). Entries here are
captured so that:

- A clean re-provision from `SETUP_AWS/` reaches a working state
- The intent and scope of each ad-hoc change is documented
- Promotion to CDK has a single audit trail

For OS-level packages added to `02-system-deps.sh` etc., this
register is descriptive — once dnf installs the package, it stays
on the host. For AWS-side resources (`09-aws-resources.sh`),
the register is **active**: each entry needs an eventual decision
(promote or revoke).

---

## Active entries

### EFS SG ingress: operator host → workflow EFS

| Field | Value |
|---|---|
| **Captured in** | `SETUP_AWS/operator/sync-aws-resources.sh` |
| **Resource type** | EC2 security-group rule |
| **EFS SG (target)** | `sg-04bd2b41beecd1201` (MdcDataStack EFS SG) |
| **Operator host SG (source)** | `sg-09bb60ffa41137076` (launch-wizard-1) |
| **Protocol/port** | TCP 2049 (NFS) |
| **Live rule ID** | `sgr-04b3d7802002780ce` |
| **Added** | 2026-05-27 (Phase 0 of `omd-tenants-1-foundation`) |
| **Why** | Required for `mcp_server_python/scripts/populate_workflow_efs*.sh` to mount EFS from this EC2 instance. The CDK `MdcDataStack` only allows ingress from the AgentCore ECS task SG — operator hosts need their own ingress to populate. |
| **Run-as** | Operator user (NOT root). The AWS API calls require EC2 ingress permissions which the EC2 instance role does not have. |
| **CDK location** | `infrastructure/cdk/lib/mdc-data-stack.ts` (the `MdcEfs` filesystem's connections block) |
| **Decision pending** | Revoke (steady-state) or promote to CDK (if we expect frequent re-populates). |
| **If revoked** | Re-run `SETUP_AWS/operator/sync-aws-resources.sh` to restore. |

### `amazon-efs-utils` package

| Field | Value |
|---|---|
| **Captured in** | `SETUP_AWS/provisioning/02-system-deps.sh` |
| **Resource type** | OS-level dnf package |
| **Host** | `i-0907ea89fb15fd90a` (and any future operator hosts) |
| **Added** | 2026-05-27 (Phase 0 of `omd-tenants-1-foundation`) |
| **Why** | Provides `mount.efs` helper used by `populate_workflow_efs*.sh`. Without it, `mount -t efs` fails with no EFS handler. |
| **CDK location** | N/A — OS-level, not in CDK. The right long-term home is either Ansible / SSM State Manager / Packer-built AMI (none currently exist). |
| **Decision pending** | None for now — captured in the bootstrap script, leave as-is until we have a config-management system. |

---

## Process for adding new entries

When you make an AWS-side or OS-level change that isn't yet in CDK:

1. **Add it to the right place:**
   - **OS-level (root-required)**: a numbered script under
     `SETUP_AWS/provisioning/`. Idempotency comes naturally from
     `dnf install -y` etc.
   - **AWS-side (operator-user-required)**: append a block to
     `SETUP_AWS/operator/sync-aws-resources.sh`. Use the existing
     idempotency pattern (describe-first, then act).
2. **Make the script block idempotent.** AWS-side changes need an
   explicit "check first" pattern (see `sync-aws-resources.sh` for
   the EFS SG example).
3. **Add an entry to this register** under "Active entries" with
   all the fields above.
4. **Reference this file in code comments** so future readers
   know where to look.

## Process for resolving entries

**Promotion to CDK** (preferred for AWS resources):
1. Edit `infrastructure/cdk/lib/<stack>.ts` to declare the resource.
2. Run `cdk diff <stack>` and confirm the diff is "no change"
   (the resource already exists; CDK just adopts ownership).
3. Run `cdk deploy <stack>` to make CDK the owner.
4. Remove the block from `SETUP_AWS/operator/sync-aws-resources.sh`.
5. Remove the entry from this register.

**Revocation** (preferred when the change is no longer needed):
1. Run the documented revoke command from the script's comment block.
2. Remove the block from the relevant script.
3. Remove the entry from this register.

## Future plan

The intent is to eventually replace this register with a real
configuration-management story:

- **AWS resources** → CDK (already in flight, mature stack at
  `infrastructure/cdk/`)
- **OS-level config on EC2 hosts** → either Ansible, AWS Systems
  Manager State Manager, or Packer-built AMIs. Decision pending.

Until both halves are in place, this register is the bridge.
