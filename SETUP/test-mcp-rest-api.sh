#!/usr/bin/env bash
#
# Test MCP REST API - Search Documentation
#

# Load MCP environment
source "$(dirname "${BASH_SOURCE[0]}")/mcp_env.sh" --quiet

echo "🔍 Testing MCP REST API semantic search..."
echo ""

# Send a tools/list request first to see available tools
echo "1. Listing available MCP tools..."
curl -s -X POST http://localhost:3000/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list"
  }' | jq -r '.result.tools[] | "   - " + .name' | head -10

echo ""
echo "2. Testing search_documentation tool..."
curl -s -X POST http://localhost:3000/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "mcp_globalworkflo_search_documentation",
      "arguments": {
        "query": "weather forecast",
        "max_results": 3
      }
    }
  }' | jq

echo ""
echo "✅ MCP REST API test complete"
echo "   The MCP server handles embeddings internally!"
echo "   No need for separate embedding provider"
