# Requirements Document

## Introduction

This feature adds the `which_pillar` recommender tool and gateway-side
attribution machinery that lets agents and developers answer the
question *"which tenant should I be asking?"* without learning all
configured pillar names by heart. After this feature lands, an agent
can call `which_pillar(file_or_topic="dev/jobs/JGLOBAL_ATMOS_POST")`
and get back a ranked recommendation (`gw_sfs` first, with
explanation) — and every response from any tenant carries provenance
metadata sufficient for an audit log.

This feature depends on `omd-tenants-1-foundation` (catalog + tenant
resolution + per-tenant data isolation) and assumes at least two
tenants are configured (typically `gw` + `gw-sfs` from the pilot
spec).

## Glossary

- **Pillar_Recommender**: A new MCP tool `which_pillar` that maps an
  arbitrary text query (file path, symbol name, free-text topic) to
  a ranked list of tenant_ids most likely to contain it.
- **Recommendation_Score**: A number in [0,1] indicating the
  recommender's confidence that the query belongs to a given tenant.
  Higher is better.
- **Pillar_Reasoning**: A short human-readable string explaining
  why a tenant scored as it did (e.g. "file path matches a
  gw_sfs-only prefix `dev/jobs/JGLOBAL_*_POST`").
- **Tenant_Attribution_Block**: A structured metadata block attached
  to every tool response containing `tenant_id`, `branch`,
  `repo_ref`, `lifecycle`, `data_freshness_iso`, and a stable
  `request_id`.
- **Audit_Trail**: A JSONL append-only log of (timestamp, request_id,
  tenant_id, tool_name, caller_principal) tuples written to a
  configurable path.

## Requirements

### Requirement 1: `which_pillar` Tool

**User Story:** As an agent or developer who does not know which
pillar a piece of code belongs to, I want a single tool to ask, so
that I do not have to guess between configured tenants.

#### Acceptance Criteria

1. THE `utility` module SHALL register a new MCP tool `which_pillar`
   with input schema `{file_or_topic: str, max_results: int=3}` and
   output a markdown table of recommendations.
2. EACH recommendation SHALL contain `tenant_id`,
   `recommendation_score` ∈ [0,1], and `reasoning`.
3. WHEN the input is a file path with a tenant-distinguishing prefix
   (e.g. `dev/jobs/JGLOBAL_*_POST` → `gw_sfs`), the recommender SHALL
   return that tenant with score ≥ 0.9 in position 1.
4. WHEN the input is a free-text topic (e.g. "ocean heat content"),
   the recommender SHALL semantically search every configured
   tenant's index and rank tenants by aggregated top-k similarity.
5. WHEN no tenant scores above 0.3, the recommender SHALL return a
   single result `{tenant_id: "gw", reasoning: "no strong match;
   falling back to canonical tenant"}`.
6. THE tool SHALL respond in under 1 second for path-based queries
   and under 3 seconds for semantic queries.

### Requirement 2: Tenant Attribution on Every Response

**User Story:** As an audit reviewer, I want every tool response
to carry full tenant provenance, so that I can reconstruct which
branch's code the agent reasoned over for any past query.

#### Acceptance Criteria

1. EVERY tool response from a Tenant_Aware_Tool SHALL include a
   Tenant_Attribution_Block in its rendered output (markdown footer
   block).
2. THE block SHALL include: `tenant_id`, `branch`, `repo_ref`,
   `lifecycle`, `data_freshness_iso` (timestamp of last ingestion for
   the tenant), and a server-generated `request_id`.
3. THE `request_id` SHALL be a UUID v4 generated per request and
   reused if the request includes a `correlation_id` field
   (forwards the client-supplied identifier).
4. THE `data_freshness_iso` SHALL be drawn from the tenant's most
   recent `last_ingested` timestamp in the unified manifest.

### Requirement 3: Audit Trail

**User Story:** As a security reviewer, I want a per-request log
record proving which tenant served which call, so that compliance
audits can be answered from a single artifact.

#### Acceptance Criteria

1. EVERY tool invocation SHALL append one JSONL record to
   `$AGENTCORE_AUDIT_LOG` (default
   `sdd_framework/execution_state/audit_trail.jsonl`).
2. THE record SHALL contain at minimum: `timestamp`, `request_id`,
   `tenant_id`, `tool_name`, `caller_principal` (IAM principal from
   the AgentCore context), and `tool_args_redacted` (tool args with
   any field matching `*_secret`/`*_token`/`*_key` replaced with
   `***`).
4. THE audit trail writer SHALL be best-effort: a write failure
   SHALL log a `[WARN]` and not block the tool response.
5. THE audit trail SHALL be readable by a new utility tool
   `get_audit_trail` that supports filtering by `tenant_id`,
   `tool_name`, and time range.

### Requirement 4: Multi-Tenant Routing in `mcp_health_check`

**User Story:** As an operator, I want the health check to confirm
all tenants are reachable, so that I can verify the routing layer
is working without ad-hoc shell scripts.

#### Acceptance Criteria

1. `mcp_health_check(functional=True)` SHALL fan out the existing
   per-module smoke queries to each configured tenant (in addition
   to the default tenant).
2. THE rendered output SHALL show the smoke matrix as a 2D table:
   rows = modules, columns = tenants, cells = pass/fail/skip.
3. WHEN any tenant×module cell fails, the overall status SHALL be
   `DEGRADED` rather than `HEALTHY`.

### Requirement 5: Performance & Cost Bounds

**User Story:** As an operator, I want routing overhead to be small
relative to the underlying tool latency, so that adding tenants does
not noticeably slow the system.

#### Acceptance Criteria

1. THE `which_pillar` tool's path-based path SHALL not query
   OpenSearch or Neptune; it SHALL match on configured prefix
   patterns only and SHALL respond in <100 ms.
2. THE `which_pillar` tool's semantic-search path SHALL run at
   most one query per tenant (parallelizable via `asyncio.gather`)
   and SHALL respond within `1s + 0.3s × num_tenants`.
3. THE Tenant_Attribution_Block SHALL add at most 200 bytes to a
   response (cheap relative to typical tool output of several KB).

### Requirement 6: Configuration & Discovery

**User Story:** As a developer, I want to enumerate available
tenants without reading the catalog file, so that my client tooling
can discover them dynamically.

#### Acceptance Criteria

1. `get_server_info(include_capabilities=True)` SHALL include a
   `tenants` array listing each tenant's `tenant_id`, `branch`,
   `repo_ref`, and `lifecycle`.
2. THE `which_pillar` tool's input schema SHALL declare an enum
   of valid tenant_ids in its `tenant_id` field for clients that
   want to override the recommendation.
