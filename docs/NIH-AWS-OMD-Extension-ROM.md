# NIH AWS Sandbox — OMD AI Assistance Platform Extension: Rough Order of Magnitude (ROM) Cost Estimate

**Date:** June 25, 2026
**Author:** Terry McGuinness, NOAA NWS POCAI Software Engineering — OMD CAT Unit
**Audience:** NIH AWS Sandbox technical team
**Status:** Funding approved (June 25, 2026) — ROM submitted to size the extension envelope
**Region:** `us-east-1` · **Account:** `903050880929`
**Companion docs:** *NIH AWS Sandbox — OMD AI Assistance Platform Extension Proposal* (management
narrative), `MDC-MCP-RAG-AWS-Architecture-v3` (deployed architecture), `MCP-External-Access-Design-Path-B`
(extension design)

---

## 1. Purpose

This ROM sizes the steady-state monthly AWS spend for the OMD AI Assistance Platform after the
NIH-funded extension lands. It covers:

1. The **deployed prototype footprint** (already running under NIH Sandbox).
2. Two changes funded by this extension: the **EC2 upsize** (resolves recurring out-of-memory
   events during full re-ingestion / community detection runs) and the **first activation of
   Amazon SageMaker** for AI-side drift detection and domain-adaptive fine-tuning.
3. The **new external-access plane** (Cognito + Lambda token broker + CloudWatch audit).
4. Cost-control offset from the **operator-driven hibernation system** (specified under
   `.kiro/specs/nih-sandbox-cost-control/`).

ROM accuracy: ±25%. All figures are on-demand list pricing in `us-east-1` as of June 2026,
730 hr/month, before any Enterprise Discount Program (EDP) or Savings Plan negotiation.

---

## 2. Deployed Prototype — Specific Inventory

| Component | Resource ID / SKU | Notes |
|-----------|-------------------|-------|
| MCP runtime | Bedrock AgentCore Runtime `mdc_mcp_rag_server_python-v5K2F8BGrN` (v35) | Firecracker microVM, MCP/Streamable-HTTP, VPC-mode, idle 900 s / max 28,800 s |
| Embeddings | Bedrock `amazon.titan-embed-text-v2:0` (1024-dim) + baked-in MPNet (768-dim) + Nova (1024-dim) | 3 indices per program tenant |
| Graph DB | Neptune cluster `mdc-mcp-graprag-neptune-1`, engine 1.4.6.0, **`db.r8g.xlarge`** writer | 148,723 nodes / 2,820,440 rels; 100 GB storage; IAM SigV4 over Bolt+WSS:8182 |
| Vector DB | OpenSearch domain `mdc-mcp-rag-search`, **2× `r6g.large.search`** zone-aware, 2.11 | 17 indices / 206,341 docs; 2× 100 GB gp3 @ 3000 IOPS; KMS at rest |
| Dev / ingest host | EC2 **`c6g.xlarge`** ARM64, 10.40.136.39, 60 GB gp3 | **Memory pressure during full re-ingest & Leiden community detection — see §3** |
| Container registry | ECR `mdc-mcp-rag` (ARM64, `:agentcore` tag, ~302 MB) | 1 production tag + rolling staging tags |
| File system | EFS `mdc-mcp-rag-efs`, encrypted, 30-day IA lifecycle, AP `fsap-03e641f056b341f29` | ~50 GB warm / ~100 GB cold |
| Object storage | S3 `mdc-mcp-rag-migration`, versioned, KMS-encrypted | Snapshots, ingestion staging, backups |
| Secrets / config | Secrets Manager (Neptune creds, GitHub token) + SSM Parameter Store (endpoints, backend mode) | ~5 secrets |
| IAM | `mdc-mcp-rag-ecs-task-role` (trust: ECS + AgentCore) | Single execution role |
| Network | VPC `vpc-055f30ffa3d661e6b`, no IGW, no NAT, **10 interface/gateway endpoints** (S3 gw, Secrets, SSM, Logs, ECR API/DKR, Bedrock Runtime, SageMaker API/Runtime, execute-api) | Fully private data plane |
| Observability | CloudWatch Logs (audit + app) + metrics + alarms | JSON Lines audit format |
| KMS | 2 customer-managed keys (Neptune at-rest, OpenSearch at-rest) | RETAIN policy |
| IaC | CDK stacks `MdcVpcStack`, `MdcSecurityStack`, `MdcDataStack` | All stateful resources `RemovalPolicy: RETAIN` |

### Multi-tenant footprint

Tenants in production catalog: `gw`, `gw_sfs`, `gw_jedi_gfs`, `gw_v17`, `gw_gefs_v12`. Per-tenant
isolation via Neptune label predicates and OpenSearch index prefixes; no per-tenant infrastructure
duplication.

---

## 3. EC2 Upsize — Memory Justification

The current `c6g.xlarge` (4 vCPU / **8 GB RAM**) hits OOM during three operations that are now
routine, not exceptional:

1. **Full Bedrock Titan re-ingest** of the OpenSearch tenant set (~206 K docs at 1024-dim each;
   embedding generation + index writes peak at ~12 GB resident).
2. **Leiden community detection + LLM summarization** during graph hierarchy materialization
   (2,113 community summaries; peaks at ~10 GB working set in the Python driver).
3. **Parity test runs** that hold the legacy and AWS adapter responses in memory side-by-side
   across all 51 tools.

Recommended replacement: **`r7g.2xlarge`** (8 vCPU / **64 GB RAM**, ARM Graviton3, same KMS-encrypted
gp3 EBS). Rationale:

- 8× the RAM eliminates the three OOM scenarios with headroom for the Python-port parity workload.
- Graviton3 keeps us on ARM (no container image rebuild, same `:agentcore` tag works for local test).
- Memory-optimized (`r`) family is correct shape — these workloads are RAM-bound, not CPU-bound.
- Stays within hibernate scope: instance is stopped by the `Hibernate_Operation` outside business
  hours.

Alternative evaluated: `m6g.2xlarge` (8 vCPU / 32 GB) — rejected because the Leiden + Titan
re-ingest peak (~14 GB observed) leaves insufficient headroom for the OS + Docker + simultaneous
parity runs.

---

## 4. SageMaker — Activated Under This Extension

The SageMaker Processing/Training pipeline (`scripts/sagemaker_launcher.py`, `Dockerfile.sagemaker`,
`drift_detector.py`, `fine_tuning_pipeline.py`, `hard_negative_miner.py`) was **built but dormant**
in the prototype because it was not cost-justified for a single-user developer footprint. With NIH
extension funding and an expanding external-consumer base (CI + RDHPCS), it is **activated** for:

| Job | Cadence | Instance | Cost / Run | Monthly |
|-----|---------|----------|------------|---------|
| Drift detector (Bedrock Titan embedding drift vs. baseline) | Weekly | `ml.m5.large` | ~$0.02 | **~$1** |
| Hard-negative mining (improves retrieval P@5 by adding adversarial training pairs) | Monthly | `ml.m5.xlarge` | ~$1 | **~$1** |
| Domain-adaptive fine-tuning of MPNet 768-dim model | Quarterly | `ml.g5.xlarge`, 1–2 hr | $5–15 | **~$3–5** (amortized) |
| Re-ingestion (LLM community summarization, full tenant rebuild) | On-demand (~quarterly) | `ml.m5.2xlarge`, ~3 hr | ~$5 | **~$2** (amortized) |

**Steady-state SageMaker line item: ~$7–10/mo.** SageMaker is the AI/ML compute path that keeps
the knowledge base accurate as the Global Workflow source tree and documentation evolve.

---

## 5. External-Access Plane — New Resources Under This Extension

| Resource | Sizing |
|----------|--------|
| Cognito User Pool with 2 app clients (`CI_App_Client` client-credentials, `HPC_App_Client` auth-code) + resource server with scopes `mcp/ci-readonly`, `mcp/hpc-user` | Free tier covers expected MAU (≤ 50,000) |
| Lambda Token_Broker (Python 3.12, 256 MB, < 1 s per invocation) | ~10 K invocations/mo (CI runs + HPC sessions) |
| API Gateway in front of Token_Broker (regional, IAM auth via GitHub OIDC role) | ~10 K requests/mo |
| GitHub OIDC federated IAM role (no recurring cost) | — |
| AgentCore Runtime authorizer config (Cognito discovery URL + allowed scopes) | No additional cost — change to existing Runtime |
| CloudWatch Logs for audit (JSON Lines, one entry per tool invocation) | ~2 GB ingested/mo at projected load |

---

## 6. ROM — Monthly Steady-State Cost

All prices `us-east-1`, on-demand, 730 hr/mo, list pricing. Two columns: **24/7 active** vs.
**with hibernation** (operator-driven sleep ~50% of calendar time — nights, weekends, inter-burst).

| # | Service | SKU / Sizing | 24/7 Active | With Hibernation |
|---|---------|--------------|-------------:|------------------:|
| 1 | EC2 dev/ingest host | **`r7g.2xlarge`** (8 vCPU / 64 GB) | $313 | $156 |
| 2 | EC2 EBS | 200 GB gp3 (60 root + 140 data) + 3000 IOPS baseline | $20 | $20 |
| 3 | Neptune writer | `db.r8g.xlarge` | $333 | $167 |
| 4 | Neptune storage + I/O | 100 GB + ~2 M I/O ops | $30 | $20 |
| 5 | OpenSearch domain | 2× `r6g.large.search`, zone-aware | $244 | $122 |
| 6 | OpenSearch storage | 2× 100 GB gp3 @ 3000 IOPS | $25 | $25 |
| 7 | Bedrock AgentCore Runtime | Per-session microVM, projected 200 sessions/mo × ~10 min | $40 | $40 |
| 8 | Bedrock embeddings (Titan v2) | ~5 M tokens/mo at $0.02 / 1M | $1 | $1 |
| 9 | EFS | 50 GB warm + 50 GB IA | $18 | $18 |
| 10 | S3 | 100 GB Standard + ~10 K PUT/GET | $3 | $3 |
| 11 | ECR | 2 GB image storage | $0.20 | $0.20 |
| 12 | Secrets Manager | 5 secrets | $2 | $2 |
| 13 | SSM Parameter Store | Standard tier | $0 | $0 |
| 14 | VPC interface endpoints | 9 × $0.01/hr × 730 | $66 | $66 |
| 15 | VPC S3 gateway endpoint | — | $0 | $0 |
| 16 | KMS | 2 CMK | $2 | $2 |
| 17 | CloudWatch Logs | ~10 GB ingest + 30 GB retention | $8 | $8 |
| 18 | CloudWatch metrics + alarms | ~20 custom metrics, ~10 alarms | $5 | $5 |
| 19 | **SageMaker (extension)** | Drift + hard-neg + fine-tune + re-ingest | **$10** | **$10** |
| 20 | **Cognito (extension)** | 2 app clients, ≤ 50 K MAU | **$0** | **$0** |
| 21 | **Lambda Token_Broker (extension)** | 10 K invocations × 256 MB × < 1 s | **$0.50** | **$0.50** |
| 22 | **API Gateway (extension)** | 10 K requests | **$0.04** | **$0.04** |
| 23 | Data transfer | Intra-region + minor egress | $5 | $5 |
| | **Subtotal** | | **~$1,125** | **~$670** |
| | **ROM ±25% envelope** | | **$845 – $1,405** | **$505 – $840** |

**Recommended budget basis:** plan against the **24/7 active** column to stay safe during burst
weeks; expect actuals to track the **with-hibernation** column once the operator-driven sleep/wake
runbook is in routine use.

### Annual outlook

- **24/7 worst case:** ~$13,500/yr
- **With hibernation (steady operating mode):** ~$8,000/yr
- **Hibernation annual savings vs. 24/7:** **~$5,500/yr** — funds roughly half the next year's
  SageMaker fine-tuning cycles and Bedrock model upgrades.

---

## 7. One-Time / Setup Costs (Extension Scope)

| Item | ROM |
|------|----:|
| CDK stack additions (`MdcAuthStack`, Lambda packaging, IAM federated role) — engineering, no AWS spend | $0 |
| Initial SageMaker container build + push to ECR | < $1 |
| First fine-tuning run + baseline establishment | ~$15 |
| Penetration / auth-path validation (Cognito + JWT + scope-enforcement properties P1–P8) | $0 (internal) |
| Runbook authoring (CI + HPC) | $0 (internal) |
| **Total one-time AWS spend** | **< $20** |

---

## 8. Assumptions & Caveats

1. Pricing is **on-demand list** in `us-east-1`. EDP / Compute Savings Plans for the EC2 +
   Neptune + OpenSearch line could drop the 24/7 subtotal by 15–30%; not modeled here.
2. AgentCore Runtime is billed per-session-second; the $40/mo figure assumes 200 monthly sessions
   averaging 10 minutes (current developer-only load). External CI + HPC consumers will raise
   this — re-baseline after 90 days of mixed-tenant traffic.
3. Bedrock embedding cost is modest because re-ingestion is infrequent (drift-triggered).
   A full re-ingest of all 5 tenants × 3 embedding profiles is ~$5 one-time.
4. SageMaker quarterly fine-tuning is amortized; the actual invoice will be lumpy ($15 in the
   month of the run, $0 otherwise).
5. Hibernation savings assume ~50% calendar-time sleep. Actual will depend on operator discipline
   and research-burst cadence; the spec includes audit-log telemetry so we can measure this.
6. No GuardDuty / Security Hub / Inspector line items — those are funded under the broader
   NIH Sandbox security baseline, not this extension.
7. Data egress is modest because all backend traffic is VPC-private. Public egress is limited to
   AgentCore Runtime responses to CI/HPC callers.

---

## 9. Bottom Line for NIH AWS

- **Steady-state monthly ROM:** **~$670/mo** with hibernation, **~$1,125/mo** at 24/7 ceiling.
- **EC2 upsize (`c6g.xlarge` → `r7g.2xlarge`):** +~$240/mo, eliminates the three OOM scenarios
  blocking full re-ingestion and parity testing.
- **SageMaker activation:** +~$10/mo, unlocks drift detection, hard-negative mining, and
  domain-adaptive fine-tuning — the AI/ML compute path the platform was designed around.
- **External-access plane (Cognito + Lambda + API GW):** **< $1/mo** — the limiting factor on
  scaling to GitHub CI and RDHPCS users is engineering effort, not AWS cost.
- **Cost-control offset:** the hibernation system pays for the EC2 upsize and SageMaker
  activation roughly twice over each year.

Confidence: **medium-high** on lines 1–6, 9–18, 23 (measured against current invoices); **medium**
on AgentCore (line 7) and SageMaker (line 19) pending 90-day post-deployment re-baseline; **high**
on the extension line items (20–22) which are dominated by AWS free-tier coverage.
