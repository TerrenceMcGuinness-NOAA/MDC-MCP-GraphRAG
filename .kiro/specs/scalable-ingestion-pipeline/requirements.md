# Requirements Document

## Introduction

This feature refactors the ingestion pipeline from a serial, single-EC2 operator-run
process into a parallelized, SageMaker-backed batch system capable of processing
multiple tenants concurrently and running on-demand to prevent RAG drift as branches
evolve. The current Fortran ingester took 37 hours for one tenant on a 4-core EC2 —
unacceptable as we scale to 5+ tenants with regular refresh cycles.

After this feature lands:
- A full tenant ingestion (code + shell + Fortran + config + EXPDIR + Rocoto) runs
  in under 2 hours on a SageMaker Processing instance
- Multiple tenants can be processed in parallel
- Ingestion can be triggered on-demand (git push webhook or manual) to keep the RAG
  current with branch HEAD
- The pipeline is idempotent and resumable — interrupted runs can be continued

## Glossary

- **Ingestion_Pipeline**: The complete sequence of scripts that populate Neptune and OpenSearch for a tenant: code ingest → shell graph → Fortran graph → config files → EXPDIR → Rocoto XML → Fortran bridge
- **SageMaker_Processing_Job**: An AWS SageMaker managed compute job that spins up an instance, runs a container, and tears down — paying only for compute time used
- **RAG_Drift**: The condition where the knowledge base becomes stale relative to the source branch HEAD, causing the AI to answer based on outdated code
- **Tenant_Refresh**: A full re-ingestion of a tenant's data to bring it current with the branch tip
- **Parallel_Parser**: The refactored parsing layer that uses multiprocessing to parse files concurrently across available CPU cores
- **Per_File_Timeout**: A configurable maximum time allowed for parsing a single file before it is skipped and logged as a timeout failure
- **Batch_Orchestrator**: The top-level script or Step Function that sequences the ingestion stages and manages parallelism across tenants
- **Incremental_Mode**: Ingesting only files changed since the last run (git diff-based) rather than the full tree

## Requirements

### Requirement 1: Parallel File Parsing

**User Story:** As an operator, I want file parsing to use all available CPU cores so that ingestion completes in hours, not days.

#### Acceptance Criteria

1. THE Fortran_AST_Ingester SHALL use Python multiprocessing (Pool or ProcessPoolExecutor) to parse files across N worker processes, where N defaults to `os.cpu_count() - 1` and is overridable via `--workers`
2. THE Shell_Graph_Ingester SHALL support the same `--workers` flag for parallel parsing of shell scripts
3. EACH worker process SHALL have an independent fparser2/ShellScriptParser instance (no shared mutable state)
4. WHEN a file takes longer than the Per_File_Timeout (default 120 seconds, overridable via `--timeout`), THE worker SHALL terminate parsing of that file, log a timeout warning, and continue with the next file
5. THE parallel parsing SHALL preserve correctness — the same set of parse results regardless of worker count (deterministic output)
6. THE progress reporting SHALL aggregate results from all workers and print unified progress lines

### Requirement 2: SageMaker Processing Job Integration

**User Story:** As an operator, I want to offload ingestion to a large SageMaker instance so I can process big tenants quickly without tying up the development EC2.

#### Acceptance Criteria

1. THE Batch_Orchestrator SHALL support a `--backend {local,sagemaker}` flag: `local` runs on the current host (existing behavior); `sagemaker` submits to SageMaker Processing
2. WHEN `--backend sagemaker` is specified, THE orchestrator SHALL create a SageMaker Processing Job using the configured instance type (default `ml.m5.4xlarge` — 16 vCPU, 64GB RAM), Docker image, and IAM role
3. THE SageMaker Processing Job SHALL have network access to Neptune and OpenSearch (same VPC subnets and security groups as the AgentCore runtime)
4. THE SageMaker Processing Job SHALL mount the EFS filesystem at `/mnt/workflow` (same access point as the AgentCore runtime) to access tenant worktrees
5. THE SageMaker Processing Job SHALL write ingestion reports to S3 (`s3://mdc-mcp-rag-artifacts/ingestion-reports/`) and to the EFS-backed reports directory
6. THE SageMaker Processing Job SHALL exit with code 0 on success, non-zero on failure, and emit CloudWatch metrics for monitoring
7. THE Docker image for SageMaker SHALL be the same ECR image used by the AgentCore runtime (`mdc-mcp-rag:python-tenants-*`), extended with fparser2 and multiprocessing dependencies if needed

### Requirement 3: Multi-Tenant Concurrent Processing

**User Story:** As an operator managing 5+ workflow branches, I want to refresh multiple tenants simultaneously so that the full catalog stays current.

#### Acceptance Criteria

1. THE Batch_Orchestrator SHALL accept `--tenants all` (process every tenant in the catalog) or `--tenants gw_v17,gw_sfs` (specific list)
2. WHEN multiple tenants are specified, THE orchestrator SHALL launch one SageMaker Processing Job per tenant (concurrent execution)
3. THE orchestrator SHALL respect a configurable concurrency limit (`--max-concurrent`, default 3) to avoid overwhelming Neptune/OpenSearch
4. EACH tenant's ingestion SHALL be independent — one tenant's failure SHALL NOT block or cancel other tenants' jobs
5. THE orchestrator SHALL produce a summary report listing each tenant's status (success/failure/duration/node-counts)

### Requirement 4: On-Demand Triggering for RAG Drift Prevention

**User Story:** As a system maintainer, I want ingestion to run automatically when a branch is updated so the RAG never falls more than N hours behind.

#### Acceptance Criteria

1. THE system SHALL support a webhook endpoint (or EventBridge rule) that triggers ingestion when a tenant's branch receives a push
2. THE webhook handler SHALL resolve the pushed branch to the matching tenant_id and trigger an incremental ingestion (`--mode diff`)
3. THE system SHALL support a scheduled trigger (cron or EventBridge Schedule) for periodic full refreshes (e.g. weekly `--mode full`)
4. THE system SHALL track last-ingested commit SHA per tenant and skip ingestion if HEAD has not advanced since the last run
5. WHEN incremental mode detects zero changed files, THE system SHALL log "no changes" and exit 0 without submitting a SageMaker job

### Requirement 5: Resumable and Idempotent Execution

**User Story:** As an operator, I want interrupted ingestion runs to be resumable so that transient failures don't require starting from scratch.

#### Acceptance Criteria

1. THE ingestion pipeline SHALL checkpoint progress after each stage (code → shell → Fortran → config → EXPDIR → Rocoto → bridge) so that a re-run can skip completed stages
2. THE checkpoint SHALL be stored in S3 or the ingestion reports directory as a JSON file with completed stages and their outputs
3. WHEN a `--resume` flag is passed, THE orchestrator SHALL read the checkpoint and skip stages already marked complete
4. ALL Neptune writes SHALL continue to use MERGE semantics so that re-running a stage produces no duplicates
5. THE SageMaker Processing Job SHALL have a configurable maximum runtime (default 4 hours) after which it is terminated and the checkpoint reflects partial completion

### Requirement 6: Instance Right-Sizing

**User Story:** As a cost-conscious operator, I want the system to use the smallest instance that can complete the job within the time budget.

#### Acceptance Criteria

1. THE orchestrator SHALL support configurable instance types per ingestion stage (Fortran parsing needs more CPU/memory than shell parsing)
2. THE default instance configuration SHALL be:
   - Fortran graph: `ml.m5.4xlarge` (16 vCPU, 64GB — CPU-bound parsing)
   - Shell/Config/EXPDIR/Rocoto: `ml.m5.xlarge` (4 vCPU, 16GB — lighter work)
   - Code ingest (embeddings): `ml.m5.xlarge` (4 vCPU — Bedrock-call-bound, not CPU-bound)
3. THE system SHALL log instance utilization (CPU%, memory%) in the ingestion report for future right-sizing decisions

### Requirement 7: Observability and Alerting

**User Story:** As an operator, I want to monitor ingestion health and be alerted on failures so I can intervene quickly.

#### Acceptance Criteria

1. THE orchestrator SHALL emit CloudWatch custom metrics: `ingestion/duration_seconds`, `ingestion/nodes_created`, `ingestion/parse_success_rate`, `ingestion/status` (per tenant)
2. THE orchestrator SHALL log to CloudWatch Logs under a dedicated log group (`/mdc-mcp-rag/ingestion`)
3. WHEN a job fails or parse_success_rate drops below 80%, THE system SHALL publish to an SNS topic for operator alerting
4. THE ingestion report JSON SHALL include timing breakdowns per stage so bottlenecks can be identified

### Requirement 8: Backward Compatibility

**User Story:** As a developer, I want the existing local-run mode to continue working unchanged so that small/quick ingestions don't require SageMaker.

#### Acceptance Criteria

1. ALL existing ingestion scripts SHALL continue to work with `--backend local` (the default) — no behavior change for current operator workflows
2. THE parallel parsing (`--workers`) and timeout (`--timeout`) improvements SHALL apply to both local and SageMaker backends
3. THE refactored scripts SHALL pass all existing unit and property tests without modification
4. THE `--dry-run` flag SHALL continue to work identically for both backends (parse + summarize, no writes)

### Requirement 9: Security and Access Control

**User Story:** As a security-conscious operator, I want SageMaker jobs to use least-privilege IAM roles and not expose credentials in job definitions.

#### Acceptance Criteria

1. THE SageMaker Processing Job SHALL assume a dedicated IAM role (`mdc-mcp-rag-sagemaker-processing-role`) with permissions limited to: Neptune query/write, OpenSearch index/write, S3 read/write on the artifacts bucket, EFS mount, CloudWatch metrics/logs, ECR pull
2. THE IAM role SHALL NOT have permissions to modify IAM, create/delete infrastructure, or access other AWS accounts
3. Secrets (GitHub token, etc.) SHALL be injected via Secrets Manager at job startup, not passed as environment variables in the job definition
4. THE SageMaker VPC configuration SHALL use the same private subnets and security group as the AgentCore runtime (no public internet access)
