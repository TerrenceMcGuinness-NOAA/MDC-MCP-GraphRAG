# MDC MCP-RAG Platform — AWS Architecture Reference

**Organization:** NOAA / NWS / NCEP / EMC / MDC (formerly EIB)  
**Version:** 3.0.0  
**Date:** May 1, 2026  
**Status:** Fully Operational  
**Account:** 903050880929 (us-east-1)

---

## 1. Executive Summary

The MDC MCP-RAG Platform is an AI-assisted development system for NOAA's Global Workflow
codebase. It provides **51 MCP tools** across 9 modules for code analysis, semantic search,
EE2 compliance validation, and operational guidance — backed by a **hybrid triple-store RAG
engine** (vector search via OpenSearch + graph traversal via Neptune).

The platform runs on two parallel deployments:
- **AWS (production):** Bedrock AgentCore Runtime → Neptune + OpenSearch (148K nodes, 2.8M rels, 206K vector docs)
- **On-premises (legacy):** Docker MCP Gateway → Neo4j + ChromaDB on RDHPCS infrastructure

Both expose the same 51-tool MCP interface. Developers connect via Kiro IDE.

---

## 2. Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                           AWS CLOUD — us-east-1 (903050880929)                       │
│                                                                                      │
│  ┌────────────────────────────────────────────────────────────────────────────────┐   │
│  │                     BEDROCK AGENTCORE LAYER                                    │   │
│  │                                                                                │   │
│  │  ┌──────────────────────────────────────────────────────────────────────────┐   │   │
│  │  │  AgentCore Runtime: mdc_mcp_rag_server (v4, READY)                      │   │   │
│  │  │  Protocol: MCP │ Network: VPC │ Endpoint: DEFAULT                       │   │   │
│  │  │  Container: mdc-mcp-rag:agentcore (ECR, 302MB)                          │   │   │
│  │  │  ┌────────────────────────────────────────────────────────────────────┐  │   │   │
│  │  │  │  Node.js 20 MCP Server (v3.6.2) — 51 tools, 9 modules            │  │   │   │
│  │  │  │  DB_BACKEND=aws → NeptuneAdapter + OpenSearchAdapter              │  │   │   │
│  │  │  │  SigV4 IAM auth │ APOC→openCypher transform │ k-NN search        │  │   │   │
│  │  │  └────────────────────────────────────────────────────────────────────┘  │   │   │
│  │  │  Idle: 900s │ Max lifetime: 28800s │ Firecracker microVM                │   │   │
│  │  │  Role: mdc-mcp-rag-ecs-task-role (ECS + AgentCore trust)                │   │   │
│  │  └──────────────────────────┬───────────────────────────────────────────────┘   │   │
│  │                             │ invoke_agent_runtime (SigV4)                      │   │
│  └─────────────────────────────┼──────────────────────────────────────────────────┘   │
│                                │                                                      │
│  ┌─────────────────────────────┼──────────────────────────────────────────────────┐   │
│  │              VPC: nihacio-nwspocaisofteng-vpc (10.40.132.0/22)                  │   │
│  │              All private subnets │ No IGW │ No NAT Gateway                      │   │
│  │                                                                                 │   │
│  │  ┌─────────────────────────────────────────────────────────────────────────┐    │   │
│  │  │  SUBNET: us-east-1a (10.40.137.0/24)    │  us-east-1b (10.40.138.0/24) │    │   │
│  │  │                                          │                              │    │   │
│  │  │  ┌──────────────────────────┐            │  ┌────────────────────────┐  │    │   │
│  │  │  │  OpenSearch (r6g.large)  │            │  │  OpenSearch (r6g.large)│  │    │   │
│  │  │  │  Node 1                  │            │  │  Node 2               │  │    │   │
│  │  │  │  sg: opensearch-sg       │            │  │  Zone-aware replica   │  │    │   │
│  │  │  └──────────────────────────┘            │  └────────────────────────┘  │    │   │
│  │  │                                          │                              │    │   │
│  │  │                                          │  ┌────────────────────────┐  │    │   │
│  │  │                                          │  │  Neptune (db.r8g.xl)  │  │    │   │
│  │  │                                          │  │  Writer instance      │  │    │   │
│  │  │                                          │  │  Port 8182 (Bolt+WSS) │  │    │   │
│  │  │                                          │  │  sg: default VPC SG   │  │    │   │
│  │  │                                          │  └────────────────────────┘  │    │   │
│  │  └─────────────────────────────────────────────────────────────────────────┘    │   │
│  │                                                                                 │   │
│  │  ┌─────────────────────────────────────────────────────────────────────────┐    │   │
│  │  │  SUBNET: us-east-1d (10.40.136.0/24)                                   │    │   │
│  │  │                                                                         │    │   │
│  │  │  ┌──────────────────────────────────────────────────────────────────┐   │    │   │
│  │  │  │  EC2: c6g.xlarge (ARM64) — 10.40.136.39                         │   │    │   │
│  │  │  │  OS: Amazon Linux 2023 │ Node.js 20 │ Python 3.9 │ Docker 25   │   │    │   │
│  │  │  │  sg: launch-wizard-1                                            │   │    │   │
│  │  │  │                                                                  │   │    │   │
│  │  │  │  ┌─────────────────────────────────────────────────────────┐     │   │    │   │
│  │  │  │  │  Kiro IDE (SSH Remote)                                  │     │   │    │   │
│  │  │  │  │  ├─ agentcore-mcp-rag: stdio proxy → AgentCore Runtime  │     │   │    │   │
│  │  │  │  │  └─ eib-mcp-gateway: HTTP → legacy on-prem (dev tunnel) │     │   │    │   │
│  │  │  │  └─────────────────────────────────────────────────────────┘     │   │    │   │
│  │  │  │                                                                  │   │    │   │
│  │  │  │  Mount: /mdc-mcp-rag (EFS, encrypted)                           │   │    │   │
│  │  │  │  Repo:  /mdc-mcp-rag/eib-mcp-rag-server (git: develop_aws)     │   │    │   │
│  │  │  └──────────────────────────────────────────────────────────────────┘   │    │   │
│  │  └─────────────────────────────────────────────────────────────────────────┘    │   │
│  │                                                                                 │   │
│  │  ┌─────────────────────────────────────────────────────────────────────────┐    │   │
│  │  │  VPC ENDPOINTS (10 — all private, no internet egress)                   │    │   │
│  │  │  • S3 (Gateway)           • Secrets Manager      • SSM                  │    │   │
│  │  │  • CloudWatch Logs        • ECR API              • ECR DKR              │    │   │
│  │  │  • Bedrock Runtime        • SageMaker API        • SageMaker Runtime    │    │   │
│  │  │  • API Gateway (execute-api)                                            │    │   │
│  │  └─────────────────────────────────────────────────────────────────────────┘    │   │
│  └─────────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                        │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐   │
│  │  SUPPORTING AWS SERVICES                                                        │   │
│  │                                                                                 │   │
│  │  ECR: mdc-mcp-rag (903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag)   │   │
│  │       └─ Tag: agentcore (302MB, pushed 2026-05-01)                              │   │
│  │                                                                                 │   │
│  │  S3:  mdc-mcp-rag-migration (versioned, encrypted, block public access)         │   │
│  │                                                                                 │   │
│  │  EFS: mdc-mcp-rag-efs (fs-032d52e4677000758, encrypted, lifecycle 30d)          │   │
│  │                                                                                 │   │
│  │  IAM: mdc-mcp-rag-ecs-task-role                                                 │   │
│  │       Trust: ecs-tasks.amazonaws.com + bedrock-agentcore.amazonaws.com           │   │
│  │       Policies: inline (Neptune, OpenSearch, S3, ECR, Secrets Manager, SSM)      │   │
│  │                                                                                 │   │
│  │  Secrets Manager: mdc-mcp-rag/neptune/credentials, mdc-mcp-rag/github/token     │   │
│  │  SSM Parameters:  /mdc-mcp-rag/neptune/endpoint, /mdc-mcp-rag/opensearch/...    │   │
│  │                                                                                 │   │
│  │  CloudFormation Stacks (CDK):                                                   │   │
│  │    • MdcVpcStack      (created 2026-04-06, VPC + endpoints)                     │   │
│  │    • MdcSecurityStack  (created 2026-04-07, Secrets + SSM + IAM)                │   │
│  │    • MdcDataStack      (created 2026-04-07, Neptune* + OpenSearch* + EFS + S3)  │   │
│  │    * Neptune & OpenSearch are imported (admin-created), not CDK-managed          │   │
│  └─────────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                        │
└────────────────────────────────────────────────────────────────────────────────────────┘
         │                                              │
         │ SSH (Kiro Remote)                            │ Dev Tunnel (HTTPS)
         │                                              │
┌────────┴───────────────────────┐    ┌─────────────────┴──────────────────────────────┐
│  DEVELOPER WORKSTATIONS        │    │  ON-PREMISES LEGACY SYSTEM (RDHPCS)            │
│                                │    │                                                │
│  ┌──────────┐  ┌──────────┐   │    │  Docker MCP Gateway (:18888)                    │
│  │  Kiro    │  │  Claude  │   │    │    └─ EIB-MCP-RAG Server (34 tools, v3.1)       │
│  │  IDE     │  │  Desktop │   │    │         ├─ ChromaDB (12 collections, 14.8K docs) │
│  └──────────┘  └──────────┘   │    │         └─ Neo4j 5.26 (4.2K nodes, 85K rels)    │
│                                │    │                                                │
│  MCP Connections:              │    │  Persistent: /mcp_rag_eib/ (25GB)              │
│  • agentcore-mcp-rag (stdio)  │    │  OS: Rocky Linux 9 │ Spack │ Docker Compose    │
│  • eib-mcp-gateway (HTTP)     │    │                                                │
└────────────────────────────────┘    └────────────────────────────────────────────────┘
```

---

## 3. Data Stores — Live Statistics

### 3.1 Neptune Graph Database

| Property | Value |
|----------|-------|
| **Cluster** | mdc-mcp-graprag-neptune-1 |
| **Engine** | Neptune 1.4.6.0 |
| **Instance** | db.r8g.xlarge (1 writer, us-east-1b) |
| **Port** | 8182 (Bolt over WSS) |
| **Auth** | IAM (SigV4) |
| **Encryption** | KMS at rest |
| **Security Group** | sg-06ee2c5e37b210420 (default VPC SG) |
| **Nodes** | 148,723 |
| **Relationships** | 2,820,440 |
| **Files indexed** | 17,273 |
| **Functions indexed** | 87,610 |
| **Fortran subroutines** | 27,941 |
| **Languages** | Shell, Python, Fortran |

**Relationship breakdown:**
| Type | Count |
|------|-------|
| CALLS | 2,216,985 |
| USES | 487,061 |
| DEFINES | 91,315 |
| DEPENDS_ON_ENV | 11,167 |
| IMPORTS | 10,443 |
| EXPORTS | 1,861 |
| INVOKES | 923 |
| SOURCES | 600 |
| EXECUTES | 85 |

### 3.2 OpenSearch Vector Database

| Property | Value |
|----------|-------|
| **Domain** | mdc-mcp-rag-search |
| **Engine** | OpenSearch 2.11 |
| **Instances** | 2× r6g.large.search (zone-aware, us-east-1a + 1b) |
| **Storage** | 2× 100GB gp3 (3000 IOPS) |
| **Security Group** | sg-085591f442d4cd7b6 |
| **Collections** | 17 |
| **Total Documents** | 206,341 |

**Collection breakdown:**
| Collection | Documents | Embedding |
|------------|-----------|-----------|
| mdc-code-context-titan1024 | 90,135 | Titan 1024-dim |
| mdc-code-context-mpnet768 | 60,576 | MPNet 768-dim |
| mdc-workflow-docs-titan1024 | 27,222 | Titan 1024-dim |
| mdc-workflow-docs-mpnet768 | 22,498 | MPNet 768-dim |
| mdc-community-summaries-titan1024 | 2,113 | Titan 1024-dim |
| mdc-community-summaries-mpnet768 | 2,113 | MPNet 768-dim |
| mdc-jjobs-titan1024 | 751 | Titan 1024-dim |
| mdc-jjobs-mpnet768 | 700 | MPNet 768-dim |
| mdc-workflow-docs-nova1024 | 150 | Nova 1024-dim |
| mdc-ee2-standards-titan1024 | 34 | Titan 1024-dim |
| mdc-ee2-standards-mpnet768 | 34 | MPNet 768-dim |
| ee2-standards-v7-0-0-titan1024 | 12 | Titan 1024-dim |

---

## 4. AgentCore Runtime

| Property | Value |
|----------|-------|
| **Runtime ID** | mdc_mcp_rag_server-TMXDllG2Wi |
| **Version** | 4 (deployed 2026-05-01) |
| **Status** | READY |
| **Protocol** | MCP (JSON-RPC over HTTP) |
| **Network** | VPC (us-east-1a, us-east-1b) |
| **Endpoint** | DEFAULT (live version 4) |
| **Container** | 903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:agentcore |
| **Execution Role** | mdc-mcp-rag-ecs-task-role |
| **Workload Identity** | mdc_mcp_rag_server-TMXDllG2Wi |
| **Idle Timeout** | 900s (15 min) |
| **Max Lifetime** | 28800s (8 hours) |
| **Compute** | Firecracker microVM (managed by AgentCore) |

**Environment Variables:**
```
DB_BACKEND=aws
NEPTUNE_ENDPOINT=wss://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182
OPENSEARCH_ENDPOINT=https://vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com
AWS_REGION=us-east-1
WORKFLOW_ROOT=/app/supported_repos/global-workflow
```

---

## 5. MCP Server — Tool Inventory (51 tools)

| Module | Tools | Backend |
|--------|-------|---------|
| Workflow Info | 3 | Static (filesystem) |
| Code Analysis | 5 | Neptune (graph) |
| Semantic Search | 6 | OpenSearch + Neptune (hybrid) |
| EE2 Compliance | 4 | OpenSearch |
| Operational | 3 | OpenSearch + Neptune |
| GitHub Integration | 4 | GitHub API |
| SDD Workflow | 9 | Local JSONL |
| Session/Utility | 3 | Local + health probes |
| Graph RAG | 14 | Neptune (cross-language trace, GGSR) |

---

## 6. Network & Security

### 6.1 VPC

| Property | Value |
|----------|-------|
| **VPC ID** | vpc-055f30ffa3d661e6b |
| **Name** | nihacio-nwspocaisofteng-vpc |
| **CIDR** | 10.40.132.0/22 |
| **Internet Gateway** | None |
| **NAT Gateway** | None |
| **Connectivity** | VPC Endpoints only (fully private) |

### 6.2 Subnets (active)

| Subnet | CIDR | AZ | Used By |
|--------|------|----|---------|
| subnet-0e13af6b3a9a6416f | 10.40.137.0/24 | us-east-1a | OpenSearch, AgentCore |
| subnet-04447750c61bd7e06 | 10.40.138.0/24 | us-east-1b | OpenSearch, Neptune, AgentCore |
| subnet-024fd9b597b3075a5 | 10.40.136.0/24 | us-east-1d | EC2 instance |

### 6.3 Security Groups

| SG ID | Name | Purpose |
|-------|------|---------|
| sg-06ee2c5e37b210420 | default | Neptune cluster |
| sg-096489a0876cc78c1 | mdc-mcp-rag-ecs-sg | ECS/AgentCore tasks |
| sg-085591f442d4cd7b6 | mdc-mcp-rag-opensearch-sg | OpenSearch domain |
| sg-04bd2b41beecd1201 | MdcDataStack-MdcEfs... | EFS mount targets |
| sg-09bb60ffa41137076 | launch-wizard-1 | EC2 instance |
| sg-054437d2d5ea5ece9 | nihacio-...-endpoints-sg | VPC endpoints |

### 6.4 VPC Endpoints (10)

| Service | Type |
|---------|------|
| S3 | Gateway |
| Secrets Manager | Interface |
| SSM | Interface |
| CloudWatch Logs | Interface |
| ECR API | Interface |
| ECR DKR | Interface |
| Bedrock Runtime | Interface |
| SageMaker API | Interface |
| SageMaker Runtime | Interface |
| API Gateway (execute-api) | Interface |

---

## 7. CloudFormation / CDK Stacks

| Stack | Created | Last Updated | Resources |
|-------|---------|-------------|-----------|
| MdcVpcStack | 2026-04-06 | 2026-04-07 | VPC, subnets, VPC endpoints |
| MdcSecurityStack | 2026-04-07 | 2026-04-22 | Secrets Manager, SSM, IAM |
| MdcDataStack | 2026-04-07 | 2026-04-22 | EFS, S3, Neptune (imported), OpenSearch (imported) |

**Note:** Neptune and OpenSearch are admin-created resources imported into CDK via
`fromDomainEndpoint()` — CDK does not manage their lifecycle. All stateful resources
have `removalPolicy: RETAIN` per the April 22 post-mortem guardrails.

---

## 8. Client Connectivity

### 8.1 Kiro IDE → AgentCore (production path)

```
Kiro IDE (developer laptop)
  └─ SSH Remote → EC2 (10.40.136.39)
       └─ stdio: python3 agentcore-kiro-proxy.py
            └─ boto3 invoke_agent_runtime (SigV4)
                 └─ AgentCore microVM (VPC)
                      └─ MCP Server (Node.js)
                           ├─ Neptune (Bolt+WSS, SigV4)
                           └─ OpenSearch (HTTPS, SigV4)
```

### 8.2 Kiro IDE → Legacy Gateway (reference path)

```
Kiro IDE (developer laptop)
  └─ SSH Remote → EC2 (10.40.136.39)
       └─ HTTP: dev tunnel → on-prem RDHPCS
            └─ Docker MCP Gateway (:18888)
                 └─ MCP Server (Node.js, Docker)
                      ├─ Neo4j (Bolt :7687)
                      └─ ChromaDB (HTTP :8080)
```

---

## 9. Data Volume Comparison

| Metric | Legacy (On-Prem) | AWS (Production) | Ratio |
|--------|-----------------|-------------------|-------|
| Graph nodes | 4,211 | 148,723 | 35× |
| Graph relationships | 85,894 | 2,820,440 | 33× |
| Vector documents | 14,856 | 206,341 | 14× |
| Languages indexed | Shell, Python | Shell, Python, Fortran | +1 |
| MCP tools | 34 | 51 | +17 |
| Server version | v3.1 | v3.6.2 | — |

---

## 10. Deployment History

| Date | Event | Version |
|------|-------|---------|
| 2026-04-06 | MdcVpcStack created (VPC, subnets, endpoints) | CDK |
| 2026-04-07 | MdcSecurityStack + MdcDataStack created | CDK |
| 2026-04-22 | Neptune data loss incident → CDK safety guardrails added | Post-mortem |
| 2026-04-23 | AgentCore container built + pushed to ECR | v1 |
| 2026-04-25 | Neptune SigV4 adapter + Fortran re-ingestion | v8.8.0 |
| 2026-04-27 | Fortran ingestion complete (63K nodes) | v8.8.1 |
| 2026-04-30 | AgentCore Runtime created (v2), Kiro proxy built | v8.9.0 |
| 2026-05-01 | Neptune policy fix, NeptuneAdapter optimized, Runtime v4 | v8.9.1 |

---

## 11. Known Issues & Next Steps

| Issue | Status | Priority |
|-------|--------|----------|
| AgentCore cold-start latency (60-90s first DB call) | Open | Medium |
| `list_job_scripts` / `get_job_details` path mismatch in container | Open | Low |
| Legacy gateway session drop under rapid sequential calls | Known (dev tunnel) | Low |
| `explain_with_context` thin responses on AWS backend | Open | Medium |
| Nova embedding collections empty (0 docs) | Open | Low |

---

*Generated from live AWS API queries on 2026-05-01.  
All resource IDs, endpoints, and statistics reflect actual deployed state.*
