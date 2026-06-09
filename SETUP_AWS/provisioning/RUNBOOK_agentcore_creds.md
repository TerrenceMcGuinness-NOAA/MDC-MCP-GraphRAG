# Runbook — agentcore-mcp-rag Credential Provisioning

Operator runbook for `tools/provision-agentcore-creds.py`, the provisioning
tool that gives every eligible per-user OS account on the shared EC2 host the
ability to use the `agentcore-mcp-rag` MCP server from Kiro.

For each target user the tool ensures:

- a `[agentcore-rag]` profile in `~/.aws/credentials`, sourced from the master
  IAM keys in `/home/ec2-user/.aws/credentials [default]`; and
- an `agentcore-mcp-rag` server entry in `~/.kiro/settings/mcp.json` whose
  `env` sets `AWS_PROFILE=agentcore-rag` and `AWS_REGION=us-east-1`.

The tool is idempotent, atomic, and never logs the master keys.

> **Note on the runbook path.** requirements.md R15 names
> `.kiro/specs/agentcore-creds-provisioning/RUNBOOK.md`; design.md and the
> implementation plan place the runbook here under `SETUP_AWS/provisioning/`
> alongside the host provisioning scripts. This file is the canonical runbook.

## Operator Identity

The tool runs **only as `ec2-user`**. It refuses to run under any other
identity (exit code `3`) before reading any source credentials or touching any
target home directory. Acceptable invocations:

- directly as `ec2-user`, or
- as root via `sudo` **only** when `SUDO_USER=ec2-user`.

It escalates via `sudo` for the specific per-target filesystem operations
(directory creation, ownership, atomic file install) and for the verification
probe. It never opens another user's home directory from its own UID. The
required `sudo` allow-list is documented in
`SETUP_AWS/provisioning/sudoers-agentcore-creds.example`.

## Bulk Mode

Provision every eligible user (the `Eligible_User_Set`):

```bash
sudo -u ec2-user python3.12 \
  /mdc-mcp-rag/eib-mcp-rag-server/tools/provision-agentcore-creds.py \
  --all --verify
```

A user is eligible when, in the NSS passwd database, the account has UID ≥
`1000`, a login shell that is not `/sbin/nologin`, `/usr/sbin/nologin`, or
`/bin/false`, a home directory byte-equal to `/home/<name>`, and is not
`ec2-user`, `root`, or in the exclusion list. Users are processed in ascending
C-locale order; a failure on one user does not stop the others.

Preview without writing anything:

```bash
sudo -u ec2-user python3.12 \
  /mdc-mcp-rag/eib-mcp-rag-server/tools/provision-agentcore-creds.py \
  --all --dry-run --format table
```

## Single User Mode

Onboard exactly one named user without touching anyone else's home directory:

```bash
sudo -u ec2-user python3.12 \
  /mdc-mcp-rag/eib-mcp-rag-server/tools/provision-agentcore-creds.py \
  --user alice --verify
```

If the named user does not exist, is `ec2-user`/`root`/excluded, has UID <
`1000`, has a non-interactive login shell, or has a home directory other than
`/home/<name>`, the tool prints an error and exits non-zero without modifying
any filesystem path.

## Exclude File Format

`--exclude-file PATH` unions additional account names into the exclusion list.
Each line is trimmed of surrounding whitespace; empty lines and lines whose
first non-whitespace character is `#` are ignored. If the path is missing or
unreadable the tool exits non-zero without modifying any filesystem state.

```text
# accounts to skip
deploy-bot
backup
   # trailing service accounts
svc-scan
```

```bash
sudo -u ec2-user python3.12 \
  /mdc-mcp-rag/eib-mcp-rag-server/tools/provision-agentcore-creds.py \
  --all --exclude-file /home/ec2-user/agentcore-exclude.txt
```

## Run Summary Dispositions

Every run ends with a `Run_Summary` (table by default, or JSON with
`--format json`) classifying each processed user:

| Disposition | Condition |
|-------------|-----------|
| `created` | Neither file existed before the run; both were created. |
| `updated` | At least one file existed and had its byte content changed. |
| `skipped` | Both files already held the managed values; no byte content changed (mode/ownership are still re-asserted). |
| `failed` | A precondition or write failed (see Troubleshooting), or the verification probe failed. |

The summary also prints aggregate counts for all four dispositions (including
zeros). Exit codes:

| Code | Meaning |
|------|---------|
| `0` | All processed users dispositioned non-`failed`. |
| `2` | Argument/usage error (e.g. both or neither of `--all`/`--user`, or an invalid `--user`). |
| `3` | Identity gate refused (not running as `ec2-user`). |
| `4` | Source credential load failed (missing/empty/unreadable `[default]`). |
| `5` | Configuration validation failed (bad runtime ARN, region, proxy path, or exclude file). |
| `6` | At least one user dispositioned `failed`. |

## Master Key Rotation

The tool never rotates IAM keys; it only propagates whatever is in the source
file. To rotate:

1. Replace the values inside the `[default]` section of the
   `Source_Credentials_File` (`/home/ec2-user/.aws/credentials`).
2. Re-run the tool in Bulk Mode with `--verify`:

```bash
sudo -u ec2-user python3.12 \
  /mdc-mcp-rag/eib-mcp-rag-server/tools/provision-agentcore-creds.py \
  --all --verify
```

Because the tool is idempotent, users whose keys are already current land as
`skipped`; users whose `[agentcore-rag]` key differs are re-written as
`updated`.

## Verification

With `--verify`, the tool runs the `Verification_Probe` for every user it
classifies `created`, `updated`, or `skipped`. The probe runs, as the target
user with `AWS_PROFILE=agentcore-rag` and `AWS_REGION` set:

1. `aws sts get-caller-identity`
2. `aws bedrock-agentcore-control list-agent-runtimes --region <region>`

Each call has a 30-second timeout. A non-zero exit or a timeout re-classifies
that user as `failed` with a reason that distinguishes the two. Response bodies
are not printed unless `--verbose` is supplied. See Requirement 8 of the spec
for the precise probe semantics.

## Troubleshooting

| Failure reason (per-user) | Diagnostic action | Remediation |
|---------------------------|-------------------|-------------|
| `home directory ... does not exist` / `not a directory` / `owned by uid ...` | `ls -ld /home/<user>` | Create/repair the home directory and ownership, then re-run for that user. |
| `... exists and is a symlink/file, not a regular directory` | `ls -ld /home/<user>/.aws` | Remove or relocate the offending path; re-run. |
| `existing mcp.json is not valid JSON` | `python3.12 -m json.tool /home/<user>/.kiro/settings/mcp.json` | Fix or remove the malformed JSON; re-run (the tool will not overwrite invalid JSON). |
| `concurrent modification detected` | Check whether Kiro/another process is editing the file | Re-run when the file is quiescent. |
| `sts timeout after 30s` / `sts exit <rc>` | Run `sudo -u <user> -H env AWS_PROFILE=agentcore-rag AWS_REGION=us-east-1 aws sts get-caller-identity` | Confirm the master keys are valid and not expired; confirm network/STS reachability. |
| `agentcore timeout after 30s` / `agentcore exit <rc>` | Run the `bedrock-agentcore-control list-agent-runtimes` call manually | Confirm the IAM identity has `bedrock-agentcore:*` list permissions and the region is correct. |
| `cross-file profile name mismatch` | Inspect both files | This indicates a tool bug; capture both files (redacted) and report. |

Global (non-per-user) failures print an error to stderr and use the exit codes
in the Run Summary Dispositions table.

## References

- Tool source: `tools/provision-agentcore-creds.py`
- MCP stdio proxy provisioned for: `tools/agentcore-kiro-proxy.py`
- Sudoers allow-list: `SETUP_AWS/provisioning/sudoers-agentcore-creds.example`
- Consumer guide (steering): [`.kiro/steering/09-agentcore-mcp-for-global-workflow.md`](../../.kiro/steering/09-agentcore-mcp-for-global-workflow.md)
  *(the spec's R15.5 refers to this as `01-agentcore-mcp-for-global-workflow.md`; renamed `09-` in this workspace)*
- Tool-selection guide (steering): [`.kiro/steering/10-agentcore-mcp-tool-guide.md`](../../.kiro/steering/10-agentcore-mcp-tool-guide.md)
  *(the spec's R15.5 refers to this as `02-agentcore-mcp-tool-guide.md`; renamed `10-` in this workspace)*
- Verification probe semantics: Requirement 8, `--verify` option (see the
  Verification section above).

## Out of Scope

The tool does **not** do any of the following (Requirement 16):

- Call any AWS API in the `iam:*`, `sso-admin:*`, `identitystore:*` namespaces
  or `sts:AssumeRole`.
- Create, modify, delete, rename, or re-permission any path under
  `tools/agentcore-kiro-proxy.py` or the `mdc-mcp-rag` server source tree; the
  only paths it writes are under `/home/<Target_User>`.
- Modify the EC2 instance profile/role, any role trust or inline/managed
  policy, or any AWS resource other than the read-only `sts:GetCallerIdentity`
  and AgentCore list calls of the verification probe.
- Rotate, regenerate, replace, or deactivate any IAM access key. Propagating
  new source-file values on the next run is the only mechanism by which the
  tool reflects an externally-performed key rotation.
