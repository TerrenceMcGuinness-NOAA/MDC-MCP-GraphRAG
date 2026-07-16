# User-Provisioning Drift Remediation — Full Spec

**Spec ID**: `user-provisioning-drift-remediation`
**Status**: **spec-authored, implementation pending** (Kiro-CLI ready)
**Discovered**: 2026-07-15 by the T6 `--status` upgrade in `user-provisioning-ownership-hardening`
**Parent spec**: [`.kiro/specs/user-provisioning-ownership-hardening/`](../user-provisioning-ownership-hardening/)  — committed on `develop` as `dc20d69` (T1–T7) + `30af7fd` (T8 live remediation)

## Spec artifacts

- [`requirements.md`](requirements.md) — 9 EARS requirements + 7 acceptance criteria + traceability matrix
- [`design.md`](design.md) — additive changes to `SETUP/provisioning/00-users.sh` only; no new SPOT fields; new functions `remediate_user()`, `check_user_drifts()`, `render_remediation_plan()`
- [`tasks.md`](tasks.md) — 13 sequenced tasks (T1–T5 code + docs, T6–T12 operator-gated, T13 closeout)
- [`progress.md`](progress.md) — task tracker + corrections log + human-gated boundaries + preserve/adopt decision points
- [`.config.kiro`](.config.kiro) — spec metadata

## Problem

The T6 integrity check surfaced pre-existing drift on three of the four pre-hardening user accounts:

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

Ground-truth `id` and `stat` confirms the drift (see the parent spec's `progress.md`).

The parent spec's `00-users.sh` cannot remediate this state because:
1. `create_user()` short-circuits on `id ${user}` returning 0 — so `useradd -g pwuser` never re-runs for existing users.
2. `create_scratch_space()`'s R3 preserve branch would treat every child under the mis-owned scratch dir as "operator-pre-staged" and skip the `chown -R`, leaving Terry's ownership intact on children.
3. `add_to_groups()` is idempotent for present group memberships but has no way to backfill missing ones — the current run would silently no-op if it can't detect that `kasmvnc-cert` is missing.

Remediation therefore needs its own, differently-shaped code path.

## Scope

Fix the drift on the three affected users without breaking their in-flight work. Explicitly:

1. `usermod -g pwuser <user>` — flip the primary group. Warn if `pwuser` GID is not on the host.
2. `chown -R <user>:pwuser /mcp_rag_eib/SCRATCH_SPACE/<user>` — reclaim ownership. Requires operator confirmation because it touches every file in the tree; a `--dry-run` mode must show which paths will change.
3. `usermod -aG kasmvnc-cert <user>` — backfill the missing supplementary group. No-op if the user is already in the group or the group doesn't exist.
4. Report post-remediation `--status` for each user; success is `[OK]` on all six checks.

## Non-goals

- Not a full re-provisioning. Passwords, SSH keys, bashrc templates, and repo clones are unchanged.
- Not adding new SPOT fields. Uses `PROVISION_PRIMARY_GROUP` from the parent spec's `user_config.sh`.
- Not implementing a general "reprovision existing user" pathway. This is a one-shot remediation for the three users named above.

## Suggested implementation shape

- New flag `--remediate <username>` (repeatable) or `--remediate-all` on `00-users.sh`.
- Reuses `resolve_ownership` + `list_prestaged_paths` from `common.sh` (already in place after the parent spec lands).
- Dry-run integration follows the parent spec's `render_provisioning_plan()` pattern: `--dry-run --remediate <user>` prints a plan and mutates nothing.

## Acceptance

After execution:
- `sudo ./00-users.sh --status` reports `[OK]` for all six checks on Anna.Smoot, Brian.Curtis, Georgios.Britzolakis.
- Terry.McGuinness's `--status` output is unchanged (still `[OK]`).
- Anton.Fernando (assumed already provisioned via the parent spec's T8 by then) remains `[OK]`.
- The three users can still log in, `docker` still works, KasmVNC displays work (validates the `usermod -g pwuser` was safe).

## Deferral rationale

Not folded into the parent spec because:
- Parent spec's stated goal is "harden the provisioning system + realize Anton." Retroactive fixes to Terry-era accounts are a separate operation semantically.
- The remediation code path (in-place `usermod`/`chown -R` on live user accounts) has a different risk profile than the "create a new user" path — it deserves its own dry-run + review gate.
- The three affected users are all currently functional; the drift is hygiene, not breakage.

## Full spec authoring deferred

*(historical — the four canonical files above supersede this section; see [`requirements.md`](requirements.md), [`design.md`](design.md), [`tasks.md`](tasks.md), [`progress.md`](progress.md))*
