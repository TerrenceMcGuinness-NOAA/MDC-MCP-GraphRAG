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

## Code Conventions

- ASCII prefixes only in console output (`[OK]`, `[ERROR]`, `[WARN]`) — no emoji (breaks MCP stdio)
- 2-space indentation (JS and Bash)
- ES Modules (`import`/`export`) for all `.js` files
- Bash variables always quoted: `"${variable}"`
- Python docstrings: numpy style
- Always update `CHANGELOG.md` for version changes

## AWS-Specific Considerations

- No Docker on this system — do not reference `docker compose`, `docker build`, etc. for runtime
- Docker configs in the repo are legacy reference only
- The persistent data root is `/mdc-mcp-rag` (not `/mcp_rag_eib`)
- Use AWS-native services where possible (see architecture context steering file)
- Node.js MCP server runs natively via `npm start` from `mcp_server_node/`
- ChromaDB and Neo4j need AWS-native deployment (ECS, managed services, or native install)

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
| MCP client config | `.kiro/settings/mcp.json` (points to legacy) |
| Changelog | `CHANGELOG.md` (root) |
