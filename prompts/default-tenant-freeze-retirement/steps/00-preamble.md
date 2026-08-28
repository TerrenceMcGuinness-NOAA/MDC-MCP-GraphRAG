# Context

Repo:   /mdc-mcp-rag/eib-mcp-rag-server
Branch: verify with `git branch --show-current`; the runner enforces $DTFR_BRANCH
Spec:   .kiro/specs/default-tenant-freeze-retirement/
Record: sdd_framework/workflows/phase80_default_tenant_freeze_retirement.md

Read requirements.md, design.md, and tasks.md in full before writing any code.
tasks.md is authoritative for WHAT to build; design.md explains WHY and records
the trade-offs already settled. The phase doc is the point of record for the
reasoning and its eight caveats. Do not relitigate a settled decision.

You are ONE step in a sequential series. No other agent is running. The steps
before you have already landed; the steps after you have not started.

# What this feature is, in three sentences

Phase 79 froze default-tenant (`gw`) output byte-for-byte. That freeze was
correct for a 1,635-insertion read-path refactor, but it now blocks three
improvements and one of them is preserving a document total known to be wrong.
This feature builds the replacement gate first, then retires the freeze as a
standing rule while keeping the capture machinery as a tool.

# Toolchain

- **The interpreter is `python3.12`, NOT `python3`.** Bare `python3` here is
  3.9.25 with a stale partial dependency set: no pytest-asyncio, no pytest-cov,
  older hypothesis, and a chromadb missing `chromadb.errors`. Because
  `pyproject.toml` sets `--strict-markers`, the absent pytest-asyncio makes every
  `@pytest.mark.asyncio` an unregistered marker and you get ~31 collection
  errors. If you see asyncio marker errors, you used the wrong interpreter.
- Tests:  `cd mcp_server_python && python3.12 -m pytest <target> -q`
- Style:  `pycodestyle <files>`
- Registered markers: `property`, `parity`, `unit`. **Do not invent a new one**
  and do not register one. This feature adds no marker (R15.5).
- You have NO AWS credentials and NO MCP tools, by design. Every test must be
  hermetic: injected facades, recorded responses, no live OpenSearch, Neptune,
  ChromaDB, Neo4j, or Bedrock call. If a task seems to need a live backend, you
  have misread it — check the "What cannot be completed in this environment"
  section of tasks.md.

# Standing constraints

- **NOTHING under `mcp_server_python/src/` changes.** This is stronger than R15.3
  asks for and it is the cheapest reviewer check available:
  `git diff --stat mcp_server_python/src/` must return empty. If you find
  yourself editing a file under `src/`, stop and report — you have misread the
  task.
- ASCII-only console and diagnostic output (R1.10). No emoji, no box-drawing.
- pycodestyle-clean Python, numpy-style docstrings.
- Do not modify `mcp_server_python/tests/baselines/pre_change/*` or
  `recorded_backend/*`. Those are Phase 79's one-shot captures from revision
  `4eb422915bdf2728466e6ff5df449b7a539cdede` and cannot be re-recorded.
- Where a choice trades a settled invariant for a cleaner internal shape, TAKE
  PRESERVATION and note it in a comment.

# Scope discipline

Implement ONLY the step below. Do not start the next one, even if it looks
trivial. If a file your step needs does not exist and a later step owns it, stop
and report rather than creating a stub.

**Two sub-tasks in this plan are ATOMIC and are called out in their own steps:
6.3 and 8.3.** Each bundles a freeze supersession with its replacement check
because R8.2/R8.3 forbid any revision in which a criterion is relaxed and its
replacement is absent. If your step is one of those, land every bullet together
or land nothing.

# Definition of done

1. The code and its tests exist as the task specifies.
2. Run your own new tests, then run the FULL unit and property suites:
   `python3.12 -m pytest tests/unit tests/properties -q`
   Because steps are sequential you are the only writer, so a regression
   anywhere is attributable to you.

   **Four tests fail before you start. Do NOT investigate or fix them.**
   None touches this feature's surface:

     tests/unit/test_environment.py::test_known_modules_covers_nine_tool_modules
     tests/unit/test_error_analysis.py::test_extract_ci_error_signal_tool
     tests/unit/test_workflow_info_tools.py::test_resolve_workflow_root_default_when_envs_empty
     tests/properties/test_tenancy.py::TestP6WorkflowRootContainment::test_workflow_root_is_contained

   The fourth is a bug in the *test's assertion*, not the validator: Hypothesis
   reaches `workflow_subdir="a.."`, which `_SUBDIR_RE` legitimately accepts, and
   the test asserts `".." not in str(workflow_root)` — a substring check where a
   path-component check is meant. `/mnt/workflow/a..` resolves to itself and
   `'..' in path.parts` is False. Filed, out of scope. Because Hypothesis
   searches randomly it may not reproduce every run; treat 3 or 4 failures as
   equally clean provided the set is a subset of those four.

   **The pass condition is: 0 collection errors, no failure outside those four,
   ZERO skips, everything else green.** Baseline at the start of this feature is
   **1784 passed, 4 failed, 0 skipped**. A fifth failure is yours, and so is a
   skip — the suite currently has none and R15.5's meta-test forbids adding a
   conditionally-skipped test. Do not expect a fixed collected count; it grows as
   each step lands tests.

   **One exception, and only for the step that owns it:** the design's Testing
   Strategy describes a transitional state around task 6.3. If you are that step,
   read that section before concluding a fifth failure is a defect.
3. Run pycodestyle on every file you created or modified.
4. Confirm `git diff --stat mcp_server_python/src/` is empty.
5. Report: files touched, your tests passed/failed, full-suite passed/failed,
   skip count, pycodestyle result, the `src/` diff check, and anything you found
   that contradicts the spec. **Report contradictions rather than working around
   them silently** — three of this spec's four most valuable findings came from a
   step questioning a premise it had been handed.
6. Do NOT commit. Do NOT push.
