# Requirements Document

## Introduction

The AWS AgentCore runtime (`mdc_mcp_rag_server_python-v5K2F8BGrN`) is running an
older Docker image (`python-tenants-v2`) that predates Phases 67–73. The code
fixes (path rename conformance, manifest scope field, ChromaDB adapter parity,
Fortran coverage-gap path fix, node-count scope annotations) are on `develop` but
the runtime won't pick them up until a new image is built, pushed to ECR, and the
runtime updated. This is a **routine image-rebuild + deploy** — no schema changes,
no data mutations, no new dependencies.

## Requirements

### Requirement 1: Build a new container image from current `develop`

#### Acceptance Criteria

1. THE image SHALL be built from `mcp_server_python/Dockerfile` at the current
   `develop` HEAD, incorporating Phases 67, 68, 70, 71, 72, and 73.
2. THE image SHALL target `linux/arm64` (AgentCore microVM architecture).
3. THE image SHALL be tagged `python-tenants-v3` plus a git-short-SHA suffix for
   traceability (e.g. `python-tenants-v3-e98b65a`).
4. A local smoke test (`get_server_info` via the proxy → 52+ tools, 9 modules)
   SHALL pass before the image is pushed.

### Requirement 2: Push to ECR preserving prior tags

#### Acceptance Criteria

1. THE image SHALL be pushed to
   `903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:python-tenants-v3`.
2. Prior tags (`python-tenants-v1`, `python-tenants-v2`) SHALL remain in the
   repository as rollback targets (no `--force` tag overwrite).

### Requirement 3: Update the AgentCore runtime

#### Acceptance Criteria

1. `update-agent-runtime` SHALL be called with the new `containerUri`, preserving
   all existing configuration: env vars (6), subnets (2), security group,
   EFS access point, protocol (MCP), lifecycle (idle 900s, max 28800s), metadata.
2. THE runtime SHALL reach `READY` state within 5 minutes of the update.
3. THE update command and its output SHALL be recorded in the run log.

### Requirement 4: Post-deploy verification

#### Acceptance Criteria

1. `mcp_health_check --deep --detailed --functional` → HEALTHY 4/4, ≥9/10
   functional pass (workflow_info SKIP is accepted — EFS not on EC2).
2. `get_knowledge_base_status` → `Total Documents > 0`, status `[OK] Healthy`,
   AND the new `(tenant scope)` annotation visible.
3. `check_knowledge_integrity` → Coverage Gap shows `[OK] ... (graph-only)`
   (not `[SKIP]`).
4. `get_knowledge_base_status(all_tenants=True)` → returns a whole-graph count
   ≥ the tenant-scoped count, labeled `(all tenants, all labels)`.

### Requirement 5: Rollback documented

#### Acceptance Criteria

1. THE rollback command (`update-agent-runtime` → `python-tenants-v2`) SHALL be
   recorded in the run log before the deploy.
2. Rollback SHALL be executable in a single command with no data-side effects.

### Requirement 6: Boundaries

#### Acceptance Criteria

1. No Neptune/OpenSearch/EFS data changes — this is runtime code only.
2. No new environment variables or network configuration changes.
3. No auto-commit or auto-push (git policy 08).
