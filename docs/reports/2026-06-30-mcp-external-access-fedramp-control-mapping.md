# MCP External Access (Path B) — FedRAMP / NIST 800-53 Control Mapping & Review Talking Points

**Date:** 2026-06-30
**Subject spec:** `.kiro/specs/mcp-external-access/` (Path B — Cognito JWT authorizer on the existing AgentCore Runtime)
**Audience:** AWS Summit DC FedRAMP review session
**Status of subject:** Design complete (R1–R11 + P1–P8); **implementation not started** — all tasks (Task 0 onward) are unchecked.
**Prepared by:** Kiro (analysis aid). Verify service-authorization claims against the live [FedRAMP Marketplace](https://marketplace.fedramp.gov) and [AWS services-in-scope](https://aws.amazon.com/compliance/services-in-scope/FedRAMP) before relying on them.

---

## 1. One-page talking points (read this first)

**What this is.** Path B exposes the 51-tool MDC MCP RAG server to two new external consumer classes — GitHub Actions CI and HPC user sessions (Hera, Orion, Hercules, Gaea, Ursa) — by attaching a Cognito-issued JWT authorizer to the existing AgentCore Runtime. The developer SigV4 path stays byte-identical. Path C (AgentCore Gateway + Cedar) is deferred.

**The gating question (raise this before anything else).** The whole feature runs on **Bedrock AgentCore Runtime in commercial `us-east-1`**.
- Amazon **Bedrock**'s FedRAMP **High** authorization is **GovCloud (US-West) only** ([AWS, Aug 2024](https://aws.amazon.com/about-aws/whats-new/2024/08/amazon-bedrock-achieves-fedramp-high-authorization/); [services-in-scope](https://aws.amazon.com/compliance/services-in-scope/FedRAMP/amazon-bedrock-models/)).
- **Bedrock AgentCore** is new (Cedar policy engine GA 2026-03-03). No evidence it sits in **any** FedRAMP boundary yet.
- **Amazon Cognito** *is* FedRAMP-authorized in **US East/West** commercial ([AWS P-ATO](https://aws.amazon.com/blogs/security/aws-achieves-fedramp-p-ato-for-18-additional-services-in-the-aws-us-east-west-and-aws-govcloud-us-regions/)).

So the auth layer is on solid FedRAMP ground; the hosting runtime likely is not. **Reframe the design's gating check:** the spec (design §2 AD-2) treats "is the public endpoint reachable under VPC mode" as the go/no-go. From a FedRAMP standpoint the real gate is "is AgentCore in an authorized boundary at all, and in which region/baseline."

**Three asks for AWS:**
1. FedRAMP authorization roadmap for Bedrock AgentCore (Runtime, Gateway, Identity) — baseline + region + timeline.
2. If unauthorized, does this need to move to **GovCloud**, and what is the AgentCore GovCloud timeline?
3. Confirm Cognito's commercial-region FedRAMP Moderate status still holds for our use.

**What will land well.** Least-privilege IAM (AC-6), no long-lived CI secrets via GitHub OIDC (IA-5), server-side scope-to-tool enforcement with a single source of truth (AC-3 / CM-7), structured per-call audit (AU-2/AU-3), and everything-in-CDK with drift detection + RETAIN policies (CM-2/CM-6/CA-7).

**Top gaps to own before they're raised.** MFA is optional and not phishing-resistant (IA-2); FIPS endpoints/crypto not specified (SC-13/SC-8(1)); CMK encryption-at-rest only conditional (SC-28/SC-12); no WAF/DoS control on the public MCP edge in Path B (SC-5/SC-7); GitHub-hosted runners sit outside the boundary (CA-3/SA-9); audit retention stated inconsistently (90 vs 365 days — AU-11).

**Data-classification soundbite (defuses boundary scrutiny).** The indexed corpus is public NOAA-EMC open-source code plus public documentation — no CUI crosses the public edge.

---

## 2. NIST 800-53 control mapping

Legend — **Status:** ✅ addressed by the design · ⚠️ partial / needs strengthening · ❌ gap / not addressed · ❓ depends on external fact (service authorization).

### Access Control (AC)

| Control | Where the spec addresses it | Status | Gap / POA&M note |
|---|---|---|---|
| AC-2 Account Management | HPC users admin-provisioned (`selfSignUpEnabled:false`, design §3.1) | ⚠️ | Cognito-native user lifecycle (deprovision on departure) is manual. Federating to NOAA SSO centralizes AC-2. |
| AC-3 Access Enforcement | Server-side scope→tool middleware; `allowedToolSets.js` single source of truth (R5, design §8, §10) | ✅ | Strong. ESLint rule + CODEOWNERS guard the mapping (R5.11). |
| AC-4 Information Flow | Neptune/OpenSearch stay VPC-private; only MCP edge public (R8, design §1) | ✅ | Data plane isolation preserved. |
| AC-6 Least Privilege | Token_Broker scoped to one Lambda ARN; Secrets read scoped to one secret; OIDC role `sub` allowlisted (R3.1, R3.2, design §4.2) | ✅ | Exemplary least-privilege story. |
| AC-12 Session Termination | Token lifetime 300–3600 s (R1.7); HPC refresh token 1 day (design §3.4) | ⚠️ | Justify the 1-day HPC refresh token against session-timeout policy; CI client-credentials issues no refresh (dead `refreshTokenValidity` config). |

### Identification & Authentication (IA)

| Control | Where the spec addresses it | Status | Gap / POA&M note |
|---|---|---|---|
| IA-2 Identification & Auth (users) | Cognito JWT for HPC users; SigV4 for developers (R2, R4) | ⚠️ | Human HPC path depends on Cognito-native identity. |
| IA-2(1)/(2) MFA | `mfa: OPTIONAL`, OTP (design §3.1) | ❌ | FedRAMP expects MFA enforced for all access. Set REQUIRED, or federate to NOAA SSO so its MFA applies. |
| IA-2(11)/(12) Phishing-resistant MFA / PIV | — | ❌ | OMB M-22-09 wants phishing-resistant MFA. OTP is not. NOAA SSO + PIV/CAC federation is the compliant path (AD-1 option c). |
| IA-5 Authenticator Mgmt | GitHub OIDC → no long-lived CI secrets (R3.4, Property P8); Cognito secret only in Secrets Manager, read by one Lambda | ✅ | Strong. HPC CLI writes token to `0600` cache only on explicit opt-in (R4.6/R4.7). |
| IA-8 Non-organizational users (GitHub OIDC federation) | Federated IAM role with `sub` allowlist (R3.1) | ⚠️ | Document the external IdP trust (GitHub OIDC) as an IA-8 / SA-9 interconnection. |

### Audit & Accountability (AU)

| Control | Where the spec addresses it | Status | Gap / POA&M note |
|---|---|---|---|
| AU-2 Event Logging | One audit entry per tool call (R6.1) | ✅ | |
| AU-3 Content of Records | `caller_sub`, tool, ISO-8601 ms timestamp, scope, request ID, outcome; GitHub run_id/repo/ref for CI (R6.2–R6.7) | ✅ | Excludes payloads by design (data minimization) — defensible. |
| AU-4 / AU-5 Capacity & Failure | 2 s log-write budget; falls back to error log without blocking response (R6.8) | ⚠️ | Define behavior if CloudWatch is unavailable beyond the single retry. |
| AU-9 Protect Audit Info | CloudWatch log group, task-role scoped to PutLogEvents on that group (design §9.2) | ⚠️ | Add CMK encryption on the audit log group; restrict read access explicitly. |
| AU-11 Retention | Audit group 365 days (design §9.2); a second log says 90 days (design §4.6) | ⚠️ | **Reconcile 90 vs 365.** Confirm against AU-11 obligation (often 1 yr online + archived). |

### System & Communications Protection (SC)

| Control | Where the spec addresses it | Status | Gap / POA&M note |
|---|---|---|---|
| SC-5 DoS Protection | Lambda reserved concurrency (design §4.7) | ⚠️ | The public MCP edge has no WAF/rate-limit in Path B (AWS-managed endpoint). Path C Gateway addresses it — state interim posture. |
| SC-7 Boundary Protection | VPC-private data stores; public MCP edge only (R8) | ⚠️ | No customer-controlled WAF in front of the MCP edge until Path C. |
| SC-8 / SC-8(1) Transmission Confidentiality | TLS 1.2/1.3 to MCP edge (R8.1) | ⚠️ | Require FIPS-validated TLS; document FIPS endpoints (or note GovCloud is FIPS-by-default). |
| SC-12 / SC-13 Key Mgmt & Crypto | Conditional KMS (R9.3); commercial (non-FIPS) endpoints in design | ⚠️/❌ | Specify FIPS 140-validated modules + FIPS endpoints; move from conditional to required CMK. |
| SC-28 Encryption at Rest | DynamoDB stash `AWS_MANAGED`; Secrets Manager default KMS (design §3.3, §4.4) | ⚠️ | Use customer-managed KMS for audit logs, CI secret, and claims stash with documented rotation. |

### Configuration / Assessment / Supply Chain (CM, CA, SA, RA)

| Control | Where the spec addresses it | Status | Gap / POA&M note |
|---|---|---|---|
| CM-2 / CM-6 Baseline & Settings | All resources in CDK; `cdk diff` gate; RETAIN policies (R9) | ✅ | |
| CM-7 Least Functionality | CI excluded from mutation + GitHub tools (R5.3–R5.5, AD-5) | ✅ | |
| CA-7 Continuous Monitoring | Nightly drift detector → CloudWatch metric + GitHub issue (Task 13, R2.8) | ✅ | |
| CA-3 / SA-9 External System Connections | GitHub OIDC federation; GitHub-hosted runners | ⚠️ | GitHub-hosted runners are outside the boundary. Consider self-hosted runners in-boundary; document the interconnection. |
| SA-12 / RA-5 Supply Chain / Vuln | HPC CLI pins PyPI deps (R4.13); composite action uses `configure-aws-credentials@v4` | ⚠️ | Pin GitHub Actions to commit SHA, not a floating tag. |
| IR-4 / IR-5 Incident Handling | Attributable audit (caller_sub, run_id) supports traceback | ✅ | |

### Cross-cutting / environmental

| Concern | Where the spec addresses it | Status | Gap / POA&M note |
|---|---|---|---|
| Service in FedRAMP boundary | AgentCore Runtime (commercial us-east-1) | ❓ | **Primary risk.** Confirm AgentCore authorization + region/baseline. Likely requires GovCloud for High. |
| Data residency / classification | Indexed corpus = public NOAA-EMC code + public docs | ✅ | State explicitly: no CUI crosses the public edge. |

---

## 3. Recommended POA&M-style follow-ups (priority order)

1. **Confirm AgentCore FedRAMP status / region** before any further build (gating).
2. **Elevate NOAA SSO federation** (AD-1 option c) from "future" to the baseline human-auth path → resolves IA-2(1), IA-2(11), AC-2 in one move.
3. **Specify FIPS endpoints + FIPS-validated crypto** across all service calls (SC-13, SC-8(1)).
4. **Require customer-managed KMS** on audit log group, CI secret, claims stash + rotation (SC-28, SC-12, AU-9).
5. **Reconcile audit retention** to a single documented value meeting AU-11.
6. **Document the GitHub interconnection** (CA-3/SA-9); evaluate self-hosted runners in-boundary.
7. **State interim DoS/boundary posture** for the public MCP edge pending Path C Gateway (SC-5/SC-7).

---

*This document is an analysis aid, not an authorization artifact. Control determinations must be validated by the system's FedRAMP assessor (3PAO) and reflected in the SSP/POA&M.*
