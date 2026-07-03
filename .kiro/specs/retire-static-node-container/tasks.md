# Tasks: Retire the Static Node MCP Container

Each task is small and independently verifiable. Tasks 1 and 2 are the
minimum viable retirement; tasks 3 and 4 are the source-side follow-ups.

- [x] **1. Preflight**
  - Confirm no host ports bound on `eib-mcp-rag-static`
    (`docker port eib-mcp-rag-static` empty).
  - Confirm no `.vscode/mcp.json` or `SETUP/docker-mcp/catalogs/eib-local.yaml`
    reference. (Verified 2026-07-03.)

- [x] **2. Sever `mcp-gateway.service Requires=mcp-rag.service`** _(discovered gap)_
  - Attempt with drop-in reset **failed**: systemd only permits *appending*
    to `[Unit] After=/Requires=`, not resetting them (empty-value trick works
    for `ExecStart=` but not dependency lists — verified live).
  - Working fix: `sed -i` on `/etc/systemd/system/mcp-gateway.service` to
    replace both `mcp-rag.service` occurrences with `docker.service`.
  - Backup at `/etc/systemd/system/mcp-gateway.service.bak-phase63c`.
  - Mirror change in repo SPOT `SETUP/systemd/mcp-gateway.service` and
    `SETUP/systemd/mcp-gateway.service.template`.
  - Verify: `systemctl show mcp-gateway.service -p Requires` no longer lists
    `mcp-rag.service`.

- [x] **3. Stop + disable the runtime service** _(operator-run, sudo)_
  - `sudo systemctl restart mcp-gateway.service` (picks up dep change)
  - `sudo systemctl stop mcp-rag.service`
  - `sudo systemctl disable mcp-rag.service`
  - Verify `docker ps` no longer lists `eib-mcp-rag-static`.
  - Verify `get_server_info` via Devtunnel still reports 5 tenants / 53 tools.
  - _Satisfies Requirement 1._

- [x] **4. Disarm the resurrection cron** _(discovered gap; operator-run, sudo)_
  - Root cause: `/etc/cron.d/mcp-health` runs `/opt/mcp/bin/health-check.sh`
    every 5 minutes as root; the script auto-restarts `mcp-rag.service` when
    the container is missing. Journal traced the resurrection to this cron
    within minutes of the first `systemctl stop`.
  - Attempt 1: `sudo mv /etc/cron.d/mcp-health
    /etc/cron.d/mcp-health.disabled-phase63c` — **insufficient**. Rocky 9's
    `crond` reads dotted filenames too; the file fired again at the next
    `*/5` tick (05:00:01, verified in the journal).
  - Attempt 2 (the working fix): `sudo rm
    /etc/cron.d/mcp-health.disabled-phase63c`, followed by a third
    `sudo systemctl stop mcp-rag.service` that finally stuck across cron
    windows.
  - _Satisfies Requirement 4._

- [x] **5. Mark source artifacts deprecated** _(repo edit, no exec)_
  - Prepended `# DEPRECATED (Phase 63c, 2026-07-03): …` header to:
    - `SETUP/systemd/mcp-rag.service`
    - `SETUP/systemd/mcp-rag.service.template`
    - `SETUP/provisioning/12-static-mode-gateway.sh` (+ early `exit 0` guard)
    - `SETUP/cron.d/mcp-health`
    - `SETUP/bin/health-check.sh`
    - `SETUP/bin/deploy-static-gateway.sh` (+ early `exit 0` guard)
  - Both scripts opt out via `MCP_ALLOW_STATIC_MODE_ROLLBACK=1`.
  - Retitled the `12-static-mode-gateway.sh` entry in `SETUP/provisioning/provision.sh`'s
    `SCRIPTS` array so `provision.sh --list` shows the retirement.
  - _Satisfies Requirement 3._

- [x] **6. CHANGELOG entry** _(repo edit)_
  - Added `## [Unreleased] - Phase 63c — Retire Static Node MCP Container
    (Jul 3, 2026)` block referencing this spec, listing the sudo commands
    executed, and quoting the verification numbers. Expanded post-discovery
    to cover the cron resurrection gap and the parallel deprecations.
  - _Satisfies Requirement 5._
