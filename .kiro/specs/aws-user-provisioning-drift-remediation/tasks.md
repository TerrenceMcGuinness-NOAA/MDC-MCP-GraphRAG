# AWS User-Provisioning Drift Remediation — Tasks

Each task is one file / one concern with an explicit `Verify:` gate. T1–T6 are
code + docs and mutate nothing on the host. T7+ are operator-gated (real
`usermod` / `chown` / template deploys on live accounts).

## T1 — `user_config.sh` SPOT (R4, R5, R6, R8)

- Create `SETUP_AWS/provisioning/user_config.sh` with the nine fields from
  design.md § "New SPOT".
- `PROVISION_PRIMARY_GROUP` defaults to the empty string (R4).
- **Verify**:
  - `bash -n SETUP_AWS/provisioning/user_config.sh` → exit 0.
  - `bash -c 'PERSISTENT_ROOT=/mdc-mcp-rag; source SETUP_AWS/provisioning/user_config.sh; echo "${SCRATCH_ROOT}|${SHARED_GROUP}|[${PROVISION_PRIMARY_GROUP}]"'`
    → `/mdc-mcp-rag/SCRATCH|developers|[]`.

## T2 — `common.sh` helper ports (R5)

- Add `log_subsection`, `get_user_group`, `resolve_ownership`,
  `list_prestaged_paths` to `SETUP_AWS/provisioning/common.sh`.
- **Verify**:
  - `bash -n SETUP_AWS/provisioning/common.sh` → exit 0.
  - `resolve_ownership terry.mcguinness` → `terry.mcguinness:terry.mcguinness`
    with the empty SPOT; → `terry.mcguinness:developers` with
    `PROVISION_PRIMARY_GROUP=developers`.
  - `list_prestaged_paths /mdc-mcp-rag/SCRATCH ec2-user` → the eight
    non-ec2-user-owned scratch leaves, sorted.

## T3 — flags, accessors, dispatch (R1, R2, R9, R12)

- Source `common.sh` + `user_config.sh`; drop the `SHARED_GROUP` / `WORKSPACE`
  literals in favour of the SPOT.
- Add `usage()`; extend arg parsing with `--user`, `--remediate`, `--status`,
  `--dry-run`, `--help`; keep `--force` and `--add`.
- Add the `--user ⊗ --remediate` mutex guard.
- Add `user_fullname`, `user_email`, `scratch_name_for`, `user_scratch_dir`,
  `in_list`.
- Add the `--status` and `--remediate` dispatch blocks ahead of the loop, plus
  the loop's `--user` filter and `--dry-run` gate inserts.
- **Verify**:
  - `bash -n` → exit 0.
  - `--user X --remediate Y` → `mutually exclusive`, exit 2.
  - `--remediate` with no argument → error, exit 2.
  - `--help` → usage, exit 0.
  - `user_scratch_dir terry.mcguinness` → `/mdc-mcp-rag/SCRATCH/Terry.McGuinness`
    (matches the on-disk CamelCase directory).

## T4 — stage extractions + duplicate removal (R7, R8, R12)

- Extract stage 3 → `install_kiro_assets <user>`; stage 6 →
  `install_aws_skeleton <user>`; call both from the loop where the inline blocks
  were.
- `install_aws_skeleton` writes `config` and `credentials` independently, each
  only when absent (never clobbers a real key).
- Remove the duplicated stage-7 scratch block.
- **Verify**:
  - `bash -n` → exit 0.
  - `grep -c 'Create scratch workspace' provision-user-accounts.sh` → 1 (was 2).
  - The eight stage `[OK]`/`[SKIP]` output strings are unchanged (grep each).

## T5 — `check_user_integrity`, `check_user_drifts`, `print_status` (R1, R3–R8)

- Add `_fmt_mode`, the two symmetric check helpers per the design's drift
  taxonomy, and `print_status`.
- Omit rows that do not apply (empty primary-group SPOT; exempt users).
- Emit `aws_creds_placeholder` as `[PENDING user action]` in the human report.
- **Verify** (read-only, live host):
  - `sudo ./provision-user-accounts.sh --status` → one block per `users.conf`
    user, exit 0.
  - Every `[OK]`/`[DRIFT]` row cross-checked against `id`, `stat -c '%a'`,
    `stat -c '%U:%G'` ground truth for at least two users.
  - `check_user_drifts <clean user>` → empty output.
  - `--status` run leaves the host unchanged (`stat` before/after identical).

## T6 — plan renderers + `remediate_user` (R2, R3, R9, R10, R11)

- Add `render_provisioning_plan`, `render_remediation_plan`, `remediate_user`.
- R2 refusal fires before drift detection so it also applies under `--dry-run`.
- `stale_kiro_profile` remediation is `--force`-gated with a timestamped backup.
- **Verify** (dry-run only — zero mutation):
  - `--dry-run --remediate nonexistent.user` → `does not exist`, exit 1.
  - `--dry-run --remediate <clean user>` → `No drift detected`, exit 0.
  - `--dry-run --remediate <drifted user>` → numbered plan whose command count
    equals the drift-row count from `check_user_drifts`.
  - `--dry-run` (no `--remediate`) → eight-stage plan per user, no mutation.
  - Post-run `--status` output is identical to the pre-run capture (diff empty).

## T13 — R13 argument-handling fixes (operator-reported, 2026-08-12)

Three defects found by operator testing, plus one pre-existing bug they exposed.

- `require_value <flag> <value>` in `provision-user-accounts.sh`: reject an empty
  or `-`-prefixed value for `--user` / `--remediate` (R13.1).
- `print_status [<user>…]` takes an optional scope list; the `--status` dispatch
  passes `TARGET_USERS` or `REMEDIATE_USERS` (R13.2).
- `00-users.sh`: add `usage()`, `wrong_script()`, `_mode()`, argument parsing,
  a `--status` block, and a `--dry-run` plan; header documents the COTS↔AWS
  entry-point split (R13.3).
- `common.sh`: drop `export` from the `_AWS_COMMON_SH_LOADED` guard so subscripts
  launched by `provision.sh` still get the helper functions.
- **Verify**:
  - `bash -n` on all four touched shell files → exit 0.
  - `--user --help` → `requires a username, got the option '--help'`, exit 2, and
    the provisioning banner never prints.
  - `--remediate --dry-run` → same shape, exit 2. `--user` (no value) → exit 2.
  - `--status --user <a>` → 1 block; `--status --user <a> --user <b>` → 2 blocks;
    bare `--status` → 8 blocks; `--status --user ghost.user` → 1 block carrying
    the `users.conf` drift row.
  - `00-users.sh --help` → usage, exit 0; `--dry-run` → plan only;
    `--status` → read-only report; `--user x` → redirect error, exit 2;
    bare → unchanged behaviour.
  - `bash -c 'source common.sh; bash -c "source common.sh; type -t require_root"'`
    → `function` in both parent and child.
  - `sudo ./provision.sh --only 00` → `[OK] Provisioning complete`.
  - Post-fix `stat` census across all eight users identical to the pre-work
    baseline.

## T14 — R14 `safe.directory` coverage (operator-requested, 2026-08-12)

Triggered by the request to document the no-per-user-clone decision; the audit
found the model's supporting config broken for all eight developers.

- Add `shared_git_repos()`, `missing_safe_dirs()`, `write_gitconfig()`,
  `add_missing_safe_dirs()`.
- Replace the loop's hardcoded `.gitconfig` heredoc with `write_gitconfig`, and
  route the already-exists branch to `add_missing_safe_dirs` instead of skipping.
- Add `missing_gitconfig` + `stale_git_safe_dirs` to `check_user_integrity`,
  `check_user_drifts`, `render_remediation_plan`, and `remediate_user`; update
  stage [4] of `render_provisioning_plan`.
- Record the decision in design.md and the RUNBOOK.
- **Verify**:
  - `bash -n` → exit 0.
  - `shared_git_repos | wc -l` → 26 (workspace + 25 `supported_repos` git dirs).
  - `--status` shows `git safe.directory: [DRIFT expected=26 … actual=1]` for all
    eight users (pre-fix `.gitconfig`s list 3 entries, only 1 of which resolves).
  - Dry-run plan lists 25 `git config --global --add safe.directory` lines for a
    drifted user; no mutation.
  - Ground truth before: `sudo -u <user> git -C <shared submodule> status` →
    `fatal: detected dubious ownership`.
  - **Operator-gated (real run)**: after `--remediate <user>`, that same command
    succeeds, `--status` reads `26/26 shared repo(s) [OK]`, and a `diff` of the
    user's `.gitconfig` shows only added `directory =` lines.

## T7 — RUNBOOK (documentation)

- Write `SETUP_AWS/provisioning/RUNBOOK_user_drift_remediation.md`: flag
  reference, drift taxonomy table, preserve-vs-adopt decision, the
  COTS↔AWS mapping table, and the `stale_kiro_profile` / `--force` caution.
- **Verify**: `grep -c -- '--remediate' RUNBOOK_user_drift_remediation.md` → ≥ 3.

## T8 — CHANGELOG + stage (documentation)

- Add a CHANGELOG entry naming this spec.
- `git add` the four `SETUP_AWS/provisioning/` paths, the spec directory, and
  `CHANGELOG.md`. **No commit** (steering rule 08).
- **Verify**: `git diff --cached --stat` lists exactly the intended paths.

## T9 — operator-gated: remediate one real user

- Pick the user with the smallest drift set from T5's `--status` output.
- Decide **preserve** (default) vs **adopt** (`PROVISION_ADOPT_PRESTAGED=yes`)
  for scratch children before running.
- Run `--dry-run --remediate <user>`, review, then run without `--dry-run`.
- **Verify**: post-run report shows `[OK]` on every previously-drifted row;
  the user can still `ssh` in and `ws` / `work` aliases resolve.

## T10 — operator-gated: idempotency (R11)

- Re-run `--remediate <same user>` immediately.
- **Verify**: `No drift detected`, zero `usermod`/`chown`/`cp` lines in output.

## T11 — operator-gated: full-host `[OK]` gate

- `--remediate` each remaining drifted user, then `--status`.
- **Verify**: every user reports `[OK]` on all applicable rows, with only
  `[PENDING user action]` rows remaining for users who have not yet pasted
  their IAM access keys.

## T12 — closeout

- Update `progress.md` with live outcomes; confirm CHANGELOG accuracy.
- Operator authorises the commit.
