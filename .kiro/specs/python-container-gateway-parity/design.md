# Design Document — `python-container-gateway-parity`

## Overview

The two active MCP entry points have drifted. The **Docker MCP Gateway**
(`eib-mcp-gateway`) still ships a stale Node.js image (`global-workflow-unified-mcp`
v3.6.2, 51 tools, 7 modules, single-tenant), while the **stdio server**
(`eib-mcp-rag-full`) runs the current Python server (`MDC MCP/RAG Server` v1.0.0,
53 tools, 9 modules, 5 tenants, plus `code_awareness` + `branch_isolation`).

This feature brings the gateway to parity by **containerizing `mcp_server_python/` as an
x86_64 image** (`eib-mcp-rag-python:latest`) and **repointing the gateway catalog** at it.
Both entry points launch from the same repo on the same Parallel Works form factor; only
the gateway's image is behind. The swap is designed to be **transparent** — the devtunnel
URL, port `18888`, streaming transport, and `.vscode/mcp.json` `eib-mcp-gateway` entry all
remain unchanged. Only the container behind the gateway changes.

An ARM64 Dockerfile already exists at `mcp_server_python/Dockerfile` for AgentCore. This
feature creates the **x86_64 sibling** targeted specifically at the Parallel Works Docker
MCP Gateway.

**Target outcome:** running `get_server_info`, `mcp_health_check(functional=true)`, and
`get_knowledge_base_status` against `eib-mcp-gateway` returns output identical to
`eib-mcp-rag-full` — 53 tools, 9 modules, 5 tenants reachable, 11/11 functional modules
passing.

### Dependency

This feature **depends on Phase 63a** (the backend label rename). Phase 63a establishes
`DB_BACKEND=cots` as the canonical backend label; this feature bakes that default into the
new image and catalog. Phase 63b is blocked on Phase 63a merging first.

### Non-Goals

The following are explicitly out of scope:

- **Do NOT drop the Node.js server (`mcp_server_node/`).** The ingestion pipelines still
  live there; it remains in the tree.
- **The AgentCore container is separate.** It uses `mcp_server_python/Dockerfile` (ARM64,
  port 8000, baked tenant config) — a distinct deployment target that this feature does
  not touch.
- **The backend label rename is Phase 63a**, not this feature. This feature only consumes
  the `cots` label that Phase 63a introduces.

## Architecture

### Why not just reuse `mcp_server_python/Dockerfile`?

The existing Python Dockerfile is purpose-built for AgentCore Runtime and cannot serve the
Docker MCP Gateway unmodified:

- **ARM64-only.** It targets the AgentCore Runtime's ARM64 microVM constraint. Parallel
  Works nodes are **x86_64** — the AgentCore image will not run there.
- **Port `8000`.** Its port and non-root uid pattern are tuned for AgentCore, not the
  Docker MCP Gateway's port **`18888`** convention.
- **Tenant config baked in.** The AgentCore Dockerfile bakes `tenants.yaml` into the image
  and does not mount `tenants.yaml` or `.pw_workflow_mount` from the host. The gateway
  needs those **mounted read-only from the host** so workflow-root reachability probes and
  the tenant catalog resolve against live host state.

Keeping the two Dockerfiles separate lets each deployment target evolve independently. They
share the multi-stage build pattern **by convention, not inheritance** — neither is
derived from the other.

### Container topology

| Aspect | Current gateway | After this feature |
|---|---|---|
| Image | `eib-mcp-rag:latest` | `eib-mcp-rag-python:latest` |
| Base | `node:20-slim` | `python:3.12-slim` |
| Server binary | `src/UnifiedMCPServer.js full` (Node.js) | `mcp_server_python` (Python + FastMCP) |
| Version | v3.6.2 | v1.0.0 (matches stdio server) |
| Tenant support | No | Yes (5 tenants) |
| Port | 18888 (unchanged) | 18888 (unchanged) |
| Transport | Streaming HTTP (unchanged) | Streaming HTTP (unchanged) |

#### Corrected topology (verified 2026-07-03)

The gateway does not connect to an externally-managed static container. It launches its OWN
server container from the Gateway_Catalog (`--enable-all-servers` + `--catalog`), labeled
`docker-mcp-name=eib-mcp-rag`, and that container serves port 18888. Verified live: the gateway
reports the Python build (`MDC MCP/RAG Server` v1.0.0, 53 tools, 9 modules) and the running
container is `eib-mcp-rag-python:latest` carrying the `MCP_WORKFLOW_MOUNT` env from the catalog.

A separate `eib-mcp-rag-static` container exists, launched by the `mcp-rag.service` systemd unit
from the Node_Image. It is **vestigial** — it does not front port 18888 and is not part of this
feature. Do NOT edit `mcp-rag.service` as part of the cutover.

Two systemd units are in play, both `Restart=always`:
- `mcp-gateway.service` — runs `docker-mcp gateway run --catalog ... --port 18888`. Restarting
  it makes the gateway re-read the catalog and relaunch its Python container.
- `mcp-rag.service` — runs the legacy Node static container. Unrelated to this feature.

The devtunnel URL and the `.vscode/mcp.json` `eib-mcp-gateway` entry stay identical across
the swap — only the image, base, and server binary change.

## Components and Interfaces

### 1. New x86_64 Dockerfile — `SETUP/dockerfiles/Dockerfile.mcp-python`

The x86_64 sibling of `mcp_server_python/Dockerfile`, modeled after it but re-targeted at
the Docker MCP Gateway. Reuses the multi-stage pattern and drops the ARM constraint.

**Differences from the AgentCore ARM64 Dockerfile:**

| Aspect | AgentCore Dockerfile | `Dockerfile.mcp-python` (this feature) |
|---|---|---|
| Platform | ARM64 (AgentCore Runtime constraint) | `linux/amd64` (Parallel Works x86_64 nodes) |
| Port | `8000` (AgentCore convention) | `18888` (Docker MCP Gateway convention) |
| Working dir | AgentCore layout | `/app/mcp_server_python` (matches launcher-script module layout) |
| Tenant config | baked into image | mounted read-only from host (via catalog volumes) |

**Environment defaults baked into the image:**

```
DB_BACKEND=cots
CHROMADB_HOST=172.17.0.1
CHROMADB_PORT=8080
NEO4J_URI=bolt://172.17.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=gfsworkflow2025
MCP_TENANT_CATALOG_PATH=/app/mcp_server_python/src/config/tenants.yaml
```

The COTS endpoint block (`172.17.0.1` host-gateway addresses for ChromaDB and Neo4j) is
copied **verbatim** from the current gateway image so the new image connects to the exact
same data-store endpoints — no endpoint drift.

**Build inputs (COPY):**
- `mcp_server_python/pyproject.toml`
- `mcp_server_python/src/`
- `SETUP/mcp-env.sh`

**Entrypoint:** Streaming HTTP transport on port `18888` — the same shape as the ARM64
Dockerfile's entrypoint, differing only in port.

**Produced image:** `eib-mcp-rag-python:latest`.

### 2. Gateway catalog changes — `SETUP/docker-mcp/catalogs/eib-local.yaml`

Repoint the `eib-mcp-gateway` server entry at the new Python image and add the mounts and
env the Python server needs.

**Changes:**
- `image: eib-mcp-rag-python:latest` (was `eib-mcp-rag:latest`)
- Add read-only volume mounts:
  - `/mcp_rag_eib/eib-mcp-rag-server/.pw_workflow_mount:/app/.pw_workflow_mount:ro` —
    required by the tenant catalog for workflow-root reachability probes.
  - `/mcp_rag_eib/eib-mcp-rag-server/mcp_server_python/src/config/tenants.yaml:/app/mcp_server_python/src/config/tenants.yaml:ro` —
    the 5-tenant catalog, mounted rather than baked.
- Add env:
  - `DB_BACKEND: "cots"` (per Phase 63a)
  - `MCP_TENANT_CATALOG_PATH: "/app/mcp_server_python/src/config/tenants.yaml"`
  - `MCP_WORKFLOW_MOUNT: "/app/.pw_workflow_mount"` — repoints the tenant workflow-root
    base at the mounted host directory (see "Tenant workflow-root resolution" below).
- Retain the same DB endpoint ENVs as the current gateway image.

The `.pw_workflow_mount` mount is the load-bearing addition: without it, tenant
workflow-root reachability probes fail inside the container and tenants report as
unreachable.

#### Tenant workflow-root resolution

Each tenant's `workflow_root` is derived in `mcp_server_python/src/config/tenants.py`
as `MCP_WORKFLOW_MOUNT / workflow_subdir`, defaulting to `/mnt/workflow` — the AWS
AgentCore EFS access-point path. The `mcp_health_check` reachability probe then tests
`workflow_root.is_dir()`.

The volume mount alone is therefore inert: mounting the host `.pw_workflow_mount` at
`/app/.pw_workflow_mount` does nothing unless `MCP_WORKFLOW_MOUNT` also points there.
Without the env, the probe resolves against the unmounted `/mnt/workflow` default and
every tenant reports `reachable = no`. The host `.pw_workflow_mount` directory contains
exactly the five `workflow_subdir` entries (`develop`, `dev-sfs`, `dev-jedi-gfs`,
`dev-v17`, `gefs-v12`), so with `MCP_WORKFLOW_MOUNT=/app/.pw_workflow_mount` each
tenant's `workflow_root` resolves to a present directory and the probe passes for all
five tenants.

### 3. Cutover procedure (corrected)

Because the gateway launches its container from the catalog under systemd, the cutover is NOT a
`pkill` + `docker rm -f` sequence — systemd `Restart=always` respawns, and those commands also
target the wrong (vestigial Node) container. The image/env/volume swap is applied by editing the
Gateway_Catalog (Component 2) and then having the gateway re-read it:

```bash
# Baseline
./scripts/manage-devtunnel.sh --status

# Apply catalog changes: restart the gateway unit so it re-reads eib-local.yaml and
# relaunches its Python container from the updated image/env/volumes.
sudo systemctl restart mcp-gateway.service

# Verify by curling the gateway directly (see Testing / Verification Strategy).
```

The `docker mcp gateway run ...` invocation inside the unit is unchanged; only the catalog it
reads changed. Rollback is a one-line catalog edit (`image:` back to `eib-mcp-rag:latest`)
followed by the same `systemctl restart mcp-gateway.service`. The Node_Image is preserved
locally.

## Testing / Verification Strategy

This is infrastructure work (a Dockerfile, a catalog YAML, a cutover, and docs). There are
no algorithmic correctness properties to assert; verification is a **head-to-head parity
diff** between the two live entry points.

### Parity diff

Run the following three tools against **both** `eib-mcp-gateway` (the newly-swapped Python
container) and `eib-mcp-rag-full` (the reference stdio Python server), then diff the
outputs:

| Probe tool | Parameters | Parity assertion |
|---|---|---|
| `get_server_info` | — | `serverInfo.name == "MDC MCP/RAG Server"`; **53 tools / 9 modules** on both |
| `mcp_health_check` | `deep=true, detailed=true, functional=true` | **11/11 functional modules pass** on both, including `code_awareness` and `branch_isolation`; all 5 tenants reachable |
| `get_knowledge_base_status` | — | identical OpenSearch + Neptune counts and tenant table on both |

**Any drift on server name, tool count (53), module list (9), tenant table (5), or the
functional module tally (11/11) is a hard fail.** Zero drift between the gateway and the
stdio server is the pass condition.

### Individual acceptance probes

The parity diff decomposes into eight discrete probes (mapped to requirements R1–R7):

1. **Dockerfile builds** — `docker build -f SETUP/dockerfiles/Dockerfile.mcp-python -t
   eib-mcp-rag-python:latest .` succeeds.
2. **Image serves MCP** — `docker run --rm -p 18888:18888 eib-mcp-rag-python:latest`
   responds to an MCP `initialize`.
3. **Gateway routes to Python** — `curl -H "Auth: ..." https://<tunnel>/mcp initialize`
   returns `serverInfo.name == "MDC MCP/RAG Server"`.
4. **Tool parity** — gateway `get_server_info` reports 53 tools / 9 modules.
5. **Tenant parity** — gateway `mcp_health_check` reports all 5 tenants reachable
   (`gw`, `gw_sfs`, `gw_jedi_gfs`, `gw_v17`, `gw_gefs_v12`).
6. **Functional parity** — gateway `mcp_health_check(functional=true)` returns 11/11
   passed, including `code_awareness` and `branch_isolation`.
7. **Devtunnel URL unchanged** — `.vscode/mcp.json` `eib-mcp-gateway` URL needs no edit;
   `manage-devtunnel.sh --status` reports OK.
8. **CHANGELOG updated** — `[Unreleased]` entry documents the image swap + parity
   verification.

## Documentation Artifacts

| Artifact | Path | Purpose |
|---|---|---|
| x86_64 Dockerfile | `SETUP/dockerfiles/Dockerfile.mcp-python` | Container image for the Docker MCP Gateway |
| Updated gateway catalog | `SETUP/docker-mcp/catalogs/eib-local.yaml` | Points the gateway at the new image + adds tenant volumes |
| CHANGELOG entry | `CHANGELOG.md` | Records the image swap + parity outcome under `[Unreleased]` |
| Docs update | `.github/copilot-instructions.md` | "Docker MCP Gateway" section rebuild workflow reflects the Python image + new Dockerfile paths (replacing the current `mcp_server_node/` paths) |

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Python image has different DB defaults than the Node.js image | Copy the exact `172.17.0.1` endpoint block into the new Dockerfile; smoke-test that it connects to the same endpoints |
| Missing volume mount OR unset `MCP_WORKFLOW_MOUNT` breaks tenant workflow-root probes | Catalog declares both the `.pw_workflow_mount` volume AND `MCP_WORKFLOW_MOUNT=/app/.pw_workflow_mount`; probe 5 asserts all 5 tenants report `reachable = yes` |
| Rebuild forgotten after a future code change (repeat of the Docker snapshot pitfall) | Add a `--rebuild` flag to `scripts/manage-devtunnel.sh` in a follow-up (not blocking this feature) |
| ARM64 vs. x86_64 wheel differences (rare) | Multi-stage build uses `python:3.12-slim` (glibc) on both platforms; wheels resolve at pip-install time |
| Rollback path | The old `eib-mcp-rag:latest` image is preserved locally; catalog rollback is a one-line YAML edit back to the Node image |
