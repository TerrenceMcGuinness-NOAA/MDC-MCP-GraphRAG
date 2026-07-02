# Phase 63b — Python MCP Container Parity for Docker MCP Gateway

**Version**: 2.0.0
**Created**: 2026-07-02
**Revised**: 2026-07-02 — v2 folds in the v1 execution retrospective (defect register D1–D5)
**Status**: ready (v1 session abandoned; v1 artifacts retained for in-place rework)
**Estimated effort**: 0.5–1 day (Steps 1–2 scaffolding exists; rework + cutover + verify)
**Depends on**: Phase 63a (backend label rename), Phase 61 (`MCP_WORKFLOW_MOUNT`), Phase 46 (aws-infrastructure-port)
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

## 1.1 v1 Execution Retrospective & Defect Register (2026-07-02)

The first execution attempt (session `session_2026-07-02_x21txl`, driven by the
Copilot CLI running `gemini-3.1-pro-preview`) recorded Steps 1–2, partially
performed the cutover, and stalled. The rebuilt gateway achieved
**tool-surface parity** (53 tools / 9 modules / 5 tenants on both entry
points) but failed **runtime parity**. Verified head-to-head results:

| Probe | eib-mcp-rag-full (stdio) | eib-mcp-gateway (v1 container) |
|---|---|---|
| `mcp_health_check` overall | HEALTHY (4/4) | DEGRADED (2/4) |
| Functional validation | 11/11 pass | 3/11 pass, 7 fail, 1 skip |
| Tenants reachable | 5/5 | 0/5 (`/mnt/workflow` NOT mounted) |
| Vector/Graph adapters | healthy | "adapter is not configured" |
| `github_tools` probe | pass | SKIP (no token) |
| `get_knowledge_base_status` | full report (15 collections / 220,538 docs) | empty header only |

The v1 session was abandoned and the phase reset for this v2 spec. **Retained
artifacts** — [SETUP/dockerfiles/Dockerfile.mcp-python](../../SETUP/dockerfiles/Dockerfile.mcp-python)
and the edits to [SETUP/docker-mcp/catalogs/eib-local.yaml](../../SETUP/docker-mcp/catalogs/eib-local.yaml) —
are sound scaffolding but carry the defects below. **Rework them in place; do
not start from scratch.**

### Defect Register

| ID | Bug condition C(X) | Root cause | Fix location |
|----|--------------------|------------|--------------|
| **D1** | Container resolves every tenant `workflow_root` under `/mnt/workflow`, which does not exist in the image; all 5 tenants report `reachable: no` | `MCP_WORKFLOW_MOUNT` (Phase 61) is exported by `run_mcp_stdio.sh` for native launches but is absent from both the Dockerfile ENV block and the catalog env list, so `src/config/tenants.py` falls back to the AgentCore default `/mnt/workflow` | Dockerfile ENV + catalog env (Steps 1–2) |
| **D2** | Even with D1 fixed, every `.pw_workflow_mount/*` entry dangles inside the container | The host symlink farm targets absolute host paths (`/mcp_rag_eib/eib-mcp-rag-server/supported_repos/...`) that do not exist in the container mount namespace; bind-mounting the farm `:ro` transports the dangling links | Entrypoint wrapper regenerates the farm in-container against `/app/supported_repos` (Step 1); remove the host farm volume (Step 2) |
| **D3** | Server can come up on stdio instead of Streamable HTTP | v1 Dockerfile sets `MCP_TRANSPORT=stdio`, contradicting its own "Streamable HTTP entrypoint" comment. Valid values per `src/mcp_server.py` (CLI flag → `MCP_TRANSPORT` env → default): `stdio` \| `streamable-http` | Dockerfile ENV (Step 1) |
| **D4** | Running gateway container reports `vector_db`/`graph_db` "adapter is not configured" despite `DB_BACKEND=cots` present in the edited catalog | Gateway was restarted before/without the catalog edits (or from the stale `~/.docker/mcp/` copy), so the running container never received the DB env block | Cutover runbook pins the canonical absolute catalog path (Step 3) |
| **D5** | `github_tools` functional probe SKIPs with "no GitHub token available" | `GITHUB_TOKEN: "${GITHUB_TOKEN}"` in the catalog only expands if the variable is exported in the shell that launches `docker mcp gateway run`; it was not | Cutover runbook exports the token (or `docker mcp secret set`) before `gateway run` (Step 3) |

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
| 9 | Workflow mount resolves in-container (D1+D2) | Gateway `mcp_health_check` "Workflow Filesystem" reports `/app/.pw_workflow_mount` mounted with all 5 subdirectories; all 5 tenants `reachable: yes` |
| 10 | Streamable HTTP transport (D3) | Container ENV pins `MCP_TRANSPORT=streamable-http`; MCP initialize over HTTP succeeds |
| 11 | GitHub token passthrough (D5) | Gateway functional table reports `github_tools` **pass** (not SKIP) |

---

## 4. Implementation Plan (v2 — post-retrospective)

Session tracking: `start_sdd_session(phase="phase63b_python_container_gateway_parity", total_steps=5)`.
Record each step with `record_sdd_step` using the tag shown. **Do not record a
step whose hard gates have not been verified.** v1 artifacts are retained and
reworked in place.

### Step 1 — Rework `SETUP/dockerfiles/Dockerfile.mcp-python` (fixes D1, D2, D3)

The v1 file exists and is structurally correct (amd64 multi-stage, port 18888,
non-root `app` user, cots DB env block, 10-module CMD incl. `error_analysis`).
Apply these fixes:

1. **D3**: change `MCP_TRANSPORT=stdio` → `MCP_TRANSPORT=streamable-http`
   (valid values per `src/mcp_server.py`: `stdio` | `streamable-http`; the
   default is already `streamable-http`, so the explicit value is for Docker
   history legibility — `stdio` is flatly wrong).
2. **D1**: add `MCP_WORKFLOW_MOUNT=/app/.pw_workflow_mount` to the ENV block.
3. **D2**: add an entrypoint wrapper `SETUP/dockerfiles/docker-entrypoint.mcp-python.sh`
   (COPY'd into the image, `chmod +x`) that:
   - regenerates the workflow symlink farm **inside the container namespace**
     by invoking `mcp_server_python/scripts/setup_pw_workflow_mount.sh` with
     `REPO_ROOT=/app` and `MCP_WORKFLOW_MOUNT=/app/.pw_workflow_mount`, so
     links target the volume-mounted `/app/supported_repos/...` (the host
     farm's absolute-path symlinks dangle in the container — never mount it);
   - preserves the script's non-fatal warn behaviour for missing checkouts;
   - `exec`s the CMD (`python -m src.mcp_server --modules ...`).
4. Keep everything else byte-compatible with v1 (module list, wheels build,
   sdd_framework seed, non-root ownership).

**Hard gate**: `docker build` succeeds; `docker run --rm` + MCP initialize
over HTTP on 18888 returns `serverInfo.name == "MDC MCP/RAG Server"`.

Tag: `implement`.

### Step 2 — Rework the gateway catalog (fixes D1, D2, D5)

Edit [SETUP/docker-mcp/catalogs/eib-local.yaml](../../SETUP/docker-mcp/catalogs/eib-local.yaml) (v1 edits retained):

1. **D1**: add env `MCP_WORKFLOW_MOUNT: "/app/.pw_workflow_mount"`.
2. **D2**: if v1 added a volume bind-mounting the host `.pw_workflow_mount`,
   **remove it** — the entrypoint wrapper builds the farm in-container. Keep
   `supported_repos:/app/supported_repos:ro`.
3. **D5**: keep `GITHUB_TOKEN: "${GITHUB_TOKEN}"`; the cutover runbook
   (Step 3) is responsible for exporting it in the gateway's launch shell.
4. Keep from v1: `image: eib-mcp-rag-python:latest`, `DB_BACKEND: "cots"`,
   `MCP_TENANT_CATALOG_PATH`, the `tenants.yaml` `:ro` mount, and the
   `sdd_framework:/app/mcp_server_python/sdd_framework:rw` remap.

Tag: `configure`.

### Step 3 — Rebuild image and cutover (fixes D4, D5)

```bash
# Preconditions
./scripts/manage-devtunnel.sh --status          # baseline OK
export GITHUB_TOKEN="<pat>"                     # D5 — required for AC 11

# Rebuild (context = repo root; Dockerfile COPYs mcp_server_python/* and SETUP/*)
docker build -f SETUP/dockerfiles/Dockerfile.mcp-python \
  -t eib-mcp-rag-python:latest .

# Stop old gateway + containers
pkill -f "docker-mcp gateway"
docker rm -f $(docker ps -aq --filter "label=docker-mcp-name=eib-mcp-rag")

# Restart against the CANONICAL catalog — absolute path, never the
# ~/.docker/mcp/ copy (D4)
MCP_GATEWAY_AUTH_TOKEN="eib-mcp-gateway-token-2025" docker mcp gateway run \
  --catalog /mcp_rag_eib/eib-mcp-rag-server/SETUP/docker-mcp/catalogs/eib-local.yaml \
  --servers eib-mcp-rag --transport streaming --port 18888 --long-lived &
```

**Hard gate**: `docker inspect` on the spawned container shows the D1/D3 env
vars and NO host `.pw_workflow_mount` bind; devtunnel URL unchanged.

Tag: `configure`.

### Step 4 — Verify parity (AC 1–11)

Run the identical suite against **both** `eib-mcp-gateway` and
`eib-mcp-rag-full` and diff:

- `get_server_info(include_capabilities=true)`
- `mcp_health_check(deep=true, detailed=true, functional=true)`
- `get_knowledge_base_status()`

**Hard gates** (any miss = step fails; fix and re-run, do not record):

- Gateway overall **HEALTHY (4/4)** — vector + graph adapters healthy (D4 closed).
- Functional table **11/11 passed** incl. `code_awareness` and
  `branch_isolation`; `github_tools` **pass**, not SKIP (D5 closed).
- All 5 tenants `workflow_root reachable: yes` under
  `/app/.pw_workflow_mount/<subdir>` (D1+D2 closed).
- `get_knowledge_base_status` returns the populated report matching stdio
  (15 collections / 220,538 docs; Neo4j node/relationship counts equal).

Tag: `validate`.

### Step 5 — CHANGELOG + docs

- `CHANGELOG.md` `[Unreleased]`: Phase 63b entry — image swap, defect fixes
  D1–D5, parity verification results.
- `.github/copilot-instructions.md` "Docker MCP Gateway" section: replace the
  Node.js rebuild table (`mcp_server_node/` paths) with `mcp_server_python/`
  paths, the new Dockerfile, and the canonical catalog invocation from Step 3.
- `complete_sdd_session(summary=...)` — only after Steps 1–5 are all recorded.

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
| x86_64 Dockerfile | `SETUP/dockerfiles/Dockerfile.mcp-python` | Container image for Docker MCP Gateway (v1 exists — rework per D1/D2/D3) |
| Entrypoint wrapper | `SETUP/dockerfiles/docker-entrypoint.mcp-python.sh` | Regenerates workflow symlink farm in-container, then execs server (D2) |
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
| Host symlink farm dangles inside container (D2 — bit v1) | Entrypoint wrapper regenerates the farm in-container against `/app/supported_repos`; never bind-mount the host `.pw_workflow_mount` |
| Gateway launched with stale catalog (D4 — bit v1) | Runbook pins the absolute canonical catalog path; hard gate inspects the spawned container's env before verification |
| Env vars silently defaulting (D1/D3 — bit v1) | AC 9/10 assert `MCP_WORKFLOW_MOUNT` and `MCP_TRANSPORT` explicitly; `docker inspect` gate in Step 3 |
| Rollback path | Old `eib-mcp-rag:latest` image is preserved locally; catalog rollback is a one-line YAML edit |
