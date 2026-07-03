# Requirements Document

## Introduction

Head-to-head health checks between the two active MCP entry points expose a large drift.
Both launch from the same repo on the same Parallel Works form factor, but the Docker MCP
Gateway ships a stale Node.js image while the stdio server runs the current Python server:

| Dimension | Docker MCP Gateway (`eib-mcp-gateway`) | Stdio server (`eib-mcp-rag-full`) |
|---|---|---|
| Server binary | `global-workflow-unified-mcp` v3.6.2 (Node.js, `mcp_server_node/`) | `MDC MCP/RAG Server` v1.0.0 (Python, `mcp_server_python/`) |
| Tools | 51 | 53 |
| Modules | 7 | 9 |
| Multi-tenant | No | Yes (5 tenants) |
| Extra modules | — | `code_awareness`, `branch_isolation` |

This feature brings the gateway to parity by containerizing `mcp_server_python/` as an
x86_64 image and repointing the gateway catalog at it. The devtunnel URL, port `18888`,
streaming transport, and `.vscode/mcp.json` all remain unchanged — the swap is transparent.
An ARM64 Dockerfile already exists at `mcp_server_python/Dockerfile` for AgentCore; this
feature creates the x86_64 sibling for the Parallel Works Docker MCP Gateway.

This feature **depends on Phase 63a** (the backend label rename), which establishes
`DB_BACKEND=cots` as the canonical backend label.

## Glossary

- **Docker_MCP_Gateway**: The `eib-mcp-gateway` MCP entry point — a `docker mcp gateway run`
  process that fronts a container over streaming HTTP on port 18888, exposed via the
  Devtunnel.
- **Stdio_Server**: The `eib-mcp-rag-full` MCP entry point — the reference Python stdio
  server (`MDC MCP/RAG Server` v1.0.0) whose tool/module/tenant surface defines parity.
- **Python_MCP_Image**: The new x86_64 container image `eib-mcp-rag-python:latest`, built
  from the Python server for the Docker MCP Gateway.
- **Node_Image**: The current gateway image `eib-mcp-rag:latest` (Node.js, `node:20-slim`),
  preserved locally as the rollback target.
- **Python_Dockerfile**: The new build definition `SETUP/dockerfiles/Dockerfile.mcp-python`
  that produces the Python_MCP_Image (x86_64 sibling of `mcp_server_python/Dockerfile`).
- **Gateway_Catalog**: The Docker MCP Gateway catalog file
  `SETUP/docker-mcp/catalogs/eib-local.yaml` that declares the gateway's image, volumes,
  and env.
- **Tenant_Catalog**: The 5-tenant catalog `mcp_server_python/src/config/tenants.yaml`,
  mounted read-only into the container rather than baked into the image.
- **Devtunnel**: The persistent tunnel exposing the gateway's port 18888 at a stable URL;
  managed via `scripts/manage-devtunnel.sh`.
- **Workflow_Mount**: The host directory `.pw_workflow_mount`, mounted read-only into the
  container, required by the Tenant_Catalog for workflow-root reachability probes.

## Requirements

### Requirement 1: Containerize the Python Server as an x86_64 Image

**User Story:** As a platform maintainer, I want an x86_64 Dockerfile for the Python MCP
server, so that the Docker MCP Gateway can run the current server on Parallel Works nodes.

#### Acceptance Criteria

1. THE Python_Dockerfile SHALL target the `linux/amd64` platform.
2. THE Python_Dockerfile SHALL expose and serve MCP on port 18888.
3. THE Python_Dockerfile SHALL set the container working directory to
   `/app/mcp_server_python`.
4. THE Python_Dockerfile SHALL set `DB_BACKEND=cots` as the default backend environment
   value.
5. THE Python_Dockerfile SHALL bake the COTS endpoint environment block
   (`CHROMADB_HOST=172.17.0.1`, `CHROMADB_PORT=8080`, `NEO4J_URI=bolt://172.17.0.1:7687`,
   `NEO4J_USER=neo4j`, `NEO4J_PASSWORD=gfsworkflow2025`) copied verbatim from the current
   gateway image so the new image connects to the same data-store endpoints.
6. THE Python_Dockerfile SHALL set
   `MCP_TENANT_CATALOG_PATH=/app/mcp_server_python/src/config/tenants.yaml`.
7. THE Python_Dockerfile SHALL copy `mcp_server_python/pyproject.toml`,
   `mcp_server_python/src/`, and `SETUP/mcp-env.sh` into the image.
8. WHEN `docker build -f SETUP/dockerfiles/Dockerfile.mcp-python -t eib-mcp-rag-python:latest .`
   is run, THE Python_Dockerfile SHALL build successfully and produce the Python_MCP_Image.
9. WHEN the Python_MCP_Image is run with `docker run --rm -p 18888:18888
   eib-mcp-rag-python:latest`, THE Python_MCP_Image SHALL respond to an MCP `initialize`
   request.

### Requirement 2: Repoint the Gateway Catalog at the Python Image

**User Story:** As a platform maintainer, I want the gateway catalog to reference the Python
image with the required mounts and env, so that the gateway serves the multi-tenant Python
server.

#### Acceptance Criteria

1. THE Gateway_Catalog SHALL set the gateway server image to `eib-mcp-rag-python:latest`.
2. THE Gateway_Catalog SHALL mount the Workflow_Mount read-only at `/app/.pw_workflow_mount`.
3. THE Gateway_Catalog SHALL mount the Tenant_Catalog read-only at
   `/app/mcp_server_python/src/config/tenants.yaml`.
4. THE Gateway_Catalog SHALL set the env `DB_BACKEND: "cots"`.
5. THE Gateway_Catalog SHALL set the env
   `MCP_TENANT_CATALOG_PATH: "/app/mcp_server_python/src/config/tenants.yaml"`.
6. THE Gateway_Catalog SHALL retain the same DB endpoint environment variables as the
   current gateway image.

### Requirement 3: Transparent Cutover

**User Story:** As an MCP client user, I want the gateway swap to be invisible from my side,
so that no client configuration changes are required.

#### Acceptance Criteria

1. THE Docker_MCP_Gateway SHALL continue to serve on port 18888 after the cutover.
2. THE Docker_MCP_Gateway SHALL continue to use the streaming HTTP transport after the
   cutover.
3. THE Devtunnel URL SHALL remain unchanged after the cutover.
4. THE `.vscode/mcp.json` `eib-mcp-gateway` entry SHALL require no edit after the cutover.
5. THE gateway run command (`docker mcp gateway run --catalog ... --enable-all-servers
   --transport streaming --port 18888 --long-lived`) SHALL remain byte-for-byte unchanged.
6. WHEN `scripts/manage-devtunnel.sh --status` is run after the cutover, THE Devtunnel
   SHALL report an OK status.

### Requirement 4: Tool and Module Parity

**User Story:** As a maintainer, I want the gateway to expose the same tool and module
surface as the stdio server, so that clients get identical capabilities from either entry
point.

#### Acceptance Criteria

1. WHEN `get_server_info` is called against the Docker_MCP_Gateway, THE Docker_MCP_Gateway
   SHALL report `serverInfo.name == "MDC MCP/RAG Server"`.
2. WHEN `get_server_info` is called against the Docker_MCP_Gateway, THE Docker_MCP_Gateway
   SHALL report 53 tools.
3. WHEN `get_server_info` is called against the Docker_MCP_Gateway, THE Docker_MCP_Gateway
   SHALL report 9 modules.
4. THE Docker_MCP_Gateway tool and module counts SHALL match those reported by the
   Stdio_Server.

### Requirement 5: Tenant Parity

**User Story:** As a multi-tenant operator, I want all five tenants reachable through the
gateway, so that branch-scoped queries work from the gateway entry point.

#### Acceptance Criteria

1. WHEN `mcp_health_check` is called against the Docker_MCP_Gateway, THE Docker_MCP_Gateway
   SHALL report all five tenants (`gw`, `gw_sfs`, `gw_jedi_gfs`, `gw_v17`, `gw_gefs_v12`)
   as reachable.
2. THE Workflow_Mount SHALL be present inside the container so that tenant workflow-root
   reachability probes succeed.

### Requirement 6: Functional Parity

**User Story:** As a maintainer, I want the gateway's functional health check to pass every
module, so that behavioral parity with the stdio server is confirmed.

#### Acceptance Criteria

1. WHEN `mcp_health_check(functional=true)` is called against the Docker_MCP_Gateway, THE
   Docker_MCP_Gateway SHALL return 11/11 functional modules passed.
2. THE Docker_MCP_Gateway functional health check SHALL include `code_awareness` among the
   passing modules.
3. THE Docker_MCP_Gateway functional health check SHALL include `branch_isolation` among
   the passing modules.
4. WHEN `get_server_info`, `mcp_health_check(deep=true, detailed=true, functional=true)`,
   and `get_knowledge_base_status` are run against both the Docker_MCP_Gateway and the
   Stdio_Server, THE Docker_MCP_Gateway SHALL produce zero drift on server name, tool count,
   module list, and tenant table relative to the Stdio_Server.

### Requirement 7: Documentation

**User Story:** As a future maintainer, I want the image swap and rebuild workflow
documented, so that the change is discoverable and reproducible.

#### Acceptance Criteria

1. THE CHANGELOG SHALL contain an `[Unreleased]` entry documenting the gateway image swap
   and the parity verification.
2. THE `.github/copilot-instructions.md` "Docker MCP Gateway" section SHALL reference the
   Python_MCP_Image and the Python_Dockerfile rebuild workflow, replacing the current
   `mcp_server_node/` paths.

### Requirement 8: Rollback Safety

**User Story:** As an operator, I want a one-step rollback path, so that I can revert the
gateway to the Node.js image if the swap regresses.

#### Acceptance Criteria

1. THE Node_Image (`eib-mcp-rag:latest`) SHALL be preserved locally after the cutover.
2. WHERE a rollback is required, THE Gateway_Catalog SHALL support reverting to the
   Node_Image via a one-line image edit.
