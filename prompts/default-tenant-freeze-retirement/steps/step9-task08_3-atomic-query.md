# Task 8.3 — ATOMIC: take the query-result freeze off

Implement **sub-task 8.3 of Task 8 from tasks.md.** That is the whole step.

Step 8 built the addressed-set and provenance check. Nothing calls it. This step
makes it the gate for the four query tools, alongside the benchmark comparison, and
retires byte-equality for them.

## Read this first

**This is ONE change, and it needs BOTH replacements present, not one.**

Step 7 was atomic because a supersession without its replacement leaves a gate
missing. This step is stricter: the requirement names **two** replacements and makes
them jointly necessary. Land the supersession with only the structural check, or only
the benchmark criterion, and the tree passes through a state where the requirement
claims a gate that is half absent.

The two are not interchangeable and that is the point of pairing them:

- The **structural check** catches a dropped collection. A quality score cannot —
  remove one member of a two-member set and the surviving collection still answers
  the corpus queries, so coverage may not move while the tool sees half of what it
  should.
- The **benchmark comparison** catches degraded retrieval. A structural check
  cannot — the right collections can be addressed and still return worse hits.

So: all edits together, or revert and report.

## Files you own

- MODIFY `mcp_server_python/tests/unit/test_default_tenant_byte_equivalence.py`
- MODIFY `.kiro/specs/shared-scope-query-routing/requirements.md`

Do not touch `addressing.py` or `structural.py` — steps 6 and 8 finished them. Do not
touch the recorded baselines, the masks, or anything under `src/`.

## What changes in the test module

`test_query_tools_byte_equivalence` at line 174 is the target. It parameterises over
`_QUERY_SCENARIO_IDS` and compares with `capture.matches_baseline`.

Replace that comparison. For each query-tool scenario, assert instead that the set of
physical collections addressed under the default tenant is unchanged, and that every
returned hit carries a non-empty `physical_collection`. Use step 8's module —
`addressed_set` and `check_hit_provenance`.

**Note the name: `check_hit_provenance`, not `assert_hit_provenance`.** It returns a
list of findings and does not raise. A bare call whose result you discard is a silent
no-op. It was renamed for exactly that reason, after the name misled someone
reviewing it.

Leave the three reporting scenarios alone — step 7 already moved them.

**What must survive:** the earned-mask tests, the attribution-header test, the
coverage guard, and the partition guard. The masks now govern no scenario's
comparison, but the earned-mask machinery is retained deliberately as an instrument
for a future high-surface refactor, and step 7's README records that. Retiring the
last use is not a reason to delete it.

## What changes in the Phase 79 spec

Requirement 6 criterion 2 is the target. It currently requires a "complete rendered
response byte-equivalent to the response that tool returns before this change ...
including the tenant attribution header lines."

Record it as superseded, name this feature as the authority, and require **both**
replacements:

- **Structural:** a query tool invoked without a tenant addresses the same set of
  physical collections as before the change, and every returned hit carries a
  non-empty `physical_collection`.
- **Benchmark:** no gated metric of any category, and none of the overall figures,
  drops below its trailing-window median by more than the governing threshold.

Then state two things the criterion needs in its own text, because they are what stop
the pair collapsing back into one:

- The benchmark comparison measures **retrieval quality, not correctness**, and the
  structural check is required **in addition to** it rather than instead of it.
- A change that **passes the benchmark and fails the structural check is failing the
  gate.** Without that sentence someone will read two checks as two chances to pass.

## One consequence to state plainly rather than let someone find later

Byte-equality gated the rendered bytes of query-tool output. Neither replacement
does. The structural half looks at which collections were addressed and whether hits
carry provenance; the benchmark half looks at retrieval quality. **A pure formatting
change to query-tool output — relabelling a field, changing a separator, reordering
hit metadata — now passes both.**

That is a real reduction in what is gated, and it is deliberate: the requirements
define the structural half as addressed-set plus provenance, not a text comparison,
because the physical collection a read addressed is not recoverable from the rendered
text at all.

It is also why the consumer audit matters more than it looks. If something downstream
parses query-tool output, a formatting change now reaches it ungated. The audit that
identifies those consumers is the thing that makes this tolerable, and it lands in
step 10.

Do not try to fix this by keeping a byte comparison alongside — that would reinstate
the freeze this step exists to retire. Record it and move on. Note it in your report
so it reaches the final record.

## What to expect from the suite

**No new failures.** The suite sits at 1876 passed, 4 failed, 0 skipped.

As in step 7, you are changing what is asserted about the query-tool scenarios, not
what they render. The addressed sets are unchanged because no routing changed, and
the recorded responses already carry provenance because the adapters stamp it. So the
new assertions pass on the current tree.

A fifth failure is yours.

_Requirements: 8.3, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_
