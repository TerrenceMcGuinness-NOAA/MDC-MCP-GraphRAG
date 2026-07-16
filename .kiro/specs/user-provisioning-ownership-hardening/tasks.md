# User-Provisioning Ownership & Scoping Hardening — Tasks

Execution order matters for the acceptance tests. Every task is small (≤ 1 file or one contained cross-file change).

## T1 — SPOT fields in `user_config.sh` (R1, R3, R5)

- Add `PROVISION_PRIMARY_GROUP`, `PROVISION_ADOPT_PRESTAGED`, `PROVISION_INITIAL_PASSWORD_FILE` per design.md §"SPOT additions".
- Preserve existing `PROVISION_USERS`, `SCRATCH_ROOT`, and VNC blocks unchanged.
- **Verify**: `bash -n SETUP/provisioning/user_config.sh` passes; `source SETUP/provisioning/user_config.sh && echo "${PROVISION_PRIMARY_GROUP}"` prints `pwuser`.

## T2 — `common.sh` helpers (R4, R3, R5)

- Add `resolve_ownership <username>`, `list_prestaged_paths <path> <owner>`, `resolve_initial_password <username>`.
- Export them via the existing `export -f` line at the bottom of the file.
- **Verify**: source `common.sh`; `resolve_ownership Terry.McGuinness` prints `Terry.McGuinness:pwuser`; `list_prestaged_paths /mcp_rag_eib/SCRATCH_SPACE/Anton.Fernando Anton.Fernando` prints the three known-good entries (`global-workflow`, `README.md`, `.vscode`).

## T3 — `00-users.sh::create_user()` honors R1/R2/R5

- Replace the current `useradd` + `chpasswd` block per design.md.
- Do **not** remove the `ChangeMe123!` string from `user_config.sh` yet — it stays out of source per R5, and R5 introduces no new SPOT field for it.
- **Verify**: `bash -n SETUP/provisioning/00-users.sh` passes; `grep ChangeMe123 SETUP/provisioning/` returns zero results (AC5).

## T4 — `00-users.sh::create_scratch_space()` honors R3

- Replace the function body per design.md.
- **Verify**: with `PROVISION_ADOPT_PRESTAGED=no` (default) and Anton's pre-existing scratch dir intact, a plan-only run reports 3 `[PRESERVED]` entries and would only chown the top-level dir. (Real execution is deferred to T8.)

## T5 — `--dry-run` support in `00-users.sh` (R6)

- Add flag parsing (mirrors `--user`, `--status`).
- Implement `render_provisioning_plan()` calling out each mutating step per design.md.
- Route `provision_user()` through the dry-run gate.
- **Verify** (AC1): `sudo ./00-users.sh --dry-run --user Test.Ghost` on a host where `Test.Ghost` does not exist prints the plan, exits 0, and `id Test.Ghost` still returns "no such user".

## T6 — `--status` integrity cross-check (R7, R8)

- Extend `print_status()` per design.md.
- **Verify** (AC4): `sudo ./00-users.sh --status` reports `[OK]` for Terry / Anna / Brian / Georgios; `[DRIFT]` clearly for any known-drifting user (test with a temporary `usermod -G "" Test.Ghost` in a scratch container if convenient).

## T7 — Documentation

- Update `SETUP/provisioning/README.md` with:
  - the three new SPOT fields and their precedence,
  - a "Pre-staged path preservation" section explaining R3,
  - a "Dry-run first" one-liner in the top-of-file quick-start,
  - a note that R5 requires the operator to record the initial password (from the file, prompt, or generator output) before the user's first login.
- **Verify**: `grep -c 'PROVISION_PRIMARY_GROUP\|PROVISION_ADOPT_PRESTAGED\|--dry-run' SETUP/provisioning/README.md` ≥ 3.

## T8 — Anton.Fernando end-to-end re-provisioning (AC2, AC3, AC7)

- Operator-gated. Once T1–T7 are staged and reviewed:
  1. `sudo ./00-users.sh --dry-run --user Anton.Fernando` — inspect the plan.
  2. Decide on the pre-staged files (move them out, or set `PROVISION_ADOPT_PRESTAGED=yes`).
  3. `sudo ./00-users.sh --user Anton.Fernando` — execute.
  4. `sudo ./00-users.sh --status` — must report `[OK]` for all five users.
- **Verify**: `id -gn Anton.Fernando` prints `pwuser` (AC2); the three pre-staged entries have their original ownership preserved (AC3, when opt-in is `no`); the four pre-existing users remain `[OK]` (AC7).

## T9 — CHANGELOG entry

- Add an `[Unreleased]` block naming this spec, the eight closed gaps, and the operator-facing behavior changes (`--dry-run`, `--status` upgrade, primary-group SPOT).
- Cross-link to `[[EIB-MCP-RAG-Full-State-of-Affairs-Report-2026-07-15]]` as the discovery record.

## Sequencing

```
T1 ─► T2 ─► T3 ─► T4 ─► T5 ─► T6 ─► T7 ─► (human review) ─► T8 ─► T9
```

Tasks T1–T7 are code + docs only, no host mutation. T8 is the only host-mutating step and is explicitly operator-gated per the git operation policy and the "hard-to-reverse action" rule.
