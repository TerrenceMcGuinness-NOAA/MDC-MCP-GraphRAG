# Decision Log — MCP External Access (supersedes parts of Path B)

**Date:** 2026-08-06
**Status:** Path B (Runtime-attached JWT) is INVALIDATED in part. **Path C (Gateway-fronted) adopted as the path forward.**
**Inputs:** RDHPC connectivity test (T. McGuinness, gaea64), AWS rep review, AWS AgentCore documentation.

---

## 1. Confirmed external findings

### F-1. RDHPC → AWS AgentCore egress works

```
Terry.McGuinness (gaea64) ~ $ curl --max-time 10 https://bedrock-agentcore.us-east-1.amazonaws.com
Invalid api path
```

DNS + TLS + HTTP egress from RDHPC (gaea64) to the AgentCore endpoint in `us-east-1`
succeeds. `Invalid api path` is an application-layer response from the AWS service,
which proves the request traversed the network and was served.

**Caveats to carry forward:**
- This is the **control-plane** host, not a Runtime data-plane invocation URL.
- The response is an API-path error, **not** the HTTP 401 that R8.5 / Task 0.3 specify as
  the gate condition.
- Under Path C the endpoint that actually needs verifying becomes the **Gateway**
  endpoint, so Task 0 must be rewritten rather than checked off.

**Effect:** the *network reachability* half of the R8.5 concern is satisfied. The
*authorizer behavior* half is now a different test against a different endpoint.

### F-2. Not operating inside a FedRAMP boundary

Confirmed. This resolves the highest-severity open question raised in
`docs/reports/2026-06-30-mcp-external-access-fedramp-control-mapping.md` (its follow-up
#1, "confirm AgentCore FedRAMP status / region before any further build").

**Effect:** the FedRAMP control mapping is **de-escalated from blocking to advisory**.
There is no boundary/region gate above the implementation tasks, and no forced GovCloud
migration. The report's remaining items (MFA, FIPS endpoints, customer-managed KMS,
audit retention reconciliation, GitHub interconnection, DoS posture) remain as
hardening backlog, not preconditions.

### F-3. Dual inbound auth at the Runtime is IMPOSSIBLE

From [Authenticate and authorize with Inbound Auth and Outbound Auth](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-oauth.html):

> An AgentCore Runtime can support either IAM SigV4 or JWT Bearer Token based inbound
> auth, but not both simultaneously.

The same note adds that you *can* create **different versions** of a Runtime configured
for different inbound auth types.

**This is a direct factual contradiction of the shipped design.** Design §7.4 currently
asserts:

> The AgentCore Runtime accepts a valid SigV4 signature **or** a valid Bearer JWT on the
> same endpoint when a JWT authorizer is configured; it rejects only requests that have
> neither.

That statement is wrong and must be struck.

### F-4. Gateway-fronting is the documented remedy

> You can front your AgentCore Runtime with an AgentCore Gateway so that the gateway
> becomes the single, governed entry point to the runtime

Documented benefits: policy-based authorization, Bedrock Guardrails, request/response
interceptors, unified observability — all applied outside the agent's own environment.

Two supporting mechanisms exist for preventing gateway bypass:

- **SigV4 runtime (our chosen shape):** attach a **resource-based policy** to the Runtime
  allowing only the gateway execution role, plus an explicit `Deny` on all other
  principals keyed on `aws:PrincipalArn`. The gateway assumes its service role to sign
  requests to the Runtime, so the gateway role is the invoking principal.
- **JWT runtime (not our shape):** `allowedWorkloadConfiguration` on the
  `customJWTAuthorizer`, using `hostingEnvironments` (gateway ARN) and/or
  `workloadIdentities`.

### F-5. `allowedScopes` DOES exist — OQ-2 resolves favorably

The authorizer configuration documents five fields, not three:

- `discoveryUrl` (must match `^.+/\.well-known/openid-configuration$`)
- `allowedAudience` → validated against `aud`
- `allowedClients` → validated against `client_id`
- **`allowedScopes`** → "validated against the scope claim in the JWT token. The
  `allowedScopes` authorization field will be configured as a list of strings."
- **Required custom claims** → validated against claim name and value

Also: "If both `client_id` and `aud` is provided, the agent runtime authorizer will
verify both."

**Effect:** R2.1 ("non-empty list of allowed scopes") and R2.3 (verify `scope` claim) are
**satisfiable as written**. The concern that these were unimplementable is withdrawn.
Note the doc states the authorizer config shape is **identical for Runtime or Gateway**,
so this carries over to the Gateway unchanged.

### F-6. Claims propagation mechanism differs from the design's assumption

Design AD-6 assumes AgentCore forwards
`X-Amzn-Bedrock-AgentCore-Runtime-Custom-Authorizer-Claims` (base64url JSON) to the
container, and treats **absence** of that header as the `developer-sigv4` principal.

The documentation describes a different, opt-in mechanism: Step 7, "Propagate a JWT token
to AgentCore Runtime," which requires an explicit **request header allowlist**
(`RequestHeaderConfiguration`) to pass `Authorization` through, after which the agent
decodes claims itself with signature validation skipped (already validated upstream).

No mention of the `...Custom-Authorizer-Claims` header appears in this document. **AD-6's
propagation mechanism is unverified and likely incorrect as written.**

---

## 2. Adopted decision: Path C

**Shape:** Runtime stays on **default IAM SigV4** inbound auth. An **AgentCore Gateway**
fronts it and holds the **Cognito JWT authorizer**. JWT-bearing requests from CI and HPC
terminate at the Gateway; the Gateway signs SigV4 to the Runtime — the same call shape the
developer path already uses today.

**Why this is now the only coherent option:**

1. F-3 makes simultaneous JWT + SigV4 at the Runtime impossible, and the developer SigV4
   path is a hard requirement (R7.2, Property 6).
2. Keeping the Runtime on SigV4 means the developer path needs **zero change** — R7.2 and
   Property 6 are satisfied trivially rather than by regression-testing a coexistence
   behavior that does not exist.
3. The Gateway URL becomes the stable public endpoint, so Runtime redeploys stop forcing
   URL changes in CI workflows and HPC configs (already noted as a Path C benefit in
   design §14).

**Rejected alternative:** two Runtime *versions*, one SigV4 and one JWT (permitted per
F-3). Rejected because it doubles the endpoint surface, splits observability, doubles
drift-detection scope, and still leaves tool-level authorization duplicated in the MCP
server — while the Gateway exists precisely to be the single governed entry point.

---

## 3. What this invalidates in the shipped spec

| Item | Location | Status |
|---|---|---|
| SigV4/JWT coexistence on one endpoint | design §7.4 | **FALSE — strike entirely** |
| AD-6 absence-of-header ⇒ `developer-sigv4` | design AD-6, §8.2 | **Unverified mechanism; redesign** |
| R2.9 (SigV4 coexistence with authorizer) | requirements | **Unsatisfiable as written** |
| R7.2 / Property 6 (developer path preserved) | requirements, §13 | **Intent preserved, mechanism changes** — satisfied by Runtime staying SigV4 |
| Task 5.x (authorizer on Runtime) | tasks | **Retarget to Gateway** |
| AD-2 / R8.5 / R8.6 / Task 0 | design §11.2–11.3 | **Reframe** — public entry point is now the Gateway |
| "Path C — Deferred" framing | design §14, R11 | **Path C is now the baseline, not deferred** |
| OQ-2 (`allowedScopes` may not exist) | design §16 | **RESOLVED — the field exists (F-5)** |
| Cost/maturity/schedule rationale for deferring C | design §14 Rationale | **Moot — deferral is no longer available** |

**What survives intact and is directly reusable:**

- **AD-1** (PKCE primary + SRP fallback) — unaffected; Cognito-side only.
- **AD-3** (Token_Broker log-join on `broker_request_id`) — unaffected, and design
  §14 C-IMPACT-4 already anticipated that a Gateway interceptor can record the same
  field with no Cognito change.
- **All of §3** (Cognito user pool, resource server, scopes, both app clients) — the
  authorizer config shape is identical for Gateway per F-5.
- **§4** Token_Broker Lambda, **§5** composite action, **§6** HPC_CLI_Helper — all
  produce/consume tokens without caring where the authorizer is attached.
- **§10** tool enumeration (40 / 48 / 51) — content survives; enforcement point moves.
- The four **C-IMPACT** decisions in §14 were written to keep this migration cheap. They
  did their job: audit emission is stateless, scope enumeration is explicit
  default-deny, and consumers read `McpEndpointUrl` rather than hard-coded URLs.

---

## 4. New open decision points created by Path C

> **All decision points CLOSED as of 2026-09-05.** See the revised status table in Part 2
> and the Path C spec's `design.md` §9 (Gate Register) for full evidence.

**DP-1 — How does principal/scope context reach the MCP_Server? (highest priority)**
~~OPEN~~ → **CLOSED.** Option (a) chosen: Gateway REQUEST interceptor injects
`X-Amzn-Bedrock-AgentCore-Runtime-Custom-{Principal,Scope,BrokerRequestId}`. Interceptor
headers take precedence over client headers (unforgeability). §8 middleware reads those.
See F-8 and Path C design AD-C2.

**DP-2 — Does the bypass-prevention resource policy break the developer path?**
~~OPEN~~ → **CLOSED.** Posture (a) chosen: no Runtime lockdown. No resource-based policy
attached. Defense-in-depth from Gateway JWT authorizer + interceptor + MCP_Server
Allowed_Tool_Set is sufficient. See Path C design AD-C5.

**DP-3 — Gateway target semantics and tool naming.**
~~OPEN~~ → **CLOSED.** Runtime targets forward without aggregation or protocol translation;
tool names unchanged. See F-7 and Path C design AD-C1.

**DP-4 — Gateway execution role trust hardening.**
~~OPEN~~ → **CLOSED.** Gateway_Execution_Role trust policy carries `aws:SourceArn` and
`aws:SourceAccount` conditions scoped to the Gateway ARN (confused-deputy prevention).
See Path C design AD-C6, implemented in Task 2.3.

**DP-5 — Spec disposition.**
~~OPEN~~ → **CLOSED.** New spec created: `.kiro/specs/mcp-external-access-alternative-gateway/`.
This spec (`mcp-external-access-revised`) retained as historical reference. Naming split
resolved in the new spec.

**DP-6 — Cost.**
~~OPEN~~ → **CLOSED — GO.** Under $1/month at projected volume (18K–72K external
invocations/month). Lambda free tier covers the interceptor invocations. See Path C
design §8a.

---

## 5. Pre-existing issues still open (from prior review)

- **Naming split:** directory is `mcp-external-access-revised`, but requirements/design
  refer throughout to `.kiro/specs/mcp-external-access-alternative/`, including in binding
  criteria R8.5, R11.1, R11.3, R11.4 and every `Feature:` property tag. R11.6 is
  self-executing on this. Resolve during DP-5.
- ~~**`MdcServerStack` missing**~~ — **CORRECTED in Part 4.** `mdc-server-stack.ts` has never
  existed in *any* branch, so this is a long-standing unresolved import in `bin/cdk.ts`, not
  a missing-branch problem. It did not block the Path B engagement, which synthed its own
  stack successfully.
- ~~**Implementation state is zero**~~ — **WRONG. CORRECTED in Part 4.** Path B Tasks 0–5 are
  implemented on `feature/congnito_endpoint` (~1,243 lines, 53/53 CDK tests passing, **not
  deployed**). The "zero" observation was true of `develop` only, which was the wrong base to
  judge from.

---

## 6. Recommended next actions

> **All actions COMPLETED.** Path C spec created and implemented via
> `mcp-external-access-alternative-gateway` Tasks 0–7.

1. ~~Strike design §7.4 and mark AD-6 / R2.9 as superseded.~~ **DONE** — superseded in Path C spec.
2. ~~Resolve **DP-1**.~~ **DONE** — interceptor header injection (AD-C2).
3. ~~Create `.kiro/specs/mcp-external-access-alternative-gateway/`.~~ **DONE** — spec created per DP-5.
4. ~~Decide **DP-2** before writing any resource-based policy.~~ **DONE** — posture (a), no lockdown (AD-C5).
5. ~~Re-scope Task 0.~~ **DONE** — Task 0 verified JWT-in / SigV4-out through a Gateway.

---

## Sources

- [Authenticate and authorize with Inbound Auth and Outbound Auth — Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-oauth.html)
- [Configure inbound JWT authorizer — Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/inbound-jwt-authorizer.html)
- [Set up inbound authorization for your gateway — Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-inbound-auth.html)

*Content from AWS documentation was rephrased for compliance with licensing restrictions; direct quotations are kept short and attributed inline.*


---

# Part 2 — Path C mechanism research (2026-08-06, same day)

Follow-up investigation to resolve DP-1 and DP-3. Outcome: **both resolved**, one new
blocking issue found (DP-7), and one architecture fork surfaced that changes the shape of
the recommendation (DP-8).

## F-7. DP-3 RESOLVED — Runtime targets do not rename or aggregate tools

From [AgentCore Runtime targets](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-http-runtime.html):
the gateway routes traffic straight to the runtime with no aggregation and no protocol
translation, forwarding requests and responses between client and runtime agent
unmodified — explicitly unlike MCP targets, which merge tool capabilities into one
unified virtual MCP server.

**Effect:** §10's 40 / 48 / 51 tool enumeration survives byte-for-byte. No prefixing, no
renaming, no client-config churn on tool names.

**But three consequences to absorb:**
- **No capability sync and no semantic tool search** for Runtime targets. Clients must
  know exact tool names or call the server's own `tools/list`.
- **Path-based routing** — the endpoint becomes
  `https://{gatewayId}.gateway.bedrock-agentcore.{region}.amazonaws.com/{targetName}/invocations`.
  This is the new `McpEndpointUrl` value (C-IMPACT-3 anticipated exactly this).
- **Gateway protocol type must be unset.** Runtime targets can be added to gateways with
  no protocol type set, and *cannot* be added to MCP-protocol-type gateways.

## F-8. DP-1 RESOLVED — interceptor Lambda header injection is the designed channel

Under SigV4 outbound, the Runtime sees a signed request from the gateway execution role,
so JWT claims do not arrive on their own. The supported remedy is a **REQUEST interceptor
Lambda** that injects headers, per
[Header propagation with Gateway](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-headers.html):

- Interceptor-returned headers merge with the target allowlist
  (`metadataConfiguration.allowedRequestHeaders`).
- **Interceptor-provided headers take precedence over client-provided headers on
  conflict.** This is the anti-spoofing property we need — a CI or HPC caller cannot forge
  its own principal or scope. The docs name this use case directly: inject context derived
  from authenticated user claims rather than trusting client-supplied values.
- **`X-Amzn-` prefixed headers are prohibited *except* `X-Amzn-Bedrock-AgentCore-Runtime-Custom-*`.**
  That is a purpose-built channel for runtime-bound custom context — use it.
- `Authorization` cannot be allowlisted at target creation, **but is forwarded when
  supplied by an interceptor Lambda**. So passing the original JWT through is also possible.
- `passRequestHeaders: true` is required for the interceptor to see inbound headers at all.
  The docs flag this as sensitive (headers carry tokens); ensure the interceptor does not
  log them.

**Recommended DP-1 resolution:** REQUEST interceptor validates nothing (Gateway authorizer
already did), reads claims, and injects
`X-Amzn-Bedrock-AgentCore-Runtime-Custom-Principal`, `-Scope`, and `-BrokerRequestId`.
The MCP_Server middleware (§8) reads those instead of
`X-Amzn-Bedrock-AgentCore-Runtime-Custom-Authorizer-Claims`. AD-6's *intent* survives; only
the header names and their producer change. **AD-3's log-join keys on `broker_request_id`,
which rides through as one of these headers — attribution survives unchanged.**

Hard limits to design against: **max 10 request headers per target**, 4 KB per value,
printable ASCII only, names matching `^[a-zA-Z0-9_-]+$`.

**Bonus for §9 audit:** for HTTP targets the gateway passes `GATEWAY_ARN`,
`GATEWAY_ACCOUNT_ID`, `REQUEST_ID`, and `SOURCE_IP` to the Lambda via **client context**
(`SOURCE_IP` is optional — treat as may-be-absent). `SOURCE_IP` is otherwise hard to obtain
and is useful for the audit schema.

## F-9. Gateway CANNOT see tool names for a Runtime target — corrects the §14 Path C vision

Runtime targets use the **`http`** interceptor payload, not the `mcp` one. Differences that
matter:

| | MCP target | HTTP / Runtime target |
|---|---|---|
| Body format | parsed JSON (`Map<String,Object>`) | **base64-encoded string** |
| Path | always `/mcp` | actual path, e.g. `/my-target/invocations` |
| `rawGatewayRequest` | included | not included |
| Response interceptor | supported | **buffered mode only** |

Because the body is an opaque base64 string, **the gateway does not parse JSON-RPC and
therefore has no native view of `tools/call` or the tool name.** Design §14 asserted Path C
would bring "Cedar tool-level policies … evaluated per tool invocation, replacing the
single `allowedToolSets.js` enumeration." **That is not available in the Runtime-target
shape.** Two workable options instead:

- **(a) Keep tool gating in the MCP_Server.** §8 middleware and §10 enumeration survive
  essentially intact — a much smaller change than "Path C deletes §8."
- **(b) Enforce in the interceptor.** The Lambda base64-decodes the body, parses JSON-RPC,
  reads `params.name`, and on denial returns `transformedGatewayResponse` — which
  **short-circuits: the gateway replies immediately without calling the target, and the
  RESPONSE interceptor does not run.** This is a clean 403 path but re-implements §10 in a
  Lambda.

**Recommendation: (a), with (b) available later as defense-in-depth.** This preserves the
most existing design and is the least-risk path.

## F-10. NEW BLOCKING ISSUE — DP-7: interceptors are buffered-only, our server streams

Two facts that collide:

1. Runtime targets support SSE streaming, **but** "Request and response interceptor Lambda
   functions are supported in buffered mode. Interceptors are not yet supported in
   streaming mode."
2. Our deployed server is **FastMCP Streamable HTTP**. Confirmed in-repo:
   `mcp_server_python/src/mcp_server.py:331-336` defaults `--transport` to
   `streamable-http` (comment: "AgentCore/gateway"), and
   `mcp_server_python/src/config/environment.py:80` documents host/port as "Address for
   FastMCP's Streamable HTTP listener (Requirement 1.1)", port 8000
   (`src/config/aws_config.py:18`).

> **ERRATUM (corrected in Part 3):** this paragraph originally claimed no `stateless_http`
> setting existed either. **That was wrong** — `stateless_http` *is* already set and is
> required for AgentCore. The grep behind that claim truncated before reaching it. Only
> `json_response` is genuinely absent. See F-14 for the corrected, empirically verified
> position.

`json_response` is absent from `mcp_server_python/src/`. FastMCP's streamable-http default
returns SSE for responses, so as currently written **the interceptor may never fire — which
would silently remove the entire DP-1 claims channel and, with it, all principal/scope
enforcement and audit attribution.** Same failure mode as the original AD-3 defect: tokens
validate, calls succeed, governance data is absent.

**DP-7 (~~blocking~~ → **CLOSED**): ~~confirm whether the MCP server must be pinned to
buffered/JSON-response mode for interceptors to run, and whether doing so is acceptable for
tool latency and payload size.~~ **RESOLVED.** Server pinned to `json_response=True`;
interceptors confirmed firing empirically via Task 0 throwaway Gateway. Developer proxy made
framing-tolerant (v1.2.0). See Path C design AD-C4, AD-C7.**

**Related constraint:** Lambda synchronous invoke has a **6 MB combined request+response
payload limit**, and the base64-encoded body counts against it. For a RAG server returning
search results this is a live risk. Mitigation is documented: configure a payload filter
excluding `RESPONSE_BODY`, after which the interceptor still sees `statusCode`,
`contentType`, and `headers`, can inject headers, and can override status — and returning
`body: null` leaves the original response untouched. Our audit needs only metadata, so this
mitigation fits well.

## F-11. Outbound auth has four modes — one preserves §8 with no interceptor at all

AgentCore Runtime targets support: **IAM (SigV4)** (gateway assumes its service role to
sign — the chosen model), **caller IAM credentials**, **OAuth (JWT)** via credential
providers, and **token passthrough** — where the gateway validates the inbound token and
forwards it to the target unmodified, described as useful when the runtime handles its own
authorization.

**Token passthrough is a near-exact fit for the existing §8 design** (server reads the JWT
itself). But it requires the Runtime's *inbound* auth to accept that JWT, i.e. a
JWT-inbound Runtime — which reintroduces F-3's either/or and loses the "developer SigV4
needs zero change" benefit that motivated Path C. **Logged as a considered-and-rejected
alternative**, not a recommendation.

## F-12. DP-2 update — bypass prevention now exists for both inbound types

The docs now state you can enforce gateway-only access regardless of whether the runtime
uses SigV4 or JWT inbound: the gateway stamps the source of each forwarded request and the
runtime validates it. SigV4 runtimes use a resource-based policy scoped to the gateway
execution role; JWT runtimes use `allowedWorkloadConfiguration`.

**DP-2 remains an open decision, unchanged in substance:** the documented SigV4 policy
denies all principals except the gateway role, which would sever the developer path. Decide
explicitly between not locking down, or adding developer role ARNs to the `ArnNotEquals`
exception set. DP-4 (trust-policy hardening with `aws:SourceArn` / `aws:SourceAccount`)
still applies.

## F-13. Guardrails need a schema — but not for us

Runtime targets accept an optional `schema` (S3 URI or `inlinePayload`, OpenAPI or Smithy,
auto-detected) used by the gateway policy engine for features such as guardrails. HTTP
protocol runtimes must supply one; **runtimes using MCP or A2A get a default schema
automatically.** Ours is MCP, so no schema authoring is required unless we want guardrails
beyond the default.

---

## NEW DP-8 — architecture fork: Runtime target vs MCP target (CLOSED)

> **CLOSED.** Runtime target chosen (Path C design AD-C1). MCP target not needed for two
> consumer classes. Confirmed empirically: interceptors fire, headers propagate. MCP target
> retained as future option if per-tool Cedar policy becomes a hard requirement.

This is the decision that most affects the follow-on spec, and it was not visible before
this research.

| | **Runtime target** (as proposed) | **MCP target** |
|---|---|---|
| Gateway sees tool names | No — opaque base64 body | **Yes — parsed JSON-RPC** |
| Tool aggregation / `tools/list` | No, isolated | Yes, unified virtual MCP server |
| Semantic tool search | No | Yes |
| Per-tool Cedar policy | Not natively (F-9) | Natively feasible |
| Response interceptor | Buffered only | Supported |
| Endpoint needed | Runtime ARN + qualifier only | Reachable MCP endpoint |
| Gateway protocol type | must be **unset** | MCP |

An MCP target would deliver the §14 Path C vision as originally written (Cedar per-tool
policy, aggregation) and sidesteps the base64/tool-name problem — and AgentCore Gateway
supports **VPC egress to self-hosted MCP servers via private endpoints backed by VPC
Lattice**, so a private MCP endpoint is achievable. The cost is a different hosting story
than "front the existing Runtime."

**Recommendation: proceed with the Runtime target** (matches the adopted decision, minimal
change, keeps §8/§10) **and record MCP-target as the fallback** if DP-7 rules out
interceptors or if per-tool Cedar policy later becomes a hard requirement. Note the two are
mutually exclusive on a single gateway because of the protocol-type constraint in F-7.

---

## Revised decision-point status

> **All decision points CLOSED as of 2026-09-05.** Final resolutions recorded during
> Path C implementation (`mcp-external-access-alternative-gateway`). See that spec's
> `design.md` §9 (Gate Register) for the full evidence trail.

| DP | Status |
|---|---|
| DP-1 claims propagation | **CLOSED.** Resolved via Gateway REQUEST interceptor injecting `X-Amzn-Bedrock-AgentCore-Runtime-Custom-{Principal,Scope,BrokerRequestId}`. Interceptor-supplied headers take precedence over client-supplied headers (unforgeability confirmed empirically). §8 middleware reads those headers; absence ⇒ `developer-sigv4`. See Path C design AD-C2. |
| DP-2 bypass policy vs developer path | **CLOSED.** Posture (a) chosen: no Runtime resource-based policy attached. Defense-in-depth from Gateway JWT authorizer + interceptor header injection + MCP_Server Allowed_Tool_Set enforcement is sufficient. No risk of severing the developer SigV4 path. See Path C design AD-C5. |
| DP-3 tool naming | **CLOSED.** Runtime targets forward without aggregation or protocol translation; tool names unchanged. §10 enumeration survives. See F-7 and Path C design AD-C1. |
| DP-4 gateway role trust hardening | **CLOSED.** Gateway_Execution_Role trust policy carries `aws:SourceArn` and `aws:SourceAccount` conditions scoped to the Gateway ARN (confused-deputy prevention). See Path C design AD-C6. |
| DP-5 spec disposition | **CLOSED.** New spec created: `.kiro/specs/mcp-external-access-alternative-gateway/`. Path B spec (`mcp-external-access-revised`) retained as historical reference; Path C is the active implementation. Naming split resolved. |
| DP-6 gateway cost | **CLOSED — GO.** Under $1/month at projected volume (18K–72K external invocations/month). Lambda free tier covers the interceptor. See Path C design §8a. |
| DP-7 buffered vs streaming | **CLOSED.** Interceptors fire for `agentcoreRuntime` targets with JSON framing (`FASTMCP_JSON_RESPONSE=true`). Confirmed empirically via throwaway Gateway + Echo Interceptor Lambda (Task 0 verification). Server pinned to `json_response=True` with env override (Task 3). Developer proxy made framing-tolerant (v1.2.0, AD-C7). |
| DP-8 Runtime vs MCP target | **CLOSED.** Runtime target chosen (AD-C1). MCP target not needed for two consumer classes (CI, HPC). Confirmed empirically: interceptors fire, headers propagate. MCP target retained as future option if per-tool Cedar policy becomes a hard requirement. |

## Revised next actions

> **All actions COMPLETED.** Path C implementation landed via
> `mcp-external-access-alternative-gateway` Tasks 0–7.

1. ~~**Answer DP-7 first.**~~ **DONE** — Task 0 empirical verification (throwaway Gateway).
2. ~~Decide DP-8 once DP-7 is known.~~ **DONE** — Runtime target confirmed (AD-C1).
3. ~~Decide DP-2 before any resource-based policy is written.~~ **DONE** — Posture (a), no lockdown (AD-C5).
4. ~~Then create the follow-on spec (DP-5).~~ **DONE** — `mcp-external-access-alternative-gateway/`.
5. ~~Re-scope Task 0 to verify JWT-in / SigV4-out through a Gateway.~~ **DONE** — Task 0.1–0.6.

## Additional sources (Part 2)

- [Amazon Bedrock AgentCore Runtime targets](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-http-runtime.html)
- [Header propagation with Gateway](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-headers.html)
- [Types of interceptors](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-interceptors-types.html)
- [Using interceptors with Gateway](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-interceptors.html)
- [Configure AgentCore Gateway VPC Egress for Gateway Targets](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-vpc-egress.html)

*AWS documentation content was rephrased for compliance with licensing restrictions; direct quotations are kept short and attributed inline.*


---

# Part 3 — DP-7 empirically narrowed (2026-08-06)

## Erratum against Part 2

Part 2 (F-10) stated that neither `json_response` nor `stateless_http` was set in
`mcp_server_python/src/`. **The `stateless_http` half of that was wrong.** The grep behind
it was truncated by `head -20` and never reached the relevant lines. Corrected position
below. Only `json_response` is genuinely absent.

## F-14. `stateless_http` is already set — and is mandatory for AgentCore

`mcp_server_python/src/mcp_server.py` (lines ~399–418) already passes
`stateless_http=stateless` to `mcp.run()`, defaulting to **true** via the
`MCP_STATELESS_HTTP` env var. The in-code comment documents why, and it is worth preserving
as institutional knowledge:

- AgentCore generates its own `Mcp-Session-Id` per request and expects the server to accept
  it rather than mint one.
- Stateful mode rejects the platform-supplied ID with **HTTP 400**, which AgentCore
  surfaces to the client as a 500-class runtime error.
- Load balancing and microVM affinity are handled by the platform, so stateless is correct
  server-side.

**Do not change this.** `MCP_STATELESS_HTTP=false` exists only for local multi-turn
elicitation/sampling development.

Note that `stateless_http` and `json_response` are **orthogonal**. Stateless controls
session handling; `json_response` controls response framing. Setting the former does not
avoid SSE.

## F-15. `json_response` is supported by the pinned FastMCP, and is an env-var flip

Verified against the actually pinned version (`fastmcp==3.2.4`,
`mcp_server_python/pyproject.toml:20`) by installing it and introspecting:

- `FastMCP.run(transport=None, show_banner=None, **transport_kwargs)` forwards to
  `run_async`, which forwards to `run_http_async`.
- `run_http_async(...)` accepts **`json_response: bool | None = None`** alongside
  `stateless_http: bool | None = None`. `http_app(...)` accepts it too.
- `fastmcp.settings.Settings` defaults: **`json_response = False`**,
  `stateless_http = False`, `streamable_http_path = "/mcp"`.
- FastMCP's own guidance for the setting names the env var **`FASTMCP_JSON_RESPONSE`** as an
  alternative to passing the kwarg.

**Consequence: the fix requires no code change.** Setting `FASTMCP_JSON_RESPONSE=true` in
the AgentCore Runtime container environment is sufficient. Adding an explicit
`json_response=` kwarg to `mcp.run()` remains available if we prefer it pinned in code
rather than in environment config — recommend the kwarg with an env override, mirroring how
`stateless_http` is already handled, so the behavior is not silently reconfigurable.

## F-16. Empirical confirmation that this actually removes SSE framing

Ran two real FastMCP 3.2.4 streamable-http servers on loopback and issued an MCP
`initialize` with `Accept: application/json, text/event-stream`:

| `json_response` | Response `Content-Type` | First bytes |
|---|---|---|
| `False` (today's effective default) | `text/event-stream` | `event: message\r\ndata: {"jsonrpc":"2.0",...` |
| `True` | `application/json` | `{"jsonrpc":"2.0","id":1,"result":{...` |

This confirms both halves of the concern:

1. **As deployed today the server emits SSE**, which is precisely the mode in which
   AgentCore documents interceptors as unsupported for HTTP/Runtime targets. DP-7 was a
   real risk, not a theoretical one.
2. **The mitigation works and is cheap** — one setting flips the wire format to plain
   `application/json`.

This is also consistent with the MCP specification itself, which states a server answers
each request with either a single JSON object or an SSE stream scoped to that request —
so single-JSON is spec-compliant, not a degradation.

## Revised DP-7 status

**DP-7 is CLOSED.** Both halves resolved.

- **Server side: RESOLVED.** `json_response=True` pinned in `mcp_server.py` with
  `MCP_JSON_RESPONSE` env override (Task 3). Developer proxy made framing-tolerant in
  v1.2.0 (AD-C7), so the server-wide JSON framing does not break the SigV4 developer path.
- **AWS side: RESOLVED.** Empirically confirmed via Task 0 throwaway Gateway + Echo
  Interceptor Lambda: REQUEST interceptors fire for `agentcoreRuntime` targets when the
  server responds with `application/json`. The interceptor correctly injected
  `Custom-Principal: probe` and stripped forged client headers.

**Costs accepted:** disabling SSE forfeits incremental `notifications/progress` and
stream-based elicitation/sampling. Acceptable for CI and HPC (discrete `tools/call`
request/response). R3.4 emits a WARNING log if `json_response` is ever disabled.

## Additional sources (Part 3)

- [MCP specification — Streamable HTTP transport](https://modelcontextprotocol.io/specification/draft/basic/transports/streamable-http)
- `fastmcp==3.2.4` package introspection (`FastMCP.run_http_async`, `fastmcp.settings.Settings`)


---

# Part 4 — Branch reconciliation and prior-art discovery (2026-08-06)

This part corrects two factual errors in Parts 1–2 that arose from working off the wrong
base branch, and records the branch topology so the mistake is not repeated.

## F-17. Branch topology — `develop_aws` is STALE, not ahead

Measured against `origin`:

| Branch | vs `develop` | Tip | Specs | Verdict |
|---|---|---|---|---|
| `develop` | — | `77469e9` 2026-07-20 | 61 | **Current mainline** |
| `develop_aws` | **0 ahead, 56 behind** | `570a118` 2026-06-17 *"account closure notice and transition announcement"* | 44 | **Stale. Fully contained in `develop`.** |
| `develop_aws_startpoint` | — | — | — | Historical marker |
| **`feature/congnito_endpoint`** | **3 ahead, 0 behind** | `9d089f4` 2026-07-27 | 61 + impl | **The branch that matters** |

`git merge-base --is-ancestor origin/develop_aws origin/develop` returns true: **`develop_aws`
contains nothing that `develop` lacks.** Branching from `develop` was correct. The branch
carrying the external-access work is **`feature/congnito_endpoint`**, which is a strict
superset of `develop` (3 ahead, 0 behind).

**Currency rule going forward:** this work must stay rebased on
`feature/congnito_endpoint` while that branch is open, and on `develop` after it merges.
Verified at time of writing: **0 behind `develop`, 0 behind `feature/congnito_endpoint`.**

## F-18. ERRATUM — "implementation state is zero" was WRONG

Part 1 §5 asserted zero implementation. That was true of `develop` and false of the
repository. `feature/congnito_endpoint` carries **Path B Tasks 0–5 implemented** by
T. McGuinness on 2026-07-27 (~1,243 insertions):

| Artifact | Lines |
|---|---|
| `infrastructure/cdk/lib/mdc-external-access-alternative-stack.ts` | 414 |
| `infrastructure/cdk/test/mdc-external-access-alternative-stack.test.ts` | 306 |
| `docs/mdc-external-access-alt-iam-request.txt` | 203 |
| `infrastructure/cdk/lambda/token_broker/index.py` | 130 |
| `infrastructure/cdk/lambda/token_broker/test_index.py` | 91 |
| `infrastructure/cdk/scripts/authorizer-drift-detector.sh` | 58 |
| `infrastructure/cdk/bin/cdk.ts` (wiring) | +15 |
| `infrastructure/cdk/snapshots/authorizer-config.json` | 8 |

Status: **53/53 CDK tests passing, `cdk synth` clean, stack NOT deployed.** Cognito user
pool, both app clients, resource server with exactly two scopes, Token_Broker Lambda, CI
secret shell, and the authorizer custom resource are all authored.

**This is good news, not rework.** As the C8 note itself says, all Cognito, Token_Broker,
OIDC, and CDK work carries forward regardless of the Path B/C outcome — only the last-mile
routing changes. Path C is now largely a matter of *adding* a Gateway and *not* applying the
authorizer custom resource to the Runtime.

## F-19. C8 — the dual-auth risk was found empirically here, three weeks before our doc proof

The Path B engagement flagged this independently. Task 0 ran **2026-07-22** and returned
**HTTP 403** (not the expected 401) with:

> Authorization method mismatch. The agent is configured for a different authorization
> method than what was used in your request … ensure your request uses the matching method
> (OAuth or SigV4)

Correction **C8** and design **§11.3a** (added 2026-07-27) drew exactly the right inference
from "(OAuth **or** SigV4)": that AgentCore Runtime may enforce a **single** inbound auth
mode, so attaching `customJWTAuthorizer` would **break the developer SigV4 path**. The gate
was recorded as UNRESOLVED, three resolution options were documented, and — importantly —
**the stack was deliberately not deployed.** That call prevented a live outage.

**Our AWS documentation finding (F-3) resolves C8 definitively: single-mode is confirmed.**
Per §11.3a's own decision table, the mandated action is:

> AWS confirms **single-mode** (JWT replaces SigV4) → Execute the §11.3 Path C Gateway
> pivot: front the Runtime with an AgentCore Gateway that accepts JWT; Runtime stays
> SigV4-only; developer path unaffected

That is precisely the Path C decision recorded in Part 1. **C8 is now RESOLVED → pivot
confirmed.** The one action C8 forbids — `cdk deploy` of the authorizer custom resource
against the live Runtime — must remain forbidden.

Also note C2: the 403 was correctly read as a **pass** for reachability (endpoint live, no
JWT authorizer attached yet). So the R8.5 network gate was satisfied back in July; our
Part 1 note that Task 0 was "unrecorded" was true only of `develop`.

## F-20. Hard-won platform constraints that Path C must inherit

From `progress.md` on `feature/congnito_endpoint`. These are expensive to rediscover and
several would have broken the Path C spec as first drafted:

| # | Constraint | Effect on Path C |
|---|---|---|
| **C1** | Active runtime is **Python** `mdc_mcp_rag_server_python-v5K2F8BGrN`, artifact `python-tenants-v11`, **52 tools** — not the retired Node runtime (51 tools) | **Path C spec corrected**: developer count 52; the CI 40 / HPC 48 split must be **re-derived** (new R5.6, Task 5.3a) since it was computed against 51 tools |
| **C7** | `PowerUserRestrictions` blocks `iam:CreateRole` | **Path C spec corrected**: Gateway_Execution_Role and interceptor role must be *imported* via `fromRoleName(mutable:false)` and added to the admin IAM request, not created (new R8.6, Task 2.3) |
| **C12** | Constructs that implicitly create custom-resource Lambdas pull in auto-created roles → also blocked; guarded by a test asserting `AWS::IAM::Role` count == 0 | **New R8.7.** Relevant: our interceptor Lambda must use an imported execution role |
| **C9** | `update-agent-runtime` is a **full-replacement** API; partial payloads wipe `networkConfiguration`, `environmentVariables`, `protocolConfiguration`, `roleArn`, `agentRuntimeArtifact`, `lifecycleConfiguration` | **New R8.8.** Mostly moot under Path C (R2.3 forbids touching the Runtime authorizer) but must be honoured if the Runtime is ever updated |
| **C10 / C11** | GitHub OIDC provider and the three IAM roles do **not** exist in account 903050880929; admin-created and imported | Inherited unchanged; same admin doc extends to Path C's two new roles |
| **R12 note** | `cdk diff` emits **no output** in staging (no CloudFormation `GetTemplate` connectivity) | **New R8.9.** Operator must run the real `cdk diff` at deploy time; synth + resource-type assertions are a substitute only in-environment |

Environment facts also inherited: region `us-east-1`, account `903050880929`, task role
`mdc-mcp-rag-ecs-task-role`, subnets `subnet-0e13af6b3a9a6416f` /
`subnet-04447750c61bd7e06`, SG `sg-096489a0876cc78c1`, Hosted UI domain
`mdc-mcp-external-alt` (availability verified). Note the live runtime env sets
`MCP_STATELESS_HTTP=true`, consistent with F-14.

## Merge staging (no merge performed)

Per instruction, **nothing has been merged.** Current state:

- Branch `spec/mcp-external-access-path-c-decision` **rebased onto
  `origin/feature/congnito_endpoint`** — clean, no conflicts.
- 0 behind `develop`; 0 behind `feature/congnito_endpoint`.
- Three commits, spec/docs only. **No CDK, Lambda, or server code modified**, so nothing is
  deployable and nothing can regress the Path B implementation.

**Alignment needed before merge** (open questions, not blockers to review):

1. Does `feature/congnito_endpoint` merge to `develop` first, with this branch following?
   Or does this branch retarget its MR at `feature/congnito_endpoint`?
2. Should Path C's implementation continue **on** `feature/congnito_endpoint` (keeping the
   authorizer custom resource in-tree but unapplied), or on a fresh branch off it?
3. Confirm the authorizer custom resource stays **unapplied** — C8's prohibition still binds
   and is now permanent, not provisional.

---

# Part 5 — All decision points CLOSED (2026-09-05)

**Status:** All eight decision points (DP-1 through DP-8) are now **CLOSED** with final
resolutions. Path C implementation is complete via
`.kiro/specs/mcp-external-access-alternative-gateway/` Tasks 0–7.

This part records the final closure for cross-reference. The inline annotations on each DP
definition (§4 and Part 2 findings) and the revised status table (Part 2) have been updated
in place. The Path C spec's `design.md` §9 (Gate Register) is the authoritative evidence
trail for each closure.

## Final DP resolution summary

| DP | Resolution | Path C reference |
|---|---|---|
| **DP-1** Claims propagation | Gateway REQUEST interceptor injects `X-Amzn-Bedrock-AgentCore-Runtime-Custom-{Principal,Scope,BrokerRequestId}`. Interceptor headers take precedence over client headers (unforgeability). | AD-C2, Task 0.3–0.4, Task 4 |
| **DP-2** Bypass prevention vs developer path | Posture (a): no Runtime resource-based policy. Defense-in-depth from Gateway JWT authorizer + interceptor + MCP_Server Allowed_Tool_Set. | AD-C5, Task 1.1 |
| **DP-3** Tool naming | Runtime targets forward without aggregation; tool names unchanged. | AD-C1, F-7 |
| **DP-4** Gateway execution role trust | `aws:SourceArn` / `aws:SourceAccount` conditions on Gateway_Execution_Role trust policy. | AD-C6, Task 2.3 |
| **DP-5** Spec disposition | New spec `mcp-external-access-alternative-gateway` created. This spec retained as historical reference. | Task 7 |
| **DP-6** Cost | GO. Under $1/month at projected volume (18K–72K invocations/month). | §8a, Task 1.2 |
| **DP-7** Buffered vs streaming (interceptor firing) | Interceptors fire for `agentcoreRuntime` targets with JSON framing. Server pinned to `json_response=True`. Developer proxy made framing-tolerant (v1.2.0). | AD-C4, AD-C7, Task 0, Task 3 |
| **DP-8** Runtime target vs MCP target | Runtime target chosen. MCP target not needed for two consumer classes. MCP target retained as future option. | AD-C1, Task 0.5 |

## Standing constraints (unchanged)

- **The Path B Task 5 `authorizerConfiguration` custom resource must NEVER be applied to the
  live AgentCore Runtime.** C8's prohibition is permanent. See Path C design §9.3.
- **Any update to the Runtime must carry the full lossless payload** — `update-agent-runtime`
  is a full-replacement API (C9).
