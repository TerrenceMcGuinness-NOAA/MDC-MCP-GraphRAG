# Phase 63b — Python MCP Container Parity for Docker MCP Gateway

**Version**: 1.0.0
**Created**: 2026-07-02
**Status**: ready (blocked on Phase 63a merge)
**Estimated effort**: 1–2 days
**Depends on**: Phase 63a (backend label rename), Phase 46 (aws-infrastructure-port)
**Split from**: original Phase 63 (container + rename). Rename portion is Phase 63a.

---

## 1. Executive Summary

Head-to-head health checks between the two active MCP entry points expose a large drift:

| | Docker MCP Gateway (`eib-mcp-gateway`) | Stdio server (`eib-mcp-rag-full`) |
|---|---|---|
| Server binary | `global-workflow-unified-mcp` v3.6.2 (Node.js, `mcp_server_node/`) | `MDC MCP/RAG Server` v1.0.0 (Python, `mcp_server_python/`) |
| Tools | 51 | 53 |
| Modules | 7 | 9 |
| Multi-tenant | No | Yes (5 tenants) |
| Extra modules | — | `code_awareness`, `branch_isolation` |

Both entry points are launched from the same repo on the same Parallel Works form factor, but the gateway ships a stale Node.js image. This phase brings the gateway to parity by containerizing `mcp_server_python/` and repointing the gateway catalog at the new image. Devtunnel URL, port 18888, and `.vscode/mcp.json` all remain unchanged — the swap is transparent.

An ARM64 Dockerfile already exists at [mcp_server_python/Dockerfile](../../mcp_server_python/Dockerfile) for AgentCore. This phase creates the x86_64 sibling for the Parallel Works Docker MCP Gateway.

---

## 2. Scope

### 2.1 In Scope

- **New Dockerfile** `SETUP/dockerfiles/Dockerfile.mcp-python` — x86_64 sibling of `mcp_server_python/Dockerfile`. Reuses the multi-stage pattern; drops the ARM constraint; targets the Docker MCP Gateway (not AgentCore).
- Produce image `eib-mcp-rag-python:latest`.
- Update [SETUP/docker-mcp/catalogs/eib-local.yaml](../../SETUP/docker-mcp/catalogs/eib-local.yaml) to point at the new image with:
  - Volume mount for `.pw_workflow_mount` (needed by tenant catalog for workflow-root reachability probes)
  - `MCP_TENANT_CATALOG_PATH` env var
  - `DB_BACKEND=cots` (per Phase 63a) default
  - Same DB endpoint ENVs as current gateway image
- Cutover verification: `mcp_health_check(functional=true)` on both entry points returns identical output (53 tools, 9 modules, 5 tenants, 11/11 modules pass).
- CHANGELOG entry documenting gateway image swap.
- `.github/copilot-instructions.md` "Docker MCP Gateway" section updated to reference the Python image and correct rebuild workflow.

### 2.2 Out of Scope

- Dropping the Node.js server (`mcp_server_node/`) — ingestion pipelines still live there.
- AgentCore container (uses `mcp_server_python/Dockerfile` — separate deployment target).
- Backend label rename — covered by Phase 63a (this phase depends on it).

---

## 3. Acceptance Criteria

| # | Probe | Pass condition |
|---|-------|----------------|
| 1 | Dockerfile builds | `docker build -f SETUP/dockerfiles/Dockerfile.mcp-python -t eib-mcp-rag-python:latest .` succeeds |
| 2 | Image serves MCP | `docker run --rm -p 18888:18888 eib-mcp-rag-python:latest` responds to MCP initialize |
| 3 | Gateway routes to Python | `curl -H "Auth: ..." https://<tunnel>/mcp initialize` returns `serverInfo.name == "MDC MCP/RAG Server"` |
| 4 | Tool parity | Gateway `get_server_info` reports **53 tools / 9 modules** matching `eib-mcp-rag-full` |
| 5 | Tenant parity | Gateway `mcp_health_check` reports all 5 tenants reachable (`gw`, `gw_sfs`, `gw_jedi_gfs`, `gw_v17`, `gw_gefs_v12`) |
| 6 | Functional parity | Gateway `mcp_health_check(functional=true)` returns **11/11 passed** including `code_awareness` and `branch_isolation` |
| 7 | Devtunnel URL unchanged | `.vscode/mcp.json` `eib-mcp-gateway` URL requires no edit; `manage-devtunnel.sh --status` reports OK |
| 8 | CHANGELOG updated | `[Unreleased]` entry documents image swap + parity verification |

---

## 4. Implementation Plan

### Step 1 — Author `SETUP/dockerfiles/Dockerfile.mcp-python`

Model after [mcp_server_python/Dockerfile](../../mcp_server_python/Dockerfile). Differences:

- **Platform**: `linux/amd64` (Parallel Works nodes are x86_64) instead of ARM64.
- **Port**: `18888` (Docker MCP Gateway convention) instead of `8000`.
- **Working dir**: `/app/mcp_server_python` to match the module layout expected by launcher scripts.
- **Env defaults**: `DB_BACKEND=cots`, `CHROMADB_HOST=172.17.0.1`, `CHROMADB_PORT=8080`, `NEO4J_URI=bolt://172.17.0.1:7687`, `NEO4J_USER=neo4j`, `NEO4J_PASSWORD=gfsworkflow2025`, `MCP_TENANT_CATALOG_PATH=/app/mcp_server_python/src/config/tenants.yaml`.
- **Copy**: `mcp_server_python/pyproject.toml`, `mcp_server_python/src/`, `SETUP/mcp-env.sh`.
- **Entrypoint**: Streaming HTTP transport — same shape as the ARM64 Dockerfile.

Tag: `implement`.

### Step 2 — Update the gateway catalog

Edit [SETUP/docker-mcp/catalogs/eib-local.yaml](../../SETUP/docker-mcp/catalogs/eib-local.yaml):

- `image: eib-mcp-rag-python:latest`
- Add volumes:
  - `/mcp_rag_eib/eib-mcp-rag-server/.pw_workflow_mount:/app/.pw_workflow_mount:ro`
  - `/mcp_rag_eib/eib-mcp-rag-server/mcp_server_python/src/config/tenants.yaml:/app/mcp_server_python/src/config/tenants.yaml:ro`
- Add env: `DB_BACKEND: "cots"`, `MCP_TENANT_CATALOG_PATH: "/app/mcp_server_python/src/config/tenants.yaml"`.

Tag: `configure`.

### Step 3 — Cutover

```bash
# Baseline
./scripts/manage-devtunnel.sh --status

# Stop old gateway + old container
pkill -f "docker-mcp gateway"
docker rm -f $(docker ps -aq --filter "label=docker-mcp-name=eib-mcp-rag")

# Build new image
docker build -f SETUP/dockerfiles/Dockerfile.mcp-python \
  -t eib-mcp-rag-python:latest .

# Restart gateway (command unchanged)
MCP_GATEWAY_AUTH_TOKEN="..." docker mcp gateway run \
  --catalog SETUP/docker-mcp/catalogs/eib-local.yaml \
  --enable-all-servers --transport streaming --port 18888 --long-lived &
```

Tag: `configure`.

### Step 4 — Verify parity

Run `get_server_info`, `mcp_health_check(deep=true, detailed=true, functional=true)`, and `get_knowledge_base_status` against **both** `eib-mcp-gateway` and `eib-mcp-rag-full`. Diff the outputs. Any drift on server name, tool count, module list, or tenant table is a fail.

Tag: `validate`.

### Step 5 — CHANGELOG + docs

- Add `[Unreleased]` entry documenting the image swap and parity verification.
- Update `.github/copilot-instructions.md` — replace the current "Docker MCP Gateway" section's rebuild table (which lists `mcp_server_node/` paths) with the Python-server paths and the new Dockerfile.

Tag: `document`.

---

## 5. Design & Architecture

### 5.1 Why not just reuse `mcp_server_python/Dockerfile`?

- The existing Dockerfile is **ARM64-only** (AgentCore Runtime constraint).
- Its port (`8000`) and non-root uid pattern are tuned for AgentCore, not the Docker MCP Gateway's port `18888` convention.
- The AgentCore Dockerfile does not mount `tenants.yaml` or `.pw_workflow_mount` from host — it bakes tenant config into the image.

Keeping them separate lets each deployment target evolve independently. The two Dockerfiles share the multi-stage pattern via convention, not inheritance.

### 5.2 Container topology

| Aspect | Current gateway | After Phase 63b |
|---|---|---|
| Image | `eib-mcp-rag:latest` | `eib-mcp-rag-python:latest` |
| Base | `node:20-slim` | `python:3.12-slim` |
| Server binary | `src/UnifiedMCPServer.js full` (Node.js) | `mcp_server_python` (Python + FastMCP) |
| Version | v3.6.2 | v1.0.0 (matches stdio server) |
| Tenant support | No | Yes (5 tenants) |
| Port | 18888 (unchanged) | 18888 (unchanged) |
| Transport | Streaming HTTP (unchanged) | Streaming HTTP (unchanged) |

Devtunnel URL and `.vscode/mcp.json` `eib-mcp-gateway` entry stay identical.

---

## 6. Artifacts Produced

| Artifact | Path | Purpose |
|---|---|---|
| x86_64 Dockerfile | `SETUP/dockerfiles/Dockerfile.mcp-python` | Container image for Docker MCP Gateway |
| Updated gateway catalog | `SETUP/docker-mcp/catalogs/eib-local.yaml` | Points gateway at new image + adds tenant volumes |
| CHANGELOG entry | `CHANGELOG.md` | Records image swap + parity outcome |
| Docs update | `.github/copilot-instructions.md` | Rebuild workflow reflects Python image |

---

## 7. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Python image has different DB defaults than the Node.js image | Copy the exact 172.17.0.1 endpoint block into the new Dockerfile; smoke-test connects to same endpoints |
| Missing volume mounts break tenant workflow-root probes inside the container | Explicit `.pw_workflow_mount` mount in catalog; AC 5 asserts all 5 tenants report `reachable` |
| Rebuild forgotten after future code change (repeat of Docker snapshot pitfall) | Add `--rebuild` flag to `scripts/manage-devtunnel.sh` in a follow-up (not blocking this phase) |
| ARM64 vs. x86_64 wheel differences (rare) | Multi-stage build uses `python:3.12-slim` (glibc) on both platforms; wheels resolve at pip-install time |
| Rollback path | Old `eib-mcp-rag:latest` image is preserved locally; catalog rollback is a one-line YAML edit |
