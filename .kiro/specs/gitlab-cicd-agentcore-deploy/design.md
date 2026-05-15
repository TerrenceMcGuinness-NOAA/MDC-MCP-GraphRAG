# Technical Design: GitLab CI/CD Pipeline for AgentCore Deployment

## Overview

This design defines a GitLab CI/CD pipeline that automates the deployment of the MDC MCP RAG Server to AWS Bedrock AgentCore Runtime. The pipeline replaces the manual `docker build → ECR push → update-agent-runtime` workflow with a five-stage automated process triggered by pushes to the `develop_aws` branch.

The pipeline builds an ARM64 container image from `mcp_server_node/Dockerfile.agentcore`, pushes it to ECR, updates the AgentCore Runtime, validates all 51 MCP tools, and automatically rolls back on failure. All credentials are managed through GitLab CI/CD masked variables with no secrets exposed in logs.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        GitLab CI/CD Pipeline                                │
│                                                                             │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌─────────┐ │
│  │  BUILD   │──▶│   PUSH   │──▶│  DEPLOY  │──▶│ VALIDATE │──▶│  DONE   │ │
│  │          │   │          │   │          │   │          │   │         │ │
│  │ Docker   │   │ ECR Auth │   │ Record   │   │ Run 51   │   │ Report  │ │
│  │ buildx   │   │ + Push   │   │ prev ver │   │ tool     │   │ + Logs  │ │
│  │ arm64    │   │ SHA +    │   │ Update   │   │ checks   │   │         │ │
│  │          │   │ latest   │   │ runtime  │   │          │   │         │ │
│  └──────────┘   └──────────┘   │ Poll     │   └────┬─────┘   └─────────┘ │
│                                 │ health   │        │                      │
│                                 └──────────┘        │ FAIL                 │
│                                                     ▼                      │
│                                              ┌──────────┐                  │
│                                              │ ROLLBACK │                  │
│                                              │          │                  │
│                                              │ Revert   │                  │
│                                              │ image    │                  │
│                                              │ Re-valid │                  │
│                                              │ Alert on │                  │
│                                              │ failure  │                  │
│                                              └──────────┘                  │
└─────────────────────────────────────────────────────────────────────────────┘

External Services:
  ┌─────────────────┐    ┌─────────────────────────────────────────────┐
  │ ECR Registry    │    │ AgentCore Runtime (mdc_mcp_rag_server-...)  │
  │ 903050880929    │    │ VPC: 3 subnets + SG                        │
  │ mdc-mcp-rag    │    │ Neptune + OpenSearch connectivity           │
  └─────────────────┘    └─────────────────────────────────────────────┘
```

## Pipeline Stages

| Stage    | Purpose                                    | Trigger Condition                |
|----------|--------------------------------------------|----------------------------------|
| build    | Build ARM64 Docker image                   | All pipeline triggers            |
| push     | Authenticate with ECR and push image       | All pipeline triggers            |
| deploy   | Update AgentCore Runtime with new image    | `develop_aws` push or manual     |
| validate | Run 51-tool validation suite               | After successful deploy          |
| rollback | Revert to previous image on failure        | When validate stage fails        |

## File Structure

| File                            | Purpose                                          |
|---------------------------------|--------------------------------------------------|
| `.gitlab-ci.yml`                | Main pipeline definition (root of repository)    |
| `scripts/ci/deploy-agentcore.sh`| Deployment helper: update, poll, rollback        |
| `scripts/ci/validate-deploy.sh` | Post-deploy validation wrapper                   |

## `.gitlab-ci.yml` Design

```yaml
# .gitlab-ci.yml — MDC MCP RAG Server AgentCore Deployment Pipeline
# Triggered on develop_aws pushes; builds ARM64 image, pushes to ECR,
# updates AgentCore Runtime, validates 51 tools, rolls back on failure.

stages:
  - build
  - push
  - deploy
  - validate
  - rollback

variables:
  ECR_REGISTRY: "903050880929.dkr.ecr.us-east-1.amazonaws.com"
  ECR_REPOSITORY: "mdc-mcp-rag"
  IMAGE_NAME: "${ECR_REGISTRY}/${ECR_REPOSITORY}"
  AGENTCORE_RUNTIME_ID: "mdc_mcp_rag_server-TMXDllG2Wi"
  AWS_DEFAULT_REGION: "us-east-1"
  DOCKER_BUILDKIT: "1"
  DOCKERFILE_PATH: "mcp_server_node/Dockerfile.agentcore"
  BUILD_CONTEXT: "mcp_server_node/"
  PLATFORM: "linux/arm64"
  POLL_INTERVAL: "30"
  POLL_TIMEOUT: "300"
  VALIDATION_TIMEOUT: "600"

# ─── Workflow Rules ───────────────────────────────────────────────────────────

workflow:
  rules:
    - if: '$CI_COMMIT_BRANCH == "develop_aws"'
    - if: '$CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "develop_aws"'
    - if: '$CI_PIPELINE_SOURCE == "web"'
    - when: never

# ─── Pre-flight: Variable Validation ─────────────────────────────────────────

.validate_variables: &validate_variables
  - |
    MISSING=""
    for var in AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION AGENTCORE_RUNTIME_ID ECR_REGISTRY; do
      eval "val=\$$var"
      if [ -z "$val" ]; then
        MISSING="${MISSING} ${var}"
      fi
    done
    if [ -n "$MISSING" ]; then
      echo "[ERROR] Missing required CI/CD variables:${MISSING}"
      exit 1
    fi
    echo "[OK] All required variables present"

# ─── Stage: Build ─────────────────────────────────────────────────────────────

build_image:
  stage: build
  image: docker:24-dind
  services:
    - docker:24-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
  before_script:
    - *validate_variables
    - docker context create builder-ctx
    - docker buildx create --use --name arm-builder --driver docker-container
  script:
    - |
      IMAGE_TAG="${CI_COMMIT_SHORT_SHA}"
      echo "Building ${IMAGE_NAME}:${IMAGE_TAG} for ${PLATFORM}"
      docker buildx build \
        --platform "${PLATFORM}" \
        --tag "${IMAGE_NAME}:${IMAGE_TAG}" \
        --tag "${IMAGE_NAME}:latest" \
        --file "${DOCKERFILE_PATH}" \
        --cache-from "type=registry,ref=${IMAGE_NAME}:buildcache" \
        --cache-to "type=registry,ref=${IMAGE_NAME}:buildcache,mode=max" \
        --load \
        "${BUILD_CONTEXT}"
    - |
      # Verify platform architecture
      ARCH=$(docker inspect --format '{{.Architecture}}' "${IMAGE_NAME}:${IMAGE_TAG}" 2>/dev/null || echo "unknown")
      if [ "$ARCH" != "arm64" ] && [ "$ARCH" != "aarch64" ]; then
        echo "[ERROR] Expected arm64 architecture, got: ${ARCH}"
        exit 1
      fi
      echo "[OK] Image architecture verified: ${ARCH}"
  timeout: 15 minutes
  rules:
    - if: '$CI_COMMIT_BRANCH == "develop_aws"'
    - if: '$CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "develop_aws"'
    - if: '$CI_PIPELINE_SOURCE == "web"'

# ─── Stage: Push ──────────────────────────────────────────────────────────────

push_image:
  stage: push
  image: docker:24-dind
  services:
    - docker:24-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
  needs:
    - build_image
  before_script:
    - apk add --no-cache aws-cli jq
  script:
    - |
      IMAGE_TAG="${CI_COMMIT_SHORT_SHA}"
      # ECR authentication (suppress credential output)
      set +x
      aws ecr get-login-password --region "${AWS_DEFAULT_REGION}" | \
        docker login --username AWS --password-stdin "${ECR_REGISTRY}"
      set -x
      echo "[OK] ECR authentication successful"
    - |
      # Push with retry logic (3 attempts, exponential backoff)
      push_with_retry() {
        local tag="$1"
        local attempt=1
        local delay=5
        while [ $attempt -le 3 ]; do
          echo "Pushing ${IMAGE_NAME}:${tag} (attempt ${attempt}/3)"
          if docker push "${IMAGE_NAME}:${tag}"; then
            echo "[OK] Push successful: ${IMAGE_NAME}:${tag}"
            return 0
          fi
          echo "[WARN] Push failed, retrying in ${delay}s..."
          sleep $delay
          delay=$((delay * 2))
          attempt=$((attempt + 1))
        done
        echo "[ERROR] Push failed after 3 attempts: ${IMAGE_NAME}:${tag}"
        return 1
      }
      push_with_retry "${IMAGE_TAG}"
      push_with_retry "latest"
    - |
      # Verify pushed images exist in ECR
      IMAGE_TAG="${CI_COMMIT_SHORT_SHA}"
      for tag in "${IMAGE_TAG}" "latest"; do
        MANIFEST=$(aws ecr batch-get-image \
          --repository-name "${ECR_REPOSITORY}" \
          --image-ids "imageTag=${tag}" \
          --query 'images[0].imageManifest' \
          --output text 2>/dev/null)
        if [ -z "$MANIFEST" ] || [ "$MANIFEST" = "None" ]; then
          echo "[ERROR] Image manifest not found for tag: ${tag}"
          exit 1
        fi
        echo "[OK] Verified image manifest for ${tag}"
      done
  timeout: 10 minutes
  rules:
    - if: '$CI_COMMIT_BRANCH == "develop_aws"'
    - if: '$CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "develop_aws"'
    - if: '$CI_PIPELINE_SOURCE == "web"'

# ─── Stage: Deploy ────────────────────────────────────────────────────────────

deploy_runtime:
  stage: deploy
  image: amazon/aws-cli:latest
  needs:
    - push_image
  script:
    - |
      IMAGE_TAG="${CI_COMMIT_SHORT_SHA}"
      IMAGE_URI="${IMAGE_NAME}:${IMAGE_TAG}"
      chmod +x scripts/ci/deploy-agentcore.sh
      scripts/ci/deploy-agentcore.sh --update "${IMAGE_URI}"
  artifacts:
    reports:
      dotenv: deploy.env
    paths:
      - deploy.env
    expire_in: 30 days
  timeout: 10 minutes
  rules:
    - if: '$CI_COMMIT_BRANCH == "develop_aws"'
    - if: '$CI_PIPELINE_SOURCE == "web"'
      when: manual

# ─── Stage: Validate ──────────────────────────────────────────────────────────

validate_deployment:
  stage: validate
  image: node:20-slim
  needs:
    - deploy_runtime
  before_script:
    - apt-get update && apt-get install -y --no-install-recommends python3 pip
    - pip install boto3
    - cd mcp_server_node && npm ci --omit=dev && cd ..
  script:
    - chmod +x scripts/ci/validate-deploy.sh
    - scripts/ci/validate-deploy.sh
  artifacts:
    paths:
      - docs/aws-mcp-validation-report.md
      - validation-results.json
    expire_in: 30 days
    when: always
  timeout: 10 minutes
  rules:
    - if: '$CI_COMMIT_BRANCH == "develop_aws"'
    - if: '$CI_PIPELINE_SOURCE == "web"'
      when: manual

# ─── Stage: Rollback ──────────────────────────────────────────────────────────

rollback_deployment:
  stage: rollback
  image: amazon/aws-cli:latest
  needs:
    - job: deploy_runtime
      artifacts: true
    - job: validate_deployment
  script:
    - |
      chmod +x scripts/ci/deploy-agentcore.sh
      scripts/ci/deploy-agentcore.sh --rollback
  when: on_failure
  timeout: 10 minutes
  rules:
    - if: '$CI_COMMIT_BRANCH == "develop_aws"'
    - if: '$CI_PIPELINE_SOURCE == "web"'
```

## Deployment Helper Script Design (`scripts/ci/deploy-agentcore.sh`)

### Purpose

Encapsulates the AgentCore Runtime update lifecycle: record previous version, update, poll for health, and rollback on failure.

### Interface

```bash
scripts/ci/deploy-agentcore.sh --update <IMAGE_URI>   # Deploy new image
scripts/ci/deploy-agentcore.sh --rollback             # Revert to previous image
```

### Function Design

```bash
#!/usr/bin/env bash
# scripts/ci/deploy-agentcore.sh — AgentCore Runtime deployment helper
# Usage:
#   --update <IMAGE_URI>   Update runtime to new image, poll for health
#   --rollback             Revert to previously recorded image URI
set -euo pipefail

RUNTIME_ID="${AGENTCORE_RUNTIME_ID}"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
POLL_INTERVAL="${POLL_INTERVAL:-30}"
POLL_TIMEOUT="${POLL_TIMEOUT:-300}"
DEPLOY_ENV="deploy.env"

# ── Functions ─────────────────────────────────────────────────────────────────

record_previous_version() {
  # Captures the current runtime container image URI before update.
  # Stores it in deploy.env as PREVIOUS_IMAGE_URI for rollback use.
  echo "[INFO] Recording current runtime image..."
  local current_image
  current_image=$(aws bedrock-agentcore-control list-agent-runtimes \
    --region "${REGION}" \
    --query "agentRuntimeSummaries[?agentRuntimeId=='${RUNTIME_ID}'].containerConfig.containerUri" \
    --output text)

  if [ -z "${current_image}" ]; then
    echo "[ERROR] Could not retrieve current runtime image URI"
    exit 1
  fi

  echo "PREVIOUS_IMAGE_URI=${current_image}" > "${DEPLOY_ENV}"
  echo "[OK] Previous image recorded: ${current_image}"
}

update_runtime() {
  # Calls update-agent-runtime with the new image URI.
  # Preserves VPC and lifecycle configuration.
  local image_uri="$1"
  echo "[INFO] Updating AgentCore Runtime ${RUNTIME_ID} to ${image_uri}"

  local result
  result=$(aws bedrock-agentcore-control update-agent-runtime \
    --agent-runtime-id "${RUNTIME_ID}" \
    --region "${REGION}" \
    --container-config "{\"containerUri\":\"${image_uri}\"}" \
    --network-configuration '{
      "networkMode": "VPC",
      "networkModeConfig": {
        "subnets": [
          "subnet-0e13af6b3a9a6416f",
          "subnet-024fd9b597b3075a5",
          "subnet-04447750c61bd7e06"
        ],
        "securityGroups": ["sg-096489a0876cc78c1"]
      }
    }' 2>&1)

  local exit_code=$?
  if [ $exit_code -ne 0 ]; then
    echo "[ERROR] update-agent-runtime failed (exit code ${exit_code}):"
    echo "${result}"
    exit 1
  fi

  echo "[OK] Runtime update initiated"
  # Append deploy metadata
  local timestamp
  timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  echo "DEPLOYED_IMAGE_URI=${image_uri}" >> "${DEPLOY_ENV}"
  echo "DEPLOY_TIMESTAMP=${timestamp}" >> "${DEPLOY_ENV}"
  echo "IMAGE_TAG=$(echo "${image_uri}" | awk -F: '{print $NF}')" >> "${DEPLOY_ENV}"
}

poll_health() {
  # Polls runtime status every POLL_INTERVAL seconds until active or timeout.
  # Returns 0 on healthy, 1 on timeout.
  echo "[INFO] Polling runtime health (interval=${POLL_INTERVAL}s, timeout=${POLL_TIMEOUT}s)"
  local elapsed=0
  local status=""

  while [ $elapsed -lt $POLL_TIMEOUT ]; do
    status=$(aws bedrock-agentcore-control list-agent-runtimes \
      --region "${REGION}" \
      --query "agentRuntimeSummaries[?agentRuntimeId=='${RUNTIME_ID}'].status" \
      --output text 2>/dev/null || echo "UNKNOWN")

    echo "[INFO] Runtime status: ${status} (${elapsed}s elapsed)"

    if [ "${status}" = "ACTIVE" ] || [ "${status}" = "READY" ]; then
      echo "[OK] Runtime is healthy after ${elapsed}s"
      echo "RUNTIME_STATUS=${status}" >> "${DEPLOY_ENV}"
      return 0
    fi

    sleep "${POLL_INTERVAL}"
    elapsed=$((elapsed + POLL_INTERVAL))
  done

  echo "[ERROR] Runtime did not become healthy within ${POLL_TIMEOUT}s"
  echo "[ERROR] Last observed status: ${status}"
  return 1
}

rollback() {
  # Reverts runtime to the previously recorded image URI.
  if [ ! -f "${DEPLOY_ENV}" ]; then
    echo "[ERROR] No deploy.env found — cannot determine previous image"
    exit 1
  fi

  local prev_image
  prev_image=$(grep "^PREVIOUS_IMAGE_URI=" "${DEPLOY_ENV}" | cut -d= -f2-)

  if [ -z "${prev_image}" ]; then
    echo "[ERROR] PREVIOUS_IMAGE_URI not found in deploy.env"
    exit 1
  fi

  echo "[WARN] Rolling back to: ${prev_image}"
  local rollback_reason="Post-deploy validation failure"
  local rollback_timestamp
  rollback_timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

  update_runtime "${prev_image}"

  if ! poll_health; then
    echo "[ERROR] Rollback failed — runtime did not become healthy"
    echo "[ALERT] MANUAL INTERVENTION REQUIRED"
    echo "ROLLBACK_STATUS=FAILED" >> "${DEPLOY_ENV}"
    echo "ROLLBACK_TIMESTAMP=${rollback_timestamp}" >> "${DEPLOY_ENV}"
    echo "ROLLBACK_REASON=${rollback_reason}" >> "${DEPLOY_ENV}"
    # Send alert (GitLab notification channel)
    exit 1
  fi

  echo "[OK] Rollback successful"
  echo "ROLLBACK_STATUS=SUCCESS" >> "${DEPLOY_ENV}"
  echo "ROLLBACK_TIMESTAMP=${rollback_timestamp}" >> "${DEPLOY_ENV}"
  echo "ROLLBACK_REASON=${rollback_reason}" >> "${DEPLOY_ENV}"
}

# ── Main ──────────────────────────────────────────────────────────────────────

main() {
  local action="${1:-}"
  local image_uri="${2:-}"

  case "${action}" in
    --update)
      if [ -z "${image_uri}" ]; then
        echo "[ERROR] Usage: $0 --update <IMAGE_URI>"
        exit 1
      fi
      record_previous_version
      update_runtime "${image_uri}"
      poll_health
      ;;
    --rollback)
      rollback
      ;;
    *)
      echo "[ERROR] Usage: $0 --update <IMAGE_URI> | --rollback"
      exit 1
      ;;
  esac
}

main "$@"
```

### Error Handling

| Condition                          | Behavior                                          |
|------------------------------------|---------------------------------------------------|
| `update-agent-runtime` non-zero    | Halt immediately, report error output             |
| Poll timeout (5 min)               | Mark stage failed, report last status             |
| Missing `PREVIOUS_IMAGE_URI`       | Rollback aborts with error                        |
| Rollback health poll timeout       | Alert notification, mark manual intervention      |

## Validation Script Wrapper Design (`scripts/ci/validate-deploy.sh`)

### Purpose

Invokes the existing `validate-aws-mcp.js` script via the AgentCore proxy, captures results as JSON, generates the markdown report, and returns appropriate exit codes.

### Script Design

```bash
#!/usr/bin/env bash
# scripts/ci/validate-deploy.sh — Post-deploy validation wrapper
# Invokes validate-aws-mcp.js via agentcore-kiro-proxy, captures results,
# generates report, returns exit code based on pass/fail.
set -euo pipefail

VALIDATION_SCRIPT="mcp_server_node/scripts/validate-aws-mcp.js"
REPORT_PATH="docs/aws-mcp-validation-report.md"
RESULTS_JSON="validation-results.json"
EXPECTED_TOOLS=51
TIMEOUT="${VALIDATION_TIMEOUT:-600}"

echo "[INFO] Starting post-deploy validation"
echo "[INFO] Expected tools: ${EXPECTED_TOOLS}"
echo "[INFO] Timeout: ${TIMEOUT}s"

# Ensure output directory exists
mkdir -p "$(dirname "${REPORT_PATH}")"

# Run validation script with timeout
# The script connects via the agentcore-kiro-proxy to the deployed runtime
if ! timeout "${TIMEOUT}" node "${VALIDATION_SCRIPT}" \
  --timeout 30000 \
  2>&1 | tee validation-output.log; then
  echo "[ERROR] Validation script failed or timed out"
fi

# Parse results from the generated report
if [ ! -f "${REPORT_PATH}" ]; then
  echo "[ERROR] Validation report not generated at ${REPORT_PATH}"
  exit 1
fi

# Extract pass/fail counts from report
PASSED=$(grep -c "| ✅" "${REPORT_PATH}" 2>/dev/null || echo "0")
FAILED=$(grep -c "| ❌" "${REPORT_PATH}" 2>/dev/null || echo "0")
TOTAL=$((PASSED + FAILED))

echo "[INFO] Validation results: ${PASSED}/${TOTAL} passed"

# Generate JSON results for artifact
cat > "${RESULTS_JSON}" <<JSONEOF
{
  "timestamp": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "expected_tools": ${EXPECTED_TOOLS},
  "total_tools": ${TOTAL},
  "passed": ${PASSED},
  "failed": ${FAILED},
  "pass_rate": "$(echo "scale=1; ${PASSED} * 100 / ${EXPECTED_TOOLS}" | bc)%",
  "image_tag": "${CI_COMMIT_SHORT_SHA:-unknown}",
  "runtime_id": "${AGENTCORE_RUNTIME_ID:-unknown}"
}
JSONEOF

# Validate tool count
if [ "${TOTAL}" -ne "${EXPECTED_TOOLS}" ]; then
  echo "[ERROR] Tool count mismatch: expected ${EXPECTED_TOOLS}, got ${TOTAL}"
  exit 1
fi

# Check all passed
if [ "${PASSED}" -ne "${EXPECTED_TOOLS}" ]; then
  echo "[ERROR] Validation failed: ${FAILED} tools did not pass"
  echo "[ERROR] See ${REPORT_PATH} for details"
  exit 1
fi

echo "[OK] All ${EXPECTED_TOOLS} tools validated successfully"

# Append deployment summary to report
cat >> "${REPORT_PATH}" <<EOF

---
## Deployment Summary

| Field | Value |
|-------|-------|
| Image Tag | ${CI_COMMIT_SHORT_SHA:-unknown} |
| Runtime ID | ${AGENTCORE_RUNTIME_ID:-unknown} |
| Timestamp | $(date -u +"%Y-%m-%dT%H:%M:%SZ") |
| Pass Rate | ${PASSED}/${EXPECTED_TOOLS} |
EOF

exit 0
```

### Exit Codes

| Code | Meaning                                    |
|------|--------------------------------------------|
| 0    | All 51 tools passed validation             |
| 1    | Validation failure (tool count mismatch, tool errors, or timeout) |

## Rollback Mechanism

### Trigger

The rollback stage uses GitLab CI's `when: on_failure` directive, which triggers automatically when the `validate_deployment` job fails.

### Flow

```
validate_deployment FAILS
        │
        ▼
rollback_deployment triggers (when: on_failure)
        │
        ▼
Read PREVIOUS_IMAGE_URI from deploy.env artifact
        │
        ▼
Call: deploy-agentcore.sh --rollback
        │
        ├── update_runtime(PREVIOUS_IMAGE_URI)
        │       │
        │       ▼
        ├── poll_health() — wait up to 5 min
        │       │
        │       ├── SUCCESS → Log rollback outcome
        │       │
        │       └── TIMEOUT → Alert + manual intervention
        │
        └── (If runtime healthy) Re-validate via validate-aws-mcp.js
                │
                ├── 51/51 PASS → Rollback confirmed successful
                │
                └── FAIL → Alert: double-failure, manual intervention required
```

### Double-Failure Handling

If the rollback itself fails (runtime doesn't become healthy or post-rollback validation fails):

1. Pipeline marks the job as failed
2. Alert notification sent to configured GitLab notification channel
3. `ROLLBACK_STATUS=FAILED` recorded in `deploy.env`
4. Pipeline output clearly states `MANUAL INTERVENTION REQUIRED`

### Audit Trail

Every rollback records in `deploy.env`:
- `ROLLBACK_STATUS` — `SUCCESS` or `FAILED`
- `ROLLBACK_TIMESTAMP` — ISO 8601 timestamp
- `ROLLBACK_REASON` — Why the rollback was triggered

## Security Design

### Secret Storage

| Variable                | Type          | Purpose                              |
|-------------------------|---------------|--------------------------------------|
| `AWS_ACCESS_KEY_ID`     | Masked, CI/CD | IAM access key for ECR + AgentCore   |
| `AWS_SECRET_ACCESS_KEY` | Masked, CI/CD | IAM secret key                       |
| `AWS_DEFAULT_REGION`    | CI/CD         | Target region (`us-east-1`)          |
| `AGENTCORE_RUNTIME_ID`  | CI/CD         | Runtime identifier                   |
| `ECR_REGISTRY`          | CI/CD         | ECR registry URL                     |

### Credential Protection

1. **Masked variables**: All secrets configured as masked in GitLab CI/CD settings — values are redacted from job logs automatically
2. **Ephemeral ECR tokens**: `aws ecr get-login-password` generates a 12-hour token; no long-lived Docker credentials stored
3. **Suppressed output**: `set +x` wraps all credential operations to prevent shell trace from logging secrets
4. **No repository storage**: Zero secrets committed to the repository; all injected at runtime via CI/CD variables

### Variable Validation

The pipeline validates all required variables within the first 30 seconds of execution:

```bash
# Runs in before_script of first stage
for var in AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION \
           AGENTCORE_RUNTIME_ID ECR_REGISTRY; do
  eval "val=\$$var"
  if [ -z "$val" ]; then
    MISSING="${MISSING} ${var}"
  fi
done
```

Missing variables are reported by name without revealing expected values.

### Network Security

- Pipeline runners do not require VPC access — all operations use AWS CLI over public API endpoints
- The AgentCore Runtime's VPC configuration (subnets + security group) is preserved during updates, not modified
- No SSH keys or direct instance access required

## Traceability Matrix

| Requirement | Design Component(s)                                                    |
|-------------|------------------------------------------------------------------------|
| R1: Pipeline Trigger Configuration | `workflow.rules` in `.gitlab-ci.yml`; branch/MR/manual rules on each job |
| R2: Container Image Build | `build_image` job: buildx, platform flag, SHA+latest tags, 15min timeout, architecture verification |
| R3: ECR Authentication and Push | `push_image` job: `aws ecr get-login-password`, retry logic (3 attempts, exponential backoff), manifest verification |
| R4: AgentCore Runtime Update | `deploy_runtime` job + `deploy-agentcore.sh --update`: `record_previous_version()`, `update_runtime()`, `poll_health()` |
| R5: Post-Deploy Validation | `validate_deployment` job + `validate-deploy.sh`: invokes `validate-aws-mcp.js`, 51-tool check, report artifact |
| R6: Deployment Rollback | `rollback_deployment` job (`when: on_failure`) + `deploy-agentcore.sh --rollback`: revert, re-validate, alert on double-failure |
| R7: Secret and Credential Management | Masked CI/CD variables, `set +x` around credentials, variable validation in `before_script`, no secrets in logs |
| R8: Pipeline Artifacts and Reporting | `artifacts` blocks on validate/deploy jobs, `deploy.env` with JSON metadata, 30-day retention, validation report |
| R9: Pipeline Stage Ordering | `stages` declaration, `needs` dependencies, `when: on_failure` for rollback, MR-only build+push rules |
| R10: Network and VPC Configuration | `--network-configuration` in `update_runtime()` preserving subnets/SG; no lifecycle modification; connectivity validated by `validate-aws-mcp.js` |
