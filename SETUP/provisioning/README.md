# MCP RAG Modular Provisioning System

**Version:** 4.2.0
**Date:** July 2026

## Overview

This directory contains a modular provisioning system for the MCP RAG infrastructure. Instead of a single monolithic script, provisioning is split into focused, independently runnable scripts that can be orchestrated together or run individually.

## Quick Start

> **Run `--dry-run` first.** Before provisioning any new user, render the plan
> with `sudo ./00-users.sh --dry-run --user <User.Name>` and inspect the intended
> `useradd`, `chown`, `usermod`, `chpasswd`, `ssh-keygen`, and file-copy steps.
> `--dry-run` is a no-op on the host — nothing is created or modified. Only run
> the same command without `--dry-run` once the plan looks correct. See
> [Dry-run mode (`--dry-run`)](#dry-run-mode---dry-run) below.

```bash
# Preview what would happen for a new user (no mutations)
sudo ./00-users.sh --dry-run --user Firstname.Lastname

# Run all provisioning scripts
sudo ./provision.sh

# Run with options
sudo ./provision.sh --skip 09        # Skip VNC setup
sudo ./provision.sh --only 06        # Only run ChromaDB setup
sudo ./provision.sh --fresh          # Clean start (wipe caches)
sudo ./provision.sh --list           # List available scripts
```

## User-provisioning SPOT fields (`user_config.sh`)

`user_config.sh` is the single point of truth for user-provisioning behavior.
Three fields added by the `user-provisioning-ownership-hardening` spec govern
group membership, pre-staged-path handling, and the initial password.

### `PROVISION_PRIMARY_GROUP` (R1, R2)

Primary Linux group applied to every new user by `00-users.sh`.

- **Default**: `pwuser` (matches the existing Terry / Anna / Brian / Georgios
  convention on this host).
- **Effect**: `00-users.sh` invokes `useradd -g "${PROVISION_PRIMARY_GROUP}" -m -s /bin/bash <user>` iff
  the group already exists on the host. If the named group is missing,
  `useradd` falls back to a private group named after the user and
  `00-users.sh` emits a `log_warning` — no silent regression to the wrong
  group.
- **When to override**: set `PROVISION_PRIMARY_GROUP=<groupname>` in
  `user_config.sh` (or export it in the environment) for sites that use a
  different shared operator group.

### `PROVISION_ADOPT_PRESTAGED` (R3)

Controls whether `create_scratch_space()` re-owns files already present under
`${SCRATCH_ROOT}/<user>` at the moment the user is provisioned.

- **Default**: `no` — pre-staged files keep their original owner:group.
  `00-users.sh` still `chown`s the top-level scratch directory itself so the
  new user can write into it.
- **Opt-in**: set `PROVISION_ADOPT_PRESTAGED=yes` (either in `user_config.sh`
  or via `PROVISION_ADOPT_PRESTAGED=yes sudo ./00-users.sh --user <user>`) to
  perform the full `chown -R` and adopt every pre-staged entry into the new
  user. See [Pre-staged path preservation](#pre-staged-path-preservation-r3)
  below for the operator flow.

### `PROVISION_INITIAL_PASSWORD_FILE` (R5)

Path to a mode-`0600` file containing the initial password for new users. The
password itself is deliberately **not** in `user_config.sh` and **not** in
source control.

- **Default**: unset.
- **Precedence** used by `resolve_initial_password <username>` in `common.sh`:
  1. `PROVISION_INITIAL_PASSWORD_FILE` — if set and readable, the file's
     contents are used as the initial password.
  2. Interactive `read -s` prompt — if a TTY is attached and the file is not
     set, the operator is prompted (nothing echoed).
  3. Generated 16-character random password — if no TTY is attached (batch
     mode). The generated value is printed **once** to the operator's stdout
     and is not written to any state file or systemd journal.

In all three cases `chage -d 0 <user>` is invoked so the user is forced to
change the password on first login.

### Precedence summary

| Field | Consumer | Fallback on failure |
|-------|----------|---------------------|
| `PROVISION_PRIMARY_GROUP` | `00-users.sh::create_user()` | Private group + `log_warning` |
| `PROVISION_ADOPT_PRESTAGED` | `00-users.sh::create_scratch_space()` | `no` (preserve pre-staged) |
| `PROVISION_INITIAL_PASSWORD_FILE` | `common.sh::resolve_initial_password()` | Interactive prompt → generated password |

### R5 — Record the initial password before first login

Because `PROVISION_INITIAL_PASSWORD_FILE` is never persisted back into source
and the interactive / generated paths emit the value only to the operator's
stdout, **the operator must record the initial password before the user's
first login**. The password is required by the user to satisfy the
`chage -d 0` forced-change prompt on their first SSH session. Losing it means
resetting the account by hand.

Recommended handling:

- **File mode** (`PROVISION_INITIAL_PASSWORD_FILE`): keep the file at mode
  `0600` and communicate its contents to the user through an out-of-band
  secure channel (password manager, encrypted email, etc.).
- **Interactive prompt**: capture the value directly into your password
  manager as you type it — the terminal echoes nothing.
- **Generated password**: copy the single stdout line into your password
  manager immediately. It is not re-emitted anywhere.

## Pre-staged path preservation (R3)

`create_scratch_space()` treats any file under `${SCRATCH_ROOT}/<user>` that is
**not** owned by the target user as a *pre-staged path*. The default policy is
to preserve those files' ownership rather than silently rewriting it, which is
what produced the Anton.Fernando incident on 2026-07-15.

### Default behavior (`PROVISION_ADOPT_PRESTAGED=no`)

When pre-staged paths are detected, `00-users.sh`:

1. Enumerates every entry under `${SCRATCH_ROOT}/<user>` whose owner is not
   `<user>`.
2. Prints a `[PRESERVED] <path>` line per entry to the operator log.
3. `chown`s only the top-level scratch directory itself (single-level, no `-R`)
   so `<user>` can create new files inside it.
4. Leaves every enumerated pre-staged path with its original owner:group
   intact.

### Adoption (`PROVISION_ADOPT_PRESTAGED=yes`)

If the operator has consciously decided that pre-staged content belongs to the
new user (e.g. a legitimate migration), opt in by setting the flag before
running the script:

```bash
# Two ways to opt in
PROVISION_ADOPT_PRESTAGED=yes sudo ./00-users.sh --user Firstname.Lastname
# ...or edit user_config.sh: PROVISION_ADOPT_PRESTAGED="yes"
```

Under the opt-in path, `create_scratch_space()` runs the full
`chown -R "${username}:${PROVISION_PRIMARY_GROUP}" "${workspace_dir}"` and
adopts every pre-staged entry into the new user.

### Recommended flow

1. `sudo ./00-users.sh --dry-run --user <user>` — the plan lists every
   `[PRESERVED]` path that would be skipped under the default policy.
2. If any of those files really should belong to the new user, move them out
   of the way manually **or** re-run with `PROVISION_ADOPT_PRESTAGED=yes`.
3. `sudo ./00-users.sh --user <user>` — execute.

## Dry-run mode (`--dry-run`)

`00-users.sh --dry-run [--user <user>]` renders the full provisioning plan
without mutating the host. It is safe to run on production hosts and is the
recommended first step for any new-user provisioning.

The rendered plan lists, in execution order:

- The `useradd` invocation (with the resolved `PROVISION_PRIMARY_GROUP`).
- Every `chown` that would run against `${SCRATCH_ROOT}/<user>`, including a
  `[PRESERVED] <path>` line for each pre-staged entry that would be skipped
  under the current `PROVISION_ADOPT_PRESTAGED` policy.
- The `usermod -aG` commands (`docker`, `kasmvnc-cert` when present).
- The `ssh-keygen` invocation for the user's `~/.ssh/id_rsa`.
- Template copies (`bashrc`, `bash_profile`, `code.sh`) and the `.vscode/mcp.json` write.
- The password path that `resolve_initial_password` will use
  (`PROVISION_INITIAL_PASSWORD_FILE`, interactive prompt, or generated) — the
  password value itself is **not** rendered.

`--dry-run` exits `0` if the plan renders cleanly and does not perform any
`useradd`, `chown`, `usermod`, `chpasswd`, or file-write side effect. Verify
with `getent passwd <user>` before and after — the entry must not appear.

## Script Inventory

| Script | Description | Dependencies |
|--------|-------------|--------------|
| `00-users.sh` | Create Linux user accounts | None |
| `01-directories.sh` | Create directory structure | None |
| `02-system-deps.sh` | Install system packages | None |
| `03-docker.sh` | Docker installation | 02 |
| `04-nodejs.sh` | Node.js environment | 02 |
| `05-python-spack.sh` | Python and Spack modules | 02 |
| `06-chromadb.sh` | ChromaDB Docker container | 01, 03 |
| `07-mcp-server.sh` | MCP server deployment | 01, 04 |
| `08-services.sh` | Neo4j, LangFlow, systemd | 03, 06 |
| `09-desktop-vnc.sh` | VNC/noVNC remote desktop | 02 | **DEPRECATED** — Parallel Works provides VNC |
| `10-verification.sh` | Final verification | All |
| `11-docker-mcp-gateway.sh` | Docker MCP Gateway plugin | 03, 07 |
| `12-static-mode-gateway.sh` | Phase 23 Static Mode gateway | 11 |
| `13-container-cleanup.sh` | Smart container cleanup timer | 03 |

## Architecture

```
provisioning/
├── provision.sh          # Master orchestrator
├── common.sh             # Shared functions and variables
├── user_config.sh         # Provisioned users + defaults (SPOT)
├── 00-users.sh            # Linux user provisioning
├── 01-directories.sh     # Directory structure
├── 02-system-deps.sh     # System dependencies
├── 03-docker.sh          # Docker setup
├── 04-nodejs.sh          # Node.js setup
├── 05-python-spack.sh    # Python/Spack setup
├── 06-chromadb.sh        # ChromaDB container
├── 07-mcp-server.sh      # MCP server
├── 08-services.sh        # Docker Compose services
├── 09-desktop-vnc.sh     # VNC remote desktop (DEPRECATED — Parallel Works)
├── 10-verification.sh    # Verification
├── 11-docker-mcp-gateway.sh  # Docker MCP Gateway plugin
├── 12-static-mode-gateway.sh # Phase 23 static mode gateway
├── 13-container-cleanup.sh   # Smart container cleanup (Phase 23)
└── README.md             # This file
```

## Common Library (common.sh)

The `common.sh` library provides:

- **Color output functions**: `log_info`, `log_success`, `log_warning`, `log_error`
- **Section headers**: `log_section`, `log_subsection`
- **Environment variables**: `PERSISTENT_ROOT`, `MCP_ROOT`, `CHROMADB_URL`, etc.
- **Helper functions**: `require_root`, `command_exists`, `wait_for_service`
- **Result tracking**: `record_result`, `print_summary_report`

### Using in Scripts

```bash
#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

require_root

log_subsection "My Script Section"
log_info "Doing something..."
log_success "Done!"
```

## Running Individual Scripts

Each script can be run independently:

```bash
# Run a single script
sudo ./06-chromadb.sh

# Check script syntax
bash -n 06-chromadb.sh
```

## Master Orchestrator Options

```bash
# Show help
sudo ./provision.sh --help

# List all scripts
sudo ./provision.sh --list

# Skip specific scripts
sudo ./provision.sh --skip 09 --skip 10

# Run only specific scripts
sudo ./provision.sh --only 01 --only 06

# Fresh start (clean caches)
sudo ./provision.sh --fresh
```

## Summary Report

At the end of provisioning, a summary report is displayed:

```
════════════════════════════════════════════════════════════════
  Provisioning Summary Report
════════════════════════════════════════════════════════════════

Script                              Status       Details
----------------------------------- ------------ --------
01-directories.sh                   SUCCESS      3s
02-system-deps.sh                   SUCCESS      45s
03-docker.sh                        SUCCESS      12s
...
09-desktop-vnc.sh                   SKIPPED      User requested skip
10-verification.sh                  SUCCESS      2s

Total: 10 | Success: 9 | Failed: 0 | Skipped: 1
```

## Comparison with Legacy Script

| Feature | Legacy (v3.x) | Modular (v4.0) |
|---------|---------------|----------------|
| Single file | 1200+ lines | ~100 lines each |
| Error handling | Exits on first error | Continues, reports all |
| Selective run | No | `--skip`, `--only` |
| Independent testing | No | Yes |
| Summary report | No | Yes |
| Maintenance | Difficult | Easy |

## Migration from Legacy

The legacy `provision_mcp_rag_persistent.sh` is preserved for reference. To migrate:

1. Use `./provision.sh` for new installations
2. For updates, run only needed scripts: `./provision.sh --only 07`
3. Legacy script remains functional but unmaintained

## Troubleshooting

### Script fails with "common.sh not found"

```bash
# Ensure you're in the provisioning directory
cd /mcp_rag_eib/eib-mcp-rag-server/SETUP/provisioning
sudo ./provision.sh
```

### Permission denied

```bash
# Make scripts executable
chmod +x *.sh
```

### Check individual script logs

```bash
# Run script with verbose output
sudo bash -x ./06-chromadb.sh
```

## Contributing

When adding new provisioning steps:

1. Create a new numbered script (e.g., `11-new-feature.sh`)
2. Source `common.sh` at the start
3. Use `log_*` functions for output
4. Add to `SCRIPTS` array in `provision.sh`
5. Update this README

## Version History

- **4.2.0** (Jul 2026): `user-provisioning-ownership-hardening` — documented
  the three new SPOT fields (`PROVISION_PRIMARY_GROUP`,
  `PROVISION_ADOPT_PRESTAGED`, `PROVISION_INITIAL_PASSWORD_FILE`), the
  `--dry-run` flag on `00-users.sh`, the pre-staged-path preservation
  behavior (R3), and the R5 "record the initial password before first login"
  operator note.
- **4.1.0** (Feb 2026): Deprecated 09-desktop-vnc.sh (Parallel Works provides VNC)
- **4.0.0** (Dec 2025): Initial modular provisioning system
- Refactored from `provision_mcp_rag_persistent.sh` v3.6.x
