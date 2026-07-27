# Progress — MCP External Access (Path B, Cognito JWT on AgentCore Runtime)

Working memory for the kiro-cli engagement. The agent reads this at kickoff and
updates it after every task.

**Spec:** `.kiro/specs/mcp-external-access-revised/`
**Runtime:** `mdc_mcp_rag_server_python-v5K2F8BGrN` (Python, 52 tools, `python-tenants-v11`)
**Region:** us-east-1
**Account:** 903050880929

---

## Corrections (pre-seeded)

| # | Mistake/trap | Correction |
|---|---|---|
| C1 | The original spec references the Node.js runtime `mdc_mcp_rag_server-TMXDllG2Wi` (51 tools). | The active runtime is **Python** `mdc_mcp_rag_server_python-v5K2F8BGrN` (52 tools). All ARNs, endpoint URLs, and tool counts use this. |
| C2 | Task 0 expected HTTP 401. | The runtime returned **HTTP 403** ("Authorization method mismatch") — this is correct: it proves the endpoint is reachable and that no JWT authorizer is attached yet (SigV4-only). The gate passes. |
| C3 | The original design (AD-1) assumed Cognito supports RFC 8628 Device Flow. | It does NOT. The revised spec uses Auth Code + PKCE (Hosted UI) with SRP as headless fallback. |
| C4 | The original design (AD-3) used a Pre-Token-Generation trigger + DynamoDB for CI attribution. | Removed. Attribution is Token_Broker structured log + MCP Request_Metadata joined on the request id. |
| C5 | CDK stack name must NOT collide with the original spec's stack. | Use `MdcExternalAccessAlternativeStack` (AD-4). |
| C6 | The developer SigV4 path (`tools/agentcore-kiro-proxy.py`) must remain byte-identical. | R7 — do not modify it. Task 9 validates 52/52 tools still work via SigV4 after the authorizer is attached. |
| C7 | `PowerUserRestrictions` blocks `iam:CreateRole`. | CDK stack must use `fromRoleName`/`fromRoleArn` for any IAM roles that don't already exist. Admin pre-creates if needed (same pattern as the Neptune bulk-loader role). |

---

## Codebase Patterns

- **CDK stacks** live at `infrastructure/cdk/lib/`. Entry point `infrastructure/cdk/bin/cdk.ts`.
- **Admin IAM request docs** live at `docs/` (e.g. `docs/neptune-bulk-loader-role-request.txt`).
- **Runbooks** at `docs/runbooks/`.
- **Runtime env vars** (6): `DB_BACKEND=aws`, `NEPTUNE_ENDPOINT`, `OPENSEARCH_ENDPOINT`, `AWS_REGION=us-east-1`, `MCP_STATELESS_HTTP=true`, `MCP_WORKFLOW_ROOT=/app/supported_repos/global-workflow_develop`.
- **Task role:** `mdc-mcp-rag-ecs-task-role` (Neptune, OpenSearch, Bedrock, logs, X-Ray, secrets, SSM).
- **Network:** subnets `subnet-0e13af6b3a9a6416f`, `subnet-04447750c61bd7e06`; SG `sg-096489a0876cc78c1`.

---

## Key Facts for the Engagement

- **Public endpoint confirmed reachable** (2026-07-22): HTTP 403 from the Python runtime's public URL. No network/firewall block.
- **Current auth:** SigV4 only. The JWT authorizer will be *added alongside* SigV4, not replacing it (dual-auth: existing developer path unaffected).
- **GitHub OIDC provider** in AWS account: confirm whether it already exists before Task 3 creates it (may collide if another stack created it).
- **Cognito domain:** needs to be globally unique (e.g. `mdc-mcp-rag-auth`). Check availability.
- **`cdk diff` guardrail:** R12 requires showing `cdk diff` before any `cdk deploy` and recording it in the run log.

---

## Task 0 Gate Result

| Field | Value |
|---|---|
| Date | 2026-07-22 |
| Runtime | `mdc_mcp_rag_server_python-v5K2F8BGrN` |
| Endpoint | `https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/arn%3A.../invocations?qualifier=DEFAULT` |
| HTTP status | **403** |
| Response | `{"message":"Authorization method mismatch..."}` |
| Verdict | **PASS** — endpoint reachable; SigV4-only (JWT authorizer = Task 5) |
| Pivot needed? | **No** — no AgentCore Gateway required |

---

## Progress Log

| Date | Task | Result | Notes |
|---|---|---|---|
| 2026-07-22 | 0.1 | PASS (HTTP 403) | Endpoint reachable; SigV4-only; gate passes |
| 2026-07-22 | 0.2 | Pending | Record in `docs/reports/` |
| 2026-07-22 | 0.3 | PASS | No pivot needed; proceed to Task 1 |
