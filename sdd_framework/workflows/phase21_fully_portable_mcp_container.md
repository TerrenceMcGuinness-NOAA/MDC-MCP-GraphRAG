# Phase 21: Fully Portable MCP Container (Standalone Deployment)

**Description**: Create a fully self-contained Docker image that runs the MCP RAG server independently of the host VM, enabling deployment to any Docker-capable environment (AWS ECS, Kubernetes, other VMs, developer laptops).

**Priority**: MEDIUM (Long-term infrastructure goal)
**Timeline**: Q2-Q3 2025
**Status**: PLANNING
**Depends On**: Phase 11 (Docker MCP Gateway) ✅ COMPLETE, Phase 12 (DevOps GitFlow) 🔄 IN PROGRESS

---

## Problem Statement

### Current Limitations

The current `eib-mcp-rag:latest` container **cannot run independently** because:

1. **Volume Dependencies**: Requires host mounts for `supported_repos/` and `sdd_framework/`
2. **Database Dependencies**: Requires separate ChromaDB and Neo4j containers with pre-populated data
3. **Network Dependencies**: Must join existing Docker network to reach databases
4. **Data Dependencies**: RAG embeddings (14,856 docs) exist only in external ChromaDB volume

### Current Architecture (Phase 11)

```
Host VM (required)
├── /mcp_rag_eib/supported_repos/global-workflow  → mounted into container
├── /mcp_rag_eib/sdd_framework                    → mounted into container
├── ChromaDB container + data volume (14,856 docs)
├── Neo4j container + data volume (85,894 relationships)
└── Docker network: global-workflow-mcp-rag
```

### Target Architecture (Phase 21)

```
Single Docker Image OR Docker Compose Stack
├── MCP Server (Node.js)
├── ChromaDB (embedded or sidecar)
├── Neo4j (embedded or sidecar)
├── global-workflow source (git clone or embedded)
├── Pre-built RAG embeddings (baked in or downloaded)
└── Self-contained network
```

---

## Architecture Options

### Option A: Single Monolithic Image (All-in-One)

**Approach**: Package MCP server, ChromaDB, Neo4j, and data into one container.

```dockerfile
# Conceptual - NOT recommended for production
FROM node:20-slim

# Install ChromaDB server (Python)
RUN pip install chromadb uvicorn

# Install Neo4j
RUN apt-get install -y neo4j

# Copy pre-built embeddings
COPY embeddings/ /data/chromadb/
COPY graph-data/ /data/neo4j/

# Copy global-workflow source
COPY global-workflow/ /app/supported_repos/global-workflow/

# Copy MCP server
COPY mcp_server_node/ /app/

# Supervisor to run all services
CMD ["supervisord", "-c", "/etc/supervisord.conf"]
```

**Pros**:
- Single `docker run` command
- No external dependencies
- Easy distribution

**Cons**:
- Large image size (10-20+ GB with embeddings)
- Cannot scale components independently
- Updates require full image rebuild
- Resource inefficient

**Verdict**: ❌ Not recommended

---

### Option B: Self-Contained Compose Stack (Recommended)

**Approach**: Multi-container compose file with all data pre-loaded, packaged as a distributable archive.

```
eib-mcp-portable/
├── docker-compose.portable.yaml
├── images/
│   ├── eib-mcp-rag.tar         # MCP server image
│   ├── chromadb-preloaded.tar  # ChromaDB with embeddings
│   └── neo4j-preloaded.tar     # Neo4j with graph data
├── data/
│   ├── chromadb-snapshot.tar.gz  # Optional: data separate from image
│   └── neo4j-snapshot.tar.gz
├── repos/
│   └── global-workflow.tar.gz    # Source code archive
├── install.sh                    # One-command setup
└── README.md
```

**Deployment**:
```bash
# Download portable package
curl -LO https://releases.eib.noaa.gov/mcp/eib-mcp-portable-v3.2.0.tar.gz
tar xzf eib-mcp-portable-v3.2.0.tar.gz
cd eib-mcp-portable

# Install (loads images, extracts data)
./install.sh

# Run
docker compose -f docker-compose.portable.yaml up -d

# Access gateway
docker mcp gateway run --servers eib-mcp-rag --transport sse --port 8888
```

**Pros**:
- Components can be updated independently
- Standard Docker architecture
- Reasonable image sizes (2-5 GB total)
- Can pre-load embeddings efficiently

**Cons**:
- Multi-file distribution
- Requires Docker Compose
- More complex than single image

**Verdict**: ✅ Recommended approach

---

### Option C: Cloud-Native with S3/Registry (Production Scale)

**Approach**: Container images in registry, data in S3, pull at runtime.

```
┌────────────────────────────────────────────────────────────────┐
│                    Cloud Deployment                             │
│                                                                 │
│  Container Registry (GitLab/ECR/GHCR)                          │
│  ├── eib-mcp-rag:v3.2.0                                        │
│  ├── chromadb:1.3.4-compat                                     │
│  └── neo4j:5-community                                         │
│                                                                 │
│  S3 Bucket (s3://eib-mcp-data/)                                │
│  ├── chromadb/v7.0.0/chroma.sqlite3.gz                         │
│  ├── neo4j/v1.0.0/graph.dump                                   │
│  └── repos/global-workflow-v2.29.0.tar.gz                      │
│                                                                 │
│  Kubernetes / ECS Deployment                                    │
│  └── init container downloads data from S3 on first run        │
└────────────────────────────────────────────────────────────────┘
```

**Pros**:
- Smallest image sizes
- Data versioned independently
- Scales to multiple instances
- Standard cloud patterns

**Cons**:
- Requires S3/object storage
- Network dependency on first run
- More complex infrastructure

**Verdict**: ✅ For production/cloud environments

---

## Implementation Plan

### Phase 21A: Pre-loaded Database Images

**Goal**: Create ChromaDB and Neo4j images with embedded data.

#### Step 1: Export Current Data

```bash
# Export ChromaDB SQLite
docker cp chromadb:/chroma/chroma/chroma.sqlite3 ./chromadb-export/

# Export Neo4j (dump format)
docker exec neo4j neo4j-admin database dump neo4j --to-path=/dumps
docker cp neo4j:/dumps/neo4j.dump ./neo4j-export/
```

#### Step 2: Create Pre-loaded ChromaDB Image

```dockerfile
# docker/chromadb-preloaded/Dockerfile
FROM chromadb/chroma:1.0.12

# Copy pre-built embeddings
COPY chromadb-data/ /chroma/chroma/

# Ensure correct permissions
RUN chown -R chroma:chroma /chroma/chroma

EXPOSE 8000
```

Build:
```bash
docker build -t eib-chromadb-preloaded:v7.0.0 ./docker/chromadb-preloaded/
```

#### Step 3: Create Pre-loaded Neo4j Image

```dockerfile
# docker/neo4j-preloaded/Dockerfile
FROM neo4j:5-community

# Copy pre-built graph data
COPY neo4j-data/ /data/

# Load dump on first run
COPY neo4j.dump /var/lib/neo4j/import/
COPY load-dump.sh /docker-entrypoint.d/
```

#### Step 4: Clone global-workflow Into Container

**Option 4A**: Git clone at build time (larger image, but self-contained)
```dockerfile
# In Dockerfile.mcp-server
RUN git clone --depth 1 https://github.com/NOAA-EMC/global-workflow.git /app/supported_repos/global-workflow
```

**Option 4B**: Git clone at runtime (smaller image, requires network)
```bash
# In entrypoint.sh
if [ ! -d "/app/supported_repos/global-workflow" ]; then
    git clone --depth 1 https://github.com/NOAA-EMC/global-workflow.git /app/supported_repos/global-workflow
fi
```

**Option 4C**: Archive extraction (balanced approach)
```dockerfile
# Pre-package source as tar.gz
ADD global-workflow-v2.29.0.tar.gz /app/supported_repos/
```

---

### Phase 21B: Portable Compose Stack

**Goal**: Create distributable docker-compose package.

#### docker-compose.portable.yaml

```yaml
# docker-compose.portable.yaml
# Fully portable MCP RAG stack - no host dependencies
#
# Usage:
#   docker compose -f docker-compose.portable.yaml up -d
#
# Version: 1.0.0

services:
  # ============================================================================
  # MCP RAG Server (self-contained)
  # ============================================================================
  mcp-server:
    image: eib-mcp-rag:v3.2.0-portable
    container_name: eib-mcp-portable
    depends_on:
      chromadb:
        condition: service_healthy
      neo4j:
        condition: service_healthy
    environment:
      - NODE_ENV=production
      - MCP_SCENARIO=full
      - MCP_WORKFLOW_ROOT=/app/supported_repos/global-workflow
      - CHROMADB_HOST=chromadb
      - CHROMADB_PORT=8000
      - NEO4J_URI=bolt://neo4j:7687
      - NEO4J_USER=neo4j
      - NEO4J_PASSWORD=gfsworkflow2025
      - ENABLE_RAG=true
    # NO volume mounts - everything is in the container
    labels:
      io.docker.server.metadata: '{"name":"eib-mcp-rag","title":"EIB MCP RAG Server (Portable)","description":"Fully portable MCP server with embedded data"}'
    networks:
      - mcp-portable

  # ============================================================================
  # ChromaDB with Pre-loaded Embeddings
  # ============================================================================
  chromadb:
    image: eib-chromadb-preloaded:v7.0.0
    container_name: chromadb-portable
    environment:
      - CHROMA_HOST=0.0.0.0
      - CHROMA_PORT=8000
      - ANONYMIZED_TELEMETRY=false
    # Data is in the image - no volume mount needed
    # Optional: mount for persistence across container recreates
    # volumes:
    #   - chromadb-portable-data:/chroma/chroma
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v2/heartbeat"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - mcp-portable

  # ============================================================================
  # Neo4j with Pre-loaded Graph
  # ============================================================================
  neo4j:
    image: eib-neo4j-preloaded:v1.0.0
    container_name: neo4j-portable
    environment:
      - NEO4J_AUTH=neo4j/gfsworkflow2025
    # Data is in the image - no volume mount needed
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:7474"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - mcp-portable

networks:
  mcp-portable:
    driver: bridge
```

---

### Phase 21C: Distribution Package

**Goal**: Create downloadable package for air-gapped deployment.

#### Package Structure

```
eib-mcp-portable-v3.2.0/
├── docker-compose.portable.yaml
├── images/
│   ├── eib-mcp-rag-v3.2.0-portable.tar
│   ├── eib-chromadb-preloaded-v7.0.0.tar
│   └── eib-neo4j-preloaded-v1.0.0.tar
├── install.sh
├── uninstall.sh
├── gateway.sh                    # Convenience script to start gateway
├── health-check.sh
├── VERSION
└── README.md
```

#### install.sh

```bash
#!/bin/bash
# install.sh - Load portable MCP images and configure

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION=$(cat "$SCRIPT_DIR/VERSION")

echo "Installing EIB MCP RAG Portable v${VERSION}"

# Load Docker images
echo "Loading Docker images..."
docker load -i "$SCRIPT_DIR/images/eib-mcp-rag-v${VERSION}-portable.tar"
docker load -i "$SCRIPT_DIR/images/eib-chromadb-preloaded-v7.0.0.tar"
docker load -i "$SCRIPT_DIR/images/eib-neo4j-preloaded-v1.0.0.tar"

echo "Images loaded successfully!"
echo ""
echo "To start the MCP stack:"
echo "  cd $SCRIPT_DIR"
echo "  docker compose -f docker-compose.portable.yaml up -d"
echo ""
echo "To start the MCP Gateway for AI clients:"
echo "  ./gateway.sh"
```

---

### Phase 21D: Build Pipeline

**Goal**: Automate portable package creation in CI/CD.

#### GitLab CI Job

```yaml
# Add to .gitlab-ci.yml

build:portable-package:
  stage: build
  image: docker:24
  services:
    - docker:24-dind
  variables:
    VERSION: "3.2.0"
  script:
    # Build images
    - docker build -t eib-mcp-rag:v${VERSION}-portable -f Dockerfile.portable ./mcp_server_node
    - docker build -t eib-chromadb-preloaded:v7.0.0 ./docker/chromadb-preloaded
    - docker build -t eib-neo4j-preloaded:v1.0.0 ./docker/neo4j-preloaded
    
    # Export images
    - mkdir -p portable-package/images
    - docker save eib-mcp-rag:v${VERSION}-portable > portable-package/images/eib-mcp-rag-v${VERSION}-portable.tar
    - docker save eib-chromadb-preloaded:v7.0.0 > portable-package/images/eib-chromadb-preloaded-v7.0.0.tar
    - docker save eib-neo4j-preloaded:v1.0.0 > portable-package/images/eib-neo4j-preloaded-v1.0.0.tar
    
    # Copy compose and scripts
    - cp docker-compose.portable.yaml portable-package/
    - cp SETUP/bin/portable-install.sh portable-package/install.sh
    - echo "$VERSION" > portable-package/VERSION
    
    # Create tarball
    - tar -czvf eib-mcp-portable-v${VERSION}.tar.gz portable-package/
    
  artifacts:
    paths:
      - eib-mcp-portable-v${VERSION}.tar.gz
    expire_in: 30 days
  rules:
    - if: $CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/  # Only on version tags
```

---

## Validation Checklist

### Phase 21 Complete When:

- [ ] ChromaDB pre-loaded image builds with all 14,856 documents
- [ ] Neo4j pre-loaded image builds with 85,894 relationships
- [ ] MCP server image includes global-workflow source code
- [ ] Portable compose stack starts with `docker compose up -d`
- [ ] Health check passes (all 34 tools available)
- [ ] `docker mcp gateway run` works with portable stack
- [ ] Portable package installs on clean Docker host (no prior setup)
- [ ] Documentation includes air-gapped deployment instructions

### Testing Matrix

| Environment | Docker Version | Test |
|-------------|---------------|------|
| Fresh Ubuntu 22.04 VM | Docker CE 24.x | Full install and run |
| macOS (Apple Silicon) | Docker Desktop | Image load and run |
| Amazon Linux 2023 | Docker CE | ECS-compatible test |
| Windows WSL2 | Docker Desktop | Developer workstation |

---

## Timeline

| Phase | Duration | Deliverable |
|-------|----------|-------------|
| 21A | 1 week | Pre-loaded database images |
| 21B | 1 week | Portable compose stack |
| 21C | 0.5 week | Distribution package scripts |
| 21D | 0.5 week | CI/CD pipeline integration |
| Testing | 1 week | Multi-environment validation |

**Total**: ~4 weeks

---

## Dependencies

- Phase 11 (Docker MCP Gateway) ✅ Complete
- Phase 12 (DevOps GitFlow) - CI/CD pipeline for automated builds
- ChromaDB data stabilization (v7 collections finalized)
- Neo4j graph schema finalized

---

## References

- [Phase 11: Docker MCP Gateway](phase11_docker_mcp_gateway_langflow.md)
- [Phase 12: DevOps GitFlow](phase12_devops_gitflow_containerization.md)
- [Docker Multi-stage Builds](https://docs.docker.com/build/building/multi-stage/)
- [Docker Compose Specification](https://docs.docker.com/compose/compose-file/)
