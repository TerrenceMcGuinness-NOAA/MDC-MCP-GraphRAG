# MDC MCP/RAG Server — Python Port

Parallel Python port of the Node.js MCP server (`../mcp_server_node/`).

**Status**: In progress — Phase B1 (project scaffolding) + Phase B2
(database adapter layer) complete. Tool modules B3–B11 still pending.

The Node.js server remains the production deployment; this port is
cut over module by module after parity tests pass.

## Layout

```
mcp_server_python/
├── pyproject.toml              # Dependencies, build config
├── Dockerfile                  # Multi-stage ARM64 runtime image
├── .bedrock_agentcore.yaml     # Scaffold deploy config (not yet used)
├── src/
│   ├── mcp_server.py           # FastMCP entrypoint (Streamable HTTP :8000)
│   ├── config/                 # Env var loading, AWS defaults
│   ├── data/                   # VectorDB / GraphDB protocols + adapters
│   ├── graphrag/               # GGSR traversal engine (pending B3)
│   ├── tools/                  # 9 tool modules (pending B5–B11)
│   ├── sdd/                    # SDD session manager (pending B3)
│   └── agents/                 # Strands integration (pending B12)
└── tests/
    ├── unit/                   # Fast unit tests
    ├── properties/             # Hypothesis property tests (≥100 iters)
    └── parity/                 # Dual-server parity tests (pending B4)
```

## Running (local dev)

```bash
cd mcp_server_python/
python -m venv .venv && source .venv/bin/activate
pip install -e '.[test]'

# Env vars required in aws mode
export DB_BACKEND=aws
export AWS_REGION=us-east-1
export NEPTUNE_ENDPOINT="wss://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182"
export OPENSEARCH_ENDPOINT="vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com"

python -m src.mcp_server           # serve on 0.0.0.0:8000
python -m src.mcp_server --modules semantic_search,code_analysis
```

## Testing

```bash
pytest                              # full suite
pytest tests/unit/                  # fast unit tests
pytest tests/properties/            # property tests (Hypothesis)
pytest -m property                  # by marker
```

## Reference

- Spec: `.kiro/specs/python-mcp-server-port/`
- Requirements: `.kiro/specs/python-mcp-server-port/requirements.md` (R1–R18)
- Design: `.kiro/specs/python-mcp-server-port/design.md`
- Node.js baseline: `../mcp_server_node/`
