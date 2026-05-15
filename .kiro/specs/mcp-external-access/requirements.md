# Requirements Document

## Introduction

Expose the MDC MCP RAG Server — currently deployed to AWS Bedrock AgentCore Runtime
(`mdc_mcp_rag_server-TMXDllG2Wi`) and reachable only via IAM SigV4 `invoke_agent_runtime`
from the EC2 developer workstation — to two new external consumer classes:

1. **GitHub Actions CI/CD pipelines**, for automated EE2 root-cause analysis on failed
   builds and future CI-driven MCP consumption patterns.
2. **HPC user sessions** on Hera, Orion, Hercules, Gaea, and Ursa, where
   meteorologists develop forecasting software outside AWS and need MCP access without
   long-lived tokens on shared filesystems.

This spec delivers **Path B** from
`docs/reports/2026-05-07-kiro-agentcore-native-connection-options.md`: Cognito inbound
OAuth/JWT authorization configured directly on the AgentCore Runtime. Consumers connect
via the MCP Streamable HTTP endpoint using a short-lived JWT Bearer token. The existing
developer SigV4 proxy path (`tools/agentcore-kiro-proxy.py`) is preserved unchanged.

A later phase (Path C) will introduce AgentCore Gateway in front of the Runtime for
tool-level Cedar policy authorization, cross-account resource policies, interceptor-based
audit enrichment, and a stable URL decoupled from Runtime redeploys. Path C is
out of scope for this spec's detailed acceptance criteria and is captured only as a
forward reference in Requirement 11.

## Glossary

- **MCP_Server**: The MDC MCP RAG Server — a Node.js application exposing 51 tools across 9 modules over the Model Context Protocol.
- **AgentCore_Runtime**: The AWS Bedrock AgentCore serverless runtime hosting the MCP_Server at runtime ARN `arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/mdc_mcp_rag_server-TMXDllG2Wi`.
- **MCP_Endpoint**: The public MCP Streamable HTTP URL of the AgentCore_Runtime at `https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/{encoded-arn}/invocations?qualifier=DEFAULT`.
- **Cognito_User_Pool**: The Amazon Cognito user pool that issues JWT access tokens accepted by the AgentCore_Runtime authorizer.
- **CI_App_Client**: The Cognito app client configured for OAuth 2.0 client-credentials grant, used by GitHub_Actions_Runners.
- **HPC_App_Client**: The Cognito app client configured for user-flow authentication, used by HPC_Users.
- **JWT_Authorizer**: The AgentCore_Runtime inbound authorizer configuration that validates JWT access tokens against the Cognito_User_Pool discovery URL, audience, and allowed scopes.
- **Token_Broker**: An AWS Lambda function, invoked by GitHub_Actions_Runners via an IAM role assumed through GitHub OIDC federation, that exchanges federated identity for a Cognito JWT access token.
- **HPC_CLI_Helper**: A small command-line utility, distributed with the project, that HPC_Users run on their HPC login node or workstation to obtain a short-lived Cognito JWT access token and print the `Authorization: Bearer` value.
- **CI_Principal**: A caller identified by a Cognito JWT whose `scope` claim includes `mcp/ci-readonly`. Typically a GitHub_Actions_Runner.
- **HPC_Principal**: A caller identified by a Cognito JWT whose `scope` claim includes `mcp/hpc-user` and whose `sub` identifies an HPC_User.
- **Developer_Principal**: The existing AWS-native developer path — the EC2 workstation's IAM role used by `tools/agentcore-kiro-proxy.py` via `invoke_agent_runtime` SigV4. Not a JWT caller.
- **GitHub_Actions_Runner**: A GitHub-hosted or self-hosted runner executing a workflow in the project's GitHub repository.
- **HPC_User**: A meteorologist with an account on an HPC system (Hera, Orion, Hercules, Gaea, or Ursa) that is not an AWS network.
- **Allowed_Tool_Set**: The subset of the 51 MCP_Server tools callable by a given principal class, defined by scope claim.
- **Mutation_Tool_Set**: The subset of tools that modify server-side state — `mark_as_modified`, `checkpoint_state`, `restore_checkpoint`, `start_sdd_session`, `record_sdd_step`, `complete_sdd_session`, and `mcp_create_profile`.
- **Audit_Log**: A structured CloudWatch Logs stream entry written by the MCP_Server for every tool invocation, containing caller identity, tool name, timestamp, and request ID.
- **Runbook**: A markdown document in `docs/runbooks/` that walks a consumer through the steps to onboard and use the MCP_Endpoint.
- **CDK**: AWS Cloud Development Kit stacks under `infrastructure/cdk/`.

## Requirements

### Requirement 1: Cognito User Pool and App Clients

**User Story:** As a platform operator, I want a Cognito_User_Pool with distinct app clients for CI and HPC consumers, so that tokens issued to each class carry class-specific scope claims and can be governed independently.

#### Acceptance Criteria

1. THE CDK SHALL define exactly one Cognito_User_Pool in a new CDK stack located under `infrastructure/cdk/`.
2. THE Cognito_User_Pool SHALL be configured with `removalPolicy: RETAIN` per `.kiro/steering/05-cdk-data-safety.md` such that a `cdk destroy` of the stack does not delete the Cognito_User_Pool or its users.
3. THE CDK SHALL register a Cognito resource server on the Cognito_User_Pool that declares the two custom scopes `mcp/ci-readonly` and `mcp/hpc-user`, and THE two scopes SHALL be the only custom scopes defined on that resource server.
4. THE CDK SHALL define a CI_App_Client on the Cognito_User_Pool with the OAuth 2.0 client-credentials grant enabled, with `mcp/ci-readonly` as its only allowed OAuth scope, with a generated client secret, and with all other OAuth grants (authorization-code, implicit, and user-password) disabled.
5. THE CDK SHALL define an HPC_App_Client on the Cognito_User_Pool with exactly one of the OAuth 2.0 authorization-code grant or the user-password (ROPC) grant enabled, with `mcp/hpc-user` as its only allowed OAuth scope, and with the client-credentials grant disabled.
6. THE Cognito_User_Pool SHALL publish an OIDC discovery document at its issuer URL, reachable at the path `/.well-known/openid-configuration`, and the document SHALL include the `issuer`, `jwks_uri`, `token_endpoint`, and `scopes_supported` fields with `scopes_supported` containing both `mcp/ci-readonly` and `mcp/hpc-user`.
7. THE Cognito_User_Pool SHALL issue access tokens whose lifetime is at least 300 seconds and at most 3600 seconds, with the same configured lifetime applied to both the CI_App_Client and the HPC_App_Client.
8. WHEN an access token is issued by the Cognito_User_Pool, THE Cognito_User_Pool SHALL include in the token payload a `sub` claim identifying the caller, a `scope` claim whose space-separated values equal exactly the scopes granted for that request, an `iss` claim equal to the Cognito_User_Pool issuer URL, a `client_id` claim identifying the requesting app client, and an `exp` claim whose value equals the issuance time plus the configured token lifetime.
9. IF a token request specifies a scope value that is not in the allowed-scopes list of the requesting app client, THEN THE Cognito_User_Pool SHALL reject the request with an OAuth 2.0 `invalid_scope` error and SHALL NOT issue an access token for that request.
10. IF a token request presents a `client_id` that does not exist on the Cognito_User_Pool or a `client_secret` that does not match the stored secret for the given `client_id`, THEN THE Cognito_User_Pool SHALL reject the request with an OAuth 2.0 `invalid_client` error and SHALL NOT issue an access token for that request.

### Requirement 2: AgentCore Runtime JWT Authorizer

**User Story:** As a platform operator, I want the AgentCore_Runtime's inbound authorizer configured to validate Cognito-issued JWTs, so that the MCP_Endpoint accepts Bearer-token requests from external callers while preserving the existing SigV4 path for the Developer_Principal.

#### Acceptance Criteria

1. THE AgentCore_Runtime `authorizer_configuration` SHALL reference the Cognito_User_Pool discovery URL, a non-empty list of allowed audiences (`aud` or `client_id` values), and a non-empty list of allowed scopes.
2. WHEN a request arrives at the MCP_Endpoint with an `Authorization: Bearer <jwt>` header, THE JWT_Authorizer SHALL validate the token's signature against the Cognito_User_Pool JWKS using the key identified by the JWT header `kid`, and THE signature algorithm used SHALL match the algorithm published for that key in the JWKS.
3. WHEN a JWT is presented, THE JWT_Authorizer SHALL verify that the `iss` claim equals the configured Cognito issuer URL, the `aud` or `client_id` claim equals one of the configured allowed audiences, and the `scope` claim contains at least one of the configured allowed scopes.
4. WHEN a JWT is presented, THE JWT_Authorizer SHALL verify that the current time is not after `exp` and not before `nbf` (when present), applying a clock skew tolerance of at most 60 seconds.
5. IF a request arrives with no `Authorization` header, with an `Authorization` header whose scheme is not `Bearer`, or with a Bearer value that cannot be parsed as a JWT, THEN THE JWT_Authorizer SHALL reject the request with HTTP 401 and SHALL NOT forward the request to the MCP_Server.
6. IF a JWT fails any validation check in criteria 2, 3, or 4, THEN THE JWT_Authorizer SHALL reject the request with HTTP 401, SHALL NOT forward the request to the MCP_Server, and SHALL NOT return any claim values or tool metadata in the error response body.
7. IF the Cognito_User_Pool JWKS is unreachable or does not contain a key matching the JWT header `kid`, THEN THE JWT_Authorizer SHALL reject the request with HTTP 401 or HTTP 503 and SHALL NOT forward the request to the MCP_Server.
8. THE AgentCore_Runtime authorizer configuration SHALL be defined in CDK and applied via `cdk deploy`, and IF the authorizer configuration is detected as modified outside CDK, THEN the next `cdk deploy` SHALL overwrite the out-of-band change to match the CDK-defined state.
9. THE AgentCore_Runtime SHALL continue to accept IAM SigV4 `invoke_agent_runtime` calls from the Developer_Principal after the JWT_Authorizer is enabled.
10. WHEN a request that has passed authentication (either SigV4 or JWT) is forwarded to the MCP_Server, THE AgentCore_Runtime SHALL deliver an MCP payload of identical structure to the MCP_Server regardless of which authentication path was used, so that the MCP_Server requires no changes to accept either path.

### Requirement 3: GitHub Actions Consumer Flow

**User Story:** As a CI pipeline author, I want my GitHub Actions workflow to obtain a short-lived Cognito JWT without any long-lived secret in the repository, so that my failed-build analysis job can call the MCP_Endpoint securely and have every invocation attributable to the specific workflow run.

#### Acceptance Criteria

1. THE CDK SHALL define an IAM role with a trust policy that federates GitHub OIDC (`token.actions.githubusercontent.com`) and restricts the `sub` claim to a CDK-configured allowlist of one or more GitHub repository-and-ref patterns, such that AWS STS rejects any `AssumeRoleWithWebIdentity` request whose `sub` does not exactly match at least one entry in the allowlist.
2. THE CDK SHALL define a Token_Broker Lambda function whose resource policy and IAM permissions permit invocation only by principals that have assumed the federated IAM role defined in criterion 1.
3. WHEN the Token_Broker is invoked by a principal that has assumed the federated IAM role, THE Token_Broker SHALL exchange the caller's federated identity for a Cognito access token from the CI_App_Client with scope `mcp/ci-readonly` and SHALL return that access token to the caller within 5 seconds measured end-to-end from invocation to response.
4. WHEN a GitHub_Actions_Runner executes the published workflow snippet, THE GitHub_Actions_Runner SHALL assume the federated IAM role via OIDC using the runner's ephemeral GitHub OIDC token and SHALL invoke the Token_Broker without reading any long-lived AWS access key, AWS secret access key, or Cognito client secret from the repository, GitHub Actions secrets store, or runner environment variables.
5. WHEN the Token_Broker returns a JWT to the workflow snippet, THE workflow snippet SHALL set that JWT as the `Authorization: Bearer` header on every subsequent MCP_Endpoint call made within the same workflow run until the JWT expires.
6. THE JWT issued to a GitHub_Actions_Runner SHALL carry a claim identifying the GitHub workflow run that includes, at minimum, the `run_id`, `repository`, and `ref` values taken from the GitHub OIDC token, either passed through directly or populated by the Token_Broker.
7. THE JWT issued to a GitHub_Actions_Runner SHALL have a lifetime of at most 3600 seconds from the time of issuance.
8. THE project SHALL publish, under `.github/workflows/` or `.github/actions/`, a reusable workflow snippet or composite action that implements the OIDC-to-JWT exchange and exposes the resulting Bearer token to downstream workflow steps via a named output documented in the snippet's metadata.
9. IF the Token_Broker receives an invocation whose federated IAM role `sub` does not match the CDK-configured allowlist of repository-and-ref patterns, THEN THE Token_Broker SHALL return an HTTP 403 response to the caller, SHALL NOT issue a JWT, and SHALL NOT call Cognito.
10. IF the Token_Broker is authorized but cannot obtain a Cognito access token because Cognito is unreachable or rejects the request, THEN THE Token_Broker SHALL return a non-2xx HTTP response to the caller indicating an upstream token-issuance failure and SHALL NOT return a JWT.

### Requirement 4: HPC Consumer Flow

**User Story:** As an HPC-based meteorologist, I want a documented, scriptable way to obtain a short-lived Bearer token on my HPC login node or workstation and use it for the rest of my development session, so that I can query the MCP_Endpoint without running the MCP_Server locally and without storing long-lived secrets on the HPC shared filesystem.

#### Acceptance Criteria

1. THE project SHALL provide an HPC_CLI_Helper, distributed under `tools/` or `scripts/`, that an HPC_User runs to obtain a Cognito access token from the HPC_App_Client.
2. THE HPC_CLI_Helper SHALL support at least one authentication flow that does not require the HPC_User to have AWS credentials on the HPC system.
3. WHEN invoked successfully, THE HPC_CLI_Helper SHALL write the JWT access token to stdout as a single line containing only the raw token string terminated by one newline character, with no surrounding whitespace, quotes, prefixes, or labels, so that the output is directly assignable to an environment variable via shell command substitution.
4. WHEN the HPC_CLI_Helper writes the JWT to stdout, THE HPC_CLI_Helper SHALL exit with status code 0 and SHALL route all diagnostic, informational, and error output to stderr so that stdout contains only the token.
5. THE HPC_CLI_Helper SHALL NOT write the JWT to any file on disk by default.
6. WHERE the HPC_User explicitly passes a flag requesting token caching, THE HPC_CLI_Helper SHALL write the token to a single cache file whose permissions restrict read and write access to the invoking user only (mode `0600`), located in a directory owned by the invoking user, and SHALL overwrite any prior contents of that file atomically so that no partial token is observable to other processes.
7. WHERE the HPC_User explicitly passes a flag requesting token caching and a prior cache file exists, THE HPC_CLI_Helper SHALL verify that the existing file is a regular file owned by the invoking user with mode `0600` before writing, and IF that verification fails, THEN THE HPC_CLI_Helper SHALL exit with a non-zero status and print an error message to stderr identifying the offending path and the permission or ownership violation, without writing the token.
8. THE JWT issued to an HPC_User SHALL carry a `sub` claim identifying the HPC_User.
9. THE JWT issued to an HPC_User SHALL have a lifetime of at least 300 seconds and at most 3600 seconds from issuance, as indicated by the difference between its `exp` and `iat` claims.
10. IF the HPC_User attempts to use the HPC_CLI_Helper without valid authentication input, THEN THE HPC_CLI_Helper SHALL exit with a non-zero status, write nothing to stdout, and print an error message to stderr identifying each missing or invalid input by name.
11. IF the HPC_CLI_Helper cannot reach the Cognito token endpoint due to a network failure, DNS resolution failure, TLS handshake failure, or HTTP response indicating a non-success status, THEN THE HPC_CLI_Helper SHALL exit with a non-zero status, write nothing to stdout, and print an error message to stderr identifying the failure category and the endpoint that was contacted, without retrying more than 3 times and without exceeding a total wall-clock timeout of 30 seconds across all attempts.
12. IF token caching is requested and the HPC_CLI_Helper cannot create, open, or write the cache file due to a filesystem error such as permission denied, read-only filesystem, quota exceeded, or missing parent directory, THEN THE HPC_CLI_Helper SHALL exit with a non-zero status, write nothing to stdout, print an error message to stderr identifying the target path and the filesystem error category, and SHALL NOT leave a partially written cache file on disk.
13. THE HPC_CLI_Helper SHALL be runnable on Linux HPC login nodes (Hera, Orion, Hercules, Gaea, Ursa) with only dependencies available in a Python 3.9+ standard interpreter plus one pinned PyPI package set, installable to a user-local virtual environment.

### Requirement 5: Server-Side Tool Scoping Enforcement

**User Story:** As a platform operator, I want the MCP_Server to inspect the caller's JWT scope claims and restrict which tools each principal class can invoke, so that CI_Principals cannot execute state-mutating tools and the externally exposed surface area stays safe.

#### Acceptance Criteria

1. WHEN a tool invocation request arrives at the MCP_Server, THE MCP_Server SHALL read the validated JWT claims from the request context before evaluating tool authorization.
2. THE MCP_Server SHALL define an Allowed_Tool_Set for each of the scopes `mcp/ci-readonly`, `mcp/hpc-user`, and the Developer_Principal SigV4 path, with each Allowed_Tool_Set expressed as an explicit enumeration of individual tool names.
3. THE Allowed_Tool_Set for `mcp/ci-readonly` SHALL consist exclusively of read-only analysis tools drawn from the EE2 compliance, code analysis, semantic search, operational, and workflow information modules, where a read-only tool is defined as a tool that does not create, update, delete, submit, execute, or otherwise modify persistent state in any backend system.
4. THE Allowed_Tool_Set for `mcp/ci-readonly` SHALL NOT include any tool in the Mutation_Tool_Set, where the Mutation_Tool_Set is defined as the enumerated set of tools that create, update, delete, submit, or execute workflows, jobs, narratives, or other persistent artifacts in any backend system.
5. THE Allowed_Tool_Set for `mcp/hpc-user` SHALL include all tools in the `mcp/ci-readonly` Allowed_Tool_Set plus the GraphRAG and GitHub integration tools, enumerated individually.
6. THE Allowed_Tool_Set for the Developer_Principal SigV4 path SHALL consist of all 51 MCP_Server tools, enumerated individually.
7. WHEN a tool invocation arrives with a JWT whose scope claim does not include the required scope for the requested tool, THE MCP_Server SHALL return an MCP error response with HTTP status 403 and SHALL NOT execute the tool.
8. IF a tool invocation arrives with a JWT whose scope claim is present but the tool is absent from the corresponding Allowed_Tool_Set, THEN THE MCP_Server SHALL return an MCP error response with HTTP status 403 and a message identifying the tool as not permitted for the caller's scope, and SHALL NOT execute the tool.
9. IF a tool invocation arrives without a JWT, or with a JWT in which the scope claim is absent, null, or an empty value, THEN THE MCP_Server SHALL return an MCP error response with HTTP status 401 indicating missing authentication or missing scope, and SHALL NOT execute the tool.
10. IF a tool invocation arrives with a JWT whose scope claim contains only values that are not mapped to any Allowed_Tool_Set, THEN THE MCP_Server SHALL return an MCP error response with HTTP status 403 identifying the scope as unrecognized, and SHALL NOT execute the tool.
11. THE Allowed_Tool_Set mapping SHALL be defined in a single source file in the MCP_Server codebase and SHALL be the sole authority for scope-to-tool authorization, such that no other module, configuration file, environment variable, or runtime mechanism is permitted to add, remove, or override entries in any Allowed_Tool_Set.

### Requirement 6: Audit Logging

**User Story:** As a platform operator, I want every MCP_Endpoint invocation recorded with attributable caller identity, tool name, and request identifier, so that I can trace any action back to its originating principal during incident response.

#### Acceptance Criteria

1. WHEN the MCP_Server handles a tool invocation, THE MCP_Server SHALL write exactly one Audit_Log entry to CloudWatch Logs before returning the tool invocation response to the caller.
2. THE Audit_Log entry SHALL include a `caller_sub` field whose value equals the caller's `sub` claim when the caller is a CI_Principal or HPC_Principal, and whose value equals the literal string `developer-sigv4` when the caller is a Developer_Principal.
3. THE Audit_Log entry SHALL include the invoked tool name, a UTC ISO-8601 timestamp with millisecond precision, the `scope` claim value when the caller is a CI_Principal or HPC_Principal, the MCP request ID, and the outcome field whose value is exactly one of `success`, `authorization_denied`, or `execution_error`.
4. THE Audit_Log entry SHALL be serialized as a single UTF-8 JSON object on one line, terminated by a single `\n` character, with no embedded unescaped newlines (JSON Lines format).
5. THE Audit_Log entry SHALL NOT include the raw JWT, tool input arguments, or tool output payloads.
6. WHERE the caller is a CI_Principal and the JWT contains GitHub `run_id`, `repository`, and `ref` claims, THE Audit_Log entry SHALL include those three values in dedicated fields.
7. WHERE the caller is a CI_Principal and any of the GitHub `run_id`, `repository`, or `ref` claims is absent from the JWT, THE Audit_Log entry SHALL set the corresponding field to JSON `null` rather than omitting the field.
8. IF the MCP_Server cannot write the Audit_Log entry to CloudWatch Logs within 2 seconds, THEN THE MCP_Server SHALL complete the tool invocation response to the caller and SHALL emit a separate error log entry to CloudWatch Logs containing the MCP request ID and a description of the logging failure.

### Requirement 7: Developer Backward Compatibility

**User Story:** As an AWS developer using Kiro on the EC2 workstation, I want my current SigV4 proxy flow to keep working unchanged after external access is enabled, so that my daily development is not disrupted.

#### Acceptance Criteria

1. WHEN the Developer_Principal invokes the MCP_Endpoint via `tools/agentcore-kiro-proxy.py` using IAM SigV4 `invoke_agent_runtime`, THE AgentCore_Runtime SHALL route the request to the MCP_Server within 10 seconds of receipt.
2. WHILE the JWT_Authorizer is enabled on the AgentCore_Runtime, THE Developer_Principal SHALL receive a non-error MCP response for any tool invocation over the SigV4 path that would have succeeded before the JWT_Authorizer was enabled.
3. THE `tools/agentcore-kiro-proxy.py` source file SHALL remain byte-identical to its pre-feature state, such that no code change to that file is required for the Developer_Principal path to function.
4. THE `.kiro/settings/mcp.json` entry for the `agentcore-mcp-rag` Developer_Principal server SHALL remain byte-identical to its pre-feature state, such that no configuration change is required for the Developer_Principal path to function.
5. WHEN a regression verification is performed that invokes each of the 51 MCP_Server tools over the Developer_Principal SigV4 path using the unmodified proxy and unmodified Kiro configuration, THE verification SHALL observe a successful MCP response for 51 of 51 tools.

### Requirement 8: Network Reachability and VPC Isolation

**User Story:** As a security engineer, I want the MCP_Endpoint reachable from the public internet for GitHub and HPC callers while Neptune and OpenSearch remain VPC-internal, so that external consumers can reach the MCP_Server without exposing the backing data stores.

#### Acceptance Criteria

1. WHEN a client on a GitHub-hosted runner network or on an HPC login node of Hera, Orion, Hercules, Gaea, or Ursa initiates an HTTPS connection to the MCP_Endpoint, THE MCP_Endpoint SHALL complete a TLS 1.2 or TLS 1.3 handshake using a certificate whose subject or SAN matches the MCP_Endpoint hostname and whose chain is signed by a publicly trusted certificate authority.
2. WHEN a caller inside VPC `vpc-055f30ffa3d661e6b` initiates a connection to the Neptune cluster `mdc-mcp-graprag-neptune-1` on its configured Neptune endpoint port, THE Neptune cluster SHALL accept the connection, and WHEN a caller outside VPC `vpc-055f30ffa3d661e6b` initiates the same connection, THE Neptune cluster SHALL reject or drop the connection such that no TCP session is established.
3. WHEN a caller inside VPC `vpc-055f30ffa3d661e6b` initiates a connection to the OpenSearch domain `mdc-mcp-rag-search` on its configured OpenSearch endpoint port, THE OpenSearch domain SHALL accept the connection, and WHEN a caller outside VPC `vpc-055f30ffa3d661e6b` initiates the same connection, THE OpenSearch domain SHALL reject or drop the connection such that no TCP session is established.
4. THE AgentCore_Runtime SHALL retain its `network_mode: VPC` configuration and SHALL have its microVM attached to the existing private subnets of VPC `vpc-055f30ffa3d661e6b` after this feature is deployed.
5. WHEN the design phase reaches the network-architecture review, THE design SHALL record, in the design document `.kiro/specs/mcp-external-access/design.md`, a verification result citing either an AWS documentation reference or a documented test observation that confirms whether inbound public-internet traffic to the MCP_Endpoint is compatible with the AgentCore_Runtime's `network_mode: VPC`, and implementation tasks SHALL NOT start until this verification result is recorded.
6. IF the verification recorded under Acceptance Criterion 5 indicates that public inbound MCP traffic is incompatible with `network_mode: VPC`, THEN THE design SHALL document at least one alternative path, such as a Gateway fronting the AgentCore_Runtime or a change of `network_mode`, with its tradeoffs, before any implementation task begins.
7. WHEN a network reachability test is executed from a host outside VPC `vpc-055f30ffa3d661e6b` against the Neptune cluster `mdc-mcp-graprag-neptune-1` and the OpenSearch domain `mdc-mcp-rag-search` on their configured endpoint ports, THE test SHALL observe a connection failure (timeout or refused) within 30 seconds for each target, and the result SHALL be recorded in the design or verification artifact for this feature.

### Requirement 9: Infrastructure as Code and Data Safety

**User Story:** As a data steward, I want every new AWS resource for this feature defined in CDK with data-safe removal policies, so that infrastructure changes are reviewable, reproducible, and do not repeat the April 22, 2026 Neptune data loss pattern.

#### Acceptance Criteria

1. THE Cognito_User_Pool, CI_App_Client, HPC_App_Client, Token_Broker Lambda, federated IAM role, and updated AgentCore_Runtime authorizer configuration SHALL all be defined in CDK under `infrastructure/cdk/`, and no AWS resource supporting this feature SHALL be created or modified outside this CDK stack.
2. THE Cognito_User_Pool CDK construct SHALL set `removalPolicy: cdk.RemovalPolicy.RETAIN`.
3. WHERE this feature introduces a KMS key, THE KMS key CDK construct SHALL set `removalPolicy: cdk.RemovalPolicy.RETAIN`.
4. THE CDK test suite SHALL assert that each stateful resource — Cognito_User_Pool, any KMS keys introduced by this feature, the Neptune cluster, the OpenSearch domain, all S3 buckets, the EFS file system, and existing AgentCore_Runtime data surfaces — has `DeletionPolicy: Retain` in the synthesized CloudFormation template.
5. WHEN the CDK stack is deployed, THE deployment SHALL leave the Neptune cluster, OpenSearch domain, S3 buckets, EFS file system, and existing AgentCore_Runtime data surfaces unmodified, unreplaced, and undeleted.
6. IF `cdk diff` output indicates deletion, replacement, or destructive in-place modification of any resource enumerated in criterion 5, THEN THE deployment pipeline SHALL abort before executing `cdk deploy` and SHALL require explicit override by an authorized reviewer listed in `.kiro/steering/05-cdk-data-safety.md`.
7. THE `cdk diff` output SHALL be reviewed before every `cdk deploy` by a reviewer listed as authorized in `.kiro/steering/05-cdk-data-safety.md`, and THE review record SHALL capture reviewer identity, review timestamp, and diff content hash, and SHALL be no older than 24 hours at the time `cdk deploy` executes.
8. THE Cognito, IAM, and AgentCore configuration introduced by this feature SHALL be created, modified, and deleted exclusively through the CDK stack.
9. IF a Cognito, IAM, or AgentCore configuration change for this feature is detected as applied outside the CDK stack, THEN THE system SHALL revert the out-of-band change and reapply the intended configuration through CDK.

### Requirement 10: Documentation

**User Story:** As a new CI pipeline author or HPC_User, I want a single onboarding document for my consumer class, so that I can configure my workflow or session without reading the entire design.

#### Acceptance Criteria

1. THE project SHALL publish a CI Runbook at `docs/runbooks/mcp-external-access-ci.md` that contains, at minimum, the following sections in this order: Prerequisites, Step-by-step Configuration, Reusable Workflow Snippet, Allowed Tool List, and Troubleshooting.
2. THE CI Runbook SHALL include a reusable workflow snippet that, when copied verbatim into a GitHub Actions workflow with the documented prerequisites satisfied, successfully authenticates to the MCP_Endpoint and invokes at least one Allowed_Tool_Set member of `mcp/ci-readonly` end-to-end without modification.
3. THE CI Runbook SHALL enumerate every member of the Allowed_Tool_Set for `mcp/ci-readonly` by name in the Allowed Tool List section.
4. THE CI Runbook Troubleshooting section SHALL document both HTTP 401 and HTTP 403 responses, and for each response SHALL state at least one probable cause and the corresponding corrective action the workflow author must take.
5. THE project SHALL publish an HPC Runbook at `docs/runbooks/mcp-external-access-hpc.md` that contains, at minimum, the following sections in this order: Prerequisites, Step-by-step Installation and Session Setup, Reusable Snippet, Allowed Tool List, and Troubleshooting.
6. THE HPC Runbook SHALL provide installation and invocation steps for the HPC_CLI_Helper on each platform named in the project's supported HPC platforms list (Hera, Orion, Hercules, Gaea, Ursa), and SHALL NOT claim support for any platform absent from that list.
7. THE HPC Runbook SHALL state the expected JWT token lifetime as a numeric value with an explicit time unit (seconds, minutes, or hours), document the procedure for handling expired tokens, and state that JWTs SHALL NOT be stored in shared filesystem locations.
8. THE HPC Runbook Troubleshooting section SHALL document both HTTP 401 and HTTP 403 responses, and for each response SHALL state at least one probable cause and the corresponding corrective action the HPC_User must take.
9. THE project SHALL update `.kiro/steering/01-architecture-context.md` or publish a new steering file containing a summary of the external access paths that is at most 150 words and that includes direct markdown links to both the CI Runbook and the HPC Runbook.
10. THE CI Runbook and THE HPC Runbook SHALL each include a dedicated section titled to disambiguate SigV4 from JWT access that names the Developer_Principal path and states that existing AWS-workstation users SHALL continue to use the SigV4 proxy and SHALL NOT use the JWT path.

### Requirement 11: Forward Reference to Path C — Deferred

**User Story:** As a future platform maintainer, I want this spec to explicitly record that Path C (AgentCore Gateway with Cedar tool-level policies) is planned but deferred, so that Phase B implementers do not optimize Phase B in a way that blocks later Gateway adoption.

#### Acceptance Criteria

1. THE design document `.kiro/specs/mcp-external-access/design.md` SHALL include a top-level section titled exactly "Path C — Deferred" containing at minimum the subsections Scope, Rationale, and Migration Outline, where Scope names the Path C capabilities (Gateway-fronted authorizer, Cedar tool-level policies, interceptor-based audit enrichment, cross-account resource policies), Rationale states why Path C is deferred, and Migration Outline sketches the conceptual steps from a Runtime-attached authorizer to a Gateway-fronted authorizer.
2. THE design document's "Path C — Deferred" section SHALL identify at least three Phase B design decisions that would materially block or complicate Phase C adoption, and for each identified decision SHALL record the decision name, its blocking impact on Phase C, and the recommended Phase B approach that preserves Phase C compatibility.
3. THE spec scope for `.kiro/specs/mcp-external-access/` SHALL be limited to Path B, and detailed acceptance criteria, CDK constructs, and implementation tasks for Path C SHALL be captured in a separate follow-on spec created when Path C work begins.
4. THE tasks document `.kiro/specs/mcp-external-access/tasks.md` SHALL NOT include any Path C implementation task, where Path C implementation tasks are defined as tasks that provision an AgentCore Gateway, author Cedar policies, wire a Gateway-attached authorizer, or route tool invocations through a Gateway.
5. WHERE the tasks document includes a placeholder task group for the Phase B→C transition, THE placeholder task group SHALL be titled exactly "Phase B → C Migration (deferred)", SHALL contain zero executable subtasks, and SHALL cross-reference the follow-on spec location by path.
6. IF the design document lacks the "Path C — Deferred" section named in criterion 1, or IF the tasks document contains any Path C implementation task as defined in criterion 4, THEN THE spec SHALL be considered non-compliant with Requirement 11 and SHALL NOT advance to implementation.

## Correctness Properties (for Property-Based Testing)

These properties are candidates for Hypothesis/property-based tests written during implementation. They are not acceptance criteria themselves but are cross-referenced from the criteria above.

- **P1 — Valid token admission**: For every JWT whose signature validates, whose `iss`/`aud`/`exp`/`scope` satisfy Requirement 2 criteria 2–4, and whose scope maps to a non-empty Allowed_Tool_Set containing the requested tool, the MCP_Endpoint SHALL return a successful MCP response.
- **P2 — Invalid token rejection**: For every JWT missing a required claim, carrying a disallowed scope, expired, or signed with an unknown key, the MCP_Endpoint SHALL return HTTP 401 per Requirement 2 criterion 6 and SHALL NOT leak claim values.
- **P3 — CI mutation rejection**: For every invocation of a Mutation_Tool_Set member with a JWT whose scope is `mcp/ci-readonly`, the MCP_Server SHALL return HTTP 403 per Requirement 5 criterion 8.
- **P4 — Expired token no-leak**: For every expired JWT presented to the MCP_Endpoint, the response SHALL be HTTP 401 with no tool metadata in the body.
- **P5 — Audit completeness**: For every successful tool invocation, exactly one Audit_Log JSON Lines entry SHALL appear in CloudWatch Logs containing `caller_sub`, `tool`, `request_id`, and `outcome` per Requirement 6.
- **P6 — Developer path preservation**: For every tool in the 51-tool set, a SigV4 invocation via the unmodified `agentcore-kiro-proxy.py` SHALL succeed after deployment per Requirement 7 criterion 5.
- **P7 — Scope isolation**: For every JWT issued by the CI_App_Client, its scope claim SHALL equal exactly `mcp/ci-readonly`; for every JWT issued by the HPC_App_Client, its scope claim SHALL equal exactly `mcp/hpc-user`.
- **P8 — No long-lived secrets in CI path**: For every invocation of the published GitHub Actions workflow snippet, no AWS access key, secret access key, or Cognito client secret SHALL be read from any repository file, GitHub Actions secrets store entry, or runner environment variable.
