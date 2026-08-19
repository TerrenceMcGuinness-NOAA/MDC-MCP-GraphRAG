# Default-tenant byte-equivalence baselines

shared-scope-query-routing Task 6. These captures record the rendered
output of the tool layer on the revision **immediately preceding** the
read-path routing change, so that Requirement 6.5 (default-tenant
byte-equivalence) is verifiable against a valid parent revision.

## Provenance

- Branch: `update_shared_scoping`
- Parent revision (captured against): `4eb422915bdf2728466e6ff5df449b7a539cdede`
- Interpreter: `python3.12`

This is the revision before Task 7.3 re-points either adapter's `query()`
at the Read_Router. Only Task 2.4 (test generators, no production code)
had landed ahead of Task 6. Once the routing change lands there is no
valid pre-change baseline and R6.5 becomes permanently unverifiable, so
these files are one-shot and irreplaceable — do not regenerate them from a
tree that already routes through `src/data/read_router.py`.

## Why this lives under `tests/`, not `scripts/`

Requirement 12.2 freezes `mcp_server_python/scripts/` byte-for-byte and a
test enforces it. A capture harness placed there would violate the very
requirement it exists to help verify. Everything for this task lives under
`tests/baselines/`.

## Layout

```
tests/baselines/
  capture.py                      # the harness (Task 6.1) + mask helpers (6.2)
  recorded_backend/<id>.json      # frozen adapter responses + frozen inputs
  pre_change/<id>.md              # run A: the canonical baseline (Task 6.2)
  pre_change/<id>.b.md            # run B: volatility evidence for the mask check
  pre_change/<id>.masks.json      # the earned masks (empty when deterministic)
  README.md                       # this file
```

`tests/unit/test_default_tenant_byte_equivalence.py` (Task 6.3) is the
regression suite that compares the post-change rendering against
`pre_change/<id>.md`, applying only the masks in `pre_change/<id>.masks.json`.

## How a scenario is rendered (hermetic by construction)

Each `recorded_backend/<id>.json` freezes one scenario. The harness builds
a stub data-access facade whose vector and graph adapters **replay the
recorded response** rather than hitting a live backend, registers the
owning tool module on a fresh `FastMCP` server with that stub injected,
and invokes the frozen tool with the frozen argument set. No OpenSearch,
Neptune, or Bedrock call is made. Because store content is frozen by the
recording, the comparison isolates *rendering* from *data drift*, and the
same recorded responses feed both the pre-change and the post-change run
(Requirement 13.3).

### Frozen inputs per scenario

Every input that steers rendering is frozen in the scenario file and, for
the environment inputs, pinned by the harness:

- `tool` — the tool name.
- `args` — query text, `max_results`, and **every other tool argument**.
  No `tenant_id` is ever set, so resolution lands on the default `gw`
  tenant (Requirement 6.2 / 6.3 compare the default-tenant response).
- `env.DB_BACKEND` — selects the backend label (`OpenSearch`/`Neptune` vs
  `ChromaDB`/`Neo4j`).
- `env.MCP_EMBEDDING_PROFILE` — selects the physical-name map.
- `PYTEST_CURRENT_TEST` — pinned by the harness. `graph_rag`'s
  `search_architecture` and `get_change_impact` branch on `"pytest" in
  sys.modules or PYTEST_CURRENT_TEST`, an in-tree testing affordance. The
  pin guarantees the command-line capture and the pytest-hosted regression
  test take the same branch; without it the baseline and the test-time
  render would diverge for `search_architecture`.
- `SDD_STATE_DIR` — redirected to a scratch directory so no scenario writes
  into the repo tree.

### Scenarios

| id | module | tool | R6.3 |
|----|--------|------|------|
| `search_documentation` | semantic_search | search_documentation | |
| `search_ee2_standards` | ee2_compliance | search_ee2_standards | |
| `search_architecture` | graph_rag | search_architecture | |
| `get_operational_guidance` | operational | get_operational_guidance | |
| `get_knowledge_base_status` | semantic_search | get_knowledge_base_status | yes |
| `check_knowledge_integrity` | semantic_search | check_knowledge_integrity | yes |
| `mcp_health_check` | utility | mcp_health_check | yes |

Requirement 13.3 asks for at least one tool from each of
`semantic_search`, `ee2_compliance`, `graph_rag`, and `operational`;
Requirement 6.3 adds the no-`tenant_id` responses of the status,
integrity, and health reporters. All seven are present.

## Attribution header

The baseline retains the `*Tenant: gw*` / `*Branch: develop*` attribution
header, because Requirement 6.2 requires byte-equivalence *including* the
attribution header lines. The harness reuses
`tests/parity/parity_runner.py::strip_tenant_header` for header-aware
handling to stay consistent with the tenancy parity suite, but only for a
diagnostic header/body split — never to remove the header from the
authoritative comparison. (Note: that utility's regex predates the
`*Branch:*` line and therefore does not strip the current two-line header;
this is harmless here because the header is retained in the comparison
regardless.)

## Volatility masks (Task 6.2)

The harness renders each scenario **twice** over identical inputs and
diffs the two outputs at character granularity (`derive_masks`). Any span
that differs between two runs of the same code is volatile and is recorded
as a mask; a generated timestamp is the archetypal instance. The diff is
computed per-character so a mask covers only the volatile substring, never
a whole line when a single token varies.

A mask must be **earned**: `verify_masks_earned` re-derives the mask set
from the two recorded runs and rejects any committed mask that does not
trace back to a demonstrated double-run difference (and any mask whose two
spans are textually identical). The regression suite enforces this, and a
hand-added or over-broad mask fails it. This matters because the mask
mechanism is exactly what a future engineer would otherwise reach for to
make a real regression disappear.

**All seven scenarios are deterministic under the frozen, hermetic inputs,
so every `masks.json` is empty (`[]`) and the byte-equivalence comparison
is exact.** The recorded, clock-dependent, and store-derived fields that
are volatile against a live backend (ingestion timestamps, latency
figures) are frozen or absent here by construction, so no volatile span is
produced. The mask machinery is still enforced end-to-end: the regression
suite includes a genuine volatile-span case proving an earned substring
mask is accepted, tolerates a change only inside the masked span, and
rejects a change outside it, alongside the hand-added and over-broad mask
rejections.

## Regenerating

Only valid from the parent revision above. From `mcp_server_python/`:

```bash
python3.12 -m tests.baselines.capture
```

This rewrites every `pre_change/<id>.md`, `pre_change/<id>.b.md`, and
`pre_change/<id>.masks.json`. To add a scenario, add a
`recorded_backend/<id>.json` following the schema of an existing file and
re-run the capture.
