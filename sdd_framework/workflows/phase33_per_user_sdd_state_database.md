# Phase 33: Per-User SDD Session State via Database Backend

**Version**: 1.0.0
**Date**: February 26, 2026
**Status**: USER STORY (Not yet specced for execution)
**Priority**: High
**Estimated Effort**: 8-16 hours
**Upstream Dependencies**: Phase 31 (Session Model), Phase 4D (Multi-Tenant — planning only)
**Downstream Consumers**: All SDD users on shared infrastructure

---

## User Story

**As a** developer using the MCP/RAG platform on a shared VM or multi-user cluster,
**I want** SDD sessions to be isolated per user and stored in a database,
**So that** multiple developers can run concurrent SDD sessions without overwriting each other's state, and sessions survive container restarts and filesystem cleanup.

---

## Problem Statement

### Current State

The SDD session system (Phase 31) stores all state as flat files on disk:

```
sdd_framework/execution_state/
├── active_session.json     ← SINGLE file, one active session globally
├── history.jsonl           ← Append-only log, all users interleaved
└── checkpoints/            ← Named snapshots, no user namespace
```

**`SessionManager.js`** reads and writes `active_session.json` directly:
- `startSession()` → overwrites `active_session.json`
- `recordStep()` → mutates `active_session.json`
- `completeSession()` → deletes `active_session.json`, appends to `history.jsonl`
- `getSession()` → reads `active_session.json`

### Why This Is a Problem

1. **Single-user bottleneck**: Only one active session can exist at a time. If User A starts a session, User B's `start_sdd_session` call silently overwrites User A's in-progress session.

2. **No user identity**: The session model has no concept of _who_ started the session. The `sessionId` is a timestamp-based random string with no user association.

3. **File-based state doesn't scale**: The MCP gateway serves multiple users via Docker containers. Each container mounts `sdd_framework/` as a shared volume. Concurrent writes to `active_session.json` create race conditions.

4. **History is ungrouped**: `history.jsonl` interleaves events from all users with no `user` field, making audit trails per-user impossible.

5. **Container restarts lose context**: If the gateway container recycles (which happens on the `--long-lived` timeout), in-memory session state is lost. The file persists but the SessionManager re-reads it without validation.

6. **Develop branch coupling**: The current design assumes a single developer working off the `develop` branch. Multiple users on feature branches need isolated session namespaces.

### Scope Distinction from Phase 4D

Phase 4D ("Multi-Tenant SDD Workspaces") addresses the broader architecture: per-team workflow repositories, RBAC, workspace isolation, approval chains. **This phase (33) is narrower and more immediate** — it replaces the file-based session storage with a database-backed store keyed by user identity, without requiring the full multi-tenant workspace architecture.

Phase 33 is a prerequisite _enabler_ for Phase 4D. The session state database created here becomes the foundation that Phase 4D builds tenant isolation on top of.

---

## Proposed Solution

### Storage Backend: Neo4j (preferred) or SQLite

**Option A — Neo4j** (recommended, already deployed):
- SDD sessions become `(:SDDSession)` nodes with user/phase/status properties
- Steps become `(:SDDStep)` nodes linked via `[:HAS_STEP]` relationships
- Checkpoints stored as `(:SDDCheckpoint)` nodes with serialized state
- User identity from MCP transport headers or environment variable
- Natural fit: sessions can link to `(:File)` and `(:ShellScript)` nodes via `[:MODIFIES]` edges, unifying session tracking with the code graph

**Option B — SQLite** (simpler, no external dependency):
- Embedded SQLite database in `sdd_framework/execution_state/sessions.db`
- Tables: `sessions`, `steps`, `checkpoints`, `history`
- User identity column on all tables
- File-level locking handles concurrent access adequately for <10 users

### User Identity Resolution

Priority order:
1. `X-MCP-User` header (set by gateway proxy or MCP client)
2. `MCP_USER` environment variable (set in container or shell)
3. `os.userInfo().username` (fallback for local stdio mode)
4. `anonymous` (final fallback)

### Interface Changes

`SessionManager` API remains the same — callers don't change:
- `startSession(phase, options)` → now includes `userId` internally
- `getSession()` → returns only the calling user's active session
- `recordStep(...)` → scoped to calling user's session
- `completeSession(...)` → only completes the calling user's session
- `getHistory(...)` → filterable by user

New optional parameter on tools:
- `get_sdd_session({ user })` — admin view of another user's session
- `get_sdd_execution_history({ user })` — filter history by user

---

## Acceptance Criteria

1. Two users can have concurrent active SDD sessions without interference
2. `get_sdd_session()` returns only the calling user's session
3. `history.jsonl` (or DB equivalent) includes a `user` field on every event
4. Session state survives container restart without corruption
5. Backward compatibility: existing `active_session.json` migrated on first startup
6. `get_sdd_framework_status()` shows per-user session counts
7. No regression in session lifecycle: start → record → complete flow unchanged

---

## Migration Path

1. On first startup with new SessionManager, check for `active_session.json`
2. If present, import it as a session for the current user and delete the file
3. Import `history.jsonl` entries (assign `user: "legacy"` where unknown)
4. Continue writing to DB; stop writing flat files
5. Keep `history.jsonl` as a read-only archive for pre-Phase 33 audit trail

---

## Out of Scope (deferred to Phase 4D)

- Per-team workflow repositories
- Role-based access control (RBAC)
- Workflow approval chains across teams
- Workspace isolation and quotas
- Branch-aware session namespacing (e.g., session per user per branch)
