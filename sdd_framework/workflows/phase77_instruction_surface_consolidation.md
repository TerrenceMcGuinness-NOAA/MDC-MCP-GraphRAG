# Phase 77: Instruction Surface Consolidation and Enforcement

| Field | Value |
|-------|-------|
| **Version** | v1.0.0 |
| **Status** | DESIGN — not started |
| **Date** | 2026-08-10 |
| **Execution Mode** | SDD Session (Phase 31 model) |
| **Supersedes** | Phase 32 (AI Instruction File Architecture, 2026-02-24) |
| **Related** | Phase 62 (`extract_ci_error_signal`), Phase 63b (Node→Python gateway swap), GSA Playbook Security Controls Reconciliation v2.1 |
| **Branch** | `develop_aws` (feature branch if multi-session) |

---

## 1. Problem Statement

Phase 32 restructured the agent instruction surface in February 2026. Its **structural**
work succeeded and still holds: conditional loading via `applyWhen`, YAML front matter,
separation of base guidance from MCP tool reference. Its **currency** work did not
survive, because the mechanism it left behind was a prose rule rather than a check.

Phase 32 §6 closes with: *"After any `server.registerTool()` change ... re-run the tool
coverage check and update all three files."* Nothing enforces it. The result is the same
failure shape as the April 22 CDK corrective action and the spec-first policy — correct
diagnosis, advisory remediation, recurrence.

Since Phase 32 the surface has also grown a second vendor ecosystem (Kiro steering +
hooks) that Phase 32 did not know about, and two platform swaps (COTS→AWS backend,
Node→Python server) invalidated content it deliberately left alone.

### 1.1 Current state — measured 2026-08-10

Ground truth from `get_server_info`: **53 tools, 9 of 10 modules.**

| # | Surface | Lines | Consumer | Defects |
|---|---------|-------|----------|---------|
| S1 | `.github/copilot-instructions.md` | 206 | Copilot (always) | Says 52 tools. "Node.js MCP Server" — Phase 63b swapped to Python. Cites `.vscode/mcp.json` as SPOT; live config is `.kiro/settings/mcp.json`. |
| S2 | `.github/instructions/eib-mcp-tools.instructions.md` | 302 | Copilot (`applyWhen`) | Says 52 tools / 9 modules / v7.28.0. Missing `extract_ci_error_signal`. All module headers label backends **ChromaDB + Neo4j**; AWS deployment is OpenSearch + Neptune. Regeneration header points at the retired Node server. |
| S3 | `.github/cursor-instructions.md` | 377 | Cursor (likely none) | Scoped to *global-workflow*, not this repo. References `MCP_node.js-RAG_development` branch, `mcp-server-rag.js`, Xenova transformers, `~/.cursor/mcp.json`. Lists ~9 tools. Non-standard filename — Cursor reads `.cursorrules` / `.cursor/rules/`. Effectively orphaned. |
| S4 | `.github/mcp.json` | 25 | unclear | Points at retired `mcp_server_node/src/UnifiedMCPServer.js`. Mount root `/mcp_rag_eib/`; actual is `/mdc-mcp-rag/`. Contains plaintext `NEO4J_PASSWORD`. |
| S5 | `.kiro/steering/*.md` (14 files) | 2,476 | Kiro | **Inclusion modes inverted — see §1.2.** |
| S6 | `.kiro/hooks/*.json` (2 files) | — | Kiro | Both `PostFileSave` + `action.type: agent` — advisory and post-hoc. CDK hook does not fire at `cdk deploy`. |
| S7 | `.kiro/settings/mcp.json` | — | Kiro | Current and correct (the live config). |

**Total: 3,361 lines across 7 surfaces and 4 vendor formats, with no SPOT and no validation.**

### 1.2 P8 — Steering inclusion is inverted (new, highest severity)

Verified against a live session on 2026-08-10:

| Inclusion mode | Files | Loaded in session |
|---|---|---|
| `inclusion: auto` | 01-architecture, **02-development-workflow**, 03-naming, 04-phase48-progress, **05-cdk-data-safety**, **07-feature-branch-spec-workflow**, **08-git-operation-policy** | **None** |
| `inclusion: always` | 09-agentcore-consumer, 10-tool-guide | Yes |
| no front matter (defaults to always) | 06-python-port-progress, 07-tenant-usability-gaps, 11-tenant-roadmap, 12-multi-tenant-gap-tracker, 13-ci-error-reporting-policy | Yes |

**1,540 lines loaded; 936 lines not loaded.** The 936 that did not load contain every
hard behavioral rule in the project. The 1,540 that did load are predominantly progress
logs and gap trackers — historical state, not rules.

Observed consequences in that session:

1. The agent made four commits and one push. `08-git-operation-policy.md` was never in
   context. Compliance occurred because the user requested each action explicitly and the
   agent's base instructions require it — not because the project policy was loaded.
2. `05-cdk-data-safety.md` — the direct corrective action from the April 22, 2026 Neptune
   data-loss incident — was not in context. Any CDK work in that session would have
   proceeded without it.
3. The Spec-First Rule reached the agent **only because `spec-first-guard.json` inlines a
   copy of it.** The hook's "Reference rules" section cites `02-development-workflow.md`
   and `07-feature-branch-spec-workflow.md`; neither was loaded. The citation is
   decorative. **The hook is effective precisely because it duplicates the rule instead of
   referencing it** — a deliberate SPOT violation that is load-bearing. Any consolidation
   must preserve that property or replace it with a real gate.

### 1.3 P9 — No enforcement substrate exists

```
.github/workflows/        absent
.gitlab-ci.yml            absent
.pre-commit-config.yaml   absent
```

No CI and no pre-commit anywhere in the repo. `mcp_server_node/scripts/generate-tool-docs.js`
exists — a drift detector *was* built — but it targets the retired Node server, has no
Python successor, and has no runner. It is dead code from an enforcement standpoint.

Consequence: **Kiro hooks are currently the only available enforcement point in the
system.** This is the root cause of every advisory-only control identified in the GSA
reconciliation v2.1 — there is nowhere else to put a gate.

### 1.4 Carried-forward Phase 32 problems

| Phase 32 ID | Status |
|---|---|
| P1 MCP instructions load unconditionally | **Fixed, holding** |
| P2 Base instructions reference MCP at top | **Fixed, holding** |
| P3 Tool counts stale (34 → actual 42) | **RECURRED** — now 52 → actual 53 |
| P4 Non-existent tools listed | Fixed |
| P5 `applyWhen` not in YAML front matter | **Fixed, holding** |
| P6 8 tools undocumented | Fixed, then re-broken by Phase 62 |
| P7 No standalone global-workflow instruction file | Out of scope here (lives in the global-workflow repo) |

---

## 2. Target Architecture

### Design Principles

Inherits Phase 32's five principles, adds three:

1. *(P32)* **Conditional loading** — vendor-gated content loads only when relevant
2. *(P32)* **Context budget** — enforced per file, measured
3. *(P32)* **SPOT** — each concern in exactly one file
4. *(P32)* **Graceful degradation** — function without MCP, better with it
5. *(P32)* **Schema compliance** — valid front matter per vendor schema
6. **NEW — Replace, never add.** Net surface count must decrease. A consolidation that
   adds an eighth file has failed.
7. **NEW — Generate anything countable.** Any statement containing a tool count, module
   count, or tool name is generated from the live registry, never hand-maintained. P3
   has recurred twice because a human had to remember.
8. **NEW — Fail closed on presence and currency.** Contract presence and doc-vs-registry
   agreement are checked mechanically at session start and pre-commit, not asserted in prose.

### Target Surface Inventory

| Surface | Fate | Target |
|---|---|---|
| `AGENTS.md` (root) | **NEW — the behavioral SPOT** | Vendor-neutral behavioral contract per the [agents.md standard](https://agents.md), read natively by Kiro, Copilot, Cursor, Claude Code, Codex, and 20+ others. Hand-written, ~150 lines, contains **no counts**. |
| `.github/instructions/eib-mcp-tools.instructions.md` | **GENERATED** | Tool reference emitted from the live registry. `applyWhen` retained. No prose duplication of behavioral rules. |
| `.github/copilot-instructions.md` | **REDUCED to a pointer** | ~20 lines: "behavioral contract is in `/AGENTS.md`; tool reference loads conditionally." Platform-dev specifics (build/test commands, gateway rebuild table) move to `AGENTS.md` or a `docs/` page. |
| `.github/cursor-instructions.md` | **DELETE** | Orphaned, wrong repo scope, non-standard filename, badly stale. Nothing reads it. |
| `.github/mcp.json` | **DELETE or FIX** | Points at a retired server with a wrong path and a plaintext credential. If any consumer still needs it, regenerate from `.kiro/settings/mcp.json`; otherwise remove. |
| `.kiro/steering/*.md` | **RE-CLASSIFIED** | Behavioral rules → `always`. Progress logs and gap trackers → `manual` or `fileMatch`. Rules that duplicate `AGENTS.md` → reduced to project-specific deltas. |
| `.kiro/hooks/*.json` | **AUGMENTED** | Add `SessionStart` contract-presence check and a `PreToolUse` gate. Existing two retained; CDK hook additionally bound to the deploy action. |
| `.pre-commit-config.yaml` | **NEW** | The substrate. Doc-currency check, secret scan, lint. |

### Net effect

7 surfaces / 3,361 lines / 4 formats → **6 surfaces / ~2,400 lines / 1 canonical format
plus generated vendor views**, with two mechanical gates where there are currently none.

---

## 3. Implementation Steps

Ordered by dependency. Step 1 is independently valuable and should land first regardless
of whether later steps proceed.

### Step 1 — Steering inclusion audit *(tag: configure)*

Highest value, lowest cost, no new tooling. Front-matter edits only.

- Promote to `inclusion: always`: `02-development-workflow.md`,
  `05-cdk-data-safety.md`, `07-feature-branch-spec-workflow.md`,
  `08-git-operation-policy.md`
- Evaluate `01-architecture-context.md` and `03-naming-conventions.md` for `always`
  versus `fileMatch`
- Demote to `manual` or `fileMatch`: `04-phase48-progress.md`,
  `06-python-port-progress.md`, `07-tenant-usability-gaps.md`,
  `11-tenant-roadmap.md`, `12-multi-tenant-gap-tracker.md`
- Resolve the `07-` prefix collision (`07-feature-branch-spec-workflow.md` and
  `07-tenant-usability-gaps.md`)
- Add front matter to the five files that currently have none, so the mode is explicit
  rather than defaulted

Expected outcome: behavioral rules present in every session; **net context cost flat or
lower**, since 936 lines of rules displace ~1,000 lines of progress logs.

### Step 2 — Enforcement substrate *(tag: configure)*

- Create `.pre-commit-config.yaml`
- Hooks: `ruff` (lint + format), a secret scan (`gitleaks` or `detect-secrets`),
  trailing-whitespace / end-of-file, and a placeholder for the Step 3 currency check
- Document the one-command bootstrap (`make setup` or equivalent) per playbook §15.3
- Unblocks the deferred v2.1 recommendations (`pip-audit`, SAST, SBOM) that assumed a
  substrate

### Step 3 — Tool documentation generator, Python *(tag: implement)*

- `mcp_server_python/scripts/generate_tool_docs.py`, modelled on the Node original
- Source of truth: the live FastMCP registry (or `src/tools/*.py` introspection) — never
  a hand-maintained list
- Emits the tool tables in `eib-mcp-tools.instructions.md` between generated markers,
  matching the `GENERATED:...:START/END` convention the GSA playbook uses
- `--check` mode: non-zero exit on any divergence between docs and registry
- Wire `--check` into Step 2's pre-commit config
- Retire `mcp_server_node/scripts/generate-tool-docs.js`

### Step 4 — Author `AGENTS.md` *(tag: document)*

- Root-level, agents.md standard, vendor-neutral
- Contains: core principles and priority order, spec-first gate, git operation policy,
  data-safety rules, console-output and code-style conventions, SPOT registry, prohibited
  actions, verification expectations
- Contains **no** tool counts, module counts, or tool names — those live only in generated output
- Decide and record whether to declare the GSA universal contract as a prerequisite
  (`~/.agentic-coding-playbook/AGENTS.md`) or to remain self-contained. Recommendation:
  self-contained initially, with an explicit note on divergence from the GSA universal
  contract, since we are not currently provisioning that file
- **Preserve the load-bearing duplication from §1.2 item 3:** hooks must keep inlining the
  rules they enforce, or the inlining must be replaced by a real gate in Step 6. Do not
  reduce hooks to citations.

### Step 5 — Reduce and retire vendor surfaces *(tag: implement)*

- `.github/copilot-instructions.md` → pointer file; relocate platform-dev content
- Delete `.github/cursor-instructions.md`
- Delete or regenerate `.github/mcp.json` (see §5 for the credential cross-reference)
- Reduce steering files that duplicate `AGENTS.md` to project-specific deltas only
- Verify no behavioral rule exists in more than one place

### Step 6 — Wire the gates *(tag: configure)*

- `SessionStart` hook: assert `AGENTS.md` present and doc-vs-registry current; fail closed
  with a clear message if not
- `PreToolUse` hook on `execute_bash`: `action.type: command`, exit 2 to block or
  `permissionDecision: "ask"` to confirm, matching irreversible operations
  (`cdk deploy`, `update-agent-runtime`, `aws * delete-*`, `git push`, `rm -rf`)
- Bind the CDK safety check to the **deploy action**, closing the April 22 corrective
  action #6 / #10 gap identified in reconciliation v2.1 §4.3
- Preserve rule inlining in hook prompts per Step 4

### Step 7 — Validate and record *(tag: validate)*

- Run the §4 validation matrix
- Confirm in a fresh session that the promoted steering files appear in context
- Confirm `--check` fails on an intentionally stale doc, then passes after regeneration
- Confirm the `PreToolUse` gate blocks a representative command
- CHANGELOG entry; SDD session history

---

## 4. Validation Criteria

| # | Check | Expected |
|---|-------|----------|
| V1 | `AGENTS.md` exists at repo root with valid agents.md structure | Pass |
| V2 | `grep -c` for any tool count in a hand-maintained file | 0 |
| V3 | `generate_tool_docs.py --check` on a clean tree | exit 0 |
| V4 | Same, after adding a tool without regenerating | non-zero |
| V5 | Tool count in generated docs equals `get_server_info` | 53 (or current) |
| V6 | `extract_ci_error_signal` documented | Pass |
| V7 | Backend labels reflect the active `DB_BACKEND`, not hardcoded ChromaDB/Neo4j | Pass |
| V8 | Fresh session context contains 02, 05, 07-feature-branch, 08 | Pass |
| V9 | Progress logs absent from a fresh session unless requested | Pass |
| V10 | Total always-loaded steering lines | ≤ 1,540 (no regression) |
| V11 | `.github/cursor-instructions.md` | absent |
| V12 | Plaintext credential in any `.github/` file | 0 occurrences |
| V13 | `.pre-commit-config.yaml` present; `pre-commit run --all-files` passes | Pass |
| V14 | `SessionStart` hook fails closed when `AGENTS.md` is removed | Pass |
| V15 | `PreToolUse` gate blocks or prompts on a matched command | Pass |
| V16 | No behavioral rule appears in two hand-maintained files | Pass |
| V17 | Hook prompts still inline the rules they enforce | Pass |

---

## 5. Dependencies and Cross-References

| Item | Relationship |
|---|---|
| **Credential sweep** | `.github/mcp.json` carries a plaintext `NEO4J_PASSWORD`, one of 30+ tracked occurrences of the same value (Dockerfiles, `docker-compose.yml`, gateway catalog, 6 provisioning scripts, 2 READMEs, ~15 ingester defaults). Step 5 removes it from `.github/` only. **The systemic sweep is a separate security concern** and should be tracked with the SC-28 `/tmp` finding from reconciliation v2.1, not absorbed here. Separation of concerns. |
| **GSA reconciliation v2.1** | Step 2 unblocks the CI-dependent recommendations (RA-5, SI-3, SR-3) that assumed a substrate. Step 6 addresses CM-7, CM-5, AC-5. Step 1 addresses CM-2 and SA-15 — a documented baseline that is not delivered to the agent is not an effective baseline. |
| **Phase 62** | Introduced `extract_ci_error_signal` and the `error_analysis` module; the immediate cause of the current P3 recurrence. Step 3 makes such additions self-documenting. |
| **Phase 63b** | Node→Python gateway swap; invalidated the generator path and the "Node.js MCP Server" architecture line. |
| **Phase 32** | Superseded. Its structural design is retained; its prose-rule maintenance mechanism is replaced by Step 3. |
| **global-workflow repo** | Phase 32's P7 (standalone instruction file) and `instructions/mcp.instructions.md` live there. Out of scope; note if a companion change is needed. |

---

## 6. Context Budget Analysis

| Scenario | Current | Target |
|----------|---------|--------|
| Kiro session, always-loaded steering | 1,540 lines (~62% progress logs) | ~1,500 lines (~95% behavioral rules) |
| Copilot, no MCP | 206 lines (partly stale) | ~20-line pointer + `AGENTS.md` ~150 = ~170 |
| Copilot, MCP active | 206 + 302 = 508 | ~170 + generated reference ~250 = ~420 |
| Cursor | 377 lines, likely unread | 0 |

Net: comparable or lower token cost, with the material difference that the loaded content
is behavioral rules rather than historical status.

---

## 7. Risks and Rollback

| Risk | Mitigation |
|---|---|
| Promoting four steering files to `always` inflates context | V10 caps total; demotions offset promotions |
| Generated markers clobber hand-written prose | Generator writes only between explicit markers; V16 audit before enabling |
| `PreToolUse` gate blocks legitimate work | Start with `permissionDecision: "ask"` rather than exit 2; tune the match list from observed friction |
| `AGENTS.md` becomes an eighth stale surface | Principles 6-8 exist to prevent this; V2 and V16 enforce |
| Deleting `.github/mcp.json` breaks an unknown consumer | Confirm no consumer first; the file is preserved in git history |

**Rollback:** every step is independently revertible. Step 1 is front matter only. Steps 2-3
add files. Steps 4-6 are additive plus two deletions recoverable from history.

---

## 8. Notes

The through-line from the April 22 postmortem, the spec-first policy, Phase 32, and this
phase is a single pattern: **this project diagnoses correctly and remediates advisorily.**
Phase 32's §6 rule, the CDK hook's file-save trigger, and the steering citations that
point at unloaded files are three instances of the same shape.

The distinguishing commitment of Phase 77 is that every rule it establishes must be
either generated or gated. Where it cannot be, that is recorded as an accepted risk with a
named owner rather than left as prose.
