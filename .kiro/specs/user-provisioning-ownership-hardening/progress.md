# User-Provisioning Ownership & Scoping Hardening — Progress

## Status: **Phase A complete (T1–T7) — awaiting human review before T8**

- 2026-07-15 — Spec created after the `Anton.Fernando` provisioning gap-play.
- 2026-07-15 — **T1** completed by `kiro-cli 2.12.2` (Opus 4.7). Three SPOT fields → `user_config.sh`. Verified. Staged.
- 2026-07-15 — **T2** completed by `kiro-cli 2.12.2` (Opus 4.7). Three helpers → `common.sh` (117 lines). Verified. Unstaged.
- 2026-07-15 — **T3** completed by `kiro-cli 2.12.2` (Opus 4.7). `create_user()` rewritten (+12/-2). AC5 satisfied. Unstaged.
- 2026-07-15 — **T4** completed by `kiro-cli 2.12.2` (Opus 4.7). `create_scratch_space()` rewritten. Dry-trace against Anton → correct preserve branch, all 3 paths detected. Unstaged.
- 2026-07-15 — **T5** completed by `kiro-cli 2.12.2` (Opus 4.7). `--dry-run` flag + 9-section `render_provisioning_plan()` added to `00-users.sh` (cumulative +195/-13). AC1 satisfied end-to-end. Unstaged.
- 2026-07-15 — **T6** completed by `kiro-cli 2.12.2` (Opus 4.7). `print_status()` upgraded to 6-check integrity block (cumulative +338/-13). Correct check; surfaced pre-existing drift on 3 users → follow-up spec stubbed at `.kiro/specs/user-provisioning-drift-remediation/`. AC4/AC7 reworded to reflect steady state. Unstaged.
- 2026-07-15 — **T7** completed by `kiro-cli 2.12.2` (Opus 4.7). `SETUP/provisioning/README.md` updated (+165/-2): version bumped 4.1.0→4.2.0, all four T7 items landed (SPOT fields with precedence, dry-run quick-start, pre-staged preservation with opt-in, R5 initial-password note). Verify grep threshold met (29≫3). Unstaged.

**Phase A total surface**: 4 files touched under `SETUP/provisioning/` (+636/-15), 2 spec directories added (+7 files). All changes backward-compatible for existing users (they remain functional; the 3 drift rows are historical state to be closed by the follow-up spec).

## Known follow-ups (out of scope for this spec)

- **`user-provisioning-drift-remediation`** — new stub spec at `.kiro/specs/user-provisioning-drift-remediation/README.md`. Closes the pre-existing drift observed on Anna.Smoot, Brian.Curtis, and Georgios.Britzolakis (primary group, scratch owner, `kasmvnc-cert` membership). Depends on this spec landing; not blocking T8.

## Task tracker

| Task | Status | Started | Completed | Notes |
|------|--------|---------|-----------|-------|
| T1 SPOT fields | **done** | 2026-07-15 | 2026-07-15 | Kiro Opus 4.7; verified; staged with Anton PROVISION_USERS line |
| T2 common.sh helpers | **done** | 2026-07-15 | 2026-07-15 | Kiro Opus 4.7; verified; unstaged |
| T3 create_user | **done** | 2026-07-15 | 2026-07-15 | Kiro Opus 4.7; verified; unstaged; AC5 satisfied |
| T4 create_scratch_space | **done** | 2026-07-15 | 2026-07-15 | Kiro Opus 4.7; verified; unstaged; dry-trace correct |
| T5 --dry-run | **done** | 2026-07-15 | 2026-07-15 | Kiro Opus 4.7; verified; unstaged; AC1 satisfied end-to-end |
| T6 --status upgrade | **done** | 2026-07-15 | 2026-07-15 | Kiro Opus 4.7; verified; unstaged; check correct; surfaced pre-existing drift on 3 users → follow-up spec stubbed |
| T7 README | **done** | 2026-07-15 | 2026-07-15 | Kiro Opus 4.7; verified; unstaged; +165/-2 lines; verify grep 29≫3 |
| T8 Anton re-provisioning | operator-gated | | | Blocked on T1–T7 review |
| T9 CHANGELOG | pending | | | |

## Corrections / gotchas (populated as the loop runs)

- 2026-07-15 (T1) — none. Kiro respected the "append only" instruction and produced idiomatic bash matching repo conventions on first pass. Only annotation: staging bundled the pre-existing Anton PROVISION_USERS line with T1's append (both single-file, causally related — kept bundled by operator choice).
- 2026-07-15 (T2) — **improvement caught by Kiro, not in the original design**: `list_prestaged_paths` resolves `<owner>` to a numeric UID via `id -u` *before* invoking `find -not -uid`. A naïve `find -not -user "${owner}"` fails with `find: '<name>' is not the name of a known user` and produces silent empty output when the target user does not yet exist on the host — which is exactly the first-time-provisioning case (Anton pre-creation). Kiro's UID-first approach with a "user doesn't exist ⇒ owns nothing" fallback preserves the semantically correct pre-staged-path detection. Design.md was implicit on this; the implementation is now the ground truth.
- 2026-07-15 (T3) — minor UX improvement: `log_info "Creating user account: ${username}"` placed above the group-existence check (design.md pseudocode had it after). Message order now flows correctly; semantically equivalent.
- 2026-07-15 (T4) — inline comment addition explaining why the preserve branch omits `-R` on the `chown` (top-level dir must be user-writable so post-provision writes work, while pre-staged children retain their original ownership). Aids future readers; no behavior change.
- 2026-07-15 (T5) — three authoring choices worth recording as the reference implementation of the dry-run pattern: (1) password rendered as `<initial-password-from-R5-precedence>` placeholder — no leak, no lie, no premature call to the T2 helper; (2) non-command steps (append heredoc to `.bashrc`, `sed -i` on `.bash_profile`) rendered in `(prose)` instead of fake one-liners; (3) `update_bare_repo` also gated behind DRY_RUN with a `[DRY-RUN] Would refresh ... (skipped)` message, which the design.md did not explicitly require but is the right call for whole-run mutation-safety. AC1 satisfied on first pass.
- 2026-07-15 (T6) — **discovery, not a correction**: `--status` upgrade revealed that Anna.Smoot, Brian.Curtis, and Georgios.Britzolakis carry three pre-existing drifts each (private primary group instead of `pwuser`; scratch dirs owned by `Terry.McGuinness:pwuser`; not in `kasmvnc-cert`). This is exactly the class of drift R1-R3 exist to prevent going forward, but it is not remediable via `create_user()` (which short-circuits on existing users) or `create_scratch_space()` alone (top-level chown fixes the outer dir, not the primary group or supplementary group memberships). Scope kept: T8 realizes Anton with the hardened path; historical drift moves to the new stub spec `user-provisioning-drift-remediation`. Requirements AC4 and AC7 were rewritten to describe the post-hardening steady state rather than the fictional clean pre-state. No T6 code changes required.
- 2026-07-15 (T7) — **Kiro reporting anomaly** (correctness OK, self-report wrong): Kiro's summary claimed "no file changes were made because the documentation was already in place — likely landed in a prior T7 session." Git diff proves otherwise: 165 insertions, 2 deletions in this session's run. All four T7 requirements were substantively added (SPOT fields, dry-run quick-start, pre-staged preservation, R5 note) plus a v4.1.0→4.2.0 version bump. Class of failure: agentic-mode confabulation about own actions during the self-verify step. Our independent `git diff` check caught it. Worth watching for in future Kiro-CLI runs; not a correctness gate failure since verify caught the truth.

## Human-gated boundaries

- T8 is the only host-mutating task and requires explicit operator authorization.
- Before T8: operator must decide the fate of the three pre-staged entries under `/mcp_rag_eib/SCRATCH_SPACE/Anton.Fernando` (`global-workflow/`, `README.md`, `.vscode/`).
- No git commit / push runs autonomously (per `.kiro/steering/08-git-operation-policy.md`).
