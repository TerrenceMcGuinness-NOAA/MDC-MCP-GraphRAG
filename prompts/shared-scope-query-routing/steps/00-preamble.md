# Context

Repo:   /mdc-mcp-rag/eib-mcp-rag-server
Branch: update_shared_scoping  (verify with `git branch --show-current`; stop if it differs)
Spec:   .kiro/specs/shared-scope-query-routing/

Read requirements.md, design.md, and tasks.md in full before writing any code.
tasks.md is authoritative for WHAT to build; design.md explains WHY and records
the trade-offs already settled. Do not relitigate a settled decision.

You are ONE step in a sequential series. No other agent is running. The steps
before you have already landed; the steps after you have not started.

# Toolchain

- **The interpreter is `python3.12`, NOT `python3`.** Bare `python3` here is
  3.9.25 with a stale partial dependency set: no pytest-asyncio, no pytest-cov,
  older hypothesis, and a chromadb missing `chromadb.errors`. Because
  `pyproject.toml` sets `--strict-markers`, the absent pytest-asyncio makes every
  `@pytest.mark.asyncio` an unregistered marker and you get 31 collection errors.
  Under `python3.12` the suite collects 1505 tests with zero errors. If you see
  asyncio marker errors, you used the wrong interpreter.
- Tests:  `cd mcp_server_python && python3.12 -m pytest <target> -q`
- Style:  `pycodestyle <files>`  (2.14.0, on PATH)
- Registered markers: `property`, `parity`, `unit`. Do not invent a new one.
- You have NO AWS credentials and NO MCP tools, by design. Every test must be
  hermetic: stubbed clients, recorded responses, no live OpenSearch, Neptune, or
  Bedrock call. If a task seems to need a live backend, you have misread it.

# Standing constraints

- READ PATH ONLY. Do NOT modify any file under mcp_server_python/scripts/.
  Requirement 12.2 freezes that directory byte-for-byte and a test enforces it.
- Nothing you write may create, delete, or write a Physical_Collection
  (Requirement 12.5). Reads and metadata counts only.
- ASCII-only console and diagnostic output. No emoji, no box-drawing.
- pycodestyle-clean Python, numpy-style docstrings.
- Default `gw` tenant byte-equivalence is the hard constraint. Where a choice
  trades it for a cleaner internal shape, TAKE PRESERVATION and note it in a
  comment.

# Scope discipline

Implement ONLY the step below. Do not start the next one, even if it looks
trivial. If a file your step needs does not exist and a later step owns it, stop
and report rather than creating a stub.

# Definition of done

1. The code and its tests exist as the task specifies.
2. Run your own new tests, then run the FULL unit and property suites:
   `python3.12 -m pytest tests/unit tests/properties -q`
   Because steps are sequential you are the only writer, so a regression
   anywhere is attributable to you.

   **Four tests fail before you start. Do NOT investigate or fix them.**
   None touch this spec's surface. The first three are environment-dependent and
   were confirmed failing by steps 1 and 2 in isolation, with all step-authored
   files removed:

     tests/unit/test_environment.py::test_known_modules_covers_nine_tool_modules
     tests/unit/test_error_analysis.py::test_extract_ci_error_signal_tool
     tests/unit/test_workflow_info_tools.py::test_resolve_workflow_root_default_when_envs_empty
     tests/properties/test_tenancy.py::TestP6WorkflowRootContainment::test_workflow_root_is_contained

   Root cause of the third, as an illustration: `_resolve_workflow_root` returns
   `global-workflow_develop` because that submodule exists on this instance,
   while the test hard-codes `global-workflow`.

   The fourth surfaced during step 5 and is a bug in the **test's assertion**,
   not in the validator. Hypothesis reached `workflow_subdir="a.."`, which
   `_SUBDIR_RE` legitimately accepts, and the test asserts `".." not in
   str(workflow_root)` — a substring check where a path-component check is
   meant. `/mnt/workflow/a..` has parts `('/', 'mnt', 'workflow', 'a..')` and
   resolves to itself, so nothing escapes; `'..' in path.parts` is False. It is
   filed, out of scope here, and lives in the tenancy surface, not scope routing.
   Because Hypothesis searches randomly it may not reproduce on every run —
   treat 3 or 4 failures as equally clean provided the set is a subset of the
   four above.

   So the pass condition is: **0 collection errors, no failure outside those
   four, everything else green.** A 5th failure is yours. Do not expect a fixed
   collected count — it grows as each step lands tests (1544 after step 1,
   1589 after step 2, 1640 after step 5).
3. Run pycodestyle on every file you created or modified.
4. Report: files touched, your tests passed/failed, full-suite passed/failed,
   pycodestyle result, and anything you found that contradicts the spec.
5. Do NOT commit. Do NOT push.
