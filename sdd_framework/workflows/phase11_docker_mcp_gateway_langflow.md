# Phase 11: Docker MCP Gateway + LangFlow Integration

**Description**: Deploy the MCP RAG server as a Docker-based MCP service using Docker MCP Gateway, enabling LangFlow integration for advanced tool chain development and intermediate response inspection.

**Rationale**: The current stdio-based MCP integration with VS Code works for end-user assistance but limits our ability to:
1. Inspect intermediate tool responses in the MCP chain
2. Refine tool Separation of Concerns (SOC) iteratively
3. Test tool compositions and orchestrations visually
4. Share MCP tools across multiple AI clients (LangFlow, Claude Desktop, Cursor, etc.)

**Reference**: [Docker MCP Gateway](https://github.com/docker/mcp-gateway)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     AI Clients                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │ LangFlow │  │ VS Code  │  │  Claude  │  │  Cursor  │        │
│  │          │  │ Copilot  │  │ Desktop  │  │          │        │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘        │
│       │             │             │             │               │
│       └─────────────┴──────┬──────┴─────────────┘               │
│                            │                                     │
│                   ┌────────▼────────┐                           │
│                   │  Docker MCP     │                           │
│                   │    Gateway      │ Port 8080 (streaming)     │
│                   │  (docker-mcp)   │                           │
│                   └────────┬────────┘                           │
│                            │                                     │
│           ┌────────────────┼────────────────┐                   │
│           │                │                │                   │
│   ┌───────▼───────┐ ┌──────▼──────┐ ┌──────▼──────┐            │
│   │ EIB-MCP-RAG   │ │  GitHub     │ │  Future     │            │
│   │ Server        │ │  MCP Server │ │  Servers    │            │
│   │ (Container)   │ │ (Container) │ │             │            │
│   └───────────────┘ └─────────────┘ └─────────────┘            │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Phase 11A: Dockerize MCP RAG Server

### Step 1: Create Dockerfile for MCP Server
**Type**: file_creation
**Target**: mcp_server_node/Dockerfile
**Description**: Create a production Dockerfile for the UnifiedMCPServer

```dockerfile
# MCP RAG Server Dockerfile
# Based on Node.js 20 LTS with minimal footprint

FROM node:20-slim AS base

# Install dependencies for native modules
RUN apt-get update && apt-get install -y \
    python3 \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy package files
COPY package.json package-lock.json ./

# Install production dependencies
RUN npm ci --only=production

# Copy source code
COPY src/ ./src/

# Set environment defaults
ENV NODE_ENV=production
ENV MCP_SCENARIO=full
ENV CHROMA_SERVER_URL=http://chromadb:8000
ENV NEO4J_URI=bolt://neo4j:7687
ENV NEO4J_USER=neo4j
ENV NEO4J_PASSWORD=password
ENV ENABLE_RAG=true
ENV ENABLE_GITHUB=true

# MCP servers use stdio transport by default
# For Gateway integration, we expose nothing (stdio is piped by Docker)
CMD ["node", "src/UnifiedMCPServer.js"]
```

### Step 2: Create Docker Compose for Full Stack
**Type**: file_creation
**Target**: docker-compose.mcp.yaml
**Description**: Docker Compose file for complete MCP stack with ChromaDB and Neo4j

```yaml
version: '3.8'

services:
  # MCP RAG Server - exposed to Gateway
  mcp-rag-server:
    build:
      context: ./mcp_server_node
      dockerfile: Dockerfile
    container_name: eib-mcp-rag
    environment:
      - MCP_SCENARIO=full
      - CHROMA_SERVER_URL=http://chromadb:8000
      - NEO4J_URI=bolt://neo4j:7687
      - NEO4J_USER=neo4j
      - NEO4J_PASSWORD=${NEO4J_PASSWORD:-password}
      - GITHUB_TOKEN=${GITHUB_TOKEN}
      - ENABLE_RAG=true
      - ENABLE_GITHUB=true
    depends_on:
      - chromadb
      - neo4j
    # No ports exposed - MCP Gateway connects via docker exec stdio
    networks:
      - mcp-network
    labels:
      - "mcp.server=true"
      - "mcp.name=eib-mcp-rag"
      - "mcp.description=EIB MCP RAG Server for Global Workflow"

  # ChromaDB Vector Database
  chromadb:
    image: chromadb/chroma:latest
    container_name: chromadb
    ports:
      - "8000:8000"
    volumes:
      - chromadb_data:/chroma/chroma
    environment:
      - IS_PERSISTENT=TRUE
      - ANONYMIZED_TELEMETRY=FALSE
    networks:
      - mcp-network

  # Neo4j Graph Database
  neo4j:
    image: neo4j:5-community
    container_name: neo4j
    ports:
      - "7474:7474"  # HTTP
      - "7687:7687"  # Bolt
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
    environment:
      - NEO4J_AUTH=neo4j/${NEO4J_PASSWORD:-password}
      - NEO4J_PLUGINS=["apoc"]
    networks:
      - mcp-network

volumes:
  chromadb_data:
  neo4j_data:
  neo4j_logs:

networks:
  mcp-network:
    driver: bridge
```

### Step 3: Create MCP Server Catalog Entry
**Type**: file_creation
**Target**: mcp_server_node/docker-mcp-catalog.yaml
**Description**: Docker MCP Catalog configuration for our server

```yaml
# Docker MCP Catalog Entry for EIB MCP RAG Server
# Used by: docker mcp catalog import ./docker-mcp-catalog.yaml

servers:
  eib-mcp-rag:
    description: "EIB MCP RAG Server - Global Workflow AI Assistant"
    image: eib-mcp-rag:latest
    build:
      context: .
      dockerfile: Dockerfile
    environment:
      - MCP_SCENARIO
      - CHROMA_SERVER_URL
      - NEO4J_URI
      - NEO4J_USER
      - NEO4J_PASSWORD
      - GITHUB_TOKEN
      - ENABLE_RAG
      - ENABLE_GITHUB
    secrets:
      - GITHUB_TOKEN
      - NEO4J_PASSWORD
    tools:
      # Workflow Info Tools
      - get_workflow_structure
      - get_system_configs
      - describe_component
      # Semantic Search Tools
      - search_documentation
      - search_ee2_standards
      - find_related_files
      - explain_with_context
      # EE2 Compliance Tools
      - analyze_ee2_compliance
      - generate_compliance_report
      - scan_repository_compliance
      - extract_code_for_analysis
      # Code Analysis Tools
      - analyze_code_structure
      - find_dependencies
      - trace_execution_path
      - find_callers_callees
      # Operational Tools
      - get_operational_guidance
      - explain_workflow_component
      - list_job_scripts
      # GitHub Tools
      - search_issues
      - get_pull_requests
    categories:
      - development
      - compliance
      - documentation
```

---

## Phase 11B: Docker MCP Gateway Configuration

### Step 4: Install Docker MCP CLI Plugin
**Type**: command_execution
**Description**: Install the Docker MCP CLI plugin for gateway management

```bash
# Clone and build the MCP Gateway plugin
git clone https://github.com/docker/mcp-gateway.git /tmp/mcp-gateway
cd /tmp/mcp-gateway
mkdir -p "$HOME/.docker/cli-plugins/"
make docker-mcp

# Verify installation
docker mcp --help
```

### Step 5: Initialize and Configure Gateway
**Type**: command_execution
**Description**: Initialize the Docker MCP catalog and enable our server

```bash
# Initialize the default Docker MCP Catalog
docker mcp catalog init

# Import our custom catalog
docker mcp catalog import ./mcp_server_node/docker-mcp-catalog.yaml

# Enable the EIB MCP RAG server
docker mcp server enable eib-mcp-rag

# Configure secrets (GitHub token)
docker mcp secret set GITHUB_TOKEN

# List enabled servers
docker mcp server ls
```

### Step 6: Start MCP Gateway in Streaming Mode
**Type**: command_execution
**Description**: Run the MCP Gateway for multi-client access

```bash
# Run gateway in streaming mode for LangFlow integration
docker mcp gateway run --port 8080 --transport streaming

# The gateway will be available at:
# - SSE: http://localhost:8080/sse
# - Messages: http://localhost:8080/messages
```

---

## Phase 11C: LangFlow Integration

### Step 7: Configure LangFlow MCP Component
**Type**: configuration
**Target**: LangFlow UI
**Description**: Add MCP Gateway as a tool source in LangFlow

**LangFlow Configuration**:
1. Add "MCP Client" component to canvas
2. Configure connection:
   - **Transport**: SSE
   - **URL**: `http://localhost:8080/sse`
   - **Messages Endpoint**: `http://localhost:8080/messages`
3. Connect to LLM component (Claude, GPT-4, etc.)

**Benefits for Development**:
- Visual tool chain debugging
- Intermediate response inspection
- Tool composition testing
- Prompt refinement with real-time feedback

### Step 8: Create Development Workflow in LangFlow
**Type**: documentation
**Description**: Example LangFlow workflow for EE2 compliance refinement

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   User Input    │────▶│  MCP Client     │────▶│   LLM (Claude)  │
│  "Analyze EVS   │     │  (Gateway)      │     │   with Context  │
│   compliance"   │     └────────┬────────┘     └────────┬────────┘
└─────────────────┘              │                       │
                                 │                       │
                    ┌────────────▼────────────┐          │
                    │  Tool: scan_repository  │          │
                    │  Tool: extract_code     │          │
                    │  Tool: generate_report  │          │
                    └────────────┬────────────┘          │
                                 │                       │
                    ┌────────────▼────────────┐          │
                    │  Intermediate Response  │◀─────────┘
                    │  (Visible in LangFlow)  │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   Final Analysis        │
                    │   with Recommendations  │
                    └─────────────────────────┘
```

---

## Phase 11D: Tool SOC Refinement Workflow

### Step 9: Iterative Tool Development Process
**Type**: methodology
**Description**: Process for refining tool Separation of Concerns using LangFlow

**Development Loop**:
1. **Observe**: Run tool chain in LangFlow, inspect intermediate JSON
2. **Identify**: Find verbose/missing/redundant data in tool responses
3. **Refine**: Update tool code in `mcp_server_node/src/tools/`
4. **Rebuild**: `docker compose build mcp-rag-server`
5. **Restart**: Gateway auto-reconnects to new container
6. **Validate**: Re-run in LangFlow, compare outputs

**SOC Refinement Targets** (from current session):
| Issue | Current Tool | Refinement Needed |
|-------|--------------|-------------------|
| LLM scope boundary | extract_code_for_analysis | Add "analyze ONLY provided snippets" instruction |
| Severity levels | All compliance tools | Add CRITICAL/WARNING/ADVISORY categorization |
| COM directory comparison | extract_code_for_analysis | Add optional `com_directory` parameter |
| bash -e handling | shebang prompts | Clarify `-e` flag is acceptable (stricter than required) |

---

## Validation

### Success Criteria
- [ ] MCP RAG server runs in Docker container
- [ ] Docker MCP Gateway connects to containerized server
- [ ] `docker mcp tools ls` shows all 32 tools
- [ ] LangFlow can invoke tools via Gateway
- [ ] Intermediate responses visible in LangFlow debug panel
- [ ] Tool refinements deployed via container rebuild

### Health Check Commands
```bash
# Check container status
docker ps | grep mcp

# Check gateway status
docker mcp server ls

# List available tools via gateway
docker mcp tools ls

# Test tool call
docker mcp tools call get_knowledge_base_status '{"detailed": true}'
```

---

## Dependencies

- Docker Desktop with MCP Toolkit enabled
- Docker MCP Gateway CLI plugin
- LangFlow (local or cloud instance)
- Existing ChromaDB and Neo4j data volumes

## Timeline

| Phase | Duration | Deliverable |
|-------|----------|-------------|
| 11A   | 1 day    | Dockerized MCP server |
| 11B   | 0.5 day  | Gateway configuration |
| 11C   | 0.5 day  | LangFlow integration |
| 11D   | Ongoing  | Tool refinement process |

---

## References

- [Docker MCP Gateway](https://github.com/docker/mcp-gateway)
- [MCP Specification](https://spec.modelcontextprotocol.io/)
- [LangFlow Documentation](https://docs.langflow.org/)
- [Docker MCP Catalog](https://hub.docker.com/mcp)
