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

---

## Phase 11E: KasmVNC Remote Desktop with SSO Integration

### Current State (Workaround)
KasmVNC is running on port 6080 but requires SSH local port forwarding:
```bash
ssh -L 6080:localhost:6080 Terry.McGuinness@3.236.197.228
# Then access http://localhost:6080
```

**Problem**: VS Code Dev Tunnels force HTTP→HTTPS redirect (308), breaking the KasmVNC web interface.

### Step 10: Fix VS Code Dev Tunnels HTTPS Protocol Mismatch
**Type**: configuration
**Description**: Configure KasmVNC to work with VS Code SSO-authenticated tunnels

**Option A: Enable KasmVNC SSL (Match Tunnel Expectations)**
```bash
# Re-enable SSL in KasmVNC config
cat > ~/.vnc/kasmvnc.yaml << 'EOF'
network:
  ssl:
    require_ssl: true
  websocket_port: 6080
EOF

# Restart VNC
vncserver -kill :1
sg kasmvnc-cert -c "vncserver :1 -geometry 1920x1080 -depth 24"

# Access via HTTPS tunnel
# https://lq79bhxl-6080.use.devtunnels.ms
```

**Option B: Use VS Code Port Forwarding Protocol Override**
1. In VS Code, open Ports panel
2. Right-click port 6080
3. Select "Change Port Protocol" → HTTPS
4. Accept self-signed certificate warning in browser

**Option C: Configure nginx Reverse Proxy (Production)**
```nginx
# /etc/nginx/conf.d/kasmvnc.conf
server {
    listen 6080 ssl;
    ssl_certificate /etc/pki/tls/certs/kasmvnc.pem;
    ssl_certificate_key /etc/pki/tls/private/kasmvnc.pem;
    
    location / {
        proxy_pass http://localhost:6081;  # KasmVNC internal port
        proxy_http_version 1.1;
        proxy_set_header Upgrade $websocket_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### Step 11: Update Provisioning Script for KasmVNC
**Type**: file_modification
**Target**: SETUP/provisioning/09-desktop-vnc.sh
**Description**: Update VNC provisioning to use KasmVNC properly

**Key Fixes**:
1. Detect existing KasmVNC (don't install tigervnc-server)
2. Auto-add user to `kasmvnc-cert` group
3. Configure SSL-enabled by default
4. Create systemd user service for auto-start
5. Document SSH tunnel and HTTPS tunnel access methods

### Step 12: KasmVNC Systemd User Service
**Type**: file_creation
**Target**: ~/.config/systemd/user/kasmvnc.service
**Description**: Auto-start KasmVNC on login

```ini
[Unit]
Description=KasmVNC Server
After=network.target

[Service]
Type=forking
ExecStart=/usr/bin/vncserver :1 -geometry 1920x1080 -depth 24
ExecStop=/usr/bin/vncserver -kill :1
Restart=on-failure

[Install]
WantedBy=default.target
```

**Enable**:
```bash
systemctl --user daemon-reload
systemctl --user enable kasmvnc
systemctl --user start kasmvnc
```

### Validation
- [ ] KasmVNC accessible via VS Code HTTPS tunnel (no SSH workaround)
- [ ] Multiple users can connect (Terry.McGuinness, Anna.Smoot)
- [ ] Auto-start on login via systemd user service
- [ ] Provisioning script updated for new instances

---

## References

- [Docker MCP Gateway](https://github.com/docker/mcp-gateway)
- [MCP Specification](https://spec.modelcontextprotocol.io/)
- [LangFlow Documentation](https://docs.langflow.org/)
- [Docker MCP Catalog](https://hub.docker.com/mcp)
- [KasmVNC Documentation](https://kasmweb.com/kasmvnc)
---

## Implementation Status

**Last Updated**: December 17, 2025

### Phase 11A: Dockerize MCP RAG Server ✅ COMPLETE

| Step | Status | Notes |
|------|--------|-------|
| Create Dockerfile | ✅ Complete | `SETUP/dockerfiles/Dockerfile.mcp-server` |
| Create Docker Compose | ✅ Complete | `docker-compose.mcp-standalone.yaml` |
| Add Gateway metadata label | ✅ Complete | `io.docker.server.metadata` JSON label |
| Build and test image | ✅ Complete | `eib-mcp-rag:latest` with 32 tools |

**Implementation Details**:
- Dockerfile location: `SETUP/dockerfiles/Dockerfile.mcp-server`
- Compose file: `docker-compose.mcp-standalone.yaml`
- Environment variables: `CHROMADB_HOST`, `CHROMADB_PORT`, `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`
- Gateway label format: JSON (not YAML) for reliable parsing

### Phase 11B: Docker MCP Gateway Plugin ✅ COMPLETE

| Step | Status | Notes |
|------|--------|-------|
| Clone mcp-gateway repo | ✅ Complete | `supported_repos/mcp-gateway/` |
| Build docker-mcp plugin | ✅ Complete | Go 1.25.3, v0.34.0 |
| Install plugin | ✅ Complete | `~/.docker/cli-plugins/docker-mcp` |
| Test gateway discovery | ✅ Complete | 32 tools discovered |

**Key Finding**: Docker CE requires PR #301 fix (merged Dec 12, 2025). We rebuilt from source to include this fix.

**Working Commands**:
```bash
# Build image
docker compose -f docker-compose.mcp-standalone.yaml build eib-mcp-rag

# Test gateway discovery (dry-run)
docker mcp gateway run --servers docker://eib-mcp-rag:latest --dry-run --verbose

# Start gateway with SSE transport for LangFlow
docker mcp gateway run --servers eib-mcp-rag --transport sse --port 8888 --long-lived --verbose
```

### Phase 11C: Container Network Integration ✅ COMPLETE

| Step | Status | Notes |
|------|--------|-------|
| Connect to DB network | ✅ Complete | `global-workflow-mcp-rag` network |
| Test ChromaDB connection | ✅ Complete | 12 collections, 14,856 documents |
| Test Neo4j connection | ✅ Complete | 85,894 relationships |
| Test MCP tools | ✅ Complete | `get_knowledge_base_status`, `search_documentation` |

**Network Architecture**:
- The Docker MCP Gateway runs containers in isolation (security feature)
- For RAG-enabled servers requiring DB access, run container directly on shared network
- ChromaDB connected to both `bridge` and `global-workflow-mcp-rag` networks

**Working Container Command**:
```bash
docker run -d --name eib-mcp-standalone \
  --network global-workflow-mcp-rag \
  -e CHROMADB_HOST=chromadb \
  -e CHROMADB_PORT=8000 \
  -e NEO4J_URI=bolt://neo4j:7687 \
  -e NEO4J_USER=neo4j \
  -e NEO4J_PASSWORD=gfsworkflow2025 \
  eib-mcp-rag:latest
```

### Phase 11D: LangFlow Integration ✅ COMPLETE

| Step | Status | Notes |
|------|--------|-------|
| Configure Docker MCP catalog | ✅ Complete | `~/.docker/mcp/catalogs/eib-local.yaml` |
| Configure Docker MCP registry | ✅ Complete | `~/.docker/mcp/registry.yaml` |
| Start gateway with SSE transport | ✅ Complete | Port 8888, 32 tools available |
| Register server in LangFlow | ✅ Complete | `/api/v2/mcp/servers/eib-mcp-rag` |
| Connect LangFlow to gateway | ✅ Complete | SSE transport, bearer token auth |
| Test tool invocation | ✅ Complete | Tools accessible from LangFlow UI |

**LangFlow Configuration (December 17, 2025)**:

1. **Docker MCP Catalog** (`~/.docker/mcp/catalogs/eib-local.yaml`):
```yaml
version: 3
name: eib-local
displayName: EIB Local MCP Catalog
registry:
  eib-mcp-rag:
    title: EIB MCP RAG Server
    description: AI-powered code analysis and EE2 compliance checking for NOAA Global Workflow
    type: server
    image: eib-mcp-rag:latest
    env:
      - name: CHROMADB_HOST
        value: chromadb
      - name: CHROMADB_PORT
        value: "8000"
      - name: NEO4J_URI
        value: bolt://global-workflow-neo4j:7687
      - name: NEO4J_USER
        value: neo4j
      - name: NEO4J_PASSWORD
        value: gfsworkflow2025
      - name: MCP_SCENARIO
        value: full
    metadata:
      category: devops
```

2. **Start Gateway**:
```bash
# Start with SSE transport (required for LangFlow)
docker mcp gateway run --servers eib-mcp-rag --transport sse --port 8888 --long-lived --verbose

# Output includes bearer token for authentication:
# > Gateway URL: http://localhost:8888/sse
# > Use Bearer token: Authorization: Bearer <generated-token>
```

3. **Register in LangFlow** (via API):
```bash
curl -X POST "http://localhost:7860/api/v2/mcp/servers/eib-mcp-rag" \
  -H "Authorization: Bearer <langflow-jwt>" \
  -H "Content-Type: application/json" \
  -d '{
    "transport": "sse",
    "url": "http://host.docker.internal:8888/sse",
    "headers": {
      "Authorization": "Bearer <gateway-token>"
    }
  }'
```

4. **LangFlow UI**: Select `eib-mcp-rag` in MCP Tools component → 32 tools available

**Key Learnings**:
- Use `--transport sse` (not `streamable-http`) for LangFlow compatibility
- Use `http://host.docker.internal:8888/sse` from LangFlow container
- Gateway generates new bearer token on each restart
- `--long-lived` flag maintains stateful connections for database access

### Commits

| Commit | Description |
|--------|-------------|
| `678fd69` | feat(Phase 11): Docker MCP Gateway integration |
| `1a6641b` | fix: Update MCP server container config for DB connectivity |
| `TBD` | feat(Phase 11D): Complete LangFlow integration |

### Provisioning Script

See `SETUP/bin/start-mcp-gateway.sh` for automated gateway startup with LangFlow integration

---

## Phase 11E: n8n Workflow Automation (Alternative to LangFlow)

**Status**: 🔄 IN PROGRESS  
**Start Date**: December 17, 2025

### Rationale

LangFlow v1.6.9 has critical bugs in its MCP client implementation:
1. **Dictionary race condition** (line 637): `for session_id, session_info in sessions.items()` - dict modified during iteration
2. **asyncio scoping bug** (line 1388): `import asyncio` inside try block goes out of scope in except block

While we applied patches to fix these issues, they are lost on container restart and require re-application. n8n provides a more stable, production-ready alternative for workflow automation.

### n8n Overview

- **License**: Fair-code (source-available, free for self-hosting)
- **Repository**: https://github.com/n8n-io/n8n (45k+ stars)
- **Docker**: `n8nio/n8n:latest`
- **Maturity**: 5+ years in production

### n8n vs LangFlow Comparison

| Feature | n8n | LangFlow |
|---------|-----|----------|
| **Stability** | Very mature, production-ready | Newer, has bugs |
| **MCP Support** | Via HTTP Request node | Native but buggy |
| **Docker** | Official well-tested image | Works but fragile |
| **AI/LLM** | Good integrations | AI-first design |
| **Workflows** | Event-driven, robust | AI agent focused |
| **Community** | Large, active | Growing |

### Step 1: n8n Docker Deployment

**Target**: docker-compose.devops.yaml (add n8n service)

```yaml
  n8n:
    image: n8nio/n8n:latest
    container_name: global-workflow-n8n
    restart: unless-stopped
    ports:
      - "5678:5678"
    environment:
      - N8N_BASIC_AUTH_ACTIVE=true
      - N8N_BASIC_AUTH_USER=admin
      - N8N_BASIC_AUTH_PASSWORD=eib-n8n-2025
      - N8N_HOST=localhost
      - N8N_PORT=5678
      - N8N_PROTOCOL=http
      - WEBHOOK_URL=http://localhost:5678/
    volumes:
      - n8n_data:/home/node/.n8n
    networks:
      - global-workflow-mcp-rag
```

### Step 2: MCP Gateway Connection via HTTP Request Node

n8n connects to MCP Gateway using its HTTP Request node:

1. **Gateway Endpoint**: `http://host.docker.internal:8888/sse`
2. **Transport**: Server-Sent Events (SSE)
3. **Authentication**: Bearer token header
4. **Method**: POST for tool invocation

Example HTTP Request node configuration:
```json
{
  "method": "POST",
  "url": "http://host.docker.internal:8888/sse",
  "headers": {
    "Authorization": "Bearer eib-mcp-token-2025",
    "Content-Type": "application/json"
  },
  "body": {
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "search_documentation",
      "arguments": {
        "query": "EE2 compliance",
        "max_results": 5
      }
    },
    "id": 1
  }
}
```

### Step 3: Example n8n Workflows

#### Workflow 1: EE2 Compliance Check
```
Trigger (Manual/Webhook)
    → HTTP Request: search_documentation (EE2 standards)
    → HTTP Request: scan_repository_compliance
    → HTTP Request: generate_compliance_report
    → Send Email/Slack notification
```

#### Workflow 2: Code Analysis Pipeline
```
GitHub Webhook (PR opened)
    → HTTP Request: analyze_code_structure
    → HTTP Request: find_dependencies
    → IF compliance issues
        → HTTP Request: explain_with_context
        → Post PR comment
```

### Verification Checklist

- [ ] n8n container running on port 5678
- [ ] HTTP Request node connects to MCP Gateway
- [ ] Bearer token authentication working
- [ ] Tool invocation returns valid JSON-RPC response
- [ ] Sample workflow executes successfully

### Reference

- n8n Documentation: https://docs.n8n.io/
- n8n Docker Setup: https://docs.n8n.io/hosting/installation/docker/
- MCP JSON-RPC Spec: https://spec.modelcontextprotocol.io/