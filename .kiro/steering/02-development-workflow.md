---
inclusion: auto
---

# Development Workflow — AWS Port (develop_aws branch)

## SDD Methodology

All feature work follows Spec-Driven Development (SDD): "If it's not in the SDD, it doesn't get coded."

1. Create or identify a phase spec in `sdd_framework/workflows/`
2. Use the legacy `eib-mcp-gateway` MCP tools to manage SDD sessions
3. Commit completed work to `develop_aws` branch
4. Push completed SDD phases to the legacy system until AWS is self-hosting

### SDD Session Lifecycle (via eib-mcp-gateway MCP)
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
