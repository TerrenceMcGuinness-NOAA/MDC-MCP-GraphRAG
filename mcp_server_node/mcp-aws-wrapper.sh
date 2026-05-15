#!/bin/bash
# Wrapper for Kiro MCP stdio spawner — ensures clean environment
export DB_BACKEND=aws
export OPENSEARCH_ENDPOINT=https://vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com
export NEPTUNE_ENDPOINT=wss://mdc-mcp-rag-neptune.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182
export AWS_REGION=us-east-1
exec node /mdc-mcp-rag/eib-mcp-rag-server/mcp_server_node/src/UnifiedMCPServer.js full
