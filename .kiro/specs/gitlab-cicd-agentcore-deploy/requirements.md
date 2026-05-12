# Requirements Document

## Introduction

This document specifies the requirements for a GitLab CI/CD pipeline that automates the deployment of the MDC MCP RAG Server to AWS Bedrock AgentCore Runtime. The pipeline replaces the current manual deployment process (docker build → ECR push → update-agent-runtime) with a repeatable, validated, and safe automated workflow triggered from the `develop_aws` branch.

## Glossary

- **Pipeline**: The GitLab CI/CD pipeline defined in `.gitlab-ci.yml` that orchestrates the build, push, deploy, and validate stages
- **MCP_Server**: The MDC MCP RAG Server, a Node.js application providing 51 MCP tools for code analysis, semantic search, and workflow operations
- **ECR_Registry**: The AWS Elastic Container Registry at `903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag` storing container images
- **AgentCore_Runtime**: The AWS Bedrock AgentCore Runtime identified by `mdc_mcp_rag_server-TMXDllG2Wi` in `us-east-1` that hosts the MCP_Server
- **Validation_Script**: The `mcp_server_node/scripts/validate-aws-mcp.js` script that invokes all 51 MCP tools and produces a pass/fail report
- **Parity_Test**: The `tools/mcp-parity-test.py` script that compares tool responses between legacy and AgentCore servers
- **Container_Image**: The ARM64 Docker image built from `mcp_server_node/Dockerfile.agentcore`
- **Deploy_Stage**: The pipeline stage that updates the AgentCore_Runtime to use a newly pushed Container_Image
- **Rollback**: The process of reverting the AgentCore_Runtime to the previous known-good Container_Image version

## Requirements

### Requirement 1: Pipeline Trigger Configuration

**User Story:** As a developer, I want the pipeline to trigger automatically on pushes to `develop_aws`, so that deployments happen without manual intervention after code review.

#### Acceptance Criteria

1. WHEN a commit is pushed to the `develop_aws` branch, THE Pipeline SHALL trigger the full stage sequence (build → push → deploy → validate) automatically
2. WHEN a merge request targets the `develop_aws` branch, THE Pipeline SHALL run only the build and push stages without executing the deploy or validate stages
3. WHEN a commit is pushed to a branch other than `develop_aws`, THE Pipeline SHALL not trigger
4. WHEN a tag is pushed, THE Pipeline SHALL not trigger
5. WHERE manual deployment is needed, THE Pipeline SHALL provide a manual trigger option that executes the deploy and validate stages using the most recently pushed Container_Image

### Requirement 2: Container Image Build

**User Story:** As a developer, I want the pipeline to build the ARM64 container image, so that the correct architecture is produced for AgentCore Runtime.

#### Acceptance Criteria

1. THE Pipeline SHALL build the Container_Image using `mcp_server_node/Dockerfile.agentcore` with the `linux/arm64` platform target and `mcp_server_node/` as the build context directory
2. THE Pipeline SHALL tag the Container_Image with both the short Git commit SHA (first 7 characters) and `latest`
3. THE Pipeline SHALL complete the image build within 15 minutes
4. IF the Container_Image build fails, THEN THE Pipeline SHALL halt execution and report the failure with the last 50 lines of build output
5. THE Pipeline SHALL cache Docker layer builds between pipeline runs to reduce build time
6. WHEN the Container_Image build completes, THE Pipeline SHALL verify the built image reports `linux/arm64` as its platform architecture

### Requirement 3: ECR Authentication and Push

**User Story:** As a developer, I want the pipeline to authenticate with ECR and push the image, so that the container is available for AgentCore deployment.

#### Acceptance Criteria

1. THE Pipeline SHALL authenticate with ECR_Registry using IAM credentials stored in GitLab CI/CD variables
2. WHEN authentication succeeds, THE Pipeline SHALL push the Container_Image to `903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag` and complete the push within 10 minutes per image tag
3. IF ECR authentication fails, THEN THE Pipeline SHALL halt execution and report the credential error without exposing secrets in logs
4. THE Pipeline SHALL push both the SHA-tagged and `latest`-tagged versions of the Container_Image
5. IF the ECR push fails, THEN THE Pipeline SHALL retry with exponential backoff starting at 5 seconds, and IF the push fails after 3 retry attempts, THEN THE Pipeline SHALL halt execution and report the failure including the image tag, attempt count, and error details
6. WHEN both image tags are pushed successfully, THE Pipeline SHALL verify the pushed image exists in ECR_Registry by confirming the image manifest is retrievable for each tag before proceeding to the deploy stage

### Requirement 4: AgentCore Runtime Update

**User Story:** As a developer, I want the pipeline to update the AgentCore Runtime with the new image, so that the deployed MCP server reflects the latest code.

#### Acceptance Criteria

1. WHEN the Container_Image is successfully pushed to ECR_Registry, THE Pipeline SHALL update the AgentCore_Runtime using the `update-agent-runtime` CLI command with the SHA-tagged image URI from the push stage
2. THE Pipeline SHALL reference the AgentCore_Runtime by its ID `mdc_mcp_rag_server-TMXDllG2Wi` in region `us-east-1`
3. WHEN the AgentCore_Runtime update is initiated, THE Pipeline SHALL poll the runtime status at intervals of no more than 30 seconds until the runtime reports an active status with a running container, before proceeding to validation
4. IF the AgentCore_Runtime does not reach an active status with a running container within 5 minutes, THEN THE Pipeline SHALL mark the pipeline stage as failed and include the last observed runtime status in the stage output
5. THE Pipeline SHALL record the previous runtime Container_Image URI before initiating the update, storing it as a pipeline variable accessible to the rollback stage
6. IF the `update-agent-runtime` CLI command returns a non-zero exit code, THEN THE Pipeline SHALL halt execution and report the command error output without proceeding to health polling

### Requirement 5: Post-Deploy Validation

**User Story:** As a developer, I want the pipeline to validate all 51 MCP tools after deployment, so that I have confidence the deploy did not break functionality.

#### Acceptance Criteria

1. WHEN the AgentCore_Runtime reaches a healthy state after update, THE Pipeline SHALL execute the Validation_Script against the deployed runtime
2. THE Validation_Script SHALL invoke all 51 registered MCP tools with a per-tool timeout of 30 seconds and verify each returns a non-empty response (response body length greater than 0 characters)
3. IF the deployed runtime exposes fewer or more than 51 registered tools, THEN THE Pipeline SHALL mark the deployment as failed and report the expected versus actual tool count
4. IF any single MCP tool fails validation (returns an empty response, times out, or throws an invocation error), THEN THE Pipeline SHALL mark the deployment as failed and include the tool name, module, and error details in the report
5. THE Pipeline SHALL produce a validation report artifact at `docs/aws-mcp-validation-report.md` containing per-tool pass/fail status, response duration, and an overall pass rate
6. THE Pipeline SHALL complete the full validation of all 51 tools within 10 minutes

### Requirement 6: Deployment Rollback

**User Story:** As a developer, I want the pipeline to automatically rollback on validation failure, so that a broken deploy does not leave the 51 tools unavailable.

#### Acceptance Criteria

1. IF the post-deploy validation fails, THEN THE Pipeline SHALL revert the AgentCore_Runtime to the previous Container_Image version using the `update-agent-runtime` CLI command within 5 minutes of initiating the rollback
2. WHEN a rollback is triggered, THE Pipeline SHALL use the previously recorded runtime version to restore the AgentCore_Runtime to a healthy state, waiting no longer than 5 minutes for the runtime to become healthy
3. WHEN a rollback completes, THE Pipeline SHALL re-run the Validation_Script to confirm all 51 MCP tools return non-empty, non-error responses within the 10-minute validation timeout
4. IF the rollback itself fails, THEN THE Pipeline SHALL send an alert notification to the pipeline's configured notification channel and mark the pipeline as requiring manual intervention
5. THE Pipeline SHALL log the rollback reason, timestamp, and outcome (success or failure) for audit purposes
6. IF the AgentCore_Runtime does not reach a healthy state within 5 minutes after the rollback update, THEN THE Pipeline SHALL treat the rollback as failed
7. IF the post-rollback validation fails, THEN THE Pipeline SHALL send an alert notification to the pipeline's configured notification channel and mark the pipeline as requiring manual intervention

### Requirement 7: Secret and Credential Management

**User Story:** As a developer, I want credentials managed securely through GitLab CI/CD variables, so that AWS access keys and sensitive configuration are not exposed in the repository.

#### Acceptance Criteria

1. THE Pipeline SHALL retrieve AWS credentials exclusively from GitLab CI/CD masked variables
2. THE Pipeline SHALL not write AWS credentials, ECR tokens, or AgentCore identifiers to pipeline logs
3. THE Pipeline SHALL use the following GitLab CI/CD variables: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`
4. IF any required CI/CD variable is missing or empty, THEN THE Pipeline SHALL fail within the first 30 seconds of execution with an error message identifying each missing or empty variable by name, without revealing the expected values

### Requirement 8: Pipeline Artifacts and Reporting

**User Story:** As a developer, I want the pipeline to produce deployment artifacts and reports, so that I can audit deployments and diagnose failures.

#### Acceptance Criteria

1. THE Pipeline SHALL produce the validation report as a downloadable artifact retained for 30 days
2. THE Pipeline SHALL log the deployed image tag, runtime version, and deployment timestamp as a JSON object with keys `image_tag`, `runtime_version`, and `timestamp` (ISO 8601 format)
3. WHEN the pipeline completes successfully, THE Pipeline SHALL output a deployment summary including image SHA, runtime version, and validation pass rate (number of tools passed out of 51)
4. WHEN the pipeline fails, THE Pipeline SHALL output a failure summary identifying the failed stage name, the step within that stage that failed, and the error message returned by the failed command
5. THE Pipeline SHALL store pipeline logs as artifacts retained for 7 days

### Requirement 9: Pipeline Stage Ordering and Dependencies

**User Story:** As a developer, I want the pipeline stages to execute in the correct order with proper dependencies, so that each stage has the prerequisites it needs.

#### Acceptance Criteria

1. THE Pipeline SHALL execute stages in the order: build → push → deploy → validate
2. WHEN a stage fails, THE Pipeline SHALL not execute subsequent stages except for the rollback stage
3. IF the validate stage fails after a successful deploy stage, THEN THE Pipeline SHALL run the rollback stage
4. THE Pipeline SHALL support running the build and push stages independently via manual trigger from any branch without executing the deploy or validate stages

### Requirement 10: Network and VPC Configuration

**User Story:** As a developer, I want the deployment to preserve the VPC network configuration, so that the MCP server maintains connectivity to Neptune and OpenSearch.

#### Acceptance Criteria

1. THE Pipeline SHALL preserve the existing VPC network configuration when updating the AgentCore_Runtime, including subnets `subnet-0e13af6b3a9a6416f`, `subnet-024fd9b597b3075a5`, `subnet-04447750c61bd7e06` and security group `sg-096489a0876cc78c1`
2. THE Pipeline SHALL not modify the AgentCore_Runtime lifecycle configuration (idle timeout 900s, max lifetime 28800s)
3. IF the deployed MCP_Server cannot establish a connection to Neptune or OpenSearch endpoints within 30 seconds, THEN THE Validation_Script SHALL report the connectivity failure as a validation error identifying the unreachable endpoint
