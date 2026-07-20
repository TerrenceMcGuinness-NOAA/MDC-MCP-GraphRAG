# MCP RAG Infrastructure Setup

**Version**: 3.2.0  
**Status**: ✅ Production Ready with Neo4j Graph Database  
**Last Updated**: 2025-01-15

---

## Quick Start

### 1. Initial Provisioning (One-Time)
```bash
cd /mcp_rag_eib/SETUP
sudo ./provision_mcp_rag_persistent.sh
```

### 2. Setup Spack Environment (v3.0.8+)
```bash
# Load Spack modules for ChromaDB
source /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node/setup-spack-chromadb.sh

# Install ChromaDB (if not already installed)
pip3 install --user chromadb

# Verify
python3 -c "import chromadb; print(f'ChromaDB {chromadb.__version__}')"
```

### 3. Verify Services
```bash
# ChromaDB (systemd service)
systemctl status chromadb-persistent.service
curl http://127.0.0.1:8080/api/v1/heartbeat

# Neo4j (Docker service)
docker compose ps neo4j
./test-neo4j.sh

# LangFlow (Docker service)
docker compose ps langflow
curl http://localhost:7860/api/v1/health
```

### 3. Access Web Interfaces
- **ChromaDB**: http://localhost:8080 (REST API only)
- **Neo4j Browser**: http://localhost:7474 (neo4j / gfsworkflow2025)
- **LangFlow UI**: http://localhost:7860 (admin / admin123)

---

## Architecture Overview

### Hybrid Triple-Store RAG System (v3.0.8+)

```
┌───────────────────────────────────────────────────────┐
│  MCP RAG Infrastructure (v3.0.8)                      │
├───────────────────────────────────────────────────────┤
│                                                       │
│  Spack Package Manager       100+ Packages            │
│  ├─ Python 3.11.14 (module-managed)                   │
│  ├─ FastAPI, Uvicorn, Pydantic (Lmod hierarchy)       │
│  └─ No virtual environments (user site-packages)      │
│                                                       │
│  ChromaDB (systemd)         Port 8080                 │
│  ├─ Vector embeddings for semantic similarity         │
│  └─ Uses Spack Python environment                     │
│                                                       │
│  Neo4j (Docker)             Ports 7474, 7687          │
│  ├─ Graph relationships for structural queries        │
│  ├─ APOC procedures library                           │
│  └─ Graph Data Science (GDS) algorithms               │
│                                                       │
│  LangFlow (Docker)          Port 7860                 │
│  └─ RAG pipeline visualization and testing            │
│                                                       │
│  MCP Server (Node.js)       21 Tools                  │
│  ├─ 9 Workflow tools (RAG-enhanced)                   │
│  ├─ 5 GitHub ecosystem tools                          │
│  ├─ 3 Neo4j graph tools                               │
│  └─ 4 Operational tools                               │
│                                                       │
└───────────────────────────────────────────────────────┘
```

### Storage Layout
```
/mcp_rag_eib/ (25GB persistent mount)
├── data/
│   ├── chromadb/           # Vector database
│   ├── neo4j/              # Graph database
│   │   ├── data/           # Neo4j DB files
│   │   ├── logs/           # Server logs
│   │   ├── import/         # Import staging
│   │   └── plugins/        # APOC + GDS
│   └── langflow/           # LangFlow configs
├── etc/
│   └── chromadb/           # [DEPRECATED] Old venv (removed v3.0.8)
├── mcp_server_node/        # MCP server
│   ├── src/                # Server source code
│   ├── database/           # Local caches
│   └── knowledge-base/     # Ingested docs
├── cache/                  # Build caches
│   ├── transformers/       # HuggingFace models
│   ├── npm/                # Node.js packages
│   └── pip/                # Python packages (user site-packages)
└── spack/                  # Spack package manager (v3.0.8+)
    ├── opt/                # 100+ installed packages
    ├── share/spack/lmod/   # Module files (Lmod hierarchy)
    └── bin/                # Spack executable
```

---

## Documentation Index

### Getting Started
- **[README_PROVISIONING_V3.1_COMPLETE.md](README_PROVISIONING_V3.1_COMPLETE.md)** - ChromaDB provisioning guide (v3.1.0)
- **[NEO4J_INTEGRATION_COMPLETE.md](NEO4J_INTEGRATION_COMPLETE.md)** - Neo4j integration summary (v3.2.0) ⬅️ **NEW**
- **[README_NEO4J.md](README_NEO4J.md)** - Complete Neo4j guide with Phase 0 POC plan ⬅️ **NEW**

### Configuration
- **[mcp_env.sh](mcp_env.sh)** - Central environment variables (v3.1.0)
- **[docker-compose.yml](docker-compose.yml)** - Docker services configuration
- **[dockerfiles/](dockerfiles/)** - Custom Docker images
  - `Dockerfile.langflow` - LangFlow image
  - `Dockerfile.neo4j` - Neo4j with APOC + GDS ⬅️ **NEW**

### Scripts
- **[provision_mcp_rag_persistent.sh](provision_mcp_rag_persistent.sh)** - Main provisioning script (v3.2.0)
- **[bootstrap.sh](bootstrap.sh)** - VM initial setup (v2.0.0)
- **[install-mcp-service.sh](install-mcp-service.sh)** - MCP systemd service installer

### Testing
- **[test-chromadb-collection.py](test-chromadb-collection.py)** - ChromaDB collection test
- **[test-mcp-server.sh](test-mcp-server.sh)** - MCP server validation
- **[test-mcp-rest-api.sh](test-mcp-rest-api.sh)** - MCP REST API test
- **[test-vscode-mcp.sh](test-vscode-mcp.sh)** - VS Code MCP integration test
- **[test-neo4j.sh](test-neo4j.sh)** - Neo4j comprehensive test ⬅️ **NEW**
- **[check-mcp-status.sh](check-mcp-status.sh)** - Quick health check

### Templates
- **[bashrc_template](bashrc_template)** - Standard .bashrc for VMs
- **[bash_profile_template](bash_profile_template)** - Shell environment with modules + MCP

---

## Service Management

### ChromaDB (systemd)
```bash
# Status
systemctl status chromadb-persistent.service

# Start/Stop
sudo systemctl start chromadb-persistent.service
sudo systemctl stop chromadb-persistent.service

# Logs
journalctl -u chromadb-persistent.service -f

# Health Check
curl http://127.0.0.1:8080/api/v1/heartbeat
```

### Neo4j (Docker)
```bash
# Start
cd /mcp_rag_eib/SETUP
docker compose up -d neo4j

# Stop
docker compose stop neo4j

# Logs
docker compose logs neo4j -f

# Test
./test-neo4j.sh

# Interactive Cypher Shell
docker compose exec neo4j cypher-shell -u neo4j -p gfsworkflow2025
```

### LangFlow (Docker)
```bash
# Start
docker compose up -d langflow

# Stop
docker compose stop langflow

# Logs
docker compose logs langflow -f

# Health Check
curl http://localhost:7860/api/v1/health
```

### All Docker Services
```bash
# Status
docker compose ps

# Start All
docker compose up -d

# Stop All
docker compose down

# Rebuild
docker compose up -d --build
```

### MCP Container Cleanup (Phase 23)
The smart container cleanup service manages Docker MCP Gateway container lifecycle:

```bash
# Timer Status
systemctl list-timers mcp-container-cleanup.timer

# Manual Run (Dry Run - see what would happen)
MCP_CLEANUP_DRY_RUN=true /opt/eib-mcp-rag/bin/mcp-container-cleanup.sh

# Manual Run (Actually clean up)
systemctl start mcp-container-cleanup.service

# View Logs
journalctl -u mcp-container-cleanup.service -f

# Check Current MCP Containers
docker ps --filter "label=docker-mcp=true" --format 'table {{.Names}}\t{{.Status}}\t{{.CreatedAt}}'
```

**Cleanup Algorithm**:
1. Unhealthy containers → Immediate cleanup
2. Containers with active TCP connections → Preserved (never interrupted)
3. No connections + age > 30 min → Cleanup (orphaned)
4. No connections + age < 30 min → Grace period (may reconnect)

**Configuration** (via environment variables):
- `MCP_CLEANUP_GRACE_MINUTES=30` - Grace period for disconnected containers
- `MCP_CLEANUP_DRY_RUN=true` - Preview mode (no actual cleanup)

---

## Environment Variables

Source the central environment configuration:
```bash
source /mcp_rag_eib/SETUP/mcp_env.sh
```

**Key Variables**:
- `PERSISTENT_ROOT` - `/mcp_rag_eib`
- `CHROMADB_URL` - `http://127.0.0.1:8080`
- `CHROMADB_PORT` - `8080`
- `MCP_ROOT` - `/mcp_rag_eib/eib-mcp-rag-server/mcp_server_node`
- `GW_REPO` - `/mcp_rag_eib/global-workflow_MCP_node.js-RAG`

---

## Version History

### v3.2.0 (2025-01-15) - Neo4j Integration
✅ Neo4j 5.15.0 graph database added  
✅ APOC + GDS plugins enabled  
✅ Persistent volumes for Neo4j data  
✅ Updated provisioning script with Docker Compose orchestration  
✅ Comprehensive test suite (`test-neo4j.sh`)  
✅ Phase 0 POC documentation ready  

### v3.1.0 (2025-01-10) - ChromaDB Upgrade
✅ ChromaDB 0.4.15 → 1.1.1 (API v2 support)  
✅ Node.js client chromadb@3.0.17 (breaking changes)  
✅ FastAPI 0.95.2 → 0.119.0 (Pydantic v2)  
✅ Lightweight venv (~480MB vs 7.1GB)  
✅ Module system integration (Python 3.11)  
✅ Fresh start option: `--fresh` flag  

### v3.0.0 (2024-12-15) - Persistent Architecture
✅ Complete redesign for `/mcp_rag_eib` mount  
✅ ChromaDB as systemd service  
✅ MCP server Node.js implementation  
✅ No `/contrib` dependencies  
✅ Cache storage for rebuilds  

---

## Troubleshooting

### ChromaDB Not Starting
```bash
# Check logs
journalctl -u chromadb-persistent.service -f

# Verify venv
source /mcp_rag_eib/etc/chromadb/venv/bin/activate
python -c "import chromadb; print(chromadb.__version__)"

# Rebuild with fresh option
sudo ./provision_mcp_rag_persistent.sh --fresh
```

### Neo4j Container Issues
```bash
# Check container status
docker compose ps neo4j

# View logs
docker compose logs neo4j

# Restart service
docker compose restart neo4j

# Full rebuild
docker compose down
docker compose build neo4j
docker compose up -d neo4j
```

### Docker Group Membership
```bash
# Add user to docker group
sudo usermod -aG docker $USER

# Log out and back in
exit

# Verify
docker ps  # Should work without sudo
```

### Port Conflicts
```bash
# Check if ports are in use
netstat -tuln | grep -E '8080|7474|7687|7860'

# Stop conflicting services
sudo systemctl stop <service>

# Or change ports in docker-compose.yml
```

---

## Phase 0 POC - Next Milestone

**Objective**: Prove Neo4j value with structural queries impossible for ChromaDB vectors

**Timeline**: 2-day weekend project

**Tasks**:
1. Parse `.gitmodules` → Submodule relationship graph
2. Parse `CMakeLists.txt` → Build dependency graph
3. Create 3 demo queries showing structural insights
4. Stakeholder presentation

**Success Criteria**:
- 50+ nodes, 100+ relationships ingested
- 3 actionable queries demonstrating graph value
- Stakeholder approval to proceed to Phase 1

**Documentation**: See [README_NEO4J.md](README_NEO4J.md) for complete Phase 0 plan

---

## Resources

### Internal Documentation
- **Global Workflow Wiki**: `/mcp_rag_eib/global-workflow.wiki/`
- **Enhanced Ingestion Architecture**: `../global-workflow_MCP_node.js-RAG/ENHANCED_INGESTION_ARCHITECTURE.md`
- **Changelog**: `../global-workflow_MCP_node.js-RAG/changelog.md`

### External Links
- **ChromaDB Docs**: https://docs.trychroma.com/
- **Neo4j Cypher Manual**: https://neo4j.com/docs/cypher-manual/current/
- **APOC Documentation**: https://neo4j.com/docs/apoc/current/
- **GDS Documentation**: https://neo4j.com/docs/graph-data-science/current/
- **LangFlow Docs**: https://docs.langflow.org/

### Support
- **GitHub Issues**: https://github.com/NOAA-EMC/global-workflow
- **NOAA EMC**: https://www.emc.ncep.noaa.gov/

---

## Quick Reference

### Start Everything (Fresh VM)
```bash
# 1. Run provisioning
cd /mcp_rag_eib/SETUP
sudo ./provision_mcp_rag_persistent.sh

# 2. Log out and back in (docker group)
exit

# 3. Source environment
source /mcp_rag_eib/SETUP/mcp_env.sh

# 4. Verify services
systemctl status chromadb-persistent.service
docker compose ps
./test-neo4j.sh
```

### Daily Operations
```bash
# Check everything
check-mcp-status.sh

# Restart ChromaDB
sudo systemctl restart chromadb-persistent.service

# Restart Docker services
docker compose restart

# View all logs
journalctl -u chromadb-persistent.service -f &
docker compose logs -f &
```

## Nightly RAG Benchmark Harness (SDD Phase 71)

Schedules the RAG benchmark nightly so `get_quality_metrics` returns real data
and `--compare` works. The harness appends one snapshot per run to
`quality_metrics.jsonl` (the file `get_quality_metrics` reads), rotates old
runs, and emits a fail-loud structured ERROR log on quality regressions.

Files:
- `mcp_server_python/scripts/run_benchmark_nightly.sh` — wrapper (sources
  secrets, runs the harness, appends/rotates the JSONL, regression check)
- `SETUP/systemd/mcp-benchmark.service` — oneshot service (runs the wrapper)
- `SETUP/systemd/mcp-benchmark.timer` — fires nightly at **02:30 UTC**
- `SETUP/systemd/install-benchmark-timer.sh` — installer

Install (root):
```bash
sudo /mcp_rag_eib/eib-mcp-rag-server/SETUP/systemd/install-benchmark-timer.sh
```

Operational commands:
```bash
# Run once now (also the smoke test):
systemctl start mcp-benchmark.service

# Confirm the timer is armed with a next-run inside 24h:
systemctl list-timers mcp-benchmark.timer

# Follow logs / find regressions:
journalctl -u mcp-benchmark.service -f
journalctl -u mcp-benchmark.service | grep rag_quality_regression

# Uninstall:
sudo /mcp_rag_eib/eib-mcp-rag-server/SETUP/systemd/install-benchmark-timer.sh --uninstall
```

Key environment variables (set in the `.service`, all have safe defaults):
- `MCP_HOST_STATE_DIR` — host dir holding `quality_metrics.jsonl`
  (default `/mcp_rag_eib/data/mcp-server/state`).
- `MCP_CONTAINER_STATE_DIR` — host path bind-mounted to the container's
  `/app/sdd_framework/execution_state`, so the in-container
  `get_quality_metrics` sees the file. Set this to the RW-mount source.
- `MCP_BENCHMARK_KEEP_RUNS` (default `90`), `MCP_BENCHMARK_REGRESSION_PCT`
  (default `10`), `MCP_BENCHMARK_MEDIAN_WINDOW` (default `7`).

Notes:
- Each JSONL line is one benchmark **run** (nested `categories` + `overall`) —
  the schema `get_quality_metrics` contracts for; `--compare` diffs the last
  two runs. (This corrects the draft spec's "one line per category" wording,
  which would have broken `--compare`.)
- The harness is `mcp_server_node/scripts/run_benchmark.js` (in-process tool
  calls over the 6-category corpus at `test/benchmark/ground_truth.json`); it
  needs ChromaDB + Neo4j reachable. The AWS-only `config/benchmark_runner.py`
  is **not** used here.

---

**Status**: ✅ **Production Ready**  
**Owner**: NOAA EMC Global Workflow Team  
**Last Updated**: 2025-01-15
