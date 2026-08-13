# Design: MCP External Access — Path C (Gateway-fronted, Cognito JWT on AgentCore Gateway)

**Spec ID:** `mcp-external-access-alternative-gateway`
**Companion documents:** `requirements.md` (this directory),
`../mcp-external-access-revised/decision-log.md` (normative analysis and citations),
`../mcp-external-access-revised/design.md` (inherited sections §3–§6, §9, §10, §12).

---

## 1. Overview

```
                        ┌──────────────────────────────────────────┐
   CI (GitHub Actions)  │                                          │
   HPC (RDHPC/gaea64)   │   Cognito User Pool (unchanged from B)   │
        │               │   ci-readonly scope / hpc-user scope     │
        │  JWT          └──────────────────────────────────────────┘
        ▼
┌───────────────────────────────────────────────┐
│  AgentCore GATEWAY   (protocol type: unset)   │
│  ─ customJWTAuthorizer (Cognito)              │  ← JWT validated HERE
│  ─ REQUEST interceptor Lambda                 │  ← injects trusted context
│  ─ Runtime target, outbound auth = IAM SigV4  │
└───────────────────────────────────────────────┘
        │  SigV4, signed with Gateway_Execution_Role
        │  + X-Amzn-Bedrock-AgentCore-Runtime-Custom-{Principal,Scope,BrokerRequestId}
        ▼
┌───────────────────────────────────────────────┐
│  AgentCore RUNTIME   (inbound auth: SigV4)    │  ← NO JWT authorizer, ever
│    └─ MCP_Server (FastMCP, streamable-http,   │
│         stateless_http=True,                  │
│         json_response=True)                   │
│         └─ authMiddleware → Allowed_Tool_Set  │  ← tool gating stays HERE
└───────────────────────────────────────────────┘
        ▲
        │  SigV4 direct — unchanged, no Gateway involved
   Developer (Kiro on EC2, agentcore-kiro-proxy.py)
```

### 1.1 The single invariant that forces this shape

An AgentCore Runtime supports **either** IAM SigV4 **or** JWT bearer inbound auth, **not
both simultaneously**. The Developer_Principal SigV4 path is non-negotiable, therefore the
Runtime must stay SigV4, therefore JWT validation must happen somewhere upstream. The
Gateway is the documented place.

Consequence worth stating plainly: **the developer path is now preserved structurally rather
than behaviorally.** Path B needed a regression suite to prove coexistence worked; Path C
needs only to prove no authorizer was ever attached to the Runtime. That is a stronger
guarantee and a cheaper test.

### 1.2 Three invariants (carried from Path B, re-anchored)

1. **No long-lived secrets in CI.** Unchanged — Token_Broker issues short-lived JWTs against
   a GitHub OIDC-federated role.
2. **Default-deny tool scoping.** Unchanged in substance, but the enforcement point is now
   explicitly the MCP_Server, because the Gateway cannot see tool names (§4.2).
3. **Every external invocation is attributable.** Unchanged; `broker_request_id` now travels
   as an injected header rather than a claim.

---

## 2. Architecture Decisions

### AD-C1. Runtime target, not MCP target (DP-8)

**Decision:** register the Runtime as an `agentcoreRuntime` target on a protocol-type-unset
Gateway.

**Rationale:** minimal change to a working deployment; the Runtime keeps its current
identity, image, and SigV4 developer path. Runtime targets forward requests and responses
**without aggregation or protocol translation**, so the 53 tool names are unchanged and no
client config churns.

**Accepted losses:** no capability aggregation, no semantic tool search, and — the important
one — the Gateway receives the request body as an **opaque base64 string** and never parses
JSON-RPC, so it has no native view of tool names.

**Rejected alternative:** an **MCP target**, which uses the `mcp` interceptor payload with
parsed JSON-RPC, supports aggregation and semantic search, and would enable genuine per-tool
Cedar policy. Rejected for now because it is a different hosting story and is not needed for
two consumer classes. **Retained as the fallback if Requirement 0 verification fails.** The
two are mutually exclusive on one Gateway: Runtime targets cannot attach to MCP-protocol-type
gateways.

### AD-C2. Trusted context via interceptor header injection (DP-1)

**Decision:** a REQUEST interceptor Lambda injects
`X-Amzn-Bedrock-AgentCore-Runtime-Custom-{Principal,Scope,BrokerRequestId}`.

**Rationale:** under SigV4 outbound the Runtime sees a request signed by the
Gateway_Execution_Role, so JWT claims do not arrive on their own. AWS prohibits `X-Amzn-`
prefixed propagated headers **except** `X-Amzn-Bedrock-AgentCore-Runtime-Custom-*`, which is
purpose-built for runtime-bound custom context.

**Why this is secure:** interceptor-supplied headers **take precedence over
client-supplied** ones. A CI or HPC caller that forges
`X-Amzn-Bedrock-AgentCore-Runtime-Custom-Scope: mcp/hpc-user` has that value overwritten
before it reaches the container. This is the property that lets the MCP_Server trust the
header without re-validating a signature.

**Relationship to Path B AD-6:** the *intent* is preserved verbatim, including "absence of
the trusted header ⇒ `developer-sigv4` principal". Only the header names and their producer
change. Path B's assumed automatic `...Custom-Authorizer-Claims` passthrough is not
documented and is not relied upon.

### AD-C3. Tool gating stays in the MCP_Server (corrects Path B §14)

**Decision:** `allowedToolSets` remains the enforcement point; the Gateway does not perform
per-tool authorization.

**Rationale:** AD-C1's opaque body means the Gateway cannot see `tools/call` params. Path B's
§14 promised Cedar per-tool policy as the Path C payoff; that is unavailable in this shape.

**Consequence — this is good news for effort.** Path B's §8 middleware and §10 enumeration
survive nearly intact; only the principal-derivation lines change. Path C is a *smaller*
change than Path B's §14 implied, not a larger one.

**Optional defense-in-depth:** the interceptor may base64-decode the body, parse JSON-RPC,
read `params.name`, and deny by returning a `transformedGatewayResponse`, which
short-circuits — the Gateway replies immediately without calling the target and the RESPONSE
interceptor does not run. Deferred; it duplicates §10 in a Lambda.

### AD-C4. Response framing pinned to JSON (DP-7)

**Decision:** serve `json_response=True` so responses are `application/json`, and pin it in
code with an env override.

**Rationale:** interceptors for HTTP/Runtime targets are supported **in buffered mode only,
not in streaming mode**. Verified empirically against the pinned `fastmcp==3.2.4`:

| `json_response` | `Content-Type` |
|---|---|
| `False` (today's effective default) | `text/event-stream` |
| `True` | `application/json` |

So the server as deployed today emits SSE — exactly the mode documented as unsupported.

**`stateless_http=True` must NOT be changed.** It is orthogonal to `json_response` and is
mandatory: AgentCore supplies its own `Mcp-Session-Id` per request, and stateful mode
rejects it with HTTP 400, surfacing as a 500-class runtime error.

**Accepted loss:** disabling SSE forfeits incremental `notifications/progress` and
stream-based elicitation/sampling. Acceptable for CI and HPC, which issue discrete
`tools/call` requests. It would matter for interactive agent use — hence R3.4's warning log.

### AD-C7. Framing is server-wide, so the proxy is made framing-tolerant (amends R7.1)

**Question asked (2026-08-13):** could the framing conflict between R3.1 (`json_response`
enabled so interceptors fire) and R7.1 (developer proxy byte-identical) be dissolved by
per-request content negotiation — the proxy already sends
`Accept: application/json, text/event-stream`?

**Answer: no. Verified against installed source, not inference.** In
`mcp/server/streamable_http.py` the POST response branch is:

```python
if self.is_json_response_enabled:   # -> _create_json_response
else:                               # -> SSE stream
```

The `Accept` header is read only by `_validate_accept_header`, and solely to decide whether
to return HTTP 406. It never selects a format. There is no negotiation.

**The failure mode is silent, which is worse than a hard error.** With `json_response=True`
the Accept validation *relaxes* to requiring only `application/json`. The proxy sends both
types, so it passes validation, receives a JSON body, and then `parse_sse()` finds no
`data:` lines, returns `[]`, and the caller emits `-32603 "Empty SSE response"`. Nothing at
the HTTP layer signals a problem; every developer tool call simply fails.

**Decision:** make `parse_sse()` accept both framings — SSE frames first, falling back to a
bare JSON object or array — and amend R7.1 from "byte-identical" to "functionally
unchanged". Rejected alternatives:

- **Two Runtimes off one image** (existing SSE for developers, a second with
  `FASTMCP_JSON_RESPONSE=true` behind the Gateway). Satisfies R7.1 literally, but
  permanently doubles the Runtime surface and creates an image-sync obligation on every
  deploy; a missed one yields a subtle framing-dependent divergence. Rejected as ongoing
  operational cost on a production-support system.
- **Leave the proxy SSE-only and abandon `json_response`.** Forfeits interceptors, hence
  all principal/scope enforcement. Not viable.

Tolerating both framings also removes a pre-existing latent fragility: the proxy would have
broken identically if AgentCore or FastMCP ever changed its default. Implemented in
`tools/agentcore-kiro-proxy.py` v1.2.0 with seven tests in `TestJsonResponseFraming` plus a
Hypothesis round-trip property.

**Dependency-pin drift found while verifying — carry into Task 0.** `pyproject.toml:20` pins
`fastmcp==3.2.4`, but the environment has **fastmcp 3.4.1** with **mcp 1.27.2**. The
DP-7 framing evidence in AD-C4 is labelled as verified against 3.2.4, so it was not
established against what is actually installed. Reconcile the pin (or re-verify against the
container image) before treating DP-7's server half as settled. Confirmed on 3.4.1:
`mcp.run(transport="streamable-http", ..., json_response=...)` is valid —
`run()` forwards `**transport_kwargs` to
`run_http_async(json_response: bool | None = None)`, which defaults from
`fastmcp.settings.json_response` (`FASTMCP_JSON_RESPONSE`). Task 3.1 is therefore
implementable as written, and Task 0.1's env-var route reaches the same switch.

### AD-C5. Bypass prevention is opt-in and must spare the developer (DP-2)

**Decision:** if a Runtime resource-based policy restricting invocation to the
Gateway_Execution_Role is attached, it **must** also permit the Developer_Principal role.

**Rationale:** the documented lockdown policy denies every principal except the gateway role,
keyed on `aws:PrincipalArn`. Applied verbatim it severs the developer path — the exact thing
Path C exists to preserve. An explicit `Deny` overrides any `Allow`, including
identity-based policies, so this failure would be absolute and immediate.

**Two acceptable postures, to be chosen explicitly:**
- **(a) No lockdown.** Trusted developers can reach the Runtime directly. This is today's
  architecture and today's risk posture. Simplest.
- **(b) Lockdown with an exception set.** `ArnNotEquals` lists both the Gateway_Execution_Role
  and the Developer_Principal role.

Under either, AD-C6 applies.

### AD-C6. Gateway execution role trust hardening (DP-4)

Restricting the Runtime to the gateway role is only as strong as the controls on who may
assume that role. The Gateway_Execution_Role trust policy must carry `aws:SourceArn` and
`aws:SourceAccount` conditions scoped to the Gateway ARN (confused-deputy prevention).

---

## 3. Gateway and Target Configuration

### 3.1 Gateway

Protocol type **unset** — required for an `agentcoreRuntime` target. The Cognito
`customJWTAuthorizer` uses the **same configuration shape** as the Runtime authorizer would
have, so Path B §3's Cognito design transfers with no edit:

```json
{
  "authorizerConfiguration": {
    "customJWTAuthorizer": {
      "discoveryUrl": "https://cognito-idp.<region>.amazonaws.com/<poolId>/.well-known/openid-configuration",
      "allowedClients": ["<ci-client-id>", "<hpc-client-id>"],
      "allowedAudience": ["<audience>"],
      "allowedScopes": ["mcp/ci-readonly", "mcp/hpc-user"]
    }
  }
}
```

`allowedScopes` **does exist** — this closes Path B's OQ-2. If both `allowedClients` and
`allowedAudience` are supplied, both are verified.

### 3.2 Runtime target

```json
{
  "name": "mdc-mcp-rag",
  "targetConfiguration": {
    "http": {
      "agentcoreRuntime": {
        "arn": "arn:aws:bedrock-agentcore:<region>:<acct>:runtime/<RUNTIME_ID>",
        "qualifier": "DEFAULT"
      }
    }
  },
  "metadataConfiguration": {
    "allowedRequestHeaders": [
      "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Principal",
      "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Scope",
      "X-Amzn-Bedrock-AgentCore-Runtime-Custom-BrokerRequestId"
    ]
  }
}
```

No `schema` — MCP-protocol runtimes receive a default schema automatically. Outbound auth is
IAM (SigV4).

### 3.3 Endpoint

`https://{gatewayId}.gateway.bedrock-agentcore.{region}.amazonaws.com/{targetName}/invocations`

This becomes the exported `McpEndpointUrl`. Path B's C-IMPACT-3 ensured consumers read that
export rather than hard-coding a URL, so this is a one-value change and consumers re-pull.

### 3.4 Header propagation constraints

Max 10 request headers per target; values ≤ 4 KB, printable ASCII; names matching
`^[a-zA-Z0-9_-]+$`. `Authorization` cannot be allowlisted at target creation, though it *is*
forwarded when supplied by an interceptor — we do not rely on that.

---

## 4. Request Interceptor Design

### 4.1 Contract

Runtime targets use the **`http`** interceptor payload, not `mcp`:

| | MCP target | HTTP / Runtime target |
|---|---|---|
| Body | parsed JSON | **base64 string** |
| Path | always `/mcp` | `/{targetName}/invocations` |
| `rawGatewayRequest` | included | absent |
| Response interceptor | supported | **buffered only** |

Configured with `passRequestHeaders: true` (required to see inbound headers) and a payload
filter excluding `RESPONSE_BODY`.

### 4.2 Handler sketch

```python
# infrastructure/cdk/lambda/gateway_interceptor/index.py
import base64, json, logging

log = logging.getLogger()
SCOPE_TO_PRINCIPAL = {"mcp/ci-readonly": "ci-readonly", "mcp/hpc-user": "hpc-user"}

def handler(event, context):
    req = event["http"]["gatewayRequest"]
    headers = {k.lower(): v for k, v in (req.get("headers") or {}).items()}

    # The Gateway already validated signature, iss, aud, client_id, exp and scope.
    # Decode without verification purely to read claims. NEVER log the token.
    token = headers.get("authorization", "").removeprefix("Bearer ").strip()
    claims = _decode_unverified(token) if token else {}

    scope_claim = claims.get("scope", "")
    scope = next((s for s in scope_claim.split() if s in SCOPE_TO_PRINCIPAL), None)
    if scope is None:
        return _deny(403, "no recognized scope")          # R4.6 short-circuit

    injected = {
        "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Principal": SCOPE_TO_PRINCIPAL[scope],
        "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Scope": scope,
        "X-Amzn-Bedrock-AgentCore-Runtime-Custom-BrokerRequestId":
            claims.get("broker_request_id") or headers.get("x-broker-request-id", ""),
    }
    # Interceptor values overwrite any client-supplied same-named header (R4.3).
    return {
        "interceptorOutputVersion": "1.0",
        "http": {"transformedGatewayRequest": {
            "headers": {**{k: v for k, v in req.get("headers", {}).items()
                           if not k.lower().startswith("x-amzn-bedrock-agentcore-runtime-custom-")},
                        **injected},
            "body": req["body"],          # pass through untouched, still base64
        }},
    }

def _deny(code, reason):
    body = base64.b64encode(json.dumps({"error": reason}).encode()).decode()
    return {"interceptorOutputVersion": "1.0",
            "http": {"transformedGatewayResponse": {
                "statusCode": code, "contentType": "application/json", "body": body}}}
```

Note the explicit strip of any inbound `...Custom-*` headers before merging — belt and
braces alongside the platform's precedence rule, so unforgeability does not rest on a single
mechanism.

### 4.3 Audit inputs from client context

For HTTP targets the Gateway passes `GATEWAY_ARN`, `GATEWAY_ACCOUNT_ID`, `REQUEST_ID`, and
`SOURCE_IP` via Lambda **client context**. `SOURCE_IP` is present only when available — treat
as optional. This is the cleanest source of caller IP for the audit schema.

### 4.4 Payload limits

Lambda synchronous invoke caps request + response at **6 MB**, and the base64 body counts.
For a RAG server this is a live risk, so the RESPONSE_BODY payload filter is mandatory
(R6.3). With it excluded the interceptor still sees `statusCode`, `contentType`, and
`headers`, may inject headers and override status, and returning `body: null` leaves the
original response untouched.

---

## 5. MCP_Server Middleware Changes

The **only** substantive change to Path B §8 is principal derivation:

```diff
- claims_b64 = headers.get("x-amzn-bedrock-agentcore-runtime-custom-authorizer-claims")
- if claims_b64 is None:
-     principal = "developer-sigv4"
- else:
-     claims = json.loads(base64.urlsafe_b64decode(claims_b64))
-     principal = _principal_from_scope(claims["scope"])
+ principal = headers.get("x-amzn-bedrock-agentcore-runtime-custom-principal")
+ scope     = headers.get("x-amzn-bedrock-agentcore-runtime-custom-scope")
+ if principal is None:
+     principal = "developer-sigv4"          # SigV4 direct: no Gateway, no injected headers
+ elif scope not in KNOWN_SCOPES:
+     return _forbidden()                    # default-deny (R5.4)
```

Everything downstream — `Allowed_Tool_Set` lookup, the CI/HPC/developer enumeration (see R5.5 note on re-derivation), default-deny on
unknown tools, the audit writer — is unchanged. Path B §10 is inherited verbatim.

The server never re-validates a JWT signature. The Gateway is the trust boundary, and the
header precedence rule is what makes that safe.

---

## 6. Response Framing Change

```diff
+ # Gateway interceptors run in buffered mode only; SSE framing prevents them
+ # from firing, which would silently remove all principal/scope enforcement.
+ json_response = os.environ.get("MCP_JSON_RESPONSE", "true").strip().lower() not in (
+     "false", "0", "no", "off"
+ )
+ if not json_response:
+     log.warning("[WARN] json_response disabled — Gateway interceptors may not fire")
  mcp.run(
      transport="streamable-http",
      host=config.host,
      port=config.port,
      stateless_http=stateless,
+     json_response=json_response,
  )
```

Pinned in code with an env override, mirroring the existing `MCP_STATELESS_HTTP` treatment,
so the value cannot be silently reconfigured by ambient environment. `stateless_http` is
untouched.

---

## 7. CDK Stack Layout

New stack `MdcMcpGatewayStack` containing: the Gateway, the Cognito authorizer wiring, the
Runtime target with `metadataConfiguration`, the Gateway_Execution_Role (with AD-C6 trust
conditions), the interceptor Lambda plus its role, and the `McpEndpointUrl` export.

It must **not** touch the Runtime's inbound auth. If the AD-C5(b) posture is chosen, the
Runtime resource-based policy is the one Runtime-side change and must include the developer
role.

**Known blocker:** `infrastructure/cdk/bin/cdk.ts:6` imports `MdcServerStack` from
`../lib/mdc-server-stack`, but that file is absent under `infrastructure/cdk/lib/` on
`develop` (which holds only `cdk-stack.ts`, `mdc-data-stack.ts`, `mdc-security-stack.ts`,
`mdc-vpc-stack.ts`). `cdk synth` cannot resolve it, so R8.4 fails for reasons unrelated to
this feature. Resolve before Task 2.

Inherits Path B §12.4–§12.6: DeletionPolicy tests, `cdk diff` guardrails per steering 05,
CDK-only mutation and drift detection.

---

## 8. Correctness Properties

Inherits Path B Properties 1–5, 7–10 with "Runtime authorizer" read as "Gateway authorizer".

- **Property 6 (restated):** all 53 tools succeed over Developer_Principal SigV4 directly
  against the Runtime, and `GetAgentRuntime` shows no `customJWTAuthorizer`.
- **Property 11 (unforgeability):** for any client-supplied Trusted_Context_Header value, the
  value observed by the MCP_Server equals the interceptor-derived value.
- **Property 12 (attribution completeness):** every Gateway-admitted request yields exactly
  one audit entry whose `broker_request_id` joins a Token_Broker log entry, unless the
  principal is `developer-sigv4`.

---

## 9. Gate Register

Authoritative gate status for the MCP external-access effort as a whole. Full analysis and
citations in `../mcp-external-access-revised/decision-log.md`.

### 9.1 Gates cleared

| Gate | Date | Verdict |
|---|---|---|
| **AD-1** — HPC auth grant type | 2026-07 | Cognito has no RFC 8628 device flow. Replaced with Authorization Code + PKCE (primary), SRP (fallback). |
| **AD-3** — CI attribution | 2026-07 | Pre-Token-Generation trigger does not reliably fire/enrich for M2M client-credentials. Replaced with Token_Broker log-join on `broker_request_id`. |
| **R8.5** — endpoint reachability (Path B Task 0) | 2026-07-22 | **PASS.** HTTP 403 "Authorization method mismatch". Endpoint reachable; no TCP error, so the R8.6 fallback never triggered. |
| **RDHPC egress** | 2026-08-06 | **PASS.** `curl` from gaea64 to `bedrock-agentcore.us-east-1.amazonaws.com` returned an application-layer response, proving DNS + TLS + HTTP egress. |
| **FedRAMP boundary** | 2026-08-06 | Confirmed **not** operating inside a FedRAMP boundary. The 2026-06-30 control mapping is **advisory**, not a precondition. No GovCloud migration forced. |
| **OQ-1 / OQ-3** | 2026-07 | Resolved by AD-1 / AD-3. |
| **OQ-2** — does `allowedScopes` exist? | 2026-08-06 | **Yes.** Documented as a list of strings validated against the `scope` claim. R2.1/R2.3 satisfiable. Same config shape for Runtime or Gateway. |
| **C8** — dual-auth compatibility | 2026-08-06 | **RESOLVED → single-mode confirmed → Path C pivot.** An AgentCore Runtime supports either IAM SigV4 or JWT bearer inbound auth, not both simultaneously. The July inference from the 403 body was correct. |
| **DP-1** — claims propagation | 2026-08-06 | Gateway REQUEST interceptor injects `X-Amzn-Bedrock-AgentCore-Runtime-Custom-*`; interceptor headers take precedence over client headers, giving unforgeability. |
| **DP-3** — tool naming | 2026-08-06 | Runtime targets forward without aggregation or protocol translation. Tool names unchanged. |
| **DP-7 (server half)** | 2026-08-06 | Verified against pinned `fastmcp==3.2.4`: `json_response=False` → `text/event-stream`; `True` → `application/json`. Fix is config, not code. `stateless_http=True` is orthogonal and mandatory. **Caveat 2026-08-13:** the environment actually has fastmcp **3.4.1** / mcp **1.27.2**, not the pinned 3.2.4 — reconcile the pin or re-verify against the container image (AD-C7). |
| **Framing negotiation** — can `Accept` select SSE vs JSON per request, dissolving the R3.1/R7.1 conflict? | 2026-08-13 | **No.** `streamable_http.py` branches on `is_json_response_enabled` alone; `Accept` only gates a 406. Resolved instead by making the proxy framing-tolerant and amending R7.1 (AD-C7). Proxy v1.2.0 shipped, 30 tests pass. |

### 9.2 Gates open — ordered by what they block

| # | Gate | Blocks | Owner / method |
|---|---|---|---|
| **1** | **Requirement 0 / Task 0 — do buffered interceptors fire for a JSON-response MCP Runtime target, and do injected headers reach the container?** (DP-7 AWS half, DP-1 confirmation) | **All Path C implementation.** A negative answer flips DP-8 to the MCP-target architecture and changes the spec's shape. | Throwaway Gateway, ~1 hr (Task 0), or AWS analyst confirmation |
| **2** | **DP-2 — does the Runtime resource policy restricting invocation to the Gateway also permit the Developer_Principal role?** | **Any `cdk deploy`.** AWS's documented example denies all but the gateway role, and an explicit `Deny` overrides every `Allow` — applied verbatim it severs the developer path. | Decision, then Task 1.1 |
| **3** | **IAM pre-creation** — OIDC provider + 3 Path B roles + 2 new Path C roles (Gateway execution, interceptor execution) | **Deploy.** `iam:CreateRole` blocked by `PowerUserRestrictions` (C7/C10/C11/C12). | Admin request `docs/mdc-external-access-alt-iam-request.txt`. **Lead-time item — start in parallel with Gate 1.** |
| **4** | **C13 — re-derive per-scope tool counts against the Python runtime** | **Correct enforcement.** "CI 40 / HPC 48 / developer 51" came from the retired Node runtime (51 tools); the live Python runtime has **53** (verified 2026-08-13 — progress.md C1's "52" is itself stale), so ≥2 tools are unclassified. One is `extract_ci_error_signal` (module `error_analysis`). | Task 5.3a |
| **5** | **DP-6 — Gateway + interceptor invocation cost** | Go/no-go sizing. | Task 1.2 |
| **6** | **DP-4 — Gateway execution role trust hardening** (`aws:SourceArn` / `aws:SourceAccount`) | Not blocking; answer known, needs implementing. | Task 2.3 |
| **7** | **DP-8 — Runtime target vs MCP target** | Contingent on Gate 1. Recommendation stands: Runtime target, MCP target as fallback. | Task 0.5 branch |

### 9.3 Standing constraint (not a gate)

**The Path B Task 5 `authorizerConfiguration` custom resource must NEVER be applied to the
live AgentCore Runtime.** Doing so would replace SigV4 with JWT and break the developer path
(R7 / C6). This prohibition was provisional under C8; with C8 resolved to single-mode it is
**permanent**. The resource may remain in-tree, unapplied, as it carries forward if the
architecture ever changes.

Also standing: any update to the Runtime must carry the **full lossless payload**, because
`bedrock-agentcore-control:update-agent-runtime` is a full-replacement API (C9).

---

## 10. Questions for the next AWS analyst round

Ordered by value. Gate 1 is the reason this round matters — an authoritative answer to Q1
removes the need for the throwaway-Gateway test entirely.

1. **(Gate 1 — highest value.)** For an **AgentCore Runtime target** on a Gateway, are REQUEST
   and RESPONSE interceptor Lambdas invoked when the runtime serves MCP over Streamable HTTP?
   The docs say interceptors are supported "in buffered mode" and "not yet supported in
   streaming mode" for HTTP targets. **What exactly determines which mode applies** — the
   target's response `Content-Type`, a gateway-level response-streaming setting, or something
   else? Concretely: if our MCP server returns `application/json` rather than
   `text/event-stream`, do interceptors run?
2. **(Gate 1.)** Do headers injected by a REQUEST interceptor via
   `transformedGatewayRequest.headers` reliably reach an AgentCore Runtime target's container
   when the header names use the `X-Amzn-Bedrock-AgentCore-Runtime-Custom-*` prefix and are
   listed in the target's `metadataConfiguration.allowedRequestHeaders`? Any additional
   configuration required on the **Runtime** side to receive them?
3. **(Gate 2.)** For the resource-based policy that restricts Runtime invocation to a
   Gateway's execution role — is adding a second permitted principal (our developer role) to
   the `ArnNotEquals` exception set a supported pattern, or is there a preferred way to keep a
   trusted human/IAM path alongside a gateway-fronted runtime?
4. **(DP-8.)** For an MCP server hosted **in** AgentCore Runtime, is there a supported way to
   register it as an **MCP-type** gateway target (gaining parsed JSON-RPC, tool aggregation,
   semantic search, and per-tool policy) rather than an `agentcoreRuntime` HTTP target — for
   example via VPC Lattice private endpoints? Are the two mutually exclusive on one gateway,
   given Runtime targets require protocol type unset?
5. **(DP-6.)** Pricing model for AgentCore Gateway per invocation, and whether interceptor
   Lambda invocations are billed separately or bundled.
6. **(Confirmation.)** Please confirm the single-mode inbound auth constraint is permanent
   platform behavior rather than a launch limitation, and whether multi-mode inbound auth on
   one Runtime is on the roadmap. Our entire Path C pivot rests on this.
7. **(Nice to have.)** Is `bedrock-agentcore` in scope for any FedRAMP authorization
   (region + baseline), or on the roadmap? We are not currently inside a boundary, so this is
   planning input, not a blocker.
