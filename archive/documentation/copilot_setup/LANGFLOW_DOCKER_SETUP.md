# LangFlow Docker Setup - Progress Update

**Date**: 2025-10-10  
**Phase**: 3 (Continued)  
**Status**: LangFlow Successfully Deployed ✅

---

## 🎯 Objective

Set up LangFlow RAG pipeline visualizer using Docker Compose with proper integration to the persistent ChromaDB service.

---

## ✅ Accomplishments

### 1. Docker Compose Configuration
**File**: `/mcp_rag_eib/SETUP/docker-compose.yml`

**Key Changes**:
- Removed ChromaDB service (now runs as systemd service)
- Updated to use environment variables from `mcp_env.sh`
- Configured LangFlow to connect to host ChromaDB on port 8080
- Updated volume paths to use `${PERSISTENT_ROOT}` variable
- Removed obsolete `version: '3.8'` field

**Configuration Highlights**:
```yaml
services:
  langflow:
    ports:
      - "7860:7860"
    environment:
      - CHROMA_HOST=host.docker.internal
      - CHROMA_PORT=${CHROMADB_PORT:-8080}
    extra_hosts:
      - "host.docker.internal:host-gateway"
    volumes:
      - langflow-data:/app/langflow-data

volumes:
  langflow-data:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: ${PERSISTENT_ROOT:-/mcp_rag_eib}/data/langflow
```

### 2. LangFlow Dockerfile
**File**: `/mcp_rag_eib/SETUP/dockerfiles/Dockerfile.langflow`

**Configuration**:
- Based on `langflowai/langflow:latest`
- Custom environment variables
- Persistent data directory
- Health check endpoint

### 3. Startup Script
**File**: `/mcp_rag_eib/SETUP/start-langflow.sh`

**Features**:
- Automatic environment loading
- ChromaDB connection verification
- Docker Compose orchestration
- Service health checks
- User-friendly status display

**Usage**:
```bash
/mcp_rag_eib/SETUP/start-langflow.sh
```

### 4. Service Deployment
**Container**: `global-workflow-langflow`

**Status**: ✅ Running and healthy

**Details**:
- Image built successfully (4.77GB, includes all dependencies)
- Container started and passed health checks
- Accessible at http://127.0.0.1:7860
- Integrated with ChromaDB via `host.docker.internal:8080`

---

## 📊 Current System Status

### Services Running

#### ChromaDB (Systemd Service)
```
Service: chromadb-persistent.service
Status:  ✅ Active (running)
Port:    8080
API:     http://127.0.0.1:8080/api/v1/heartbeat
Data:    /mcp_rag_eib/data/chromadb
```

#### LangFlow (Docker Container)
```
Container: global-workflow-langflow
Status:    ✅ Up (healthy)
Port:      7860
URL:       http://127.0.0.1:7860
Data:      /mcp_rag_eib/data/langflow
Username:  admin
Password:  admin123
```

### Architecture

```
Host System (Rocky Linux 9)
├── ChromaDB (Systemd Service)
│   ├── Port: 8080
│   ├── Virtual env: /mcp_rag_eib/etc/chromadb/venv
│   └── Data: /mcp_rag_eib/data/chromadb
│
└── LangFlow (Docker Container)
    ├── Port: 7860
    ├── Connects to: host.docker.internal:8080
    └── Data: /mcp_rag_eib/data/langflow (bind mount)
```

---

## 🔧 Technical Details

### Docker Compose Environment Variable Substitution

Docker Compose automatically substitutes environment variables:
- `${VARIABLE}` - Direct substitution
- `${VARIABLE:-default}` - Use default if not set
- Works with variables from shell environment

**Example**:
```bash
source /mcp_rag_eib/SETUP/mcp_env.sh  # Sets PERSISTENT_ROOT
cd /mcp_rag_eib/SETUP
docker compose up -d                   # Uses PERSISTENT_ROOT automatically
```

### Host-to-Container Communication

LangFlow container accesses host ChromaDB using:
```yaml
environment:
  - CHROMA_HOST=host.docker.internal
  - CHROMA_PORT=8080
extra_hosts:
  - "host.docker.internal:host-gateway"
```

This allows the container to reach services on the host system.

---

## 🎓 Lessons Learned

### What Worked Well ✅

1. **Environment Variable Integration**: Using `$PERSISTENT_ROOT` in docker-compose.yml makes configuration portable and consistent

2. **Host Docker Access**: `host.docker.internal` allows Docker containers to easily access host services (ChromaDB on port 8080)

3. **Bind Mounts**: Using bind mounts to persistent storage ensures LangFlow data survives container restarts

4. **Modern Docker Compose**: Using `docker compose` (with space) instead of `docker-compose` (with dash) is the current standard

5. **Startup Script**: Automated script with environment checks and health validation streamlines deployment

### Important Notes 📝

1. **Version Field Obsolete**: The `version:` field in docker-compose.yml is no longer needed in modern Docker Compose

2. **Image Size**: LangFlow image is large (~4.77GB) - includes Python environment and all ML dependencies

3. **Startup Time**: Container takes ~15 seconds to become healthy after starting

4. **Data Persistence**: All data stored in `/mcp_rag_eib/data/langflow` survives container rebuilds

---

## 🧪 Testing and Verification

### Service Health Checks

```bash
# ChromaDB
curl -s http://127.0.0.1:8080/api/v1/heartbeat

# LangFlow
curl -s http://127.0.0.1:7860/

# Docker container status
cd /mcp_rag_eib/SETUP
docker compose ps
```

### Expected Results

- **ChromaDB**: Returns heartbeat with nanosecond timestamp
- **LangFlow**: Returns HTML page (200 OK)
- **Container**: Shows status as "Up (healthy)"

---

## 📁 Files Created/Modified

### New Files
- `/mcp_rag_eib/SETUP/docker-compose.yml` - Docker Compose configuration
- `/mcp_rag_eib/SETUP/dockerfiles/Dockerfile.langflow` - LangFlow custom image
- `/mcp_rag_eib/SETUP/start-langflow.sh` - Startup script

### Directories Created
- `/mcp_rag_eib/data/langflow` - Persistent LangFlow data (mode 777)
- `/mcp_rag_eib/SETUP/dockerfiles/` - Docker build files

---

## 🚀 Usage Instructions

### Start LangFlow
```bash
# Option 1: Use startup script
/mcp_rag_eib/SETUP/start-langflow.sh

# Option 2: Manual start
source /mcp_rag_eib/SETUP/mcp_env.sh
cd /mcp_rag_eib/SETUP
docker compose up -d langflow
```

### Stop LangFlow
```bash
cd /mcp_rag_eib/SETUP
docker compose stop langflow
```

### View Logs
```bash
cd /mcp_rag_eib/SETUP
docker compose logs -f langflow
```

### Restart LangFlow
```bash
cd /mcp_rag_eib/SETUP
docker compose restart langflow
```

### Remove LangFlow (keeps data)
```bash
cd /mcp_rag_eib/SETUP
docker compose down
# Data persists in /mcp_rag_eib/data/langflow
```

---

## 🔜 Next Steps

### Immediate

1. ✅ LangFlow deployed and accessible
2. ✅ Connected to ChromaDB on host
3. ⏳ Configure LangFlow RAG pipeline
4. ⏳ Test ChromaDB integration in LangFlow UI

### Upcoming (Phase 3 Continuation)

1. **MCP Server Service**: Create systemd service for MCP server
2. **VS Code Integration**: Configure `.vscode/mcp.json`
3. **Test MCP Tools**: Verify MCP tools can access ChromaDB
4. **Documentation Ingestion**: Populate ChromaDB with workflow docs

---

## 📊 Resource Usage

### Disk Space
```
LangFlow Image: ~4.77GB
LangFlow Data:  <10MB (initial)
Total Added:    ~4.78GB
Remaining:      ~19GB on /mcp_rag_eib
```

### Memory
```
LangFlow Container: ~200-300MB (running)
```

### Network
```
Port 7860: LangFlow UI
Port 8080: ChromaDB (host service)
```

---

**Status**: Phase 3 progressing smoothly  
**Next**: MCP Server systemd service configuration  
**Updated**: 2025-10-10 17:15 UTC  
**Progress**: ~50% Complete
