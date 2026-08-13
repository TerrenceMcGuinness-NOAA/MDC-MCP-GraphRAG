# AWS User-Provisioning Drift Remediation — Requirements

**Spec ID**: `aws-user-provisioning-drift-remediation`
**Platform**: AWS EC2 host (`SETUP_AWS/provisioning/`), NOT the COTS Parallel Works host
**Source spec**: [`user-provisioning-drift-remediation`](../user-provisioning-drift-remediation/)
(COTS; landed on `develop` as `ce121cd`, following `a6c15ff` + `e8aea35`)
**Trigger**: 2026-08-12 — the COTS host gained `--status` / `--dry-run` /
`--remediate` on `SETUP/provisioning/00-users.sh`. The AWS host's
`SETUP_AWS/provisioning/provision-user-accounts.sh` has none of it: it is a
single monolithic `while read` loop with no read-only inspection mode, no plan
rendering, and no way to fix an existing account short of re-running the whole
provisioning path with `--force` (which overwrites operator/user customisations).

## Context — what the AWS host looks like today (verified 2026-08-12)

```
$ getent group developers
developers:x:1002:terry.mcguinness,anton.fernando,barry.baker,daniel.sarmiento,
                  david.huber,alexander.hrabski,alexander.richert,rahul.mahajan,ec2-user

$ getent passwd | awk -F: '$3>=1000 && $3<65534 {print $1, $3, $4}'
ec2-user 1000 1000 | ssm-user 1001 1001 | terry.mcguinness 1002 1003
anton.fernando 1003 1004 | barry.baker 1004 1005 | daniel.sarmiento 1005 1006
david.huber 1006 1007 | alexander.hrabski 1007 1008 | alexander.richert 1008 1009
rahul.mahajan 1009 1010

$ ls -la /mdc-mcp-rag/SCRATCH
drwxr-xr-x. alexander.hrabski alexander.hrabski Alexander.Hrabski
drwxr-xr-x. alexander.richert alexander.richert Alexander.Richert
drwxrwxr-x. anton.fernando    anton.fernando    Anton.Fernando
drwxrwxrwx. barry.baker       barry.baker       Barry.Baker
...
```

Three structural differences from the COTS host drive every requirement below:

| Dimension | COTS host | AWS host |
|---|---|---|
| Username form | `First.Last` (CamelCase) | `first.last` (lowercase) |
| Primary group | shared `pwuser` | per-user **private** group (`useradd -m -s /bin/bash -G developers`) |
| Shared group | `docker`, `kasmvnc-cert` | `developers` |
| Scratch root | `/mcp_rag_eib/SCRATCH_SPACE/<Username>` | `/mdc-mcp-rag/SCRATCH/<First.Last>` — **CamelCase, derived from the `users.conf` full name, not from the username** |
| Repo access | per-user clone in scratch (`eib-mcp-rag-server`) | **shared** group-readable checkout at `/mdc-mcp-rag/eib-mcp-rag-server` — no per-user clone |
| Per-user MCP assets | `<scratch>/.vscode/mcp.json` (VS Code) | `~/.kiro/settings/mcp.json` + `~/.kiro/steering/` + `~/.kiro/skills/` (Kiro CLI) |
| AWS auth | n/a | `~/.aws/config` + `~/.aws/credentials` (`[agentcore-rag]` profile, per-user IAM access keys) |
| User SPOT | `PROVISION_USERS` array in `user_config.sh` | `users.conf` (`username:full_name:email`) |

Because the AWS host has no per-user clone, the COTS **R10 `missing_clone`**
drift has no direct analogue. Its role — "the per-user asset that silently goes
missing and breaks the developer's tooling" — is played on AWS by the
`~/.kiro/` bundle and the `~/.aws/` skeleton. Those become the AWS R10 family.

The reasoning behind the single-shared-checkout model is recorded in
design.md § "Decision record — no per-user clone of `eib-mcp-rag-server` on AWS"
and, operator-facing, in `RUNBOOK_user_drift_remediation.md` § "Why there is no
per-user clone". In short: on COTS the clone *is* the MCP runtime (a local stdio
`node` process reads it); on AWS the runtime is remote (AgentCore) and the only
local artifact is one proxy script read out of the shared tree. Duplicating the
27 GB tree eight times would consume 216 GB to no functional end, and would
fragment the proxy version against a single runtime ARN. The model's one hard
requirement — a git `safe.directory` exception per shared repo — is R14.

Evidence that this drift class is real and currently hand-patched: the untracked
one-off `SETUP_AWS/provisioning/fix-user-mcp-aws-profile.sh` exists solely to
sweep every user's `~/.kiro/settings/mcp.json` for a wrong `AWS_PROFILE` env
value. That is exactly the shape of work `--remediate` is meant to absorb.

## Requirements (EARS)

### R1 — `--status` read-only integrity report

`provision-user-accounts.sh` **shall** accept `--status`, which prints a per-user
integrity block for every user in `users.conf` and exits 0 without mutating the
host. Each check emits `[OK]`, `[DRIFT expected=X actual=Y]`, or `[PENDING …]`
(for conditions only the end user can resolve — see R8). Mirrors the COTS
`check_user_integrity` contract.

### R2 — `--remediate <username>` flag

The script **shall** accept `--remediate <username>` (repeatable). It targets a
user who **already exists** and **shall** refuse with `[ERROR]` + exit 1 when
the target user is absent from the host — `--remediate` is not a creation path.
`--remediate` and `--user` **shall** be mutually exclusive in one invocation
(`[ERROR]` + exit 2).

### R3 — drift-driven scope

For each target user the system **shall** compute the drift set via
`check_user_drifts` and apply **only** the fixes corresponding to reported drift
rows. A user with an empty drift set **shall** log "no remediation needed",
issue zero mutating commands, and return 0.

### R4 — primary-group remediation (SPOT-gated, inert by default on AWS)

The `PROVISION_PRIMARY_GROUP` SPOT field **shall** default to the **empty
string** on AWS, meaning "each user's private group is correct" — the current
and intended AWS convention. When it is empty, no primary-group drift is
reported and no `usermod -g` is ever issued. When an operator sets it to a
non-empty group name that exists on the host, the system **shall** report
primary-group drift and remediate it with
`usermod -g "${PROVISION_PRIMARY_GROUP}" <user>`. A non-empty value naming a
group that does not exist **shall** emit `[WARN]` and skip the fix.

Rationale: preserves the COTS field name and semantics (so both hosts read the
same way) while defaulting to a no-op on the platform whose convention differs.

### R5 — scratch-owner remediation (preserve-safe)

When scratch-dir top-level owner drift is reported, the system **shall**
`chown "$(resolve_ownership <user>)" "${SCRATCH_ROOT}/<Scratch.Name>"` on the
**top level only** (no `-R`). Children retain existing ownership. Any child not
owned by the target user **shall** be enumerated as `[PRESERVED]` in the report
and **shall not** be adopted unless `PROVISION_ADOPT_PRESTAGED=yes`, in which
case `chown -R` is applied. Identical preserve/adopt semantics to COTS.

A **missing** scratch directory is a distinct drift row; remediation creates it
(`mkdir -p`, `chown`, `chmod 755`) and there is nothing to preserve.

The scratch directory name **shall** be derived from the `users.conf` full-name
field (`Terry McGuinness` → `Terry.McGuinness`), matching the existing
provisioning loop. It **shall not** be derived by capitalising the username,
which cannot reproduce intra-word capitals (`mcguinness` → `McGuinness`).

### R6 — supplementary-group remediation

For each group in `PROVISION_SUPP_GROUPS` (default `("developers")`) that the
user is missing AND that exists on the host, the system **shall** invoke
`usermod -aG <group> <user>`. Groups absent from the host **shall** emit
`[WARN]` and be skipped, never failing the run.

### R7 — permission-mode remediation

The system **shall** report and remediate mode drift on the security-sensitive
per-user paths:

| Path | Expected | Fix |
|---|---|---|
| `~/.ssh` | `0700` | create if missing, `chmod 700`, `chown` to user |
| `~/.ssh/authorized_keys` | `0600` | create if missing, `chmod 600`, `chown` to user |
| `~/.aws` | `0700` | create if missing, `chmod 700`, `chown` to user |
| `~/.aws/credentials` | `0600` | write the placeholder skeleton **only if absent**, `chmod 600`, `chown` to user |

The system **shall never** overwrite an existing `~/.aws/credentials` — a real
access key pasted by the user is unrecoverable if clobbered. Only the mode and
ownership are corrected.

### R8 — `~/.kiro` asset drift (AWS R10 analogue)

The system **shall** report the following as drift, unless the user is listed in
the SPOT allowlist `PROVISION_KIRO_EXEMPT_USERS` (defaults to empty; intended
for operators who manage their own Kiro config):

- `missing_kiro_mcp` — `~/.kiro/settings/mcp.json` absent. Remediated by
  deploying `user-templates/mcp.json`.
- `missing_kiro_steering` — `~/.kiro/steering/` holds zero `*.md` files.
  Remediated by copying `user-templates/steering/*.md`.
- `stale_kiro_profile <actual>` — `mcp.json` exists but its
  `mcpServers.agentcore-mcp-rag.env.AWS_PROFILE` differs from the
  `PROVISION_AWS_PROFILE` SPOT. **Reported always, remediated only when
  `--force` is also passed** — the file may carry user customisations
  (`autoApprove` edits, extra servers) that a blind template redeploy would
  drop. When `--force` is given, the system **shall** back the file up to
  `mcp.json.bak.<UTC timestamp>` before rewriting.

Additionally the system **shall** report `aws_creds_placeholder` as a
`[PENDING user action]` row (not `[DRIFT]`) when `~/.aws/credentials` still
contains the provisioning placeholder. This condition is **not remediable by the
operator** — the user must paste their own IAM access key per
`RUNBOOK_developer_aws_credentials.md`. `--remediate` **shall** emit `[WARN]`
naming the runbook and continue.

### R9 — `--dry-run` integration

`--dry-run` **shall** render a plan and mutate nothing, for both paths:

- `--dry-run --remediate <user>` renders the numbered surgical fixes for that
  user's drift set, with resolved variable substitution. A zero-drift user
  renders "no drift detected, no action" and exits 0.
- `--dry-run` (provisioning path) renders the numbered steps the provisioning
  loop would perform per user, mirroring its existing eight numbered stages.

### R10 — before/after report

At the end of a real (non-dry-run) `--remediate` run, the system **shall**
re-invoke `check_user_integrity` for the targeted user so the operator sees the
post-remediation state. Rows skipped by a host-condition guard (R4/R6/R8)
**shall** remain visible rather than being silently dropped.

### R11 — idempotency

Running `--remediate <user>` twice back-to-back **shall** produce identical
`[OK]` output on the second run with zero mutating commands issued.

### R12 — backward compatibility

Invoking `provision-user-accounts.sh` with no flags, or with `--force`, **shall**
behave exactly as before this spec: iterate `users.conf` and run all eight
provisioning stages. The new flags are purely additive. `--add` keeps its
current "append to users.conf then re-run" advisory behaviour.

### R13 — no flag is ever silently accepted or silently ignored

Added 2026-08-12 after operator testing surfaced three defects of exactly this
shape.

1. A flag that takes a username (`--user`, `--remediate`) **shall** reject a
   missing value, and **shall** reject a value that starts with `-`, with
   `[ERROR]` + usage + exit 2. Previously `--user --help` bound the username
   `--help` and then fell through into a **real, mutating** provisioning run
   instead of printing usage.
2. `--status` **shall** honour an explicit user list from `--user` or
   `--remediate` and report only those users. Previously it ignored both and
   always dumped every user in `users.conf`.
3. **`00-users.sh` (the `ec2-user` bootstrap, stage 00 of `provision.sh`)
   shall parse arguments.** It previously accepted and discarded every flag,
   which meant `--help` printed nothing and — the serious case —
   `--dry-run` performed its full `mkdir`/`touch`/`chmod`/`chown` mutation
   despite the flag. It **shall** support `--help`, `--status`, and `--dry-run`
   for its own narrow scope, and **shall** reject `--user` / `--remediate` /
   `--force` / `--add` with an `[ERROR]` naming `provision-user-accounts.sh` as
   the correct script.

Rationale for (3): on the COTS host `00-users.sh` **is** the per-user
provisioning script, so an operator with COTS muscle memory reaches for
`00-users.sh` first. On AWS the two roles are split. Silently ignoring the flags
made that mistake invisible; an explicit redirect makes it self-correcting.

### R14 — git `safe.directory` coverage for the shared checkout

Added 2026-08-12 while documenting the no-per-user-clone decision. The
shared-checkout model (see design.md § "Decision record") is owned by `ec2-user`,
so git refuses to operate in it for any other account without an ownership
exception. Therefore:

1. Provisioning **shall** write a `safe.directory` entry for `${WORKSPACE}` and
   for **every** `supported_repos/*` entry that is a git repository, enumerated
   **from disk** rather than hardcoded. A hardcoded list silently rots when
   checkouts are renamed — which is what happened (`c15080f`), leaving all 25 real
   checkouts unlisted and git unusable in them for all 8 developers.
2. A missing `~/.gitconfig` **shall** be reported as `missing_gitconfig` and
   remediated by writing the whole file.
3. An existing `~/.gitconfig` missing one or more entries **shall** be reported as
   `stale_git_safe_dirs <count>` and remediated by **appending** the missing
   entries via `git config --global --add`, run as the target user. The file
   **shall not** be rewritten — a developer's aliases, credential helpers, and
   other personal settings must survive — and therefore this repair **shall not**
   require `--force`.
4. A wildcard entry (`directory = *`) **shall** be treated as covering everything.

## Non-goals

- Bulk `--remediate-all`. Repeat `--remediate <user>` per user; explicit is safer.
- Password / IAM-key management. AWS accounts here are SSH-key based; access
  keys are user-owned per the runbook.
- Home-directory content sweeps (`~/.gitconfig` body, `.bashrc` diffing against
  the template). Presence-only checks; content drift is out of scope.
- Touching the COTS `SETUP/provisioning/` tree. This spec is AWS-only.
- Retiring `fix-user-mcp-aws-profile.sh`. Its function is superseded by the
  `stale_kiro_profile` drift row, but removing it is a separate decision (see
  "Open question" below).

## Open question for the operator (not resolved by this spec)

`user-templates/mcp.json` sets `"AWS_PROFILE": "agentcore-rag"` (commit
`6435643`, "Fix AWS_PROFILE=agentcore-rag in mcp.json template and
credentials"), while the untracked `fix-user-mcp-aws-profile.sh` exists to
**strip** that exact key, on the reasoning that boto3 should fall through to the
EC2 instance profile. These are contradictory intents. This spec treats the
**template as authoritative** (`PROVISION_AWS_PROFILE="agentcore-rag"`) because
it is the committed artifact and matches `RUNBOOK_developer_aws_credentials.md`,
which instructs users to create an `[agentcore-rag]` profile. If the runbook is
wrong, change the SPOT field to `""` and the drift check inverts to "expect no
AWS_PROFILE" — a one-line change, no code edit.

## Acceptance criteria

- **AC1** — `sudo ./provision-user-accounts.sh --status` prints an integrity
  block for all eight `users.conf` users and exits 0. `stat`/`id` ground truth
  independently confirms every `[OK]` and `[DRIFT]` row it prints.
- **AC2** — `sudo ./provision-user-accounts.sh --dry-run --remediate <clean user>`
  prints "no drift detected" and exits 0; nothing on the host changes.
- **AC3** — `sudo ./provision-user-accounts.sh --dry-run --remediate <drifted user>`
  prints a numbered plan naming exactly the fixes for that user's reported
  drifts, and mutates nothing (verified by re-running `--status` and diffing).
- **AC4** — `sudo ./provision-user-accounts.sh --remediate nonexistent.user`
  prints `[ERROR] user nonexistent.user does not exist; --remediate is not for
  creation`, exits 1, touches nothing.
- **AC5** — `--user X --remediate Y` is rejected with `[ERROR] … mutually
  exclusive`, exit 2.
- **AC6** — A real `--remediate` run on a drifted user clears every remediable
  drift row; the R10 post-run report shows `[OK]`, and a second run is a
  zero-mutation no-op (R11).
- **AC7** — `bash -n` passes on `provision-user-accounts.sh`, `common.sh`, and
  `user_config.sh`.
- **AC8** — With `PROVISION_PRIMARY_GROUP=""` (the AWS default), no `--status`
  run reports a primary-group row and no `usermod -g` appears in any dry-run
  plan (R4 inertness).
- **AC9** — `sudo ./provision-user-accounts.sh` with no flags produces
  byte-identical stage output to the pre-spec script for an already-provisioned
  user (R12 backward compatibility).
- **AC10** — `--user --help` and `--remediate --dry-run` both print
  `[ERROR] … requires a username, got the option '…'` + usage and exit 2 without
  entering the provisioning loop. `--user` with no value exits 2 (R13.1).
- **AC11** — `--status --user <name>` reports exactly that one user;
  `--status --user a --user b` reports exactly two; bare `--status` still reports
  every `users.conf` user. A `--user` name absent from `users.conf` still
  produces a block carrying the `users.conf` drift row (R13.2).
- **AC12** — `00-users.sh --help` prints usage and exits 0;
  `00-users.sh --dry-run` renders a plan and mutates nothing;
  `00-users.sh --status` reports `ec2-user`'s `~/.ssh` state read-only;
  `00-users.sh --user x` errors with a pointer to `provision-user-accounts.sh`
  and exits 2; bare `00-users.sh` behaves exactly as before (R13.3).
- **AC13** — `sudo ./provision.sh --only 00` completes successfully, proving the
  `common.sh` sourcing-guard fix (see design.md § "Pre-existing bug found during
  R13 verification").
- **AC14** — `--status` reports a `git safe.directory` row for every user. On a
  user whose `.gitconfig` predates the fix it reads
  `[DRIFT expected=26 shared repo(s) actual=1]`; the dry-run plan lists one
  `git config --global --add safe.directory <path>` line per missing repo; after a
  real `--remediate` the row reads `26/26 shared repo(s) [OK]`, a
  `git -C <shared submodule> status` as that user no longer errors, and any
  pre-existing non-`safe` sections of their `.gitconfig` are unchanged (R14).

## Traceability

| Requirement | Acceptance |
|---|---|
| R1 `--status` | AC1 |
| R2 `--remediate` flag + refusal + mutex | AC4, AC5 |
| R3 drift-driven scope | AC2, AC3, AC6 |
| R4 primary group (SPOT-gated) | AC8 |
| R5 scratch owner / missing + preserve-adopt | AC3, AC6 |
| R6 supplementary groups | AC3, AC6 |
| R7 permission modes | AC3, AC6 |
| R8 `~/.kiro` assets + pending-creds row | AC1, AC3, AC6 |
| R9 dry-run (both paths) | AC2, AC3 |
| R10 before/after report | AC6 |
| R11 idempotency | AC6 |
| R12 backward compatibility | AC9 |
| R13.1 no flag swallowed as a username | AC10 |
| R13.2 `--status` honours `--user` / `--remediate` | AC11 |
| R13.3 `00-users.sh` parses arguments | AC12 |
| R14 `safe.directory` coverage (enumerated from disk) | AC14 |
| (all) syntax | AC7 |
| (enabling fix) `common.sh` guard not exported | AC13 |
