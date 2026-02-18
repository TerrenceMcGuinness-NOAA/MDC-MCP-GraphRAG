# SDD Workflow Step Type Reference

**Purpose**: Define step type vocabulary for SDD workflow specifications.

**Related Files**:
- `mcp_server_node/src/sdd/SessionManager.js` — Session lifecycle and step recording
- `mcp_server_node/src/sdd/WorkflowExecutor.js` — Parses workflow markdown

---

## Semantic Step Tags (Phase 31)

SDD workflow steps use **intent-based semantic tags** that describe what a step accomplishes. These tags are **descriptive, not prescriptive** — they help humans and AI understand the nature of each step but do NOT gate execution.

In IDE modality (VS Code, Copilot, Claude Desktop), the chat window itself is the approval mechanism. In future CLI/YOLO modality (Phase 4C USD), the preserved ISD approval infrastructure will enforce execution gates.

### Tag Reference

| Tag | Meaning | Examples |
|-----|---------|----------|
| `research` | Gather information, read code, search docs | Explore codebase, read existing impl |
| `design` | Make architectural decisions, define interfaces | Choose approach, define schema |
| `implement` | Write or modify code | Create files, edit functions, add tests |
| `configure` | Set up infrastructure or settings | Docker compose, env vars, systemd |
| `validate` | Verify correctness | Run tests, check health, review output |
| `document` | Update docs, changelog, comments | CHANGELOG.md, README, inline docs |
| `ingest` | Update knowledge base | Run ingestion scripts, rebuild graph |

### Step Format in Workflow Specs

```markdown
### Step N: <Human-Readable Title>
**Tag**: <semantic_tag>
**Target**: <file path or component>

Description of what this step accomplishes and any important details.
```

### Example

```markdown
### Step 1: Create SessionManager.js
**Tag**: implement
**Target**: `mcp_server_node/src/sdd/SessionManager.js`

New module responsible for session lifecycle: startSession, recordStep,
skipStep, getSessionState, resumeSession, completeSession, getHistory.

### Step 2: Validate with live test
**Tag**: validate

Start a session against phase31, record step completions, verify state
persists across server restart.
```

---

## Session Lifecycle

Steps are tracked through the SDD session tools:

```
1. start_sdd_session({ phase: "phase31_..." })   → Creates active session
2. record_sdd_step({ step: 1, name: "...", tag: "implement" })  → Records progress
3. get_sdd_session()                              → Check current state
4. complete_sdd_session({ summary: "..." })       → Finalize and archive
```

Session state persists in `sdd_framework/execution_state/active_session.json`.
History is appended to `sdd_framework/execution_state/history.jsonl`.

---

## File Organization

```
sdd_framework/workflows/
├── phase23_static_mode_multiuser_gateway.md   ← Workflow spec
├── phase31_sdd_execution_model_refactor.md    ← Workflow spec
├── _sdd_step_type_reference.md                ← This guide
└── _templates/
    └── workflow_template.md                   ← Starter template
```

---

## Legacy Reference: Verb + Noun Paradigm

> **Note**: The verb+noun step type system below was designed for the Phase 4B ISD approval
> infrastructure. It is preserved here for the future CLI/YOLO execution modality (Phase 4C USD),
> where autonomous execution requires permission-based gating. The approval infrastructure code
> is preserved in `mcp_server_node/src/sdd/approval/`.

### Verb = HOW (Determines Approval)

| Verb | Meaning | Approval | Why |
|------|---------|----------|-----|
| `generate` | LLM synthesizes content | Required | Non-deterministic output |
| `write` | Literal content copied | Context | Content is shown, may auto-approve |
| `execute` | Run command/script | Required | Side effects on system |
| `delete` | Remove artifact | Required | Destructive operation |
| `read` | Query/inspect | Auto | No state change |
| `validate` | Verify condition | Auto | No state change |

### Noun = WHAT/WHERE (Clarifies Target)

| Noun | Target Type | Examples |
|------|-------------|----------|
| `file` | File on disk | config, script, service unit |
| `command` | Shell execution | systemctl, docker, git |
| `query` | Data retrieval | ChromaDB search, Neo4j query |
| `service` | System service | start, stop, restart |

### Combined Step Types

```
generate_file     → LLM creates file content (approval required)
write_file        → Copy literal content to file (content shown)
execute_command   → Run shell command (approval required)
delete_file       → Remove file (approval required)
read_query        → Retrieve data (auto-execute)
validate_service  → Check service status (auto-execute)
```

### Migration from Legacy Types

| Legacy Type | Verb+Noun Type |
|-------------|----------------|
| `code_generation` | `generate_file` |
| `file_creation` | `write_file` or `generate_file` |
| `command` | `execute_command` |
| `ingestion` | `execute_ingest` |
| `health_check` | `check_health` |
| `data_query` | `read_query` |
| `validation` | `validate_*` |
