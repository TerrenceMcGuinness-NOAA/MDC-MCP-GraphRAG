# Phase 13: Multi-user KasmVNC + User Provisioning Integration

## Description

Integrate Linux user provisioning and multi-user KasmVNC (one DISPLAY per Linux user) into the modular provisioning system so the configuration is reproducible on a cold-boot AWS VM. The system is allowed to modify `/etc` because this is a dedicated host and provisioning runs under `sudo` (via `SETUP/bootstrap.sh`).

Key outcomes:
- User creation is executed as part of `SETUP/provisioning/provision.sh`.
- KasmVNC configuration is applied for all provisioned users.
- A stable systemd template (`kasmvnc@.service`) is created and per-user configs under `/etc/kasmvnc/` are generated.
- Legacy/competing VNC services that can kill the Kasm session (e.g., `vncserver@1.service`) are prevented from starting.

## Steps

### Step 1: Establish a single source of truth for provisioned users
- Create a shared config file (e.g., `SETUP/provisioning/user_config.sh`) containing:
  - `PROVISION_USERS=(...)` (including Terry + additional users)
  - scratch root path
  - display mapping policy (start at `:1`, increment per user)
  - optional list of users to auto-enable at boot

### Step 2: Make the existing user provisioning script reusable by modular provisioning
- Refactor `SETUP/bin/provision_users.sh` so it can be sourced without executing `main`.
- Make it read the user list from the shared config file.

### Step 3: Add a new modular provisioning step for user accounts
- Add a new provisioning script in `SETUP/provisioning/` (e.g., `00-users.sh`).
- Update `SETUP/provisioning/provision.sh` to run the new script early.
- Ensure the script is idempotent:
  - skips existing users
  - preserves existing keys where present

### Step 4: Update the VNC provisioning to support multi-user KasmVNC via systemd
- Update `SETUP/provisioning/09-desktop-vnc.sh` to:
  - configure `.vnc/xstartup`, `.vnc/config`, `.vnc/kasmvnc.yaml` for each provisioned user
  - create `/etc/systemd/system/kasmvnc@.service`
  - create `/etc/kasmvnc/<user>.conf` for each user (with `VNCDISPLAY=:N`)
  - optionally enable `kasmvnc@<user>.service` for selected users
  - prevent legacy `vncserver@1.service` from starting (disable+mask)

### Step 5: Documentation and operator guidance
- Ensure there is a clear runbook for adding a new user/display and enabling the service.
- Keep it consistent with the modular provisioning system.

## Validation

Run on a clean VM (or after stopping services) and validate:
1. `sudo SETUP/provisioning/provision.sh --only 00` creates users and scratch workspaces.
2. `sudo SETUP/provisioning/provision.sh --only 09` creates:
   - `/etc/systemd/system/kasmvnc@.service`
   - `/etc/kasmvnc/<user>.conf`
3. Service behavior:
   - `systemctl is-enabled vncserver@1.service` is `masked` (or `disabled`) to avoid conflicts.
   - `systemctl enable --now kasmvnc@Terry.McGuinness.service` works and produces a web UI.
4. Ports:
   - `ss -ltn | grep 8444` shows the websocket listener when display `:1` is running.
5. Desktop:
   - Logging into the KasmVNC web UI lands in a MATE desktop session.
