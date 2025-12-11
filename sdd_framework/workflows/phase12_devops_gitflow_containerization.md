# Phase 12: DevOps GitFlow & Containerization Strategy

**Description**: Establish a complete DevOps pipeline from development to production using GitLab CI/CD, container registry, and Docker MCP Gateway integration. This SDD captures the architectural findings from the ChromaDB investigation and defines the path forward for a production-ready MCP system.

**Priority**: CRITICAL - Foundation for all future development
**Timeline**: Q1-Q2 2025 (Two Quarters)
**Status**: PLANNING

---

## Part 1: Current State Analysis & Root Cause

### 1.1 ChromaDB Architectural Disconnect (December 2025 Finding)

**Problem Statement**: The MCP RAG system shows healthy heartbeat but returns 0 collections despite 12 collections with 14,854 documents existing in the SQLite database.

**Evidence Collected**:

| Test | Client Type | Result |
|------|-------------|--------|
| Host Python PersistentClient | Direct SQLite | ✅ 12 collections, 14,854 docs |
| Host Python HttpClient | Docker API :8080 | ❌ 0 collections |
| Node.js ChromaClient | Docker API :8080 | ❌ 0 collections |
| curl API v2/heartbeat | Docker API :8080 | ✅ Heartbeat works |
| curl API v2/collections | Docker API :8080 | ❌ Empty array |

**Root Cause Chain**:

```
1. Ingestion scripts (Python) → HttpClient → Port 8080
   BUT: At time of ingestion, port 8080 was served by Python uvicorn server
        (chromadb_server.py pointing to /mcp_rag_eib/data/chromadb)

2. Current runtime:
   - Port 8080 → Docker container (chromadb/chroma:latest)
   - Docker container mounts /mcp_rag_eib/data/chromadb:/data:Z
   - Container sees file but returns 0 collections (version mismatch)

3. Version Incompatibility:
   - Host Python: chromadb==1.3.4 (created the SQLite schema)
   - Docker container: chromadb/chroma:1.3.7.dev9 (cannot read 1.3.4 schema)
   - No chromadb/chroma:1.3.4 Docker image exists on Docker Hub
```

**Historical Context** (from git log):
- `2fb1e80` (Nov 30, 2025): "fix(chromadb): correct Docker mount path from /chroma/chroma to /data"
- Prior to this: Python uvicorn server was used for ChromaDB
- Transition to Docker was incomplete - data written by Python, read by Docker fails

### 1.2 Dual Service Configuration

Two conflicting systemd services exist:

| Service | Mount Path | Status |
|---------|------------|--------|
| chromadb-docker.service | `/data:Z` (correct) | Updated Nov 30 |
| chromadb-persistent.service | `/chroma/chroma` (wrong) | Outdated |

### 1.3 Ingestion Script Architecture

All ingestion scripts use `chromadb.HttpClient`:

```
scripts/ingest_code_v7.py          → HttpClient(localhost:8080)
scripts/ingest_ee2_v7.py           → HttpClient(localhost:8080)
scripts/ingest_documentation_*.py  → HttpClient(localhost:8080)
scripts/ingest_ci_test_cases.py    → HttpClient(localhost:8080)
scripts/ingestion_base.py          → HttpClient(localhost:8080)
```

No scripts use `PersistentClient` - all depend on HTTP API.

### 1.4 Data Location

```
/mcp_rag_eib/data/chromadb/
├── chroma.sqlite3          # 206 MB - Contains all embeddings
└── <embedding directories>  # Vector data files
```

---

## Part 2: Remediation Strategy

### 2.1 Option A: Rebuild Data with Docker (Clean Slate)

**Approach**: Re-ingest all data with Docker ChromaDB container running.

**Pros**:
- Clean architecture (Docker-first)
- Container-portable data
- Version consistency

**Cons**:
- Re-ingestion takes 4-6 hours
- Temporary loss of RAG capability

**Steps**:
1. Stop Docker container
2. Backup existing data: `mv /mcp_rag_eib/data/chromadb /mcp_rag_eib/data/chromadb.bak.1.3.4`
3. Create fresh directory: `mkdir /mcp_rag_eib/data/chromadb`
4. Start Docker container (creates fresh DB)
5. Run all ingestion scripts
6. Verify collections via API

### 2.2 Option B: Run Python ChromaDB Server (Quick Fix)

**Approach**: Use Python uvicorn server instead of Docker for development.

**Pros**:
- Immediate fix (minutes)
- Uses existing data
- No re-ingestion needed

**Cons**:
- Not container-portable
- Development/Production gap
- Version drift risk

**Steps**:
1. Stop Docker container: `docker stop chromadb`
2. Start Python server: `python3 mcp_server_node/chromadb_server.py`
3. Verify: `curl http://localhost:8080/api/v2/collections`

### 2.3 Option C: Build Custom ChromaDB 1.3.4 Image (Bridge)

**Approach**: Create Docker image with chromadb==1.3.4 to match existing data.

**Pros**:
- Uses existing data
- Container-based
- Path to production

**Cons**:
- Custom image maintenance
- Eventually need to migrate

**Steps**:
1. Create Dockerfile with `pip install chromadb==1.3.4`
2. Build and push to GitLab Container Registry
3. Update docker-compose to use custom image
4. Verify data accessibility

### 2.4 Recommended Path: Option A + GitFlow

For DevOps maturity, we recommend **Option A** (clean re-ingestion) because:
- Development branch can use Python server (fast iteration)
- Operations branch uses Docker (container-first)
- Production uses verified container images
- No version drift between environments

---

## Part 3: GitFlow Branch Strategy (Modern Best Practices)

### 3.1 Branch Structure

```
main (protected - production releases only)
│
├── develop (integration branch)
│   └── feature/* (feature branches - experimental)
│       └── feat/ee2-tools, feat/new-ingestion, fix/health-check
│
├── release/* (release candidates)
│   └── release/v3.2.0, release/v4.0.0
│
└── hotfix/* (emergency production fixes)
    └── hotfix/critical-bug
```

**Note**: We use a modified GitFlow with explicit environment branches for DevOps:

```
Environment Branches (CI/CD Triggers):
├── env/dev-ops (containerization validation)
├── env/staging (pre-production)
└── env/production (live deployment)
```

### 3.2 Branch Purposes & Data Isolation

| Branch | Purpose | Database Access | Who Can Touch |
|--------|---------|-----------------|---------------|
| `feature/*` | Experimentation | **Local/Dev DBs only** | Developers |
| `develop` | Integration | **Local/Dev DBs only** | Developers (via MR) |
| `env/dev-ops` | Container validation | **Containerized DBs** | CI/CD Pipeline only |
| `release/*` | Release candidates | **Staging DBs** | Release Manager |
| `env/staging` | Pre-production | **Staging DBs (read-only)** | CI/CD Pipeline only |
| `env/production` | Live deployment | **Production DBs** | CI/CD Pipeline only |
| `main` | Stable reference | N/A | Protected (tags only) |
| `hotfix/*` | Emergency fixes | **Staging → Production** | Senior Devs + Approval |

### 3.3 Data Environment Isolation (CRITICAL)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        DATA ENVIRONMENT ISOLATION                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  DEVELOPMENT MODE (feature/* and develop branches)                          │
│  ════════════════════════════════════════════════                           │
│  • Scripts use: chromadb.PersistentClient (direct SQLite)                   │
│  • OR: Local Docker container (developer's own)                             │
│  • Data location: /mcp_rag_eib/data/chromadb-dev/                           │
│  • Neo4j: Local instance or dev container                                   │
│  • Purpose: Experimentation, rapid iteration, breaking things is OK         │
│  • Developers can: Create, modify, delete collections freely                │
│                                                                              │
│  ──────────────────────────────────────────────────────────────────────────  │
│                                                                              │
│  DEV-OPS MODE (env/dev-ops branch)                                          │
│  ════════════════════════════════                                           │
│  • Scripts use: chromadb.HttpClient → Docker container                      │
│  • Container image: Pinned version from GitLab Registry                     │
│  • Data location: /mcp_rag_eib/data/chromadb-devops/                        │
│  • Neo4j: Containerized (docker-compose)                                    │
│  • Purpose: Validate containerized deployment works                         │
│  • CI/CD can: Re-ingest, run integration tests                              │
│  • Developers: READ-ONLY access for debugging                               │
│                                                                              │
│  ──────────────────────────────────────────────────────────────────────────  │
│                                                                              │
│  STAGING MODE (env/staging branch)                                          │
│  ═══════════════════════════════                                            │
│  • Scripts use: chromadb.HttpClient → Staging container                     │
│  • Container image: Release candidate from GitLab Registry                  │
│  • Data location: Staging server /opt/mcp/data/chromadb/                    │
│  • Purpose: Final validation before production                              │
│  • Access: CI/CD Pipeline only, humans READ-ONLY                            │
│                                                                              │
│  ──────────────────────────────────────────────────────────────────────────  │
│                                                                              │
│  PRODUCTION MODE (env/production branch)                                    │
│  ═══════════════════════════════════════                                    │
│  • Scripts: NEVER run directly against production                           │
│  • Container image: Tagged release (v3.2.0) from GitLab Registry            │
│  • Data location: Production server (isolated network)                      │
│  • Purpose: Serve live MCP tools                                            │
│  • Access: CI/CD Pipeline only, NO human access to data                     │
│  • Changes: Only via approved pipeline deployments                          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.4 Script Execution Modes

All ingestion and database scripts support environment-aware execution:

```bash
# Development mode (default on feature/* branches)
MCP_ENV=development python3 scripts/ingest_documentation_v7.py
# → Uses PersistentClient or local Docker
# → Writes to /mcp_rag_eib/data/chromadb-dev/

# Dev-Ops mode (CI/CD on env/dev-ops)
MCP_ENV=devops python3 scripts/ingest_documentation_v7.py
# → Uses HttpClient → containerized ChromaDB
# → Writes to devops Docker volume

# Production mode (CI/CD only, never manual)
MCP_ENV=production python3 scripts/ingest_documentation_v7.py
# → Uses HttpClient → production ChromaDB
# → Requires pipeline authentication
# → Audit logged
```

**Environment Detection** (scripts/config/environment.py):
```python
import os

MCP_ENV = os.environ.get('MCP_ENV', 'development')

CHROMADB_CONFIG = {
    'development': {
        'client_type': 'PersistentClient',  # Direct SQLite access
        'path': '/mcp_rag_eib/data/chromadb-dev',
        'allow_writes': True,
    },
    'devops': {
        'client_type': 'HttpClient',  # Containerized
        'host': 'localhost',
        'port': 8080,
        'allow_writes': True,  # CI/CD can re-ingest
    },
    'staging': {
        'client_type': 'HttpClient',
        'host': os.environ.get('STAGING_CHROMADB_HOST', 'staging-chromadb'),
        'port': 8000,
        'allow_writes': False,  # Read-only for validation
    },
    'production': {
        'client_type': 'HttpClient',
        'host': os.environ.get('PROD_CHROMADB_HOST'),
        'port': 8000,
        'allow_writes': False,  # NEVER write directly
        'require_pipeline_auth': True,
    },
}
```

### 3.3 Development Workflow

```
Developer Workflow:
┌─────────────────────────────────────────────────────────────────────┐
│  1. Create feature branch from develop                               │
│     git checkout develop && git checkout -b feature/my-feature       │
│                                                                       │
│  2. Develop with Node.js direct execution                            │
│     - MCP server: node src/UnifiedMCPServer.js full                  │
│     - ChromaDB: python3 chromadb_server.py (or Docker)               │
│     - Neo4j: Docker container                                         │
│                                                                       │
│  3. Test locally, commit, push                                        │
│     git push origin feature/my-feature                                │
│                                                                       │
│  4. Create MR to develop (code review)                                │
│                                                                       │
│  5. Merge to develop (triggers unit tests only)                       │
└─────────────────────────────────────────────────────────────────────┘

Containerization Workflow:
┌─────────────────────────────────────────────────────────────────────┐
│  6. Create MR from develop → develop_ops                             │
│                                                                       │
│  7. GitLab CI/CD triggers:                                            │
│     - Build MCP server Docker image                                   │
│     - Run container integration tests                                 │
│     - Push to GitLab Container Registry                               │
│     - Tag: registry.gitlab-licensed.vlab.noaa.gov/.../mcp:develop    │
│                                                                       │
│  8. Review container build artifacts                                  │
└─────────────────────────────────────────────────────────────────────┘

Staging Workflow:
┌─────────────────────────────────────────────────────────────────────┐
│  9. Create MR from develop_ops → staging                             │
│                                                                       │
│  10. GitLab CI/CD triggers:                                           │
│      - Deploy to staging environment                                  │
│      - Run end-to-end tests                                           │
│      - Performance benchmarks                                         │
│      - Security scanning (container vulnerability)                    │
│                                                                       │
│  11. QA validation and approval                                       │
└─────────────────────────────────────────────────────────────────────┘

Production Workflow:
┌─────────────────────────────────────────────────────────────────────┐
│  12. Create MR from staging → production                             │
│                                                                       │
│  13. GitLab CI/CD triggers:                                           │
│      - Tag image as production: mcp:vX.Y.Z                           │
│      - Deploy to production environment                               │
│      - Health check verification                                      │
│      - Rollback capability if health fails                           │
│                                                                       │
│  14. Merge production → main (stable reference)                       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Part 4: GitLab CI/CD Pipeline Design

### 4.1 Pipeline Stages

```yaml
stages:
  - lint          # Code quality checks
  - test          # Unit tests
  - build         # Docker image build
  - scan          # Security scanning
  - deploy        # Environment deployment
  - verify        # Post-deployment checks
```

### 4.2 Pipeline Configuration (.gitlab-ci.yml)

```yaml
# .gitlab-ci.yml - MCP RAG Server CI/CD Pipeline
# GitLab Runner: Shell executor on Parallel Works or Docker executor
#
# Branch Naming Convention:
#   - develop         : Main development integration branch
#   - feat/*          : Feature branches (local development)
#   - fix/*           : Bug fix branches (local development)
#   - release/*       : Release preparation branches
#   - env/dev-ops     : Container integration testing
#   - env/staging     : Pre-production validation
#   - env/production  : Production deployment (CI/CD only)

variables:
  REGISTRY: registry.gitlab-licensed.vlab.noaa.gov
  IMAGE_NAME: nws/operations/ncep/emc/eib/eib-mcp-rag-server
  DOCKER_TLS_CERTDIR: ""
  
  # Environment-specific compose files
  COMPOSE_DEVOPS: docker-compose.devops.yaml
  COMPOSE_STAGING: docker-compose.staging.yaml
  COMPOSE_PRODUCTION: docker-compose.production.yaml

# ============================================================================
# RULE TEMPLATES (DRY principle)
# ============================================================================
.rules:feature:
  rules:
    - if: $CI_COMMIT_BRANCH =~ /^feat\// || $CI_COMMIT_BRANCH =~ /^fix\//
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

.rules:develop:
  rules:
    - if: $CI_COMMIT_BRANCH == "develop"

.rules:devops:
  rules:
    - if: $CI_COMMIT_BRANCH == "env/dev-ops"

.rules:staging:
  rules:
    - if: $CI_COMMIT_BRANCH == "env/staging"

.rules:production:
  rules:
    - if: $CI_COMMIT_BRANCH == "env/production"

# ============================================================================
# STAGE: Lint (Feature + Develop branches)
# ============================================================================
lint:js:
  stage: lint
  script:
    - cd mcp_server_node
    - npm ci
    - npm run lint
  rules:
    - !reference [.rules:feature, rules]
    - !reference [.rules:develop, rules]

lint:python:
  stage: lint
  script:
    - pip install flake8 pycodestyle
    - flake8 mcp_server_node/scripts/ --max-line-length=120
  rules:
    - !reference [.rules:feature, rules]
    - !reference [.rules:develop, rules]

# ============================================================================
# STAGE: Test
# ============================================================================
test:unit:
  stage: test
  variables:
    MCP_ENV: development
  script:
    - cd mcp_server_node
    - npm ci
    - npm test
  rules:
    - !reference [.rules:develop, rules]
    - !reference [.rules:devops, rules]

# Container integration tests - only on env/* branches
test:integration:
  stage: test
  variables:
    MCP_ENV: devops
    CHROMA_SERVER_URL: http://chromadb:8000
    NEO4J_URI: bolt://neo4j:7687
    NEO4J_AUTH: neo4j/testpassword
  script:
    - docker compose -f $COMPOSE_DEVOPS up -d chromadb neo4j
    - sleep 10  # Wait for services
    - cd mcp_server_node
    - npm ci
    - npm run test:integration
  after_script:
    - docker compose -f $COMPOSE_DEVOPS down
  rules:
    - !reference [.rules:devops, rules]
    - !reference [.rules:staging, rules]

# ============================================================================
# STAGE: Build (Container images - only env/* branches)
# ============================================================================
build:mcp-server:
  stage: build
  image: docker:24
  services:
    - docker:24-dind
  variables:
    DOCKER_HOST: tcp://docker:2376
  before_script:
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $REGISTRY
  script:
    - cd mcp_server_node
    - docker build -t $REGISTRY/$IMAGE_NAME/mcp-server:$CI_COMMIT_SHORT_SHA .
    - docker push $REGISTRY/$IMAGE_NAME/mcp-server:$CI_COMMIT_SHORT_SHA
    # Tag with sanitized branch name (env/dev-ops → env-dev-ops)
    - |
      BRANCH_TAG=$(echo "$CI_COMMIT_BRANCH" | sed 's/\//-/g')
      docker tag $REGISTRY/$IMAGE_NAME/mcp-server:$CI_COMMIT_SHORT_SHA $REGISTRY/$IMAGE_NAME/mcp-server:$BRANCH_TAG
      docker push $REGISTRY/$IMAGE_NAME/mcp-server:$BRANCH_TAG
  rules:
    - !reference [.rules:devops, rules]
    - !reference [.rules:staging, rules]
    - !reference [.rules:production, rules]

build:chromadb-compat:
  stage: build
  image: docker:24
  services:
    - docker:24-dind
  variables:
    DOCKER_HOST: tcp://docker:2376
  before_script:
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $REGISTRY
  script:
    - cd docker/chromadb
    - docker build -t $REGISTRY/$IMAGE_NAME/chromadb:1.3.4-compat .
    - docker push $REGISTRY/$IMAGE_NAME/chromadb:1.3.4-compat
  rules:
    - !reference [.rules:devops, rules]
  when: manual  # Only rebuild when needed

# ============================================================================
# STAGE: Integrate (Container stack validation - env/dev-ops only)
# ============================================================================
integrate:container-stack:
  stage: build
  variables:
    MCP_ENV: devops
  script:
    - echo "Starting full container stack validation..."
    - docker compose -f $COMPOSE_DEVOPS up -d
    - sleep 15  # Wait for all services
    # Validate ChromaDB
    - |
      if ! curl -s http://localhost:8080/api/v2/heartbeat | grep -q "heartbeat"; then
        echo "ERROR: ChromaDB health check failed"
        exit 1
      fi
    # Validate Neo4j
    - |
      if ! curl -s http://localhost:7474 | grep -q "neo4j"; then
        echo "ERROR: Neo4j health check failed"
        exit 1
      fi
    # Validate MCP Server
    - docker compose -f $COMPOSE_DEVOPS logs mcp-server | tail -20
    - echo "Container stack validation PASSED"
  after_script:
    - docker compose -f $COMPOSE_DEVOPS down
  rules:
    - !reference [.rules:devops, rules]

# ============================================================================
# STAGE: Scan (Security - staging and production)
# ============================================================================
scan:container:
  stage: scan
  image: aquasec/trivy:latest
  script:
    - trivy image --exit-code 1 --severity HIGH,CRITICAL $REGISTRY/$IMAGE_NAME/mcp-server:$CI_COMMIT_SHORT_SHA
  allow_failure: true
  rules:
    - !reference [.rules:staging, rules]
    - !reference [.rules:production, rules]

# ============================================================================
# STAGE: Deploy
# ============================================================================
deploy:staging:
  stage: deploy
  variables:
    MCP_ENV: staging
  environment:
    name: staging
    url: https://staging-mcp.eib.noaa.gov
  script:
    - |
      ssh $STAGING_HOST << 'EOF'
        cd /opt/mcp
        docker compose -f docker-compose.staging.yaml pull
        docker compose -f docker-compose.staging.yaml up -d
      EOF
  rules:
    - !reference [.rules:staging, rules]

deploy:production:
  stage: deploy
  variables:
    MCP_ENV: production
  environment:
    name: production
    url: https://mcp.eib.noaa.gov
  script:
    - |
      ssh $PRODUCTION_HOST << 'EOF'
        cd /opt/mcp
        docker compose -f docker-compose.production.yaml pull
        docker compose -f docker-compose.production.yaml up -d
      EOF
  rules:
    - !reference [.rules:production, rules]
  when: manual  # ALWAYS require manual approval for production

# ============================================================================
# STAGE: Verify
# ============================================================================
verify:health:
  stage: verify
  script:
    - |
      for i in {1..30}; do
        if curl -s "$DEPLOY_URL/api/v2/heartbeat" | grep -q "heartbeat"; then
          echo "Health check passed"
          exit 0
        fi
        sleep 10
      done
      echo "Health check failed"
      exit 1
  rules:
    - !reference [.rules:staging, rules]
    - !reference [.rules:production, rules]
```

### 4.3 GitLab Runner Configuration

```toml
# /etc/gitlab-runner/config.toml (on Parallel Works)

[[runners]]
  name = "mcp-rag-runner"
  url = "https://gitlab-licensed.vlab.noaa.gov/"
  token = "RUNNER_TOKEN"
  executor = "shell"
  
  [runners.custom_build_dir]
    enabled = true
  
  [runners.cache]
    Type = "local"
    Path = "/mcp_rag_eib/cache/gitlab-runner"

[[runners]]
  name = "mcp-rag-docker-runner"
  url = "https://gitlab-licensed.vlab.noaa.gov/"
  token = "RUNNER_TOKEN"
  executor = "docker"
  
  [runners.docker]
    image = "docker:24"
    privileged = true
    volumes = ["/cache", "/var/run/docker.sock:/var/run/docker.sock"]
```

---

## Part 5: Container Registry Strategy

### 5.1 Registry Location

```
GitLab Container Registry:
registry.gitlab-licensed.vlab.noaa.gov/nws/operations/ncep/emc/eib/eib-mcp-rag-server

Images:
├── mcp-server/                           # MCP Server images
│   ├── mcp-server:env-dev-ops            # Latest env/dev-ops build
│   ├── mcp-server:env-staging            # Latest env/staging build
│   ├── mcp-server:env-production         # Latest env/production build
│   ├── mcp-server:v3.0.0                 # Semantic version tags
│   └── mcp-server:<commit-sha>           # Immutable commit references
├── chromadb/                             # ChromaDB images
│   └── chromadb:1.3.4-compat             # Custom ChromaDB image (version-locked)
└── neo4j:5.15.0                          # Cached Neo4j image (optional)
```

### 5.2 Image Tagging Strategy

| Environment | Tag Pattern | Example |
|-------------|-------------|---------|
| Dev-Ops | `env-dev-ops` | `mcp-server:env-dev-ops` |
| Staging | `env-staging`, `rc-<version>` | `mcp-server:env-staging`, `mcp-server:rc-3.1.0` |
| Production | `env-production`, `v<semver>`, `latest` | `mcp-server:v3.1.0`, `mcp-server:latest` |
| Feature | `feat-<name>` | `mcp-server:feat-ee2-tools` (only if needed) |
| Immutable | `<commit-sha>` | `mcp-server:0c05694` |

### 5.3 Image Lifecycle

```
Retention Policy:
- develop tags: Keep last 10
- staging tags: Keep last 5
- production tags: Keep all (for rollback)
- commit-sha tags: Keep 30 days
- Semantic versions (vX.Y.Z): Keep forever
```

---

## Part 6: Docker MCP Gateway Integration

### 6.1 Architecture with Gateway

```
┌─────────────────────────────────────────────────────────────────────┐
│                         AI Clients                                   │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│   │ VS Code  │  │ Claude   │  │ LangFlow │  │ Cursor   │           │
│   │ Copilot  │  │ Desktop  │  │          │  │          │           │
│   └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘           │
│        │             │             │             │                  │
│        └─────────────┴──────┬──────┴─────────────┘                  │
│                             │                                        │
│                    ┌────────▼────────┐                              │
│                    │  Docker MCP     │                              │
│                    │    Gateway      │  Port 8090 (SSE/Streaming)   │
│                    │  (docker-mcp)   │                              │
│                    └────────┬────────┘                              │
│                             │ stdio                                  │
│            ┌────────────────┼────────────────┐                      │
│            │                │                │                      │
│    ┌───────▼───────┐ ┌──────▼──────┐ ┌──────▼──────┐               │
│    │ EIB-MCP-RAG   │ │  GitHub     │ │  Future     │               │
│    │ Server        │ │  MCP Server │ │  Servers    │               │
│    │ (Container)   │ │ (Container) │ │             │               │
│    └───────┬───────┘ └─────────────┘ └─────────────┘               │
│            │                                                         │
│    ┌───────┴───────────────────┐                                    │
│    │                           │                                    │
│    ▼                           ▼                                    │
│ ┌──────────────┐       ┌──────────────┐                            │
│ │   ChromaDB   │       │    Neo4j     │                            │
│ │  (Container) │       │  (Container) │                            │
│ │  Port 8080   │       │  Port 7687   │                            │
│ └──────────────┘       └──────────────┘                            │
└─────────────────────────────────────────────────────────────────────┘
```

### 6.2 Gateway Deployment Steps

```bash
# 1. Install Docker MCP CLI plugin
git clone https://github.com/docker/mcp-gateway.git /tmp/mcp-gateway
cd /tmp/mcp-gateway
make docker-mcp
mv docker-mcp ~/.docker/cli-plugins/

# 2. Initialize catalog
docker mcp catalog init

# 3. Import our server definition
docker mcp catalog import mcp_server_node/docker-mcp-catalog.yaml

# 4. Enable server
docker mcp server enable eib-mcp-rag

# 5. Run gateway
docker mcp gateway run --port 8090 --transport streaming

# 6. Verify
docker mcp tools ls
```

---

## Part 7: Implementation Phases

### Phase 12A: Immediate Remediation (Week 1)

**Goal**: Restore RAG functionality with clear architecture

| Step | Task | Owner | Duration |
|------|------|-------|----------|
| 12A.1 | Document current state (this SDD) | AI Agent | 1 day |
| 12A.2 | Decide remediation path (A, B, or C) | Terry | Decision |
| 12A.3 | Execute remediation | AI Agent | 1-4 hours |
| 12A.4 | Verify MCP health check shows all collections | AI Agent | 30 min |
| 12A.5 | Update provisioning scripts | AI Agent | 1 hour |

### Phase 12B: GitFlow Branch Setup (Week 2)

**Goal**: Establish branch structure and protection rules

| Step | Task | Duration |
|------|------|----------|
| 12B.1 | Create `develop` branch from main | 1 hour |
| 12B.2 | Create `env/dev-ops` branch from develop | 1 hour |
| 12B.3 | Create `env/staging` branch from env/dev-ops | 1 hour |
| 12B.4 | Create `env/production` branch from env/staging | 1 hour |
| 12B.5 | Configure GitLab branch protection rules | 2 hours |
| 12B.6 | Document branch workflow in CONTRIBUTING.md | 2 hours |

**Branch Protection Rules**:
- `develop`: Requires 1 approval, no force push
- `env/dev-ops`: Requires 1 approval, CI must pass
- `env/staging`: Requires 2 approvals, CI + security scan must pass
- `env/production`: Requires 2 approvals + CODEOWNER, CI/CD only deployment

### Phase 12C: CI/CD Pipeline (Weeks 3-4)

**Goal**: Implement GitLab CI/CD pipelines

| Step | Task | Duration |
|------|------|----------|
| 12C.1 | Create .gitlab-ci.yml with lint/test stages | 4 hours |
| 12C.2 | Configure GitLab Runner on Parallel Works | 4 hours |
| 12C.3 | Add Docker build stage | 4 hours |
| 12C.4 | Configure Container Registry authentication | 2 hours |
| 12C.5 | Add security scanning stage | 2 hours |
| 12C.6 | Test full pipeline on develop_ops | 4 hours |

### Phase 12D: Docker MCP Gateway (Weeks 5-6)

**Goal**: Integrate with Docker MCP Gateway

| Step | Task | Duration |
|------|------|----------|
| 12D.1 | Finalize Dockerfile | 2 hours |
| 12D.2 | Test container with ChromaDB | 4 hours |
| 12D.3 | Install Docker MCP Gateway plugin | 2 hours |
| 12D.4 | Configure MCP catalog entry | 2 hours |
| 12D.5 | Test Gateway with VS Code | 4 hours |
| 12D.6 | Test Gateway with LangFlow | 4 hours |

### Phase 12E: Staging Environment (Weeks 7-8)

**Goal**: Establish staging deployment

| Step | Task | Duration |
|------|------|----------|
| 12E.1 | Provision staging server | 4 hours |
| 12E.2 | Configure staging docker-compose | 2 hours |
| 12E.3 | Configure staging pipeline stage | 2 hours |
| 12E.4 | Implement health check verification | 2 hours |
| 12E.5 | Document staging deployment process | 2 hours |

### Phase 12F: Production Readiness (Weeks 9-10)

**Goal**: Production deployment capability

| Step | Task | Duration |
|------|------|----------|
| 12F.1 | Configure production pipeline stage | 4 hours |
| 12F.2 | Implement rollback automation | 4 hours |
| 12F.3 | Configure monitoring/alerting | 4 hours |
| 12F.4 | Security review and hardening | 8 hours |
| 12F.5 | Documentation and runbooks | 8 hours |

---

## Part 8: Success Criteria

### 8.1 Phase 12 Complete When:

- [ ] MCP health check shows all collections (12+) with documents (14,000+)
- [ ] GitFlow branches exist: develop, develop_ops, staging, production
- [ ] .gitlab-ci.yml runs successfully on all branches
- [ ] Container images build and push to GitLab Registry
- [ ] Docker MCP Gateway serves tools to LangFlow
- [ ] Staging deployment automated via pipeline
- [ ] Production deployment with manual approval gate
- [ ] Rollback tested and documented

### 8.2 Metrics

| Metric | Current | Target |
|--------|---------|--------|
| RAG Collections Accessible | 0 | 12+ |
| RAG Documents Accessible | 0 | 14,000+ |
| Pipeline Stages | 0 | 6 |
| Container Build Time | N/A | < 5 min |
| Deployment Time | Manual | < 10 min |
| Rollback Time | N/A | < 5 min |

---

## Part 9: Risk Mitigation

### 9.1 Identified Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Data loss during remediation | HIGH | Backup before any changes |
| Container version drift | MEDIUM | Pin versions, use commit SHAs |
| Pipeline failures block development | HIGH | Allow manual override |
| Gateway compatibility issues | MEDIUM | Test incrementally |
| GitLab Runner capacity | LOW | Queue management, runner scaling |

### 9.2 Rollback Procedures

```bash
# Container Rollback
docker compose pull mcp-rag-server:v<previous>
docker compose up -d

# Branch Rollback
git revert HEAD
git push origin <branch>

# Data Rollback
mv /mcp_rag_eib/data/chromadb /mcp_rag_eib/data/chromadb.failed
mv /mcp_rag_eib/data/chromadb.bak /mcp_rag_eib/data/chromadb
```

---

## References

- [Docker MCP Gateway](https://github.com/docker/mcp-gateway)
- [GitLab CI/CD Documentation](https://docs.gitlab.com/ee/ci/)
- [GitFlow Workflow](https://www.atlassian.com/git/tutorials/comparing-workflows/gitflow-workflow)
- [Phase 11 SDD](phase11_docker_mcp_gateway_langflow.md)
- [NOAA VLab GitLab](https://gitlab-licensed.vlab.noaa.gov/)

---

## Appendix A: Current File Inventory

### Existing Docker Files
- `docker-compose.mcp.yaml` - Full stack (ChromaDB + Neo4j + MCP)
- `docker-compose.mcp-standalone.yaml` - MCP + ChromaDB only
- `mcp_server_node/Dockerfile` - MCP server container (in docker_mcp branch)
- `mcp_server_node/docker-mcp-catalog.yaml` - Gateway catalog entry

### Existing Service Files
- `/etc/systemd/system/chromadb-docker.service` - Docker ChromaDB (correct mount)
- `/etc/systemd/system/chromadb-persistent.service` - Docker ChromaDB (wrong mount)

### Existing Python ChromaDB Servers
- `mcp_server_node/chromadb_server.py` - uvicorn server (port 8080)
- `mcp_server_node/start_chromadb.py` - Simple server (port 8000)

---

## Appendix B: Environment Variables

```bash
# ============================================================================
# DEVELOPMENT ENVIRONMENT (MCP_ENV=development)
# - Feature branches (feat/*, fix/*)
# - Uses PersistentClient (direct SQLite access)
# - Local experimentation allowed
# ============================================================================
export MCP_ENV="development"
export CHROMA_DATA_PATH="/mcp_rag_eib/data/chromadb-dev"
# ChromaDB: PersistentClient(path=$CHROMA_DATA_PATH)
export NEO4J_URI="bolt://localhost:7687"
export MCP_SCENARIO="full"
export ENABLE_RAG="true"

# ============================================================================
# DEV-OPS ENVIRONMENT (MCP_ENV=devops)
# - env/dev-ops branch
# - Containerized databases (Docker Compose)
# - CI/CD validates container compatibility
# ============================================================================
export MCP_ENV="devops"
export CHROMA_SERVER_URL="http://localhost:8080"  # Docker container
# ChromaDB: HttpClient(host="localhost", port=8080)
export NEO4J_URI="bolt://localhost:7687"
export MCP_SCENARIO="full"
export ENABLE_RAG="true"

# ============================================================================
# STAGING ENVIRONMENT (MCP_ENV=staging)
# - env/staging branch
# - Remote containerized databases
# - Read-only validation
# ============================================================================
export MCP_ENV="staging"
export CHROMA_SERVER_URL="http://staging-chromadb:8000"
export NEO4J_URI="bolt://staging-neo4j:7687"
export MCP_SCENARIO="full"
export ENABLE_RAG="true"

# ============================================================================
# PRODUCTION ENVIRONMENT (MCP_ENV=production)
# - env/production branch
# - NEVER accessed manually - CI/CD only
# - Audit logged, authentication required
# ============================================================================
export MCP_ENV="production"
export CHROMA_SERVER_URL="http://prod-chromadb:8000"
export NEO4J_URI="bolt://prod-neo4j:7687"
export MCP_SCENARIO="full"
export ENABLE_RAG="true"

# ============================================================================
# GitLab CI/CD Registry Variables
# ============================================================================
export CI_REGISTRY="registry.gitlab-licensed.vlab.noaa.gov"
export CI_REGISTRY_IMAGE="$CI_REGISTRY/nws/operations/ncep/emc/eib/eib-mcp-rag-server"
```
