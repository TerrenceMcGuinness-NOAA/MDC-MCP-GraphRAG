# Docker MCP Server - Quick Start Guide

## TL;DR

```bash
# Start MCP server in Docker
cd /mcp_rag_eib/eib-mcp-rag-server
docker compose -f docker-compose.mcp-standalone.yaml up -d

# Check status
docker ps | grep eib-mcp-rag

# View logs
docker logs eib-mcp-rag

# Test MCP tools
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | \
  docker exec -i eib-mcp-rag node src/UnifiedMCPServer.js core

# Stop server
docker compose -f docker-compose.mcp-standalone.yaml down
```

## What's Running

- **Container**: `eib-mcp-rag`
- **Image**: `eib-mcp-rag:latest` (1.66GB)
- **Tools**: 32 MCP tools across 7 categories
- **Databases**:
  - ChromaDB: `host.docker.internal:8080` (systemd service)
  - Neo4j: `global-workflow-neo4j:7687` (Docker container)

## Common Commands

### Start/Stop

```bash
# Start (detached)
docker compose -f docker-compose.mcp-standalone.yaml up -d

# Start (foreground with logs)
docker compose -f docker-compose.mcp-standalone.yaml up

# Stop
docker compose -f docker-compose.mcp-standalone.yaml down

# Restart
docker compose -f docker-compose.mcp-standalone.yaml restart
```

### Monitoring

```bash
# Real-time logs
docker logs -f eib-mcp-rag

# Last 50 lines
docker logs --tail 50 eib-mcp-rag

# Health check
docker inspect eib-mcp-rag | jq '.[].State.Health'
```

### Debugging

```bash
# Shell access
docker exec -it eib-mcp-rag /bin/bash

# Run Node REPL
docker exec -it eib-mcp-rag node

# Check environment
docker exec eib-mcp-rag env | grep MCP

# Test database connections
docker exec eib-mcp-rag curl http://host.docker.internal:8080/api/v2/heartbeat
docker exec eib-mcp-rag ping -c 3 global-workflow-neo4j
```

### Rebuild Image

```bash
# Rebuild after code changes
docker compose -f docker-compose.mcp-standalone.yaml build

# Force rebuild (no cache)
docker compose -f docker-compose.mcp-standalone.yaml build --no-cache

# Rebuild and restart
docker compose -f docker-compose.mcp-standalone.yaml up -d --build
```

## Configuration

Edit `docker-compose.mcp-standalone.yaml` to change:

- `MCP_SCENARIO`: full (default), core, rag, github
- Database connection strings
- Feature flags (ENABLE_RAG, ENABLE_GITHUB)
- GitHub token (for GitHub tools)

## Available Tools

### Workflow Info (3)
- get_workflow_structure
- get_system_configs
- describe_component

### Semantic Search (8)
- search_documentation
- search_ee2_standards
- find_related_files
- explain_with_context
- analyze_ee2_compliance
- generate_compliance_report
- scan_repository_compliance
- extract_code_for_analysis

### Code Analysis (4)
- analyze_code_structure
- find_dependencies
- trace_execution_path
- find_callers_callees

### Operational (3)
- get_operational_guidance
- explain_workflow_component
- list_job_scripts

### SDD Framework (7)
- list_sdd_workflows
- get_sdd_workflow
- execute_sdd_workflow_supervised
- get_sdd_execution_history
- get_sdd_framework_status
- validate_sdd_compliance
- get_sdd_step_details

### GitHub (3)
- search_issues
- get_pull_requests
- get_repository_info

### System Health (2)
- mcp_health_check
- get_server_info

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Container won't start | Check logs: `docker logs eib-mcp-rag` |
| Can't connect to ChromaDB | Verify systemd service: `systemctl --user status chromadb-persistent` |
| Can't connect to Neo4j | Check container: `docker ps \| grep neo4j` |
| Out of disk space | Prune images: `docker system prune -a` |
| Permission denied | Check volume mounts in docker-compose.mcp-standalone.yaml |

## Files

- **Dockerfile**: `mcp_server_node/Dockerfile`
- **Compose**: `docker-compose.mcp-standalone.yaml`
- **Catalog**: `mcp_server_node/docker-mcp-catalog.yaml`
- **Docs**: `DOCKER_MCP_SETUP.md` (detailed documentation)

## Next Steps

See `DOCKER_MCP_SETUP.md` for:
- Architecture diagrams
- Alternative deployment options
- HTTP wrapper implementation
- LangFlow integration strategies
- Full testing procedures
