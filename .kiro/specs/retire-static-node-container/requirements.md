# Requirements: Retire the Static Node MCP Container (COTS side)

## Introduction

Phase 63b (2026-07-03) repointed the Docker MCP Gateway (`mcp-gateway.service`,
served at port 18888 via the Devtunnel) at the new x86_64 Python image
`eib-mcp-rag-python:latest` (5 tenants, 53 tools, 9 modules). Since then, the
gateway's per-session `Gateway_Launched_Container` (currently `vibrant_shirley`)
is what actually fronts remote MCP traffic on the COTS Parallel Works host.

The legacy `mcp-rag.service` systemd unit — added in v7.1.1 (2026-01-09) as the
Phase 23 "Static_Node_Container" — continues to run a long-lived
`eib-mcp-rag-static` container from the old Node.js image `eib-mcp-rag:latest`.
Phase 63b's spec labels it "vestigial and unrelated" and out of scope. Live
verification (2026-07-03):

- `docker port eib-mcp-rag-static` → empty (no host ports bound)
- No reference in `.vscode/mcp.json` or `SETUP/docker-mcp/catalogs/eib-local.yaml`
- Devtunnel port 18888 → `mcp-gateway.service` → Python container (5 tenants,
  verified via `get_server_info`)

Two visible costs of leaving it running:

1. **Operator confusion.** `docker ps` shows the old Node image alongside the
   new Python image, prompting the reasonable-but-wrong inference that the
   Node container is what serves remote clients (and hence a single-tenant
   surface).
2. **Idle resource use.** 8 GB memory + 4 CPU reservation per the unit's
   resource limits, for a container nothing routes to.

This spec retires the runtime service and marks the source-side artifacts as
deprecated, without deleting them (rollback safety, per Phase 63b policy which
also preserves the Node image locally).

## Glossary

- **Static_Node_Container**: The `eib-mcp-rag-static` docker container run by
  `mcp-rag.service` from the Node image `eib-mcp-rag:latest`.
- **Static_Service_Unit**: The systemd unit `mcp-rag.service`
  (`/etc/systemd/system/mcp-rag.service`).
- **Repo_Unit_File**: The tracked source of the unit at
  `SETUP/systemd/mcp-rag.service`.
- **Repo_Unit_Template**: The tracked template at
  `SETUP/systemd/mcp-rag.service.template`.
- **Provisioning_Script**: `SETUP/provisioning/12-static-mode-gateway.sh`,
  which installs and starts the `Static_Service_Unit` on new hosts.
- **Gateway_Service**: `mcp-gateway.service` — the Docker MCP Gateway systemd
  unit that spawns per-session Python containers from the catalog.
- **Node_Image**: The container image `eib-mcp-rag:latest`, preserved locally
  as the Phase 63b rollback target.

## Requirements

### Requirement 1: Stop and disable the runtime service

**User Story:** As a platform operator, I want the `Static_Service_Unit` stopped
and disabled, so that `docker ps` reflects the actual serving topology and no
resources are reserved for a vestigial container.

#### Acceptance Criteria

1. WHEN the operator runs `sudo systemctl stop mcp-rag.service`, THEN the
   `Static_Node_Container` SHALL exit and be removed by the unit's `ExecStop*`
   stanzas.
2. WHEN the operator runs `sudo systemctl disable mcp-rag.service`, THEN the
   `Static_Service_Unit` SHALL not restart at boot.
3. AFTER completion, `docker ps` on the host SHALL not list any container
   named `eib-mcp-rag-static`.
4. AFTER completion, `mcp-gateway.service` SHALL remain `active (running)` and
   `get_server_info` via the Devtunnel SHALL continue to report `Tenants: 5
   (default: gw)` and `Total Tools: 53`.

### Requirement 2: Preserve the Node image for rollback

**User Story:** As a platform operator, I want the `Node_Image` retained on
the host, so that Phase 63b's documented rollback path (one-line catalog edit
back to `eib-mcp-rag:latest`) remains available without re-pulling.

#### Acceptance Criteria

1. THE `Node_Image` SHALL remain in the host's local docker image store after
   retirement (`docker images eib-mcp-rag:latest` returns a row).
2. THE spec SHALL NOT include an `image rm` step.

### Requirement 3: Mark source artifacts as deprecated (no delete)

**User Story:** As a future maintainer, I want the source unit files, the
provisioning script, and the parallel Phase 23 SPOT files (health-check script,
cron file, alternate deployer) kept in tree but clearly marked as deprecated
with runtime guards, so that existing docs and git history stay intact,
rollback is documented, and a re-provision of a new host does not resurrect
the stack.

#### Acceptance Criteria

1. THE `Repo_Unit_File` and `Repo_Unit_Template` SHALL each have a leading
   `# DEPRECATED (Phase 63c, 2026-07-03): …` comment explaining that the
   Gateway_Service supersedes them.
2. THE `Provisioning_Script` SHALL have a leading `# DEPRECATED (Phase 63c,
   2026-07-03): …` comment AND a runtime short-circuit that `exit 0`s unless
   the operator sets `MCP_ALLOW_STATIC_MODE_ROLLBACK=1`. `provision.sh` SHALL
   continue to list the script in its `SCRIPTS` array but with a title that
   makes the retired status visible to `provision.sh --list`.
3. THE parallel Phase 23 SPOT files `SETUP/cron.d/mcp-health`,
   `SETUP/bin/health-check.sh`, and `SETUP/bin/deploy-static-gateway.sh`
   SHALL each carry a leading `# DEPRECATED (Phase 63c, 2026-07-03): …`
   header. The two executable files (`health-check.sh` and
   `deploy-static-gateway.sh`) SHALL additionally short-circuit with `exit 0`
   under the same `MCP_ALLOW_STATIC_MODE_ROLLBACK=1` opt-in as the
   provisioning script.
4. NO files under `SETUP/systemd/`, `SETUP/cron.d/`, `SETUP/bin/`, or
   `SETUP/provisioning/` SHALL be deleted in this phase; retirement follows
   the Phase 63b posture of preserving rollback artifacts.

### Requirement 4: Disable the resurrection cron on the live host

**User Story:** As a platform operator, I want the live-host cron entry that
auto-restarts `mcp-rag.service` disarmed, so that the retirement in Requirement
1 stays retired across the every-five-minute cron interval.

#### Acceptance Criteria

1. THE cron file `/etc/cron.d/mcp-health` SHALL be removed from
   `/etc/cron.d/` so `cron` no longer schedules its `*/5 * * * *`
   invocation. Renaming to a dotted suffix (e.g. `.disabled-phase63c`) is
   INSUFFICIENT on Rocky 9 because `crond` reads dotted files as well;
   deletion is required. Rollback is `sudo cp $REPO/SETUP/cron.d/mcp-health
   /etc/cron.d/` after the repo SPOT DEPRECATED header is stripped.
2. AFTER removal, `sudo systemctl stop mcp-rag.service` SHALL leave
   `mcp-rag.service` inactive across at least two full 5-minute cron windows,
   confirming the cron path was the resurrection vector.

### Requirement 5: CHANGELOG entry

**User Story:** As a reader of `CHANGELOG.md`, I want the retirement recorded
under the current Unreleased block, so that the SPOT changelog stays accurate.

#### Acceptance Criteria

1. `CHANGELOG.md` SHALL gain an `## [Unreleased] - Phase 63c` entry dated
   2026-07-03 that names the retired service, the disarmed cron entry, the
   deprecated repo SPOT files, the preserved image, and the verification
   commands that proved multi-tenant service continues via the Gateway_Service.

## Non-Goals

- Deleting `mcp-rag.service`, `mcp-rag.service.template`,
  `12-static-mode-gateway.sh`, `SETUP/bin/health-check.sh`, or
  `SETUP/bin/deploy-static-gateway.sh` from git.
- Removing the `Node_Image` from the host or from local registries.
- Changing the `mcp-container-cleanup.timer` (v7.1.5, still valid — it reaps
  ephemeral per-session gateway containers, unrelated to the static one).
- Touching AWS AgentCore Runtime deployment or the `aws` DB_BACKEND path.
