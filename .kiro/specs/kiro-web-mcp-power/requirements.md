# Requirements Document

## Introduction

Package the MDC MCP RAG Server — the GraphRAG-backed code assistant for the NOAA
`global-workflow` repository and its per-branch tenants — as a **Kiro Power** so that
browser-based Kiro Web sessions can call its tools.

**This spec delivers a PROTOTYPE / preview capability. It is not production.** Every
requirement below is written for a prototype trust posture, and Requirement 4 records an
explicitly accepted residual authorization risk that a production deployment must retire.

Kiro Web does not read `.kiro/settings/mcp.json`. In Kiro Web, MCP tools reach the agent
only through an installed Power, invoked through the single `kiro_powers` interface
(actions `list`, `activate`, `use`, `readSteering`, `readSkill`, `configure`). A Power is
an installable capability bundle that packages steering documentation and zero or more MCP
servers.

**Plan A — the delivery decision this spec records.** The MDC_Power reaches the MCP_Server
over IAM SigV4 `bedrock-agentcore:InvokeAgentRuntime`, reusing the already complete stdio
bridge `tools/agentcore-kiro-proxy.py` delivered by the spec `agentcore-kiro-proxy` (46 of
46 tasks complete). Plan A uses no Amazon Cognito user pool, no JWT, no OAuth scope, no
Bearer token, and no Token_Broker, and it has no delivery dependency on Path_B_Baseline.

**Why a developer-trust posture is justified.** Access to a Kiro Web session is already
gated by United States government CAC single sign-on into the project's AWS account under
project IAM, through Kiro subscriptions. A Kiro Web session is therefore a named, strongly
authenticated human operating inside the project IAM boundary, and not an anonymous
browser sandbox. Plan A treats a Kiro Web session as an instance of the existing
Developer_Principal class rather than as a new public consumer class.

**Path B proceeds in parallel and stays coupled.** The spec
`.kiro/specs/mcp-external-access-revised/` (Path_B_Baseline) retains ownership of the
Amazon Cognito JWT posture, the GitHub Actions CI consumer class, and the RDHPCS/HPC
login-node endpoints. The Cognito JWT posture is the eventual production migration path for
Kiro Web, and Requirement 4 names the trigger for that migration. Path_B_Baseline is not a
prerequisite for delivering this spec.

This spec defines the requirements for the `mdc-mcp-graphrag` Power: its manifest, its
SigV4 stdio transport through the existing proxy, its AWS credential lifecycle, its
IAM-bounded authorization surface together with the residual risk that surface carries, its
tenant-selection surface, its audit trail, and its sequencing relative to already-designed
work.

### Gap analysis: what Kiro Web needs that the current wiring does not provide

Three gaps drive this spec.

**Gap 1 — the existing proxy path is viable in Kiro Web, and Plan A adopts it.** The
repository's current `.kiro/settings/mcp.json` declares one stdio server,
`eib-mcp-rag-full`, launched by executing
`/mcp_rag_eib/eib-mcp-rag-server/mcp_server_python/scripts/run_mcp_stdio.sh`. That path
depends on the developer EC2 workstation filesystem layout, which a Kiro Web sandbox does
not have, so that path stays unused by the MDC_Power. The AWS-native alternative documented
in `.kiro/steering/09-agentcore-mcp-for-global-workflow.md` is different in kind:
`tools/agentcore-kiro-proxy.py` (spec `agentcore-kiro-proxy`, 46 of 46 tasks complete)
bridges MCP stdio JSON-RPC to boto3 `invoke_agent_runtime` SigV4 calls and reassembles the
SSE response. That proxy lives inside this repository, which the Kiro Web session already
holds in its working tree; the sandbox can spawn child processes, can install `boto3`, and
can reach the AWS service endpoints, all verified live and recorded under
`### Verified Kiro Web sandbox characteristics` below. The single element the sandbox lacked
was AWS credential material, and credential delivery is fixed by the reframed Open Question
OQ-1 and governed by Requirement 3. Plan A therefore reuses
`tools/agentcore-kiro-proxy.py` unmodified and unforked, as required by Requirement 2.

**Gap 2 — Kiro Web is no longer being made a fourth Cognito consumer class.** The
designed-but-unimplemented spec `.kiro/specs/mcp-external-access-revised/` (Path B: a
Cognito-backed JWT authorizer attached to the existing AgentCore Runtime, exposing MCP
Streamable HTTP) enumerates exactly three consumer classes: the developer workstation over
IAM SigV4, GitHub Actions CI over GitHub OIDC → `AssumeRoleWithWebIdentity` → Token_Broker
Lambda → Cognito client-credentials with scope `mcp/ci-readonly`, and HPC login-node users
over Authorization Code + PKCE through the Cognito Hosted UI (with `USER_SRP_AUTH` as
fallback) with scope `mcp/hpc-user`. An earlier draft of this spec added Kiro Web as a
fourth consumer class with its own Cognito app client and its own OAuth scope. That
decision is reversed. Under Plan A, Kiro Web uses the existing Developer_Principal IAM
SigV4 path under a prototype trust posture, this spec creates no Cognito scope, no Cognito
app client, and no Token_Broker consumer, and Path_B_Baseline keeps its three consumer
classes unchanged. The cost of that reversal is that authorization is bounded by IAM at the
AgentCore Runtime rather than per MCP tool; Requirement 4 states that cost plainly and
records it as an accepted prototype risk with a named migration trigger.

**Gap 3 — tenant selection needs an agent-facing surface.** The `global-workflow` tenants
are represented as branches (`gw`, `gw_sfs`, `gw_jedi_gfs`, `gw_v17`, `gw_gefs_v12` per
`.kiro/steering/09-agentcore-mcp-for-global-workflow.md`). A Kiro Web agent must be able to
discover the tenant catalog, declare which tenant it is querying, and receive an honest
answer when a tenant's graph or vector index is absent or stale — the concern already
scoped for the local server by the unstarted spec `.kiro/specs/tenant-status-honesty/`.

### Verified Kiro Web sandbox characteristics

These facts were **observed directly in a live Kiro Web session** and are recorded here so
that no future reader re-derives them incorrectly. They matter because an earlier draft of this
spec justified its remote-HTTP-only and Bearer-token-only constraints partly on the premise
that the sandbox was *incapable* of the alternatives. That premise is wrong, and Plan A rests
on these observations.

1. **Child process spawning works.** `subprocess.run` succeeds in the sandbox, and the bundled
   `playwright` Power runs a local browser process. A sandbox-hosted MCP stdio server is
   therefore technically possible.
2. **AWS API endpoints are reachable over the public internet.**
   `https://bedrock-agentcore.us-east-1.amazonaws.com/` returns HTTP 404 and
   `https://cognito-idp.us-east-1.amazonaws.com/` returns HTTP 400. Both completed TLS, which
   proves the network path to each service exists; the status codes reflect an unrouted path
   and a malformed request body respectively, not a blocked connection.
3. **The `aws` CLI is installed.** `aws --version` reports version 2.33.15, and the executable
   is present at `/usr/bin/aws`.
4. **The AWS STS regional endpoint is reachable.** `https://sts.us-east-1.amazonaws.com/`
   returns HTTP 302, which completed TLS and therefore proves the network path exists.
5. **`boto3` is not preinstalled but is installable.** `pip download boto3` succeeded in the
   sandbox, so the proxy's only third-party dependency can be provisioned at session time.
6. **No AWS credentials are present.** There is no `~/.aws` directory and therefore no
   `~/.aws/sso` cache; `AWS_EC2_METADATA_DISABLED` is set; and no `AWS_ACCESS_KEY_ID`,
   `AWS_SECRET_ACCESS_KEY`, or `AWS_SESSION_TOKEN` environment variable is set. `AWS_REGION`
   and `AWS_DEFAULT_REGION` *are* set, and a region value is no indication that a credential
   source exists. A SigV4 request therefore cannot be signed without first introducing
   credential material into the sandbox.
7. **Network mode is `OPEN_INTERNET`.**
8. **CAC SSO gates the session but does not deliver AWS credentials.** United States
   government CAC single sign-on controls who may open a Kiro Web session against the
   project's AWS account under project IAM, and it does **not** propagate AWS credentials into
   the sandbox process environment. Credential delivery into the sandbox is a separate,
   required, explicit step, fixed by the reframed Open Question OQ-1 and governed by
   Requirement 3.

The operative consequence is fact 6: the sandbox can spawn the proxy process, can install
`boto3`, and can reach both `sts` and `bedrock-agentcore`, but it holds no AWS credential to
sign with until one is delivered. Plan A is therefore viable, and the earlier draft's
prohibitions on child processes, MCP stdio transport, `agentcore-kiro-proxy.py` invocation,
and SigV4 signing are removed rather than restated as design choices.

### Scope boundaries

- **Delivery plan (recorded, not open)**: Plan A. The MDC_Power invokes the MCP_Server over
  IAM SigV4 `invoke_agent_runtime` through the unmodified, unforked existing bridge
  `tools/agentcore-kiro-proxy.py`. This spec introduces no Amazon Cognito user pool, no JWT
  authorizer, no OAuth scope, and no Bearer token.
- **Status**: Prototype_Status is `prototype`. The MDC_Power is a preview capability for
  project members inside the CAC SSO and project IAM boundary, and it is not a production
  service.
- **No Path B delivery dependency**: Open Question OQ-2 remains retired, and its resolution is
  now `no-delivery-dependency`, superseding the earlier `carved-enabling-slice` resolution. No
  Path_B_Baseline task is required for the MDC_Power to function. The GitHub Actions CI
  consumer class, the RDHPCS/HPC login-node consumer class, the Token_Broker Lambda, the
  GitHub OIDC federated IAM role, and the Cognito JWT authorizer all remain owned by
  Path_B_Baseline and are off this spec's critical path.
- **Path B coupling and migration intent**: Path_B_Baseline proceeds in parallel and stays
  coupled to this spec through the shared AgentCore_Runtime_Arn. The Cognito JWT posture with
  per-scope tool enforcement is the production migration path for Kiro Web, and the migration
  trigger is named in Requirement 4.
- **In scope**: the Power definition and its steering bundle; the SigV4 stdio transport
  contract through the existing proxy; the Kiro Web session's AWS credential lifecycle; the
  Kiro_Web_Principal IAM policy, the tool surface that policy grants, and the documented
  residual risk that surface carries; the tenant-selection and tenant-status surface exposed
  through the Power; attribution and audit for Kiro Web invocations; failure diagnostics;
  documentation; and the coupling contract with `mcp-external-access-revised`.
- **Out of scope**: implementing the Path B Cognito authorizer itself (owned by
  `mcp-external-access-revised`); modifying `tools/agentcore-kiro-proxy.py` or
  `.kiro/settings/mcp.json`; adding, removing, or changing any MCP tool's behavior; ingesting
  data for any tenant; AgentCore Gateway adoption (Path C, deferred by
  `mcp-external-access-revised` Requirement 11).

## Glossary

- **MCP_Server**: The MDC MCP RAG Server — the Python MCP tool server deployed on AWS
  Bedrock AgentCore Runtime, backed by Amazon Neptune (openCypher graph) and Amazon
  OpenSearch (k-NN + BM25 vector).
- **AgentCore_Runtime**: The AWS Bedrock AgentCore serverless runtime hosting the
  MCP_Server. Two runtime identifiers appear in existing repository artifacts and are
  reconciled by Open Question OQ-4.
- **AgentCore_Runtime_Arn**: The single AWS resource ARN of the AgentCore_Runtime, of the form
  `arn:aws:bedrock-agentcore:<region>:<account-id>:runtime/<runtime-id>`, whose literal value
  is fixed by Open Question OQ-4. The AgentCore_Runtime_Arn is simultaneously the
  `agentRuntimeArn` target of every `invoke_agent_runtime` call and the sole `Resource` element
  of the Kiro_Web_Principal IAM policy required by Requirement 4.
- **Proxy_Bridge**: The existing stdio-to-SigV4 bridge program at
  `tools/agentcore-kiro-proxy.py`, delivered complete by the spec `agentcore-kiro-proxy`, which
  reads MCP JSON-RPC messages from standard input, forwards each message as a boto3
  `bedrock-agentcore` `invoke_agent_runtime` call signed with AWS Signature Version 4,
  reassembles the SSE response body, and writes the MCP JSON-RPC response to standard output.
- **MCP_Stdio_Transport**: The MCP standard-input/standard-output transport, in which an MCP
  client exchanges newline-delimited MCP JSON-RPC messages with a local child process. This is
  the transport the MDC_Power uses under Plan A.
- **Runtime_Session_Id**: The `runtimeSessionId` value the Proxy_Bridge sends on every
  `invoke_agent_runtime` call, at least 33 characters long, under which the AgentCore_Runtime
  keeps server-side session state.
- **Prototype_Status**: The declared maturity of the MDC_Power, whose value under this spec is
  `prototype`, meaning a preview capability for project members inside the CAC SSO and project
  IAM boundary and not a production service.
- **MCP_Endpoint**: The public HTTPS MCP Streamable HTTP URL through which the
  AgentCore_Runtime accepts MCP JSON-RPC requests. **Not used under Plan A** — Plan A reaches
  the AgentCore_Runtime through the `invoke_agent_runtime` AWS API rather than through an MCP
  Streamable HTTP URL. The term is retained for the Path B migration discussion.
- **Streamable_HTTP_Transport**: The MCP Streamable HTTP transport, in which an MCP client
  issues HTTPS requests carrying MCP JSON-RPC payloads and consumes JSON or
  `text/event-stream` responses, with no local child process. **Not used under Plan A**;
  retained for the Path B migration discussion.
- **Kiro_Web**: The browser-originated Kiro session running in a remote cloud sandbox, whose
  network mode is `OPEN_INTERNET` and which does not read `.kiro/settings/mcp.json`.
- **Kiro_Power**: An installable Kiro capability bundle that packages steering documents,
  optional skills, and zero or more MCP server declarations.
- **MDC_Power**: The Kiro_Power defined by this spec, which surfaces MCP_Server tools to
  Kiro_Web.
- **Power_Manifest**: The declarative definition of the MDC_Power — its name, description,
  keyword triggers, steering file list, and MCP server declarations.
- **Powers_Interface**: The `kiro_powers` tool through which Kiro_Web discovers and invokes
  Powers, supporting the actions `list`, `activate`, `use`, `readSteering`, `readSkill`, and
  `configure`.
- **Steering_Bundle**: The set of markdown steering documents shipped inside the MDC_Power
  and retrievable through the Powers_Interface `readSteering` action.
- **Kiro_Web_Principal**: The AWS IAM identity a Kiro_Web session assumes and under which the
  Proxy_Bridge signs every `invoke_agent_runtime` call, held by a named human already
  authenticated through government CAC single sign-on.
- **Kiro_Web_Credentials**: The short-lived AWS credentials the Kiro_Web session holds for the
  Kiro_Web_Principal — an access key identifier, a secret access key, a session token, and an
  expiration timestamp issued by AWS STS — whose delivery mechanism is fixed by the reframed
  Open Question OQ-1 and whose lifecycle is governed by Requirement 3.
- **Web_Scope**: The OAuth 2.0 scope string that identifies a Kiro_Web_Principal to the
  MCP_Server, analogous to the existing `mcp/ci-readonly` and `mcp/hpc-user` scopes.
  **Not used under Plan A** — Plan A creates no OAuth scope for Kiro_Web. The term is retained
  for the Path B migration discussion, where its literal value becomes decidable again.
- **Web_App_Client**: The Cognito app client that issues access tokens carrying the Web_Scope.
  **Not used under Plan A**; retained for the Path B migration discussion.
- **Cognito_User_Pool**: The Amazon Cognito user pool defined by
  `.kiro/specs/mcp-external-access-revised/` that issues the JWT access tokens the
  AgentCore_Runtime authorizer accepts. **Not used under Plan A**; retained for the Path B
  migration discussion, and owned by Path_B_Baseline.
- **Token_Broker**: The AWS Lambda function defined by
  `.kiro/specs/mcp-external-access-revised/` that mints a Cognito access token for a
  federated caller and writes one structured CloudWatch Logs entry keyed by its own request
  identifier. **Not used under Plan A**; owned by Path_B_Baseline (Task 4), and no Kiro_Web
  behavior depends on it.
- **Broker_Request_Id**: The Token_Broker request identifier that the Token_Broker returns to
  its caller and records in its structured log entry. **Not used under Plan A**; retained only
  to name the Path_B_Baseline CI-path mechanism this spec does not use.
- **Token_Issuance_Correlation_Id**: The identifier that joins a Kiro_Web Audit_Log entry to
  the log entry recording the issuance of the access token that entry's request presented.
  **Not used under Plan A**, because Plan A presents no access token; retained for the Path B
  migration discussion. Under Plan A, Kiro_Web attribution rests on the CloudTrail-recorded IAM
  principal identifier, the Runtime_Session_Id, and the Kiro_Web_Session_Id.
- **Kiro_Web_Session_Id**: The MDC_Power-generated identifier, constant across every call in
  one Kiro_Web session and distinct across concurrent Kiro_Web sessions, that anchors
  Kiro_Web attribution together with the CloudTrail-recorded IAM principal identifier of the
  Kiro_Web_Principal and the Runtime_Session_Id.
- **Request_Metadata**: Named values a caller attaches to an MCP call so the MCP_Server audit
  logger can record them beside the caller identity the MCP_Server observes for that
  invocation.
- **Audit_Log**: The structured CloudWatch Logs JSON Lines stream the MCP_Server writes, one
  entry per tool invocation.
- **Allowed_Tool_Set**: The set of MCP_Server tools callable by a given principal class. Under
  Plan A the Allowed_Tool_Set for the Kiro_Web_Principal is the complete MCP_Server tool
  registry, as stated by Requirement 4; keying an Allowed_Tool_Set by OAuth scope is a
  Path_B_Baseline mechanism.
- **Mutation_Tool_Set**: The enumerated set of MCP_Server tools that create, update, delete,
  or otherwise modify persistent or session state, as defined by
  `.kiro/specs/mcp-external-access-revised/requirements.md`.
- **Developer_Principal**: The existing developer path — the EC2 workstation IAM role used by
  the Proxy_Bridge over IAM SigV4 `invoke_agent_runtime`. Under Plan A the Kiro_Web_Principal
  is an instance of this principal class, differing only in how its credentials arrive.
- **Tenant**: One `global-workflow` branch indexed as an isolated slice of the shared Neptune
  cluster and OpenSearch domain, identified by a `tenant_id`.
- **Tenant_Catalog**: The authoritative list of Tenants, sourced from
  `mcp_server_python/src/config/tenants.yaml`.
- **Tenant_Data_Status**: A per-Tenant classification of index population, with the values
  `populated`, `graph-only`, `vector-only`, `empty`, and `probe-error`, as defined by
  `.kiro/specs/tenant-status-honesty/`.
- **Path_B_Baseline**: The spec `.kiro/specs/mcp-external-access-revised/`, organized as 14
  top-level task groups numbered Task 0 through Task 13, all of which were unstarted when
  this spec was written.
- **Enabling_Slice**: The subset of Path_B_Baseline task groups that an earlier Cognito-based
  draft of this spec required in order to function. **Not used under Plan A** — Plan A requires
  no Path_B_Baseline task. The term is retained for the Path B migration discussion.
- **Power_Runbook**: The markdown onboarding document for Kiro_Web consumers of the
  MDC_Power.

## Requirements

### Requirement 1: Power Packaging and Discovery

**User Story:** As a Kiro Web user, I want the MDC MCP RAG server delivered as an installable
Power, so that its tools appear in my browser session through the Powers interface without
any local configuration.

#### Acceptance Criteria

1. THE project SHALL publish exactly one Power_Manifest for the MDC_Power, and THE
   Power_Manifest SHALL parse without error as a single machine-readable declaration whose
   required fields are all present and non-empty: a Power name of 1 to 64 characters, a
   description of 1 to 200 characters containing exactly one sentence, a keyword trigger
   list of at least 5 entries, a Steering_Bundle file list of at least 2 entries, and
   exactly one MCP server declaration naming the MCP_Server, where that MCP server
   declaration contains exactly one command string and exactly one argument vector that
   together launch the Proxy_Bridge as described in Requirement 2.
2. WHEN a Kiro_Web session invokes the Powers_Interface `list` action, THE
   Powers_Interface SHALL return, within 10 seconds, the MDC_Power's name, description,
   keyword trigger list, and MCP server name, and each returned value SHALL be
   character-for-character identical to the corresponding value declared in the
   Power_Manifest.
3. WHEN a Kiro_Web session invokes the Powers_Interface `activate` action for the
   MDC_Power, THE Powers_Interface SHALL return, within 10 seconds, the MDC_Power
   documentation, the MCP server name under which the MDC_Power's tools are grouped, and
   the name and input schema of every tool in the Kiro_Web Allowed_Tool_Set defined in
   Requirement 4, and THE set of tool names returned SHALL equal that Allowed_Tool_Set
   exactly, with no tool name omitted and no tool name present that is absent from that
   Allowed_Tool_Set.
4. THE Power_Manifest keyword trigger list SHALL include at minimum the terms
   `global-workflow`, `graphrag`, `mdc-mcp`, `tenant`, and `ee2`, each matched
   case-insensitively.
5. THE Steering_Bundle SHALL include a consumer guide derived from
   `.kiro/steering/09-agentcore-mcp-for-global-workflow.md` and a tool-selection guide
   derived from `.kiro/steering/10-agentcore-mcp-tool-guide.md`, and every file named in
   the Power_Manifest Steering_Bundle file list SHALL exist and SHALL be non-empty.
6. WHEN a Kiro_Web session invokes the Powers_Interface `readSteering` action for a file
   named in the Steering_Bundle, THE Powers_Interface SHALL return, within 10 seconds, the
   complete content of that file byte-identical to the file shipped inside the MDC_Power.
7. WHEN a Kiro_Web session invokes the Powers_Interface `use` action naming the
   MDC_Power's MCP server and a tool in the Kiro_Web Allowed_Tool_Set, THE MDC_Power SHALL
   forward the call to the MCP_Server through the Proxy_Bridge with the caller-supplied
   tool name and tool arguments unmodified, and SHALL return the MCP_Server response to the
   caller with the tool result content unmodified.
8. THE Power_Manifest SHALL declare the MCP server as a local MCP_Stdio_Transport server,
   and THE declared argument vector SHALL name the Proxy_Bridge path
   `tools/agentcore-kiro-proxy.py`, the AgentCore_Runtime_Arn, and the AWS region of the
   AgentCore_Runtime_Arn.
9. THE Power_Manifest and every file in the Steering_Bundle SHALL contain zero occurrences
   of an AWS access key identifier, an AWS secret access key, an AWS session token, or any
   other credential material, verified by a text scan of those files that reports zero
   matches.
10. WHERE the MDC_Power declares a configurable value, including the AgentCore_Runtime_Arn
    fixed by Open Question OQ-4 and the AWS region of that AgentCore_Runtime_Arn, THE
    MDC_Power SHALL read that value from Power configuration or from a session environment
    variable, and THE Steering_Bundle SHALL contain zero literal values for those
    configurable items.
11. IF a Kiro_Web session invokes the Powers_Interface `readSteering` action for a file
    name that is absent from the Steering_Bundle file list, THEN THE Powers_Interface
    SHALL return an error naming the requested file name as not part of the
    Steering_Bundle and SHALL return no file content.
12. IF a Kiro_Web session invokes the Powers_Interface `use` action naming a tool that is
    absent from the Kiro_Web Allowed_Tool_Set, THEN THE MDC_Power SHALL return an error
    naming the requested tool as not exposed by the MDC_Power, SHALL send no
    `invoke_agent_runtime` call to the AgentCore_Runtime_Arn, and SHALL remain able to
    serve the next `use` invocation in the same Kiro_Web session.

### Requirement 2: SigV4 Stdio Transport Through the Existing AgentCore Proxy

**User Story:** As a platform operator, I want the Power to reach the MCP server over IAM
SigV4 `invoke_agent_runtime` through the existing completed proxy bridge, so that Kiro Web
delivery reuses a proven code path, adds no new authentication infrastructure, and stays on
the same transport the developer workstation already uses.

**Design rationale.** The Proxy_Bridge at `tools/agentcore-kiro-proxy.py` is complete (spec
`agentcore-kiro-proxy`, 46 of 46 tasks), already speaks MCP stdio on one side and
`invoke_agent_runtime` SigV4 on the other, already reassembles SSE responses, already retries
throttling errors, and already regenerates an expired runtime session. The Kiro_Web sandbox
can spawn that process, can install its single third-party dependency `boto3`, and can reach
the `bedrock-agentcore` regional endpoint, all verified live under
`### Verified Kiro Web sandbox characteristics`. Reusing the Proxy_Bridge unmodified keeps one
implementation of the AgentCore call path under one spec's ownership, so a fix in that path
reaches both the developer workstation and Kiro Web.

#### Acceptance Criteria

1. THE MDC_Power SHALL exchange every MCP JSON-RPC message with the MCP_Server over the
   MCP_Stdio_Transport of exactly one Proxy_Bridge child process, writing each MCP request
   to that process's standard input and reading each MCP response from that process's
   standard output.
2. THE Proxy_Bridge SHALL translate each MCP JSON-RPC message the Proxy_Bridge receives on
   standard input into exactly one `bedrock-agentcore` `invoke_agent_runtime` API call whose
   request is signed with AWS Signature Version 4 using the Kiro_Web_Credentials resolved
   from the AWS credential chain of the Proxy_Bridge process, and SHALL send no MCP JSON-RPC
   payload to the AgentCore_Runtime_Arn over any unsigned request.
3. THE MDC_Power SHALL launch the Proxy_Bridge from the repository path
   `tools/agentcore-kiro-proxy.py`, and THE content of that file SHALL be byte-identical to
   the version delivered by the spec `agentcore-kiro-proxy`, verified by a checksum
   comparison that reports a match, such that this spec's implementation introduces zero
   modified lines in that file.
4. THE project SHALL contain exactly one copy of the Proxy_Bridge source file, such that a
   repository-wide search for a file whose content matches the Proxy_Bridge returns exactly
   one path, and THE MDC_Power SHALL contain zero forked, vendored, inlined, or rewritten
   copies of the Proxy_Bridge logic.
5. WHEN the Powers_Interface `activate` action for the MDC_Power runs, THE MDC_Power SHALL
   verify that the Python interpreter used to launch the Proxy_Bridge can import `boto3` at
   version 1.34.0 or later, by executing an import check that reports the resolved `boto3`
   version and an exit status, and SHALL record the resolved `boto3` version in the
   activation output.
6. IF the import check required by Acceptance Criterion 5 reports that `boto3` is absent or
   reports a version earlier than 1.34.0, THEN THE MDC_Power SHALL install `boto3` at
   version 1.34.0 or later into the Python environment of the Proxy_Bridge exactly once per
   Kiro_Web session, SHALL repeat the import check after that installation, and SHALL send
   no MCP request until an import check reports a `boto3` version of 1.34.0 or later.
7. IF the import check required by Acceptance Criterion 5 still reports `boto3` as absent or
   earlier than version 1.34.0 after the single installation attempt permitted by Acceptance
   Criterion 6, THEN THE MDC_Power SHALL fail the Powers_Interface `activate` action, SHALL
   return an error naming the failing stage `proxy-launch`, the failure category
   `dependency-provisioning`, and the resolved `boto3` state, and SHALL launch no
   Proxy_Bridge process.
8. WHEN the AgentCore_Runtime returns a `text/event-stream` response body, THE Proxy_Bridge
   SHALL reassemble the received event-stream frames, in the order received, into exactly
   one MCP JSON-RPC response object whose `id` equals the `id` of the MCP request that
   produced that response, SHALL support a reassembled payload of at least 10 MiB, and SHALL
   write that response object to standard output only after the response body reports
   completion.
9. WHEN a Kiro_Web session invokes the MDC_Power more than once, THE MDC_Power SHALL use
   exactly one Runtime_Session_Id of at least 33 characters for the duration of that
   Kiro_Web session and SHALL send that byte-identical Runtime_Session_Id as the
   `runtimeSessionId` value of every `invoke_agent_runtime` call in that session, so that
   server-side session state written by one call is readable by the next call, and IF the
   AgentCore_Runtime rejects the Runtime_Session_Id as unknown or expired, THEN THE
   MDC_Power SHALL generate exactly one replacement Runtime_Session_Id and SHALL retry the
   rejected MCP request exactly once with that replacement Runtime_Session_Id.
10. THE MDC_Power SHALL send every `invoke_agent_runtime` call to the single
    AgentCore_Runtime_Arn fixed by Open Question OQ-4, passed as the `agentRuntimeArn`
    parameter, and SHALL send zero calls naming any other AgentCore Runtime ARN.
11. WHEN the Kiro_Web session ends, THE MDC_Power SHALL terminate the Proxy_Bridge process,
    such that 10 seconds after the session end the count of Proxy_Bridge processes belonging
    to that session is zero.
12. WHEN the Proxy_Bridge connects to the `bedrock-agentcore` regional service endpoint of
    the AgentCore_Runtime_Arn, THE Proxy_Bridge SHALL complete a TLS 1.2 or TLS 1.3
    handshake within 10 seconds using a certificate whose subject or subject-alternative
    name matches that service endpoint hostname and whose chain is signed by a publicly
    trusted certificate authority, SHALL negotiate no TLS version below TLS 1.2, and THE
    MDC_Power SHALL expose no Power configuration value, environment variable, or argument
    that disables certificate-chain validation or hostname validation.
13. IF the TLS handshake with the `bedrock-agentcore` regional service endpoint fails
    certificate-chain validation, fails hostname validation, or negotiates no TLS version of
    1.2 or higher, THEN THE MDC_Power SHALL close the connection before transmitting any
    SigV4-signed request or MCP JSON-RPC payload, SHALL return an error to the Kiro_Web
    session naming the failing stage `endpoint-invocation`, the failure category
    `tls-handshake`, and the contacted hostname, and SHALL NOT retry that connection attempt
    more than 3 times.
14. IF the configured AgentCore_Runtime_Arn value is absent, or does not match the form
    `arn:aws:bedrock-agentcore:<region>:<account-id>:runtime/<runtime-id>` with all four
    variable segments non-empty, or if the configured AWS region value is absent, THEN THE
    MDC_Power SHALL fail the Powers_Interface `activate` action, SHALL return an error naming
    the failing stage `power-activation` and the missing or invalid configuration value, and
    SHALL send no `invoke_agent_runtime` call.
15. IF an `invoke_agent_runtime` response body closes before one complete MCP JSON-RPC
    response object is reassembled, or IF no event-stream frame is received for 30
    consecutive seconds, THEN THE MDC_Power SHALL abandon that response, SHALL discard the
    partially reassembled bytes, SHALL return an error to the Kiro_Web session naming the
    failing stage `response-parsing` and the invoked tool name, and SHALL remain able to
    serve the next request in the same Kiro_Web session using the Runtime_Session_Id
    retained under Acceptance Criterion 9.

### Requirement 3: AWS Credential Lifecycle for a Browser-Originated Session

**User Story:** As a security engineer, I want the Kiro Web session's AWS credentials to be
short-lived, bounded, redacted, and discarded at session end, so that a browser-originated
session cannot become a persistent credential and an expired credential produces an
actionable instruction rather than an opaque SDK failure.

#### Acceptance Criteria

1. THE Kiro_Web_Credentials SHALL be short-lived AWS STS credentials for the
   Kiro_Web_Principal, consisting of an access key identifier, a secret access key, a
   session token, and an expiration timestamp, obtained by the credential-delivery
   mechanism fixed by the reframed Open Question OQ-1, and THE selected mechanism SHALL be
   recorded in the design document before any implementation task for this spec begins.
2. THE Kiro_Web_Credentials SHALL carry a session token and an expiration timestamp, such
   that long-term IAM user access keys, which carry neither, are excluded from use by the
   MDC_Power.
3. THE remaining lifetime of the Kiro_Web_Credentials at the moment of delivery into the
   Kiro_Web session, computed as the expiration timestamp minus the current UTC time, SHALL
   be at least 900 seconds and at most 43200 seconds, where 43200 seconds is 12 hours and is
   the stated maximum credential lifetime for the Kiro_Web_Principal.
4. WHEN a new MCP request is issued and the remaining lifetime of the held
   Kiro_Web_Credentials, computed as the expiration timestamp minus the current UTC time, is
   less than the pre-expiry refresh threshold of 900 seconds, THE MDC_Power SHALL emit one
   credential-expiry warning to the Kiro_Web session that names the remaining lifetime in
   seconds and names the credential-refresh command fixed by the reframed Open Question
   OQ-1, and SHALL send the MCP request.
5. WHERE the credential-delivery mechanism fixed by the reframed Open Question OQ-1 supports
   unattended refresh, THE MDC_Power SHALL obtain replacement Kiro_Web_Credentials when the
   remaining lifetime falls below the 900-second pre-expiry refresh threshold and SHALL send
   subsequent `invoke_agent_runtime` calls signed with the replacement Kiro_Web_Credentials.
6. THE MDC_Power SHALL redact the Kiro_Web_Credentials from every output the MDC_Power
   produces, such that no contiguous substring longer than 8 characters of the secret access
   key and no contiguous substring longer than 8 characters of the session token appears in
   any Kiro_Web chat response, log line, error message, diagnostic output, or MCP error
   payload.
7. WHEN the MDC_Power holds Kiro_Web_Credentials, THE MDC_Power SHALL retain that credential
   material only in the process memory and process environment of the Kiro_Web session and
   SHALL write zero bytes of that credential material to the sandbox filesystem, the
   repository working tree, persisted Power configuration, the Power_Manifest, the
   Steering_Bundle, or the Kiro_Web chat transcript.
8. WHEN the Kiro_Web session ends, THE MDC_Power SHALL discard the Kiro_Web_Credentials from
   process memory and from the Proxy_Bridge process environment within 5 seconds of the
   session end, and SHALL leave zero bytes of that credential material in the Kiro_Web
   sandbox filesystem or in the repository working tree.
9. IF the AWS credential chain of the Proxy_Bridge resolves no credentials, or resolves
   credentials that lack a session token or lack an expiration timestamp, THEN THE MDC_Power
   SHALL return an error to the Kiro_Web session naming the failing stage
   `credential-resolution` and the failure category `credentials-absent`, stating that the
   Kiro_Web session holds no usable Kiro_Web_Credentials, and naming the credential-refresh
   command fixed by the reframed Open Question OQ-1, and SHALL send no
   `invoke_agent_runtime` call.
10. IF an `invoke_agent_runtime` call fails with an AWS error indicating expired or invalid
    credentials, including `ExpiredTokenException`, `InvalidClientTokenId`, and
    `UnrecognizedClientException`, THEN THE MDC_Power SHALL classify that failure as expired
    Kiro_Web_Credentials and SHALL return an error to the Kiro_Web session naming the
    failing stage `credential-resolution`, the failure category `credential-expiry`, the
    expiration timestamp of the held Kiro_Web_Credentials, and the credential-refresh command
    the Kiro_Web user is to run to obtain replacement Kiro_Web_Credentials.
11. WHEN the MDC_Power returns the error required by Acceptance Criterion 9 or Acceptance
    Criterion 10, THE returned message SHALL state the re-authentication instruction in
    place of the raw AWS SDK exception text, such that the message contains the
    credential-refresh command and contains no Python traceback and no raw botocore
    exception representation.
12. IF the MDC_Power obtains replacement Kiro_Web_Credentials after a failure classified
    under Acceptance Criterion 10, THEN THE MDC_Power SHALL resend the failed MCP request
    exactly once with the same MCP method and parameters signed by the replacement
    Kiro_Web_Credentials, and IF that single resend also fails with an expired-or-invalid
    credential error, THEN THE MDC_Power SHALL return the error required by Acceptance
    Criterion 10 and SHALL send no further resend for that MCP request.
13. THE credential-delivery mechanism fixed by the reframed Open Question OQ-1 SHALL grant
    the Kiro_Web_Principal only the IAM permission stated in Requirement 4 Acceptance
    Criterion 1, such that the Kiro_Web_Credentials confer no AWS permission beyond that
    permission.

### Requirement 4: IAM-Bounded Authorization and Its Accepted Residual Risk

**User Story:** As a platform operator, I want the Kiro Web principal's AWS permission
narrowed to a single action on a single AgentCore Runtime ARN, and I want the tool-level
consequence of that boundary stated plainly, so that the prototype's authorization posture is
honest rather than implied to be finer-grained than it is.

**What this requirement does and does not deliver.** Under Plan A, authorization is enforced
by AWS IAM at the `invoke_agent_runtime` API boundary. IAM evaluates the API call; it does not
read the MCP JSON-RPC payload and therefore cannot observe which MCP tool the payload names.
The consequence, stated in the acceptance criteria below rather than buried in prose, is that
a Kiro_Web session that can call the AgentCore_Runtime_Arn at all can call every MCP_Server
tool, including every mutation tool. Per-tool least privilege is not available under Plan A.

#### Acceptance Criteria

1. THE IAM policy attached to the Kiro_Web_Principal SHALL permit exactly one AWS action,
   `bedrock-agentcore:InvokeAgentRuntime`, on exactly one resource, the single
   AgentCore_Runtime_Arn fixed by Open Question OQ-4, and SHALL permit no other AWS action
   and no other AWS resource.
2. THE IAM policy attached to the Kiro_Web_Principal SHALL be verifiable against the
   synthesized policy document, such that the synthesized document contains exactly one
   `Allow` statement, that statement's action list contains exactly one entry equal to
   `bedrock-agentcore:InvokeAgentRuntime`, that statement's resource list contains exactly
   one entry equal to the AgentCore_Runtime_Arn, and the account identifier, region, and
   runtime identifier segments of that resource entry contain zero wildcard characters.
3. THE IAM permission granted by Acceptance Criterion 1 SHALL grant the Kiro_Web_Principal
   the **complete MCP_Server tool surface, including every member of the
   Mutation_Tool_Set**, because AWS IAM evaluates the `invoke_agent_runtime` API call and
   cannot observe the MCP tool name carried inside the request payload.
4. THE Allowed_Tool_Set for the Kiro_Web_Principal under Plan A SHALL equal the complete
   MCP_Server tool registry designated authoritative by Open Question OQ-5, such that the
   count of tools callable by a Kiro_Web session equals the count of tools in that registry
   and the intersection of the Allowed_Tool_Set with the Mutation_Tool_Set equals the
   Mutation_Tool_Set.
5. **Per-tool least privilege is NOT achievable under Plan A.** THE project SHALL record
   that per-tool authorization for a Kiro_Web session requires the Path_B_Baseline
   scope-enforcement middleware, and THE MDC_Power SHALL implement no mechanism that is
   described as restricting which MCP_Server tools a Kiro_Web session is permitted to
   execute.
6. WHERE the MDC_Power presents a reduced tool list to the Kiro_Web agent, THE MDC_Power
   documentation SHALL describe that reduced list as a client-side convenience filter that a
   caller holding the Kiro_Web_Credentials can bypass, and SHALL NOT describe that reduced
   list as a security control or as an authorization boundary.
7. THE project SHALL record the residual risk stated in Acceptance Criterion 3 and
   Acceptance Criterion 5 as an explicitly accepted, documented prototype risk in the
   Power_Runbook, and THE recorded risk entry SHALL state all four of the following: the
   risk in one sentence, the role that accepted the risk, the Prototype_Status scope under
   which the risk is accepted, and the named migration trigger required by Acceptance
   Criterion 8.
8. THE named migration trigger for retiring the residual risk SHALL be the earlier of the
   first Kiro_Web consumer outside the CAC single-sign-on and project IAM boundary and the
   promotion of the MDC_Power beyond Prototype_Status, and THE recorded migration action
   SHALL be adoption of the Path_B_Baseline Cognito JWT posture with per-scope tool
   enforcement.
9. THE Power_Runbook SHALL enumerate exactly these four compensating controls for the
   residual risk, each with a stated verification method: a named human authenticated
   through government CAC single sign-on holds every Kiro_Web session; AWS CloudTrail
   attributes every `invoke_agent_runtime` call to that human's IAM principal; the IAM policy
   bounds the Kiro_Web_Principal to the single AgentCore_Runtime_Arn required by Acceptance
   Criterion 1; and the MDC_Power is scoped to Prototype_Status use by project members.
10. THE project SHALL enable AWS CloudTrail recording of `bedrock-agentcore`
    `InvokeAgentRuntime` calls in the AWS account and region of the AgentCore_Runtime_Arn,
    such that each recorded event carries the IAM principal identifier of the caller and the
    AgentCore_Runtime_Arn of the invoked runtime.
11. WHEN a Kiro_Web session invokes the Powers_Interface `activate` action for the
    MDC_Power, THE returned documentation SHALL state the Prototype_Status value, SHALL
    state that the granted surface includes every member of the Mutation_Tool_Set, and SHALL
    name the Power_Runbook section that records the accepted residual risk.
12. WHERE a tool in the Allowed_Tool_Set accepts a `tenant_id` parameter, THE
    Powers_Interface `activate` response SHALL show `tenant_id` in that tool's input schema.
13. IF the AWS API denies the `stop_runtime_session` call that the Proxy_Bridge issues during
    session teardown, THEN THE MDC_Power SHALL treat that denial as non-fatal, SHALL complete
    the teardown required by Requirement 2 Acceptance Criterion 11, and SHALL record one log
    entry stating that the AgentCore session persists until the AgentCore idle timeout
    elapses.

### Requirement 5: Tenant Selection Surface for the Agent

**User Story:** As a Kiro Web agent working on a specific `global-workflow` branch, I want to
discover the tenant catalog and declare which tenant I am querying, so that my answers come
from the branch the user is actually working on.

#### Acceptance Criteria

1. THE MDC_Power SHALL expose a tool through which a Kiro_Web session retrieves the
   Tenant_Catalog, and THE Tenant_Catalog response SHALL contain exactly one entry per
   Tenant declared in `mcp_server_python/src/config/tenants.yaml` and no additional
   entries, and each entry SHALL carry all five of the following fields: the Tenant's
   `tenant_id`, the Tenant's `global-workflow` branch name, the Tenant's index prefix, the
   Tenant's label prefix, and the Tenant's lifecycle designation whose value is exactly
   one of `production`, `staging`, or `experimental`.
2. WHERE a Tenant's index prefix or label prefix is the empty string, THE Tenant_Catalog
   entry for that Tenant SHALL present that field as an empty string, and SHALL NOT omit
   the field and SHALL NOT substitute a placeholder value.
3. WHEN a Kiro_Web session invokes the Tenant_Catalog retrieval tool, THE MCP_Server SHALL
   return the Tenant_Catalog response within 5 seconds, and THE retrieval tool SHALL
   require no `tenant_id` argument.
4. THE MDC_Power SHALL forward a caller-supplied `tenant_id` argument to the MCP_Server
   through the Proxy_Bridge character-for-character identical to the value the Kiro_Web
   session supplied, and SHALL NOT apply case folding, whitespace trimming, alias
   substitution, prefix addition, or prefix removal to that value.
5. WHEN a Kiro_Web session invokes a tenant-scoped tool with the `tenant_id` argument
   absent or set to JSON `null`, THE MCP_Server SHALL resolve the request to the default
   Tenant `gw` declared in the defaults section of
   `mcp_server_python/src/config/tenants.yaml`, SHALL execute the request against Tenant
   `gw`, and SHALL state in the response that the default Tenant was applied.
6. IF a Kiro_Web session supplies a `tenant_id` value that is a non-empty string of 1 to
   64 characters and that does not match, by exact case-sensitive string comparison, any
   `tenant_id` in the Tenant_Catalog, THEN THE MCP_Server SHALL return an error response
   naming the supplied `tenant_id` and enumerating the `tenant_id` values present in the
   Tenant_Catalog, SHALL NOT execute the requested query against any Tenant including the
   default Tenant `gw`, and SHALL leave all persistent state and session state unchanged.
7. IF a Kiro_Web session supplies a `tenant_id` argument that is the empty string, that
   consists only of whitespace characters, that exceeds 64 characters, or that is not a
   JSON string, THEN THE MCP_Server SHALL return an error response naming the `tenant_id`
   argument as malformed, SHALL NOT resolve the request to the default Tenant `gw`, and
   SHALL NOT execute the requested query against any Tenant.
8. WHEN the MCP_Server returns a response for a tenant-scoped tool for which a Tenant
   resolved, THE response SHALL state the resolved `tenant_id` and the `global-workflow`
   branch name that the Tenant_Catalog associates with that `tenant_id`, in both success
   responses and error responses produced after Tenant resolution, so that the Kiro_Web
   session can confirm which Tenant answered.
9. IF the MCP_Server cannot read the Tenant_Catalog source file, THEN THE MCP_Server SHALL
   return an error response naming the Tenant_Catalog load failure, SHALL NOT return a
   partial or empty Tenant_Catalog, and SHALL NOT resolve any tenant-scoped request to the
   default Tenant `gw`.
10. THE Steering_Bundle SHALL state that omitting `tenant_id` resolves to the default
    Tenant `gw`, SHALL enumerate every `tenant_id` value in the Tenant_Catalog together
    with its `global-workflow` branch name, SHALL state that `tenant_id` matching is exact
    and case-sensitive, and SHALL instruct the agent to pass `tenant_id` explicitly when
    the user names a non-default branch.
11. WHERE Open Question OQ-7 is resolved in the design document to the effect that a
    session-declared `tenant_id` can be held either by the MDC_Power or by the MCP
    session, THE MDC_Power SHALL apply that declared `tenant_id` to every subsequent
    tenant-scoped call in the same Kiro_Web session for which the caller supplies no
    explicit `tenant_id`, and THE MDC_Power SHALL state the applied `tenant_id` and its
    `global-workflow` branch name in each such response; WHERE Open Question OQ-7 is
    resolved to the effect that neither layer can hold that state, THE design document
    SHALL record this acceptance criterion as withdrawn and tenant declaration SHALL
    reduce to the per-call `tenant_id` argument behavior specified in Acceptance Criteria
    4, 5, 6, and 7.

### Requirement 6: Honest Degradation When a Tenant Index Is Missing or Stale

**User Story:** As a Kiro Web user asking about a branch whose index was never ingested, I
want the Power to tell me the index is empty rather than presenting zero results as ground
truth, so that I do not act on a false negative.

#### Acceptance Criteria

1. THE MDC_Power SHALL expose, as a member of the Allowed_Tool_Set for the
   Kiro_Web_Principal defined in Requirement 4 Acceptance Criterion 4, a tenant-status tool
   through which a Kiro_Web session retrieves in a single response the Tenant_Data_Status of
   every Tenant listed in the Tenant_Catalog, with exactly one Tenant_Data_Status value per
   Tenant_Catalog entry, no Tenant_Catalog entry omitted, and no `tenant_id` repeated; THE
   literal name of that tool SHALL be the name read from the MCP_Server tool source under
   Open Question OQ-5.
2. THE Tenant_Data_Status reported for a Tenant SHALL be exactly one of `populated`,
   `graph-only`, `vector-only`, `empty`, or `probe-error`, and THE five values SHALL be
   mutually exclusive and collectively exhaustive for every Tenant, determined as follows:
   `populated` when the count of graph nodes carrying that Tenant's label prefix is
   greater than zero AND the count of vector documents carrying that Tenant's index prefix
   is greater than zero; `graph-only` when the graph node count is greater than zero AND
   the vector document count equals zero; `vector-only` when the vector document count is
   greater than zero AND the graph node count equals zero; `empty` when both counts equal
   zero; `probe-error` when at least one of the two counts could not be obtained.
3. WHEN a Kiro_Web session invokes a graph-traversal tool for a Tenant whose graph node
   count under that Tenant's label prefix equals zero, THE MCP_Server SHALL return a
   response that sets a dedicated index-coverage field to a value denoting an unpopulated
   graph index and SHALL state the resolved `tenant_id` in that response.
4. WHEN a Kiro_Web session invokes a semantic-search tool for a Tenant whose vector
   document count under that Tenant's index prefix equals zero, THE MCP_Server SHALL
   return a response that sets a dedicated index-coverage field to a value denoting an
   unpopulated vector index and SHALL state the resolved `tenant_id` in that response.
5. WHEN a Kiro_Web session invokes a tenant-scoped read tool for a Tenant whose queried
   index count is greater than zero and the query matches zero results, THE MCP_Server
   SHALL set the same index-coverage field to a value denoting a populated index with zero
   matches, and THAT value SHALL differ, by string comparison, from every value used under
   Acceptance Criteria 3 and 4, so that a caller distinguishes the two conditions without
   parsing prose.
6. IF the MCP_Server cannot determine the index count for the queried Tenant while serving
   a tenant-scoped read tool, THEN THE MCP_Server SHALL set the index-coverage field to a
   value denoting undetermined index coverage, SHALL NOT set that field to a value
   denoting either a populated index or an unpopulated index, and SHALL state in the
   response that the coverage determination failed.
7. IF a Tenant_Data_Status probe raises an error or does not return a count within 10
   seconds for a given Tenant, THEN THE MCP_Server SHALL report that Tenant's
   Tenant_Data_Status as `probe-error`, SHALL NOT report that Tenant as `empty`,
   `populated`, `graph-only`, or `vector-only`, and SHALL still return a
   Tenant_Data_Status value for every remaining Tenant_Catalog entry within a total of 30
   seconds for the tenant-status tool response.
8. THE tenant-status tool response SHALL report, for each Tenant, the completion timestamp
   of the most recent recorded ingestion for that Tenant as a UTC ISO-8601 value with
   second-or-finer precision, SHALL set that value to JSON `null` when no ingestion record
   exists for that Tenant, and THE Tenant_Data_Status enumeration SHALL NOT be extended
   with any staleness value, because no staleness threshold is defined by this spec and
   automatic stale-index classification is deferred to a separate spec.
9. THE Steering_Bundle SHALL instruct the Kiro_Web agent, for any response whose
   index-coverage field denotes an unpopulated index, to report the outcome as an
   index-coverage gap for the named Tenant rather than as an absence of the queried
   artifact; to state the resolved `tenant_id` and its `global-workflow` branch name
   whenever it reports an empty or zero-match result; to report a Tenant_Data_Status of
   `probe-error` or an undetermined index-coverage field as unknown coverage rather than
   as `empty`; and to state the ingestion completion timestamp from Acceptance Criterion
   8, or its absence, whenever the user asks whether an answer is current.
10. THE Steering_Bundle SHALL state that graph-traversal results for Tenants other than
    `gw` may return fewer relationships than exist in the corresponding branch while the
    relationship ingestion described in
    `.kiro/steering/09-agentcore-mcp-for-global-workflow.md` remains incomplete, and SHALL
    instruct the Kiro_Web agent to state that limitation when it reports a graph-traversal
    result for a Tenant whose `tenant_id` is not `gw`.

### Requirement 7: Preservation of Existing Invariants

**User Story:** As an AWS developer using Kiro on the EC2 workstation, I want the new Power to
change nothing about my existing path or about the data stores' network posture, so that
adding a browser consumer introduces no regression.

**Why the Proxy_Bridge freeze is a dependency, not an avoidance.** Under Plan A the MDC_Power
executes `tools/agentcore-kiro-proxy.py` itself, as required by Requirement 2 Acceptance
Criterion 3. The freeze in Acceptance Criterion 1 therefore protects a file this feature
depends on, and a divergent copy would silently split the AgentCore call path into two
implementations.

#### Acceptance Criteria

1. THE `tools/agentcore-kiro-proxy.py` file SHALL remain byte-for-byte identical to its
   content at the baseline commit recorded under Acceptance Criterion 8, because the
   MDC_Power depends on that file unmodified under Requirement 2 Acceptance Criterion 3,
   where identity is evidenced by a file-content comparison that reports a differing-byte
   count of exactly 0 and a file-size difference of exactly 0 bytes, and THE comparison SHALL
   be executed and its result recorded once before this feature's changes are merged and once
   after this feature's CDK stack is deployed.
2. THE MDC_Power SHALL contain no forked, vendored, patched, inlined, or rewritten copy of
   the Proxy_Bridge, and THE repository SHALL contain exactly one Proxy_Bridge source file, as
   required by Requirement 2 Acceptance Criterion 4, evidenced by a repository-wide search
   that returns exactly one path whose content matches the Proxy_Bridge and by a review record
   confirming that this feature's change set modifies zero lines of that file.
3. THE `.kiro/settings/mcp.json` file SHALL remain byte-for-byte identical to its content
   at the baseline commit recorded under Acceptance Criterion 8, evidenced by a
   file-content comparison reporting a differing-byte count of exactly 0, and THE freeze
   SHALL apply irrespective of whether that file's existing stdio server entry is current
   or stale, a question reserved to Open Question OQ-6 and out of scope for this spec; THE
   stdio server entry in that file SHALL remain the EC2 developer workstation wiring, and THE
   MDC_Power SHALL read no configuration value from that file.
4. WHILE the MDC_Power is installed and activated in at least one Kiro_Web session, THE
   AgentCore_Runtime SHALL continue to accept IAM SigV4 `invoke_agent_runtime` calls from the
   Developer_Principal, evidenced by at least one invocation of a read-oriented tool issued
   from the EC2 developer workstation through the unmodified `tools/agentcore-kiro-proxy.py`
   returning a non-error MCP response within 60 seconds of the invocation being issued.
5. THE Neptune cluster and the OpenSearch domain SHALL remain reachable only from inside
   VPC `vpc-055f30ffa3d661e6b` after this feature is implemented, evidenced by a
   post-deployment negative test in which a TCP connection attempt from a host outside
   that VPC to the configured Neptune endpoint port and a TCP connection attempt from that
   same host to the configured OpenSearch endpoint port each reach no established TCP
   state within 10 seconds per attempt.
6. THE MDC_Power SHALL require no change to the MCP_Server's tool implementations, tool
   names, tool input schemas, or tool output formats, evidenced by a comparison of the
   MCP_Server tool registry enumeration recorded at the baseline commit against the
   enumeration recorded after this feature is deployed, in which the set of tool names,
   the set of input-schema parameter names per tool, and the declared output format per
   tool are equal with 0 additions, 0 removals, and 0 modifications.
7. IF any verification required by Acceptance Criteria 1 through 6 reports a non-zero
   difference, more than one Proxy_Bridge copy, or a connection that reaches established TCP
   state, THEN THE project SHALL report a regression failure naming the file, resource, or
   principal class affected and the specific differing item, SHALL NOT mark this feature's
   implementation complete, SHALL NOT promote this feature's deployment beyond the
   environment in which the failure was observed, and SHALL leave the pre-existing
   Developer_Principal configuration in place unmodified.
8. THE design document SHALL record the baseline commit identifier that fixes the content
   of the two files named in Acceptance Criteria 1 and 3 and the baseline MCP_Server tool
   registry enumeration used by Acceptance Criterion 6, and SHALL record that identifier
   before the first implementation task for this spec begins.
9. WHEN a Kiro_Web_Principal request and a Developer_Principal request are in flight against
   the AgentCore_Runtime at the same time, THE MCP_Server SHALL return one response to each
   caller in which the resolved `tenant_id` equals the `tenant_id` resolved for that caller's
   own request, so that neither request alters the other's resolved Tenant or result.

### Requirement 8: Auditability and Attribution for Kiro Web Invocations

**User Story:** As a platform operator investigating an incident, I want every Kiro Web tool
invocation attributable to a named IAM principal and a single Kiro Web session, so that I can
trace an action back to the human who took it.

**What attribution rests on under Plan A.** Plan A presents no access token, so attribution
anchors on three values: the IAM principal identifier that AWS CloudTrail records for each
`InvokeAgentRuntime` call under Requirement 4 Acceptance Criterion 10, the Runtime_Session_Id
that the Proxy_Bridge sends on every call under Requirement 2 Acceptance Criterion 9, and the
Kiro_Web_Session_Id that the MDC_Power generates for the session. The CloudTrail record carries
the principal; the Audit_Log carries the tool, the tenant, and the outcome; the two session
identifiers join them.

#### Acceptance Criteria

1. WHEN the MCP_Server receives a tool invocation request originating from a Kiro_Web
   session, THE MCP_Server SHALL write exactly one Audit_Log entry for that request to
   CloudWatch Logs, and SHALL emit that Audit_Log entry before returning the response to the
   caller except under the timeout condition of Acceptance Criterion 11.
2. THE Audit_Log entry for a Kiro_Web_Principal invocation SHALL contain all of the
   following fields, each field present in every entry: the caller identity the MCP_Server
   observes for that invocation, as a non-empty string of at most 256 characters; a
   consumer-class value that is a fixed literal string identifying the caller as Kiro_Web and
   that differs from the consumer-class literal used by the Developer_Principal workstation
   path; the invoked tool name, as a non-empty string of at most 128 characters; the
   invocation timestamp, as a UTC ISO-8601 string with exactly 3 fractional-second digits and
   a trailing `Z` designator; the MCP request identifier, as a non-empty string of at most
   128 characters; the Runtime_Session_Id, as a string of at least 33 and at most 128
   characters; the Kiro_Web_Session_Id, as a non-empty string of at most 128 characters; the
   resolved `tenant_id` determined under Requirement 5, as a non-empty string of at most 64
   characters; and an outcome value that is exactly one of `success`, `invalid_request`, or
   `execution_error`.
3. THE Audit_Log entry SHALL be serialized as a single UTF-8 JSON object occupying exactly
   one line, terminated by exactly one newline character, containing no unescaped newline
   or carriage-return characters in any field value, and occupying at most 4096 bytes; and
   IF a string field value exceeds its length bound stated in Acceptance Criterion 2, THEN
   THE MCP_Server SHALL truncate that value to its bound and SHALL mark the value as
   truncated.
4. THE Audit_Log entry SHALL contain no AWS access key identifier, no AWS secret access
   key, no AWS session token, no contiguous substring longer than 8 characters of the secret
   access key or of the session token of the Kiro_Web_Credentials, no tool input argument
   name, no tool input argument value, and no tool output payload.
5. WHEN the MDC_Power sends an MCP tool invocation to the MCP_Server through the
   Proxy_Bridge, THE MDC_Power SHALL attach as Request_Metadata both of the following: the
   Kiro_Web_Session_Id, as a non-empty string of at most 128 characters that is identical
   across every call in one Kiro_Web session and distinct across concurrent Kiro_Web
   sessions; and the consumer-class literal required by Acceptance Criterion 2.
6. THE Audit_Log entry for a Kiro_Web_Principal invocation SHALL record each of the two
   Request_Metadata values named in Acceptance Criterion 5 in its own dedicated field, and
   IF a Request_Metadata value is absent from the received request, THEN THE MCP_Server
   SHALL set that field to explicit JSON `null` and SHALL NOT omit the field, SHALL NOT
   substitute an empty string, and SHALL NOT substitute a placeholder value.
7. WHEN an operator joins the CloudTrail `InvokeAgentRuntime` events recorded under
   Requirement 4 Acceptance Criterion 10 to the Audit_Log entries written under Acceptance
   Criterion 1, THE join SHALL resolve every Audit_Log entry of one Kiro_Web session to
   exactly one IAM principal identifier, SHALL use only the Runtime_Session_Id and the
   Kiro_Web_Session_Id as join inputs, SHALL require no AWS credential material as join
   input, and THE Runtime_Session_Id value SHALL be byte-identical in the CloudTrail event
   and in the Audit_Log entry.
8. THE design document SHALL name the CloudTrail event field that carries the
   Runtime_Session_Id for an `InvokeAgentRuntime` call, and IF CloudTrail records no field
   carrying the Runtime_Session_Id, THEN THE design document SHALL record the substitute join
   inputs as the AgentCore_Runtime_Arn, the CloudTrail event time, and the Audit_Log entry
   timestamp within a stated tolerance window of at most 5 seconds, and THE substitute join
   SHALL still resolve every Audit_Log entry of one Kiro_Web session to exactly one IAM
   principal identifier.
9. THE Kiro_Web attribution design SHALL NOT use an Amazon Cognito Pre-Token-Generation
   trigger and SHALL NOT rely on any custom claim injected into any access token, consistent
   with Path_B_Baseline Requirement 13, and THIS constraint SHALL bind the migration to the
   Path B Cognito JWT posture named in Requirement 10 Acceptance Criterion 4, such that
   attribution after that migration is derived only from standard JWT claims validated by the
   AgentCore_Runtime and from Request_Metadata.
10. THE outcome value recorded in the Audit_Log entry SHALL be determined as follows:
    `success` IF the invoked tool executed and returned a non-error MCP result;
    `invalid_request` IF the MCP_Server rejected the request without executing the tool,
    including the tenant-resolution rejections required by Requirement 5 Acceptance Criterion
    6 and Requirement 5 Acceptance Criterion 7; and `execution_error` IF the invoked tool
    executed and did not return a non-error MCP result.
11. IF the MCP_Server has not confirmed the Audit_Log entry write within 2 seconds of
    initiating that write, THEN THE MCP_Server SHALL return the tool invocation response
    to the caller unchanged, SHALL emit one separate error log entry containing the MCP
    request identifier and a description of the logging failure category, and SHALL NOT
    retry the Audit_Log write for that request more than once.
12. WHEN the MCP_Server receives more than one request carrying the same MCP request
    identifier, including retries issued under Requirement 2 Acceptance Criterion 9,
    Requirement 3 Acceptance Criterion 12, or Requirement 9 Acceptance Criterion 5, THE
    MCP_Server SHALL write exactly one Audit_Log entry per received request, and each such
    entry SHALL be distinguishable from the others by its timestamp field.

### Requirement 9: Graceful Failure and Diagnostics

**User Story:** As a Kiro Web user whose call just failed, I want an actionable message that
names the failing stage, so that I can tell an outage apart from a permissions problem or an
expired credential without reading the design document.

**Reconciliation of the failing-stage vocabulary.** Acceptance Criterion 9 defines exactly
seven failing stages, and those seven are the only values any MDC_Power error names as a
stage. The finer-grained labels that Requirement 2 and Requirement 3 attach to specific
failures — `dependency-provisioning`, `credentials-absent`, `credential-expiry`,
`dns-resolution`, `tcp-connection`, `tls-handshake`, `request-timeout`, and
`stream-idle-timeout` — are failure categories reported in a separate field beside the stage,
and Acceptance Criterion 10 records the mapping from each category to its stage.

#### Acceptance Criteria

1. IF the MDC_Power cannot launch the Proxy_Bridge child process, IF that process exits
   before the MCP initialize handshake completes, or IF the `boto3` import check fails after
   the single installation attempt permitted by Requirement 2 Acceptance Criterion 6, THEN
   THE MDC_Power SHALL return an error to the Kiro_Web session that names the failing stage
   `proxy-launch`, names the Proxy_Bridge path, and names the failure category as exactly one
   of `dependency-provisioning`, `interpreter-missing`, `script-missing`, or `process-exit`,
   and SHALL send no `invoke_agent_runtime` call.
2. IF the Proxy_Bridge cannot resolve the `bedrock-agentcore` regional service endpoint
   hostname, cannot establish a TCP session to that endpoint, or cannot complete the TLS
   handshake required by Requirement 2 Acceptance Criterion 12, THEN THE MDC_Power SHALL
   return an error to the Kiro_Web session that names the failing stage `endpoint-invocation`,
   names the hostname contacted, and names the failure category as exactly one of
   `dns-resolution`, `tcp-connection`, or `tls-handshake`, and SHALL NOT return an MCP tool
   result.
3. IF a connection attempt fails as described in Acceptance Criterion 2, THEN THE
   MDC_Power SHALL make at most 3 total connection attempts for that MCP request, SHALL
   wait at least 1 second and at most 4 seconds before each subsequent attempt, and SHALL
   NOT exceed 15 seconds of cumulative wall-clock time across all connection attempts for
   that request.
4. IF an `invoke_agent_runtime` call fails with an AWS authorization error, including
   `AccessDeniedException`, THEN THE MDC_Power SHALL return an error to the Kiro_Web session
   that names the failing stage `authorization`, names the invoked tool, names the
   AgentCore_Runtime_Arn targeted, and states that the IAM policy of the Kiro_Web_Principal
   does not permit `bedrock-agentcore:InvokeAgentRuntime` on that resource, and SHALL NOT
   retry the request and SHALL NOT obtain replacement Kiro_Web_Credentials.
5. IF an `invoke_agent_runtime` call fails with an AWS throttling error or an AWS service
   error, THEN THE MDC_Power SHALL send the request at most 4 times in total, comprising the
   initial attempt and at most 3 retries, SHALL wait at least 1 second before the first
   retry, SHALL make each subsequent delay at least twice the immediately preceding delay,
   and SHALL NOT exceed 10 seconds of cumulative delay across all retries of that request.
6. IF every attempt permitted by Acceptance Criterion 5 fails, THEN THE MDC_Power SHALL
   return an error to the Kiro_Web session that names the failing stage `tool-execution`, the
   last observed AWS error code, the invoked tool, and the number of attempts made, and SHALL
   NOT send that request again.
7. IF a single `invoke_agent_runtime` attempt has not yielded a complete MCP JSON-RPC
   response within 60 seconds measured from the transmission of the first byte of that
   request, or IF no event-stream frame has been received for 30 consecutive seconds while
   the Proxy_Bridge is reassembling a `text/event-stream` response under Requirement 2
   Acceptance Criterion 8, THEN THE MDC_Power SHALL abandon that request attempt and SHALL
   return a timeout error that names the failing stage `tool-execution`, the invoked tool,
   the elapsed time in whole seconds, and the failure category as exactly one of
   `request-timeout` or `stream-idle-timeout`.
8. IF the reassembled response cannot be parsed as an MCP JSON-RPC object or carries a
   JSON-RPC `id` value not matching the `id` of any outstanding request, THEN THE MDC_Power
   SHALL return an MCP error response that names the failing stage `response-parsing`, the
   invoked tool, and the parse or correlation failure, and SHALL NOT retry that request.
9. WHEN the MDC_Power returns any error to the Kiro_Web session, THE error message SHALL
   name exactly one failing stage, selected from `power-activation`, `credential-resolution`,
   `proxy-launch`, `endpoint-invocation`, `authorization`, `tool-execution`, and
   `response-parsing`, SHALL name no second value from that set, and SHALL contain no AWS
   access key identifier and no contiguous substring longer than 8 characters of the secret
   access key or of the session token of the Kiro_Web_Credentials.
10. THE MDC_Power SHALL assign the failing stage named in Acceptance Criterion 9 by applying
    the first matching rule in the following order, so that the seven stage values are
    exhaustive over every failure mode described anywhere in this document and mutually
    exclusive for any single failure: (a) `power-activation` when the Powers_Interface
    `activate` action fails because a configurable value required by Requirement 1 Acceptance
    Criterion 10 or by Requirement 2 Acceptance Criterion 14 is absent or invalid; (b)
    `credential-resolution` when the AWS credential chain resolves no usable
    Kiro_Web_Credentials under Requirement 3 Acceptance Criterion 9, when an
    `invoke_agent_runtime` call fails with an expired-or-invalid credential error under
    Requirement 3 Acceptance Criterion 10, or when the single resend permitted by Requirement
    3 Acceptance Criterion 12 fails for the same reason; (c) `proxy-launch` when the
    Proxy_Bridge process could not be launched or sustained, including the `boto3`
    provisioning failure of Requirement 2 Acceptance Criterion 7; (d) `endpoint-invocation`
    when no AWS API response was received for the request, including the TLS failure of
    Requirement 2 Acceptance Criterion 13; (e) `authorization` when the AWS API returned an
    authorization error for `invoke_agent_runtime`; (f) `response-parsing` when a response
    was received but could not be parsed or correlated as described in Acceptance Criterion 8
    or Requirement 2 Acceptance Criterion 15; (g) `tool-execution` for every other failure,
    including the retry exhaustion of Acceptance Criterion 6, the timeout conditions of
    Acceptance Criterion 7, the ceiling of Acceptance Criterion 12, and an MCP error result
    returned by the MCP_Server; and THE MDC_Power SHALL report the failure category named in
    Acceptance Criteria 1, 2, and 7 and in Requirement 2 Acceptance Criteria 7 and 13 and
    Requirement 3 Acceptance Criteria 9 and 10 in a field separate from the stage field, and
    SHALL NOT report a failure category as a stage value.
11. WHEN the MDC_Power returns an error whose failing stage is `credential-resolution`,
    `endpoint-invocation`, `authorization`, `tool-execution`, or `response-parsing`, THE
    MDC_Power SHALL accept the next Powers_Interface `use` invocation in the same Kiro_Web
    session without a further Powers_Interface `activate` action and SHALL retain the
    Runtime_Session_Id held under Requirement 2 Acceptance Criterion 9; and WHEN the
    MDC_Power returns an error whose failing stage is `power-activation` or `proxy-launch`,
    THE MDC_Power SHALL require a further Powers_Interface `activate` action before it serves
    another Powers_Interface `use` invocation and SHALL state that requirement in the error.
12. IF the cumulative wall-clock time of a single Powers_Interface `use` invocation,
    counted across credential resolution, Proxy_Bridge launch, connection attempts, retry
    delays, and response reassembly, reaches 120 seconds, THEN THE MDC_Power SHALL abandon
    all remaining attempts for that invocation and SHALL return a timeout error that names
    the failing stage `tool-execution`, the invoked tool, and the cumulative elapsed time in
    whole seconds.
13. WHEN a Kiro_Web session invokes the diagnostic action that the MDC_Power exposes, THE
    MDC_Power SHALL return exactly the following fields: the configured AgentCore_Runtime_Arn;
    the configured AWS region; a boolean stating whether Kiro_Web_Credentials are currently
    resolved; the remaining lifetime of those Kiro_Web_Credentials as a whole number of
    seconds, or JSON `null` when no Kiro_Web_Credentials are resolved; a boolean stating
    whether a Runtime_Session_Id is currently held; a boolean stating whether `boto3` is
    importable by the Python interpreter that launches the Proxy_Bridge; the outcome of a
    single MCP health call issued against the read tool designated for that purpose in the
    design document, as exactly one of `success` or `failure`; the elapsed time of that
    health call in whole milliseconds; and, when that outcome is `failure`, the failing stage
    assigned by Acceptance Criterion 10.
14. WHEN the MDC_Power returns the diagnostic action result, THE MDC_Power SHALL exclude
    the AWS access key identifier, the secret access key, the session token, and every
    contiguous substring longer than 8 characters of the secret access key or of the session
    token of the Kiro_Web_Credentials from that result.
15. IF the diagnostic action health call has not completed within 60 seconds, THEN THE
    MDC_Power SHALL report the health-call outcome as `failure` with the failing stage
    `tool-execution` and SHALL still return every other field required by Acceptance
    Criterion 13.
16. IF the Powers_Interface `activate` action for the MDC_Power fails, THEN THE returned
    error SHALL name the failing stage assigned by Acceptance Criterion 10, which for an
    activation failure is exactly one of `power-activation`, `credential-resolution`, or
    `proxy-launch`, SHALL name the absent configuration value or the failing dependency, and
    SHALL state that no MDC_Power tool is available to the Kiro_Web session until that
    failure is resolved.

### Requirement 10: Prototype Status, Path B Coupling, and the Migration Path

**User Story:** As a delivery lead, I want this spec's delivery decoupled from the unstarted
Path B work while its prototype status and its production migration path are recorded, so that
Kiro Web ships now and its authorization gap is retired on a planned trigger rather than
forgotten.

#### Acceptance Criteria

1. THE delivery of this spec SHALL depend on zero Path_B_Baseline tasks, such that the
   project can start and complete every implementation task of this spec while the count of
   completed Path_B_Baseline task groups is zero, and THE design document SHALL record the
   resolution of the retired Open Question OQ-2 as `no-delivery-dependency`.
2. THE Prototype_Status value `prototype` SHALL appear in the Power_Manifest description
   required by Requirement 1 Acceptance Criterion 1, in the Powers_Interface `activate`
   output required by Requirement 4 Acceptance Criterion 11, and in the Power_Runbook
   required by Requirement 11 Acceptance Criterion 2, spelled character-for-character
   identically in all three places.
3. THE project SHALL record the residual per-tool-authorization gap stated in Requirement 4
   Acceptance Criterion 3 and Requirement 4 Acceptance Criterion 5, together with the named
   migration trigger of Requirement 4 Acceptance Criterion 8, in both the design document and
   the Power_Runbook, and THE two records SHALL state the same migration trigger.
4. THE design document SHALL record the migration path from Plan A to the Path_B_Baseline
   Amazon Cognito JWT posture with per-scope tool enforcement, and SHALL enumerate, by
   requirement number and criterion number, every acceptance criterion of this spec whose
   wording changes on that migration, covering at minimum the transport criteria of
   Requirement 2, the credential criteria of Requirement 3, the authorization criteria of
   Requirement 4, the attribution criteria of Requirement 8, the failing-stage criteria of
   Requirement 9, the documentation criteria of Requirement 11, and the egress criteria of
   Requirement 12.
5. THIS spec SHALL provision no Amazon Cognito user pool, no Cognito resource server, no
   Cognito app client, no JWT authorizer, no Token_Broker, no GitHub OIDC federated IAM role,
   no AgentCore Gateway, and no Cedar policy, verified by a synthesis of every CDK stack this
   spec introduces reporting zero resources of those types.
6. THE tasks document for this spec SHALL contain no task that provisions or configures an
   AgentCore Gateway, that authors, reviews, or deploys a Cedar policy, or that routes MCP
   tool invocations through an AgentCore Gateway, because that work is deferred by
   Path_B_Baseline Requirement 11.
7. PATH_B_BASELINE SHALL retain sole ownership of the GitHub Actions CI consumer class and
   of the RDHPCS/HPC login-node consumer class, and no acceptance criterion of this spec SHALL
   depend on Path_B_Baseline Task 3, Task 4, Task 7, or Task 8.
8. THIS spec and Path_B_Baseline SHALL stay coupled through the single shared
   AgentCore_Runtime_Arn fixed by Open Question OQ-4, such that a text comparison of the
   AgentCore_Runtime_Arn value recorded in this spec's design document against the value
   recorded in Path_B_Baseline reports equality.
9. WHEN the AgentCore_Runtime_Arn value changes in either this spec or Path_B_Baseline, THE
   same change set SHALL update the recorded value in the other spec, so that the equality
   required by Acceptance Criterion 8 holds after every such change.
10. THE tasks document for this spec SHALL contain no task whose stated work is already the
    stated work of a Path_B_Baseline task, and WHERE a task of this spec references a
    Path_B_Baseline task, THE tasks document SHALL reference it by the Path_B_Baseline spec
    name followed by that task's identifier and SHALL NOT restate the steps of that task.

### Requirement 11: Documentation

**User Story:** As a new Kiro Web user, I want one onboarding document for the Power, so that I
can obtain credentials, install the Power, and run a first query without reading the design,
and so that I learn the prototype's authorization limits before I use it.

#### Acceptance Criteria

1. THE project SHALL publish a Power_Runbook at `docs/runbooks/kiro-web-mcp-power.md`
   whose top-level heading is followed by exactly the seven sections `Prototype Status and
   Accepted Risk`, `Prerequisites`, `Installation and Activation`, `First Query`, `Tenant
   Selection`, `Tool Surface`, and `Troubleshooting`, spelled as written, appearing in that
   order, each rendered as a second-level markdown heading, with no additional second-level
   heading placed between them.
2. THE Power_Runbook `Prototype Status and Accepted Risk` section SHALL state the
   Prototype_Status value `prototype`, SHALL state that the granted surface includes every
   member of the Mutation_Tool_Set as required by Requirement 4 Acceptance Criterion 3, SHALL
   state that per-tool authorization is not enforced as required by Requirement 4 Acceptance
   Criterion 5, SHALL enumerate the four compensating controls required by Requirement 4
   Acceptance Criterion 9 each with its stated verification method, and SHALL state the
   migration trigger and migration action required by Requirement 4 Acceptance Criterion 8.
3. THE Power_Runbook `Prerequisites` section SHALL enumerate the steps by which a Kiro_Web
   user obtains Kiro_Web_Credentials under the credential-delivery mechanism fixed by the
   reframed Open Question OQ-1, naming each command the user runs verbatim; SHALL state the
   `boto3` availability requirement of Requirement 2 Acceptance Criterion 5 including the
   minimum version `1.34.0`; SHALL enumerate every configuration value the MDC_Power reads
   under Requirement 1 Acceptance Criterion 10, including the AgentCore_Runtime_Arn and the
   AWS region, by its configuration name; SHALL state for each configuration value whether
   the MDC_Power fails activation when that value is absent; and SHALL contain no AWS access
   key identifier, no AWS secret access key, and no AWS session token value.
4. THE Power_Runbook `First Query` section SHALL contain exactly one Powers_Interface `use`
   invocation that names the MDC_Power MCP server name declared in the Power_Manifest,
   names one tool that Acceptance Criterion 6 enumerates, and supplies a literal
   `tenant_id` value drawn from the Tenant_Catalog, and that invocation SHALL contain no
   placeholder, ellipsis, angle-bracketed substitution marker, or bracketed substitution
   marker requiring the reader to supply a value.
5. WHEN a reader issues the First Query invocation required by Acceptance Criterion 4
   verbatim in a Kiro_Web session in which every item listed in the Power_Runbook
   `Prerequisites` section is satisfied, THE MDC_Power SHALL return a non-error MCP_Server
   response that states the resolved `tenant_id`.
6. THE Power_Runbook `Tool Surface` section SHALL enumerate by name every member of the
   Allowed_Tool_Set for the Kiro_Web_Principal defined in Requirement 4 Acceptance Criterion
   4, which is the complete MCP_Server tool registry, SHALL match the enumeration returned by
   the Powers_Interface `activate` action required by Requirement 1 Acceptance Criterion 3
   name-for-name, SHALL mark each listed tool as either accepting or not accepting a
   `tenant_id` parameter, SHALL state that the MDC_Power enforces no per-tool restriction, and
   SHALL state that any reduced list the MDC_Power presents is a client-side convenience
   filter that a caller holding the Kiro_Web_Credentials can bypass, as required by
   Requirement 4 Acceptance Criterion 6.
7. THE Power_Runbook `Tenant Selection` section SHALL enumerate every `tenant_id` value in
   the Tenant_Catalog together with the corresponding `global-workflow` branch name, SHALL
   state that omitting `tenant_id` resolves to the default Tenant `gw`, SHALL name the
   tool through which a Kiro_Web session reads Tenant_Data_Status, and SHALL list the five
   Tenant_Data_Status values `populated`, `graph-only`, `vector-only`, `empty`, and
   `probe-error`.
8. THE Power_Runbook `Troubleshooting` section SHALL document, for each of the seven
   failing-stage values enumerated in Requirement 9 Acceptance Criterion 9, the observable
   symptom a Kiro_Web session sees, at least one probable cause, and at least one corrective
   action the reader can perform, and SHALL document as named entries within that coverage
   the absent-credential condition of Requirement 3 Acceptance Criterion 9, the
   credential-expiry condition of Requirement 3 Acceptance Criterion 10, the absent or
   outdated `boto3` condition of Requirement 2 Acceptance Criterion 7, the AWS authorization
   denial of Requirement 9 Acceptance Criterion 4, and the `dns-resolution`,
   `tcp-connection`, and `tls-handshake` failure categories of Requirement 9 Acceptance
   Criterion 2.
9. THE Power_Runbook SHALL include, within the `Prerequisites` section or after the
   `Troubleshooting` section, a passage that names the Developer_Principal SigV4 path, states
   that developers on the EC2 workstation continue to use `.kiro/settings/mcp.json` rather
   than the MDC_Power, states that the MDC_Power launches the same unmodified
   `tools/agentcore-kiro-proxy.py` bridge, and states that the MDC_Power reads its
   AgentCore_Runtime_Arn and region from Power configuration rather than from
   `.kiro/settings/mcp.json`.
10. THE Power_Runbook SHALL state the minimum and maximum Kiro_Web_Credentials lifetime as
    integer values with the explicit unit `seconds`, matching the bound required by
    Requirement 3 Acceptance Criterion 3, SHALL state that a Kiro_Web session observes a
    credential-expiry warning naming the remaining lifetime when that lifetime falls below
    900 seconds as required by Requirement 3 Acceptance Criterion 4, and SHALL state that a
    Kiro_Web session whose Kiro_Web_Credentials expire mid-session observes an error naming
    the `credential-resolution` stage together with the credential-refresh command, as
    required by Requirement 3 Acceptance Criterion 10 and Requirement 3 Acceptance Criterion
    11.
11. THE project SHALL publish or update a steering file containing a summary of the
    Kiro_Web access path that is at most 150 whitespace-delimited words and that includes
    at least one markdown link whose target is the Power_Runbook path stated in Acceptance
    Criterion 1.
12. THE Power_Runbook SHALL record the reconciled MCP_Server tool count resolved by Open
    Question OQ-5 as a single integer, SHALL cite the source file or files under
    `mcp_server_python/src/tools/` from which that count was read, and SHALL NOT cite
    `README.md`, `.kiro/specs/mcp-external-access-revised/`, or
    `.kiro/steering/10-agentcore-mcp-tool-guide.md` as the authority for that count.
13. IF the MCP_Server tool registry gains or loses a tool name, THEN THE project SHALL
    update the Power_Runbook `Tool Surface` section in the same change set that alters the
    registry, so that the enumeration required by Acceptance Criterion 6 remains
    name-for-name identical to the registry.

### Requirement 12: Security and Data Handling for a Browser-Originated Session

**User Story:** As a security engineer, I want the browser-originated path held to a stated
data-handling posture whose limits are recorded honestly, so that adding a browser consumer
does not widen the blast radius and so that no control is claimed that the implementation does
not enforce.

#### Acceptance Criteria

1. THE MDC_Power SHALL restrict its network egress to an allowlist whose members are
   exactly the following and no other hostname: the `bedrock-agentcore` regional service
   endpoint hostname for the region of the AgentCore_Runtime_Arn; the `sts` regional service
   endpoint hostname for that region; every hostname required by the credential-delivery
   mechanism fixed by the reframed Open Question OQ-1; and, WHERE `boto3` is provisioned at
   session time under Requirement 2 Acceptance Criterion 6, the package index hostname from
   which that installation downloads; such that a capture of every outbound connection the
   MDC_Power opens during a Kiro_Web session contains no destination hostname absent from
   that allowlist.
2. THE design document SHALL enumerate explicitly, for the credential-delivery mechanism
   selected under the reframed Open Question OQ-1, every hostname the allowlist of Acceptance
   Criterion 1 contains, and SHALL state for each hostname which of the four categories in
   Acceptance Criterion 1 admits it.
3. WHEN the MDC_Power constructs the body of an MCP request, THE MDC_Power SHALL populate
   that body from only the MCP JSON-RPC `method` and `params` values supplied by the
   Kiro_Web session, such that byte-wise comparison of the request body against the
   caller-supplied arguments yields no additional file content.
4. WHILE a Kiro_Web session is active, THE MDC_Power SHALL NOT open, read, or transmit any
   file under the Kiro_Web sandbox repository working tree for the purpose of constructing
   an MCP request, and repository file content SHALL reach the MCP_Server only as the
   literal value of a tool argument the Kiro_Web session supplied.
5. THE Kiro_Web sandbox filesystem, the repository working tree, and the Power configuration
   values returned by the Powers_Interface `configure` action SHALL contain zero occurrences
   of the secret access key of the Kiro_Web_Credentials, zero occurrences of the session token
   of the Kiro_Web_Credentials, and zero occurrences of any contiguous substring longer than 8
   characters of either, verified by a text search of those three locations that reports zero
   matches.
6. THE Kiro_Web sandbox SHALL have no direct network path to the Neptune cluster or the
   OpenSearch domain, such that a connection attempt from the Kiro_Web sandbox to the
   configured Neptune endpoint port and a connection attempt from the Kiro_Web sandbox to
   the configured OpenSearch domain endpoint port each establish no TCP session within 10
   seconds, and all Neptune and OpenSearch access for a Kiro_Web_Principal request SHALL
   occur inside the AgentCore_Runtime.
7. WHERE this feature introduces a Secrets Manager secret, a KMS key, a CloudWatch log
   group, or any other data-bearing resource, THE corresponding CDK construct SHALL set
   `removalPolicy: cdk.RemovalPolicy.RETAIN`, and THE CDK test suite for this feature
   SHALL assert `DeletionPolicy: Retain` on every such resource in the synthesized
   CloudFormation template, per `.kiro/steering/05-cdk-data-safety.md` Rules 1 and 2.
8. THE AWS resources introduced by this feature SHALL be defined in CDK under
   `infrastructure/cdk/`, and no AWS resource supporting this feature SHALL be created or
   modified outside CDK, verified by a CDK diff of this feature's stack executed after
   deployment reporting zero resource differences.
9. WHEN a deployment of this feature's CDK stack is proposed, THE deployment procedure
   SHALL produce a CDK diff or CloudFormation change set for that stack and SHALL require
   that the diff or change set list no deletion and no replacement of the Neptune cluster,
   the OpenSearch domain, any S3 bucket, or the EFS file system before the deployment
   proceeds, per `.kiro/steering/05-cdk-data-safety.md` Rule 4.
10. IF a CDK diff or change set for this feature's stack lists a deletion or a replacement
    of the Neptune cluster, the OpenSearch domain, any S3 bucket, or the EFS file system,
    THEN THE deployment SHALL NOT be executed, and THE condition SHALL be recorded with
    the affected resource logical identifier and resource type.
11. WHEN a deployment of this feature's CDK stack completes, THE Neptune cluster
    identifier, the OpenSearch domain endpoint, the S3 bucket names, and the EFS file
    system identifier SHALL each equal the value recorded before that deployment, and THE
    Neptune node count and relationship count SHALL be greater than or equal to their
    pre-deployment values.
12. THE project SHALL record that every member of the Mutation_Tool_Set is reachable by a
    Kiro_Web session under the IAM permission of Requirement 4 Acceptance Criterion 1, SHALL
    state no control that prevents that reachability, and SHALL rely on exactly the four
    compensating controls enumerated in Requirement 4 Acceptance Criterion 9, each verifiable
    by the method stated in Acceptance Criterion 13.
13. THE verification method for each compensating control named in Acceptance Criterion 12
    SHALL be exactly as follows: for the named-human control, a record showing that access to
    the Kiro_Web session requires government CAC single sign-on into the project AWS account;
    for the attribution control, retrieval of the CloudTrail `InvokeAgentRuntime` event
    carrying the IAM principal identifier for one test invocation, per Requirement 4
    Acceptance Criterion 10; for the IAM-boundary control, the synthesized-policy assertion
    required by Requirement 4 Acceptance Criterion 2; and for the prototype-scope control, the
    presence of the Prototype_Status value in all three locations required by Requirement 10
    Acceptance Criterion 2.

## Correctness Properties (for Property-Based Testing)

These properties are candidates for property-based tests written during implementation. They
are cross-referenced from the acceptance criteria above and are not acceptance criteria
themselves. Each is intended to be implemented as a single property-based test running at
least 100 iterations.

- **P1 — SSE reassembly round-trip fidelity.** For any valid MCP JSON-RPC request object and
  any partitioning of the corresponding response into `text/event-stream` frames, the object
  the MDC_Power writes to the Proxy_Bridge standard input and the object recovered from the
  reassembled frames SHALL preserve the request `id`, `method`, and `params` values and the
  response association to that `id`, for reassembled payloads up to at least 10 MiB.
  *Validates Requirement 2 criteria 1, 8.*
- **P2 — SigV4 signing correctness and single-target invocation.** For any MCP JSON-RPC
  message the Proxy_Bridge receives, the resulting `invoke_agent_runtime` call SHALL carry an
  AWS Signature Version 4 signature computed from the held Kiro_Web_Credentials that the AWS
  API accepts, SHALL name the configured AgentCore_Runtime_Arn as `agentRuntimeArn`, and SHALL
  name no other AgentCore Runtime ARN; and no MCP JSON-RPC payload SHALL be transmitted over
  an unsigned request. *Validates Requirement 2 criteria 2, 10.*
- **P3 — Runtime_Session_Id reuse within a session.** For any sequence of two or more
  MDC_Power invocations in one Kiro_Web session, every `invoke_agent_runtime` call SHALL carry
  a byte-identical `runtimeSessionId` of at least 33 characters; and for any sequence in which
  the AgentCore_Runtime rejects that Runtime_Session_Id as unknown or expired, the MDC_Power
  SHALL generate exactly one replacement Runtime_Session_Id and SHALL issue exactly one retry
  of the rejected request. *Validates Requirement 2 criterion 9.*
- **P4 — Proxy_Bridge unmodified preservation.** For any change set that implements this
  feature, the content of `tools/agentcore-kiro-proxy.py` SHALL equal its content at the
  recorded baseline commit with a differing-byte count of exactly 0, and a repository-wide
  search SHALL return exactly one path whose content matches the Proxy_Bridge. *Validates
  Requirement 2 criteria 3, 4; Requirement 7 criteria 1, 2.*
- **P5 — Credential redaction across every outcome.** For any MDC_Power outcome — success,
  `power-activation` failure, `credential-resolution` failure, `proxy-launch` failure,
  `endpoint-invocation` failure, `authorization` failure, `tool-execution` failure,
  `response-parsing` failure, or diagnostic-action output — no string returned to the Kiro_Web
  session, no string written to any log, and no Audit_Log entry SHALL contain the AWS access
  key identifier or any contiguous substring longer than 8 characters of the secret access key
  or of the session token of the Kiro_Web_Credentials. *Validates Requirement 3 criteria 6, 7;
  Requirement 8 criterion 4; Requirement 9 criteria 9, 14.*
- **P6 — Credential-expiry detection and re-authentication surfacing.** For any
  `invoke_agent_runtime` failure whose AWS error code denotes expired or invalid credentials,
  the MDC_Power SHALL classify the failing stage as `credential-resolution`, SHALL return a
  message containing the credential-refresh command and containing no Python traceback and no
  raw botocore exception representation, and SHALL issue at most one resend of that MCP
  request. *Validates Requirement 3 criteria 10, 11, 12.*
- **P7 — IAM policy resource scoping.** For any synthesized CloudFormation template of this
  feature's stack, the IAM policy attached to the Kiro_Web_Principal SHALL contain exactly one
  `Allow` statement, exactly one action equal to `bedrock-agentcore:InvokeAgentRuntime`,
  exactly one resource equal to the configured AgentCore_Runtime_Arn, and zero wildcard
  characters in the account, region, and runtime segments of that resource. *Validates
  Requirement 4 criteria 1, 2.*
- **P8 — Tenant passthrough fidelity.** For any `tenant_id` value in the Tenant_Catalog and
  any tenant-scoped tool in the Allowed_Tool_Set, the `tenant_id` the MCP_Server resolves
  SHALL equal the `tenant_id` the Kiro_Web session supplied, and the response SHALL state that
  resolved value; and for any `tenant_id` value absent from the Tenant_Catalog, the MCP_Server
  SHALL return an error naming that value and SHALL query no other Tenant. *Validates
  Requirement 5 criteria 4, 6, 8.*
- **P9 — Empty-versus-unpopulated distinguishability.** For any Tenant and any tenant-scoped
  read tool, a response produced against an unpopulated index for that Tenant SHALL be
  distinguishable, by a field or marker in the response, from a response produced against a
  populated index that matched no results. *Validates Requirement 6 criteria 3, 4, 5.*
- **P10 — Audit entry well-formedness and joinability.** For any Kiro_Web_Principal tool
  invocation reaching the MCP_Server dispatcher, exactly one Audit_Log JSON Lines entry SHALL
  be emitted that parses as a single-line JSON object, carries non-empty caller-identity,
  consumer-class, tool, request-identifier, Runtime_Session_Id, outcome, and resolved
  `tenant_id` fields, sets each Request_Metadata-derived field to a string or explicit JSON
  `null`, contains no credential material and no tool argument and no tool output, and joins on
  the Runtime_Session_Id and the Kiro_Web_Session_Id to exactly one CloudTrail-recorded IAM
  principal identifier. *Validates Requirement 8 criteria 1, 2, 3, 4, 6, 7.*
- **P11 — Error stage labeling exhaustiveness.** For any MDC_Power failure mode described
  anywhere in this document, the error returned to the Kiro_Web session SHALL name exactly one
  of the seven stage values enumerated in Requirement 9 criterion 9, SHALL name no failure
  category as a stage, and the MDC_Power SHALL remain able to serve a subsequent request in
  the same Kiro_Web session for every stage other than `power-activation` and `proxy-launch`.
  *Validates Requirement 9 criteria 9, 10, 11.*

## Open Questions

These decisions are genuinely open. Each must be resolved and recorded in the design document
before the corresponding implementation tasks begin.

**Two identifiers are retired and are not reused.** **OQ-2** — the Path B dependency question —
is resolved as `no-delivery-dependency` and is now stated directly as Requirement 10 Acceptance
Criterion 1. **OQ-3** — the literal Web_Scope string — is not applicable under Plan A, because
Plan A creates no OAuth scope; that question transfers to Path_B_Baseline, which owns the
Cognito resource server, and it must be answered there before Kiro_Web migrates to the Path B
posture under Requirement 10 Acceptance Criterion 4. The identifiers OQ-2 and OQ-3 are
deliberately left unreused, and the surviving open questions keep their original identifiers
OQ-1 and OQ-4 through OQ-8, so that every existing cross-reference in downstream artifacts
remains resolvable.

| ID | Question | Why it is open | Resolution owner |
|---|---|---|---|
| **OQ-1** | How are the short-lived AWS credentials of Kiro_Web_Credentials delivered into the Kiro Web session? Candidates: **(a) `aws sso login` device authorization flow against AWS IAM Identity Center — recommended primary.** The CLI prints a verification URL and user code that the user completes in their own CAC-authenticated browser; the resulting credentials are cached in the sandbox and are refreshable without re-pasting a secret. **(b)** Short-lived AWS STS credentials pasted by the user into session environment variables. **(c)** An `AssumeRole` chain from a Kiro-Web-provided identity, if such an identity is later documented. | Candidate (a) fits the project's existing CAC single-sign-on and IAM Identity Center posture and avoids pasted secrets entirely, and IAM Identity Center **does** support the OAuth 2.0 device authorization grant even though Amazon Cognito user pools do not (per Path_B_Baseline AD-1) — which is precisely why the device flow is available to Plan A and was not available to the retired Cognito draft. Against (a): the verified sandbox has no `~/.aws/sso` cache (see `### Verified Kiro Web sandbox characteristics`, fact 6), so (a) requires a login step at each session start unless that cache persists across sessions, which is unverified. Candidate (b) is the lowest-effort fallback but places secret material in the session environment. Candidate (c) cannot be evaluated until a Kiro Web workload identity is documented. Requirement 3 criteria 1, 4, 5, 9, and 13; Requirement 11 criterion 3; and Requirement 12 criteria 1 and 2 all gate on this. | Design phase |
| **OQ-4** | Which AgentCore Runtime ARN is the AgentCore_Runtime_Arn for this feature? `.kiro/specs/mcp-external-access-revised/` names `mdc_mcp_rag_server-TMXDllG2Wi`; `.kiro/steering/09-agentcore-mcp-for-global-workflow.md` names `arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/mdc_mcp_rag_server_python-v5K2F8BGrN`. | **Criticality raised under Plan A.** The two artifacts disagree, and the same literal value is now simultaneously the SigV4 invocation target of Requirement 2 criterion 10 and the sole IAM policy `Resource` of Requirement 4 criteria 1 and 2. An incorrect value is therefore both a functional defect — every call fails or reaches the wrong runtime — and a security defect, because the IAM grant would be scoped to a resource other than the one the MDC_Power calls. Requirement 1 criteria 8 and 10, Requirement 2 criteria 10 and 14, Requirement 4 criteria 1 and 2, Requirement 10 criteria 8 and 9, and Requirement 12 criterion 1 all depend on this. | Design phase |
| **OQ-5** | What is the MCP_Server's authoritative tool count and tool list? `README.md` states 34 tools for the Node server; `.kiro/specs/mcp-external-access-revised/` states 51; `.kiro/steering/10-agentcore-mcp-tool-guide.md` states 52 across 9 modules. | Requirement 4 criterion 4 and Requirement 11 criteria 6 and 12 require an enumerated Allowed_Tool_Set, which cannot be enumerated against three conflicting counts. Under Plan A this enumeration also documents exactly what the unrestricted surface contains, including which of its members belong to the Mutation_Tool_Set, so the count is now a disclosure obligation as well as a documentation one. The count must be read from `mcp_server_python/src/tools/*.py` rather than from any of the three documents. | Design phase |
| **OQ-6** | Does `.kiro/settings/mcp.json`'s current single stdio entry `eib-mcp-rag-full` remain the intended local developer wiring, given that steering file 09 documents `agentcore-mcp-rag` as the connection path? | Requirement 7 criterion 3 requires `.kiro/settings/mcp.json` to stay byte-identical, which locks in whichever entry is present. If the file is already stale relative to steering 09, that should be resolved by a separate spec rather than silently by this one. | Design phase |
| **OQ-7** | Does the MDC_Power persist a session-declared `tenant_id` (Requirement 5 criterion 11) inside the Power, inside the MCP session, or not at all? | Kiro_Web session lifetime and Power state semantics are not documented in this repository. If neither layer can hold state, tenant declaration reduces to per-call `tenant_id` arguments and Requirement 5 criterion 11 must be recorded as withdrawn. | Design phase |
| **OQ-8** | Given that no per-tool restriction is enforceable under Plan A, should the Steering_Bundle advise the Kiro_Web agent against invoking members of the Mutation_Tool_Set, and is a client-side advisory guard in the MDC_Power worth implementing? | Requirement 4 criterion 5 forbids any mechanism described as restricting which tools a Kiro_Web session may execute, and Requirement 4 criterion 6 requires any reduced tool list to be described as a bypassable convenience filter. An advisory guard is trivially bypassable by a caller holding the Kiro_Web_Credentials and must never be presented as a security control; the open question is whether the reduction in accidental mutation justifies the risk that a reader mistakes the guard for enforcement. Requirement 11 criterion 6 documents whichever answer is chosen. | Design phase |

## Non-Goals

- **Per-tool authorization enforcement for a Kiro_Web session.** Enforcing which MCP_Server
  tools a Kiro_Web session may execute requires the Path_B_Baseline scope-enforcement
  middleware, which this spec does not deliver. Requirement 4 records the resulting residual
  risk and its migration trigger.
- **Production readiness.** Prototype_Status is `prototype`. This spec delivers a preview
  capability for project members inside the CAC single-sign-on and project IAM boundary.
- **Any Amazon Cognito, JWT, OAuth scope, or Bearer-token mechanism.** Plan A uses IAM SigV4
  only. Implementing the Path_B_Baseline Cognito authorizer, resource server, app clients, or
  CDK stack belongs to `.kiro/specs/mcp-external-access-revised/`.
- Enabling the GitHub Actions CI consumer class. Path_B_Baseline retains sole ownership of it
  (Tasks 3, 4, and 7).
- Enabling the RDHPCS/HPC login-node consumer class, including the `mdc-mcp-jwt`
  HPC_CLI_Helper. Path_B_Baseline retains sole ownership of it (Task 8).
- Building the Token_Broker Lambda or the GitHub OIDC federated IAM role. Path_B_Baseline
  retains ownership of both (Tasks 4 and 3), and no Kiro_Web behavior depends on either.
- Adopting AgentCore Gateway or authoring Cedar tool-level policies (Path C, deferred by
  Path_B_Baseline Requirement 11).
- Modifying the Proxy_Bridge `tools/agentcore-kiro-proxy.py` or `.kiro/settings/mcp.json`. The
  MDC_Power executes the Proxy_Bridge unmodified and reads no configuration from
  `.kiro/settings/mcp.json`.
- Adding, removing, renaming, or changing the behavior of any MCP_Server tool.
- Ingesting data for any Tenant, or closing the non-`gw` relationship-ingestion gap tracked by
  the `graph-port-*` spec series.
- Defining an automatic stale-index classification or staleness threshold, which Requirement 6
  Acceptance Criterion 8 defers to a separate spec.
- Publishing the MDC_Power to any Power registry outside this project.
