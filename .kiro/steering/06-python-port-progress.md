# Python MCP Server Port — Progress Notes

Short-form progress log for the Python port of the Node.js MCP server
(spec: `.kiro/specs/python-mcp-server-port/`). The Node.js server
(`mcp_server_node/`) continues to serve production traffic; the Python
port (`mcp_server_python/`) is validated module-by-module via parity
tests before cutover.

## 2026-05-12 — Phase B4 + early B11 deployed (utility-only smoke test)

### Status

- First AgentCore Runtime deployment for the Python server: **PASSED**.
- New staging runtime coexists with the production Node.js runtime.
- `.kiro/settings/mcp.json` still points at the Node.js runtime — the
  operator will flip it manually once the Python path is ready for
  end-to-end use.

### Runtimes in play

| Runtime | ID | Version | Use |
|---|---|---|---|
| **Node.js (production)** | `mdc_mcp_rag_server-TMXDllG2Wi` | v10 | Active MCP target for `.kiro/settings/mcp.json`. 51 tools. **Untouched.** |
| **Python (staging)** | `mdc_mcp_rag_server_python-v5K2F8BGrN` | v2 | Utility-only smoke test. 4 tools: `get_server_info`, `mcp_health_check`, `get_health_trend`, `get_quality_metrics`. |

### Completed phases

- **B1** — project scaffolding, `pyproject.toml`, Dockerfile, environment
  config (committed as `8.11.0`).
- **B2** — `VectorDBProtocol` / `GraphDBProtocol`, OpenSearch + Neptune
  adapters, `UnifiedDataAccess` facade, backend selector (also in
  `8.11.0`).
- **B3** — GGSR traversal engine, GraphGuidedRetrieval hybrid, SDD
  `SessionManager` with JSONL parity (committed as `8.12.0`).
- **B4** — parity-testing framework (`tests/parity/parity_runner.py`),
  mock adapter library in `tests/conftest.py` (committed as `8.13.0`).
- **Early B11** — `src/tools/utility.py` with the 4 utility tools ported
  from `UnifiedMCPServer.js`. Pulled forward from its spec slot so this
  smoke-test deployment has a minimal working tool set that does not
  need Neptune/OpenSearch connectivity. Remainder of B11 (`github_tools`,
  etc.) will be ported in its original slot. (Also `8.13.0`.)

### Known issue resolved during this deploy

- **FastMCP `stateless_http=True` is required for AgentCore MCP mode.**
  Stateful mode rejects AgentCore's platform-generated `Mcp-Session-Id`
  with HTTP 400, which AgentCore surfaces as a 500-class runtime error.
  `src/mcp_server.py` now sets `stateless_http=True` by default; override
  via the `MCP_STATELESS_HTTP=false` env var for local stateful testing.
  Full root-cause analysis is in
  `docs/reports/2026-05-12-python-server-smoke-test.md`.

### Verified outputs

Per the smoke test (full report at
`docs/reports/2026-05-12-python-server-smoke-test.md`):

- `mcp_health_check({})` → `Overall Status: HEALTHY (2/3 components healthy)`,
  with `Data Access Layer: disabled` — exactly the degraded-mode-boot
  shape.
- `get_server_info({})` → version `1.0.0`, 4 tools registered, active
  module `utility`.

### Next

- **B5** (`semantic_search`, 7 tools) — the parity framework from B4 will
  validate this against the Node.js baseline once both runtimes are
  callable from the same client.
- Subsequent phases (B6 – B10) add the remaining tool modules.
- Phase B11 completion: `github_tools` and any residual utility tools.

### How to rebuild / redeploy the staging runtime

```bash
cd mcp_server_python
docker build --platform linux/arm64 \
    -t 903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:python-utility-v1 \
    -f Dockerfile .

aws ecr get-login-password --region us-east-1 \
    | docker login --username AWS --password-stdin \
        903050880929.dkr.ecr.us-east-1.amazonaws.com
docker push 903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:python-utility-v1

aws bedrock-agentcore-control update-agent-runtime \
    --region us-east-1 \
    --agent-runtime-id mdc_mcp_rag_server_python-v5K2F8BGrN \
    --agent-runtime-artifact '{"containerConfiguration":{"containerUri":"903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:python-utility-v1"}}' \
    --role-arn arn:aws:iam::903050880929:role/mdc-mcp-rag-ecs-task-role \
    --network-configuration '{"networkMode":"VPC","networkModeConfig":{"subnets":["subnet-0e13af6b3a9a6416f","subnet-04447750c61bd7e06"],"securityGroups":["sg-096489a0876cc78c1"]}}' \
    --protocol-configuration '{"serverProtocol":"MCP"}' \
    --lifecycle-configuration '{"idleRuntimeSessionTimeout":900,"maxLifetime":28800}'
```

Use a new tag (e.g. `python-utility-v2`, `python-semantic-v1`) when the
change is not strictly iterative on the same smoke-test scope, so a
rollback target is preserved.

### How to delete the staging runtime

Safe at any time — the Node.js runtime is the production target and has
never been modified:

```bash
aws bedrock-agentcore-control delete-agent-runtime \
    --region us-east-1 \
    --agent-runtime-id mdc_mcp_rag_server_python-v5K2F8BGrN
```
