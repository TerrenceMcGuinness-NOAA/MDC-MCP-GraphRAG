# GSA Agentic Coding Playbook — Assessment & Applicability Report

**Date**: 2026-08-10
**Assessed by**: Kiro session with Terrence McGuinness
**Subject**: `supported_repos/agentic-coding-playbook/` (GSA-TTS, CC0 1.0)
**Our system**: NOAA MDC MCP-RAG Server (AgentCore + EIB Gateway)

---

> ## Partial Correction — Read This First
>
> **Sections 1-3 (what the playbook is, provenance, GSA support resources) remain
> accurate and current.**
>
> **Section 4 ("Relevance to Our MCP-RAG System") contains a scope error.** It
> evaluates the MCP-RAG server in isolation and describes the system as a read-only
> analysis tool. The correct boundary is the composite agentic system — the LLM agent
> plus the MCP tool surface plus filesystem write access, arbitrary command execution,
> git push authority, and the developer's ambient AWS credentials. Under that boundary
> the alignment picture is substantially worse than Section 4 states.
>
> Specific claims now known to be wrong:
> - "Cannot reach any production system" — an agent-issued `update-agent-runtime`
>   rotated the live AgentCore runtime v37 to v38 on 2026-08-10.
> - "Never modifies operational code" — the agent edits source, commits, and pushes.
> - The read-only framing omits the 2026-04-22 incident in which an agent-assisted
>   CDK deploy destroyed the production Neptune cluster (59,759 nodes,
>   2,633,374 relationships). See `docs/postmortem/2026-04-22-neptune-data-loss.md`.
>
> **Superseding analysis:**
> [[GSA-Agentic-Coding-Playbook-Security-Controls-Reconciliation]] v2.0 — treat that
> document as authoritative for any compliance question.

---

## 1. What Is It

The **Agentic Coding Playbook** is a set of markdown files, templates, validation
tools, and executable "skills" published by GSA's Technology Transformation
Services (TTS) on GitHub under CC0 (public domain). It provides practical,
tool-agnostic guidance for federal employees who build software with AI coding
agents.

It is **not** authoritative federal policy. It is community-maintained best
practices grounded in authoritative sources (NIST, OMB, OWASP, CISA). Each
agency tailors it to their own ATO requirements.

### The Three-Repo Ecosystem

| Repo | Purpose |
|------|---------|
| [Quickstart](https://github.com/GSA-TTS/agentic-coding-quickstart) | First-day setup, sandbox config |
| [Playbook](https://github.com/GSA-TTS/agentic-coding-playbook) (this one) | Standards, templates, compliance procedures |
| [Patterns](https://github.com/GSA-TTS/agentic-coding-patterns) | Community lessons learned, shareable workflows |

### Key Documents

| File | What It Covers |
|------|----------------|
| `AGENTS.md` | Universal behavioral contract (15 sections, 35 NIST controls mapped) |
| `docs/CODING_PRACTICES.md` | Secure coding standards (input validation, secrets, crypto, size limits) |
| `docs/SECURITY-CONTROLS.md` | NIST 800-53 Rev 5.2 control overlay for agentic AI systems |
| `docs/FEDERAL-AI-LANDSCAPE.md` | Catalog of 42 federal AI guidance documents with status tracking |
| `checklists/pre-deployment.md` | 62-item security checklist before production deployment |
| `PLAYBOOK.md` | Step-by-step from project plan to cloud.gov deploy |

---

## 2. Provenance & Authority

### Who Maintains It

**GSA Technology Transformation Services (TTS)** — the same org that runs
18F, cloud.gov, login.gov, and the IT Modernization Centers of Excellence.
TTS is part of GSA's Federal Acquisition Service.

Repository: `github.com/GSA-TTS/agentic-coding-playbook`
License: CC0 1.0 Universal (public domain — federal employees may freely use,
modify, and distribute)
Last commit: August 2026 (actively maintained, ~200 commits)

### Authoritative Frameworks It Cites

| Framework | Version | Role |
|-----------|---------|------|
| NIST SP 800-53 | Rev 5.2 (Sep 2024) | Security and privacy controls |
| NIST AI RMF | 1.0 (Jan 2023) | AI risk: Govern, Map, Measure, Manage |
| NIST SP 800-218A | Final (Jun 2024) | Secure AI software development (SSDF) |
| NIST AI 600-1 | 1.0 (Jul 2024) | GenAI risk profile |
| OWASP Top 10 LLM | 2025 | LLM application risks |
| OWASP Agentic AI | 2026 | Agentic application risks |
| OMB M-25-21 | Apr 2025 | Federal AI governance |
| CISA Secure by Design | 2025 | Secure-by-default principles |

### What It Is NOT

- Not authoritative federal policy (the NIST pubs and OMB memos it cites ARE)
- Not a substitute for an agency's ATO process
- Not procurement guidance
- Not suitable as-is for FIPS High or classified systems
- Not guaranteed — provided as-is, community-tested

---

## 3. GSA Ongoing Support & Resources

| Resource | Access | Description |
|----------|--------|-------------|
| **AI Community of Practice** | aicop@gsa.gov | 12,000+ members, 100+ agencies, monthly meetings (2nd Thursday, 1-2 PM ET via ZoomGov) |
| **2026 MCP Hackathon** | [gsa.gov](https://www.gsa.gov/artificial-intelligence/ai-community-of-practice/events-and-training/2026-ai-hackathon) | Sep-Oct 2026, government-wide, build MCP servers for open data (partners: Databricks, OpenAI, IBM) |
| **Mastering Agentic AI Training** | [gsa.gov](https://www.gsa.gov/artificial-intelligence/ai-community-of-practice/events-and-training/mastering-agentic-ai-systems) | Cohort-based facilitator-led series for federal employees |
| **AI Guide for Government** | [coe.gsa.gov](https://coe.gsa.gov/coe/ai-guide-for-government/print-all/index.html) | High-level guide for agency AI adoption |
| **AI Governance Toolkit** | [coe.gsa.gov PDF](https://coe.gsa.gov/docs/AICoP-AIGovernanceToolkit.pdf) | Privacy, DEIA, and governance framework |
| **GSA IT Security Policy** | [CIO 2100.1R](https://www.gsa.gov/directives-library/gsa-information-technology-it-security-policy-16) | GSA's own IT security directive (Govern function) |
| **Federal AI Landscape Registry** | `data/federal-ai-landscape.yaml` in the playbook | Machine-readable catalog of 42 guidance documents with status, dates, cross-refs |

**Operating authority**: The AI CoP operates under 41 USC 1703 / Public Law
117-207, OMB M-25-21, M-25-22, and EO 14179.

---

## 4. Relevance to Our MCP-RAG System

### Where We Already Align

| Playbook Requirement | Our Practice | Status |
|---------------------|--------------|--------|
| **Plan before execute** (§14.1) | Kiro spec-first policy — no code without a committed spec | EXCEEDS (our policy is stricter) |
| **Least privilege** (§3.1) | MCP tools are read-only analysis aids; never modify operational code | ALIGNED |
| **Audit trail** (§2.2) | SDD session logging, CHANGELOG, git history, deploy logs | ALIGNED |
| **Pin dependencies** (§5.2) | `pyproject.toml` with exact versions, lock files committed | ALIGNED |
| **No secrets in code** (§4.1) | Secrets via AWS Secrets Manager, env vars, `.config/eib-mcp/secrets.env` (gitignored) | ALIGNED |
| **Testing before commit** (§8.1) | 700+ unit tests, live smoke probes, parity suite | ALIGNED |
| **TLS for all network** (§6.1) | Neptune/OpenSearch via HTTPS+SigV4, all external via TLS | ALIGNED |
| **Change management** (§14.2) | PR-based flow, no direct commits to protected branches | ALIGNED |
| **Docs-as-code** (§15.4) | Steering files, specs, wiki reports all version-controlled | ALIGNED |
| **No silent failures** (§14.5) | SkipProbe pattern, explicit error reporting, health check PASS/FAIL/SKIP | ALIGNED |
| **Run-and-verify loop** (§14.4) | Smoke probes, functional validation, parity checks | ALIGNED |
| **Session boundaries** (§2.3) | MCP_STATELESS_HTTP=true, no state persisted between sessions | ALIGNED |

### Where We Have Gaps

| Playbook Requirement | Current State | Priority | Recommended Action |
|---------------------|---------------|----------|-------------------|
| **Formal AGENTS.md** (§universal contract) | No `AGENTS.md` in our repo | MEDIUM | Adopt the thin project-layer template; reference the universal contract as a prerequisite |
| **NIST control mapping** (§SECURITY-CONTROLS) | No explicit 800-53 mapping for our system | MEDIUM | Create a lightweight control overlay for MCP-RAG (read-only tool, FIPS Moderate baseline) |
| **AI contribution attribution** (§2.1) | No formal policy; some commits have co-author trailers, most don't | LOW | Adopt PR-level disclosure (the playbook says commit-level is OPTIONAL) |
| **Pre-deployment security checklist** (§6/checklists) | No formal checklist for `update-agent-runtime` deploys | MEDIUM | Adapt the 62-item checklist to a runtime-deploy-specific subset |
| **SBOM generation** (§5.2) | No SBOM; we have `pyproject.toml` + Docker image but no formal BOM | LOW | Add `pip-audit` + `syft` to CI for automatic SBOM |
| **ADR for architecture decisions** (§15.1) | We use SDD phases and Kiro specs but not formal ADRs | LOW | SDD phases serve the same purpose; document the mapping |
| **Size limits enforcement** (§13.3) | No automated check (50-line functions, 400-line files) | LOW | Add ruff complexity rules to CI |
| **Periodic end-to-end validation** (§8.3) | We have smoke probes but no scheduled cadence beyond ad-hoc | MEDIUM | Wire the Phase 76 staleness monitor + scheduled smoke runs |

### Where the Playbook Could Learn From Us

Our system has patterns the playbook doesn't address:

- **Multi-tenant data isolation** — label-prefix scoping, per-tenant graph/vector stores
- **Spec-first policy stricter than plan-before-execute** — committed spec required before code, not just a plan
- **SDD (Structured Development Documentation)** — richer than ADRs; includes session tracking, step recording, phase lineage
- **MCP tool surface as a security boundary** — the agent can only call defined tools with defined parameters; no arbitrary code execution path exists

---

## 5. Recommendations

### Immediate (no spec needed — trivial fixes)

1. **Add a thin `AGENTS.md`** to our repo root using the playbook's template.
   Reference the universal contract as a prerequisite. Add our project-specific
   rules (spec-first, CHANGELOG, no emoji in console output, etc.)

2. **Add PR-level AI attribution** to our PR template or CONTRIBUTING.md:
   "AI-assisted PRs should note this in the PR description."

### Short-term (spec needed)

3. **Create a deploy checklist** adapted from the playbook's 62-item list.
   Scope it to our `update-agent-runtime` deploys. Include: image tag recorded,
   env vars verified, rollback command documented, functional smoke post-deploy.

4. **Map our existing controls** to NIST 800-53. Our system is narrower than
   what the playbook covers (read-only analysis tool, no user-facing auth, no
   PII processing). A 10-15 control subset would cover our actual surface.

### Long-term (growth opportunities)

5. **Contribute our patterns to the Patterns repo** — multi-tenant RAG isolation,
   spec-first policy, SDD framework, MCP tool-surface-as-security-boundary.
   These are novel federal practices that the community would benefit from.

6. **Register for the 2026 MCP Hackathon** (Sep-Oct). Our system IS an MCP
   server over government data. We could contribute our architecture as a
   reference implementation or demo.

7. **Join the AI CoP** (if not already). Monthly meetings, working groups,
   and direct access to the playbook maintainers for feedback.

---

## 6. Summary

The GSA Agentic Coding Playbook is **directly germane** to our system. It
codifies best practices we already follow (plan-before-execute, least privilege,
audit trails, no secrets in code) and identifies gaps we should close (AGENTS.md,
deploy checklist, NIST mapping).

It is **not** a regulatory mandate we must comply with — it's a community
resource we can adopt selectively. The CC0 license means we can take what we
need without attribution or restriction.

The strongest immediate value is:
- The **62-item pre-deployment checklist** (adapt for our runtime deploys)
- The **NIST 800-53 control overlay** (template for our own security narrative)
- The **Federal AI Landscape registry** (42 guidance documents we should be aware of)
- The **2026 MCP Hackathon** (community exposure for our work)

Our system is **more rigorous** than the playbook in several areas (spec-first
policy, multi-tenant isolation, SDD phases). We should contribute these patterns
back to the ecosystem — GSA TTS explicitly invites this via the Patterns repo.
