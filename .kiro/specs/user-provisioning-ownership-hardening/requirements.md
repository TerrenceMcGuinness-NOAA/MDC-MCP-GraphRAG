# User-Provisioning Ownership & Scoping Hardening — Requirements

**Spec ID**: `user-provisioning-ownership-hardening`
**Trigger**: 2026-07-15 provisioning of `Anton.Fernando` surfaced eight verifiable gaps in `SETUP/provisioning/`. This spec closes the ownership + scoping subset (the specific gaps proven by that run). Anything beyond that subset is deferred and out of scope.
**Sister artifact**: [[EIB-MCP-RAG-Full-State-of-Affairs-Report-2026-07-15]] (wiki) documents the broader instruction-file evaluation context but does not overlap this spec.

## Context — what we verified on 2026-07-15

The `Anton.Fernando` provisioning gap-play produced these ground-truth facts:

1. Existing users (Terry, Anna, Brian, Georgios) all have primary group `pwuser`. `00-users.sh` uses `useradd -m -s /bin/bash "${username}"` at [line 85](../../SETUP/provisioning/00-users.sh#L85) — this creates a **private group** named after the user, not `pwuser`. Group parity is not enforced anywhere.
2. Anton's scratch dir at `/mcp_rag_eib/SCRATCH_SPACE/Anton.Fernando` already held operator-staged content (`global-workflow/`, `README.md`, `.vscode/`) owned by `Terry.McGuinness:pwuser`. `create_scratch_space()` in `00-users.sh` runs a blind `chown -R "${username}:${user_group}" "${workspace_dir}"` — pre-existing content is silently re-owned.
3. Four different ownership-resolution schemes coexist across the 17 provisioning scripts:
   - `00-users.sh` → `get_user_group()` (per target user)
   - `01/05/06/07/08/14` → `USER_OWNERSHIP` (via `get_ownership` → `get_actual_user`)
   - `15-github-copilot-cli.sh` → `"${USER_NAME}:${USER_NAME}"` (assumes group == username — wrong under the `pwuser` convention)
   - `16-lmod.sh` → `"${MCP_USER}:${MCP_GROUP}"` (separate env-var pair)
4. The default password `ChangeMe123!` is hardcoded inline at [00-users.sh L87](../../SETUP/provisioning/00-users.sh#L87). No env override, no config field, no site-secret path.
5. There is no dry-run / pre-flight mode. An operator cannot see "would create user X; would chown paths Y1..Yn; would add to groups G1..Gn" before mutating the host.
6. `create_scratch_space` treats the entire `${SCRATCH_ROOT}/${username}` subtree as provisioning-owned. There is no notion of a **protected pre-staged path** the script must not chown.
7. `add_to_groups()` conditionally adds to `docker` / `kasmvnc-cert` on each run but never verifies membership across all provisioned users. The `--status` mode only compares configured vs. existing user lists.
8. `--status` performs no ownership / group / SSH-key / scratch-dir integrity cross-check. It answers "does the account exist?" and nothing else.

## Requirements (EARS)

### R1 — Primary group SPOT

The system **shall** expose a single configuration field `PROVISION_PRIMARY_GROUP` in `SETUP/provisioning/user_config.sh` whose default is `pwuser` on this host and which is honored by every provisioning script that creates a user or chowns a user-owned path.

### R2 — `useradd` honors the primary-group SPOT

When `00-users.sh` creates a new user, the system **shall** invoke `useradd` with `-g "${PROVISION_PRIMARY_GROUP}"` **iff** the group exists on the host; otherwise the system shall fall back to the current private-group behavior and emit a `log_warning` naming the missing group.

### R3 — Protected pre-staged paths

When `create_scratch_space()` runs against a `${SCRATCH_ROOT}/${username}` that already contains files not owned by the target user, the system **shall**:
- (a) enumerate the pre-existing entries,
- (b) print a summary of what will be re-owned,
- (c) proceed only when `PROVISION_ADOPT_PRESTAGED=yes` is set (default `no`), and
- (d) otherwise skip the `chown -R` on the pre-existing entries while still creating any new provisioning artifacts.

### R4 — Ownership-resolution SPOT

The system **shall** collapse the four ownership-resolution schemes onto one shared helper (`resolve_ownership <username>`) exported from `common.sh` and used by all provisioning scripts (00, 01, 05, 06, 07, 08, 14, 15, 16). `USER_NAME:USER_NAME` and `MCP_USER:MCP_GROUP` composites shall be removed from per-script code; `USER_OWNERSHIP` may remain as a cached env var populated from the shared helper.

### R5 — Default password removed from source

The system **shall** move the initial password out of source. Precedence: (a) `PROVISION_INITIAL_PASSWORD_FILE` env var pointing to a mode-0600 file, else (b) an interactive `read -s` prompt when a TTY is attached, else (c) a randomly generated 16-character password logged only to the operator's stdout (never to the state file or systemd journal). `chage -d 0` behavior is preserved so the user is forced to change on first login.

### R6 — Dry-run / pre-flight mode

The system **shall** accept `--dry-run` on `00-users.sh` and produce a rendered plan listing every intended `useradd`, `chown`, `usermod -aG`, `chpasswd`, `ssh-keygen`, and file copy — with no mutations to the host — including a "protected pre-staged path" section that names every file R3 would skip.

### R7 — Group membership idempotency check

The `--status` mode **shall** additionally report, per configured user, the delta between their current supplementary groups and the required set (`docker`, `kasmvnc-cert` when present) so the operator can `usermod -aG` the drift without running the full script.

### R8 — Integrity cross-check in `--status`

The `--status` mode **shall** report, per configured user: account exists (`id`), primary group matches SPOT, `${SCRATCH_ROOT}/${username}` exists with correct owner:group, `~/.ssh` mode is 0700, `~/.ssh/authorized_keys` mode is 0600. Any mismatch is printed as `[DRIFT]`; a fully-clean user is printed as `[OK]`.

## Non-goals

- Multi-tenant provisioning (Anton is a single-user gap; keep the surface single-tenant here).
- Rewriting `common.sh` beyond adding `resolve_ownership` and the R3 protected-paths helper.
- Migrating the four existing schemes to `resolve_ownership` **in the same commit** — R4 permits a phased migration; the acceptance test only requires that the new helper exists, is exported, and is used by `00-users.sh` + `14-final-ownership.sh` (the two hot-path scripts).
- Central identity (LDAP/AD/SSSD). Out of scope; the `pwuser` primary-group convention on this host is the ground truth for R1.
- Retroactively fixing ownership on already-provisioned users. Handled operationally, not in this spec.

## Acceptance criteria

- **AC1**: `sudo ./00-users.sh --dry-run --user Nonexistent.User` on a clean host prints the full plan and mutates nothing (verified by `getent passwd` + `ls /home` before/after).
- **AC2**: A newly-provisioned user on this host has primary group `pwuser`, matching Terry / Anna / Brian / Georgios.
- **AC3**: Running `sudo ./00-users.sh --user X` when `${SCRATCH_ROOT}/X` contains pre-existing non-X-owned files leaves those files' ownership unchanged (unless `PROVISION_ADOPT_PRESTAGED=yes`).
- **AC4**: `sudo ./00-users.sh --status` reports either `[OK]` for every check per user, or a precise `[DRIFT expected=X actual=Y]` for any mismatch, without mutating the host. For newly-provisioned users the row is `[OK]`; for the pre-hardening users that were provisioned before this spec landed (Anna.Smoot, Brian.Curtis, Georgios.Britzolakis), pre-existing drift on primary group / scratch owner / supplementary groups is expected and its remediation is out of scope here — tracked in the follow-up spec `user-provisioning-drift-remediation`.
- **AC5**: `grep -R 'ChangeMe123' SETUP/provisioning/` returns zero matches.
- **AC6**: `grep -R '"${USER_NAME}:${USER_NAME}"\|"${MCP_USER}:${MCP_GROUP}"' SETUP/provisioning/` returns zero matches (or is explicitly justified per non-goal deferral).
- **AC7**: The four pre-hardening users (Terry.McGuinness, Anna.Smoot, Brian.Curtis, Georgios.Britzolakis) continue to be **functional** — they can still log in, own their home directories, and access `docker`. Any `[DRIFT]` reported by the new `--status` for those users reflects historical state that pre-dates this spec; correcting it is deferred to `user-provisioning-drift-remediation`. This spec does not regress any of them.

## Traceability

| Gap (from Context) | Requirement | Acceptance |
|--------------------|-------------|------------|
| G1 primary-group | R1, R2 | AC2 |
| G2 blind chown | R3 | AC3 |
| G3 four schemes | R4 | AC6 |
| G4 hardcoded password | R5 | AC5 |
| G5 no dry-run | R6 | AC1 |
| G6 no protected paths | R3 | AC3 |
| G7 group idempotency | R7 | AC4 |
| G8 shallow --status | R8 | AC4, AC7 |
