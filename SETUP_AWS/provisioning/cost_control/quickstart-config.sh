#!/bin/bash
################################################################################
# quickstart-config.sh -- Shared resource ids for the quickstart wrappers
#
# Sourced by quickstart-{status,sleep,wake}.sh. Centralises the live sandbox
# resource ids and AWS region so the wrappers stay short. Override any value
# from the environment if needed (e.g. for a future second sandbox).
#
# This is the quickstart footprint -- the one currently running in account
# 903050880929 / us-east-1, the NIH Sandbox prototype. The full multi-env
# state-machine version lives in cost_control/cli.py and depends on the CDK
# stacks being deployed (RUNBOOK_cost_control.md).
################################################################################

# ASCII-only logging helpers (project convention).
log_info()  { echo "[INFO]  $*"; }
log_ok()    { echo "[OK]    $*"; }
log_warn()  { echo "[WARN]  $*" >&2; }
log_error() { echo "[ERROR] $*" >&2; }

# AWS region and account.
: "${AWS_REGION:=us-east-1}"
: "${AWS_ACCOUNT_ID:=903050880929}"

# Neptune cluster (graph DB).
: "${NEPTUNE_CLUSTER_ID:=mdc-mcp-graprag-neptune-1}"

# OpenSearch domain (vector DB).
: "${OPENSEARCH_DOMAIN_NAME:=mdc-mcp-rag-search}"
: "${OPENSEARCH_VPC_SECURITY_GROUP:=sg-085591f442d4cd7b6}"
: "${OPENSEARCH_PROD_SUBNETS:=subnet-0e13af6b3a9a6416f,subnet-04447750c61bd7e06}"
: "${OPENSEARCH_SLEEP_SUBNET:=subnet-0e13af6b3a9a6416f}"

# OpenSearch cluster shapes. Sleep is single-node single-AZ, no auto-tune.
# Production is the original multi-AZ shape verified live 2026-06-15.
: "${OPENSEARCH_PROD_INSTANCE_TYPE:=r6g.large.search}"
: "${OPENSEARCH_PROD_INSTANCE_COUNT:=2}"
: "${OPENSEARCH_SLEEP_INSTANCE_TYPE:=t3.small.search}"
: "${OPENSEARCH_SLEEP_INSTANCE_COUNT:=1}"

# AgentCore runtime (the Python one; the Node.js one was deleted 2026-06-15).
: "${AGENTCORE_RUNTIME_ID:=mdc_mcp_rag_server_python-v5K2F8BGrN}"

# EC2 host the operator runs from (this box).
: "${EC2_INSTANCE_ID:=i-0907ea89fb15fd90a}"

# Bucket for prehibernate snapshots (created 2026-06-15).
: "${SNAPSHOT_BUCKET:=mdc-mcp-rag-snapshots-${AWS_ACCOUNT_ID}}"

# Polling cadence.
: "${POLL_INTERVAL_S:=30}"
: "${NEPTUNE_WAKE_TIMEOUT_S:=1800}"
: "${OPENSEARCH_PROCESSING_TIMEOUT_S:=3600}"

# Verify aws CLI is on PATH; the wrappers all need it.
if ! command -v aws >/dev/null 2>&1; then
  log_error "aws CLI not found on PATH. Install it before running the wrappers."
  return 1 2>/dev/null || exit 1
fi

# Verify caller identity is resolvable -- catches expired creds early.
if ! aws sts get-caller-identity --output text --query Arn >/dev/null 2>&1; then
  log_error "AWS credentials not usable. Run 'aws sts get-caller-identity' to debug."
  return 1 2>/dev/null || exit 1
fi
