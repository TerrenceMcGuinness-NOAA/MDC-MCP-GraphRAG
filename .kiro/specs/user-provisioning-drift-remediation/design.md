# User-Provisioning Drift Remediation — Design

## Overview

Additive changes to `SETUP/provisioning/00-users.sh`. No new files, no new SPOT fields, no `common.sh` changes required. Reuses the T2 helpers (`resolve_ownership`, `list_prestaged_paths`) and the T6 helper (`check_user_integrity`) unchanged. Backward-compatible: `--remediate` is a purely additive flag; running the script without it behaves exactly as today.

## Data flow

```
sudo ./00-users.sh --remediate <user> [--dry-run]
        │
        ▼
provision_user gate rejected (username matches --remediate, not --user)
        │
        ▼
remediate_user <user>
   ├── refuse if !id <user>          (R9)
   ├── check_user_integrity → drifts (T6 helper reused)
   ├── if no drifts → log "no remediation needed", return 0 (R2/R8)
   ├── if DRY_RUN=true → render_remediation_plan; return 0 (R6)
   ├── for each drift row apply the surgical fix (R3/R4/R5)
   │     • primary group  → usermod -g "${PROVISION_PRIMARY_GROUP}" <user>
   │     • scratch owner  → chown "${user}:${PROVISION_PRIMARY_GROUP}" \
   │                         "${SCRATCH_ROOT}/<user>"        (top-level only)
   │     • supp groups    → usermod -aG <missing> <user>     (per group)
   ├── enumerate scratch children still not owned by <user> as [PRESERVED]
   │   (R4 preserve semantics; unless PROVISION_ADOPT_PRESTAGED=yes)
   └── re-run check_user_integrity → before/after report (R7)
```

## Flag parsing changes (arg-parse loop)

Add `--remediate <user>` alongside the existing loop. New global array `REMEDIATE_USERS=()` mirrors `TARGET_USERS`. Uses the same repeatable pattern.

```bash
REMEDIATE_USERS=()
# ... inside the case block:
    --remediate)
      [[ $# -ge 2 ]] || { log_error "--remediate requires a username"; exit 2; }
      REMEDIATE_USERS+=("$2")
      shift 2
      ;;
```

Precedence: `--status` still exits early (unchanged). `--remediate` and `--user` are **mutually exclusive** in the same invocation — reject with `[ERROR]` if both are given.

Main-flow dispatch after arg parsing:

```bash
if [[ ${#REMEDIATE_USERS[@]} -gt 0 ]]; then
  for username in "${REMEDIATE_USERS[@]}"; do
    remediate_user "${username}"
  done
  log_success "Remediation step complete"
  exit 0
fi
```

## `remediate_user()` — new function

Placement: immediately after `provision_user()`. Signature `remediate_user <username>`.

```bash
remediate_user() {
  local username="$1"

  log_subsection "Remediating user: ${username}"

  # R9: refuse on non-existent user
  if ! id "${username}" &>/dev/null; then
    log_error "user ${username} does not exist; --remediate is not for creation"
    return 1
  fi

  # R2/R7: detect drifts up front
  local drifts
  drifts="$(check_user_drifts "${username}")"    # helper below
  if [[ -z "${drifts}" ]]; then
    log_info "No drift detected for ${username}; nothing to remediate"
    return 0
  fi

  # R6: dry-run gate
  if [[ "${DRY_RUN}" == true ]]; then
    render_remediation_plan "${username}" "${drifts}"
    return 0
  fi

  # Apply fixes based on drift set
  local group="${PROVISION_PRIMARY_GROUP}"

  if grep -q '^primary_group ' <<<"${drifts}"; then
    if getent group "${group}" > /dev/null 2>&1; then
      log_info "usermod -g ${group} ${username}"
      usermod -g "${group}" "${username}" || log_error "usermod -g failed"
    else
      log_warning "Primary group '${group}' missing on host; skipping"
    fi
  fi

  if grep -q '^scratch_owner ' <<<"${drifts}"; then
    local scratch="${SCRATCH_ROOT}/${username}"
    log_info "chown ${username}:${group} ${scratch}    # top-level only (R3-safe)"
    chown "${username}:${group}" "${scratch}" || log_error "scratch chown failed"

    # Enumerate any children still not owned by the target user; either preserve
    # (default) or adopt (PROVISION_ADOPT_PRESTAGED=yes). Reuses T2 helper.
    mapfile -t prestaged < <(list_prestaged_paths "${scratch}" "${username}")
    if [[ ${#prestaged[@]} -gt 0 ]]; then
      if [[ "${PROVISION_ADOPT_PRESTAGED}" == "yes" ]]; then
        log_warning "Adopting ${#prestaged[@]} pre-staged path(s) into ${username}"
        chown -R "${username}:${group}" "${scratch}"
      else
        log_warning "Preserving ${#prestaged[@]} pre-staged path(s) (set PROVISION_ADOPT_PRESTAGED=yes to adopt):"
        printf '  [PRESERVED] %s\n' "${prestaged[@]}"
      fi
    fi
  fi

  if grep -q '^supp_groups ' <<<"${drifts}"; then
    # Missing groups are encoded after the tag; parse and iterate.
    local missing_line missing
    missing_line="$(grep '^supp_groups ' <<<"${drifts}")"
    missing="${missing_line#supp_groups }"
    local g
    for g in ${missing//,/ }; do
      if getent group "${g}" > /dev/null 2>&1; then
        log_info "usermod -aG ${g} ${username}"
        usermod -aG "${g}" "${username}" || log_error "usermod -aG ${g} failed"
      else
        log_warning "Supplementary group '${g}' missing on host; skipping"
      fi
    done
  fi

  # R7: post-remediation status re-check for this user
  log_info "Post-remediation integrity for ${username}:"
  check_user_integrity "${username}"

  log_success "Remediation complete for ${username}"
}
```

## `check_user_drifts()` — small new helper

`check_user_integrity` (T6) prints human-readable rows. `remediate_user` needs a machine-parseable drift set. Add a sibling helper that returns tag-lines, one per drift, so the switch statement can grep them:

```bash
check_user_drifts() {
  local username="$1"
  local drifts=()
  local group="${PROVISION_PRIMARY_GROUP}"
  local scratch="${SCRATCH_ROOT}/${username}"
  local expected_owner="${username}:${group}"

  # primary group
  local actual_group
  actual_group="$(id -gn "${username}" 2>/dev/null || echo "")"
  [[ "${actual_group}" != "${group}" ]] && drifts+=("primary_group ${actual_group}")

  # scratch top-level owner
  if [[ -d "${scratch}" ]]; then
    local actual_owner
    actual_owner="$(stat -c '%U:%G' "${scratch}" 2>/dev/null || echo "")"
    [[ "${actual_owner}" != "${expected_owner}" ]] \
      && drifts+=("scratch_owner ${actual_owner}")
  fi

  # supplementary groups — only for groups that exist on host
  local required=(docker kasmvnc-cert)
  local missing=()
  local g
  for g in "${required[@]}"; do
    if getent group "${g}" > /dev/null 2>&1; then
      id -nG "${username}" 2>/dev/null | tr ' ' '\n' | grep -qx "${g}" \
        || missing+=("${g}")
    fi
  done
  [[ ${#missing[@]} -gt 0 ]] && drifts+=("supp_groups $(IFS=,; echo "${missing[*]}")")

  printf '%s\n' "${drifts[@]}"
}
```

Rationale for splitting: `check_user_integrity` stays purely human-facing (T6 contract unchanged); `check_user_drifts` is the parseable feed for the remediation switch. Two functions, one purpose each.

## `render_remediation_plan()` — R6 dry-run

Mirrors the parent spec's `render_provisioning_plan()`:

```bash
render_remediation_plan() {
  local username="$1"
  local drifts="$2"
  local group="${PROVISION_PRIMARY_GROUP}"

  echo ""
  echo "═══════════════════════════════════════════════════════════════════"
  echo "  DRY-RUN REMEDIATION PLAN for user: ${username}"
  echo "  (no mutations will be performed)"
  echo "═══════════════════════════════════════════════════════════════════"
  echo ""
  local n=0
  if grep -q '^primary_group ' <<<"${drifts}"; then
    n=$((n+1))
    echo "[${n}] Primary group"
    echo "    usermod -g ${group} ${username}"
  fi
  if grep -q '^scratch_owner ' <<<"${drifts}"; then
    n=$((n+1))
    echo "[${n}] Scratch dir top-level"
    echo "    chown ${username}:${group} ${SCRATCH_ROOT}/${username}    # top-level only"
    mapfile -t prestaged < <(list_prestaged_paths "${SCRATCH_ROOT}/${username}" "${username}")
    if [[ ${#prestaged[@]} -gt 0 ]]; then
      echo ""
      echo "    [PRESERVED] ${#prestaged[@]} pre-staged child path(s) will NOT be re-owned"
      echo "                (set PROVISION_ADOPT_PRESTAGED=yes to adopt instead):"
      printf '      [PRESERVED] %s\n' "${prestaged[@]}"
    fi
  fi
  if grep -q '^supp_groups ' <<<"${drifts}"; then
    n=$((n+1))
    echo "[${n}] Supplementary group memberships"
    local missing_line missing
    missing_line="$(grep '^supp_groups ' <<<"${drifts}")"
    missing="${missing_line#supp_groups }"
    local g
    for g in ${missing//,/ }; do
      echo "    usermod -aG ${g} ${username}"
    done
  fi
  echo ""
  echo "═══════════════════════════════════════════════════════════════════"
  echo "  END DRY-RUN PLAN — nothing was written to the host"
  echo "═══════════════════════════════════════════════════════════════════"
}
```

## Mutual-exclusion guard

Immediately after arg parsing, add:

```bash
if [[ ${#TARGET_USERS[@]} -gt 0 ]] && [[ ${#REMEDIATE_USERS[@]} -gt 0 ]]; then
  log_error "--user and --remediate are mutually exclusive in the same invocation"
  exit 2
fi
```

Rationale: one intent per invocation. Create OR remediate, never both.

## Deliberately unchanged

- `user_config.sh` — no new SPOT fields; R3/R5 reuse `PROVISION_PRIMARY_GROUP` and `PROVISION_ADOPT_PRESTAGED`.
- `common.sh` — no new helpers required. T2's `resolve_ownership` and `list_prestaged_paths` used as-is.
- `check_user_integrity` — T6 human-readable output stays unchanged (public contract). *(Superseded by R10 — see "Option C addendum" below.)*
- `create_user`, `create_scratch_space`, `provision_user`, `render_provisioning_plan`, `print_status` — untouched. This spec is purely additive.

---

## Option C addendum — R10 missing-clone drift (added 2026-07-15)

Extending scope to close the clone-presence gap surfaced by the operator during T6-Terry dry-run testing. Anna, Brian, Georgios each have an `eib-mcp-rag-server` clone in scratch (owned by Terry, addressed by R4's preserve/adopt); Terry has none by intentional design (works from `${EIB_REPO}`); Anton has one properly owned. R10 makes this a first-class drift so future users are caught automatically.

### New SPOT field

Add to `user_config.sh` (below the existing R3-related fields):

```bash
# R10 (drift-remediation spec): users for whom check_user_drifts and
# check_user_integrity do NOT treat a missing eib-mcp-rag-server clone in
# scratch as drift. Typically the operator who runs provisioning and works
# from the shared main checkout at ${EIB_REPO} instead of a personal scratch
# clone. Everyone else on PROVISION_USERS is expected to have a clone.
PROVISION_CLONE_EXEMPT_USERS=(
  "Terry.McGuinness"
)
```

### `check_user_drifts` extension (this spec's helper)

Append the new check at the end of the function, before the final `printf` guard:

```bash
  # R10: missing clone in scratch (skipped for exempt users)
  local exempt=false u
  for u in "${PROVISION_CLONE_EXEMPT_USERS[@]}"; do
    [[ "${username}" == "${u}" ]] && { exempt=true; break; }
  done
  if ! ${exempt}; then
    local repo="${scratch}/eib-mcp-rag-server"
    [[ ! -d "${repo}/.git" ]] && drifts+=("missing_clone")
  fi
```

### `check_user_integrity` extension (parent-spec T6 helper — cross-spec touch)

Append a matching row to the T6 output, following the same table shape. Cross-spec but same file (`00-users.sh`), same intent (keep the two helpers symmetric). Renders `[OK]` when the clone exists, `[DRIFT expected=cloned actual=missing]` when it does not. **For exempt users (`PROVISION_CLONE_EXEMPT_USERS`) the row is omitted entirely** — matches the existing T6 pattern that conditionally omits checks when the underlying condition doesn't apply on this host (e.g., the `kasmvnc-cert` supplementary-group check is skipped when that group is not present). This keeps `check_user_integrity` and `check_user_drifts` behaviorally symmetric: both emit nothing for the exempt-user case.

### `remediate_user` new branch (R10 apply)

Append to the branch chain in `remediate_user`, between the R5 supp-groups branch and the R7 post-remediation status re-check:

```bash
  # R10: missing clone in scratch
  if grep -q '^missing_clone' <<<"${drifts}"; then
    log_info "clone_mcp_rag_repo ${username}    # calling parent-spec's cloner"
    clone_mcp_rag_repo "${username}" || log_error "clone_mcp_rag_repo failed for ${username}"
  fi
```

Reuses `clone_mcp_rag_repo` unchanged — the same function that landed Anton's clone during parent-spec T8. Handles operator-SSH-authenticated clone from `${UPSTREAM_REPO_URL}`, R3-safe pre-create of `${repo_dir}` chown'd to `${SUDO_USER}`, and final `chown -R <user>:pwuser ${repo_dir}` handoff. No new code path in the cloner; only a new caller.

### `render_remediation_plan` new section

Add a numbered section per drift, matching the existing pattern:

```bash
  # [n] Missing clone (R10)
  if grep -q '^missing_clone' <<<"${drifts}"; then
    n=$((n+1))
    echo "[${n}] Missing eib-mcp-rag-server clone in scratch"
    echo "    (clone_mcp_rag_repo ${username} — will invoke:)"
    echo "    install -d -m 755 -o \${SUDO_USER} -g pwuser \\"
    echo "        ${workspace_dir}/eib-mcp-rag-server"
    echo "    sudo -u \${SUDO_USER} git clone ${UPSTREAM_REPO_URL} \\"
    echo "        ${workspace_dir}/eib-mcp-rag-server"
    echo "    chown -R ${username}:${group} ${workspace_dir}/eib-mcp-rag-server"
    echo ""
  fi
```

### README subsection

Extend the `## Retroactive drift remediation (--remediate)` section (added in T5) with a new `### R10 missing-clone drift and the exempt allowlist` subsection covering:
- Purpose (missing scratch clone is drift by default).
- `PROVISION_CLONE_EXEMPT_USERS` allowlist behavior (currently: `Terry.McGuinness`; SPOT to expand for future operators or shared-checkout users).
- The clone runs as `${SUDO_USER}` reusing the parent-spec's `clone_mcp_rag_repo` — same auth path as `--user` provisioning.

### Cross-spec touch — acknowledged

Modifying `check_user_integrity` reaches into the parent spec's T6 helper. Justification: the two helpers (`check_user_integrity` human-facing, `check_user_drifts` machine-parseable) are meant to stay symmetric — extending one requires extending the other. Both live in the same file (`00-users.sh`); the change is a purely additive row. The parent spec's T6 acceptance criteria (six checks emitting `[OK]` for clean users) still hold; a seventh row is added for the same clean-user population when R10 lands.

### R10 risks

- **R-risk-10a** — `clone_mcp_rag_repo` requires `${SUDO_USER}` to have SSH access to `${UPSTREAM_REPO_URL}` (gitlab-community). Same constraint as parent-spec T8, inherited. If a future operator without SSH access runs `--remediate` on a missing-clone user, the clone will fail with the parent-spec's `[ERROR] Clone failed. Confirm ${operator} has SSH access...` message. Documented, not silently swallowed.
- **R-risk-10b** — The exempt allowlist is a per-host list, not a per-operator list. If Terry stops being the operator and someone else takes over provisioning duties, they'll need to be added to `PROVISION_CLONE_EXEMPT_USERS` too (or Terry removed if he no longer works from `${EIB_REPO}`). Acceptable; explicit is better than clever.

## Risks

- **R-risk-1** — `usermod -g` on a logged-in user. Group flip takes effect on the user's next login/session. If Anna is currently logged in via VNC/SSH, her running processes retain the old primary group until she logs out. Acceptable — the drift is filesystem hygiene, not a security fix.
- **R-risk-2** — Silent group ownership on files created under the old primary group. Files Anna created before remediation are still owned `Anna.Smoot:Anna.Smoot` in her `$HOME`. Out of scope; this spec only fixes `${SCRATCH_ROOT}/${username}` and the account itself. If needed, a follow-up `--remediate-home` could sweep `$HOME` — but not today.
- **R-risk-3** — `chown` on the scratch top-level might briefly show mixed ownership (top=Anna, children=Terry) to any live consumer. Same as parent spec R3 preserve semantics; documented, not a regression.

## Verified pre-conditions before starting

1. Parent spec committed on `develop` at `30af7fd` (T8 live remediation) or later.
2. Terry, Anton = `[OK]×6`; Anna, Brian, Georgios show the three known drifts.
3. `check_user_integrity` (T6 helper) exported and callable.
4. `resolve_ownership`, `list_prestaged_paths` (T2 helpers) exported.
5. No active in-flight run on `00-users.sh` (no `.provision_status` lock file, if such a lock exists).
