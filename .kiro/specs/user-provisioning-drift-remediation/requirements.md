# User-Provisioning Drift Remediation — Requirements

**Spec ID**: `user-provisioning-drift-remediation`
**Parent spec**: [`user-provisioning-ownership-hardening`](../user-provisioning-ownership-hardening/) (landed 2026-07-15 as `dc20d69` + `30af7fd` on `develop`)
**Trigger**: 2026-07-15 — the T6 `--status` upgrade in the parent spec surfaced pre-existing drift on three legacy accounts (`Anna.Smoot`, `Brian.Curtis`, `Georgios.Britzolakis`) that the T8 provisioning path cannot fix. This spec closes that drift with a purpose-built `--remediate` flag; no other scope.

## Context — what we verified on 2026-07-15

Post-T8 `sudo ./00-users.sh --status` output, verbatim (see [parent spec progress.md](../user-provisioning-ownership-hardening/progress.md)):

```
User: Anna.Smoot
  primary group: [DRIFT expected=pwuser actual=Anna.Smoot]
  scratch:       [DRIFT expected=Anna.Smoot:pwuser        actual=Terry.McGuinness:pwuser]
  supp groups:   [DRIFT expected=docker,kasmvnc-cert      actual=docker]

User: Brian.Curtis
  primary group: [DRIFT expected=pwuser actual=Brian.Curtis]
  scratch:       [DRIFT expected=Brian.Curtis:pwuser      actual=Terry.McGuinness:pwuser]
  supp groups:   [DRIFT expected=docker,kasmvnc-cert      actual=docker]

User: Georgios.Britzolakis
  primary group: [DRIFT expected=pwuser actual=Georgios.Britzolakis]
  scratch:       [DRIFT expected=Georgios.Britzolakis:pwuser actual=Terry.McGuinness:pwuser]
  supp groups:   [DRIFT expected=docker,kasmvnc-cert      actual=docker]
```

Terry.McGuinness and Anton.Fernando are already `[OK]` on all six checks.

The parent spec's `00-users.sh` cannot remediate this drift because:

1. `create_user()` short-circuits on `id ${user}` returning 0 — `useradd -g pwuser` never re-runs on an existing user.
2. `create_scratch_space()` treats non-user-owned children as R3 pre-staged content and preserves them; the top-level owner-flip does not cascade.
3. `add_to_groups()` runs unconditionally per invocation but never re-detects missing memberships — it just calls `usermod -aG` and moves on. Silent no-op if a group doesn't exist on the host.

Remediation therefore needs its own, differently-shaped code path.

## Requirements (EARS)

### R1 — `--remediate <username>` flag

`00-users.sh` **shall** accept `--remediate <username>` (repeatable) alongside the existing `--user`, `--dry-run`, and `--status` flags. `--remediate` targets a user who **already exists**; it is not for creation and shall refuse (with `[ERROR]` + exit 1) when the target user is missing.

### R2 — drift-driven scope

For each target user, the system **shall** call `check_user_integrity` (T6 helper) and apply **only** the fixes needed for each `[DRIFT]` row. A user reporting `[OK]` on all six checks is a clean no-op that logs "no remediation needed" and exits 0.

### R3 — primary-group remediation

When `check_user_integrity` reports primary-group drift, the system **shall** invoke `usermod -g "${PROVISION_PRIMARY_GROUP}" <user>` iff the group exists on the host. If missing, emit `[WARN]` naming the group and skip the fix (matches parent-spec R2 fallback).

### R4 — scratch-owner remediation (R3-safe)

When `check_user_integrity` reports scratch-dir top-level owner drift, the system **shall** `chown "${user}:${PROVISION_PRIMARY_GROUP}" "${SCRATCH_ROOT}/<user>"` on the **top level only** (no `-R`). Children retain their existing ownership under the same preservation semantics as the parent spec's R3. If any child is not owned by the target user post-fix, the system **shall** enumerate them as `[PRESERVED]` in the report (identical shape to the parent-spec preserve output), and **shall not** adopt them unless `PROVISION_ADOPT_PRESTAGED=yes` is set (in which case it applies `chown -R` — same opt-in as the parent spec).

### R5 — supplementary-group remediation

For each supplementary group that `check_user_integrity` reports as missing AND that exists on the host, the system **shall** invoke `usermod -aG <group> <user>`. Missing groups on the host emit `[WARN]` and are skipped (never fail the run).

### R6 — `--dry-run` integration

`--dry-run --remediate <user>` **shall** render the planned `usermod` / `chown` commands with resolved substitution and mutate nothing. Format follows the parent spec's `render_provisioning_plan()` pattern. Zero-drift users render "no drift detected, no action" and exit 0.

### R7 — before/after report

At end of a real (non-dry-run) run, the system **shall** re-invoke `check_user_integrity` for each targeted user and emit a compact before → after diff. Success criterion: every previously-drifted row is now `[OK]` (unless skipped per R3/R4/R5's host-condition guards, which must be surfaced).

### R8 — idempotency

Running `--remediate <user>` twice back-to-back **shall** produce identical `[OK]` output on the second run, with zero mutating commands issued.

### R9 — refusal on non-existent user

`--remediate NonExistent.User` **shall** print `[ERROR] user NonExistent.User does not exist; --remediate is not for creation` and exit 1 without touching the host. (Contrast with `--user` which creates missing users.)

### R10 — missing-clone drift (Option C, added 2026-07-15)

A user for whom no `${SCRATCH_ROOT}/<user>/eib-mcp-rag-server/.git` directory exists **shall** be treated as carrying a `missing_clone` drift, **except** when the user is listed in a new SPOT allowlist `PROVISION_CLONE_EXEMPT_USERS` in `user_config.sh` (defaults to `("Terry.McGuinness")` on this host — the operator who works from the shared main checkout at `${EIB_REPO}` and does not need a scratch clone).

When `missing_clone` is present and not exempted, `remediate_user` **shall** invoke the parent-spec's `clone_mcp_rag_repo <user>` unchanged — the same function that landed Anton.Fernando's clone during T8, which handles operator-SSH-authenticated clone from `${UPSTREAM_REPO_URL}`, R3-safe pre-create of `${repo_dir}` chown'd to `${SUDO_USER}`, and final `chown -R <user>:pwuser ${repo_dir}` handoff.

`check_user_integrity` (parent-spec T6 helper) **shall** also report this drift in its human-readable `--status` output so operators can see missing-clone rows without invoking `--remediate --dry-run` first. This is a cross-spec touch — the parent spec is committed but its T6 helper is co-located in `SETUP/provisioning/00-users.sh` and the two helpers (`check_user_integrity` + `check_user_drifts`) are meant to stay symmetric; extending both together preserves that symmetry.

Exempt users **shall not** be flagged; a missing clone for them is intentional (the operator uses a shared checkout, a submodule of a larger workspace, or an off-scratch working copy).

## Non-goals

- Password reset — not our concern; drift here is filesystem/group only.
- SSH key changes — Anton-style keypair generation is a provisioning-time concern.
- Repo clone / bashrc / `.vscode/mcp.json` — already handled at initial provisioning.
- Home directory contents.
- Bulk `--remediate-all` mode. Repeat `--remediate <user>` N times if you need N users; explicit is safer than implicit.
- Re-running any part of `provision_user()` chain on existing users (that path is deliberately gated by the idempotency check in `create_user`).

## Acceptance criteria

- **AC1** — `sudo ./00-users.sh --dry-run --remediate Terry.McGuinness` prints "no drift detected, no action" and exits 0. `git diff` on the host state shows nothing changed.
- **AC2** — `sudo ./00-users.sh --remediate Terry.McGuinness` (real run) is a clean no-op: reports Terry `[OK]` before and after, issues zero `usermod`/`chown` commands, exits 0.
- **AC3** — `sudo ./00-users.sh --dry-run --remediate Anna.Smoot` prints a plan naming exactly three fixes (usermod -g, chown top-level, usermod -aG kasmvnc-cert). Nothing mutates.
- **AC4** — `sudo ./00-users.sh --remediate Anna.Smoot` (real run) flips the primary group, the scratch top-level owner, and adds `kasmvnc-cert`. Post-status: Anna reports `[OK]` on all six checks. If any scratch children remain owned by Terry, they are listed as `[PRESERVED]` in the report and Anna still reports `[OK]` on the top-level scratch check (children are not part of the T6 gate).
- **AC5** — `sudo ./00-users.sh --remediate NonExistent.User` prints `[ERROR] user NonExistent.User does not exist; --remediate is not for creation`, exits 1, and does not touch the host.
- **AC6** — Running AC4 twice in a row produces identical `[OK]` output on the second run, with zero mutating commands (R8 idempotency).
- **AC7** — Post-remediation of all three legacy users (Anna, Brian, Georgios), `sudo ./00-users.sh --status` reports `[OK]` for all applicable checks (six pre-R10, seven post-R10) for every user in `PROVISION_USERS`. This is the "we're done" state for the drift-remediation follow-up.
- **AC8** — `check_user_drifts Terry.McGuinness` (via direct source-and-invoke) emits **no** `missing_clone` line — Terry is on `PROVISION_CLONE_EXEMPT_USERS`. `check_user_drifts` for a non-exempt user whose `${SCRATCH_ROOT}/<u>/eib-mcp-rag-server/.git` is absent emits exactly one `missing_clone` line. Verified via a synthetic test: temporarily `sudo mv` Anna's clone aside, re-run `check_user_drifts Anna.Smoot`, confirm `missing_clone` in the output, then `sudo mv` the clone back. Zero permanent mutation.
- **AC9** — `sudo ./00-users.sh --dry-run --remediate <synthetic-missing-clone user>` renders a numbered section calling `clone_mcp_rag_repo <user>` (rendering the resolved `${UPSTREAM_REPO_URL}` and target path) with no mutation. The real (non-dry-run) invocation on the same user then produces a fully-owned clone at `${SCRATCH_ROOT}/<u>/eib-mcp-rag-server/.git` and clears the drift.

## Traceability

| Requirement | Acceptance |
|-------------|-----------|
| R1 flag | AC1, AC5 |
| R2 drift-driven | AC1, AC2, AC3 |
| R3 primary group | AC3, AC4 |
| R4 scratch owner | AC3, AC4 |
| R5 supp group | AC3, AC4 |
| R6 dry-run | AC1, AC3 |
| R7 before/after | AC4, AC7 |
| R8 idempotency | AC6 |
| R9 refusal | AC5 |
| R10 missing-clone drift + exempt allowlist | AC8, AC9 |
