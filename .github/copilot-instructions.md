# AI Coding Agent Instructions for EIB MCP-RAG Server

## Project Overview

MCP/RAG development platform for NOAA Global Workflow AI assistance. Provides 52 tools for code analysis, EE2 compliance validation, semantic search, and session state tracking across operational weather forecasting infrastructure.

**Architecture**: Node.js MCP Server → OpenSearch (vectors) + Neptune (graph) → AI Clients (Kiro, CLI, Claude)
**Backend Selector**: `DB_BACKEND=cots` (default on Parallel Works) routes to ChromaDB + Neo4j Community; `DB_BACKEND=aws` routes to OpenSearch + Neptune via adapter pattern. `DB_BACKEND=legacy` accepted for one release with deprecation WARN (Phase 63a; removal in Phase 64).
**Deployment**: AWS Bedrock AgentCore Runtime (production) or mcp-http-server.js (development)

## Infrastructure as Code (IaC) — Primary Principle

All AWS infrastructure MUST be defined and deployed via Infrastructure as Code:
- **CDK** (`infrastructure/cdk/`) for VPC, Neptune, OpenSearch, EFS, S3, IAM roles
- **AWS Bedrock AgentCore** for MCP server deployment (Runtime, Gateway, Memory)
- **CloudFormation** as the underlying deployment mechanism
- No manual AWS console changes — all config via code, CLI, or CDK
- Hand-rolled scripts are acceptable ONLY as temporary dev bridges

## Build, Test, and Lint

All commands run from `mcp_server_node/`:

```bash
# Start MCP server
npm start                    # full mode (all tools, requires ChromaDB + Neo4j)
npm run start:core           # core mode (code analysis only, requires Neo4j)
npm run dev                  # watch mode

# Tests (custom runner — NOT vitest/jest)
npm test                     # full test suite
npm run test:verbose         # with detailed output

# Vitest unit tests (if vitest installed)
npx vitest run src/__tests__                              # all unit tests
npx vitest run src/__tests__/CodeAnalysisTools.test.js    # single test file
./run-unit-tests.sh SemanticSearchTools                   # by module name
./run-unit-tests.sh --coverage                            # with coverage

# Validate syntax only (no lint configured)
npm run validate             # node --check on core files

# Infrastructure
docker compose -f docker-compose.devops.yaml up -d    # start ChromaDB + Neo4j
curl http://localhost:8080/api/v2/heartbeat            # verify ChromaDB (MUST use v2)
curl http://localhost:7474                              # verify Neo4j
```

### Docker MCP Gateway

The MCP server can run natively (stdio) or via the **Docker MCP Gateway** (Streamable HTTP on port 18888). The gateway is a thin wrapper managed by the `mcp-gateway.service` systemd unit (`Restart=always`); it spawns the server container from the `eib-mcp-rag-python:latest` Docker image (the x86_64 Python build — it replaced the legacy Node.js `eib-mcp-rag:latest` image in Phase 63b).

**CRITICAL: The Docker image is a snapshot.** Unlike native mode (which runs live source code), the gateway runs code **baked into the image at build time**. Any changes to files under `mcp_server_python/` require an image rebuild before they take effect in gateway mode.

```bash
# Rebuild after ANY code change (build context is the repo root)
docker build -f SETUP/dockerfiles/Dockerfile.mcp-python -t eib-mcp-rag-python:latest .

# Apply the new image — the systemd unit relaunches the container from the catalog
sudo systemctl restart mcp-gateway.service
```

The gateway run command (catalog, `--transport streaming --port 18888 --long-lived`)
lives in the `mcp-gateway.service` unit and does not change. The old
`pkill "docker-mcp gateway"` + `docker stop/rm` recipe is retired — do not use it.

**Rollback**: one-line edit of `SETUP/docker-mcp/catalogs/eib-local.yaml` back to
`image: eib-mcp-rag:latest` (the Node image is preserved locally), then
`sudo systemctl restart mcp-gateway.service`. No rebuild required to revert.

#### What requires an image rebuild

| Changed File/Directory | Baked into Image? | Rebuild? |
|------------------------|-------------------|----------|
| `mcp_server_python/src/` (tools, core, data) | Yes | **Yes** |
| `mcp_server_python/pyproject.toml` (dependencies) | Yes | **Yes** |
| `SETUP/dockerfiles/Dockerfile.mcp-python` | Yes | **Yes** |
| `SETUP/mcp-env.sh` | Yes | **Yes** |
| `SETUP/docker-mcp/catalogs/eib-local.yaml` (image/env/volumes) | No (gateway config) | No — `systemctl restart` |
| `.pw_workflow_mount/` symlinks | No (volume-mounted `:ro`) | No — `systemctl restart` |
| `mcp_server_python/src/config/tenants.yaml` | No (volume-mounted `:ro`) | No — `systemctl restart` |
| `sdd_framework/` | No (volume-mounted `:rw`) | No |
| `supported_repos/` | No (volume-mounted `:ro`) | No |
| `.vscode/mcp.json` | No (client-side) | No |

**Common pitfall**: Adding/modifying tools in `src/tools/` and testing only via native mode. The gateway will still serve the old tools until the image is rebuilt and `mcp-gateway.service` is restarted.

**COTS backend note**: the gateway image bundles the on-prem (`DB_BACKEND=cots`) clients
— `chromadb`, `neo4j`, and `sentence-transformers`/`torch` for the 768-dim `mpnet768`
local embeddings — pinned to the Spack versions the stdio server uses. The mpnet model
loads offline from the host HuggingFace cache mounted read-only at `/app/.hf_cache`.

**GitHub token note**: docker-mcp treats `GITHUB_TOKEN` as a secret and will not pass it
through as a plain `-e` env var. It is declared in the catalog `secrets:` block and its
value is supplied via `docker mcp gateway run --secrets <.env>`. The
`mcp-gateway.service` drop-in runs `SETUP/docker-mcp/mcp-gateway-launch.sh`, which
sources the shell secrets SPOT (`~/.config/eib-mcp/secrets.env`) and writes a tmpfs
`.env` for the switch. Rotate the token in that secrets file, then
`sudo systemctl restart mcp-gateway.service`.

## Architecture

### Server Scenarios

`UnifiedMCPServer.js` loads tool modules based on scenario:

| Scenario | Flag | Tools | Databases Required |
|----------|------|-------|--------------------|
| `full` | `npm start` | 52 (all) | ChromaDB + Neo4j |
| `core` | `npm run start:core` | ~20 | Neo4j only |
| `rag` | `npm run start:rag` | ~38 | ChromaDB + Neo4j |
| `github` | `npm run start:github` | ~24 | Neo4j + GitHub API |

### Data Flow

```
Tool Modules (9 files in src/tools/)
       │
       ▼
UnifiedDataAccess (src/data/)
  ├── GraphDatabase.js  → Neo4j (bolt://localhost:7687)
  └── VectorDatabase.js → ChromaDB (http://localhost:8080)
       │
       ▼
BaseServer (src/core/) → MCP SDK → stdio transport → AI client
```

### Tool Modules (9 modules, 52 tools)

Full tool reference with parameters, descriptions, and usage workflows is in `.github/instructions/eib-mcp-tools.instructions.md` (auto-loaded when MCP server is connected).

**Database requirements by module**: WorkflowInfoTools (Filesystem), CodeAnalysisTools (Neo4j), SemanticSearchTools (ChromaDB + Neo4j), EE2ComplianceTools (ChromaDB), OperationalTools (ChromaDB), GraphRAGTools (ChromaDB + Neo4j), GitHubTools (GitHub API), SDDWorkflowTools (Filesystem), Utility (Built-in).

### SDD Methodology (REQUIRED for new features)

**SDD = Spec-Driven Development**: "If it's not in the SDD, it doesn't get coded."

**Spec-First Gate** (no exceptions for "feels small"). Before any code change other
than a trivial fix, author a Kiro spec or SDD phase under `.kiro/specs/<spec-name>/`
or `sdd_framework/workflows/` and commit it BEFORE the implementation commit.

A change is **not** trivial — and therefore requires a spec — if it:

- Adds / removes / renames a SPOT config field
- Adds a CLI flag, env var, or new public function arg
- Bumps a SPOT version (e.g. `VERSION = "8.x.y"`)
- Modifies shared pipeline code (crawler, ingester, adapter, embedding provider,
  manifest registry, gap detector, tool module)
- Establishes a new heuristic or pattern other contributors will follow
- Touches >= 3 non-test files

When in doubt, write the spec. The cost is one short markdown triplet; the cost
of skipping it is silent gaps that don't surface until parity testing catches
them. See the 2026-05-21 MPAS path-prefix retrospective in
`.kiro/steering/02-development-workflow.md` for the canonical counter-example.

1. **Plan** → Create spec in `sdd_framework/workflows/phaseX_feature_name.md`
2. **Execute** → Use SDD MCP tools to track session (see tool reference for full lifecycle)

Phase naming: `phase<N><letter>_<descriptor>.md` (e.g., `phase24e_hierarchical_communities.md`). Currently 31+ phases with sub-phases. See `sdd_framework/methodology/spec_driven_design_core.md` for the full protocol.

## Key Conventions

### Code Style
- **Console output**: ASCII prefixes only (`[OK]`, `[ERROR]`, `[WARN]`) — NO emoji in `console.log()` (breaks MCP stdio protocol)
- **Indentation**: 2 spaces (JS and Bash)
- **Bash variables**: Always quoted `"${variable}"`
- **Python docstrings**: numpy style
- **ES Modules**: All `.js` files use `import`/`export` (package `"type": "module"`)

### SPOT (Single Point of Truth)
Each config has exactly one source:
- Documentation URLs → `mcp_server_node/scripts/documentation_sources_config.py`
- Environment config → `SETUP/mcp-env.sh`
- MCP server config → `.vscode/mcp.json`
- **Changelog** → `CHANGELOG.md` (root) — update for ALL version changes

### Changelog Practice
**Always update `CHANGELOG.md`** when modifying tools, infrastructure, or completing SDD phases. Format: semantic versioning with dated headers and commit refs.

### Git Operation Policy
**Git commit and push only on direct user request.** The agent stages changes (`git add <paths>`) so the user can review staged hunks but does not run `git commit` or `git push` autonomously. Branch switches, merges, rebases, and force-anything also require explicit user authorization. See `.kiro/steering/08-git-operation-policy.md` for the full rule set.

### Software Stack
Dependencies go through the **Spack module system**, not arbitrary `pip install`:
```bash
module load gcc/11.5.0
module load python/3.11 py-pip py-neo4j py-pydantic py-httpx
python3 -m pip install --user chromadb sentence-transformers  # only if not in Spack
```
Never `pip install` without `--user`. Document any new dependency in `SETUP/mcp-env.sh`.

### Anti-Patterns
- ChromaDB v1 API (`/api/v1/*`) — deprecated, use v2
- Modifying `supported_repos/` — read-only git submodules
- Duplicating configuration across files (violates SPOT)

## Domain Glossary

| Term | Meaning |
|------|---------|
| **EE2** | EMC Environment 2.0 — NCO production coding standards |
| **GFS/GEFS** | Global Forecast System / Ensemble version |
| **HPC** | Hera, WCOSS2, Orion, Hercules, Gaea compute platforms |
| **GGSR** | Graph-Guided Semantic Retrieval (hybrid Neo4j+ChromaDB queries) |
| **SDD/ISD/USD** | Spec-Driven Development / Interactive Supervised / Unsupervised Development |
