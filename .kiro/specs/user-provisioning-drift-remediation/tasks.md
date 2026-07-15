# User-Provisioning Drift Remediation — Tasks

Every task is small (≤ 1 file, ≤ 1 function) and has an explicit `Verify:` gate. One Kiro-CLI invocation per task; stop after Verify and report. Follows the parent-spec cadence.

## T1 — `--remediate <user>` arg parsing (R1)

- Add `REMEDIATE_USERS=()` next to `TARGET_USERS=()`.
- Add the `--remediate)` branch in the arg-parse case block per design.md.
- Add the mutual-exclusion guard immediately after arg parsing.
- Extend `usage()` with the new flag and one-line description.
- **Verify**:
  - `bash -n SETUP/provisioning/00-users.sh` → exit 0.
  - `sudo -n bash SETUP/provisioning/00-users.sh --user X --remediate Y 2>&1 | grep 'mutually exclusive'` → non-empty.
  - `sudo -n bash SETUP/provisioning/00-users.sh --remediate` (no arg) → error, exit 2.

## T2 — `check_user_drifts()` helper (R2)

- Add the helper next to `check_user_integrity` per design.md.
- **Verify** (no sudo needed):
  - `bash -c 'source SETUP/provisioning/user_config.sh; source SETUP/provisioning/common.sh 2>/dev/null; source <(sed -n "/^check_user_drifts()/,/^}/p" SETUP/provisioning/00-users.sh); check_user_drifts Terry.McGuinness'` → prints nothing (Terry is clean).
  - Same command with `Anna.Smoot` → prints three lines starting with `primary_group `, `scratch_owner `, `supp_groups `.

## T3 — `render_remediation_plan()` (R6)

- Add the renderer per design.md, next to `render_provisioning_plan()`.
- **Verify** (direct invocation — `sudo -n bash 00-users.sh --dry-run --remediate <user>` will *not* work yet because the main-flow dispatch is T4's job; those wire-through verify commands become valid once T4 lands):
  - `bash -c 'source SETUP/provisioning/user_config.sh; source SETUP/provisioning/common.sh 2>/dev/null; eval "$(sed -n "/^render_remediation_plan()/,/^}/p" SETUP/provisioning/00-users.sh)"; drifts=$(printf "primary_group Anna.Smoot\nscratch_owner Terry.McGuinness:pwuser\nsupp_groups kasmvnc-cert"); render_remediation_plan Anna.Smoot "$drifts"' | grep -c 'usermod\|chown'` → **3** (one per drift).
  - Same invocation with `render_remediation_plan Terry.McGuinness ""` → **0** (empty drift set renders no commands).
  - Post-run: `id -gn Anton.Fernando` still returns `pwuser`, `stat -c '%U' /mcp_rag_eib/SCRATCH_SPACE/Anna.Smoot` still returns `Terry.McGuinness` — zero mutation confirmed.

## T4 — `remediate_user()` (R2, R3, R4, R5, R7, R8, R9)

- Add the function per design.md, immediately after `provision_user()`.
- Add the main-flow dispatch block that iterates `REMEDIATE_USERS` and calls `remediate_user`.
- **Verify (dry-run only — no host mutation yet)**:
  - `sudo -n bash SETUP/provisioning/00-users.sh --dry-run --remediate NonExistent.User 2>&1 | grep -c 'does not exist'` → 1 (R9 refusal message rendered even in dry-run since it's a pre-flight check).
  - `sudo -n bash SETUP/provisioning/00-users.sh --dry-run --remediate Terry.McGuinness | grep -c 'No drift detected\|no drift'` → ≥ 1.
  - `sudo -n bash SETUP/provisioning/00-users.sh --dry-run --remediate Anna.Smoot` → renders the 3-fix plan; exit 0.

## T5 — README update (documentation)

- Amend `SETUP/provisioning/README.md` with a new subsection under Quick Start covering `--remediate`, including:
  - Purpose (retroactive drift fix on existing users; not for creation).
  - The R9 refusal case.
  - The R8 idempotency guarantee.
  - The R3 preserve/adopt behavior on scratch children.
  - A "run --dry-run first" reminder.
- Version bump `SETUP/provisioning/README.md` header 4.2.0 → 4.3.0.
- **Verify**: `grep -c '\-\-remediate' SETUP/provisioning/README.md` → ≥ 3.

## T5a — R10 SPOT field + drift detection (Option C addendum)

- Add `PROVISION_CLONE_EXEMPT_USERS=("Terry.McGuinness")` to `SETUP/provisioning/user_config.sh` under a clearly-commented R10 header (see design.md § "New SPOT field").
- Extend `check_user_drifts()` (this spec's helper, added in T2) with the R10 branch: skip when the target user is in `PROVISION_CLONE_EXEMPT_USERS`; otherwise emit `missing_clone` when `${SCRATCH_ROOT}/<user>/eib-mcp-rag-server/.git` is absent.
- Extend `check_user_integrity()` (parent-spec T6 helper — cross-spec touch, acknowledged in design.md) with a matching human-readable row that respects the same exempt allowlist.
- **Verify** (all direct-invocation; no host mutation):
  - `bash -c 'source SETUP/provisioning/user_config.sh; source SETUP/provisioning/common.sh 2>/dev/null; eval "$(sed -n "/^check_user_drifts()/,/^}/p" SETUP/provisioning/00-users.sh)"; check_user_drifts Terry.McGuinness'` → prints nothing (Terry is exempt).
  - Same probe against `Anna.Smoot` → does **not** emit `missing_clone` (Anna has an existing clone, ownership-drifted but present).
  - Synthetic missing-clone probe: `sudo -n mv /mcp_rag_eib/SCRATCH_SPACE/Anna.Smoot/eib-mcp-rag-server /tmp/anna-clone-safekeep && bash -c '<same source-and-invoke>' check_user_drifts Anna.Smoot; sudo -n mv /tmp/anna-clone-safekeep /mcp_rag_eib/SCRATCH_SPACE/Anna.Smoot/eib-mcp-rag-server` → the middle invocation emits `missing_clone`; the final `mv` restores state. Verify Anna's clone is back where it was via `ls /mcp_rag_eib/SCRATCH_SPACE/Anna.Smoot/eib-mcp-rag-server/.git` (present).
  - `--status` run reports a seventh check row for each non-exempt user (`[OK]` for Anton, Anna/Brian/Georgios; row omitted for Terry).

## T5b — R10 remediation branch + renderer section

- Extend `render_remediation_plan()` with the `missing_clone` numbered section per design.md § "render_remediation_plan new section" — must print the resolved `install -d`, `sudo -u ${SUDO_USER} git clone`, and `chown -R` triplet.
- Extend `remediate_user()` with the R10 branch per design.md § "remediate_user new branch (R10 apply)" — calls the parent-spec's `clone_mcp_rag_repo <user>` unchanged, positioned between the R5 supp-groups branch and the R7 post-remediation status re-check.
- **Verify** (dry-run only; no clone actually pulled):
  - Synthetic case (same safekeep-and-restore pattern as T5a): `sudo -n mv .../Anna.Smoot/eib-mcp-rag-server /tmp/anna-clone-safekeep && sudo -n bash SETUP/provisioning/00-users.sh --dry-run --remediate Anna.Smoot | grep -cE '(install -d|git clone|clone_mcp_rag_repo)' && sudo -n mv /tmp/anna-clone-safekeep .../Anna.Smoot/eib-mcp-rag-server` → grep count ≥ 1 during the dry-run; final `mv` restores state.
  - Post-run integrity: Anna's clone is back at `.git`, no `--remediate` real run fired, no host mutation beyond the temporary rename.

## T5c — README R10 subsection

- Extend the `## Retroactive drift remediation (--remediate)` section in `SETUP/provisioning/README.md` (added in T5) with a new `### R10 missing-clone drift and the exempt allowlist` subsection covering:
  - Purpose (missing scratch clone is drift by default).
  - `PROVISION_CLONE_EXEMPT_USERS` allowlist behavior and how to expand it.
  - The clone runs as `${SUDO_USER}` reusing the parent-spec's `clone_mcp_rag_repo`.
- Version bump `SETUP/provisioning/README.md` header 4.3.0 → 4.3.1.
- **Verify**: `grep -c 'PROVISION_CLONE_EXEMPT_USERS\|missing_clone\|R10' SETUP/provisioning/README.md` → ≥ 3.

## T6 — Clean-user no-op smoke test (AC1, AC2)

**Operator-run** (not Kiro; requires sudo credential cache warm).

```bash
# Dry-run first
sudo -n bash SETUP/provisioning/00-users.sh --dry-run --remediate Terry.McGuinness
# Real run — should be identical (no-op)
sudo -n bash SETUP/provisioning/00-users.sh --remediate Terry.McGuinness
# Confirm nothing changed
sudo -n bash SETUP/provisioning/00-users.sh --status 2>&1 | sed -n '/Terry.McGuinness/,/^User: /p' | head -8
```

- **Verify**:
  - Both dry-run and real run output "No drift detected for Terry.McGuinness; nothing to remediate".
  - Real run issued zero `usermod`/`chown` commands (grep the output).
  - `--status` for Terry unchanged: 6× `[OK]`.
  - `sudo grep 'primary group' /etc/subgid` (or equivalent) unchanged for Terry.

## T7 — Refusal on non-existent user (AC5)

Operator-run. Single command:

```bash
sudo -n bash SETUP/provisioning/00-users.sh --remediate Ghost.User; echo "exit=$?"
```

- **Verify**:
  - Stderr contains `does not exist; --remediate is not for creation`.
  - `exit=1`.
  - `id Ghost.User` → still "no such user".

## T8 — Real remediation of Anna.Smoot (AC3, AC4)

Operator-run. Do the dry-run first; inspect the plan; then execute.

```bash
sudo -n bash SETUP/provisioning/00-users.sh --dry-run --remediate Anna.Smoot   # inspect
sudo -n bash SETUP/provisioning/00-users.sh --remediate Anna.Smoot             # apply
sudo -n bash SETUP/provisioning/00-users.sh --status 2>&1 | sed -n '/Anna.Smoot/,/^User: /p' | head -8
```

- **Decision point before real run**: are Anna's scratch children owned by Terry (which they are, per T6 output)? Options:
  - Default: preserve them → Anna's `--status` will still show scratch `[OK]` at top level; children remain Terry-owned (acceptable per R4).
  - Adopt: prepend `PROVISION_ADOPT_PRESTAGED=yes ` to the real-run command; children get chown'd to Anna.
- **Verify**:
  - Real-run output shows exactly three fixes applied (`usermod -g pwuser`, `chown ... /Anna.Smoot`, `usermod -aG kasmvnc-cert`).
  - Post-`--status`: Anna reports 6× `[OK]` (AC4).
  - Anna's account still functional: `sudo -u Anna.Smoot -H bash -c 'echo hello'` works and prints `hello`.

## T9 — Real remediation of Brian.Curtis (AC3, AC4)

Same shape as T8, for Brian. Operator makes the same preserve/adopt decision independently.

## T10 — Real remediation of Georgios.Britzolakis (AC3, AC4)

Same shape as T8, for Georgios.

## T11 — Idempotency verification (AC6)

Operator-run. Immediately after T10 completes:

```bash
sudo -n bash SETUP/provisioning/00-users.sh --remediate Anna.Smoot --remediate Brian.Curtis --remediate Georgios.Britzolakis
```

- **Verify**:
  - Output for each user reads "No drift detected; nothing to remediate".
  - Zero `usermod`/`chown` commands issued (grep output).
  - Exit 0.

## T12 — Full-status verification (AC7)

Operator-run:

```bash
sudo -n bash SETUP/provisioning/00-users.sh --status
```

- **Verify**: every user in `PROVISION_USERS` (Terry, Anna, Brian, Georgios, Anton) reports six `[OK]` rows. Zero `[DRIFT]` lines anywhere in the output. This is the "we're done" gate.

## T13 — CHANGELOG entry + commit

- Add `[Unreleased]` block to `CHANGELOG.md` naming this spec, the `--remediate` flag, and the three users successfully remediated (Anna / Brian / Georgios).
- Update `progress.md` (this spec's tracker) to mark all tasks done and drop the corrections log.
- Stage exactly:
  - `SETUP/provisioning/00-users.sh`
  - `SETUP/provisioning/README.md`
  - `.kiro/specs/user-provisioning-drift-remediation/progress.md`
  - `CHANGELOG.md`
- **Verify**: `git diff --cached --stat` shows only these four files. Commit with a message that references the parent-spec commit chain (`dc20d69` + `30af7fd`) and this spec's Kiro path.

## Sequencing

```
T1 ─► T2 ─► T3 ─► T4 ─► T5 ─► T5a ─► T5b ─► T5c ─► (human review of dry-runs)
                                                          │
                                                          ▼
                                                   T6 (Terry no-op)
                                                          │
                                                          ▼
                                                   T7 (refusal test)
                                                          │
                                                          ▼
              ┌───────────────────────────────────────────┼───────────────────────────┐
              ▼                                           ▼                           ▼
           T8 (Anna)                                  T9 (Brian)              T10 (Georgios)
              │                                           │                           │
              └───────────────┬───────────────────────────┴───────────────────────────┘
                              ▼
                          T11 (idempotency)
                              │
                              ▼
                          T12 (full [OK] gate)
                              │
                              ▼
                          T13 (CHANGELOG + commit)
```

T1–T5c are code + docs only, no host mutation. T6–T12 are operator-gated. T13 is the closeout commit.

**Option C additions (T5a–T5c)** are inserted between T5 and T6 following the phase-suffix convention used elsewhere in the repo (e.g., phase63a/phase63b). They land the R10 missing-clone drift detection + remediation additively; the existing T6–T13 flow does not change shape and automatically picks up the new seventh integrity row where applicable.
