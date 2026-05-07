---
inclusion: auto
---

# Development Workflow — AWS Port (develop_aws branch)

## SDD Methodology

All feature work follows Spec-Driven Development (SDD): "If it's not in the SDD, it doesn't get coded."

The AWS port is tracked as **SDD Phase 48** (not Phase 46 — that numbering is used in the Kiro
tasks.md but conflicts with SDD Phase 46 "Knowledge Base Gap Closure" which is already completed).

### Phase 48 ↔ Kiro Task Mapping

| SDD Step | Kiro Task | Sub-Phase | Name |
|----------|-----------|-----------|------|
| 0 | 0.1–0.3 | 48A | AWS EC2 provisioning scripts (SETUP_AWS/) |
| 1 | 1.1 | 48A | Scaffold CDK project and VPC stack |
| 2 | 1.2 | 48A | Define Security stack |
| 3 | 1.3 | 48A | Define Data stack (Neptune, OpenSearch, EFS, S3) |
| 4 | 1.4, 2 | 48A | CDK unit tests + `cdk synth` validation |
| 5 | 3.1–3.3 | 48A | Implement `resolveConfig()` + property tests |
| 6 | 4.1 | 48B | Define adapter interfaces ✅ DONE |
| 7 | 4.2 | 48B | Implement OpenSearch adapter |
| 8 | 4.3 | 48B | Implement ChromaDB legacy adapter ✅ DONE |
| 9 | 5.1–5.2 | 48B | Implement Neptune adapter + APOC transform |
| 10 | 5.3 | 48B | Implement Neo4j legacy adapter ✅ DONE |
| 11 | 6.1–6.2 | 48B | Implement backend selector + wire UnifiedDataAccess ✅ DONE |
| 12 | 4.4–5.5, 6.3 | 48B | Adapter property tests |
| 13 | 8.1–8.3 | 48B | ECS Fargate + API Gateway + CloudFront |
| 14 | 9.1–9.5 | 48B | Health check + error handling + resilience |
| 15–19 | 11.1–13.2 | 48C | Data migration + search validation |
| 20–21 | 14.1–14.2 | 48D | Ingestion pipeline adaptation |
| 22–25 | 16.1–16.3 | 48E | Monitoring, validation, cutover |

### SDD Session State Files

When recording SDD progress, update these files directly:

- **Active session**: `sdd_framework/execution_state/active_session.json`
  - Add entries to `completedSteps[]` array with `step`, `name`, `tag`, `completedAt`, `notes`
  - Update `lastActivityAt` timestamp
  - Tags: `research`, `design`, `implement`, `configure`, `validate`, `document`, `ingest`

- **Audit trail**: `sdd_framework/execution_state/history.jsonl`
  - Append one JSON line per step: `{"event":"step_completed","sessionId":"session_2026-03-30_phase48","step":N,"name":"...","tag":"...","timestamp":"..."}`

- **Phase spec**: `sdd_framework/workflows/phase48_aws_infrastructure_port.md` (read-only reference)

### SDD Session Lifecycle (via eib-mcp-gateway MCP or direct file edit)
```
start_sdd_session → record_sdd_step (repeat) → complete_sdd_session
```
Session state persists in `sdd_framework/execution_state/active_session.json`.
Use `get_sdd_session` to resume across conversations.

## Using the Legacy MCP During Development

The `eib-mcp-gateway` MCP tools are available for:
- Querying the NOAA Global Workflow knowledge base (ChromaDB + Neo4j)
- Running EE2 compliance checks against code
- Searching documentation and architecture
- Managing SDD workflow sessions
- Analyzing code structure and dependencies via the graph database

These tools reflect the **legacy system's data** — the same data we are porting to AWS.

## Using the AWS MCP (AgentCore + Neptune Direct)

Two AWS-native MCP connections are configured:

1. **`agentcore-mcp-rag`** — Full 51-tool MCP server via AgentCore Runtime proxy
   - Uses `tools/agentcore-kiro-proxy.py` (stdio → boto3 → AgentCore SSE)
   - Currently: static tools work, graph/vector tools pending VPC connectivity fix

2. **Neptune MCP Server** — Direct openCypher/Gremlin access to the AWS Neptune graph
   - 164,916 nodes, 2,941,593 relationships (live, fully loaded)
   - Use for ad-hoc graph queries, schema inspection, data validation
   - Configured via `amazon-neptune-mcp-server` in `.kiro/settings/mcp.json`

## Steering vs COTS Instruction Files

**Steering** (`.kiro/steering/`) is the authoritative context system for Kiro. It is always
loaded and drives agent behavior on this workspace.

**Instruction files** (`.github/instructions/`) are a separate system for COTS IDEs (GitHub
Copilot, Cursor) that conditionally load when those IDEs detect an active MCP server. They
document the same 51 tools but are NOT maintained for Kiro and may drift from current state.

**Rule**: Do not edit instruction files to influence Kiro behavior. Edit steering files instead.

## Code Conventions

- ASCII prefixes only in console output (`[OK]`, `[ERROR]`, `[WARN]`) — no emoji (breaks MCP stdio)
- 2-space indentation (JS and Bash)
- ES Modules (`import`/`export`) for all `.js` files
- Bash variables always quoted: `"${variable}"`
- Python docstrings: numpy style
- Always update `CHANGELOG.md` for version changes

## CDK Deployment Safety (Post-Mortem Corrective Action)

After the April 22, 2026 Neptune data loss incident, the following are MANDATORY
for any CDK stack deployment. See `.kiro/steering/05-cdk-data-safety.md` for full rules.

1. **Every stateful resource MUST have `removalPolicy: RETAIN`** — CDK defaults to DESTROY
2. **Run `cdk diff` before every `cdk deploy`** — review for unintended deletions
3. **Two-step pattern for resource migration** — deploy RETAIN first, then remove from CDK
4. **CDK tests MUST assert `DeletionPolicy: Retain`** on all stateful resources
5. **Never skip the pre-deploy checklist** in `.kiro/steering/05-cdk-data-safety.md`

## AWS-Specific Considerations

- **IaC First**: All infrastructure changes via CDK or AgentCore CLI — no manual console changes
- **AgentCore for MCP**: Deploy MCP server via `agentcore launch` (not manual node processes)
- No Docker on this system — do not reference `docker compose`, `docker build`, etc. for runtime
- Docker configs in the repo are legacy reference only
- The persistent data root is `/mdc-mcp-rag` (not `/mcp_rag_eib`)
- Use AWS-native services where possible (see architecture context steering file)
- Node.js MCP server runs natively via `npm start` from `mcp_server_node/` (dev only)
- For production: wrap with BedrockAgentCoreApp and deploy via `agentcore launch`

## Build & Test (on this AWS instance)

All commands from `mcp_server_node/`:
```bash
npm start              # full mode (requires ChromaDB + Neo4j)
npm run start:core     # core mode (Neo4j only)
npm test               # full test suite
npm run test:verbose   # detailed output
npm run validate       # syntax check
```

## SPOT (Single Point of Truth)

| Config | Source |
|--------|--------|
| Documentation URLs | `mcp_server_node/scripts/documentation_sources_config.py` |
| Environment config | `SETUP/mcp-env.sh` |
| MCP client config (Kiro) | `.kiro/settings/mcp.json` (legacy + AgentCore + Neptune) |
| AgentCore deployment | `mcp_server_node/.bedrock_agentcore.yaml` |
| Neptune endpoint | `wss://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182` |
| OpenSearch endpoint | `vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com` |
| Changelog | `CHANGELOG.md` (root) |
| SDD phase progress | `.kiro/steering/04-phase48-progress.md` |

## Development Guidelines

### Change Logging
- Each time you generate code, note the changes in `CHANGELOG.md`
- Follow semantic versioning guidelines
- Include date and description of changes
- Periodically perform git commits with clear messages when appropriate
- Never change the branch that we start with

### Code Style
- Follow the existing code style in the repository
- Use consistent indentation (2 spaces)
- Follow the BASH style already in code base especially `"${variable}"` for variables
- Never add extra whitespace at the end or beginning of lines
- Use pycodestyle for Python code
- Use shfmt where appropriate and shellcheck for linting

### Code Quality
- Ensure code is clean, well-commented, and follows best practices
- Use consistent naming conventions
- Avoid unnecessary complexity at all costs and make sure the code is easy to understand by average developers
- Avoid over-engineering solutions
- Use readable code that conveys intent and meaning over comments
- Write unit tests for new features and bug fixes
- Ensure code is modular and reusable
