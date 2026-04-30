# MCP Access Architecture Proposal

## MDC MCP RAG Server — Multi-User Access & Scaling Strategy

**Date**: April 30, 2026
**Author**: Terry McGuinness, EMC/EIB
**Account**: 903050880929 (us-east-1)
**System**: MDC MCP RAG Server — 51 AI-powered development tools for the Global Forecast System (GFS)

---

## Executive Summary

The MDC MCP RAG Server provides 51 AI-powered tools (code analysis, semantic search, compliance checking, workflow tracing) to developers working on NOAA's Global Forecast System. The server queries a Neptune graph database (164,916 nodes, 2.9M relationships) and OpenSearch vector store (85,000+ documents) to provide contextual intelligence about the GFS codebase.

We propose a two-phase deployment strategy:

- **Phase 1**: Internal access for a 10-person cohort via GFE laptops with CAC-enabled VPN, using AgentCore Runtime for per-user session isolation and scaling
- **Phase 2**: External access for CI/CD pipelines (GitHub Actions) via FedRAMP-compliant Private API Gateway + Fargate, enabling automated code quality and compliance checks

Both phases maintain zero internet exposure for the data plane (Neptune, OpenSearch) with supporting security enhancments.

---

## System Context

### What the MCP Server Does

The Model Context Protocol (MCP) server exposes 51 tools that help developers understand, navigate, and validate the Global Forecast System codebase:

| Category | Tools | Backend |
|----------|-------|---------|
| Code Analysis | 5 tools (call chains, dependencies, execution tracing) | Neptune graph |
| Semantic Search | 6 tools (documentation, related files, RAG explanations) | OpenSearch vectors + Neptune |
| EE2 Compliance | 4 tools (standards search, compliance scanning) | OpenSearch vectors |
| Workflow Operations | 3 tools (job scripts, component explanations) | Neptune + filesystem |
| SDD Framework | 9 tools (session management, workflow tracking) | Local state |
| Cross-Language Tracing | 4 tools (Shell→Fortran→Python execution chains) | Neptune graph |
| Utilities | 3 tools (health, metrics, server info) | All backends |

### Current Data Plane (Already Deployed, Private VPC)

| Resource | Type | Access |
|----------|------|--------|
| Neptune (graph) | `mdc-mcp-graprag-neptune-1` | Private subnet, IAM auth, port 8182 |
| OpenSearch (vectors) | `vpc-mdc-mcp-rag-search` | Private subnet, port 443 |
| ECR (container image) | `mdc-mcp-rag:agentcore` | ARM64, 302MB |
| Security Group | `sg-096489a0876cc78c1` | Egress to Neptune + OpenSearch only |

### Current State

- MCP server container built and tested (ARM64, Node.js 20)
- AgentCore Runtime deployed and validated (status: READY, 51 tools responding)
- **First user (developer lead) fully connected and operational**:
  - GFE laptop → CAC VPN → AWS VPC (working)
  - Kiro IDE → IAM auth (SigV4) → AgentCore Runtime (working)
  - All 51 MCP tools validated via `invoke_agent_runtime` (working)
- No internet-facing endpoints

---

## Phase 1: Internal Cohort Access (10 Users)

### Objective

Enable 10 developers on GFE laptops to access the MCP server through their Kiro IDE, with per-user session isolation and automatic scaling.

### Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  GFE Laptop (Developer)                                      │
│  ┌──────────┐                                                │
│  │ Kiro IDE │──── MCP over HTTPS ────┐                       │
│  └──────────┘                        │                       │
└──────────────────────────────────────│───────────────────────┘
                                       │
                              CAC-enabled VPN / Port Forward
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────┐
│  AWS VPC (Private, no Internet Gateway)                      │
│                                                              │
│  ┌───────────────────────────────────────────────────────┐   │
│  │  AgentCore Runtime (mdc_mcp_rag_server)               │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │   │
│  │  │  Session 1  │  │  Session 2  │  │  Session N  │    │   │
│  │  │  (User A)   │  │  (User B)   │  │  (User N)   │    │   │
│  │  │  microVM    │  │  microVM    │  │  microVM    │    │   │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘    │   │
│  │         │                │                │           │   │
│  │         └────────────────┼────────────────┘           │   │
│  │                          │                            │   │
│  └──────────────────────────│────────────────────────────┘   │
│                             │                                │
│                             ▼                                │
│  ┌───────────────────────────────────────────────────────┐   │
│  │  Data Plane (shared, read-only from MCP perspective)  │   │
│  │  ┌─────────────────┐    ┌─────────────────────────┐   │   │
│  │  │ Neptune (graph) │    │ OpenSearch (vectors)    │   │   │
│  │  │ 164,916 nodes   │    │ 85,000+ documents       │   │   │
│  │  │ 2,941,593 rels  │    │ 5 indices (titan1024)   │   │   │
│  │  └─────────────────┘    └─────────────────────────┘   │   │
│  └───────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

### Why AgentCore Runtime (Not Fargate) for Phase 1

| Requirement | AgentCore | Fargate |
|-------------|-----------|---------|
| Per-user session isolation | ✅ Dedicated microVM per session | ❌ Shared containers |
| Scale to zero (no idle cost) | ✅ No sessions = no charges | ❌ Min 1 task always running |
| No capacity planning | ✅ Managed fleet | ❌ Must configure desired count, scaling policies |
| Cold start for 10 users | ✅ ~4s per session | ⚠️ Comparable with pre-warmed tasks |
| Observability per user | ✅ Session-level CloudWatch/X-Ray | ⚠️ Task-level only |
| Automatic session cleanup | ✅ Idle timeout (15 min), max lifetime (8 hr) | ❌ Must implement |

### Access Pattern

1. Developer connects GFE laptop to NOAA VPN (CAC authentication)
2. VPN provides access to the private VPC (no internet gateway)
3. Kiro IDE (running on GFE) connects to EC2 via SSH remote development (same pattern as VS Code Remote SSH)
4. Kiro pushes its server-side component onto the EC2 via the SSH connection
5. Kiro spawns the **AgentCore MCP Proxy** as a `"command"` type MCP server on the EC2
6. The proxy calls `InvokeAgentRuntime` (boto3, SigV4) to reach the AgentCore Runtime
7. AgentCore creates an isolated microVM session for that user
8. MCP server in the microVM queries Neptune/OpenSearch on behalf of the user
9. Session auto-terminates after 15 minutes idle (configurable)

### Kiro-to-AgentCore Connectivity (The Proxy)

AgentCore MCP runtimes are accessed via the `InvokeAgentRuntime` API with SigV4 signing — they do not expose a plain HTTPS URL. Kiro's MCP client expects either a plain HTTP URL or a local `"command"` process. The solution is a **thin stdio proxy** that runs on the EC2:

```
┌─────────────────────────────────────────────────────────────────┐
│  GFE Laptop                                                     │
│  ┌──────────┐                                                   │
│  │ Kiro IDE │ ─── SSH Remote Development ───┐                   │
│  └──────────┘                               │                   │
└─────────────────────────────────────────────│───────────────────┘
                                              │
                              CAC VPN → Jumpbox → SSH
                                              │
                                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  EC2 Instance (Kiro remote workspace)                           │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  agentcore-kiro-proxy.py (command-type MCP server)        │  │
│  │  - Reads JSON-RPC from stdin (Kiro sends it)              │  │
│  │  - Calls invoke_agent_runtime via boto3 (SigV4/IAM)       │  │
│  │  - Parses SSE response from AgentCore                     │  │
│  │  - Writes JSON-RPC to stdout (Kiro reads it)              │  │
│  └───────────────────────────┬───────────────────────────────┘  │
│                              │                                   │
│                              │ boto3 API call (VPC-internal)     │
│                              ▼                                   │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  AgentCore Runtime (microVM per user session)             │  │
│  │  51 MCP tools → Neptune + OpenSearch                      │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

**Key properties of the proxy:**
- Single Python file (~100 lines), no dependencies beyond boto3 (already on EC2)
- Runs on the EC2 where Kiro's remote workspace lives — same pattern as the AWS Powers
- Each user's Kiro instance spawns its own proxy process → own AgentCore session → own microVM
- Transparent forwarding: proxy never interprets tool schemas, just passes JSON-RPC through

**Kiro MCP configuration (on EC2 at `/home/ec2-user/.kiro/settings/mcp.json`):**

```json
{
  "agentcore-mcp-rag": {
    "command": "python3",
    "args": ["/home/ec2-user/eib-mcp-rag-server/tools/agentcore-kiro-proxy.py",
             "--runtime-id", "mdc_mcp_rag_server-TMXDllG2Wi"],
    "env": {
      "AWS_REGION": "us-east-1"
    }
  }
}
```

This follows the same pattern as the three existing AWS Powers (IAM Policy Autopilot, AWS IaC, AgentCore) which are also configured as `"command"` type servers on the EC2.

### Important: No Software on GFE

- **Nothing runs on the GFE laptop** except Kiro itself (desktop application)
- All MCP servers, Powers, Python, uvx, boto3 — everything executes on the EC2
- Kiro connects to the EC2 via SSH remote development (analogous to VS Code Remote SSH)
- The GFE provides only the thin client UI and the CAC VPN network path

### Authentication (Validated)

The access pattern is already proven and in use:

- **VPN**: CAC-enabled VPN from GFE laptop to private VPC ✅
- **IAM**: Kiro authenticates to AWS via IAM credentials (SigV4) ✅
- **AgentCore**: `InvokeAgentRuntime` API call is authorized by IAM policy ✅

This is the same pattern that will be replicated for the 10-person cohort — each developer gets IAM credentials with `bedrock-agentcore:InvokeAgentRuntime` permission. The VPN provides the network boundary, IAM provides the identity boundary.

### AgentCore Runtime Configuration (Already Deployed)

```
Runtime ID:     mdc_mcp_rag_server-TMXDllG2Wi
ARN:            arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/mdc_mcp_rag_server-TMXDllG2Wi
Protocol:       MCP
Network:        VPC (us-east-1a, us-east-1b)
Subnets:        subnet-0e13af6b3a9a6416f, subnet-04447750c61bd7e06
Security Group: sg-096489a0876cc78c1
Idle Timeout:   900s (15 minutes)
Max Lifetime:   28800s (8 hours)
Container:      903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:agentcore
Execution Role: arn:aws:iam::903050880929:role/mdc-mcp-rag-ecs-task-role
Status:         READY
```

### What's Needed from Infrastructure Team (Phase 1)

1. **IAM identities**: 9 additional developer IAM users with `bedrock-agentcore:InvokeAgentRuntime` permission (1 already active and validated)
2. **EC2 access**: Each developer needs SSH remote development access to the EC2 (same jumpbox pattern as current setup)
3. **Kiro onboarding**: Each developer configures Kiro with SSH remote connection to EC2 + their IAM credentials
4. **Proxy deployment**: The `agentcore-kiro-proxy.py` script is already in the repo — no additional installation needed
5. **No Internet Gateway required** — all traffic stays within VPC
6. **VPN routing already in place** — CAC VPN → private VPC connectivity confirmed working

### Cost Estimate (Phase 1)

- AgentCore Runtime: $0 when idle, ~$0.05/session-hour when active
- 10 users × 4 hours/day × 20 days/month = 800 session-hours/month
- Estimated: ~$40/month compute (plus Neptune/OpenSearch baseline which is already running)

---

## Phase 2: External CI/CD Access (GitHub Actions)

### Objective

Expose the MCP server as an API endpoint accessible from GitHub Actions workflows, enabling automated code quality checks, EE2 compliance scanning, and PR review assistance — while maintaining FedRAMP compliance and zero direct internet exposure to the data plane.

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  GitHub Actions Runner                                          │
│  ┌──────────────────┐                                           │
│  │ MCP Client Step  │───── HTTPS (mTLS) ────┐                   │
│  └──────────────────┘                       │                   │
└─────────────────────────────────────────────│───────────────────┘
                                              │
                                    Public Internet (TLS 1.3)
                                              │
                                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  AWS VPC (FedRAMP Boundary)                                     │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Private API Gateway (REST, PRIVATE endpoint type)        │  │
│  │  - WAF WebACL (rate limiting, IP allowlist, bot control)  │  │
│  │  - mTLS with client certificates                          │  │
│  │  - API key + usage plan (per-workflow throttling)         │  │
│  │  - Request/response logging to CloudWatch                 │  │
│  │  - Resource policy: deny all except VPC endpoint          │  │
│  └───────────────────────────┬───────────────────────────────┘  │
│                              │                                  │
│  ┌───────────────────────────▼───────────────────────────────┐  │
│  │  Internal NLB (Network Load Balancer)                     │  │
│  │  - Health checks on /ping                                 │  │
│  │  - TLS termination                                        │  │
│  └───────────────────────────┬───────────────────────────────┘  │
│                              │                                  │
│  ┌───────────────────────────▼───────────────────────────────┐  │
│  │  ECS Fargate Service                                      │  │
│  │  - MCP Server container (ARM64, same image)               │  │
│  │  - Auto-scaling (1-10 tasks based on request count)       │  │
│  │  - Task role: Neptune + OpenSearch access                 │  │
│  │  - No public IP, private subnets only                     │  │
│  └───────────────────────────┬───────────────────────────────┘  │
│                              │                                  │
│  ┌───────────────────────────▼───────────────────────────────┐  │
│  │  Data Plane (unchanged from Phase 1)                      │  │
│  │  Neptune (graph) + OpenSearch (vectors)                   │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Why Fargate (Not AgentCore) for Phase 2

| Requirement | Fargate | AgentCore |
|-------------|---------|-----------|
| GitHub Actions integration | ✅ Standard HTTPS endpoint | ⚠️ Requires SDK/proxy |
| FedRAMP compliance documentation | ✅ Well-established pattern | ⚠️ Newer service, less compliance history |
| API Gateway + WAF integration | ✅ Native | ⚠️ Not designed for this |
| Stateless request/response (CI jobs) | ✅ Perfect fit | ❌ Overkill (session isolation unnecessary for CI) |
| Cost at scale (1000s of CI runs) | ✅ Predictable, task-based | ⚠️ Session overhead per invocation |
| mTLS client certificates | ✅ API GW native | ❌ Not supported |

### FedRAMP Compliance Controls

| Control | Implementation |
|---------|---------------|
| **AC-4 (Information Flow)** | Private API GW, VPC endpoint, no internet gateway |
| **AC-17 (Remote Access)** | mTLS + API keys for GitHub Actions; VPN + CAC for humans |
| **AU-2 (Audit Events)** | CloudWatch Logs for all API GW requests, Fargate task logs |
| **IA-2 (Identification)** | mTLS client certs (machine identity), Cognito (human identity) |
| **SC-7 (Boundary Protection)** | WAF WebACL, resource policy, security groups, no public subnets |
| **SC-8 (Transmission Confidentiality)** | TLS 1.3 end-to-end, no plaintext |
| **SC-13 (Cryptographic Protection)** | KMS-encrypted data at rest (Neptune, OpenSearch, S3) |
| **SI-4 (Monitoring)** | X-Ray tracing, CloudWatch alarms, WAF logging |

### GitHub Actions Integration Pattern

```yaml
# .github/workflows/mcp-compliance-check.yml
name: EE2 Compliance Check
on: [pull_request]

jobs:
  compliance:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Run EE2 Compliance Scan
        uses: noaa-emc/mcp-action@v1
        with:
          endpoint: ${{ secrets.MCP_ENDPOINT_URL }}
          client-cert: ${{ secrets.MCP_CLIENT_CERT }}
          client-key: ${{ secrets.MCP_CLIENT_KEY }}
          tool: scan_repository_compliance
          args: |
            categories: ["error_handling", "environment_variables", "file_naming"]
            
      - name: Check Code Context
        uses: noaa-emc/mcp-action@v1
        with:
          endpoint: ${{ secrets.MCP_ENDPOINT_URL }}
          client-cert: ${{ secrets.MCP_CLIENT_CERT }}
          client-key: ${{ secrets.MCP_CLIENT_KEY }}
          tool: get_change_impact
          args: |
            symbol: ${{ github.event.pull_request.title }}
```

### What's Needed from Infrastructure Team (Phase 2)

1. **VPC Endpoint for API Gateway** (already exists: `vpce-0b2f402157c32c1c8`)
2. **ACM certificate** for the API Gateway custom domain (private CA or public ACM)
3. **mTLS client CA** — private CA for issuing client certificates to GitHub Actions
4. **WAF WebACL** — rate limiting, GitHub IP allowlist (GitHub publishes their IP ranges)
5. **DNS** — private hosted zone entry for the API endpoint
6. **CDK deployment approval** — we have the stacks coded, need permission to deploy
7. **FedRAMP documentation** — SSP updates for the new access path

### Cost Estimate (Phase 2)

- API Gateway: ~$3.50/million requests
- Fargate: ~$0.04/vCPU-hour, ~$0.004/GB-hour (1 vCPU, 2GB per task)
- NLB: ~$0.006/hour + $0.006/LCU-hour
- WAF: $5/month + $1/million requests
- Estimated for 10,000 CI runs/month: ~$50/month (plus existing Neptune/OpenSearch baseline)

---

## Phase Comparison

| Aspect | Phase 1 (Internal) | Phase 2 (CI/CD) |
|--------|-------------------|-----------------|
| Users | 10 developers (human) | GitHub Actions (machine) |
| Access | VPN + CAC | mTLS + API key |
| Compute | AgentCore (microVM/session) | Fargate (shared tasks) |
| Scaling | Per-session, auto | Task count, auto-scaling |
| Auth | VPN trust / IAM / Cognito | mTLS client certs |
| Internet exposure | None | API Gateway only (WAF-protected) |
| State | Session-based (multi-turn) | Stateless (single request) |
| Cost model | Per session-hour | Per request + task-hour |
| FedRAMP boundary | Fully inside VPC | API GW at boundary, data inside |

---

## Timeline

| Phase | Milestone | Dependencies | Target |
|-------|-----------|-------------|--------|
| 1a | AgentCore Runtime deployed | ✅ Done | April 30, 2026 |
| 1b | First user validated (VPN + IAM + Kiro) | ✅ Done | April 30, 2026 |
| 1c | AgentCore Kiro Proxy built and tested | Spec complete | May 2026 |
| 1d | 9 additional IAM users + EC2 access provisioned | Infra team | May 2026 |
| 1e | 10-user pilot with Kiro | Developer onboarding | May 2026 |
| 2a | CDK stack deployment (API GW + Fargate) | Infra team approval | June 2026 |
| 2b | mTLS + WAF configuration | Security team | June 2026 |
| 2c | GitHub Actions integration | DevOps | July 2026 |
| 2d | FedRAMP documentation update | Compliance team | July 2026 |

---

## Existing Assets (Ready to Deploy)

| Asset | Location | Status |
|-------|----------|--------|
| MCP Server container (ARM64) | `903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:agentcore` | ✅ Pushed |
| AgentCore Runtime | `mdc_mcp_rag_server-TMXDllG2Wi` | ✅ READY |
| AgentCore Kiro Proxy | `tools/agentcore-kiro-proxy.py` | 🔨 Spec complete |
| CDK Stacks (API GW + Fargate) | `infrastructure/cdk/lib/` | ✅ Coded, 27 tests passing |
| Neptune graph database | 164,916 nodes, 2,941,593 relationships | ✅ Loaded |
| OpenSearch vector store | 85,000+ documents, 5 indices | ✅ Loaded |
| IAM execution role | `mdc-mcp-rag-ecs-task-role` | ✅ Configured |
| Service-linked roles (AgentCore) | All 4 created | ✅ Active |

---

## Questions for Infrastructure/Security Team

1. Can we provision 9 additional IAM users with `bedrock-agentcore:InvokeAgentRuntime` permission for the pilot cohort?
2. For Phase 2, is there a preferred private CA for mTLS client certificates?
3. Do we need a separate ATO/SSP update for the API Gateway exposure, or does it fall under the existing system boundary?
4. Is there a preferred WAF rule set for GitHub Actions IP allowlisting?
5. Any concerns with the AgentCore service-linked roles that were created?

---

## References

- AgentCore Runtime: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-mcp.html
- AgentCore Kiro Proxy Spec: `.kiro/specs/agentcore-kiro-proxy/` (requirements, design, tasks)
- CDK Stacks: `infrastructure/cdk/lib/` (this repository)
- Container: `mcp_server_node/Dockerfile.agentcore`
- Permissions: `docs/agentcore-permissions-request.md`
- Phase 51b SDD: `sdd_framework/workflows/phase51b_agentcore_mcp_deployment.md`
