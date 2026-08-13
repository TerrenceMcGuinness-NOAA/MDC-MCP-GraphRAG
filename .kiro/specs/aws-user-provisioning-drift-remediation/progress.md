# AWS User-Provisioning Drift Remediation — Progress

## Status: **T1–T8 COMPLETE (code + docs, zero host mutation) — T9–T12 operator-gated**

- 2026-08-12 — Spec authored (`requirements.md`, `design.md`, `tasks.md`, this
  file) after reviewing the COTS `user-provisioning-drift-remediation` spec and
  its landed implementation (`ce121cd`).
- 2026-08-12 — T1–T8 implemented and verified read-only against the live AWS
  host. Staged, not committed (steering rule 08).

## Task tracker

| Task | Status | Notes |
|------|--------|-------|
| T1 `user_config.sh` SPOT | **done** | 9 fields; `PROVISION_PRIMARY_GROUP=""` (AWS default) |
| T2 `common.sh` helper ports | **done** | `log_subsection`, `get_user_group`, `resolve_ownership`, `list_prestaged_paths` |
| T3 flags + accessors + dispatch | **done** | `--user`, `--remediate`, `--status`, `--dry-run`, `--help`; mutex guard fires before `require_root` (no sudo needed to see the error) |
| T4 stage extractions + dedup | **done** | `install_kiro_assets`, `install_aws_skeleton`; duplicated stage-7 block removed |
| T5 integrity + drift helpers | **done** | 12-row taxonomy; verified against `id`/`stat` ground truth |
| T6 plan renderers + `remediate_user` | **done** | all 10 renderer branches exercised |
| T7 RUNBOOK | **done** | `RUNBOOK_user_drift_remediation.md` |
| T13 R13 argument-handling fixes | **done** | operator-reported 2026-08-12; 3 defects + 1 pre-existing `common.sh` bug they exposed |
| T14 R14 `safe.directory` coverage | **done** | operator-requested decision write-up; audit found git access broken for all 8 users |
| T8 CHANGELOG + stage | **done** | staged; commit awaits operator |
| T9 remediate one real user | operator-gated | preserve-vs-adopt decision required first |
| T10 idempotency re-run | operator-gated | blocked on T9 |
| T11 full-host `[OK]` gate | operator-gated | blocked on T10 |
| T12 closeout | pending | blocked on T11 |

## Verification log (2026-08-12, live host, read-only)

`bash -n` clean on all three shell files.

**T1/T2 probes** — `resolve_ownership terry.mcguinness` →
`terry.mcguinness:terry.mcguinness` with the empty SPOT and
`terry.mcguinness:developers` with `PROVISION_PRIMARY_GROUP=developers`.
`list_prestaged_paths /mdc-mcp-rag/SCRATCH ec2-user` → the eight scratch leaves.

**T3 probes** — `--user X --remediate Y` → `mutually exclusive`, exit 2.
`--remediate` (no arg) → exit 2. `--bogus` → exit 2. `--help` → exit 0.

**T5 `--status`** — one block per `users.conf` user, exit 0. Three real drifts
found and independently confirmed via `stat`:

| User | Drift | Ground truth |
|---|---|---|
| `anton.fernando` | `~/.aws/credentials mode` `0664` ≠ `0600` | `stat -c %a` → `664` ✓ |
| `alexander.richert` | `~/.ssh/authorized_keys` missing | file absent ✓ |
| `rahul.mahajan` | `~/.ssh/authorized_keys` missing | file absent ✓ |

Five users (`barry.baker`, `david.huber`, `alexander.hrabski`,
`alexander.richert`, `rahul.mahajan`) show `[PENDING user action]` — they have
never pasted an IAM access key. Not operator drift.

`terry.mcguinness` and `daniel.sarmiento` are fully `[OK]`.

**T6 dry-run plans** — section count equals drift-row count in every case:
`anton.fernando` 1/1, `rahul.mahajan` 2/2, `barry.baker` 1/1,
`terry.mcguinness` → `No drift detected`. `nonexistent.user` → refusal, exit 1.

**Branch coverage.** `PROVISION_PRIMARY_GROUP=developers` (env override) forced
the `primary_group` + `scratch_owner` branches live: rendered
`usermod -g developers`, a top-level-only `chown`, and a real
`[PRESERVED] /mdc-mcp-rag/SCRATCH/Terry.McGuinness/temp`.
`PROVISION_ADOPT_PRESTAGED=yes` flipped the same case to
`chown -R … # ADOPT 1 pre-staged path(s)`. `stale_kiro_profile` (both
report-only and `--force`), `scratch_missing`, and `missing_kiro_*` were
exercised via direct `render_remediation_plan` invocation with synthetic drift
strings.

`mcp_json_profile` unit probe: real config → `agentcore-rag`; malformed JSON →
`__PARSE_ERROR__`; `{}` → empty.

**Zero mutation confirmed twice.** A `stat` census of `~/.ssh`,
`~/.ssh/authorized_keys`, `~/.aws`, `~/.aws/credentials` across all eight users
is byte-identical before and after the full `--status` + dry-run sequence, and
`--status` output diffs empty against its pre-dry-run capture.

## Deviations from the COTS spec (and why)

1. **`PROVISION_PRIMARY_GROUP` defaults to empty.** COTS uses shared `pwuser`;
   AWS gives each user a private primary group. Same field name and same
   `resolve_ownership` precedence, inert by default here.
2. **No `missing_clone` analogue.** AWS has one shared checkout, not per-user
   clones. Its role is taken by `missing_kiro_mcp` / `missing_kiro_steering` /
   the `aws_*` rows.
3. **Two AWS-only drift classes** — `stale_kiro_profile` and
   `aws_creds_placeholder` — cover cloud-auth state that has no COTS equivalent.
4. **`--dry-run` also covers the provisioning path**, mirroring the loop's eight
   numbered stages. COTS renders its plan from already-decomposed functions;
   here the plan is a static mirror because six of the eight stages stay inline.
5. **`aws_creds_placeholder` is `[PENDING user action]`, not `[DRIFT]`.** Only
   the developer can resolve it.

## Findings surfaced by this work (operator decisions, not code)

- **Contradictory `AWS_PROFILE` intent.** `user-templates/mcp.json` sets
  `"AWS_PROFILE": "agentcore-rag"` (commit `6435643`), while the untracked
  `fix-user-mcp-aws-profile.sh` exists to strip that exact key. This spec treats
  the committed template as authoritative. One of the two should be retired —
  see requirements.md § "Open question".
- **Steering-bundle skew.** `~/.kiro/steering` holds 2 files for the five
  earliest users and 4 for the three most recent. The check is presence-only
  (content drift is a stated non-goal), so all report `[OK]`. If the newer two
  files matter for everyone, that is a `--force` refresh, not a drift fix.
- **`~/.aws/credentials` mode `0664` on `anton.fernando`** is the one genuine
  security-relevant finding: a credentials file readable by the `developers`
  group. It is group-readable but the file still holds the placeholder-free
  content only that user wrote; rotating is the safe follow-up if a real key was
  ever in it while group-readable.

## Corrections log

### 2026-08-12 — T14, no-per-user-clone decision written up; broke-in-the-open finding

The operator asked to "expound and clarify the decision not to clone the
eib-mcp-rag-server repo in the user's SCRATCH space." requirements.md asserted it
as a fact and R8 depended on it, but the reasoning was never recorded. Written up
in design.md § "Decision record" (technical) and RUNBOOK § "Why there is no
per-user clone" (operator-facing), grounded in a live census:

| Evidence | Value |
|---|---|
| Shared checkout | `/mdc-mcp-rag/eib-mcp-rag-server`, `ec2-user:developers`, 775 (group-writable), branch `develop` |
| Tree size | 27 GB total — 12 GB `.git`, 14 GB `supported_repos` (25 checkouts), 910 MB platform source |
| 8 per-user clones would cost | 216 GB vs 381 GB free on `/mnt/mdc-mcp-rag` |
| Users with an `eib-mcp-rag-server` clone in scratch | **0 of 8** |
| What scratch actually holds | personal clones of the repos under study (Anton 9 dirs, Barry 8, Terry 8: `global-workflow*`, GDASApp, spack-stack, UFS_UTILS, wikis, forks) |
| Commits into the shared checkout | 40, all `Terry.McGuinness` — shared-write contention is latent, not observed |

The load-bearing distinction: on COTS the clone **is** the MCP runtime (each
user's VS Code launches `node <clone>/mcp_server_node/src/UnifiedMCPServer.js`
against local ChromaDB/Neo4j). On AWS the runtime is remote (AgentCore) and the
only local artifact is `tools/agentcore-kiro-proxy.py`, *read* out of the shared
tree. That is why `mcp.json` is a drift row and a clone is not.

**The audit found the model's supporting configuration broken for all eight
developers.** The shared tree is `ec2-user`-owned, so every account needs a git
`safe.directory` exception per shared repo. The provisioning heredoc hardcoded
three entries, two of which name directories that have not existed since the
multi-tenant rename (`c15080f`: `global-workflow` → `global-workflow_develop`,
`global-workflow_dev-v17` → `global-workflow_dev-gfs.v17`), and the other 23 git
repos under `supported_repos/` were never listed at all. Proof:

```
$ sudo -u rahul.mahajan git -C .../supported_repos/global-workflow_develop status
fatal: detected dubious ownership in repository at
'/mnt/mdc-mcp-rag/eib-mcp-rag-server/supported_repos/global-workflow_develop'
```

So the shared-checkout decision was sound but its one hard requirement had
silently rotted — developers could read the tree but git refused to work in any
of the 25 checkouts. Fixed by enumerating the entries from disk (26 paths today)
and adding two drift rows. Repair for existing accounts **appends** via
`git config --global --add` as the user rather than rewriting `~/.gitconfig`, so
personal settings survive and no `--force` is needed. `--status` now shows
`[DRIFT expected=26 shared repo(s) actual=1]` for all eight users.

Also verified that both path forms satisfy git's ownership check (symlink
`/mdc-mcp-rag/…` and resolved `/mnt/mdc-mcp-rag/…`), so the existing convention
was kept — only the list was wrong. Because the list is now derived from disk,
the next `supported_repos` rename surfaces as drift instead of silently breaking
everyone.

### 2026-08-12 — T13, operator-reported argument-handling defects

The operator tested the delivered scripts and reported "`--help` does not print
usage and `--user` does not work with `--status`", then clarified they had been
running **`00-users.sh`**, not `provision-user-accounts.sh`. Three real defects,
all the same shape — a flag accepted or ignored instead of validated:

1. **`--user --help` swallowed the flag as a username** and then fell through
   into a real, mutating provisioning run (it reached the `groupadd` check and
   `chgrp -R`/`chmod -R g+rX` on `${WORKSPACE}` before the loop found no matching
   user). Root cause: `[[ $# -ge 2 ]]` only checks that a next word exists, not
   that it is a value. Fixed with a `require_value` helper that also rejects any
   `-`-prefixed value. This was my defect, introduced with the new flags.
2. **`--status` ignored `--user`.** `print_status` iterated `users.conf`
   unconditionally. Fixed by giving it an optional scope list. My defect —
   the flag combination was never in a verify gate, which is exactly the gap
   an acceptance criterion is supposed to close (now AC11).
3. **`00-users.sh` had no argument parsing at all** — pre-existing, and the most
   serious of the three: `--dry-run` performed its full `mkdir`/`touch`/`chmod`/
   `chown` despite the flag, and `--help` printed nothing. Fixed by adding
   `--help` / `--status` / `--dry-run` over its own scope plus an explicit
   redirect for the per-user flags.

**The naming trap is structural, not operator error.** On COTS,
`SETUP/provisioning/00-users.sh` *is* the per-user provisioning script with
`--user` / `--remediate` / `--status` / `--dry-run`. On AWS the same filename is
the narrow `ec2-user` bootstrap. Reaching for `00-users.sh` first is the
*correct* instinct carried across platforms; the script silently accepting the
flags is what made it a dead end. My design.md named
`provision-user-accounts.sh` as the AWS home for the capability and treated
`00-users.sh` as "deliberately unchanged" — correct on scope, wrong on
discoverability. Fixed by making the split explicit in `00-users.sh`'s header,
usage text, and error messages.

### Pre-existing bug exposed while verifying the above

`provision.sh --only 00` failed with `require_root: command not found` (exit
127). Cause: `common.sh` ended its sourcing guard with
`export _AWS_COMMON_SH_LOADED=1`. `provision.sh` sources `common.sh` and then
launches each subscript as a child `bash`; the exported guard is inherited, the
child's own `source common.sh` returns early, and **no helper function is defined
in the child**. This affected all nine subscripts, not just stage 00.

Proven against the committed `common.sh`, independent of this spec's edits:

```
$ bash -c 'source common.sh; bash -c "source common.sh; type -t require_root"'
parent: function
child:  UNDEFINED
```

Fixed by dropping `export`. Verified: `type -t require_root` → `function` in both
parent and child; double-sourcing in one process still guarded;
`provision.sh --only 00` → `[OK] Provisioning complete`.

Out of scope but worth a follow-up: COTS `SETUP/provisioning/common.sh` carries
the identical `export _COMMON_SH_LOADED=1`, and its `--user`/`--remediate`
parsing uses the same `[[ $# -ge 2 ]]` pattern that produced defect (1).

### Hazard noticed, deliberately NOT acted on

With `provision.sh` unblocked, be aware that stage `01-directories.sh` ends with
`chown -R "${OWNER}:${OWNER}" "${PERSISTENT_ROOT}"` where `OWNER` is
`get_actual_user` (i.e. `ec2-user`). Running it today would recursively re-own
**`/mdc-mcp-rag/SCRATCH/*`**, clobbering every developer's scratch ownership. It
predates this spec and is an operator decision, not a drift-remediation concern —
flagged here rather than changed.

## Human-gated boundaries

- T1–T8 are code + docs with zero host mutation. Verified above.
- T9–T11 issue real `usermod` / `chown` / `chmod` / template deploys on live
  accounts. The operator drives them, after choosing preserve vs adopt per user.
- T12 (commit) requires explicit operator authorisation per steering rule 08.

## Known follow-ups (out of scope)

- `--remediate-all` bulk mode. Deliberately omitted; explicit per-user is safer.
- Content-level drift on `.bashrc` / `.gitconfig` / steering files (currently
  presence-only).
- Folding `provision-user-accounts.sh` into the `provision.sh` orchestrator.
  Per-user provisioning stays an operator action, not part of the host build.
