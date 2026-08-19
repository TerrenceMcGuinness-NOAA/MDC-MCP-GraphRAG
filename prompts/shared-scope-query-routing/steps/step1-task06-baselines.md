# Task 6 — baseline captures for default-tenant byte-equivalence

Implement **Task 6 (sub-tasks 6.1, 6.2, 6.3) from tasks.md.**

## This is one-shot and irreplaceable. Read this section twice.

These captures must record the behaviour of the revision *preceding* the routing
change. Once Task 7.3 re-points the adapters at the Read_Router there is no
valid pre-change baseline and Requirement 6.5 becomes permanently unverifiable —
there is no way to recover it later.

You are step 1 of a sequential series, which is deliberate: every later step
that touches a rendering path runs after you, so the tree you capture is a valid
parent revision by construction. Only Task 2.4 (test generators, no production
code) has landed ahead of you. Record `git rev-parse HEAD` into the README so the
baseline's provenance is unambiguous.

If you find the tree already contains `src/data/read_router.py` wired into
either adapter's `query()`, STOP and report — you are too late and a human needs
to decide what to do.

## 6.1 — the harness

Create `mcp_server_python/tests/baselines/` containing `capture.py`,
`recorded_backend/*.json`, and `README.md`.

The harness location is not incidental. It goes under `tests/`, never under
`mcp_server_python/scripts/`: Requirement 12.2 freezes that directory, so a
capture harness placed there would violate the very requirement it exists to
help verify.

Each scenario replays a recorded adapter response through a stub adapter rather
than hitting a live backend. That freezes store content by construction, so the
comparison isolates *rendering* from *data drift*. The same recorded responses
must feed both the pre-change and post-change runs — Requirement 13.3 is
explicit about this.

Freeze per scenario: tool name, query text, max_results, every other tool
argument, DB_BACKEND, MCP_EMBEDDING_PROFILE, and no tenant_id.

Cover at least one tool from each of `src/tools/semantic_search.py`,
`src/tools/ee2_compliance.py`, `src/tools/graph_rag.py`, and
`src/tools/operational.py`, plus the no-tenant_id responses of
get_knowledge_base_status, check_knowledge_integrity, and mcp_health_check
(Requirement 6.3).

Reuse `tests/parity/parity_runner.py::strip_tenant_header` for attribution
header handling so treatment stays consistent with the existing tenancy parity
suite. Note the name has **no leading underscore** — it is public and listed in
that module's `__all__`. Read it before writing your own.

Related prior art you should read before designing the harness:
`tests/parity/test_self_parity.py` already implements a golden-baseline pattern
with a `GOLDEN_DIR` (`tests/parity/golden/`, 8 captures committed), a
`_golden_filename(tool, args)` hashing scheme, and a regeneration entry point.
It is gated behind `MCP_TEST_AGAINST_LIVE=1` and captures from a **live**
backend, which is why it does not satisfy Requirement 6.5 on its own — you need
stub-replayed, hermetic captures. But match its naming and file layout
conventions rather than inventing parallel ones, and reuse `_golden_filename` if
it fits.

## 6.2 — the volatility masks. This is the subtle part.

Write `mcp_server_python/tests/baselines/pre_change/*.md`.

Run the harness against the current revision **twice** over identical inputs and
diff the two outputs. Any span that differs between two runs of the *same* code
is volatile — generated timestamps in the integrity report are the known
instance. Record each such span as a mask.

A mask must be **earned by a demonstrated diff.** Implement a check that every
mask traces back to a recorded double-run difference, and make a hand-added mask
fail that check. This matters because the mask mechanism is exactly what a
future engineer would reach for to make a real regression disappear, and the
check is what stops them.

Do not mask a whole line when only a substring is volatile. An over-broad mask
silently forfeits coverage.

## 6.3 — the regression tests

Create `mcp_server_python/tests/unit/test_default_tenant_byte_equivalence.py`
comparing post-change rendered output against the masked pre-change baseline,
applying only the 6.2 masks.

These pass trivially today. That is intended and is not a reason to weaken them:
they are the guard that Task 7 will be measured against.

_Requirements: 6.2, 6.3, 6.5, 13.3_
