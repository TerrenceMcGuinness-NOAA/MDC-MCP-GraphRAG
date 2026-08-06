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

**DP-1 — How does principal/scope context reach the MCP_Server? (highest priority)**
With JWT terminated at the Gateway and SigV4 on the wire to the Runtime, the Runtime sees
a SigV4 request from the *gateway execution role*. Per F-6 the claims header is not a
documented passthrough. Options:
  (a) Gateway request interceptor injects principal/scope headers;
  (b) `RequestHeaderConfiguration` allowlist forwards `Authorization` and the MCP server
      decodes claims (doc Step 7 pattern);
  (c) move tool-level authorization **to the Gateway** (Cedar / policy-based authz) and
      let the MCP server trust the Gateway entirely.
Option (c) would substantially shrink or delete §8 middleware and §10's in-server
enumeration. This choice determines how much of §8/§9/§10 survives.

**DP-2 — Does the bypass-prevention resource policy break the developer path?**
The documented lockdown policy `Deny`s every principal except the gateway execution role.
Applied verbatim, **developers lose direct SigV4 access** — the exact thing Path C was
chosen to preserve. Either (a) do not lock the Runtime down, accepting that trusted
developers bypass the Gateway (this is today's architecture), or (b) add developer role
ARNs to the `ArnNotEquals` exception set. Decide explicitly; do not inherit the doc's
example unmodified.

**DP-3 — Gateway target semantics and tool naming.**
The Runtime is registered as a **gateway target**. Confirm whether the Gateway re-exposes
or prefixes the 51 MCP tool names, since §10's enumeration and all client configs depend
on exact names.

**DP-4 — Gateway execution role trust hardening.**
Per the docs, restricting the Runtime to the gateway role is only as strong as controls on
who may assume that role. Add `aws:SourceArn` / `aws:SourceAccount` conditions to the
gateway execution role trust policy, scoped to the Gateway ARN (confused-deputy
prevention).

**DP-5 — Spec disposition.**
Path C was explicitly scoped (R11.3) to a **separate follow-on spec**,
`.kiro/specs/mcp-external-access-alternative-gateway/`. Decide: create that spec now and
retire `mcp-external-access-revised`, or amend the revised spec in place. Recommendation:
new spec, reusing §3–§6 and §10 verbatim, since roughly half the revised spec's
Runtime-authorizer content is now dead and in-place editing will leave contradictions.

**DP-6 — Cost.**
The Gateway is an additional per-invocation priced service; design §14 cited cost as
deferral reason #1. That objection no longer permits a decision, but the cost still needs
sizing against expected CI + HPC volume.

---

## 5. Pre-existing issues still open (from prior review)

- **Naming split:** directory is `mcp-external-access-revised`, but requirements/design
  refer throughout to `.kiro/specs/mcp-external-access-alternative/`, including in binding
  criteria R8.5, R11.1, R11.3, R11.4 and every `Feature:` property tag. R11.6 is
  self-executing on this. Resolve during DP-5.
- **`MdcServerStack` missing:** `infrastructure/cdk/bin/cdk.ts:6` imports
  `MdcServerStack` from `../lib/mdc-server-stack`, but `infrastructure/cdk/lib/` contains
  only `cdk-stack.ts`, `mdc-data-stack.ts`, `mdc-security-stack.ts`, `mdc-vpc-stack.ts`.
  No `mdc-server-stack.ts` exists under `infrastructure/cdk`. On `develop`, `cdk synth`
  cannot resolve that import. Confirm whether the file lives on `develop_aws` before any
  CDK task starts.
- **Implementation state is zero:** no external-access CDK stack, no
  `mcp_server_node/src/auth/`, no `tools/mdc_mcp_jwt/`, no `.github/actions/`, no
  runbooks. Every task box unchecked. Nothing built needs unwinding.

---

## 6. Recommended next actions

1. Strike design §7.4 and mark AD-6 / R2.9 as superseded, so nobody implements against
   the false coexistence claim.
2. Resolve **DP-1** — it determines the scope of the follow-on spec.
3. Create `.kiro/specs/mcp-external-access-alternative-gateway/` per R11.3, carrying
   §3–§6 and §10 forward; fix the naming split in the process.
4. Decide **DP-2** before writing any resource-based policy.
5. Re-scope Task 0: verify JWT-in / SigV4-out through a Gateway, not 401 on the Runtime
   URL.

---

## Sources

- [Authenticate and authorize with Inbound Auth and Outbound Auth — Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-oauth.html)
- [Configure inbound JWT authorizer — Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/inbound-jwt-authorizer.html)
- [Set up inbound authorization for your gateway — Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-inbound-auth.html)

*Content from AWS documentation was rephrased for compliance with licensing restrictions; direct quotations are kept short and attributed inline.*
