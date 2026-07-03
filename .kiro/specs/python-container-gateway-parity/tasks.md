# Implementation Plan: python-container-gateway-parity

## Overview

Bring the Docker MCP Gateway (`eib-mcp-gateway`) to parity with the stdio server
(`eib-mcp-rag-full`) by containerizing `mcp_server_python/` as an x86_64 image and
repointing the gateway catalog at it. Delivered as the source doc's five-step plan:

- **Step 1** (implement): author `SETUP/dockerfiles/Dockerfile.mcp-python`
- **Step 2** (configure): update the gateway catalog `eib-local.yaml`
- **Step 3** (configure): cutover — stop old gateway/container, build, restart
- **Step 4** (validate): verify parity across both entry points
- **Step 5** (document): CHANGELOG `[Unreleased]` + copilot-instructions

This is infrastructure work (Dockerfile + catalog YAML + cutover + docs), so there are no
property-based tests — verification is the head-to-head parity diff (Step 4). All paths are
relative to the repo root. Depends on **Phase 63a** (backend label rename) merging first.

References:
- Requirements: `.kiro/specs/python-container-gateway-parity/requirements.md` (R1–R8)
- Design: `.kiro/specs/python-container-gateway-parity/design.md`
- Source of record: `sdd_framework/workflows/phase63b_python_container_gateway_parity.md`
- Sibling Dockerfile: `mcp_server_python/Dockerfile` (ARM64, AgentCore)

## Tasks

### Step 1 — Author the x86_64 Dockerfile (tag: implement)

- [ ] 1. Author `SETUP/dockerfiles/Dockerfile.mcp-python`
  - New file, modeled after `mcp_server_python/Dockerfile`, reusing the multi-stage pattern
    and dropping the ARM constraint
  - Target `linux/amd64`; expose/serve MCP on port `18888`; set workdir `/app/mcp_server_python`
  - Bake env defaults: `DB_BACKEND=cots`, the verbatim COTS endpoint block
    (`CHROMADB_HOST=172.17.0.1`, `CHROMADB_PORT=8080`, `NEO4J_URI=bolt://172.17.0.1:7687`,
    `NEO4J_USER=neo4j`, `NEO4J_PASSWORD=gfsworkflow2025`), and
    `MCP_TENANT_CATALOG_PATH=/app/mcp_server_python/src/config/tenants.yaml`
  - COPY `mcp_server_python/pyproject.toml`, `mcp_server_python/src/`, `SETUP/mcp-env.sh`
  - Entrypoint: streaming HTTP transport on `18888` (same shape as the ARM64 Dockerfile)
  - **Implements: R1.1, R1.2, R1.3, R1.4, R1.5, R1.6, R1.7**

  - [ ] 1.1 Build smoke test
    - Run `docker build -f SETUP/dockerfiles/Dockerfile.mcp-python -t eib-mcp-rag-python:latest .`
      and confirm it succeeds, producing `eib-mcp-rag-python:latest`
    - Run `docker run --rm -p 18888:18888 eib-mcp-rag-python:latest` and confirm it responds
      to an MCP `initialize` request
    - **Implements: R1.8, R1.9**

### Step 2 — Update the gateway catalog (tag: configure)

- [ ] 2. Update `SETUP/docker-mcp/catalogs/eib-local.yaml`
  - Set the gateway server image to `eib-mcp-rag-python:latest`
  - Add read-only volume mounts:
    - `/mcp_rag_eib/eib-mcp-rag-server/.pw_workflow_mount:/app/.pw_workflow_mount:ro`
    - `/mcp_rag_eib/eib-mcp-rag-server/mcp_server_python/src/config/tenants.yaml:/app/mcp_server_python/src/config/tenants.yaml:ro`
  - Add env: `DB_BACKEND: "cots"` and
    `MCP_TENANT_CATALOG_PATH: "/app/mcp_server_python/src/config/tenants.yaml"`
  - Retain the same DB endpoint ENVs as the current gateway image
  - **Implements: R2.1, R2.2, R2.3, R2.4, R2.5, R2.6**

### Step 3 — Cutover (tag: configure — GATED operator step)

- [ ] 3. Perform the transparent cutover
  - STOP-AND-CONFIRM: this stops the running gateway and removes the live container
  - Baseline: `./scripts/manage-devtunnel.sh --status`
  - Stop old gateway + old container:
    `pkill -f "docker-mcp gateway"` then
    `docker rm -f $(docker ps -aq --filter "label=docker-mcp-name=eib-mcp-rag")`
  - Build new image:
    `docker build -f SETUP/dockerfiles/Dockerfile.mcp-python -t eib-mcp-rag-python:latest .`
  - Restart the gateway with the **unchanged** run command:
    `docker mcp gateway run --catalog SETUP/docker-mcp/catalogs/eib-local.yaml
    --enable-all-servers --transport streaming --port 18888 --long-lived &`
  - Do NOT edit `.vscode/mcp.json`; do NOT change the port or transport; preserve the
    `eib-mcp-rag:latest` Node_Image locally as the rollback target
  - **Implements: R3.1, R3.2, R3.3, R3.4, R3.5, R8.1, R8.2**

  - [ ] 3.1 Confirm devtunnel unchanged
    - Run `scripts/manage-devtunnel.sh --status`; confirm OK and that the tunnel URL is
      unchanged from the baseline
    - **Implements: R3.6**

### Step 4 — Verify parity (tag: validate)

- [ ] 4. Verify tool and module parity
  - Call `get_server_info` against `eib-mcp-gateway`; assert
    `serverInfo.name == "MDC MCP/RAG Server"`, 53 tools, 9 modules
  - Diff against `eib-mcp-rag-full`; counts must match
  - **Implements: R4.1, R4.2, R4.3, R4.4**

- [ ] 5. Verify tenant parity
  - Call `mcp_health_check` against `eib-mcp-gateway`; assert all 5 tenants
    (`gw`, `gw_sfs`, `gw_jedi_gfs`, `gw_v17`, `gw_gefs_v12`) reachable
  - Confirm the `.pw_workflow_mount` mount is present inside the container
  - **Implements: R5.1, R5.2**

- [ ] 6. Verify functional parity + zero drift
  - Call `mcp_health_check(deep=true, detailed=true, functional=true)` against
    `eib-mcp-gateway`; assert 11/11 modules pass, including `code_awareness` and
    `branch_isolation`
  - Run `get_server_info`, `mcp_health_check(deep,detailed,functional)`, and
    `get_knowledge_base_status` against **both** `eib-mcp-gateway` and `eib-mcp-rag-full`;
    diff the outputs — any drift on server name, tool count, module list, or tenant table
    is a hard fail
  - **Implements: R6.1, R6.2, R6.3, R6.4**

- [ ] 7. Parity checkpoint
  - Ensure all parity probes pass and outputs are drift-free; ask the user if questions arise

### Step 5 — Documentation (tag: document)

- [ ] 8. Update CHANGELOG
  - Add an `[Unreleased]` entry documenting the gateway image swap (Node.js
    `eib-mcp-rag:latest` → Python `eib-mcp-rag-python:latest`) and the parity verification
  - **Implements: R7.1**

- [ ] 9. Update copilot-instructions
  - Update the `.github/copilot-instructions.md` "Docker MCP Gateway" section's rebuild
    workflow to reference the Python_MCP_Image and `SETUP/dockerfiles/Dockerfile.mcp-python`,
    replacing the current `mcp_server_node/` paths
  - **Implements: R7.2**

## Notes

- **Step 1 is the only pure authoring task** — the Dockerfile is the linchpin artifact.
  Get the platform (`linux/amd64`), port (`18888`), and the verbatim COTS endpoint block
  right so the image connects to the same data stores as the Node image.
- **Step 3 is a gated operator action** — it stops the live gateway. The run command is
  unchanged; only the catalog (edited in Step 2) now points at the Python image.
- **The `.pw_workflow_mount` mount is load-bearing** — without it, tenant workflow-root
  reachability probes fail and Step 5 (tenant parity) will not pass.
- **Rollback is a one-line catalog edit** back to `eib-mcp-rag:latest`, which is preserved
  locally — no rebuild required to revert.
- **Blocked on Phase 63a** — the `DB_BACKEND=cots` default this feature bakes in comes from
  the Phase 63a backend rename.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["1.1"] },
    { "id": 2, "tasks": ["2"] },
    { "id": 3, "tasks": ["3"] },
    { "id": 4, "tasks": ["3.1"] },
    { "id": 5, "tasks": ["4", "5", "6"] },
    { "id": 6, "tasks": ["7"] },
    { "id": 7, "tasks": ["8", "9"] }
  ]
}
```
