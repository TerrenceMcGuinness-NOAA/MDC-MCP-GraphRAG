# Task 1 — Scope_Authority, one component owns collection scope

Implement **Task 1 (sub-tasks 1.1, 1.2, 1.3, 1.4) from tasks.md.**

Creates `mcp_server_python/src/data/collection_scope.py` plus its unit tests.
Independently shippable: it adds no runtime behaviour, only a fail-on-drift guard.

## Files you own

- NEW `mcp_server_python/src/data/collection_scope.py`
- NEW `mcp_server_python/tests/unit/test_collection_scope.py`
- NEW `mcp_server_python/tests/unit/test_collection_scope_consistency.py`

Touch nothing else. In particular do NOT create `src/data/read_router.py` —
Task 2 owns it and another agent may be writing it.

## The three things that are easy to get wrong

**1. `check_scope_consistency` must read the manifest directly with `json.load`,
NOT through `src.manifest.loader.load_manifest`.** Read that loader first and
you will see why: it catches JSONDecodeError, OSError, and ValueError, falls
back to `documentation_sources.json`, and on further failure returns an *empty*
registry so callers can boot degraded. That silent degradation is the exact
failure mode this check exists to catch. Route the check through it and a
corrupt manifest reports zero findings. An unreadable manifest is itself a
finding, never an exception.

**2. The Hybrid_Domain invariant is asserted at import time, not at query time.**
Every member of `_BUILTIN_HYBRID` must classify `shared`. Failing at import means
a future mistake takes the process down at load, where it is obvious, instead of
surfacing as a wrong query result months later.

**3. `scope_of` returns `None` for an unrecognised identifier.** It does not
guess and it does not raise. The Read_Router owns the Requirement 1.5 `tenant`
fallback; this module only reports what it knows. Keeping the fallback out of
here is what lets Requirement 5.6 (unloadable config is a hard error) and
Requirement 1.5 (unknown identifier degrades gracefully) stay separable.

## Sub-task notes

**1.1** — the five classifications are in the task text. Import **stdlib only**,
nothing from this repository. That is Requirement 12.6's condition for this being
a shared module rather than a write-path modification.

**1.2** — the override chain is `MCP_COLLECTION_SCOPE_JSON` (inline JSON
content), then `MCP_COLLECTION_SCOPE_PATH` (a path), then the built-in tables.
An override **replaces both tables wholesale**, never merges, so the active
classification is always readable from one document. Validate schema_version,
every scope value, and every hybrid member. Any violation raises
`ScopeConfigError` naming the failing source. Memoize the content read.

**1.3** — four finding classes, listed in the task text. The drift gate is an
ordinary pytest test (`test_no_scope_drift`), deliberately **not** a boot-time
validation: failing server startup over a manifest classification the built-in
table already answers correctly is the wrong trade-off for a read-mostly aid
over a production forecasting system.

**1.4** — assert the import boundary: no `read_router`, no adapter, no
`src.tools` import. Note in the docstring that the write path is not re-pointed
at this module in this change, because Requirement 12.2 freezes `scripts/`.

_Requirements: 1.1, 1.2, 1.6, 1.7, 1.8, 1.9, 5.6, 5.7, 12.6_
