# Phase 18: KasmVNC Access via SSH Port Forwarding (Runbook)

## Description

Document the short-term operational access pattern for the prototype cohort: use **basic SSH local port forwarding** to access per-user KasmVNC web desktops.

This phase intentionally avoids devtunnels/SSO/TLS decisions until security review is available.

## Goals

- Provide copy/paste commands for cohort members to reach per-user desktops.
- Ensure the workflow is compatible with the existing per-user systemd units (`kasmvnc@<user>.service`).
- Keep steps minimal and repeatable for post-provisioning user additions.

## Non-goals

- No public HTTPS exposure.
- No certificate distribution / PKI.
- No SSO integration.

## Steps

1. Create a concise runbook in `docs/` describing:
   - How to add/configure a user session post-provisioning using `SETUP/provisioning/09-desktop-vnc.sh`.
   - How to start/stop the user’s service with systemd.
   - How to determine the user’s web port (8443 + display).
   - SSH local port-forward commands (Linux/macOS and Windows PowerShell).
   - The local URL to open and expected auth prompt.

2. Add a short pointer in the existing multi-user doc to the new runbook.

## Validation

- Confirm a user session is reachable via SSH port forwarding:
  - On server: `sudo systemctl is-active kasmvnc@<user>.service` returns `active`.
  - On client: `ssh -L <local_port>:127.0.0.1:<remote_port> <user>@<host>` connects.
  - In browser: `http://localhost:<local_port>/` returns a KasmVNC BasicAuth prompt and loads after login.

