# Phase 12: GitLab CI/CD Provisioning Pipeline

**Status**: PLANNED  
**Priority**: HIGH  
**Depends On**: Phase 11 (Docker MCP Gateway) - COMPLETE  
**Target Version**: v9.0.0  
**Created**: December 10, 2025  

## Overview

Convert the manual provisioning scripts (`SETUP/provisioning/*.sh`) into GitLab CI/CD pipelines executed by self-hosted GitLab runners. This eliminates manual SSH-based provisioning and enables infrastructure-as-code deployment directly from the repository.

## Motivation

### Current State (Manual Provisioning)
```
Developer SSH → Target Host → Run bootstrap.sh → Run provision scripts manually
```

**Problems**:
- Manual execution prone to human error
- No audit trail of what was run
- Difficult to reproduce exact environment
- No automated testing of provisioning
- Version drift between hosts

### Target State (GitLab CI/CD)
```
Git Push → GitLab Pipeline → Self-Hosted Runner → Automated Provisioning
```

**Benefits**:
- ✅ **Reproducible**: Same pipeline runs identically every time
- ✅ **Auditable**: GitLab logs all pipeline executions
- ✅ **Testable**: Can run in dry-run mode before production
- ✅ **Version-controlled**: Pipeline changes tracked in git
- ✅ **Parallelizable**: Independent stages run concurrently
- ✅ **Rollback-capable**: Previous pipeline versions available

## Architecture

### GitLab Runner Deployment

```
┌─────────────────────────────────────────────────────────────┐
│                    GitLab (VLab)                            │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              .gitlab-ci.yml Pipeline                │    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐  │    │
│  │  │ validate │→│ provision│→│ deploy   │→│ verify │  │    │
│  │  └──────────┘ └──────────┘ └──────────┘ └────────┘  │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼ (Runner executes jobs)
┌─────────────────────────────────────────────────────────────┐
│                 Self-Hosted GitLab Runner                   │
│                   (ParallelWorks VM)                        │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  gitlab-runner (Docker executor or Shell executor)  │    │
│  │  - Registered with GitLab VLab                      │    │
│  │  - Tags: mcp-rag, provisioning, docker              │    │
│  │  - Access to /mcp_rag_eib mount                     │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │   ChromaDB   │  │    Neo4j     │  │  MCP Server  │       │
│  │  (Docker)    │  │   (Docker)   │  │   (Docker)   │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

### Runner Executor Strategy

| Executor | Use Case | Pros | Cons |
|----------|----------|------|------|
| **Shell** | Direct host provisioning | Access to Spack, systemd | Less isolation |
| **Docker** | Container builds/deploys | Clean isolation | Can't access host Spack |
| **Docker-in-Docker** | Building Docker images | Full Docker access | Complexity |

**Recommendation**: Use **Shell executor** for provisioning (needs Spack/systemd access), **Docker executor** for container builds.

## Pipeline Stages

### Stage 1: Validate
```yaml
validate:
  stage: validate
  script:
    - ./SETUP/provisioning/00-validate-environment.sh
    - shellcheck SETUP/provisioning/*.sh
    - yamllint .gitlab-ci.yml
  tags:
    - mcp-rag
    - shell
```

### Stage 2: Provision Infrastructure
```yaml
provision-spack:
  stage: provision
  script:
    - ./SETUP/provisioning/01-spack.sh
  tags:
    - mcp-rag
    - shell
  only:
    - docker_mcp
    - main

provision-node:
  stage: provision
  script:
    - ./SETUP/provisioning/02-node.sh
  needs: [provision-spack]
  tags:
    - mcp-rag
    - shell
```

### Stage 3: Deploy Services
```yaml
deploy-chromadb:
  stage: deploy
  script:
    - docker compose -f docker-compose.mcp-standalone.yaml up -d chromadb
    - ./SETUP/provisioning/wait-for-service.sh chromadb 8080
  tags:
    - mcp-rag
    - docker

deploy-neo4j:
  stage: deploy
  script:
    - docker compose -f docker-compose.mcp-standalone.yaml up -d neo4j
    - ./SETUP/provisioning/wait-for-service.sh neo4j 7687
  tags:
    - mcp-rag
    - docker

deploy-mcp-server:
  stage: deploy
  needs: [deploy-chromadb, deploy-neo4j]
  script:
    - docker compose -f docker-compose.mcp-standalone.yaml up -d mcp-server
  tags:
    - mcp-rag
    - docker
```

### Stage 4: Verify
```yaml
verify-health:
  stage: verify
  script:
    - curl -f http://localhost:8080/api/v2/heartbeat
    - curl -f http://localhost:7474
    - docker exec eib-mcp-rag node -e "console.log('MCP Server OK')"
  tags:
    - mcp-rag
```

## Implementation Steps

### Step 1: Install GitLab Runner on ParallelWorks VM
**Type**: manual  
**Component**: GitLab Runner  
**Documentation**: https://docs.gitlab.com/runner/install/linux-repository.html

```bash
# Install GitLab Runner
curl -L "https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.rpm.sh" | sudo bash
sudo dnf install gitlab-runner

# Register runner with VLab GitLab
sudo gitlab-runner register \
  --url https://gitlab-licensed.vlab.noaa.gov \
  --registration-token <TOKEN_FROM_GITLAB_PROJECT_SETTINGS> \
  --executor shell \
  --description "mcp-rag-provisioning" \
  --tag-list "mcp-rag,provisioning,shell" \
  --run-untagged=false \
  --locked=true
```

### Step 2: Create .gitlab-ci.yml
**Type**: code_generation  
**Target**: .gitlab-ci.yml  
**Content**: Full pipeline definition

### Step 3: Refactor Provisioning Scripts for CI
**Type**: code_modification  
**Files**: SETUP/provisioning/*.sh  
**Changes**:
- Add exit codes for CI compatibility
- Add `--ci-mode` flag for non-interactive execution
- Remove interactive prompts
- Add structured output for pipeline logs

### Step 4: Add Environment-Specific Variables
**Type**: configuration  
**Location**: GitLab Project → Settings → CI/CD → Variables

| Variable | Description | Protected |
|----------|-------------|-----------|
| `MCP_RAG_ROOT` | Base path (/mcp_rag_eib) | No |
| `CHROMADB_HOST` | ChromaDB endpoint | No |
| `NEO4J_PASSWORD` | Neo4j password | Yes |
| `DOCKER_REGISTRY` | GitLab registry URL | No |
| `DOCKER_AUTH_CONFIG` | Registry credentials | Yes |

### Step 5: Create Pipeline Triggers
**Type**: configuration  
**Triggers**:
- Push to `docker_mcp` branch → Full pipeline
- Push to `main` branch → Full pipeline with production tags
- Manual trigger → Selective stage execution
- Schedule → Nightly health check pipeline

### Step 6: Add Pipeline Badges to README
**Type**: documentation  
**Target**: README.md

```markdown
[![Pipeline Status](https://gitlab-licensed.vlab.noaa.gov/NWS/Operations/NCEP/EMC/EIB/eib-mcp-rag-server/badges/docker_mcp/pipeline.svg)](...)
```

### Step 7: Create Rollback Pipeline
**Type**: code_generation  
**Target**: .gitlab-ci.yml (rollback job)

```yaml
rollback:
  stage: rollback
  when: manual
  script:
    - docker compose -f docker-compose.mcp-standalone.yaml down
    - docker compose -f docker-compose.mcp-standalone.yaml up -d --force-recreate
  tags:
    - mcp-rag
```

## File Changes Summary

| File | Action | Description |
|------|--------|-------------|
| `.gitlab-ci.yml` | CREATE | Main pipeline definition |
| `SETUP/provisioning/*.sh` | MODIFY | Add CI mode, exit codes |
| `SETUP/provisioning/00-validate-environment.sh` | CREATE | Pre-flight checks |
| `SETUP/provisioning/wait-for-service.sh` | CREATE | Health check waiter |
| `README.md` | MODIFY | Add pipeline badges |
| `docs/GITLAB_RUNNER_SETUP.md` | CREATE | Runner installation guide |

## Success Criteria

1. **Runner Registered**: GitLab runner visible in project settings
2. **Pipeline Executes**: Push triggers automated pipeline
3. **Services Deploy**: ChromaDB, Neo4j, MCP server all healthy post-pipeline
4. **Logs Available**: Full execution logs in GitLab CI/CD interface
5. **Rollback Works**: Manual rollback job restores previous state
6. **No Manual SSH**: Complete provisioning without SSH access

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Runner loses host access | Medium | High | Shell executor with proper permissions |
| Spack modules not available in CI | Medium | Medium | Source mcp-env.sh in before_script |
| Docker socket permissions | Low | Medium | Add gitlab-runner to docker group |
| Secrets exposed in logs | Low | High | Use GitLab masked variables |
| Pipeline timeout on slow ops | Medium | Low | Set appropriate job timeouts |

## Timeline Estimate

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| Runner Installation | 1 day | GitLab admin access |
| Pipeline Creation | 2 days | Runner working |
| Script Refactoring | 2 days | Pipeline structure |
| Testing & Validation | 2 days | All stages working |
| Documentation | 1 day | Pipeline stable |
| **Total** | **8 days** | |

## References

- [GitLab Runner Documentation](https://docs.gitlab.com/runner/)
- [GitLab CI/CD Pipeline Configuration](https://docs.gitlab.com/ee/ci/yaml/)
- [Self-Hosted Runners Best Practices](https://docs.gitlab.com/runner/configuration/runner_autoscale_aws/)
- Phase 11: Docker MCP Gateway (prerequisite)
