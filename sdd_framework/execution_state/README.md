# Execution State Directory

This directory contains persistent state files for SDD session tracking (Phase 31).

## Files

### `active_session.json` — Current Active Session

Only one session is active at a time. Created by `start_sdd_session`, removed on `complete_sdd_session`.

```json
{
  "sessionId": "session_2026-02-18_a1b2c3",
  "phase": "phase31_sdd_execution_model_refactor",
  "startedAt": "2026-02-18T14:30:00Z",
  "lastActivityAt": "2026-02-18T15:45:00Z",
  "status": "in_progress",
  "currentStep": 3,
  "totalSteps": 8,
  "completedSteps": [
    {
      "step": 1,
      "name": "Create SessionManager.js",
      "tag": "implement",
      "completedAt": "2026-02-18T14:35:00Z",
      "notes": "Created with 7 public methods"
    }
  ],
  "skippedSteps": [],
  "blockers": []
}
```

### `history.jsonl` — Append-Only Event Log

Every session event is logged as a single JSON line. Survives server restarts and provides an audit trail.

```jsonl
{"sessionId":"session_2026-02-18_a1b2c3","phase":"phase31_sdd_execution_model_refactor","event":"started","timestamp":"2026-02-18T14:30:00Z"}
{"sessionId":"session_2026-02-18_a1b2c3","phase":"phase31_sdd_execution_model_refactor","event":"step_completed","step":1,"name":"Create SessionManager.js","tag":"implement","timestamp":"2026-02-18T14:35:00Z"}
{"sessionId":"session_2026-02-18_a1b2c3","phase":"phase31_sdd_execution_model_refactor","event":"completed","summary":"Refactored execution model","timestamp":"2026-02-18T16:00:00Z"}
```

### Event Types

| Event | Description |
|-------|-------------|
| `started` | New session activated |
| `step_completed` | Step marked as done |
| `step_skipped` | Step skipped with reason |
| `resumed` | Session resumed in a new conversation |
| `completed` | Session finished successfully |
| `abandoned` | Session terminated without completion |
| `symbol_examined` | Symbol auto-recorded via `get_code_context` (Phase 24H-3) |
| `file_modified` | File modification tracked via `mark_as_modified` (Phase 24H-3) |
| `checkpoint_created` | Session state checkpointed via `checkpoint_state` (Phase 24H-3) |
| `checkpoint_restored` | Session state restored via `restore_checkpoint` (Phase 24H-3) |

### Semantic Step Tags

| Tag | Meaning |
|-----|---------|
| `research` | Gather information, read code, search docs |
| `design` | Architectural decisions, define interfaces |
| `implement` | Write or modify code |
| `configure` | Infrastructure or settings setup |
| `validate` | Verify correctness (tests, health checks) |
| `document` | Update docs, changelog, comments |
| `ingest` | Update knowledge base |

## Managed By

- `SessionManager.js` — Session lifecycle management + Phase 24H-3 session state (modifications, examined, checkpoints)
- `SDDWorkflowTools.js` — MCP tool interface (`start_sdd_session`, `record_sdd_step`, etc.)
- `GraphRAGTools.js` — Session state tools (`mark_as_modified`, `get_session_context`, `checkpoint_state`, `restore_checkpoint`)

### `checkpoints/` — Session State Checkpoints (Phase 24H-3)

Checkpoint files created by `checkpoint_state`. Each file is a JSON snapshot of `modifications[]`, `examined[]`, and step progress at the time of creation.

Format: `<checkpoint_id>.json` (e.g., `chk_2026-02-24_a1b2c3.json`)

## Legacy Files

The TTL-based `<execution_id>.json` files from Phase 4B `ExecutionStateStore.js` are no longer created. The approval infrastructure is preserved in `mcp_server_node/src/sdd/approval/` for future CLI/YOLO modality (Phase 4C USD).
