# KasmVNC per-user desktops via SSH port forwarding (prototype cohort runbook)

This repo supports one KasmVNC desktop per Linux user via a systemd template unit.

This runbook documents the **short-term, security-simple** access method: **SSH local port forwarding**.

## 1) Add or update a user session (server-side)

From the host (or a privileged shell on the host), configure a single user post-provisioning:

- Configure user (repeatable):
  - `sudo /mcp_rag_eib/eib-mcp-rag-server/SETUP/provisioning/09-desktop-vnc.sh --user <username>`

- Configure user and start immediately:
  - `sudo /mcp_rag_eib/eib-mcp-rag-server/SETUP/provisioning/09-desktop-vnc.sh --user <username> --enable-now`

- Optional: force a specific display (sets `VNCDISPLAY=:N`):
  - `sudo /mcp_rag_eib/eib-mcp-rag-server/SETUP/provisioning/09-desktop-vnc.sh --user <username> --display <N>`

- View current assignments and unit status (read-only):
  - `sudo /mcp_rag_eib/eib-mcp-rag-server/SETUP/provisioning/09-desktop-vnc.sh --status --user <username>`

## 2) Start/stop the desktop service (server-side)

- Start now and enable at boot:
  - `sudo systemctl enable --now kasmvnc@<username>.service`

- Restart (useful if auth lockout is suspected):
  - `sudo systemctl restart kasmvnc@<username>.service`

- Stop:
  - `sudo systemctl stop kasmvnc@<username>.service`

- Check status:
  - `sudo systemctl --no-pager --full status kasmvnc@<username>.service`

## 3) Determine the user’s KasmVNC web port (server-side)

KasmVNC’s web port is:

$$\text{port} = 8443 + \text{displayNumber}$$

Examples:
- Display `:1` → port `8444`
- Display `:2` → port `8445`

The display is set in `/etc/kasmvnc/<username>.conf` (key: `VNCDISPLAY=...`).

## 4) Set/rotate the user’s KasmVNC web password (server-side)

KasmVNC web auth uses `~/.kasmpasswd`.

- Set/reset password interactively:
  - `sudo kasmvncpasswd -u <username>`

## 5) Connect from your client using SSH local port forwarding

### Linux/macOS

Forward the remote web port to a local port:

- Example: user desktop is on remote port `8445`:
  - `ssh -L 8445:127.0.0.1:8445 <ssh_user>@<host>`

Then open:
- `http://localhost:8445/`

### Windows PowerShell (OpenSSH)

- `ssh -L 8445:127.0.0.1:8445 <ssh_user>@<host>`

Then open:
- `http://localhost:8445/`

## Expected browser behavior

- You should get a BasicAuth prompt.
- Username: the Linux user (e.g., `Anna.Smoot`)
- Password: whatever was set via `kasmvncpasswd -u <username>`

## Troubleshooting

- **Connection refused**: check `sudo systemctl status kasmvnc@<username>.service` on the server.
- **Auth keeps failing**: reset with `sudo kasmvncpasswd -u <username>`.
- **Temporary lockout / blacklisting after repeated failed auth**: restart the service:
  - `sudo systemctl restart kasmvnc@<username>.service`
