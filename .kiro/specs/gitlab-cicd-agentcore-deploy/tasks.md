# Implementation Tasks

## Task Dependency Graph

```
Task 1 (deploy-agentcore.sh) ──┐
                                ├──▶ Task 3 (.gitlab-ci.yml) ──▶ Task 5 (Test locally) ──▶ Task 6 (Deploy & validate)
Task 2 (validate-deploy.sh) ───┘                                        ▲
                                                                        │
Task 4 (CI/CD variables) ──────────────────────────────────────────────┘

Task 7 (Property-based tests) ── parallel with Tasks 5–6
```

- Tasks 1 and 2 are independent and can be implemented in parallel
- Task 3 depends on Tasks 1 and 2 (pipeline references both scripts)
- Task 4 is independent (GitLab settings configuration)
- Task 5 depends on Task 3 (validates the pipeline YAML and scripts)
- Task 6 depends on Tasks 4 and 5 (needs variables configured and pipeline validated)
- Task 7 can run in parallel with Tasks 5–6

## Tasks

### Task 1: Create deployment helper script (`scripts/ci/deploy-agentcore.sh`)

Implements the AgentCore Runtime update lifecycle: record previous version, update, poll health, and rollback. [R4, R6, R10]

- [ ] 1.1 Create `scripts/ci/deploy-agentcore.sh` with shebang, `set -euo pipefail`, and environment variable defaults (`RUNTIME_ID`, `REGION`, `POLL_INTERVAL`, `POLL_TIMEOUT`, `DEPLOY_ENV`)
- [ ] 1.2 Implement `record_previous_version()` function that queries `aws bedrock-agentcore-control list-agent-runtimes` to capture the current container image URI and writes `PREVIOUS_IMAGE_URI` to `deploy.env` [R4.5]
- [ ] 1.3 Implement `update_runtime()` function that calls `aws bedrock-agentcore-control update-agent-runtime` with the new image URI, preserving VPC network configuration (3 subnets + security group), and appends `DEPLOYED_IMAGE_URI`, `DEPLOY_TIMESTAMP`, and `IMAGE_TAG` to `deploy.env` [R4.1, R4.2, R4.6, R10.1, R10.2]
- [ ] 1.4 Implement `poll_health()` function that polls runtime status every `POLL_INTERVAL` seconds (default 30s) until ACTIVE/READY or `POLL_TIMEOUT` (default 300s), returning 0 on healthy and 1 on timeout [R4.3, R4.4]
- [ ] 1.5 Implement `rollback()` function that reads `PREVIOUS_IMAGE_URI` from `deploy.env`, calls `update_runtime()` with it, polls health, and records `ROLLBACK_STATUS`, `ROLLBACK_TIMESTAMP`, and `ROLLBACK_REASON` in `deploy.env`; alerts on failure [R6.1, R6.2, R6.4, R6.5, R6.6]
- [ ] 1.6 Implement `main()` dispatcher that parses `--update <IMAGE_URI>` and `--rollback` arguments, validates inputs, and calls the appropriate function sequence

### Task 2: Create validation wrapper script (`scripts/ci/validate-deploy.sh`)

Wraps the existing `validate-aws-mcp.js` script, captures results, generates the markdown report artifact, and returns appropriate exit codes. [R5, R8]

- [ ] 2.1 Create `scripts/ci/validate-deploy.sh` with shebang, `set -euo pipefail`, and configuration variables (`VALIDATION_SCRIPT`, `REPORT_PATH`, `RESULTS_JSON`, `EXPECTED_TOOLS=51`, `TIMEOUT`)
- [ ] 2.2 Implement validation execution: run `node validate-aws-mcp.js --timeout 30000` with a `timeout` wrapper of `VALIDATION_TIMEOUT` seconds, capturing output to `validation-output.log` [R5.1, R5.2, R5.6]
- [ ] 2.3 Implement result parsing: extract pass/fail counts from the generated report using grep, validate total tool count equals 51, and fail with descriptive error if count mismatches [R5.3, R5.4]
- [ ] 2.4 Implement JSON results generation: write `validation-results.json` with `timestamp`, `expected_tools`, `total_tools`, `passed`, `failed`, `pass_rate`, `image_tag`, and `runtime_id` fields [R8.2]
- [ ] 2.5 Implement deployment summary: append a summary table to the markdown report with image tag, runtime ID, timestamp, and pass rate [R8.3]
- [ ] 2.6 Implement exit code logic: return 0 when all 51 tools pass, return 1 on any failure (count mismatch, tool errors, timeout) [R5.3, R5.4]

### Task 3: Create `.gitlab-ci.yml` pipeline definition

Defines the five-stage pipeline with workflow rules, variable validation, and all job configurations. [R1, R2, R3, R4, R5, R6, R7, R8, R9]

- [ ] 3.1 Create `.gitlab-ci.yml` with `stages` declaration (build, push, deploy, validate, rollback), pipeline-level `variables` block, and `workflow.rules` for `develop_aws` branch, merge requests, and manual triggers [R1, R9.1]
- [ ] 3.2 Implement the `build_image` job: Docker-in-Docker service, buildx setup for ARM64, SHA+latest tagging, registry cache, architecture verification, and 15-minute timeout [R2.1–R2.6]
- [ ] 3.3 Implement the `push_image` job: ECR authentication with `set +x` credential suppression, push with 3-attempt exponential backoff retry, manifest verification for both tags, and 10-minute timeout [R3.1–R3.6, R7.2]
- [ ] 3.4 Implement the `deploy_runtime` job: invokes `scripts/ci/deploy-agentcore.sh --update`, produces `deploy.env` dotenv artifact, restricted to `develop_aws` push and manual web triggers [R4, R9.4]
- [ ] 3.5 Implement the `validate_deployment` job: installs Node.js dependencies, invokes `scripts/ci/validate-deploy.sh`, produces report and JSON artifacts with 30-day retention [R5, R8.1, R8.5]
- [ ] 3.6 Implement the `rollback_deployment` job: `when: on_failure`, depends on deploy artifacts and validate job, invokes `scripts/ci/deploy-agentcore.sh --rollback` [R6, R9.2, R9.3]

### Task 4: Configure GitLab CI/CD variables

Document and configure the required masked/protected CI/CD variables in the GitLab project settings. [R7]

- [ ] 4.1 Document the required CI/CD variables in a setup guide: `AWS_ACCESS_KEY_ID` (masked), `AWS_SECRET_ACCESS_KEY` (masked), `AWS_DEFAULT_REGION`, `AGENTCORE_RUNTIME_ID`, `ECR_REGISTRY` [R7.1, R7.3]
- [ ] 4.2 Configure `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` as masked and protected variables scoped to the `develop_aws` branch [R7.1, R7.2]
- [ ] 4.3 Configure `AWS_DEFAULT_REGION` (`us-east-1`), `AGENTCORE_RUNTIME_ID` (`mdc_mcp_rag_server-TMXDllG2Wi`), and `ECR_REGISTRY` (`903050880929.dkr.ecr.us-east-1.amazonaws.com`) as CI/CD variables [R7.3]
- [ ] 4.4 Implement the `.validate_variables` YAML anchor with the pre-flight check that fails within 30 seconds if any required variable is missing or empty, reporting variable names without values [R7.4]
- [ ] 4.5 Verify that masked variables are redacted in pipeline log output by running a test job that references them

### Task 5: Test pipeline locally (dry-run validation)

Validate the pipeline YAML syntax, script correctness, and stage dependencies before pushing to GitLab. [R9]

- [ ] 5.1 Run `gitlab-ci-lint` or equivalent YAML validation on `.gitlab-ci.yml` to verify syntax, stage references, and `needs` dependency graph are valid
- [ ] 5.2 Run `shellcheck` on `scripts/ci/deploy-agentcore.sh` and `scripts/ci/validate-deploy.sh` to catch shell scripting errors and unsafe patterns
- [ ] 5.3 Verify script executability: confirm both scripts have `chmod +x` permissions and run without errors when invoked with `--help` or invalid arguments (testing usage output)
- [ ] 5.4 Validate the `workflow.rules` logic: confirm pipeline triggers only for `develop_aws` pushes, `develop_aws`-targeted MRs, and manual web triggers; confirm no trigger for other branches or tags [R1.1–R1.5]
- [ ] 5.5 Verify artifact configuration: confirm `deploy.env` dotenv report, validation report path, and retention periods (30 days for reports, 7 days for logs) are correctly specified [R8.1, R8.5]

### Task 6: Deploy and validate (first real pipeline run)

Execute the pipeline end-to-end on the `develop_aws` branch and verify all stages complete successfully. [R1–R10]

- [ ] 6.1 Push the pipeline files to `develop_aws` and confirm the pipeline triggers automatically with all 5 stages visible [R1.1]
- [ ] 6.2 Verify the build stage completes: ARM64 image built within 15 minutes, architecture verified as `arm64`/`aarch64` [R2.3, R2.6]
- [ ] 6.3 Verify the push stage completes: ECR authentication succeeds, both SHA and `latest` tags pushed, manifests verified in ECR [R3.2, R3.4, R3.6]
- [ ] 6.4 Verify the deploy stage completes: previous version recorded in `deploy.env`, runtime updated, health poll succeeds within 5 minutes [R4.3, R4.5]
- [ ] 6.5 Verify the validate stage completes: all 51 tools pass validation, report artifact generated at `docs/aws-mcp-validation-report.md`, JSON results artifact produced [R5.1–R5.5, R8.1]
- [ ] 6.6 Verify rollback behavior: intentionally trigger a validation failure (e.g., temporarily break a tool) and confirm the rollback stage activates, reverts the image, and re-validates [R6.1–R6.3]

### Task 7: Property-based tests for pipeline scripts

Write correctness property tests for the deployment and validation scripts to verify invariants hold across a range of inputs. [R4, R6, R7]

- [ ] 7.1 Write a property test for idempotent rollback: verify that calling `rollback()` multiple times with the same `deploy.env` always produces the same `update_runtime()` call with `PREVIOUS_IMAGE_URI`, regardless of intermediate state [R6.1, R6.2]
- [ ] 7.2 Write a property test for variable validation: generate random subsets of required variables (some present, some missing/empty) and verify the validation logic correctly identifies all missing variables by name without false positives or negatives [R7.4]
- [ ] 7.3 Write a property test for retry behavior: verify that `push_with_retry()` always attempts exactly 3 times on persistent failure, with exponential backoff delays of 5s, 10s, 20s, and returns non-zero exit code after exhausting retries [R3.5]
- [ ] 7.4 Write a property test for poll_health timing: verify that `poll_health()` never exceeds `POLL_TIMEOUT` seconds of wall-clock time regardless of the status values returned, and always makes at least `floor(POLL_TIMEOUT / POLL_INTERVAL)` status checks before timing out [R4.3, R4.4]
- [ ] 7.5 Write a property test for image tag format: verify that the pipeline always produces image URIs matching the pattern `<ECR_REGISTRY>/<ECR_REPOSITORY>:<7-char-hex-sha>` for SHA tags and `<ECR_REGISTRY>/<ECR_REPOSITORY>:latest` for latest tags, for any valid Git commit SHA input [R2.2]
