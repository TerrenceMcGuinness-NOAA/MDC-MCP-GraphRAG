# Phase 14: GitLab Pipelines + Self-hosted Runners + Containerized MCP Testing

## Description

Convert the modular provisioning system under `SETUP/provisioning/` into GitLab CI/CD pipelines executed by self-hosted GitLab runners installed on the target VMs. Then implement and validate the **next task**: running and testing a containerized version of the MCP server (the `eib-mcp-rag` container) against the containerized dependencies (ChromaDB + Neo4j).

This phase intentionally builds on (and does not replace) the existing modular provisioning work:
- Phase 13 made host setup reproducible via provisioning scripts.
- Phase 11/12 established the containerization and Docker MCP Gateway direction.

## Goals

1. **Pipeline-driven host bootstrap**
   - GitLab pipelines can invoke `SETUP/bootstrap.sh` / `SETUP/provisioning/provision.sh` on a clean VM runner and reach a known-good host state.

2. **Runner-on-VM architecture**
   - CI/CD jobs run directly on the VM via a self-hosted runner (shell executor), so they can:
     - modify `/etc`
     - control `systemctl`
     - manage Docker and volumes

3. **Containerized MCP smoke test**
   - A pipeline job can bring up the container stack using the repo’s compose files (devops/staging/production variants exist) and run a deterministic validation sequence.

## Non-goals

- Full production hardening (certs, HA, advanced monitoring). Those remain Phase 12/Production readiness items.
- Re-ingestion or large data rebuild unless required by the chosen ChromaDB remediation path.

## Current Inputs / Evidence

- Modular provisioning exists and is orchestrated via `SETUP/provisioning/provision.sh`.
- Compose files already exist at repo root:
  - `docker-compose.devops.yaml`
  - `docker-compose.staging.yaml`
  - `docker-compose.production.yaml`
- The container test target is the MCP server container described in Phase 11/12 as `eib-mcp-rag`.

## Work Breakdown

### 14A. Runner architecture and registration

**Objective**: Install and register a GitLab runner on each VM.

Steps:
1. Decide executor type:
   - Recommended for this repo: **shell executor** on the VM.
   - Alternative: docker executor, but it complicates privileged ops and nested Docker.
2. Install `gitlab-runner` and register it with tags, e.g. `vm`, `docker`, `privileged`.
3. Ensure runner user permissions:
   - member of `docker` group
   - passwordless sudo for the subset of commands needed by provisioning (or run runner as root if approved by ops policy)
4. Validate runner can execute:
   - `docker ps`
   - `sudo SETUP/provisioning/provision.sh --list`

Validation:
- A test pipeline can run a “hello runner” job and a “docker ok” job.

---

### 14B. Map modular provisioning to pipeline stages

**Objective**: Treat provisioning steps as CI jobs (or job groups), without losing idempotency.

Steps:
1. Define a pipeline stage layout:
   - `prep` (checkout, env)
   - `host_provision` (runs modular provisioning)
   - `container_stack` (docker compose up/down)
   - `verify` (smoke tests)
2. Define a minimal “cold boot” job that runs provisioning:
   - `sudo SETUP/bootstrap.sh` (or targeted `provision.sh --only <step>` during iteration)
3. Decide job granularity:
   - Option 1: one job for entire provisioning (fast path)
   - Option 2: separate jobs per step number (e.g., `00`, `09`, `10`) for faster feedback
4. Capture logs and artifacts:
   - provisioning logs
   - service statuses
   - docker compose logs

Validation:
- A pipeline run is repeatable (second run is no-op or minimal change).

---

### 14C. Containerized MCP bring-up job (devops mode)

**Objective**: Start the full container stack on the runner VM using the devops compose file.

Steps:
1. Use `docker compose -f docker-compose.devops.yaml up -d` (or the repo-defined equivalent).
2. Wait for dependencies:
   - ChromaDB heartbeat responds
   - Neo4j is reachable
3. Start/verify MCP container (`eib-mcp-rag`) is running.
4. Collect logs for all three services.

Validation:
- `docker ps` shows the expected containers.
- `curl` health checks pass for DB services.

---

### 14D. Containerized MCP smoke tests (the “next task”)

**Objective**: Verify the containerized MCP server can perform a minimal, repeatable set of operations.

Planned smoke test assertions (minimum viable):
1. **Server starts cleanly**
   - container exits are zero
   - logs show successful tool registration
2. **Dependency connectivity**
   - MCP connects to Neo4j (bolt)
   - MCP connects to ChromaDB using the correct v2 API
3. **Minimal tool invocation**
   - Execute a deterministic tool call that does not require external credentials (e.g., knowledge base status, workflow structure).

Implementation options for tool invocation:
- Option A (preferred): a small Node test harness executed in CI that imports the MCP tool modules or hits a test endpoint if present.
- Option B: run the MCP server in a test mode that exposes a local HTTP health endpoint for CI only.

Validation:
- Pipeline emits a concise report with: container versions, tool availability, DB heartbeat, and pass/fail status.

## Deliverables

- Self-hosted GitLab runner registration documented (runbook + required permissions).
- GitLab pipeline definition mapping host provisioning + container stack + smoke tests.
- Containerized MCP smoke test job that runs in CI on VM runners.

## Risks / Open Decisions

- Runner privileges: shell executor + sudo requirements must be approved.
- Secrets handling: GitHub token and registry auth must be stored as GitLab CI protected variables.
- ChromaDB data compatibility: if devops uses Docker ChromaDB, it must be the version consistent with the data strategy defined in Phase 12.

## Success Criteria

- [ ] A pipeline run on a clean VM runner can:
  - [ ] run modular provisioning to completion
  - [ ] start the devops container stack
  - [ ] run containerized MCP smoke tests
  - [ ] publish logs/artifacts
- [ ] The smoke tests are deterministic (no manual clicks, no interactive prompts).

## Next Steps (Immediate)

1. Draft the pipeline design and runner setup runbook.
2. Implement the first pipeline job that runs `SETUP/provisioning/provision.sh --list` and a minimal `--only` step.
3. Add the container bring-up + smoke test job using `docker-compose.devops.yaml`.
