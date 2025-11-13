# Multi-Tier MCP RAG Architecture - Production Deployment Framework
**Date**: 2025-10-10  
**Status**: Architectural Design Complete ✅  
**Purpose**: Enterprise-scale MCP deployment for NWS developers with GitHub Actions integration

## Executive Summary

This document defines the complete architectural framework for deploying the MCP RAG system as a **shared multi-user service** supporting:
- **Individual NWS developers** via VS Code with MCP stdio
- **Automated PR reviews** via GitHub Actions with REST API
- **EE2 compliance analysis** integrated into CI/CD pipelines
- **Centralized vector knowledge base** for all users and automation

## System Architecture Overview

```
┌───────────────────────────────────────────────────────────────────────────┐
│                        NWS Developer Workstations                         │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐         │
│  │ Developer 1      │  │ Developer 2      │  │ Developer N      │         │
│  │ VS Code          │  │ VS Code          │  │ VS Code          │         │
│  │ ├─ Copilot       │  │ ├─ Copilot       │  │ ├─ Copilot       │         │
│  │ └─ MCP Client    │  │ └─ MCP Client    │  │ └─ MCP Client    │         │
│  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘         │
│           │ SSH Tunnel          │ SSH Tunnel          │ SSH Tunnel        │
│           │ (passwordless)      │ (passwordless)      │ (passwordless)    │
└───────────┼─────────────────────┼─────────────────────┼───────────────────┘
            │                     │                     │
            └─────────────────────┴─────────────────────┘
                                  │
                                  ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                     MCP RAG Server (Per-User Processes)                   │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │  MCP stdio Server (spawned per VS Code connection)                   │ │
│  │  - Protocol: stdio (stdin/stdout)                                    │ │
│  │  - Isolation: One process per user                                   │ │
│  │  - Tools: 17 MCP tools (workflow, RAG, GitHub)                       │ │
│  │  - Location: /mcp_rag_eib/mcp_server_node/src/UnifiedMCPServer.js    │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                      Shared Infrastructure Services                        │
│                                                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  REST API Server (HTTP Daemon)                          Port 3000    │  │
│  │  ────────────────────────────────────────────────────────────────────│  │
│  │  • Express.js HTTP server                                            │  │
│  │  • Exposes MCP tools as REST endpoints                               │  │
│  │  • GitHub Actions integration                                        │  │
│  │  • PR review automation with EE2 compliance                          │  │
│  │  • Authentication: GitHub SSO tokens                                 │  │
│  │  • Rate limiting: Per-user quotas                                    │  │
│  │  • Logging: Audit trail for all API calls                            │  │
│  │                                                                      │  │
│  │  Endpoints:                                                          │  │
│  │    POST /api/v1/analyze-pr          - Full PR analysis               │  │
│  │    POST /api/v1/search-knowledge     - RAG semantic search           │  │
│  │    POST /api/v1/analyze-ee2          - EE2 compliance check          │  │
│  │    POST /api/v1/analyze-error        - Error diagnosis               │  │
│  │    GET  /api/v1/health               - Health check                  │  │
│  │    GET  /api/v1/metrics              - Usage metrics                 │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  ChromaDB Vector Database                               Port 8080    │  │
│  │  ────────────────────────────────────────────────────────────────────│  │
│  │  • Shared vector store (single source of truth)                      │  │
│  │  • Collections:                                                      │  │
│  │    - code_knowledge          (source code embeddings)                │  │
│  │    - documentation           (official docs)                         │  │
│  │    - error_patterns          (historical errors)                     │  │
│  │    - solutions_knowledge     (proven fixes)                          │  │
│  │    - github_intelligence     (issues/PRs)                            │  │
│  │    - workflow_dependencies   (component relationships)               │  │
│  │    - build_system_knowledge  (CMake, build logs)                     │  │
│  │    - test_results            (test history)                          │  │
│  │    - ee2_compliance          (EE2 requirements & analysis)           │  │
│  │  • Queried by: All MCP stdio servers + REST API                      │  │
│  │  • Persistence: /mcp_rag_eib/data/chromadb                           │  │
│  │  • Systemd service: chromadb-persistent.service                      │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  LangFlow Visual Pipeline Builder                       Port 7860    │  │
│  │  ────────────────────────────────────────────────────────────────────│  │
│  │  • Visual RAG pipeline design tool                                   │  │
│  │  • Admin/development interface                                       │  │
│  │  • ChromaDB integration via host.docker.internal:8080                │  │
│  │  • Docker container: global-workflow-langflow                        │  │
│  │  • Credentials: admin / admin123                                     │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                          GitHub Actions CI/CD                              │
│                                                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  PR Review Automation Workflow                                       │  │
│  │  ────────────────────────────────────────────────────────────────────│  │
│  │                                                                      │  │
│  │  Trigger: on: pull_request                                           │  │
│  │                                                                      │  │
│  │  Steps:                                                              │  │
│  │   1. Fetch PR diff                                                   │  │
│  │   2. Call REST API: POST /api/v1/analyze-pr                          │  │
│  │      └─ Body: { pr_number, diff, files_changed, author }             │  │
│  │   3. Analyze code changes via RAG                                    │  │
│  │   4. Check EE2 compliance: POST /api/v1/analyze-ee2                  │  │
│  │   5. Generate review comments                                        │  │
│  │   6. Post comments to PR                                             │  │
│  │                                                                      │  │
│  │  Analysis Includes:                                                  │  │
│  │   • Code quality review                                              │  │
│  │   • Pattern matching against best practices                          │  │
│  │   • Dependency impact analysis                                       │  │
│  │   • EE2 compliance verification  *                                   │  │
│  │   • Error-prone pattern detection                                    │  │
│  │   • Documentation completeness                                       │  │
│  │   • Test coverage suggestions                                        │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  EE2 Compliance Gate                                                 │  │
│  │  ────────────────────────────────────────────────────────────────────│  │
│  │                                                                      │  │
│  │  Automated EE2 Analysis:                                             │  │
│  │   • Software Configuration Management (SCM) compliance               │  │
│  │   • Documentation requirements verification                          │  │
│  │   • Code review process adherence                                    │  │
│  │   • Testing requirements validation                                  │  │
│  │   • Change control procedures                                        │  │
│  │   • Security and access controls                                     │  │
│  │                                                                      │  │
│  │  Output:                                                             │  │
│  │   • Pass/Fail status                                                 │  │
│  │   • Detailed compliance report                                       │  │
│  │   • Recommendations for non-compliance                               │  │
│  │   • Links to relevant EE2 documentation                              │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────┘
```

## Component Details

### 1. MCP stdio Server (Per-User Processes)

**Protocol**: Model Context Protocol (MCP) over stdio  
**Invocation**: Spawned by VS Code MCP client per SSH session  
**Lifecycle**: Runs for duration of VS Code connection, terminates on disconnect  
**Isolation**: Each user gets their own process with independent state

**Configuration File**: `.vscode/mcp.json` (workspace or user settings)
```json
{
  "mcpServers": {
    "global-workflow-unified": {
      "command": "node",
      "args": ["/mcp_rag_eib/mcp_server_node/src/UnifiedMCPServer.js"],
      "env": {
        "CHROMADB_URL": "http://127.0.0.1:8080",
        "GITHUB_TOKEN": "${env:GH_TOKEN}"
      }
    }
  }
}
```

**17 Available Tools**:
- Workflow analysis (8 tools)
- RAG semantic search (5 tools)
- GitHub integration (4 tools)

**Authentication**: SSH keys (passwordless) + GitHub SSO

### 2. REST API Server (HTTP Daemon)

**Purpose**: Expose MCP tools as HTTP endpoints for GitHub Actions  
**Technology**: Express.js + Node.js  
**Port**: 3000 (configurable)  
**Deployment**: systemd service (persistent daemon)

**Service File**: `/etc/systemd/system/mcp-rest-api.service`

**Authentication Strategy**:
- GitHub App JWT tokens for GitHub Actions
- Personal Access Tokens (PAT) for manual API calls
- Rate limiting: 100 req/hour per user, 1000 req/hour for CI/CD

**Key Endpoints**:

```javascript
// Full PR analysis with EE2 compliance
POST /api/v1/analyze-pr
Body: {
  pr_number: number,
  repository: string,
  diff: string,
  files_changed: string[],
  author: string,
  check_ee2: boolean  // Enable EE2 compliance check
}
Response: {
  analysis: {
    code_quality: {},
    patterns_detected: [],
    risks: [],
    suggestions: []
  },
  ee2_compliance: {
    status: "pass" | "fail" | "warning",
    score: number,
    violations: [],
    recommendations: []
  }
}

// EE2 Compliance Analysis (dedicated endpoint)
POST /api/v1/analyze-ee2
Body: {
  code: string,
  file_path: string,
  context: string
}
Response: {
  compliant: boolean,
  score: number,
  categories: {
    scm: { pass: boolean, issues: [] },
    documentation: { pass: boolean, issues: [] },
    testing: { pass: boolean, issues: [] },
    security: { pass: boolean, issues: [] }
  },
  recommendations: [],
  documentation_links: []
}

// RAG semantic search
POST /api/v1/search-knowledge
Body: {
  query: string,
  collections: string[],
  limit: number
}
Response: {
  results: [
    { content: string, metadata: {}, score: number }
  ]
}

// Error diagnosis (historical log analysis)
POST /api/v1/analyze-error
Body: {
  error_message: string,
  stack_trace: string,
  component: string
}
Response: {
  root_cause: string,
  similar_incidents: [],
  proven_solutions: [],
  code_locations: []
}
```

**Security**:
- HTTPS only (TLS/SSL certificates)
- JWT token validation
- Rate limiting per user
- Request logging for audit trail
- CORS restricted to GitHub Actions IPs

### 3. ChromaDB Vector Database

**Purpose**: Centralized vector knowledge base  
**Technology**: ChromaDB 0.4.15  
**Port**: 8080  
**Storage**: /mcp_rag_eib/data/chromadb (persistent)  
**Service**: chromadb-persistent.service (systemd)

**Collections Structure** (9 collections):

1. **code_knowledge**
   - Source code embeddings from 50+ repositories
   - 3-5M lines of code (Fortran, Python, C/C++, Shell)
   - Metadata: repo, file_path, language, function_name, line_range

2. **documentation**
   - Official documentation, READMEs, Sphinx/Doxygen
   - API documentation with examples
   - Operational guides

3. **error_patterns**
   - Historical error logs (1+ year)
   - Stack traces with context
   - Metadata: timestamp, component, severity, resolution_status

4. **solutions_knowledge**
   - Proven fixes linked to errors
   - Commit hashes of successful resolutions
   - Success rate tracking

5. **github_intelligence**
   - Issues, PRs, commit messages
   - Bug reports and resolutions
   - Discussion threads

6. **workflow_dependencies**
   - Component relationship graph
   - Dependency mappings
   - Build-time and runtime dependencies

7. **build_system_knowledge**
   - CMakeLists.txt configurations
   - Build logs (successful and failed)
   - Compiler flags and options

8. **test_results**
   - CTest results history
   - Regression test patterns
   - Flaky test identification

9. **ee2_compliance** ⭐ **NEW**
   - EE2 requirements documentation
   - Compliance categories and criteria
   - Historical compliance analysis results
   - Best practice examples
   - Violation patterns and resolutions

**Access Pattern**:
- MCP stdio servers: Direct ChromaDB client connection
- REST API: Shared ChromaDB client with connection pooling
- LangFlow: via host.docker.internal:8080

### 4. LangFlow Visual Pipeline Builder

**Purpose**: Visual RAG pipeline development and testing  
**Technology**: LangFlow 1.6.4 (Docker)  
**Port**: 7860  
**Container**: global-workflow-langflow  
**Credentials**: admin / admin123

**Use Cases**:
- Design complex RAG workflows visually
- Test ChromaDB queries interactively
- Prototype EE2 compliance pipelines
- Debug embedding generation
- Admin tool for RAG system tuning

### 5. GitHub Actions Integration

**Workflow File**: `.github/workflows/pr-review-rag.yml`

```yaml
name: AI-Powered PR Review with EE2 Compliance

on:
  pull_request:
    types: [opened, synchronize, reopened]
    branches: [develop, main, MCP_node.js-RAG_ParallelWorks]

jobs:
  ai-review:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
        with:
          fetch-depth: 0
      
      - name: Get PR diff
        id: pr-diff
        run: |
          git diff origin/${{ github.base_ref }}...HEAD > pr.diff
      
      - name: Call RAG API for PR Analysis
        id: rag-analysis
        run: |
          curl -X POST https://your-vm.noaa.gov:3000/api/v1/analyze-pr \
            -H "Authorization: Bearer ${{ secrets.MCP_API_TOKEN }}" \
            -H "Content-Type: application/json" \
            -d @- <<EOF
          {
            "pr_number": ${{ github.event.pull_request.number }},
            "repository": "${{ github.repository }}",
            "diff": "$(cat pr.diff | jq -Rs .)",
            "files_changed": $(gh pr view ${{ github.event.pull_request.number }} --json files -q '.files[].path' | jq -s .),
            "author": "${{ github.event.pull_request.user.login }}",
            "check_ee2": true
          }
          EOF
      
      - name: Post review comments
        uses: actions/github-script@v7
        with:
          script: |
            const analysis = ${{ steps.rag-analysis.outputs.result }};
            
            // Post general PR review
            await github.rest.pulls.createReview({
              owner: context.repo.owner,
              repo: context.repo.repo,
              pull_request_number: context.issue.number,
              body: analysis.analysis.summary,
              event: 'COMMENT'
            });
            
            // Post EE2 compliance status
            const ee2Status = analysis.ee2_compliance.status === 'pass' ? '✅' : '❌';
            await github.rest.issues.createComment({
              owner: context.repo.owner,
              repo: context.repo.repo,
              issue_number: context.issue.number,
              body: `## ${ee2Status} EE2 Compliance Check\n\n${analysis.ee2_compliance.summary}\n\nScore: ${analysis.ee2_compliance.score}/100`
            });
      
      - name: Update PR status check
        uses: actions/github-script@v7
        with:
          script: |
            const analysis = ${{ steps.rag-analysis.outputs.result }};
            const state = analysis.ee2_compliance.status === 'pass' ? 'success' : 'failure';
            
            await github.rest.repos.createCommitStatus({
              owner: context.repo.owner,
              repo: context.repo.repo,
              sha: context.payload.pull_request.head.sha,
              state: state,
              context: 'EE2 Compliance',
              description: `Compliance score: ${analysis.ee2_compliance.score}/100`
            });
```

## EE2 Compliance Analysis Framework

### EE2 Categories Analyzed

1. **Software Configuration Management (SCM)**
   - Version control compliance
   - Branch strategy adherence
   - Commit message standards
   - Change tracking

2. **Documentation Requirements**
   - Code documentation (docstrings, comments)
   - README updates for new features
   - API documentation completeness
   - User-facing documentation

3. **Code Review Process**
   - PR description quality
   - Review participation
   - Approval requirements
   - Discussion resolution

4. **Testing Requirements**
   - Unit test coverage
   - Integration test presence
   - Regression test updates
   - Test documentation

5. **Security and Access Controls**
   - Sensitive data handling
   - Authentication mechanisms
   - Authorization checks
   - Audit logging

6. **Change Control Procedures**
   - Issue tracking linkage
   - Change approval workflow
   - Rollback procedures
   - Deployment documentation

### EE2 Knowledge Base Ingestion

**Sources**:
- NOAA EE2 official documentation
- Historical compliance audits
- Best practice examples from approved PRs
- Violation patterns from rejected PRs
- NWS coding standards
- NOAA security guidelines

**Embeddings**:
- EE2 requirement texts with semantic understanding
- Code examples demonstrating compliance
- Anti-patterns showing violations
- Remediation guidance

### Compliance Scoring Algorithm

```javascript
function calculateEE2Score(analysis) {
  const weights = {
    scm: 0.20,
    documentation: 0.20,
    code_review: 0.15,
    testing: 0.20,
    security: 0.15,
    change_control: 0.10
  };
  
  let score = 0;
  for (const [category, weight] of Object.entries(weights)) {
    score += analysis[category].score * weight;
  }
  
  return {
    total: Math.round(score),
    status: score >= 80 ? 'pass' : score >= 60 ? 'warning' : 'fail',
    breakdown: analysis
  };
}
```

**Thresholds**:
- **Pass**: ≥80/100 - PR meets EE2 requirements
- **Warning**: 60-79/100 - PR needs improvements
- **Fail**: <60/100 - PR blocked until compliance achieved

## Deployment Architecture

### User Access Model

**Developer Workstations → VM**:
- SSH with public key authentication (passwordless)
- GitHub SSO for identity verification
- VS Code Remote SSH extension
- MCP client spawns per-user stdio server

**GitHub Actions → REST API**:
- GitHub App JWT tokens
- Rate limiting per repository
- API key rotation policy
- Audit logging

### Multi-User Isolation

**Process Isolation**:
- Each VS Code connection = separate Node.js process
- User-specific environment variables
- Independent MCP tool execution
- No cross-user data leakage

**Resource Limits** (systemd or cgroups):
- Memory: 2GB per user MCP process
- CPU: 50% of 1 core per process
- Max processes per user: 5

**Storage Isolation**:
- User-specific cache directories
- Shared read-only knowledge base
- Write access only to user logs

### Scaling Considerations

**Current Capacity (Single VM)**:
- 10-20 concurrent VS Code users
- 100 GitHub Actions API calls/hour
- 1000 RAG queries/minute

**Horizontal Scaling (Future)**:
- Load balancer for REST API
- Multiple REST API instances
- Shared ChromaDB (single instance adequate for now)
- Redis for session management

**Vertical Scaling**:
- Increase VM resources (CPU, RAM)
- SSD for ChromaDB performance
- More cores for parallel MCP processes

## Implementation Roadmap

### Phase 1: Core Infrastructure ✅ (Complete)
- [x] ChromaDB installation and configuration
- [x] LangFlow Docker deployment
- [x] MCP stdio server working
- [x] Submodules cloned (50+ repos)
- [x] Enhanced ingestion architecture designed

### Phase 2: REST API Development ⏳ (Next)
- [ ] Express.js REST API server implementation
- [ ] GitHub authentication middleware
- [ ] Rate limiting and security
- [ ] API endpoint implementations
- [ ] systemd service for REST API
- [ ] Health checks and monitoring

### Phase 3: EE2 Integration ⏳
- [ ] EE2 documentation ingestion
- [ ] EE2 compliance collection in ChromaDB
- [ ] Compliance analysis algorithms
- [ ] Scoring and reporting
- [ ] Integration with PR review workflow

### Phase 4: GitHub Actions Workflows ⏳
- [ ] PR review automation workflow
- [ ] EE2 compliance gate
- [ ] Status checks and comments
- [ ] Workflow testing and refinement

### Phase 5: Knowledge Base Population ⏳
- [ ] Documentation ingestion (all 50+ repos)
- [ ] Source code ingestion (semantic chunking)
- [ ] GitHub issues/PRs ingestion
- [ ] Error log ingestion (1+ year data)
- [ ] Build and test result ingestion
- [ ] Relationship graph building

### Phase 6: Production Deployment ⏳
- [ ] Multi-user testing
- [ ] Performance optimization
- [ ] Security hardening
- [ ] Documentation and training
- [ ] Monitoring and alerting
- [ ] Backup and disaster recovery

## Security Considerations

### Authentication & Authorization
- **VS Code users**: SSH keys + GitHub SSO
- **REST API**: GitHub App JWT + PAT
- **Admin access**: Multi-factor authentication
- **Service accounts**: Rotating secrets in HashiCorp Vault

### Network Security
- **Firewall rules**: Restrict ports 3000, 7860, 8080 to authorized IPs
- **TLS/SSL**: HTTPS only for REST API
- **VPN**: Optional for additional security layer
- **SSH tunneling**: Encrypted connections for VS Code users

### Data Security
- **Vector embeddings**: No PII in ChromaDB
- **API logs**: Sanitize sensitive data
- **Error logs**: Redact credentials and tokens
- **Backup encryption**: Encrypted backups of ChromaDB data

### Compliance
- **NOAA security policies**: Full adherence
- **Data classification**: Appropriate handling per sensitivity
- **Audit logging**: All API calls and user actions logged
- **Access reviews**: Quarterly user access audits

## Monitoring & Observability

### Metrics
- **MCP stdio**: Process count, memory usage per user
- **REST API**: Request rate, latency, error rate
- **ChromaDB**: Query performance, collection sizes
- **LangFlow**: Container health, uptime
- **System**: CPU, memory, disk I/O

### Logging
- **Application logs**: JSON format, centralized collection
- **Access logs**: All API requests with user context
- **Error logs**: Stack traces, context, recovery actions
- **Audit logs**: Security-sensitive operations

### Alerting
- **Service down**: Immediate notification
- **High error rate**: Alert if >5% errors
- **Resource exhaustion**: Alert at 80% capacity
- **Security events**: Unauthorized access attempts

## Success Metrics

### Developer Productivity
- **Time to answer**: <2 minutes for code questions
- **Error resolution**: <15 minutes with RAG assistance
- **PR review time**: 50% reduction with AI assistance

### Code Quality
- **EE2 compliance rate**: >95% on first submission
- **Bug detection**: Catch 80% of potential issues in PR review
- **Documentation coverage**: 100% of public APIs documented

### System Performance
- **API response time**: <500ms p95
- **RAG query latency**: <200ms p95
- **Uptime**: 99.9% availability

## Support & Maintenance

### On-Call Rotation
- **Primary**: System administrator
- **Secondary**: MCP developer
- **Escalation**: Management contact

### Maintenance Windows
- **Scheduled downtime**: Sunday 2-4 AM UTC monthly
- **Emergency patches**: As needed with 24h notice

### Documentation
- **User guides**: VS Code MCP setup, API usage
- **Admin runbooks**: Service restarts, troubleshooting
- **Architecture docs**: This document + implementation details

---

## Appendix: Key Decision Points

### Why MCP stdio for VS Code?
**Decision**: Use MCP protocol over stdio for VS Code integration  
**Rationale**: MCP specification requires stdio for local tool integration; secure, simple, and well-supported by VS Code  
**Alternative considered**: HTTP server per user (rejected due to port management complexity and security concerns)

### Why REST API for GitHub Actions?
**Decision**: Build Express.js REST API wrapper around MCP tools  
**Rationale**: GitHub Actions needs HTTP endpoints; enables broader integration; natural fit for CI/CD automation  
**Alternative considered**: GitHub App with custom webhooks (more complex, less flexible)

### Why single ChromaDB instance?
**Decision**: One ChromaDB server for all users and API  
**Rationale**: Shared knowledge base ensures consistency; adequate performance for expected load; simplifies maintenance  
**Alternative considered**: Per-user ChromaDB instances (rejected due to storage waste and data consistency issues)

### Why systemd for services?
**Decision**: Use systemd for ChromaDB and REST API management  
**Rationale**: Standard Linux service management; auto-restart; logging integration; well-understood by operations  
**Alternative considered**: Docker Compose for all services (rejected to keep REST API and MCP stdio more flexible)

---

**Document Status**: ✅ Complete  
**Last Updated**: 2025-10-10  
**Next Review**: Before Phase 2 implementation  
**Owner**: Terry McGuinness / NOAA-EMC Team
