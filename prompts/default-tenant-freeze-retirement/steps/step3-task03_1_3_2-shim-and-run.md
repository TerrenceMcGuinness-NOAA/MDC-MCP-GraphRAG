# Task 3.1 + 3.2 — collect the tool functions, then run the cases

Implement **sub-tasks 3.1 and 3.2 of Task 3 from tasks.md.** Not 3.3 (the command
line), not 3.4/3.5/3.6 (the tests). Those are step 4.

Step 1 built the arithmetic. Step 2 built the case list. This step is the part that
actually calls the tools.

## Files you own

- MODIFY `mcp_server_python/scripts/run_benchmark.py`

That is the only file. No tests in this step — step 4 writes them. If you find
yourself needing a test to know whether something works, run it by hand and say so
in your report rather than adding a test file another step owns.

## What 3.1 does

The tools are not plain functions you can import. Each tool module has a
`register()` function that defines the tool as an inner function and hands it to
the server through a decorator. The function you want is the one the decorator
receives.

So: pass the module a stand-in for the server, let it register normally, and keep
what it hands over. Collect them into a name-to-function map.

Verified signatures — all six take `mcp` first, `data` second, then keyword-only
extras:

```
code_analysis    register(mcp, data=None, *, catalog=None)
ee2_compliance   register(mcp, data=None, *, catalog=None)
operational      register(mcp, data=None, *, catalog=None)
semantic_search  register(mcp, data=None, *, catalog=None, manifest_registry=None,
                          documentation_sources_path=None, repo_base=None)
graph_rag        register(mcp, data=None, *, catalog=None, session_manager=None)
utility          register(mcp, data=None, *, ...)
```

Three details about the stand-in, each observed in the tree rather than guessed:

1. **The decorator is always called with parentheses** in the six modules the
   cases reach, so your `tool` method receives the arguments first and must return
   the actual decorator. Handle the no-parentheses form too — `error_analysis` uses
   `@mcp.tool()` with no arguments today and a future module could drop them
   entirely.
2. **The registered name comes from `name=` when given, otherwise the function's
   own `__name__`.** Both forms exist in the tree.
3. **Return the function unchanged** from your decorator. The module keeps its own
   reference to it, and altering it would change behaviour you are trying to
   observe.

`utility.register` reads the server object for a tool-listing call inside one of
its own functions, not at registration time. Give your stand-in an async
tool-listing method returning an empty list so that degrades cleanly if a case ever
names it.

**Work out which modules to register from the case list**, not from a hardcoded
set: collect the tool names the selected cases use, map each to its owning module,
register only those. Ownership, confirmed by reading the decorator sites:

| module | tools |
|---|---|
| `code_analysis` | `analyze_code_structure`, `find_dependencies`, `find_callers_callees`, `trace_full_execution_chain` |
| `semantic_search` | `search_documentation`, `explain_with_context`, `get_knowledge_base_status`, `check_knowledge_integrity` |
| `graph_rag` | `search_architecture`, `get_code_context`, `trace_data_flow` |
| `ee2_compliance` | `search_ee2_standards` |
| `operational` | `get_operational_guidance`, `list_job_scripts`, `get_job_details` |

If a case names a tool nothing registered, that case records a zero with an error
naming the missing tool, and the run continues. Do not raise.

### The catalog, which will waste your afternoon if you get it wrong

Each tool function closes over `data` and `catalog` at registration time. The
`catalog` is what the tenant machinery resolves a tenant name against.

**Pass `catalog=None` and every tenant-scoped case fails.** Resolution raises, all
eight cases record errors, and the run looks exactly like a tenant routing bug —
eight zeros in the tenant block with plausible-looking error text. You would go
looking in the router.

So build one real catalog and thread it into every tenant-scoped module's
`register()`. The server does the same thing; its list of tenant-scoped modules is
`semantic_search`, `code_analysis`, `graph_rag`, `operational`, `ee2_compliance`,
`workflow_info`. Mirror that.

**A catalog that fails to load is fatal here — exit 1, message naming the
failure.** This is a deliberate difference from the server, which warns and keeps
going. That is right for a server that has to boot; it is wrong for a benchmark,
because a run that silently cannot express a tenant is worse than one that did not
happen.

Give `graph_rag` and `utility` a scratch directory from `tempfile.mkdtemp()` for
their state. Leave out `manifest_registry` for `semantic_search` — the cases do not
reach that path.

## What 3.2 does

`run_benchmark(corpus, *, data=None, catalog=None, category=None, results_dir=None)`.

**Two ways to get the data layer, and the difference has to be structural.** With
`data=None`, build the real one the same way the server does — load the config,
then the backend selector. With `data` supplied, use it and never touch the
builder. That matters because the requirement is that an injected layer issues no
backend traffic at all, and the way to guarantee that is for the code that opens a
socket to never be entered — not for a stub to be faithful enough.

Read no backend-selection environment variable anywhere in this file. Being
backend-agnostic comes from taking no backend argument.

**Call the collected function with the case's arguments as keywords**, tenant name
included. That is the whole point: the tenant machinery binds the tenant, and the
attribution header gets applied, exactly as a real caller's request does. Never
call the inner implementation directly and never invoke the tenant wrapper
yourself. Doing either skips the binding this harness exists to exercise, and the
harness would be blind to the class of bug it was built to catch.

Treat the return value as one piece of text. No unwrapping a content list — these
functions return a plain string.

### Accounting, which is the one thing that must not be wrong

Every selected case produces exactly one entry. A case that could not run records
zeros, a real elapsed time, an error string, and the run continues to the next one.

**The reason is the denominator.** A run that quietly dropped a failing case would
compute every average over a smaller set and report a *better* score for a *worse*
system. That is the one failure a quality gate cannot have.

Catch `Exception`, not `BaseException`, so Ctrl-C still stops a 68-case run. Add a
type check on the return value whose error names what came back instead of a
string — nothing does that today, but a future tool that did would otherwise score
zero with no explanation.

### Keep the two groups of cases separate

The overall figures and the per-category figures come from **default-tenant cases
only.** Tenant-scoped results go in their own two objects alongside.

This is what keeps the per-category numbers comparable with the 21 runs already in
the history, and it is why step 2 could safely include a case designed to score
zero. Pool them and that zero starts dragging down the number that gates unrelated
people's changes.

### The results directory will silently corrupt the history if you share it

The nightly wrapper defaults its results directory to the **Node** harness's
results folder and picks up whichever `*.json` there is newest.

So if this harness writes into that same folder, the wrapper can pick up a stale
Node result and record it in the history as though it were a Python run. Nothing
errors. The number is just wrong, and it stays wrong.

Honour the results-directory variable when it is set, and otherwise default to a
**separate** directory under `mcp_server_python`. Never fall back to the Node one.

Write nothing anywhere else.

### The record

Carry: a timestamp, a harness version, a harness identifier, the corpus version
from the loaded file, the total case count, the four figure objects, the per-case
list with each case's tenant name, and a regression object for shape parity with
the Node record.

Make the harness identifier compound — runtime, script, backend, embedding profile.
The requirement asks for something that identifies the harness; backend and profile
are what a comparison window must never mix, so recording them here is the cheap
way to make a mixed history detectable later.

_Requirements: 1.2, 1.3, 1.4, 1.5, 1.6, 2.7, 2.8, 2.9, 3.1, 3.2, 3.3, 3.5, 3.6, 4.8, 4.9, 4.10_
