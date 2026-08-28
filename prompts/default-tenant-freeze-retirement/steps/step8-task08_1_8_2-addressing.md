# Task 8.1 + 8.2 — the check a quality score cannot make

Implement **sub-tasks 8.1 and 8.2 of Task 8 from tasks.md.** Not 8.3 — step 9 owns
that, and it is atomic.

Step 7 retired byte-equality for the three reporting tools. The four query tools are
still byte-frozen. This step builds their replacement; step 9 swaps it in.

## Files you own

- NEW `mcp_server_python/tests/baselines/addressing.py`
- NEW `mcp_server_python/tests/baselines/expected/addressed_sets.json`
- NEW `mcp_server_python/tests/properties/test_addressed_sets.py`

**Nothing you write is called by anything yet.** Byte-equality stays in force for
all four query-tool scenarios through your step. Do not touch
`test_default_tenant_byte_equivalence.py`, `structural.py`, the recorded baselines,
or anything under `src/`.

## Why this cannot be a text parser, unlike step 6

Step 6 could parse the rendered report because the reports name their collections.
Query-tool output does not, and two independent facts make that irrecoverable.

**The rendered collection field carries the logical name, not the physical one.**
`semantic_search` renders `| **Collection:** {name}` from the logical identifier.
Phase 79 deliberately added `physical_collection` as a *new* result key rather than
repurposing that field, precisely so the rendered bytes would not move. So the
physical collection a read addressed is not in the text.

**The capture harness cannot see it either.** `_StubVectorDB` replaces the adapter
wholesale, and it receives the *logical* name — the real adapter is what calls the
router internally. So the recorded scenarios have no view of physical addressing.

That is why this check works against the router directly and against both adapters
through a fixture, and why it is a separate module from `structural.py` rather than
another rule inside it.

## 8.1 — two functions, because they fail for different reasons

### The addressed-set half

```python
def addressed_set(tool_name: str, *, tenant, profile) -> frozenset[str]: ...
```

For a given tool, the set of physical collections it addresses is the union of
`resolve_read_targets(c, tenant, profile=profile)` over the logical collections that
tool reads. Pure: no network, no filesystem, no probe for whether a collection
exists.

**The tool-to-collections mapping is not uniform, and you have to read it rather
than assume it.** Verified shapes:

```
graph_rag.py       CODE_COLLECTION            = "code-with-context-v8-0-0"
                   COMMUNITY_COLLECTION       = "community-summaries"
operational.py     WORKFLOW_DOCS_COLLECTION   = "global-workflow-docs-v8-0-0"
                   JJOBS_COLLECTION           = "jjobs-v8-0-0"
                   CODE_COLLECTION            = "code-with-context-v8-0-0"
semantic_search.py DEFAULT_SEARCH_COLLECTIONS = (a tuple, several)
                   CONTEXT_TYPE_COLLECTIONS   = (a dict of tuples)
```

So some tools read one collection, some read several, and `semantic_search` holds
both a tuple and a dict keyed by context type. Import the constants from the modules
rather than restating the strings — a copy here would silently drift from the code
it claims to describe, which is the failure mode this whole check exists to prevent.

Record the expectations in `expected/addressed_sets.json`, keyed tool name then
profile, values sorted lists. A change that drops a collection from a tool's fan-out
changes the set and fails naming the dropped collection.

**This is the check a quality score structurally cannot make.** Drop one member of a
two-member set and the benchmark's coverage may not move at all — the surviving
collection still answers the corpus queries — while the tool now sees half of what it
should. That asymmetry is exactly why the requirements make this check *additional*
to the benchmark rather than a substitute, and why passing the benchmark while
failing this counts as failing the gate.

### The provenance half

Every hit a read returns must carry a non-empty `physical_collection` whose value is
a member of the addressed set.

This needs hits from a real adapter, so use the existing `adapters()` fixture in
`tests/properties/conftest.py`. It parameterises a `ChromaDBAdapter` and an
`OpenSearchAdapter` over recorded client doubles, with explicit embedding functions
so neither Bedrock nor sentence-transformers is needed. **Both must be swept** —
provenance asserted on one backend and broken on the other is the shape of bug this
would otherwise miss.

Verified that the stamping exists on both paths: `opensearch_adapter.py` sets
`row["physical_collection"] = physical` in the single-member identity path and again
in the merge path. So there is something real to assert against, not an aspiration.

Keep the two halves as separate functions. They fail for different reasons and a
reviewer needs to know which — "you dropped a collection" and "a hit lost its
provenance" call for different investigations.

## 8.2 — Property 13

New `tests/properties/test_addressed_sets.py`, marker `property`, `deadline=None`,
at least 100 examples, tagged
`# Feature: default-tenant-freeze-retirement, Property 13: <title>`.

For any query tool and any embedding profile: the addressed set equals the recorded
expectation, and computing it issues no network request, no filesystem read, and no
existence probe. For any hit returned by either adapter: it carries a non-empty
`physical_collection` that is a member of the addressed set.

Assert the purity clause structurally — exercise the function with socket and
filesystem access replaced by raising doubles — rather than by reading the source.
That is the technique step 4 used for the harness and Phase 79 used for the router.

## Two things to get right

**Use the default tenant for the addressed-set expectations.** This check replaces
byte-equality for the *default-tenant* query-tool responses, so that is the tenant
whose sets need pinning. Nothing stops you covering a prefixed tenant as well and it
is cheap signal, but the default is the one the gate is about.

**Sweep the profiles that resolve.** `titan1024` and `mpnet768` both map to real
physical names. A third profile exists that maps to nothing and passes the logical
name through unchanged — if you include it, expect passthrough rather than an
`mdc-`-shaped name, and do not treat that as a defect.

## Suite state

**1873 passed, 4 failed, 0 skipped.** Your work adds tests and changes no existing
behaviour, so nothing should move. A fifth failure is yours.

_Requirements: 11.2, 11.6_
