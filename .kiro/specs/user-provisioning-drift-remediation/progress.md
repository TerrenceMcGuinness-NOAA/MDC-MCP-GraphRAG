# User-Provisioning Drift Remediation — Progress

## Status: **Phase A COMPLETE (T1–T5, T5a–T5c) — awaiting human review before operator-run T6–T12**

- 2026-07-15 — Stub `README.md` written when the parent spec's T6 `--status` upgrade surfaced pre-existing drift on Anna.Smoot, Brian.Curtis, Georgios.Britzolakis.
- 2026-07-15 — Parent spec committed as `dc20d69` (T1–T7) + `30af7fd` (T8 live remediation) on `develop`. Anton.Fernando fully provisioned; Terry + Anton = 6×`[OK]`; the three legacy users still show the three known drifts.
- 2026-07-15 — Full spec authored (`requirements.md`, `design.md`, `tasks.md`, this file).
- 2026-07-15 — **T1** completed by `kiro-cli 2.12.2` (Opus 4.7). `--remediate <user>` arg parsing added (+25/-8). Unstaged.
- 2026-07-15 — **T2** completed by `kiro-cli 2.12.2` (Opus 4.7). `check_user_drifts()` helper added. Unstaged.
- 2026-07-15 — **T3** completed by `kiro-cli 2.12.2` (Opus 4.7). `render_remediation_plan()` added. Unstaged.
- 2026-07-15 — **T4** completed by `kiro-cli 2.12.2` (Opus 4.7). `remediate_user()` + main-flow dispatch added. End-to-end wire-through verified; zero host mutation. **Staged** (Kiro).
- 2026-07-15 — **T5** completed by `kiro-cli 2.12.2` (Opus 4.7). `SETUP/provisioning/README.md` updated (+97/-1). Unstaged.
- 2026-07-15 — **Option C scope expansion authored**: operator observed Terry's scratch had no `eib-mcp-rag-server` clone during T6 dry-run testing ("nothing done but scratch space does not have the develop repo"). Census confirmed 4/5 users had a clone (Anna/Brian/Georgios's owned by Terry — handled by R4 preserve/adopt; Anton's correctly owned; Terry's absent by intentional design). New R10 (missing-clone drift + `PROVISION_CLONE_EXEMPT_USERS` allowlist) added to `requirements.md`; `design.md` extended with SPOT field, `check_user_drifts` extension, `check_user_integrity` cross-spec touch, `remediate_user` branch, `render_remediation_plan` section; `tasks.md` gains T5a/T5b/T5c following the phase-suffix convention. Terry stays exempt; future users automatically caught. **Not yet implemented — awaiting Kiro-CLI T5a.**

**Phase A total surface so far**: 2 files touched under `SETUP/provisioning/` (`00-users.sh` +284/-8, `README.md` +97/-1). Spec artifacts also updated (requirements/design/tasks/progress) but not yet committed. Additive; backward-compatible.

## Task tracker

| Task | Status | Started | Completed | Notes |
|------|--------|---------|-----------|-------|
| T1 `--remediate` arg parsing | **done** | 2026-07-15 | 2026-07-15 | Kiro Opus 4.7; verified; unstaged; 3/3 Verify gates green |
| T2 `check_user_drifts()` helper | **done** | 2026-07-15 | 2026-07-15 | Kiro Opus 4.7; verified; unstaged; correct output across all 5 users |
| T3 `render_remediation_plan()` | **done** | 2026-07-15 | 2026-07-15 | Kiro Opus 4.7; verified via direct invocation; tasks.md verify block corrected to reflect T4 dependency |
| T4 `remediate_user()` + dispatch | **done** | 2026-07-15 | 2026-07-15 | Kiro Opus 4.7; verified end-to-end via `--remediate`; 4/4 Verify gates green; **staged** |
| T5 README update | **done** | 2026-07-15 | 2026-07-15 | Kiro Opus 4.7; verified; unstaged; new H2 section between --dry-run and Script Inventory; version 4.3.0; version-history entry |
| T5a R10 SPOT + drift detection | **done** | 2026-07-15 | 2026-07-15 | Kiro Opus 4.7; verified; unstaged; 5/5 Verify gates green; caught design.md↔tasks.md discrepancy on exempt-row rendering |
| T5b R10 remediate branch + renderer | **done** | 2026-07-15 | 2026-07-15 | Kiro Opus 4.7; verified; unstaged; trap-guarded safekeep-and-restore probe; Anna's clone unchanged post-test |
| T5c R10 README subsection | **done** | 2026-07-15 | 2026-07-15 | Kiro Opus 4.7; verified; unstaged; version 4.3.1; R10 subsection nested inside ## Retroactive drift remediation; grep threshold 11≫3 |
| T6 Terry no-op smoke test | operator-gated | | | Blocked on T1–T5 |
| T7 Refusal on non-existent user | operator-gated | | | Blocked on T1–T5 |
| T8 Remediate Anna.Smoot | operator-gated | | | Blocked on T6, T7 |
| T9 Remediate Brian.Curtis | operator-gated | | | Blocked on T6, T7 |
| T10 Remediate Georgios.Britzolakis | operator-gated | | | Blocked on T6, T7 |
| T11 Idempotency verification | operator-gated | | | Blocked on T8, T9, T10 |
| T12 Full-status `[OK]` gate | operator-gated | | | Blocked on T11 |
| T13 CHANGELOG + commit | pending | | | Blocked on T12 |

## Corrections / gotchas

- 2026-07-15 (T1) — none. Kiro delivered clean additive changes and even realigned the `usage()` column padding to accommodate the longer `--remediate <username>` string. The 8 deletions in the diff are the old shorter-padded usage lines being replaced by wider-padded equivalents — purely cosmetic, substance preserved.
- 2026-07-15 (T2) — none, and two authoring quality points worth recording: (1) Kiro added an explicit `if [[ ${#drifts[@]} -gt 0 ]]; then printf ...` guard around the array expansion — defensive against `set -u` on older bash, preserves the "clean user prints nothing" contract; (2) supp_groups payload emits only truly-missing groups (Anna already in `docker`, so only `kasmvnc-cert` appears — the comma-list format handles single-group and multi-group cases uniformly for T4 to parse).
- 2026-07-15 (T3) — **spec-authoring bug caught by Kiro**: the tasks.md T3 Verify block was written with `sudo -n bash 00-users.sh --dry-run --remediate <user> | grep -c ...` which requires the main-flow dispatch loop — a T4 deliverable, not T3. Kiro correctly fell back to direct-invocation probes (`eval "$(sed -n "/^render_remediation_plan()/,/^}/p" 00-users.sh)"`) to verify T3's contract in isolation, then flagged the mismatch cleanly. tasks.md T3 verify block was rewritten to use the direct-invocation approach; the original wire-through commands will pass automatically once T4 lands. Positive quality point on Kiro's part: caught a real gap in my spec and proceeded correctly instead of falsely claiming pass or falsely failing.
- 2026-07-15 (T4) — none. Kiro delivered the whole payoff task cleanly: `remediate_user()` placed correctly (sibling of `provision_user`), main-flow dispatch placed correctly (sibling of `STATUS_ONLY` early-exit), all six R-numbered requirements honored (R2/R3/R4/R5/R6/R7/R8/R9) with correct branching. End-to-end wire-through confirmed: `--dry-run --remediate Anna.Smoot` renders 3 usermod|chown lines + 8 preserved paths; Terry no-op; NonExistent.User R9 refusal; zero host mutation everywhere. The three T4 sibling pairs (provision/remediate, render_provisioning/render_remediation, check_integrity/check_drifts) form a nice symmetric architecture — good sign the design was sound.
- 2026-07-15 (T5) — none. Kiro placed the new section at a defensible reading-order position (between `## Dry-run mode` and `## Script Inventory` — SPOT → preserve semantics → dry-run → remediate uses all of the above → reference material). Used the same R-numbered subsection convention (`### R9`, `### R8`, `### R3`) established in the parent-spec T7 README. Version-history entry references the spec by name so future greps land at the changelog entry.
- 2026-07-15 (T5a) — **spec-doc discrepancy caught by Kiro**: design.md said `Renders [OK] when exempt or when the clone exists`; tasks.md T5a Verify said `row omitted for Terry`. Kiro correctly implemented tasks.md's contract (omit for exempt) since it was the explicit Verify gate, symmetric with `check_user_drifts` behavior, and consistent with the existing T6 pattern that omits the `kasmvnc-cert` check when that group is absent on the host. Kiro flagged the discrepancy in its report rather than silently choosing one. design.md was updated post-verification to match the implementation (this decision documented here for the audit trail). Positive quality point: Kiro didn't rewrite arbitrarily nor silently pick — it named the tension and asked.
- 2026-07-15 (T5b) — none, and two quality touches worth propagating: (1) **trap-guarded restore** (`trap restore_clone EXIT`) in the safekeep-and-restore synthetic missing-clone probe — Anna's clone is put back even if the dry-run errors mid-execution; the pattern is worth reusing for any host-state-manipulating test. (2) **`\${SUDO_USER}` deliberately escaped** in the R10 renderer output — the literal placeholder shows in the plan because the invoking-operator name is only known at real-run time; static-resolvable vars (`workspace_dir`, `UPSTREAM_REPO_URL`, `group`) still expand. Honest rendering that doesn't over-promise.
- 2026-07-15 (T5c) — none. Clean single-file README extension: version-header bump, nested subsection insertion inside the existing `## Retroactive drift remediation` H2 (not a new H2), matching version-history entry appended above the T5 entry. Kept the operator-facing story readable by keeping R10 as a subsection of the flag it participates in rather than promoting it to a sibling H2.

## Human-gated boundaries

- T1–T5 are code + docs, no host mutation. Kiro-CLI can execute them one at a time.
- T6–T12 are operator-run (real `usermod` / `chown` on existing accounts). Kiro-CLI **should not** execute these; the operator drives them and reports outcome back for the tracker + corrections log.
- T13 (commit) requires explicit operator authorization per steering rule 08.

## Preserve-vs-adopt decision (per user, at T8/T9/T10)

The three affected users have scratch dirs whose children are all owned by `Terry.McGuinness:pwuser` (per parent-spec T6 output). Before each of T8/T9/T10, the operator decides one of:

- **Preserve (default)** — run without `PROVISION_ADOPT_PRESTAGED=yes`. Only the scratch top-level flips; children remain Terry-owned. Anna/Brian/Georgios `--status` will still show `[OK]` on all six checks (children are not part of the T6 gate); a `[PRESERVED]` note is emitted for the record.
- **Adopt** — prepend `PROVISION_ADOPT_PRESTAGED=yes` on the invocation. Children get `chown -R` to the target user.

This is deliberately per-user, not spec-wide.

## Known follow-ups (out of scope for this spec)

- **`--remediate-home`** — sweep `$HOME` files under the old primary group and chgrp them to `pwuser`. Not urgent; deferred until someone reports actual file-access breakage.
- **`--remediate-all`** — bulk mode over `PROVISION_USERS`. Deferred pending demand; explicit per-user invocation is safer.
- The AWS/AgentCore serving path has no user-provisioning drift equivalent; this spec is COTS-host-only.
