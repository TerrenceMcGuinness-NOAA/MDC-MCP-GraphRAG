# Requirements Document

## Introduction

The MDC MCP-RAG platform is the AWS-deployed code/documentation analysis service
that supports NOAA Global Workflow research under an NIH Sandbox managed AWS
funding envelope. The platform's compute footprint (EC2 dev host, Amazon
Neptune cluster, Amazon OpenSearch domain, AWS Bedrock AgentCore Runtime, NAT
Gateway, supporting VPC endpoints) accrues cost continuously, including during
the long stretches of nights, weekends, and inter-burst gaps when no operator
or research consumer is using the system. This feature defines the
**Cost_Control_System** — a CDK-based Infrastructure-as-Code (IaC) automation
that, on operator command, hibernates the compute footprint to a near-zero
hourly cost ("**Sleep_State**") and later restores it to a fully-initialized,
query-serving footprint ("**Wake_State**"), without losing any ingested data,
graph relationships, vector embeddings, tenant-prefixed indices, or container
images.

The motivating goal is **funding preservation**: by reducing AWS spend during
periods of non-use, the same NIH Sandbox dollar budget extends the operational
lifetime of the investigation. The feature must be operator-driven (research
bursts are unpredictable), strictly data-preserving (the ingestion runs that
produced the current knowledge base are expensive to repeat — the v17 Fortran
re-ingest alone took ~3.2 hours and the gw baseline community-summary pipeline
spends Bedrock LLM dollars per run), and idempotent so that re-issuing a
command in any state is safe.

The current platform topology to be controlled:

| Tier | AWS Resource | Hourly Cost Driver | Native Stop/Start? |
|------|--------------|-------------------|---------------------|
| Compute host | EC2 instance (t3.large class, ~60 GB EBS, EFS mount at `/mnt/workflow`) | EC2 hour | yes (stop/start) |
| Graph DB | Amazon Neptune cluster `mdc-mcp-graprag-neptune-1` (gw: ~149K nodes / 4.5M rels; gw_v17: ~81K nodes / 1.28M rels) | Neptune compute hour | yes (cluster stop/start; auto-restarts after 7 days) |
| Vector DB | Amazon OpenSearch VPC domain (21 indices, ~252K + ~57K docs) | Domain instance hours | no (delete-and-restore-from-snapshot, scale down, or accept idle cost) |
| MCP runtime | AWS Bedrock AgentCore Runtime `mdc_mcp_rag_server_python-v5K2F8BGrN` (currently v35, 6 env vars, 2 subnets, 1 SG, EFS access point `fsap-03e641f056b341f29`) | Per-session — runtime definition itself is free | no — DELETE/CREATE only (definition is free; sessions auto-terminate) |
| Network | VPC, subnets, security groups, NAT Gateway, VPC endpoints | NAT Gateway hour + endpoint hours; VPC itself free | no for NAT (delete/recreate or replace with stoppable NAT instance) |
| File system | EFS workflow worktrees (`/mnt/workflow/develop`, `/mnt/workflow/dev-v17`, …) | Storage GB-month | n/a — storage-only, persistent |
| Container registry | ECR repository `mdc-mcp-rag` | Storage GB-month | n/a — storage-only |
| Object storage | S3 buckets (snapshots, backups, staging) | Storage GB-month + requests | n/a — storage-only |
| Logs | CloudWatch log groups | Ingestion + retention | n/a — retention policy |

Operationally, **Sleep_State** means: every per-hour-billed compute resource is
either stopped (where the service supports it) or destroyed (where it does
not), and every byte of ingested or accumulated state is preserved in a
storage-only tier whose hourly cost is dominated by GB-months of storage and is
small relative to active compute. **Wake_State** means: every compute resource
is back online, every tenant in the catalog (`gw`, `gw_sfs`, `gw_jedi_gfs`,
`gw_v17`, `gw_gefs_v12`) returns its expected attribution from the MCP, and a
`Wake_Validation_Probe` confirms the system is serving queries. The transition
from one to the other is initiated by an operator, gated on an explicit
confirmation, audit-logged, and protected against concurrent invocations by a
versioned state file.

The CDK app, runbook, and supporting tooling produced by this feature land in
`SETUP_AWS/provisioning/` alongside the existing host-provisioning runbooks
(`RUNBOOK_agentcore_creds.md`, `provision-user-accounts.sh`, etc.) so that
operator workflows are co-located.

## Glossary

- **Cost_Control_System**: The CDK app, supporting Lambda functions, runbook,
  and operator CLI defined by this spec. The aggregate of every artefact under
  `SETUP_AWS/provisioning/` that participates in sleep/wake control.
- **Operator**: The human (or service identity acting on a human's behalf) who
  invokes the `Hibernate_Operation` or `Wake_Operation` from a privileged
  workstation or CI runner. Identified in `Audit_Log_Record` entries by AWS
  caller identity ARN.
- **Active_Mode**: The state in which every compute resource enumerated in the
  Introduction is online and the platform serves MCP queries normally.
- **Sleep_State**: The state in which `Compute_Stack` resources are stopped or
  destroyed, `Storage_Stack`, `IAM_Stack`, and `Network_Stack` resources remain
  in place, and the platform's hourly cost is reduced by at least the
  `Cost_Savings_Target` relative to `Active_Mode`.
- **Wake_State**: The state, equivalent to `Active_Mode`, that follows a
  successful `Wake_Operation` and `Wake_Validation_Probe`.
- **Sleeping**: The transient state during which the `Hibernate_Operation` is
  executing; entered after the operator confirmation gate and exited on success
  to `Sleep_State` or on failure to `Active_Mode_Degraded` (with the
  `Audit_Log_Record` capturing partial progress).
- **Waking**: The transient state during which the `Wake_Operation` is
  executing; entered after the operator confirmation gate and exited on success
  to `Wake_State` or on failure to `Sleep_State_Degraded`.
- **Hibernate_Operation**: The operator-initiated, idempotent procedure that
  transitions the platform from `Active_Mode` to `Sleep_State`, performing
  pre-destruction snapshots of any data tier whose compute layer will be
  destroyed and stopping every per-hour compute resource.
- **Wake_Operation**: The operator-initiated, idempotent procedure that
  transitions the platform from `Sleep_State` to `Wake_State`, restoring data
  from the most recent valid snapshots where compute layers were destroyed and
  starting every per-hour compute resource.
- **Storage_Stack**: The CDK stack `MdcMcpRag-Storage-{env}` that contains EFS,
  ECR, S3 backup buckets, snapshot resources (Neptune cluster snapshots,
  OpenSearch manual snapshot repository), and their lifecycle policies. Never
  destroyed by the `Cost_Control_System`.
- **IAM_Stack**: The CDK stack `MdcMcpRag-IAM-{env}` that contains every IAM
  role and policy referenced by `Compute_Stack`, `Storage_Stack`, and the
  `Cost_Control_System` itself. Never destroyed.
- **Network_Stack**: The CDK stack `MdcMcpRag-Network-{env}` that contains the
  VPC, subnets, route tables, security groups, and VPC endpoints that have no
  compute hour. Never destroyed. The NAT Gateway is excluded from this stack
  and lives in `Compute_Stack` because it is per-hour-billed.
- **Compute_Stack**: The CDK stack `MdcMcpRag-Compute-{env}` that contains
  every per-hour-billed resource: EC2 instance, Neptune cluster, OpenSearch
  domain, AgentCore Runtime definition, NAT Gateway. Destroyed and recreated
  by `Hibernate_Operation` and `Wake_Operation` for resources without native
  stop/start; stopped and started in place for resources that support it.
- **Snapshot_Lifecycle**: The set of rules that govern when a `Snapshot` is
  created, retained, and deleted. Snapshots are taken before any
  destructive `Hibernate_Operation` step, retained for at least the configured
  minimum retention window, and pruned thereafter by lifecycle policy.
- **Snapshot**: A point-in-time, restorable copy of a single data tier. Types
  include `Neptune_Cluster_Snapshot`, `OpenSearch_Manual_Snapshot`, and
  `ECR_Image_Tag` (already immutable; included by reference rather than copy).
- **Wake_Validation_Probe**: The post-`Wake_Operation` automated probe that
  verifies (a) every tenant in the platform's tenant catalog resolves its
  attribution header correctly, (b) `mcp_health_check` reports HEALTHY for
  Base, Vector, and Graph DB components, and (c) `get_knowledge_base_status`
  returns non-zero counts for the gw baseline and for every other tenant whose
  pre-sleep counts were non-zero.
- **State_File**: The single, S3-versioned JSON object at the configured S3
  key, owned by the `Cost_Control_System`, that records the platform's current
  state (one of `Active_Mode`, `Sleep_State`, `Sleeping`, `Waking`,
  `Active_Mode_Degraded`, `Sleep_State_Degraded`), the timestamp of the last
  state transition, the AWS caller identity that initiated it, the
  `Snapshot` identifiers produced or consumed by the most recent transition,
  and a monotonic operation counter.
- **Audit_Log_Record**: A structured JSON record emitted by every
  `Hibernate_Operation` step and every `Wake_Operation` step, conforming to
  the schema in Requirement 9. Persisted both to CloudWatch Logs and to the
  S3 audit bucket.
- **Drift_Reconciliation**: The `Wake_Operation` sub-step that compares each
  data tier's current `Storage_Stack` state against the manifest captured in
  the `State_File` at the previous `Hibernate_Operation` and either reconciles
  detected differences automatically (where the change is unambiguously
  data-preserving) or fails loud with a non-zero exit and a `Drift_Detected`
  diagnostic.
- **Cost_Savings_Target**: The required minimum reduction in platform hourly
  AWS spend during `Sleep_State` relative to `Active_Mode`, expressed as a
  percentage. Set by Requirement 5.
- **Wake_SLA**: The required maximum elapsed wall-clock time from operator
  issuance of the `Wake_Operation` command to a successful
  `Wake_Validation_Probe`. Set by Requirement 6.
- **Confirmation_Gate**: The interactive operator step that prevents a
  destructive `Hibernate_Operation` or `Wake_Operation` from proceeding until
  the operator types or supplies the exact confirmation phrase declared by
  the operation in question.
- **Schedule_Mode**: The optional automated invocation path (EventBridge cron
  rule plus Lambda) that issues `Hibernate_Operation` or `Wake_Operation` on
  a schedule. Off by default.
- **Tenant_Catalog**: The set of tenants declared in
  `mcp_server_python/src/config/tenants.yaml` (currently `gw`, `gw_sfs`,
  `gw_jedi_gfs`, `gw_v17`, `gw_gefs_v12`). The
  `Wake_Validation_Probe` references this set.
- **Environment_Name**: The CDK context value (e.g. `dev`, `staging`, `prod`)
  that parameterizes every stack name, resource tag, and `State_File` key,
  so multiple isolated deployments coexist in the same AWS account.
- **Provisioning_Directory**: The fixed path
  `SETUP_AWS/provisioning/` in this repository, where every artefact produced
  by this spec lands.

## Requirements

### Requirement 1: Operator-Driven Hibernate Operation

**User Story:** As an NIH Sandbox operator, I want to issue a single command
that puts the entire MCP-RAG platform to sleep, so that the platform stops
accruing per-hour compute charges during periods of non-use.

#### Acceptance Criteria

1. THE Cost_Control_System SHALL expose a `Hibernate_Operation` invokable from
   `SETUP_AWS/provisioning/` that, when executed by the Operator, transitions
   the platform from `Active_Mode` to `Sleep_State`.
2. WHEN the Operator invokes the `Hibernate_Operation`, THE Cost_Control_System
   SHALL acquire the `State_File` lock, write `Sleeping` as the current state,
   and emit a `Sleep_Started` `Audit_Log_Record` before performing any
   destructive action.
3. WHEN the `Hibernate_Operation` reaches a per-tier step that destroys a
   compute resource fronting a data tier, THE Cost_Control_System SHALL create
   a Snapshot of that data tier and SHALL persist the snapshot identifier in
   the `State_File` before the destructive AWS API call is issued.
4. WHEN every compute resource enumerated by the `Compute_Stack` has been
   stopped or destroyed and every required Snapshot has been confirmed
   `available`, THE Cost_Control_System SHALL write `Sleep_State` as the
   current state in the `State_File`, SHALL emit a `Sleep_Completed`
   `Audit_Log_Record`, and SHALL release the `State_File` lock.
5. IF any step of the `Hibernate_Operation` fails after the destructive
   transition has begun, THEN THE Cost_Control_System SHALL write
   `Active_Mode_Degraded` to the `State_File`, SHALL emit a `Sleep_Failed`
   `Audit_Log_Record` containing the failed step identifier and the AWS error,
   SHALL release the `State_File` lock, and SHALL exit with a non-zero status.

### Requirement 2: Operator-Driven Wake Operation

**User Story:** As an NIH Sandbox operator, I want to issue a single command
that brings the entire MCP-RAG platform back to a fully serving state, so that
researchers can resume queries without manually sequencing multiple AWS
service restarts.

#### Acceptance Criteria

1. THE Cost_Control_System SHALL expose a `Wake_Operation` invokable from
   `SETUP_AWS/provisioning/` that, when executed by the Operator, transitions
   the platform from `Sleep_State` to `Wake_State`.
2. WHEN the Operator invokes the `Wake_Operation`, THE Cost_Control_System
   SHALL acquire the `State_File` lock, write `Waking` as the current state,
   and emit a `Wake_Started` `Audit_Log_Record` before issuing any compute
   creation API call.
3. WHEN the `Wake_Operation` reaches a per-tier step that requires restoring
   from a Snapshot, THE Cost_Control_System SHALL select the Snapshot
   identifier persisted in the `State_File` by the most recent successful
   `Hibernate_Operation` for that tier and SHALL fail the `Wake_Operation`
   with a non-zero exit if that Snapshot is not in `available` status.
4. WHEN every compute resource enumerated by the `Compute_Stack` has been
   created or started and the `Wake_Validation_Probe` reports success, THE
   Cost_Control_System SHALL write `Wake_State` as the current state in the
   `State_File`, SHALL emit a `Wake_Completed` `Audit_Log_Record` containing
   the elapsed wall-clock time, and SHALL release the `State_File` lock.
5. IF the `Wake_Validation_Probe` fails after every compute resource is
   reported `available` by AWS, THEN THE Cost_Control_System SHALL write
   `Sleep_State_Degraded` to the `State_File`, SHALL emit a `Wake_Failed`
   `Audit_Log_Record` enumerating each failed probe assertion, SHALL release
   the `State_File` lock, and SHALL exit with a non-zero status.

### Requirement 3: Data Preservation Across Sleep/Wake Cycles

**User Story:** As an NIH Sandbox operator, I want every byte of ingested
graph, vector, file system, container, and object data to survive a sleep/wake
cycle, so that no expensive re-ingestion or rebuild is required to return the
platform to operational quality.

#### Acceptance Criteria

1. WHEN a `Hibernate_Operation` followed by a `Wake_Operation` completes
   successfully, THE Cost_Control_System SHALL ensure that the Neptune node
   count and relationship count, broken down per tenant label prefix, are
   byte-equal to the corresponding counts captured in the
   `Hibernate_Operation` `Sleep_Started` `Audit_Log_Record`.
2. WHEN a `Hibernate_Operation` followed by a `Wake_Operation` completes
   successfully, THE Cost_Control_System SHALL ensure that for every
   OpenSearch index present at `Sleep_Started` time, the post-wake index
   exists with a document count equal to the pre-sleep document count.
3. THE Cost_Control_System SHALL NOT destroy, replace, or modify any resource
   in `Storage_Stack` as part of the `Hibernate_Operation` or
   `Wake_Operation`.
4. THE Cost_Control_System SHALL NOT destroy, replace, or modify the EFS file
   system, the EFS access point `fsap-03e641f056b341f29` (or its
   environment-equivalent in non-prod environments), or any directory tree
   under `/mnt/workflow/` as part of the `Hibernate_Operation`.
5. THE Cost_Control_System SHALL NOT delete any container image tag in the
   `mdc-mcp-rag` ECR repository as part of the `Hibernate_Operation`.

### Requirement 4: Pre-Destruction Snapshot Capture

**User Story:** As an NIH Sandbox operator, I want every destructive sleep
action to be preceded by a verified snapshot of the affected data tier, so
that any subsequent failure during the sleep transition or any external loss
event is recoverable.

#### Acceptance Criteria

1. WHEN the `Hibernate_Operation` is about to destroy or stop the Neptune
   cluster, THE Cost_Control_System SHALL initiate a Neptune cluster Snapshot
   and SHALL wait for that Snapshot to reach the `available` status before
   issuing the destructive API call.
2. WHEN the `Hibernate_Operation` is about to destroy the OpenSearch domain,
   THE Cost_Control_System SHALL initiate an OpenSearch manual Snapshot to
   the configured S3 manual-snapshot repository and SHALL wait for the
   Snapshot to reach the `SUCCESS` state before issuing the destructive API
   call.
3. WHEN the `Hibernate_Operation` is about to destroy or stop the EC2
   instance, THE Cost_Control_System SHALL ensure that the EBS root volume's
   most recent EBS Snapshot is no older than the configured maximum age, and
   SHALL initiate a fresh EBS Snapshot and wait for `completed` status if it
   is older.
4. THE Cost_Control_System SHALL retain every Snapshot it creates for at
   least the configured minimum retention window, expressed in days as a CDK
   context value that defaults to 30 days.
5. IF a Snapshot creation step does not reach its terminal success status
   within the configured per-tier wait timeout, THEN THE Cost_Control_System
   SHALL abort the `Hibernate_Operation`, SHALL emit a `Snapshot_Timeout`
   `Audit_Log_Record` naming the tier and the elapsed time, and SHALL exit
   with a non-zero status without issuing the destructive API call.

### Requirement 5: Cost Savings Target

**User Story:** As an NIH Sandbox steward, I want a documented and verifiable
floor on the hourly cost savings produced by `Sleep_State`, so that the
funding-preservation case for the system is auditable.

#### Acceptance Criteria

1. WHILE the platform is in `Sleep_State`, THE Cost_Control_System SHALL
   reduce the platform's billable per-hour AWS spend (excluding storage
   GB-month charges and one-time API request charges) by at least 80% relative
   to the same platform in `Active_Mode`.
2. THE Cost_Control_System SHALL document, in the runbook delivered to
   `SETUP_AWS/provisioning/`, the per-resource hourly cost in `Active_Mode`
   and the per-resource hourly cost in `Sleep_State` that together justify the
   80% target.
3. WHEN the `Hibernate_Operation` completes successfully, THE
   Cost_Control_System SHALL include in the `Sleep_Completed`
   `Audit_Log_Record` an estimated hourly-savings figure, computed from the
   resources stopped or destroyed in that operation, expressed in USD per
   hour.
4. WHEN the `Wake_Operation` completes successfully, THE Cost_Control_System
   SHALL include in the `Wake_Completed` `Audit_Log_Record` the total
   estimated USD savings accumulated during the preceding `Sleep_State`
   window, computed as the per-hour savings figure multiplied by the elapsed
   sleep duration.

### Requirement 6: Wake-Up Time SLA

**User Story:** As an NIH Sandbox operator returning from a research pause, I
want the platform to reach a fully operational state within a bounded
wall-clock time after I issue the wake command, so that I can plan a research
session around a predictable warm-up.

#### Acceptance Criteria

1. WHEN the `Wake_Operation` is invoked from `Sleep_State`, THE
   Cost_Control_System SHALL complete the transition to `Wake_State`,
   including a successful `Wake_Validation_Probe`, within 60 minutes of
   wall-clock time on the platform's reference environment as documented in
   the runbook.
2. WHILE the `Wake_Operation` is executing, THE Cost_Control_System SHALL emit
   a per-tier progress `Audit_Log_Record` no less frequently than once every
   five minutes, identifying the current tier under restoration and the
   elapsed wall-clock time.
3. IF the `Wake_Operation` exceeds the configured maximum wall-clock budget
   (defaulting to 90 minutes), THEN THE Cost_Control_System SHALL emit a
   `Wake_Timeout` `Audit_Log_Record`, SHALL leave the `State_File` in
   `Sleep_State_Degraded`, and SHALL exit with a non-zero status without
   forcibly cancelling in-flight AWS operations.

### Requirement 7: Idempotency of Sleep and Wake Commands

**User Story:** As an NIH Sandbox operator, I want re-issuing the sleep
command when the platform is already asleep, or the wake command when the
platform is already awake, to be a safe no-op, so that I cannot accidentally
double-execute a destructive operation.

#### Acceptance Criteria

1. WHEN the Operator invokes the `Hibernate_Operation` and the `State_File`
   reports the current state as `Sleep_State`, THE Cost_Control_System SHALL
   emit a `Sleep_NoOp` `Audit_Log_Record`, SHALL NOT modify any AWS resource,
   SHALL NOT create any new Snapshot, and SHALL exit with status 0.
2. WHEN the Operator invokes the `Wake_Operation` and the `State_File`
   reports the current state as `Wake_State` or `Active_Mode`, THE
   Cost_Control_System SHALL emit a `Wake_NoOp` `Audit_Log_Record`, SHALL NOT
   modify any AWS resource, and SHALL exit with status 0.
3. IF the Operator invokes the `Hibernate_Operation` while the `State_File`
   reports `Sleeping` or `Waking`, THEN THE Cost_Control_System SHALL emit a
   `Concurrent_Operation_Refused` `Audit_Log_Record` containing the
   conflicting state and the prior operation's caller identity, SHALL NOT
   modify any AWS resource, and SHALL exit with a non-zero status.
4. IF the Operator invokes the `Wake_Operation` while the `State_File`
   reports `Sleeping` or `Waking`, THEN THE Cost_Control_System SHALL emit a
   `Concurrent_Operation_Refused` `Audit_Log_Record` containing the
   conflicting state and the prior operation's caller identity, SHALL NOT
   modify any AWS resource, and SHALL exit with a non-zero status.

### Requirement 8: Authoritative State File

**User Story:** As an NIH Sandbox operator, I want one durable, versioned,
externally-readable record of the platform's current sleep/wake state, so
that operators, dashboards, and scheduled jobs all reach the same answer
about whether the system is asleep.

#### Acceptance Criteria

1. THE Cost_Control_System SHALL persist the `State_File` as a single JSON
   object in an S3 bucket whose versioning is enabled and whose lifecycle
   policy retains every prior version for at least the configured retention
   window.
2. THE State_File JSON object SHALL contain the fields `current_state`,
   `previous_state`, `last_transition_at` (ISO 8601 UTC), `last_caller_arn`,
   `operation_counter` (monotonically increasing integer), `environment_name`,
   `latest_snapshots` (mapping from data tier identifier to the most recent
   successful Snapshot identifier), and `schema_version` (string).
3. WHEN any `Hibernate_Operation` or `Wake_Operation` step modifies the
   `State_File`, THE Cost_Control_System SHALL increment
   `operation_counter` by 1 and SHALL refuse the write if the prior
   `operation_counter` value the writer read does not match the value
   currently stored, so that lost-update conflicts surface as explicit
   failures.
4. WHILE a `Hibernate_Operation` or `Wake_Operation` is in flight, THE
   Cost_Control_System SHALL prevent any other invocation of either
   operation from making progress past its `State_File` lock acquisition
   step.
5. THE Cost_Control_System SHALL expose a read-only `status` subcommand that
   prints the parsed `State_File` contents to standard output without
   acquiring the lock and without modifying any AWS resource.

### Requirement 9: Audit Trail and Observability

**User Story:** As an NIH Sandbox steward, I want every sleep and wake action
to leave a structured, searchable audit trail, so that cost-savings claims
and post-incident reviews can be reconstructed without re-running the
operations.

#### Acceptance Criteria

1. THE Cost_Control_System SHALL emit every `Audit_Log_Record` as a single
   JSON object on a single line, containing at minimum the fields
   `timestamp` (ISO 8601 UTC), `event_type`, `operation_id` (UUID),
   `caller_arn`, `environment_name`, `state_before`, `state_after`,
   `tier` (when applicable), `aws_resource_arns` (list, when applicable),
   `snapshot_ids` (list, when applicable), `elapsed_seconds`,
   `estimated_savings_usd_per_hour` (when applicable), and `error` (object
   with `code` and `message`, present only on failure events).
2. THE Cost_Control_System SHALL persist every `Audit_Log_Record` to a
   CloudWatch log group named `mdc-mcp-rag-cost-control-{environment_name}`
   with a configurable retention period defaulting to 365 days.
3. THE Cost_Control_System SHALL persist every `Audit_Log_Record` produced by
   a single operation to an S3 audit object keyed by `operation_id` in the
   configured audit bucket, written exactly once per operation upon
   completion or failure.
4. WHEN the `Hibernate_Operation` or `Wake_Operation` mutates an AWS resource,
   THE Cost_Control_System SHALL emit a per-resource `Audit_Log_Record`
   identifying the AWS resource ARN, the action taken, and the AWS request
   ID returned by the SDK call.

### Requirement 10: Drift Detection on Wake

**User Story:** As an NIH Sandbox operator returning from a sleep window, I
want the wake operation to refuse to silently overwrite any out-of-band
change made to the storage layer while the platform was asleep, so that
inadvertent data loss cannot be hidden by a successful wake.

#### Acceptance Criteria

1. WHEN the `Wake_Operation` begins, THE Cost_Control_System SHALL invoke
   `Drift_Reconciliation` and SHALL compare each tier's current
   `Storage_Stack` state against the per-tier manifest captured in the
   `State_File` at the most recent successful `Hibernate_Operation`.
2. WHERE `Drift_Reconciliation` detects a difference that the system has
   classified as data-preserving (for example, an additional ECR image tag
   appearing while compute was destroyed), THE Cost_Control_System SHALL
   reconcile the difference automatically, SHALL emit a `Drift_Reconciled`
   `Audit_Log_Record` enumerating the resolved differences, and SHALL
   continue the `Wake_Operation`.
3. IF `Drift_Reconciliation` detects a difference that the system has not
   classified as data-preserving (for example, a missing OpenSearch
   snapshot, a deleted ECR image referenced by the runtime, or a change to a
   storage bucket's retention policy), THEN THE Cost_Control_System SHALL
   emit a `Drift_Detected` `Audit_Log_Record` enumerating the differences,
   SHALL leave the `State_File` in `Sleep_State`, and SHALL exit with a
   non-zero status before any compute resource is created or started.
4. THE Cost_Control_System SHALL document in the runbook the manual
   intervention procedure that the Operator follows after a `Drift_Detected`
   exit, including the override flag (and the explicit confirmation phrase
   required) by which the Operator may direct the next `Wake_Operation` to
   proceed despite the detected drift.

### Requirement 11: Layered CDK Stack Decomposition

**User Story:** As an NIH Sandbox developer maintaining the IaC, I want the
CDK app to be decomposed into stacks aligned with the sleep/wake destruction
boundary, so that a destructive sleep operation cannot accidentally remove a
data tier.

#### Acceptance Criteria

1. THE Cost_Control_System SHALL define exactly four CDK stacks per
   environment: `MdcMcpRag-Storage-{env}`, `MdcMcpRag-IAM-{env}`,
   `MdcMcpRag-Network-{env}`, and `MdcMcpRag-Compute-{env}`.
2. THE `MdcMcpRag-Storage-{env}` stack SHALL declare every EFS file system,
   ECR repository, S3 bucket, OpenSearch manual snapshot S3 repository, and
   Snapshot lifecycle policy, and SHALL declare no resource that bills per
   hour.
3. THE `MdcMcpRag-IAM-{env}` stack SHALL declare every IAM role, IAM policy,
   and IAM resource referenced by any of the other three stacks or by the
   `Cost_Control_System` itself.
4. THE `MdcMcpRag-Network-{env}` stack SHALL declare the VPC, subnets, route
   tables, security groups, and any VPC endpoint that does not bill per
   hour, and SHALL declare no compute resource and no NAT Gateway.
5. THE `MdcMcpRag-Compute-{env}` stack SHALL declare every per-hour-billed
   resource, including the EC2 instance, the Neptune cluster, the
   OpenSearch domain, the AgentCore Runtime definition, and the NAT Gateway,
   and SHALL consume the storage and snapshot identifiers exported by
   `MdcMcpRag-Storage-{env}` rather than redeclaring them.
6. WHEN the `Hibernate_Operation` performs destructive actions, THE
   Cost_Control_System SHALL act only on resources owned by
   `MdcMcpRag-Compute-{env}`.

### Requirement 12: Tenant Data Preservation and Wake Validation Probe

**User Story:** As an NIH Sandbox researcher with branch-specific work in
progress, I want the wake operation to confirm that every tenant in the
catalog still resolves correctly before reporting success, so that I can
trust that my branch's graph and indices survived the sleep cycle.

#### Acceptance Criteria

1. THE Cost_Control_System SHALL include a `Wake_Validation_Probe` step that
   issues, for each tenant identifier present in the platform's
   `Tenant_Catalog`, a tenant-attributed `mcp_health_check` and a
   tenant-attributed `get_knowledge_base_status` call against the live
   AgentCore Runtime endpoint.
2. THE `Wake_Validation_Probe` SHALL assert, for the default `gw` tenant,
   that the response attribution header reports tenant `gw` and branch
   `develop` and that the reported Neptune node count and OpenSearch
   document count are non-zero.
3. THE `Wake_Validation_Probe` SHALL assert, for every non-default tenant
   identifier in the `Tenant_Catalog` whose pre-sleep counts (recorded in
   the `Sleep_Started` `Audit_Log_Record`) were non-zero, that the
   post-wake response attribution header reports the matching tenant and
   branch and that the reported counts are non-zero.
4. IF any `Wake_Validation_Probe` assertion fails, THEN THE
   Cost_Control_System SHALL apply the failure handling defined in
   Requirement 2 acceptance criterion 5.

### Requirement 13: Multi-Environment Parameterization

**User Story:** As an NIH Sandbox developer evolving the platform, I want the
CDK app to be parameterized by environment name so that the same templates
deploy isolated dev, staging, and prod stacks without code changes, even
though only one environment is in active use today.

#### Acceptance Criteria

1. THE Cost_Control_System SHALL accept an `Environment_Name` input via CDK
   context (for example, `cdk deploy --context env=dev`) and SHALL use the
   value to suffix every CDK stack name, every CloudWatch log group name,
   every audit S3 prefix, and the `State_File` S3 key.
2. THE Cost_Control_System SHALL apply, on every AWS resource it creates,
   the resource tag `mdc-mcp-rag:environment` set to the resolved
   `Environment_Name` value.
3. THE Cost_Control_System SHALL refuse to perform a `Hibernate_Operation`
   or `Wake_Operation` against any AWS resource whose
   `mdc-mcp-rag:environment` tag does not match the operation's invoked
   `Environment_Name`.
4. THE Cost_Control_System SHALL accept a `valid_environments` allow-list
   in CDK context (defaulting to `dev`, `staging`, `prod`) and SHALL refuse
   to deploy under any `Environment_Name` value outside the allow-list.

### Requirement 14: Optional Scheduled Sleep and Wake

**User Story:** As an NIH Sandbox steward, I want the option to enable a
recurring schedule (for example, sleep at 8 PM ET on weekday evenings, wake
at 8 AM ET on weekday mornings) so that the cost-saving window is consistent
without operator presence, while still being off by default during the early
operational period.

#### Acceptance Criteria

1. THE Cost_Control_System SHALL support a `Schedule_Mode` that, when
   enabled, registers an EventBridge cron rule plus a Lambda invoker that
   executes the same `Hibernate_Operation` or `Wake_Operation` code path
   used by the operator CLI.
2. THE Cost_Control_System SHALL ship with `Schedule_Mode` disabled by
   default; enabling it SHALL require the operator to set a CDK context
   value (`schedule_enabled=true`) and to provide both a sleep cron
   expression and a wake cron expression.
3. WHERE `Schedule_Mode` is enabled, THE Cost_Control_System SHALL bypass
   the interactive `Confirmation_Gate` for the scheduled operation only and
   SHALL emit a `Scheduled_Invocation` `Audit_Log_Record` whose
   `caller_arn` is the EventBridge invoker's IAM role ARN.
4. WHERE `Schedule_Mode` is enabled, THE Cost_Control_System SHALL still
   honor the idempotency rules of Requirement 7 and the concurrent
   operation refusal rules of Requirement 7 acceptance criteria 3 and 4.

### Requirement 15: Operator Confirmation Gates on Destructive Operations

**User Story:** As an NIH Sandbox operator, I want every destructive
operation to require an explicit, non-default confirmation before it
proceeds, so that I cannot put the platform to sleep or recreate compute
resources by accident from a stale terminal.

#### Acceptance Criteria

1. WHEN the operator-driven `Hibernate_Operation` is invoked interactively,
   THE Cost_Control_System SHALL display the resolved `Environment_Name`,
   the list of resources that will be destroyed or stopped, and the list
   of Snapshots that will be created, and SHALL prompt the operator for an
   exact confirmation phrase before issuing any destructive AWS API call.
2. WHEN the operator-driven `Wake_Operation` is invoked interactively, THE
   Cost_Control_System SHALL display the resolved `Environment_Name`, the
   list of Snapshots that will be consumed, and the list of resources that
   will be created or started, and SHALL prompt the operator for an exact
   confirmation phrase before issuing any compute creation API call.
3. IF the operator response to the `Confirmation_Gate` does not match the
   exact phrase declared by the operation, THEN THE Cost_Control_System
   SHALL emit a `Confirmation_Declined` `Audit_Log_Record`, SHALL NOT
   modify any AWS resource, and SHALL exit with status 0.
4. THE Cost_Control_System SHALL accept a non-interactive mode flag (for
   example, `--yes`) that substitutes a recorded confirmation token for
   the interactive prompt, intended for CI runners and the
   `Schedule_Mode` Lambda invoker, and SHALL log usage of the flag in the
   relevant `Audit_Log_Record`.

### Requirement 16: Artifact Location and Provisioning Alignment

**User Story:** As an NIH Sandbox operator, I want every artefact produced
by this feature to land alongside the existing host-provisioning runbooks,
so that the operator workflow is co-located with the existing tooling and
documentation conventions of this repository.

#### Acceptance Criteria

1. THE Cost_Control_System SHALL deliver every CDK app file, supporting
   Python or shell module, IAM policy template, EventBridge schedule
   definition, Lambda handler, and operator runbook to a subtree rooted at
   `SETUP_AWS/provisioning/`.
2. THE Cost_Control_System SHALL deliver an operator runbook at
   `SETUP_AWS/provisioning/RUNBOOK_cost_control.md` that documents the
   `Hibernate_Operation`, `Wake_Operation`, status query, drift override,
   and Schedule_Mode procedures, modeled on the structure of
   `SETUP_AWS/provisioning/RUNBOOK_agentcore_creds.md`.
3. WHEN `Hibernate_Operation` or `Wake_Operation` is invoked from a path
   outside `SETUP_AWS/provisioning/`, THE Cost_Control_System SHALL still
   resolve every relative path it depends on to a location under
   `SETUP_AWS/provisioning/`, so that the artefact tree is the single
   source of truth regardless of the operator's working directory.
