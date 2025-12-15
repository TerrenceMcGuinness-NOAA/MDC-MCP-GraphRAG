# KasmVNC multi-user (one DISPLAY per Linux user)

This repo's runtime host uses a **systemd template unit** to run one KasmVNC/TigerVNC desktop per Linux user.

## What is running (current behavior)

- The systemd unit template is `/etc/systemd/system/kasmvnc@.service`.
- Per-user overrides are read from `/etc/kasmvnc/<username>.conf`.
- KasmVNC web UI listens on a **websocket HTTPS port** (observed: display `:1` -> port `8444`).
- The desktop startup script is the standard `~/.vnc/xstartup`.
- Web login users/permissions are stored in `~/.kasmpasswd`.

## Access (prototype cohort): SSH local port forwarding

Until devtunnels/SSO/TLS choices are reviewed by security, the recommended prototype-cohort access path is basic SSH port forwarding.

See `docs/KASMVNC_SSH_PORT_FORWARDING_RUNBOOK.md`.

## Add a new user session

You can add a user session either manually (edit `/etc/kasmvnc/<username>.conf`) or via the repo provisioning script (recommended).

### Recommended (on-demand) path

Configure a user on demand (auto-allocates a free display):

```bash
sudo /mcp_rag_eib/eib-mcp-rag-server/SETUP/provisioning/09-desktop-vnc.sh --user <username>
```

Configure and also start it immediately:

```bash
sudo /mcp_rag_eib/eib-mcp-rag-server/SETUP/provisioning/09-desktop-vnc.sh --user <username> --enable-now
```

Force a specific display (only valid for a single user):

```bash
sudo /mcp_rag_eib/eib-mcp-rag-server/SETUP/provisioning/09-desktop-vnc.sh --user <username> --display 2
```

Show current config + unit status (read-only):

```bash
sudo /mcp_rag_eib/eib-mcp-rag-server/SETUP/provisioning/09-desktop-vnc.sh --status
```

### 1) Pick a unique display number

Choose a display number `N` that is not used on this host (e.g., `:2`, `:3`, ...).

### 2) Create the per-user config

Create `/etc/kasmvnc/<username>.conf`:

```ini
VNCDISPLAY=:2
GEOMETRY=1920x1080
DEPTH=24
```

### 3) Ensure the user can log in (kasm password file)

KasmVNC web auth uses `~/.kasmpasswd`. The service can hang (non-interactive) if no write-capable user exists.

A safe pattern is to run the passwd tool **as the target user**:

```bash
sudo -iu <username>
# then:
kasmvncpasswd -u <username> -w
```

If you need to target a specific password file path:

```bash
kasmvncpasswd -u <username> -w -n /home/<username>/.kasmpasswd
```

### 4) Start and enable the service

```bash
sudo systemctl enable --now kasmvnc@<username>.service
```

### 5) Find the URL/port

The port can be confirmed from either:

- `journalctl -u kasmvnc@<username>.service -n 200 --no-pager`
- `tail -n 50 /home/<username>/.vnc/*:<N>.log`

The log will include a line like:

```
Paste this url in your browser:
https://<host-ip>:<port>
```

## Operational cleanup (avoid collisions)

If the legacy `vncserver@<N>.service` unit exists for the same display, it can kill the new session by repeatedly running `vncserver -kill :N`.

Recommended:

```bash
sudo systemctl stop vncserver@1.service
sudo systemctl disable vncserver@1.service
sudo systemctl mask vncserver@1.service
```

## Troubleshooting

- **Web port not listening / SSH tunnel shows Connection refused**:
  - Check `systemctl status kasmvnc@<username>.service`.
  - Check for missing write-capable user in `~/.kasmpasswd` and fix via `kasmvncpasswd -w`.
- **Display already in use**:
  - Pick a different `VNCDISPLAY=...` in `/etc/kasmvnc/<username>.conf`.
  - Or stop the conflicting service and remove stale Xvnc processes.
