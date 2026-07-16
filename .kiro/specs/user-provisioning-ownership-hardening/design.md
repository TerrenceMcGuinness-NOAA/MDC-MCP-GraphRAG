# User-Provisioning Ownership & Scoping Hardening — Design

## Overview

Minimal, additive changes to `SETUP/provisioning/`. No new scripts; existing scripts gain flags and honor a new SPOT. All changes are backward-compatible for the four already-provisioned users (AC7).

## Data-flow (dry-run mode)

```
provision.sh / 00-users.sh --user <U> --dry-run
        │
        ▼
render_provisioning_plan(U)  ──►  stdout only
   ├─ useradd -g <PROVISION_PRIMARY_GROUP> -m -s /bin/bash <U>
   ├─ chown -R <U>:<group>  <SCRATCH>/<U>   (excluding <protected_paths>)
   ├─ usermod -aG docker,kasmvnc-cert <U>
   ├─ ssh-keygen  ~<U>/.ssh/id_rsa
   ├─ copy templates: bashrc, bash_profile, code.sh
   └─ write .vscode/mcp.json
```

No mutations. Exit 0.

## SPOT additions to `user_config.sh`

```bash
# Primary group for provisioned users on this host.
# Rationale: matches the pre-existing `pwuser` convention shared by all
# operator accounts; overrideable per site.
PROVISION_PRIMARY_GROUP="pwuser"

# When "yes", 00-users.sh will chown pre-existing content under
# ${SCRATCH_ROOT}/${username} to the target user. Default "no" preserves
# operator-staged files (see R3).
PROVISION_ADOPT_PRESTAGED="${PROVISION_ADOPT_PRESTAGED:-no}"

# Path to a mode-0600 file containing the initial password for new users.
# If unset, 00-users.sh falls back to an interactive prompt or a generated
# password (never both). See R5.
PROVISION_INITIAL_PASSWORD_FILE="${PROVISION_INITIAL_PASSWORD_FILE:-}"
```

## `common.sh` additions

### `resolve_ownership <username>` → prints `user:group`

Wraps the existing `get_ownership` but resolves the group as:
1. `${PROVISION_PRIMARY_GROUP}` if the group exists on the host, else
2. `get_user_group "${username}"` (current fallback).

Deprecates in-script use of `"${USER_NAME}:${USER_NAME}"` and `"${MCP_USER}:${MCP_GROUP}"`. Existing `USER_OWNERSHIP` env var is set from `resolve_ownership "$(get_actual_user)"`; no downstream script changes required for R4's minimum bar.

### `list_prestaged_paths <path> <owner>` → prints one path per line

Enumerates entries under `<path>` **not** owned by `<owner>`. Consumed by `create_scratch_space` (R3) and `render_provisioning_plan` (R6).

### `resolve_initial_password <username>` → prints the password to stdout

Precedence per R5. Zero side-effects other than emitting log lines to stderr; never writes the value to disk except through the caller's `chpasswd` pipe.

## `00-users.sh` changes

### `create_user()` — R1, R2, R5

```bash
create_user() {
  local username="$1"
  local group="${PROVISION_PRIMARY_GROUP}"
  local useradd_args=(-m -s /bin/bash)

  if getent group "${group}" > /dev/null 2>&1; then
    useradd_args+=(-g "${group}")
  else
    log_warning "Primary group '${group}' missing — falling back to private group for ${username}"
  fi

  if id "${username}" &>/dev/null; then
    log_warning "User ${username} already exists; skipping creation"
    return 0
  fi

  useradd "${useradd_args[@]}" "${username}"

  local password
  password="$(resolve_initial_password "${username}")"
  echo "${username}:${password}" | chpasswd
  chage -d 0 "${username}"
  log_success "User ${username} created"
}
```

### `create_scratch_space()` — R3

```bash
create_scratch_space() {
  local username="$1"
  local workspace_dir="${SCRATCH_ROOT}/${username}"
  local owner_group
  owner_group="$(resolve_ownership "${username}")"

  mkdir -p "${SCRATCH_ROOT}" "${workspace_dir}"

  mapfile -t prestaged < <(list_prestaged_paths "${workspace_dir}" "${username}")

  if [[ ${#prestaged[@]} -eq 0 ]]; then
    chown -R "${owner_group}" "${workspace_dir}"
  elif [[ "${PROVISION_ADOPT_PRESTAGED}" == "yes" ]]; then
    log_warning "Adopting ${#prestaged[@]} pre-staged path(s) into ${username}"
    chown -R "${owner_group}" "${workspace_dir}"
  else
    log_warning "Preserving ${#prestaged[@]} pre-staged path(s); set PROVISION_ADOPT_PRESTAGED=yes to adopt:"
    printf '  [PRESERVED] %s\n' "${prestaged[@]}"
    # chown only the workspace_dir itself (not -R) so the top-level entry is user-writable
    chown "${owner_group}" "${workspace_dir}"
  fi

  chmod 755 "${workspace_dir}"
}
```

### `--dry-run` flag — R6

New top-level flag. When set, `provision_user()` becomes:

```bash
provision_user() {
  local username="$1"
  if [[ "${DRY_RUN}" == true ]]; then
    render_provisioning_plan "${username}"
    return 0
  fi
  # ...existing sequence...
}
```

`render_provisioning_plan` prints the exact commands (with rendered variable substitution) that would run, plus the pre-staged path preservation section from R3.

### `--status` upgrade — R7, R8

`print_status()` gains a per-user integrity block:

```
User: Anton.Fernando
  account: [OK]
  primary group: pwuser [OK]
  scratch: /mcp_rag_eib/SCRATCH_SPACE/Anton.Fernando [OK]
  ~/.ssh mode: 0700 [OK]
  ~/.ssh/authorized_keys mode: 0600 [OK]
  supplementary groups: docker, kasmvnc-cert [OK]
```

Drift emits `[DRIFT expected=X actual=Y]`. No mutations.

## Deliberately unchanged

- `01-directories.sh` through `16-lmod.sh` — R4's minimum bar covers only `00-users.sh` + `14-final-ownership.sh`. The `USER_OWNERSHIP` env var those scripts consume will now be populated by `resolve_ownership`, so they inherit the fix without any per-file edit.
- `bashrc_template`, `bash_profile_template`, `code.sh` — templates are unchanged; only the copy step is dry-run-aware.
- `provision.sh` orchestrator — receives `--dry-run` pass-through only.

## Risks

- **R-risk-1**: An operator running `--dry-run` on a host without `getent group pwuser` will see a warning instead of the expected `-g pwuser` line. Mitigated by R2's explicit fallback + `log_warning`.
- **R-risk-2**: A pre-staged path that the operator *does* want adopted (e.g., legitimate migration of files) requires the explicit `PROVISION_ADOPT_PRESTAGED=yes` opt-in. This is the intended safety trade — the alternative (blind chown) is what produced the Anton case.
- **R-risk-3**: R5's fallback to a generated password requires the operator to record it before the first-login change. `chage -d 0` still enforces the change, but the operator must communicate the initial value out-of-band. Documented in the runbook (Task T7).

## Non-changes to the SDD wiki entry

This spec does not update `EIB-MCP-RAG-Full-State-of-Affairs-Report-2026-07-15.md`. That report enumerates findings; this spec closes a subset of them. Cross-reference is one-directional (this spec → the report).
