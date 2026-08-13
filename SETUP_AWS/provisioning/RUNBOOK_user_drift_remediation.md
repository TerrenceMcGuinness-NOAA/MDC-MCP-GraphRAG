# RUNBOOK — Developer Account Drift Remediation (AWS)

**Script**: `SETUP_AWS/provisioning/provision-user-accounts.sh`
**Spec**: `.kiro/specs/aws-user-provisioning-drift-remediation/`
**Audience**: the operator who owns this EC2 host (`ec2-user` / sudo)

Provisioned developer accounts drift: a mode gets loosened, a `~/.kiro` bundle
goes missing, someone's `authorized_keys` disappears, a scratch directory ends up
owned by the wrong user. Before this runbook the only repair was re-running the
whole provisioning path with `--force`, which overwrites the user's own
customisations. `--remediate` fixes only what is actually broken.

This is the AWS counterpart of the COTS Parallel Works capability
(`SETUP/provisioning/00-users.sh --remediate`, spec
`user-provisioning-drift-remediation`).

## Which script? (read this first if you came from the COTS host)

**On COTS, `00-users.sh` is the per-user provisioning script. On AWS it is not.**
The two roles are split:

| Script | Scope |
|---|---|
| `00-users.sh` | the **`ec2-user` bootstrap account** only; stage 00 of `provision.sh`. Supports `--help`, `--status`, `--dry-run` over that narrow scope. |
| `provision-user-accounts.sh` | **individual developer accounts** — creation, drift inspection, drift repair. Owns `--user`, `--remediate`, `--status`, `--dry-run`, `--force`. |

`00-users.sh` will refuse `--user` / `--remediate` / `--force` / `--add` and point
you here, rather than accepting the flag and doing nothing with it.

## Why there is no per-user clone of `eib-mcp-rag-server` in SCRATCH

On the COTS host, provisioning gives every developer their own clone at
`${SCRATCH}/<User>/eib-mcp-rag-server`, and a missing one is treated as drift
(`missing_clone`, that spec's R10). On AWS there is **one shared checkout** at
`/mdc-mcp-rag/eib-mcp-rag-server` and no per-user copy. That is deliberate, and
it follows from where the MCP server actually runs.

### The MCP server is not a local process here

| | COTS Parallel Works | AWS |
|---|---|---|
| Where the MCP server runs | **on the developer's own machine**, as a stdio child process | **remotely**, in a Bedrock AgentCore runtime |
| How the client launches it | `node <their clone>/mcp_server_node/src/UnifiedMCPServer.js full` | `mcp-python <shared>/tools/agentcore-kiro-proxy.py --runtime-id arn:aws:bedrock-agentcore:…` |
| Backends | local ChromaDB `:8080` + Neo4j `:7687` | Neptune + OpenSearch, VPC-private, reached by the runtime |
| What the clone is | **the runtime itself** — the server executes out of it | **a client** — one ~40 KB proxy script is read out of it |

On COTS the clone is load-bearing: the server *is* the code in that directory, so
each user needs their own to run their own server against their own databases.
On AWS nothing executes out of a per-user copy. The entire local footprint of the
MCP integration is:

- `tools/agentcore-kiro-proxy.py` — read out of the shared checkout;
- `/mnt/mdc-mcp-rag/spack/bin/mcp-python` — the shared Spack venv;
- `~/.kiro/settings/mcp.json` — per-user, and the only per-user artifact that
  matters (which is why *it* is a drift row and a clone is not).

### The cost of the alternative, measured

```
/mdc-mcp-rag/eib-mcp-rag-server        27 GB total
  ├── .git                             12 GB
  ├── supported_repos/ (25 checkouts)  14 GB   ← five global-workflow branches alone are 12 GB
  └── actual platform source          910 MB
```

Eight developers × 27 GB = **216 GB** of redundant copies against **381 GB** free
on `/mnt/mdc-mcp-rag` — 57% of remaining headroom, to duplicate a tree whose
useful-to-a-developer part is under a gigabyte.

### Version coherence

One shared checkout means one `agentcore-kiro-proxy.py`, pinned against one
AgentCore runtime ARN. Eight clones means eight proxy versions drifting
independently against a runtime that gets redeployed — and a class of "works for
me" bug that is expensive to diagnose remotely. This is the same reason the Spack
Python environment is shared rather than per-user.

### What SCRATCH is actually for on AWS

Not "no personal git work" — the opposite. SCRATCH holds each developer's own
clones of **the repos under study**, which is where their work happens:

```
/mdc-mcp-rag/SCRATCH/Anton.Fernando/   GDASApp  global-workflow  global-workflow_gfsv17
                                       ufs-weather-model  wxflow  utils  …
/mdc-mcp-rag/SCRATCH/Barry.Baker/      global-workflow  spack-stack  UFS_UTILS  AMIO  …
/mdc-mcp-rag/SCRATCH/Terry.McGuinness/ global-workflow{,_v17,_forked,.wiki}  .kiro  …
```

Zero of the eight users has ever cloned `eib-mcp-rag-server` into scratch. The
decision documents existing practice rather than imposing a new constraint.

### The hard requirement this creates: `safe.directory`

The shared tree is owned by `ec2-user`. Git refuses to operate in a repository
owned by another user, so **every developer needs a `safe.directory` exception for
the workspace and for each of the 25 `supported_repos` checkouts**, or they get:

```
fatal: detected dubious ownership in repository at
'/mnt/mdc-mcp-rag/eib-mcp-rag-server/supported_repos/global-workflow_develop'
```

Provisioning writes those entries into `~/.gitconfig`. They are now **enumerated
from disk** rather than hardcoded — the previous hardcoded list named
`supported_repos/global-workflow` and `global-workflow_dev-v17`, neither of which
has existed since the multi-tenant rename, which left all 25 real checkouts
unusable for all 8 developers. Covered by the `git safe.directory` row in
`--status` and repaired by `--remediate`, which **appends** the missing entries
one at a time as the user rather than rewriting `~/.gitconfig` (aliases and other
personal settings are preserved, and no `--force` is needed).

### Known tradeoff — one working tree, one branch

The shared checkout is `775 ec2-user:developers`, so it is group **writable**: a
developer can commit directly. The cost is that a working tree has one checked-out
branch, so two people cannot be on different branches at once, and one person's
`git checkout` changes the tree under everyone else. So far only one account has
committed there, so the contention is latent rather than observed.

If you need to work on a branch without disturbing others, prefer a **worktree**
over a clone — it costs the source (~910 MB), not the 12 GB object store:

```bash
git -C /mdc-mcp-rag/eib-mcp-rag-server worktree add \
    "${SCRATCH}/eib-mcp-rag-server-<branch>" <branch>
```

Note that `worktree add` writes metadata into the shared `.git/worktrees`, so
coordinate with the operator before using it. For sustained parallel work a
personal clone with `--reference /mdc-mcp-rag/eib-mcp-rag-server/.git` shares
objects instead of duplicating 12 GB.

**If this tradeoff ever bites**, the remedy is a worktree convention or a
reference clone — not eight full clones, and not making a per-user clone a drift
row. Revisit only if the shared tree becomes a real contention point.

## The three read-mostly modes

```bash
cd /mdc-mcp-rag/eib-mcp-rag-server/SETUP_AWS/provisioning

sudo ./provision-user-accounts.sh --status                     # 1. what is broken?
sudo ./provision-user-accounts.sh --dry-run --remediate <user> # 2. what would change?
sudo ./provision-user-accounts.sh --remediate <user>           # 3. change it
```

`--status` accepts `--user` to narrow the report to one or more accounts:

```bash
sudo ./provision-user-accounts.sh --status --user anton.fernando
sudo ./provision-user-accounts.sh --status --user alexander.richert --user rahul.mahajan
```

Always run steps 1 and 2 before step 3. `--status` and `--dry-run` mutate
nothing — they are safe to run at any time, including on a busy host.

`--remediate` is repeatable (`--remediate a --remediate b`) and is **mutually
exclusive with `--user`**: one intent per invocation, create OR repair.
It **refuses** a user who does not exist — it is not a creation path:

```
[ERROR] user nonexistent.user does not exist; --remediate is not for creation
```

## Drift taxonomy

| Row in `--status` | Meaning | What `--remediate` does |
|---|---|---|
| `account` | the Linux account is missing | nothing — use the provisioning path |
| `primary group` | only shown when `PROVISION_PRIMARY_GROUP` is set | `usermod -g <group>` |
| `supplementary groups` | not in `developers` | `usermod -aG developers` |
| `scratch … expected=exists actual=missing` | scratch dir absent | `mkdir -p` + `chown` + `chmod 755` |
| `scratch … expected=u:g actual=x:y` | wrong top-level owner | `chown` **top level only** (see preserve/adopt) |
| `~/.ssh mode` | not `0700` | `mkdir -p` + `chmod 700` + `chown` |
| `~/.ssh/authorized_keys mode` | not `0600` or missing | `touch` + `chmod 600` + `chown` |
| `~/.aws mode` | not `0700` | `mkdir -p` + `chmod 700` + `chown` |
| `~/.aws/credentials mode` | not `0600` or missing | writes the skeleton **only if absent**; `chmod 600` |
| `~/.gitconfig` | missing | write identity + all `safe.directory` entries |
| `git safe.directory` | shared repos unlisted | **appends** the missing entries as the user; never rewrites the file |
| `~/.kiro/settings/mcp.json` | missing | deploy from `user-templates/mcp.json` |
| `~/.kiro/steering` | zero `*.md` files | copy `user-templates/steering/*.md` |
| `mcp.json AWS_PROFILE` | differs from `PROVISION_AWS_PROFILE` | **`--force` only** — see the caution below |
| `~/.aws/credentials: [PENDING user action]` | placeholder key still in place | nothing — the **user** must act |

`[PENDING user action]` is not operator drift. It means that developer has never
pasted their IAM access key. Point them at
[`RUNBOOK_developer_aws_credentials.md`](RUNBOOK_developer_aws_credentials.md);
`--remediate` emits a `[WARN]` and moves on.

Rows are **omitted** rather than faked when they do not apply on this host: no
`primary group` row while `PROVISION_PRIMARY_GROUP` is empty (the AWS default),
and no `~/.kiro` rows for users on `PROVISION_KIRO_EXEMPT_USERS`.

## Preserve vs adopt — decide before you run

When a scratch directory has the wrong top-level owner, its **children** may
legitimately belong to someone else (a peer staged data there, or the operator
seeded a checkout). Two behaviours, chosen per invocation:

**Preserve (default).** Only the top-level directory is re-owned. Every child
belonging to someone else is listed and left alone:

```
[2] Scratch dir top-level: /mdc-mcp-rag/SCRATCH/Terry.McGuinness
    chown terry.mcguinness:developers /mdc-mcp-rag/SCRATCH/Terry.McGuinness    # top-level only
    [PRESERVED] 1 pre-staged child path(s) will NOT be re-owned
      [PRESERVED] /mdc-mcp-rag/SCRATCH/Terry.McGuinness/temp
```

**Adopt.** Everything under the tree is re-owned:

```bash
sudo PROVISION_ADOPT_PRESTAGED=yes ./provision-user-accounts.sh --remediate <user>
```

Run the dry-run first and read the `[PRESERVED]` list. If any of those paths
should stay where they are, do **not** adopt.

## Caution — `mcp.json AWS_PROFILE` drift and `--force`

`stale_kiro_profile` is reported but **not** repaired by default, because the
only repair is redeploying the template, which drops anything the user added to
their own `mcp.json` (edited `autoApprove` lists, extra MCP servers). With
`--force` the file is backed up to `mcp.json.bak.<UTC timestamp>` first:

```bash
sudo ./provision-user-accounts.sh --dry-run --force --remediate <user>   # review
sudo ./provision-user-accounts.sh --force --remediate <user>             # apply
```

Prefer hand-editing the one `env.AWS_PROFILE` line when the user has
customisations worth keeping.

## Guarantees

- **Idempotent.** A second `--remediate` on the same user reports
  `No drift detected` and issues zero mutating commands.
- **Credentials are never clobbered.** `~/.aws/credentials` and `~/.aws/config`
  are written only when **absent**. A pasted access key survives every
  remediation path. Mode and ownership are corrected in place.
- **Content is never read into the report.** The placeholder check is a boolean
  `grep -q`; no credential material is ever echoed.
- **Drift-driven.** Only the fixes a user's drift set calls for are applied; a
  clean user is a no-op.

## Configuration (SPOT)

`SETUP_AWS/provisioning/user_config.sh` holds the knobs; `users.conf` remains
the source of truth for *who* is provisioned.

| Field | Default | Notes |
|---|---|---|
| `SCRATCH_ROOT` | `${PERSISTENT_ROOT}/SCRATCH` | leaf is CamelCase `First.Last` from the `users.conf` full name |
| `WORKSPACE` | `${PERSISTENT_ROOT}/eib-mcp-rag-server` | the shared checkout; AWS has no per-user clone |
| `SHARED_GROUP` | `developers` | grants access to `WORKSPACE` |
| `PROVISION_SUPP_GROUPS` | `(developers)` | groups absent from the host are skipped with `[WARN]` |
| `PROVISION_PRIMARY_GROUP` | `""` | **empty is correct on AWS** — each user keeps their private group; no `usermod -g` is ever issued |
| `PROVISION_ADOPT_PRESTAGED` | `no` | env-overridable per run |
| `PROVISION_KIRO_EXEMPT_USERS` | `()` | users who manage their own `~/.kiro` |
| `PROVISION_AWS_PROFILE` | `agentcore-rag` | expected profile in `mcp.json`; set `""` to expect none |

## COTS ↔ AWS mapping

Reading the two platforms side by side; the function and flag names are
deliberately identical.

| Concept | COTS (`SETUP/`) | AWS (`SETUP_AWS/`) |
|---|---|---|
| Script | `provisioning/00-users.sh` | `provisioning/provision-user-accounts.sh` |
| User SPOT | `PROVISION_USERS` array | `users.conf` (`username:full_name:email`) |
| Username form | `First.Last` | `first.last` |
| Primary group | `pwuser` (shared) | private per-user group |
| Shared group(s) | `docker`, `kasmvnc-cert` | `developers` |
| Scratch | `/mcp_rag_eib/SCRATCH_SPACE/<Username>` | `/mdc-mcp-rag/SCRATCH/<First.Last>` |
| Repo access | per-user clone in scratch | shared `${WORKSPACE}` checkout |
| Per-user MCP config | `<scratch>/.vscode/mcp.json` | `~/.kiro/settings/mcp.json` |
| "asset missing" drift | `missing_clone` (R10) | `missing_kiro_mcp`, `missing_kiro_steering`, `aws_*` |
| Cloud auth drift | n/a | `stale_kiro_profile`, `aws_creds_placeholder` |

## Typical session

```bash
cd /mdc-mcp-rag/eib-mcp-rag-server/SETUP_AWS/provisioning

# 1. Census
sudo ./provision-user-accounts.sh --status | tee /tmp/drift-before.txt

# 2. Review one user's plan
sudo ./provision-user-accounts.sh --dry-run --remediate anton.fernando

# 3. Apply (preserve is the default; add PROVISION_ADOPT_PRESTAGED=yes to adopt)
sudo ./provision-user-accounts.sh --remediate anton.fernando

# 4. Confirm idempotency
sudo ./provision-user-accounts.sh --remediate anton.fernando   # → No drift detected

# 5. Re-census and diff
sudo ./provision-user-accounts.sh --status | tee /tmp/drift-after.txt
diff /tmp/drift-before.txt /tmp/drift-after.txt
```

Ground-truth cross-check for any row you doubt:

```bash
id <user>
stat -c '%U:%G %a' /mdc-mcp-rag/SCRATCH/<First.Last> /home/<user>/.ssh \
                   /home/<user>/.ssh/authorized_keys /home/<user>/.aws \
                   /home/<user>/.aws/credentials
```

## Related

- [`RUNBOOK_developer_aws_credentials.md`](RUNBOOK_developer_aws_credentials.md)
  — what a developer does about a `[PENDING user action]` row.
- `fix-user-mcp-aws-profile.sh` — the earlier one-off sweep for a wrong
  `AWS_PROFILE`. Superseded functionally by the `stale_kiro_profile` drift row;
  retirement is an operator decision (see the spec's
  requirements.md § "Open question").
