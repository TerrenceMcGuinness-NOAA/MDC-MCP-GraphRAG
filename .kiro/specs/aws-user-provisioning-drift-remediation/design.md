# AWS User-Provisioning Drift Remediation — Design

## Overview

Four files touched under `SETUP_AWS/provisioning/`, all additive except two
small refactors called out below:

| File | Change |
|---|---|
| `user_config.sh` | **new** — SPOT for the non-user-list provisioning knobs |
| `common.sh` | **+4 helpers** — `log_subsection`, `get_user_group`, `resolve_ownership`, `list_prestaged_paths`; sourcing-guard fix (R13 addendum) |
| `provision-user-accounts.sh` | flags + drift/remediation functions; two extractions; one bug fix |
| `00-users.sh` | argument parsing + `--status` / `--dry-run` / `--help` for the `ec2-user` bootstrap scope; redirect for per-user flags (R13 addendum) |
| `RUNBOOK_user_drift_remediation.md` | **new** — operator doc |

The COTS implementation lives in one 1,095-line script
(`SETUP/provisioning/00-users.sh`) whose provisioning path is already decomposed
into per-stage functions, so `remediate_user` could reuse `clone_mcp_rag_repo`
directly. The AWS script is a monolithic `while read` loop. Rather than
refactoring all eight stages into functions (large blast radius on a working
provisioning path), this design extracts **only the two stages remediation needs
to reuse** and leaves the other six inline and byte-identical.

## Naming/path parity table (the "preserve the path names" contract)

| Concept | COTS value | AWS value (this spec) |
|---|---|---|
| Persistent root | `/mcp_rag_eib` | `${PERSISTENT_ROOT}` = `/mdc-mcp-rag` |
| Scratch root | `/mcp_rag_eib/SCRATCH_SPACE` | `${PERSISTENT_ROOT}/SCRATCH` |
| Scratch leaf | `<Username>` (= login name) | `<First.Last>` from `users.conf` full name |
| Shared workspace | per-user clone in scratch | `${PERSISTENT_ROOT}/eib-mcp-rag-server` (shared) |
| Primary group | `pwuser` | `""` → per-user private group |
| Shared group(s) | `docker`, `kasmvnc-cert` | `developers` |
| Per-user MCP config | `<scratch>/.vscode/mcp.json` | `~/.kiro/settings/mcp.json` |
| Templates dir | `SETUP/bashrc_template`, … | `SETUP_AWS/provisioning/user-templates/` |
| User SPOT | `PROVISION_USERS` array | `users.conf` |

## New SPOT — `SETUP_AWS/provisioning/user_config.sh`

Sourced by `provision-user-accounts.sh` after `common.sh` (same order as the
COTS `00-users.sh`). Holds only knobs, no user list — `users.conf` remains the
SPOT for *who* gets provisioned.

```bash
SCRATCH_ROOT="${PERSISTENT_ROOT}/SCRATCH"
WORKSPACE="${PERSISTENT_ROOT}/eib-mcp-rag-server"
SHARED_GROUP="developers"
PROVISION_SUPP_GROUPS=("${SHARED_GROUP}")
PROVISION_PRIMARY_GROUP="${PROVISION_PRIMARY_GROUP:-}"   # empty ⇒ private group (R4)
PROVISION_ADOPT_PRESTAGED="${PROVISION_ADOPT_PRESTAGED:-no}"
PROVISION_KIRO_EXEMPT_USERS=()
PROVISION_AWS_PROFILE="agentcore-rag"
PROVISION_AWS_CRED_PLACEHOLDER="PASTE_YOUR_ACCESS_KEY_ID_HERE"
```

`SHARED_GROUP` and `WORKSPACE` currently live as literals at the top of
`provision-user-accounts.sh`; they move here and the script reads them from the
SPOT. Values are unchanged, so behaviour is unchanged.

`PROVISION_PRIMARY_GROUP` deliberately keeps the COTS name with an empty AWS
default (R4). `resolve_ownership` already implements the exact precedence this
needs — "SPOT group if it exists on the host, else the user's private group" —
so the empty default falls through to `get_user_group` and yields
`user:user`, which is what the AWS host has today.

## `common.sh` additions

Straight ports from `SETUP/provisioning/common.sh` (unchanged logic, so the two
hosts stay readable side by side):

- `log_subsection <text>` — the AWS `common.sh` has `log_section` but not the
  subsection variant the report blocks use.
- `get_user_group <user>` — primary GID → group name, with GID and
  username fallbacks.
- `resolve_ownership <user>` → `user:group`, honouring `PROVISION_PRIMARY_GROUP`
  when it names an existing group, else the private group.
- `list_prestaged_paths <path> <owner>` → direct children not owned by `<owner>`,
  one absolute path per line, sorted; filters by resolved numeric UID.

## Drift taxonomy

`check_user_drifts <username>` prints one tag-line per drift on stdout and
nothing at all for a clean user (the caller distinguishes by testing for an
empty string). This is the machine-parseable sibling of the human-facing
`check_user_integrity`, exactly as on COTS.

| Tag line | Condition | Remediation | Req |
|---|---|---|---|
| `primary_group <actual>` | SPOT non-empty, group exists, user's primary ≠ it | `usermod -g` | R4 |
| `scratch_missing` | `${SCRATCH_ROOT}/<Scratch.Name>` absent | `mkdir -p` + `chown` + `chmod 755` | R5 |
| `scratch_owner <actual>` | top-level owner ≠ `resolve_ownership` | `chown` top-level only | R5 |
| `supp_groups <a,b>` | missing memberships that exist on host | `usermod -aG` each | R6 |
| `ssh_dir_mode <actual>` | `~/.ssh` ≠ 0700 or missing | `mkdir -p`, `chmod 700`, `chown` | R7 |
| `auth_keys_mode <actual>` | `authorized_keys` ≠ 0600 or missing | `touch`, `chmod 600`, `chown` | R7 |
| `aws_dir_mode <actual>` | `~/.aws` ≠ 0700 or missing | `mkdir -p`, `chmod 700`, `chown` | R7 |
| `aws_creds_mode <actual>` | `~/.aws/credentials` ≠ 0600 or missing | skeleton **only if absent**, `chmod 600` | R7 |
| `missing_kiro_mcp` | `~/.kiro/settings/mcp.json` absent | deploy from template | R8 |
| `missing_kiro_steering` | zero `*.md` in `~/.kiro/steering` | copy templates | R8 |
| `stale_kiro_profile <actual>` | `mcp.json` `AWS_PROFILE` ≠ SPOT | **`--force` only**, with timestamped backup | R8 |
| `aws_creds_placeholder` | credentials still hold the placeholder key | none — `[WARN]` + runbook pointer | R8 |
| `missing_gitconfig` | `~/.gitconfig` absent | `write_gitconfig` (whole file) | R14 |
| `stale_git_safe_dirs <count>` | shared repos missing a `safe.directory` entry | `add_missing_safe_dirs` (append only, no `--force`) | R14 |

Ordering note: `scratch_missing` and `scratch_owner` are mutually exclusive by
construction (the owner check only runs when the directory exists), so the
remediation switch can treat them as independent branches without a precedence
rule.

`aws_creds_placeholder` is the one row that is **not** a `[DRIFT]` in the
human-readable report — it renders as `[PENDING user action]`. It is still
emitted by `check_user_drifts` so the two helpers stay symmetric (the COTS
lesson from its T5a discrepancy: both helpers must report the same set), but
`remediate_user` maps it to a `[WARN]` rather than a fix.

## Data flow

```
sudo ./provision-user-accounts.sh --remediate <user> [--dry-run] [--force]
        │
        ├── arg parse → mutex guard (--user ⊗ --remediate)              R2
        ▼
remediate_user <user>
   ├── refuse if ! id <user>                                            R2
   ├── check_user_drifts → tag lines                                    R3
   ├── empty → log "no remediation needed"; return 0                    R3/R11
   ├── DRY_RUN → render_remediation_plan; return 0                      R9
   ├── per-tag surgical fix                                        R4–R8
   │     • scratch: top-level chown; children [PRESERVED] unless
   │       PROVISION_ADOPT_PRESTAGED=yes  (list_prestaged_paths)         R5
   │     • kiro assets: install_kiro_assets  (extracted stage 3)         R8
   │     • aws skeleton: install_aws_skeleton (extracted stage 6)        R7
   │     • stale profile: --force-gated, backup then redeploy            R8
   │     • placeholder creds: [WARN] + runbook pointer, no fix           R8
   └── check_user_integrity  → post-remediation report                  R10
```

## `provision-user-accounts.sh` structure after the change

```
header / set -euo pipefail
source common.sh ; source user_config.sh          # new
usage()
arg parse: --force --user --remediate --status --dry-run --add --help
mutex guard
require root

# --- users.conf accessors -------------------------------------------------
user_fullname <user>            # field 2 from users.conf
user_email <user>               # field 3
scratch_name_for <fullname>     # "Terry McGuinness" → "Terry.McGuinness"
user_scratch_dir <user>         # ${SCRATCH_ROOT}/$(scratch_name_for …)
in_list <needle> <haystack…>

# --- extracted provisioning stages (reused by remediate_user) ------------
install_kiro_assets <user>      # was inline stage 3
install_aws_skeleton <user>     # was inline stage 6

# --- read-only inspection ------------------------------------------------
_fmt_mode <octal>
check_user_integrity <user>     # human-facing, --status
check_user_drifts <user>        # machine-parseable, feeds remediate_user
print_status

# --- plans ---------------------------------------------------------------
render_provisioning_plan <user> <fullname>
render_remediation_plan  <user> <drifts>

# --- remediation ---------------------------------------------------------
remediate_user <user>

# --- dispatch ------------------------------------------------------------
--status     → print_status; exit 0
--remediate  → loop remediate_user; exit 0
default      → the existing while-read loop, with two inserts:
                 (a) --user filter → continue
                 (b) --dry-run → render_provisioning_plan; continue
```

Everything below the dispatch line keeps its current stage numbering and output
strings so R12 (backward compatibility) holds.

## The two extractions

### `install_kiro_assets <username>` (was stage 3)

Verbatim move of the existing block: `mkdir -p` the three `~/.kiro`
subdirectories, copy `user-templates/mcp.json` when missing or `--force`, copy
`user-templates/steering/*.md` and `user-templates/skills/*.md` when missing or
`--force`, then report the steering file count. The loop calls it where the
inline block used to be. `remediate_user` calls it for `missing_kiro_mcp` /
`missing_kiro_steering`.

Only behavioural addition: `chown -R <user>:<group>` on `~/.kiro` at the end.
The loop already achieved this via its blanket `chown -R … "${HOME_DIR}"` in
stage 8; remediation does not run stage 8, so the function must own its output.
Harmless duplication in the provisioning path.

### `install_aws_skeleton <username>` (was stage 6)

Verbatim move, with the guard tightened per R7: the original wrote both
`config` and `credentials` only when `~/.aws` did not exist. The extracted
version creates the directory when missing and writes **each file
independently, only when that file is absent** — so a user who has pasted real
keys into `credentials` but lost `config` gets `config` restored without their
keys being touched. This is a deliberate behaviour improvement, not a
regression: the old code could never reach the write path when the directory
existed, so no existing file is newly at risk.

## Bug fixed in passing

The provisioning loop contains stage 7 (scratch workspace creation) **twice** —
six duplicated lines, `first`/`last`/`SCRATCH_DIR` recomputed and `mkdir -p` /
`chown` / `echo` re-run identically. The duplicate is removed. Effect on
behaviour: one fewer redundant `mkdir -p`/`chown` per user and one fewer
duplicate `[OK] scratch:` line in the output. Noted here because it is the one
place the pre-spec output is *not* byte-identical (AC9 is asserted against the
deduplicated line, not the doubled one).

---

## Decision record — no per-user clone of `eib-mcp-rag-server` on AWS

Recorded 2026-08-12 at the operator's request. requirements.md § "Context" states
this as a fact in the platform-difference table and R8 relies on it (it is why the
COTS `missing_clone` drift has no AWS analogue). The reasoning was not written
down; this section closes that gap.

**Decision.** AWS keeps **one shared checkout** at
`${PERSISTENT_ROOT}/eib-mcp-rag-server`, group `developers`, mode 775. No
per-user clone is provisioned, and a missing one is **not** drift.

**Primary reason — the clone is not the runtime here.** On COTS, each user's
VS Code launches the MCP server as a local stdio child process out of their own
clone (`node <clone>/mcp_server_node/src/UnifiedMCPServer.js full`) against local
ChromaDB and Neo4j. The clone is load-bearing: it *is* the server. On AWS the
server is a remote AgentCore runtime; the user's `~/.kiro/settings/mcp.json`
invokes `mcp-python <shared>/tools/agentcore-kiro-proxy.py --runtime-id arn:…`.
Nothing executes out of a per-user copy — one proxy script is *read* from the
shared tree. The per-user artifact that does matter is `mcp.json`, which is
exactly why that is a drift row and a clone is not.

**Secondary reason — measured cost.** The tree is 27 GB (12 GB `.git`, 14 GB
`supported_repos` across 25 checkouts, 910 MB of actual platform source). Eight
developers × 27 GB = 216 GB against 381 GB free on `/mnt/mdc-mcp-rag`.

**Tertiary reason — version coherence.** One checkout means one proxy version
pinned to one runtime ARN. Eight clones means eight proxy versions drifting
against a runtime that gets redeployed.

**Not a restriction on personal git work.** SCRATCH holds each developer's own
clones of the repos *under study* — `global-workflow` and its branches, GDASApp,
spack-stack, UFS_UTILS, wikis, forks. Census on 2026-08-12: Anton 9 such dirs,
Barry 8, Terry 8; **zero** users have an `eib-mcp-rag-server` clone. The decision
records existing practice.

**Consequence — `safe.directory` is load-bearing.** The shared tree is owned by
`ec2-user`, so every other account needs a git ownership exception for the
workspace *and each of the 25 `supported_repos` checkouts*, or git refuses to
operate there at all. This makes `~/.gitconfig` correctness a first-class concern
of the shared-checkout model, hence R14 below.

**Accepted tradeoff.** A shared working tree has one checked-out branch: two
developers cannot be on different branches simultaneously, and one `git checkout`
changes the tree under everyone. Latent rather than observed so far — only one
account has ever committed there (40 commits, all `Terry.McGuinness`). If it
becomes a real contention point the remedy is a `git worktree` convention
(~910 MB per worktree, no second object store) or a `--reference` clone that
shares objects — **not** eight full clones, and not promoting a per-user clone to
a drift row.

### R14 — `safe.directory` coverage for the shared checkout

Added 2026-08-12 while documenting the decision above; the audit found the
supporting configuration broken for **all eight** developers.

**Defect.** The provisioning loop's `.gitconfig` heredoc hardcoded three
`safe.directory` entries: the workspace, `supported_repos/global-workflow`, and
`supported_repos/global-workflow_dev-v17`. The latter two have not existed since
the multi-tenant rename (`c15080f` renamed the checkouts to
`global-workflow_develop` and `global-workflow_dev-gfs.v17`), and the other 23
git repositories under `supported_repos/` were never listed. Ground truth:

```
$ sudo -u rahul.mahajan git -C .../supported_repos/global-workflow_develop status
fatal: detected dubious ownership in repository at
'/mnt/mdc-mcp-rag/eib-mcp-rag-server/supported_repos/global-workflow_develop'
```

Verified that both the symlink form (`/mdc-mcp-rag/…`) and the resolved form
(`/mnt/mdc-mcp-rag/…`) satisfy git's check, so the existing path convention is
kept; only the list was wrong.

**Fix.** Entries are enumerated from disk, not hardcoded:

- `shared_git_repos()` — prints `${WORKSPACE}` plus each `supported_repos/*` that
  contains a `.git` entry (`-e` covers both the submodule `.git` *file* and a
  standalone `.git` *directory*). Currently 26 paths.
- `write_gitconfig <user> <fullname> <email>` — replaces the heredoc; builds the
  file with a loop. Used only when `.gitconfig` is **absent** (or `--force`).
- `missing_safe_dirs <user>` — prints the shared repos not covered by the user's
  `.gitconfig`. A wildcard `directory = *` entry short-circuits to "none missing".
- `add_missing_safe_dirs <user>` — the repair path for an **existing** file:
  `sudo -u <user> git config --global --add safe.directory <path>` per missing
  entry. Surgical and idempotent, so aliases and credential helpers survive and
  **no `--force` is required**.

Two new drift rows, wired through all four call sites (integrity report, drift
feed, plan renderer, remediation switch):

| Tag | Condition | Fix |
|---|---|---|
| `missing_gitconfig` | `~/.gitconfig` absent | `write_gitconfig` (whole file) |
| `stale_git_safe_dirs <count>` | shared repos unlisted | `add_missing_safe_dirs` (append only) |

They are mutually exclusive by construction, so `remediate_user` uses
`if` / `elif`.

**Self-maintaining.** Because the list is derived from disk, adding or renaming a
`supported_repos` checkout no longer silently breaks every developer's git access
— it shows up as `stale_git_safe_dirs` on the next `--status`.

Operator testing found three defects, all the same shape: a flag that was
accepted or ignored instead of being validated.

### R13.1 — `require_value` guard on username flags

`--user` and `--remediate` used `[[ $# -ge 2 ]]`, which only checks that *some*
next word exists. `--user --help` therefore bound the username `--help`, skipped
`usage()` entirely, and **fell through into a real provisioning run** (it reached
`groupadd`-check + `chgrp -R`/`chmod -R g+rX` on `${WORKSPACE}` before the loop
found no matching user). A new `require_value <flag> <value>` helper rejects both
an empty value and any value starting with `-`:

```bash
require_value() {
  local flag="$1" value="${2:-}"
  [[ -n "${value}"     ]] || { echo "[ERROR] ${flag} requires a username"; usage; exit 2; }
  [[ "${value}" != -*  ]] || { echo "[ERROR] ${flag} requires a username, got the option '${value}'"; usage; exit 2; }
}
```

### R13.2 — `--status` honours the explicit user list

`print_status` iterated `users.conf` unconditionally, so `--status --user x`
dumped all eight users. It now takes an optional user list:
`print_status [<user>…]` — empty means "all of `users.conf`". The dispatch block
passes `TARGET_USERS` or `REMEDIATE_USERS` (mutually exclusive, so at most one is
populated), using the `${arr[@]+"${arr[@]}"}` idiom so an empty array is safe
under `set -u` on older bash. A requested name absent from `users.conf` still
produces a block carrying the `users.conf` drift row rather than being dropped.

### R13.3 — `00-users.sh` parses arguments

`00-users.sh` had **no** argument parsing: every flag was accepted and discarded.
`--help` printed nothing, and `--dry-run` performed its full
`mkdir`/`touch`/`chmod`/`chown` mutation despite the flag. It now supports
`--help`, `--status`, and `--dry-run` over its own narrow scope (the `ec2-user`
bootstrap account) and rejects `--user` / `--remediate` / `--force` / `--add`
with a `wrong_script()` error naming `provision-user-accounts.sh`.

The header comment now states the split explicitly, because the confusion is
structural rather than accidental: **on COTS, `00-users.sh` IS the per-user
provisioning script.** An operator with COTS muscle memory reaches for
`00-users.sh` on AWS and finds a file that appears to accept their flags. The
redirect makes that mistake self-correcting.

Additions to `00-users.sh`: `usage()`, `wrong_script()`, `_mode()` (stat mode or
`missing`), a `--status` block reporting account presence + `~/.ssh` mode +
`authorized_keys` mode + `~/.ssh` owner + key-line count, and a two-section
`--dry-run` plan. The default (no-flag) path is byte-identical apart from the
`log_section` title, which gains the `(ec2-user bootstrap)` qualifier.

### Pre-existing bug found during R13 verification — `common.sh` sourcing guard

Verifying `00-users.sh` under the orchestrator (`provision.sh --only 00`) exposed
a defect that predates this spec and affects **all nine** subscripts:

```bash
[[ -n "${_AWS_COMMON_SH_LOADED:-}" ]] && return 0
export _AWS_COMMON_SH_LOADED=1          # <-- exported
```

`provision.sh` sources `common.sh`, then launches each subscript as a child
`bash`. The exported guard is inherited, so the child's own `source common.sh`
returns early and **none of the helpers are defined** in the child →
`require_root: command not found`, exit 127, at stage 00.

Proven independently of this spec's edits, against the committed `common.sh`:

```
$ bash -c 'source common.sh; bash -c "source common.sh; type -t require_root"'
parent: function
child:  UNDEFINED
```

Fix: drop `export`. Repeated sourcing inside one process is still guarded; each
subprocess sources fresh. One line, and `provision.sh --only 00` now completes.

The COTS `SETUP/provisioning/common.sh` carries the identical
`export _COMMON_SH_LOADED=1`. Not touched — this spec is AWS-only — but it is
worth a follow-up on that platform.

## `check_user_integrity` output shape

```
User: terry.mcguinness (Terry McGuinness)
  account: [OK]
  primary group: terry.mcguinness [OK]                     # or DRIFT when SPOT set
  supplementary groups: developers [OK]
  scratch: /mdc-mcp-rag/SCRATCH/Terry.McGuinness [OK]
  ~/.ssh mode: 0700 [OK]
  ~/.ssh/authorized_keys mode: 0600 [OK]
  ~/.aws mode: 0700 [OK]
  ~/.aws/credentials mode: 0600 [OK]
  ~/.aws/credentials: [PENDING user action — placeholder key; see RUNBOOK_developer_aws_credentials.md]
  ~/.kiro/settings/mcp.json: [OK]
  ~/.kiro/steering: 4 file(s) [OK]
  mcp.json AWS_PROFILE: agentcore-rag [OK]
```

Rows are omitted rather than faked when the underlying condition does not apply
on this host (COTS precedent: the `kasmvnc-cert` row is omitted when the group
is absent). Specifically: the primary-group row is omitted when
`PROVISION_PRIMARY_GROUP` is empty (R4), and all `~/.kiro` rows are omitted for
users on `PROVISION_KIRO_EXEMPT_USERS` (R8).

## Deliberately unchanged

- `users.conf` — remains the SPOT for the user list; format untouched.
- **`00-users.sh` (AWS)** — stays the `ec2-user`-only SSH bootstrap in *scope*.
  R13.3 adds argument parsing to it, but no per-user capability: it redirects
  those flags to `provision-user-accounts.sh`.
- `provision.sh` orchestrator — `provision-user-accounts.sh` is not in its
  `SCRIPTS` array and stays out of it (per-user provisioning is an operator
  action, not part of the host build).
- `user-templates/*` — content untouched. `PROVISION_AWS_PROFILE` mirrors the
  template's current value rather than changing it.
- `fix-user-mcp-aws-profile.sh` — left in place. `stale_kiro_profile` supersedes
  it functionally; retiring it is an operator decision (see requirements.md
  § "Open question").
- The COTS tree (`SETUP/provisioning/`) — zero edits.

## Risks

- **RA-1 — `usermod -g` on a logged-in user.** Inherited from COTS R-risk-1.
  Inert on AWS by default (R4 empty SPOT), so this only applies if an operator
  opts into a shared primary group.
- **RA-2 — scratch top-level flip leaves mixed ownership.** Same as COTS
  R-risk-3; documented preserve semantics, not a regression.
- **RA-3 — `stale_kiro_profile` + `--force` drops user customisations** in
  `mcp.json` (extra servers, edited `autoApprove`). Mitigated by the
  timestamped backup and by defaulting to report-only.
- **RA-4 — scratch-name derivation depends on `users.conf` full names.** A
  malformed or missing full-name field yields a wrong scratch path, which would
  present as a false `scratch_missing` drift. Mitigated: `user_fullname` returns
  empty for an unknown user and the drift functions refuse to proceed with an
  `[ERROR]` naming `users.conf` rather than guessing a path.
- **RA-5 — `check_user_drifts` reads `~/.kiro/settings/mcp.json` as root** to
  compare `AWS_PROFILE`. Read-only, and the value is a profile name, not a
  secret. Credentials files are never read for content — only `stat` mode and a
  single `grep -q` for the literal placeholder string, whose match result is
  reported as a boolean, never echoing file contents.
