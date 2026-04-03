# Phase 49: Ingestion Pipeline Restructure

## Overview

Restructure the GraphRAG MCP server's ingestion pipeline from 14+ independent Python scripts with hardcoded embedding models into a modular, multi-model, idempotent pipeline. Introduces multi-model embedding support (MPNet, Titan, Nova Multimodal), model-aware collection naming, centralized backend routing, SageMaker compute offloading, hybrid BM25+vector search, graph-augmented retrieval, and a self-improving feedback loop with domain-adaptive fine-tuning.

## Kiro Spec Authority

- Requirements: `.kiro/specs/ingestion-pipeline-restructure/requirements.md` (32 requirements)
- Design: `.kiro/specs/ingestion-pipeline-restructure/design.md`
- Tasks: `.kiro/specs/ingestion-pipeline-restructure/tasks.md` (23 tasks)

## Sub-Phases

### Phase 49A: Core Python Infrastructure (Steps 0-4)
- Step 0: Embedding Model Registry (`embedding_registry.py`) + property tests P1-P2
- Step 1: Embedding Provider Abstraction (`embedding_provider.py`) + property test P3
- Step 2: Collection Namer (`collection_namer.py`) + property tests P4-P5
- Step 3: BaseIngester refactor (`ingestion_base.py`) — centralized routing, deterministic IDs, upsert/MERGE + property tests P6-P8
- Step 4: Refactor 7 ingestion scripts to subclass BaseIngester

### Phase 49B: Model-Aware AWS Integration (Steps 5-8)
- Step 5: `aws_backend.py` model-aware index routing + property tests P9-P10
- Step 6: Dead code archival (`mcp_server_python/` → `archive/`)
- Step 7: `create-opensearch-indices.js` multi-model support + property test P11
- Step 8: `migrate-to-aws.js` + `verify-migration.js` model-aware updates

### Phase 49C: Retrieval Enhancements (Steps 9-14)
- Step 9: HybridSearchBuilder.js — BM25 + vector + RRF fusion + property tests P12-P13
- Step 10: OpenSearchAdapter.js hybrid search mode
- Step 11: GraphAugmenter.js — 1-hop Neptune expansion + property test P14
- Step 12: MatryoshkaQuery.js — adaptive dimension truncation + property test P15
- Step 13: Comparative query support (VectorDatabaseAdapter + OpenSearchAdapter)
- Step 14: Wire all enhancements into UnifiedDataAccess.js

### Phase 49D: Observability and Compute (Steps 15-17)
- Step 15: FeedbackLogger.js — anonymized query-result pair logging + property test P16
- Step 16: SageMaker launcher (`sagemaker_launcher.py`) + ECR Dockerfile
- Step 17: Drift detection (`drift_detector.py`) + property test P17

### Phase 49E: Self-Improving Loop (Steps 18-20)
- Step 18: Retrieval quality benchmarking framework (`benchmark_runner.py`)
- Step 19: Domain-adaptive fine-tuning pipeline (`fine_tuning_pipeline.py`)
- Step 20: Graph-powered hard negative mining (`hard_negative_miner.py`)

## Total Steps: 21 (Steps 0-20)

## Dependencies

- Phase 48 (AWS Infrastructure Port) — COMPLETE
- VPC Endpoints — COMPLETE (10/10 provisioned)
- CDK Bootstrap — PENDING admin ticket
- CDK Deploy — BLOCKED on bootstrap

## Parallel Works Export Instructions

See `docs/parallel-works-export-runbook.md` for the full step-by-step.

Summary: PW VM uses your AWS credentials (same access key) to write to the
S3 bucket created by CDK on the AWS EC2 side. No CDK needed on PW.

1. Pull `develop_aws` on PW
2. `npm install` (gets @aws-sdk/client-s3)
3. Configure AWS credentials (env vars or aws configure)
4. `node scripts/migrate-to-aws.js --phase export-vectors`
5. `node scripts/migrate-to-aws.js --phase export-graph`
6. Verify with `aws s3 ls s3://mdc-mcp-rag-migration/`

## Branch

`develop_aws`
