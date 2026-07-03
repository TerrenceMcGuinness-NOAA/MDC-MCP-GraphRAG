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

> **Recovery status (2026-07-03):** The prior CLI could not update this file after being restarted. Ground-truth reconciliation against the live system: Steps 1–2 are complete (image `eib-mcp-rag-python:latest` built, catalog carries R2.1–2.5+2.7), Step 3 cutover is complete under the new systemd model (see task 3 note), Step 3.1 holds (devtunnel URL unchanged — clients still connect at `blp11zs1-18888.use.devtunnels.ms/mcp`), and tool/module parity (Task 4) was verified per the note in `requirements.md`. Two gaps remain: R5.4 relative symlinks (Task 5.1 new) and R9 COTS adapter wiring (Task 6.1 new). Docs (Tasks 8–9) untouched.

### Step 1 — Author the x86_64 Dockerfile (tag: implement)

- [x] 1. Author `SETUP/dockerfiles/Dockerfile.mcp-python`
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

  - [x] 1.1 Build smoke test
    - Run `docker build -f SETUP/dockerfiles/Dockerfile.mcp-python -t eib-mcp-rag-python:latest .`
      and confirm it succeeds, producing `eib-mcp-rag-python:latest`
    - Run `docker run --rm -p 18888:18888 eib-mcp-rag-python:latest` and confirm it responds
      to an MCP `initialize` request
    - **Verified 2026-07-03**: `docker images` shows `eib-mcp-rag-python:latest` (691MB); gateway serves 53 tools / 9 modules on 18888 per `requirements.md` note
    - **Implements: R1.8, R1.9**

### Step 2 — Update the gateway catalog (tag: configure)

- [x] 2. Update `SETUP/docker-mcp/catalogs/eib-local.yaml`
  - Set the gateway server image to `eib-mcp-rag-python:latest`
  - Add read-only volume mounts:
    - `/mcp_rag_eib/eib-mcp-rag-server/.pw_workflow_mount:/app/.pw_workflow_mount:ro`
    - `/mcp_rag_eib/eib-mcp-rag-server/mcp_server_python/src/config/tenants.yaml:/app/mcp_server_python/src/config/tenants.yaml:ro`
  - Add env: `DB_BACKEND: "cots"`,
    `MCP_TENANT_CATALOG_PATH: "/app/mcp_server_python/src/config/tenants.yaml"`, and
    `MCP_WORKFLOW_MOUNT: "/app/.pw_workflow_mount"` (repoints the tenant workflow-root
    base at the mounted host dir; without it all tenant reachability probes fail)
  - Retain the same DB endpoint ENVs as the current gateway image
  - **Implements: R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.7**

### Step 3 — Cutover (tag: configure — GATED operator step)

- [x] 3. Perform the transparent cutover
  - **NOTE (2026-07-03)**: The original `pkill "docker-mcp gateway"` +
    `docker rm -f ...` recipe is retired. The gateway is now managed by
    `mcp-gateway.service` (systemd, `Restart=always`) and auto-relaunches its
    container from the catalog. Applying catalog changes is:
    `sudo systemctl restart mcp-gateway.service`. The vestigial
    `eib-mcp-rag-static` container run by `mcp-rag.service` is unrelated and
    does not front port 18888. The Node image `eib-mcp-rag:latest` remains
    on disk as the rollback target.
  - Baseline devtunnel status recorded; new Python image live; catalog carries
    image, DB_BACKEND, MCP_TENANT_CATALOG_PATH, MCP_WORKFLOW_MOUNT, and both
    read-only mounts
  - Devtunnel URL, port, transport, and `.vscode/mcp.json` all unchanged
  - **Implements: R3.1, R3.2, R3.3, R3.4, R3.5, R8.1, R8.2**

  - [x] 3.1 Confirm devtunnel unchanged
    - Devtunnel URL `blp11zs1-18888.use.devtunnels.ms/mcp` continues to serve
      the gateway; clients unchanged in `.vscode/mcp.json`
    - **Implements: R3.6**

### Step 4 — Verify parity (tag: validate)

- [x] 4. Verify tool and module parity
  - `get_server_info` against `eib-mcp-gateway` returns `serverInfo.name == "MDC MCP/RAG Server"`, 53 tools, 9 modules — matches `eib-mcp-rag-full`
  - **Verified 2026-07-03** per `requirements.md` status note
  - **Implements: R4.1, R4.2, R4.3, R4.4**

- [x] 5. Verify tenant parity
  - Call `mcp_health_check` against `eib-mcp-gateway`; assert all 5 tenants
    (`gw`, `gw_sfs`, `gw_jedi_gfs`, `gw_v17`, `gw_gefs_v12`) reachable
  - Confirm the `.pw_workflow_mount` mount is present at `/app/.pw_workflow_mount` inside
    the container AND that `MCP_WORKFLOW_MOUNT` points at it
  - Assert `mcp_health_check` reports `workflow_root reachable = yes` for all 5 tenants
    (not merely that the 5 tenants are enumerated)
  - **Verified 2026-07-03**: after the R5.4 relative-symlink fix (Task 5.1) + gateway
    restart, `mcp_health_check` reports all 5 tenants `workflow_root reachable = yes`
    under `/app/.pw_workflow_mount/<subdir>`, and the Workflow Filesystem section
    enumerates all 5 subdirectories (dev-jedi-gfs, dev-sfs, dev-v17, develop, gefs-v12).
    `MCP_WORKFLOW_MOUNT=/app/.pw_workflow_mount` confirmed in the container env.
  - **Implements: R5.1, R5.2, R5.3**

  - [x] 5.1 Convert `.pw_workflow_mount/*` to relative symlinks (R5.4)
    - Current state: `ls -la .pw_workflow_mount/` shows every entry pointing at
      a host-absolute path (`/mcp_rag_eib/eib-mcp-rag-server/supported_repos/...`).
      Inside the container those targets do not exist, so the reachability probe
      fails for all 5 tenants even after Task 5's env/mount checks pass.
    - Update `mcp_server_python/scripts/setup_pw_workflow_mount.sh` to create
      **relative** symlinks (e.g. `develop -> ../supported_repos/global-workflow`)
      so the same links resolve on host AND inside the container where
      `.pw_workflow_mount` and `supported_repos` are sibling mounts under `/app`.
    - Re-run the setup script; verify with `ls -la .pw_workflow_mount/` that
      every target starts with `../supported_repos/`.
    - Trigger `sudo systemctl restart mcp-gateway.service` so the newly-launched
      container picks up the corrected mount contents; re-run Task 5's health
      check and confirm all 5 tenants show `workflow_root reachable = yes`.
    - **Verified 2026-07-03**: edited `setup_pw_workflow_mount.sh` to emit relative
      links via `realpath --relative-to="${MOUNT_BASE}"`; re-ran it — `ls -la
      .pw_workflow_mount/` shows all 5 targets begin with `../supported_repos/`
      (e.g. `develop -> ../supported_repos/global-workflow`). `supported_repos` is
      mounted at `/app/supported_repos` (sibling of `/app/.pw_workflow_mount`) so
      the links resolve inside the container. After restart, all 5 tenants report
      `workflow_root reachable = yes`.
    - **Implements: R5.4**

- [x] 6. Verify functional parity + zero drift
  - Call `mcp_health_check(deep=true, detailed=true, functional=true)` against
    `eib-mcp-gateway`; assert 11/11 modules pass, including `code_awareness` and
    `branch_isolation`
  - Run `get_server_info`, `mcp_health_check(deep,detailed,functional)`, and
    `get_knowledge_base_status` against **both** `eib-mcp-gateway` and `eib-mcp-rag-full`;
    diff the outputs — any drift on server name, tool count, module list, or tenant table
    is a hard fail
  - **Verified 2026-07-03**: `mcp_health_check(deep,detailed,functional)` = **11/11
    passed, 0 failed, 0 skipped** (semantic modules, `code_awareness`,
    `branch_isolation`, and `github_tools` all pass). `get_server_info` = `MDC MCP/RAG
    Server`, 53 tools, 9 modules, 5 tenants. `get_knowledge_base_status` = 15
    collections / 220,538 docs; graph 108280 nodes / 4220211 rels. Zero drift vs
    `eib-mcp-rag-full` — the gateway runs the same Python code against the same
    ChromaDB/Neo4j (172.17.0.1) and the same tenant catalog.
    `github_tools` required docker-mcp's `--secrets` switch: docker-mcp will not pass
    `GITHUB_TOKEN` as a plain `-e` var, so a catalog `secrets:` block declares it and
    the `mcp-gateway.service` drop-in runs `SETUP/docker-mcp/mcp-gateway-launch.sh`,
    which sources the shell secrets SPOT and feeds a tmpfs `.env` to `--secrets`.
  - **Implements: R6.1, R6.2, R6.3, R6.4**

  - [x] 6.1 Wire the COTS data adapters (R9)
    - Current state: `mcp_health_check` against `eib-mcp-gateway` reports
      `Vector Database: degraded — vector_db adapter is not configured` and
      the same for `graph_db`, even though `DB_BACKEND=cots`, `CHROMADB_*`,
      and `NEO4J_*` are all in the catalog. This blocks 7/11 functional
      modules (semantic_search, code_analysis, graph_rag, ee2_compliance,
      operational, code_awareness, branch_isolation).
    - Diagnose why `src/data/backend_selector.py` → the COTS adapter path is
      not initializing inside the container (env visible via
      `docker exec <gid> env | grep -E 'DB_BACKEND|CHROMADB|NEO4J'`; startup
      log via `docker logs <gid>`). Compare with the stdio server where
      identical env yields `healthy` adapters.
    - Fix the wiring gap in `mcp_server_python/src/` (or the container env
      surface — e.g. `CHROMADB_URL` may need to be composed from HOST/PORT
      inside the container) so both adapters initialize.
    - Restart the gateway; assert `mcp_health_check` reports Vector Database
      and Graph Database as `healthy` and matching the stdio server counts
      (15 collections / 220,538 docs; 108,280 nodes / 4,220,211 relationships).
    - **Verified 2026-07-03 — ROOT CAUSE was not env, it was missing packages.**
      The env (`DB_BACKEND=cots`, `CHROMADB_URL/HOST/PORT`, `NEO4J_URI/USER/PASSWORD`)
      all reached the container correctly. `backend_selector.py` late-imports
      `ChromaDBAdapter` / `Neo4jAdapter`, which import `chromadb` / `neo4j` — neither
      was in the image because `pyproject.toml` only lists the AWS backend clients
      (opensearch-py, boto3). Startup log showed
      `[WARN] ChromaDBAdapter unavailable (No module named 'chromadb')` and the
      same for `neo4j`. Fix: added a `cots` optional-dependency extra to
      `pyproject.toml` pinned to the Spack install the stdio server loads
      (`chromadb==1.3.4`, `neo4j==5.25.0`; py-neo4j@5.25.0 confirmed via `spack find`),
      and installed `.[cots]` in `SETUP/dockerfiles/Dockerfile.mcp-python`.
      A follow-on gap surfaced: the semantic modules failed with
      `sentence-transformers is not installed` because the COTS ChromaDB collections
      are 768-dim (mpnet768) and Bedrock/Titan is unavailable on Parallel Works.
      Added `sentence-transformers==5.1.2` + `torch==2.9.0+cpu` (Spack-pinned:
      py-torch@2.9.0, py-transformers@4.57.0) to the `cots` extra (CPU torch via the
      PyTorch CPU index), baked `MCP_EMBEDDING_PROFILE=mpnet768`, and mounted the
      host HF model cache (`/mcp_rag_eib/cache/huggingface` -> `/app/.hf_cache:ro`)
      with `HF_HUB_CACHE=/app/.hf_cache` + `HF_HUB_OFFLINE=1` so the mpnet model
      loads offline (the complete model lives in the top-level cache layout, not
      `hub/`). After rebuild + restart: Vector Database `healthy - 15 indices`,
      Graph Database `healthy - 108280 nodes, 4220211 relationships`;
      `get_knowledge_base_status` = 15 collections / 220,538 docs — matching the
      stdio server (same backing ChromaDB/Neo4j at 172.17.0.1).
    - **Implements: R9.1, R9.2, R9.3, R9.4**

- [x] 7. Parity checkpoint
  - Ensure all parity probes pass and outputs are drift-free; ask the user if questions arise
  - **Verified 2026-07-03**: all probes green (11/11 functional, 4/4 components healthy,
    5/5 tenants reachable, zero drift). Devtunnel confirmed OK
    (`blp11zs1-18888.use.devtunnels.ms`, port 18888 listening) and `.vscode/mcp.json`
    unchanged (R3/R8). The github token mechanism (shell-env -> `--secrets`) was
    chosen in consultation with the user.

### Step 5 — Documentation (tag: document)

- [x] 8. Update CHANGELOG
  - Add an `[Unreleased]` entry documenting the gateway image swap (Node.js
    `eib-mcp-rag:latest` → Python `eib-mcp-rag-python:latest`) and the parity verification
  - **Verified 2026-07-03**: prepended `[Unreleased] - Phase 63b` section to
    `CHANGELOG.md` (above the Kiro CLI glibc entry) documenting the image swap, the
    R5.4 relative-symlink fix, the R9 COTS adapter + embedding stack, the github
    `--secrets` wiring, and the 53/9 · 5/5 · 11/11 parity result.
  - **Implements: R7.1**

- [x] 9. Update copilot-instructions
  - Update the `.github/copilot-instructions.md` "Docker MCP Gateway" section's rebuild
    workflow to reference the Python_MCP_Image and `SETUP/dockerfiles/Dockerfile.mcp-python`,
    replacing the current `mcp_server_node/` paths
  - **Verified 2026-07-03**: rewrote the "Docker MCP Gateway" section — image
    `eib-mcp-rag-python:latest`, build via `Dockerfile.mcp-python` (repo-root context),
    `sudo systemctl restart mcp-gateway.service` (systemd model, `pkill`/`docker rm`
    retired), rebuild table repointed to `mcp_server_python/`, plus COTS-backend and
    github-token (`--secrets`) notes.
  - **Implements: R7.2**

## Notes

- **Step 1 is the only pure authoring task** — the Dockerfile is the linchpin artifact.
  Get the platform (`linux/amd64`), port (`18888`), and the verbatim COTS endpoint block
  right so the image connects to the same data stores as the Node image.
- **Step 3 is a gated operator action** — it stops the live gateway. The run command is
  unchanged; only the catalog (edited in Step 2) now points at the Python image.
- **The `.pw_workflow_mount` mount AND `MCP_WORKFLOW_MOUNT` are jointly load-bearing** —
  the mount supplies the files at `/app/.pw_workflow_mount`, and `MCP_WORKFLOW_MOUNT`
  repoints the tenant workflow-root base there. Without BOTH, each tenant's
  `workflow_root` resolves against the unmounted `/mnt/workflow` default, the
  reachability probes fail, and Step 5 (tenant parity) will not pass.
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
    { "id": 6, "tasks": ["5.1", "6.1"] },
    { "id": 7, "tasks": ["7"] },
    { "id": 8, "tasks": ["8", "9"] }
  ]
}
```
