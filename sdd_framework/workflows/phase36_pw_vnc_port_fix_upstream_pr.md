# Phase 36: Parallel Works VNC Port Mismatch — Upstream Bug Fix PR

**Version**: 1.0.0
**Status**: Planning
**Created**: 2026-03-05
**Target**: Parallel Works `start-template-v3.sh` (vncserver/)

## Overview

Submit an upstream PR to Parallel Works fixing the nginx→KasmVNC port mismatch bug in `start-template-v3.sh`. On session re-launch, stale config files owned by nginx UID 101 cause `Permission denied` on config writes, leaving nginx proxying to a dead port (502/504 Bad Gateway). Additionally, the nginx `listen` port diverges from `SESSION_PORT` because each `pw agent open-port` call returns independent random ports.

### Related Work
- **v7.25.3** (`SETUP/scripts/fix-pw-vnc-port-mismatch.sh`) — our workaround script
- **v7.25.1/v7.25.2** — KasmVNC OpenSSL 3.5.x fixes (separate issue)
- **New Rocky 9 image distro** — may resolve the OpenSSL issue at the image level; evaluate when available

## Bug Analysis

### Root Cause (confirmed March 4-5, 2026)

PW `start-template-v3.sh` port assignment creates a three-way mismatch on re-launch:

1. `SESSION_PORT` — assigned by PW session runner (portal expects this)
2. `kasmvnc_port` — `pw agent open-port` (line ~378, KasmVNC `-websocketPort`)
3. `proxy_port` — separate `pw agent open-port` (line ~539), writes `config.conf`
4. On re-launch, `config.conf` is owned by nginx UID 101 → **Permission denied** → write fails silently
5. Old `config.conf` has stale `listen` and `proxy_pass` ports → 502

### Observed Port States (March 5 session)

| Component | Expected | Actual (stale) |
|-----------|----------|----------------|
| SESSION_PORT | 40135 | 40135 (correct) |
| Nginx listen | 40135 | 45715/41395 (prior session) |
| Nginx proxy_pass | 36831 | 39419 (prior session) |
| KasmVNC websocket | 36831 | 36831 (correct) |

### Additional Issues
- Two duplicate `server {}` blocks in `config.conf` (nginx warns "conflicting server name")
- `>>` (append) used instead of `>` (truncate) for config writes
- No error checking on config file write operations

## Proposed Fix (for PW PR)

### Option A: Single port assignment (preferred)
- Use one `pw agent open-port` call for both KasmVNC and nginx proxy
- Or assign `proxy_port = kasmvnc_port` directly instead of a separate `open-port`

### Option B: Defensive config write
- Remove stale `config.conf` before writing (or `chown` it)
- Use `>` (truncate) not `>>` (append)
- Add error checking: if write fails, retry with appropriate permissions
- Ensure `listen` port matches `SESSION_PORT`

### Option C: Cleanup on session start
- Kill stale nginx containers from prior sessions before creating new ones
- Remove old bind-mounted config files

## Phases

### Phase 36A: Locate and analyze PW source
1. Find the `start-template-v3.sh` in PW's marketplace desktop repo
2. Identify the exact lines for port assignment and config writes
3. Map the full port flow: SESSION_PORT → nginx listen → proxy_pass → KasmVNC
4. Check if there's a PW issue tracker or contribution guide

### Phase 36B: Develop and test the fix
5. Fork/branch the PW repo
6. Implement fix (Option A preferred, fallback to B+C)
7. Test on a clean PW session launch
8. Test on a re-launch (the failure case)
9. Verify SESSION_PORT matches nginx listen port end-to-end

### Phase 36C: Submit PR
10. Write PR description with root cause analysis and port trace evidence
11. Reference our workaround script and observed port states
12. Submit PR to Parallel Works

### Phase 36D: Rocky 9 image evaluation
13. When new Rocky 9 distro disk is available, test if OpenSSL 3.5.x issue is resolved at the image level
14. If resolved, document that v7.25.1/v7.25.2 workarounds can be retired
15. If not resolved, update `SETUP/bootstrap.sh` versionlock for new image base

## Success Criteria
- [ ] PR submitted to PW with fix for port mismatch
- [ ] Clean session launch works without manual intervention
- [ ] Session re-launch works without 502/504
- [ ] SESSION_PORT matches nginx listen port on every launch
- [ ] Rocky 9 image OpenSSL status evaluated
