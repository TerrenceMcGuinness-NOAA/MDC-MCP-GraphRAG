# Phase 31: SDD Execution Model Refactor

**Status**: IN PROGRESS
**Priority**: CRITICAL — Architectural realignment
**Created**: February 18, 2026
**Supersedes**: Phase 4B ISD approval infrastructure (partial), dry_run execution concept
**Depends On**: Phase 4 (Bootstrap Capability), Phase 4B (ISD)
**Enables**: Phase 4C USD (Claude CLI / GitHub CLI YOLO modes)

---

## Problem Statement

The Phase 4B Interactive Supervised Development (ISD) approval infrastructure was designed around an execution model where the MCP server itself gates and approves workflow steps via multi-turn tool calls. In practice, this model is **redundant in the IDE modality** (VS Code + GitHub Copilot, Claude Desktop) because:

1. **The IDE chat window IS the approval mechanism.** Every tool call requires a human turn in the conversation. The plugin manages approval natively — there is no unsupervised execution path that needs gating.

2. **Dry-run is semantically meaningless.** An SDD workflow is a *plan*. Previewing a plan before executing a plan is circular. The value is in tracking *which plan is active* and *what state we're in*, not in simulating execution.

3. **The approval infrastructure has never been used in production.** Zero executions recorded. The ISD code (6 files, ~1,200 lines) is well-engineered but addresses a problem that doesn't exist in the IDE modality.

4. **Step type semantics are over-engineered for IDE use.** The verb+noun paradigm (generate_file, execute_command, validate_service) with side-effect detection was designed for an autonomous executor. In IDE mode, the AI agent and human are collaborating turn-by-turn — the agent doesn't need permission categories because the human is already in the loop.

### What DOES matter

The **core SDD value proposition** remains valid and important:

- **Well-designed work efforts up front** — SDD workflow specs define scope, steps, success criteria, and dependencies *before* coding starts
- **Session-persistent state tracking** — Know which phase/step you're on, what's done, what's remaining, across conversation sessions
- **Clear execution history** — Audit trail of what was accomplished, when, by whom
- **Structured handoff** — A new session (or new agent) can pick up where the last one left off

### The future of ISD

The ISD approval concept will be **realized when we shift modalities**:

- **Claude CLI** with `--dangerously-skip-permissions` (YOLO mode) — the SDD framework becomes the safety layer, gating autonomous execution against the spec
- **GitHub CLI** with Copilot extensions — batch execution of SDD steps as CI/CD-like pipelines
- **n8n workflows** — webhook-triggered autonomous execution with approval gates

In these modalities, the executor IS autonomous and approval gates ARE necessary. The current ISD infrastructure should be **preserved but dormant**, not deleted.

---

## Design: Session-Oriented Execution Model

### Core Concept: "Working a Phase"

Replace the dry_run → supervised → auto_approved execution mode hierarchy with a single concept: **starting, tracking, and completing a phase**.

```
┌──────────────────────────────────────────────────────────┐
│                    SDD Session Lifecycle                  │
│                                                          │
│  1. ACTIVATE    — Declare which phase you're working on  │
│  2. TRACK       — Record step completions as they happen │
│  3. PERSIST     — Save state across sessions/restarts    │
│  4. RESUME      — Pick up where you left off             │
│  5. COMPLETE    — Mark phase done with summary           │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### Step Type Simplification

Replace the verb+noun approval-oriented taxonomy with **intent-based semantic tags** that describe what a step accomplishes, not what permissions it needs:

| Tag | Meaning | Examples |
|-----|---------|----------|
| `research` | Gather information, read code, search docs | Explore codebase, read existing impl |
| `design` | Make architectural decisions, define interfaces | Choose approach, define schema |
| `implement` | Write or modify code | Create files, edit functions, add tests |
| `configure` | Set up infrastructure or settings | Docker compose, env vars, systemd |
| `validate` | Verify correctness | Run tests, check health, review output |
| `document` | Update docs, changelog, comments | CHANGELOG.md, README, inline docs |
| `ingest` | Update knowledge base | Run ingestion scripts, rebuild graph |

These tags are **descriptive, not prescriptive**. They help the human and AI understand the nature of each step. They do NOT gate execution — execution gating is the IDE's responsibility in IDE mode, and the ISD infrastructure's responsibility in CLI/YOLO mode.

### Persistent State Schema

Replace the in-memory `executionHistory[]` array and the 5-minute-TTL `ExecutionStateStore` with a **durable JSONL log** and a **current session state file**:

#### Active Session State (`sdd_framework/execution_state/active_session.json`)

```json
{
  "sessionId": "session_2026-02-18_001",
  "phase": "phase31_sdd_execution_model_refactor",
  "startedAt": "2026-02-18T14:30:00Z",
  "lastActivityAt": "2026-02-18T15:45:00Z",
  "status": "in_progress",
  "currentStep": 3,
  "totalSteps": 8,
  "completedSteps": [
    {
      "step": 1,
      "name": "Review current ISD implementation",
      "tag": "research",
      "completedAt": "2026-02-18T14:35:00Z",
      "notes": "6 approval files, ~1,200 lines, never used in production"
    },
    {
      "step": 2,
      "name": "Design new execution model",
      "tag": "design",
      "completedAt": "2026-02-18T15:00:00Z",
      "notes": "Session-oriented model, semantic tags, persistent state"
    }
  ],
  "skippedSteps": [],
  "blockers": []
}
```

#### Execution History Log (`sdd_framework/execution_state/history.jsonl`)

```jsonl
{"sessionId":"session_2026-02-18_001","phase":"phase31_sdd_execution_model_refactor","event":"started","timestamp":"2026-02-18T14:30:00Z"}
{"sessionId":"session_2026-02-18_001","phase":"phase31_sdd_execution_model_refactor","event":"step_completed","step":1,"name":"Review current ISD implementation","tag":"research","timestamp":"2026-02-18T14:35:00Z"}
```

This log is **append-only** and survives server restarts. It provides the audit trail that the in-memory array never could.

---

## Implementation Steps

### Step 1: Create `SessionManager.js`
**Tag**: implement
**Target**: `mcp_server_node/src/sdd/SessionManager.js`

New module responsible for:
- `startSession(phaseName)` — Create active session state file
- `recordStep(stepNumber, name, tag, notes)` — Mark step complete, append to history
- `skipStep(stepNumber, reason)` — Record skipped step with reason
- `getSessionState()` — Return current session (or null if none active)
- `resumeSession()` — Load last active session for continuation
- `completeSession(summary)` — Mark phase complete, archive session
- `getHistory(options)` — Query execution history with filters

State files live in `sdd_framework/execution_state/` (already exists, currently empty except README).

### Step 2: Refactor `SDDWorkflowTools.js` — Replace approval-centric tools
**Tag**: implement
**Target**: `mcp_server_node/src/tools/SDDWorkflowTools.js`

**Remove or deprecate**:
- `execute_sdd_workflow` — The `dry_run` parameter and raw execution path
- `execute_sdd_workflow_supervised` — The multi-turn approval flow
- `manage_sdd_execution_state` — The TTL-based state store management

**Replace with**:
- `start_sdd_session` — Activate a phase, parse its steps, create session state
- `record_sdd_step` — Mark a step complete with notes (called as work progresses)
- `get_sdd_session` — Return current active session state (for resume across sessions)
- `complete_sdd_session` — Finalize phase, write summary, archive

**Keep unchanged**:
- `list_sdd_workflows` — Still needed
- `get_sdd_workflow` — Still needed (parse and display workflow spec)
- `validate_sdd_compliance` — Still needed (content validation)
- `get_sdd_framework_status` — Update to reflect session model instead of execution modes
- `get_sdd_execution_history` — Rewrite to read from JSONL history file instead of in-memory array

### Step 3: Update step type reference
**Tag**: document
**Target**: `sdd_framework/workflows/_sdd_step_type_reference.md`

Replace the verb+noun paradigm documentation with the simplified semantic tag system. Keep a "Legacy Reference" section documenting the old system for the CLI/YOLO modality future.

### Step 4: Preserve ISD infrastructure for CLI modality
**Tag**: configure
**Target**: `mcp_server_node/src/sdd/approval/`

Do NOT delete the approval infrastructure. Instead:
- Add a header comment to each file: "Reserved for CLI/YOLO execution modality (Phase 4C USD)"
- Remove imports from `SDDWorkflowTools.js` (they'll be re-imported when CLI mode is built)
- Keep all 6 files intact for future use

### Step 5: Wire `SessionManager` into `UnifiedMCPServer.js`
**Tag**: implement
**Target**: `mcp_server_node/src/UnifiedMCPServer.js`

- Import `SessionManager` and pass to `SDDWorkflowTools` constructor
- Update `getServerInfo()` tool count and capability descriptions
- Update `mcp_health_check` to report active session if one exists

### Step 6: Validate with live test
**Tag**: validate

- Start a session against this very phase (phase31)
- Record completion of steps 1-5
- Verify state persists across server restart
- Verify history.jsonl accumulates entries
- Complete the session

### Step 7: Update CHANGELOG and copilot-instructions
**Tag**: document
**Target**: `CHANGELOG.md`, `.github/copilot-instructions.md`

- Add v7.14.0 entry documenting the execution model refactor
- Update copilot-instructions SDD section to reference session model

### Step 8: Rebuild Docker image
**Tag**: configure

- Rebuild `eib-mcp-rag:latest` with updated SDD tools
- Restart gateway to pick up new tools
- Verify new tools available via gateway health check

---

## Success Criteria

| Criterion | Measure |
|-----------|---------|
| Active session tracking works | `start_sdd_session` creates state file, `get_sdd_session` returns it |
| Step recording persists | `record_sdd_step` appends to JSONL, survives restart |
| Session resume works | New conversation can call `get_sdd_session` and see prior progress |
| Session completion works | `complete_sdd_session` archives state and writes summary |
| History is queryable | `get_sdd_execution_history` reads JSONL, returns filtered results |
| ISD code preserved | All 6 approval files intact with CLI-modality header comments |
| No dry_run concept | No tool exposes a dry_run parameter |
| Docker gateway updated | New tools visible via `mcp_health_check` |

---

## What This Enables

### Immediate (IDE modality)
- Start a coding session by saying "let's work Phase 27F"
- Agent calls `start_sdd_session({ phase: "phase27_jjob_script_rag_enhancement" })`
- As work progresses, agent calls `record_sdd_step()` after each milestone
- Next session: agent calls `get_sdd_session()` → sees where we left off
- On completion: `complete_sdd_session()` → logged, auditable, archived

### Future (CLI/YOLO modality — Phase 4C USD)
- Claude CLI or GitHub CLI reads the SDD spec
- ISD approval infrastructure gates each side-effect step
- The same `SessionManager` tracks progress
- The verb+noun step types determine which steps need human approval
- YOLO mode: auto-approve all steps within spec scope

The execution model is **modality-aware**: in IDE mode, tracking is collaborative. In CLI mode, tracking becomes enforcement. Same data model, different approval policy.

---

## Non-Goals

- Deleting the ISD approval code (preserved for CLI modality)
- Changing the SDD spec markdown format (steps, phases, metadata all stay the same)
- Building the CLI/YOLO execution path (that's Phase 4C USD)
- Adding a database for state storage (JSONL files are sufficient and portable)
