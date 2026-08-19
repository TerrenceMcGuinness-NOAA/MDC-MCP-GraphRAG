# Phase 80: Retiring the Default-Tenant Byte-Equivalence Freeze

**Status**: DESIGN
**Created**: 2026-08-19
**Session**: phase80_default_tenant_freeze_retirement
**Severity**: MEDIUM — three improvements blocked; one of them preserves a
number that is known to be wrong

## Problem Statement

`shared-scope-query-routing` (Phase 79) froze default-tenant output byte-for-byte
in Requirement 6. Two criteria carry it:

- **R6.2** — every query tool run without a `tenant_id` returns a rendered
  response byte-equivalent to the pre-change response, for the same query text,
  result limit, Backend, Embedding_Profile, and store content.
- **R6.3** — the Status_Reporter, Integrity_Checker, and Health_Reporter run
  without a `tenant_id` render byte-equivalent responses, "listing the same
  Physical_Collections with the same document counts, **in preference to** the
  scope-labelling and totalling behaviour that Requirements 9, 10, and 11
  require."

That "in preference to" is the operative phrase. R6.3 does not merely permit
preservation over improvement; it *ranks* it. Three follow-ups are now blocked
behind it, and in one case the frozen behaviour is a defect.

This phase retires the freeze as a **standing rule** while keeping it available
as a **tool**.

## The freeze was the right call, and that is not in question

Recorded so it does not get relitigated as a mistake:

Phase 79 changed the query path for every tool in the server — 1,635 insertions
across 14 files in the atomic commit alone. Byte-equivalence gave a reviewer who
could not read all of it a yes-or-no answer to "did you break the production
default path", backed by 28 tests and a one-shot capture. It cost little, it
held through nine steps, and it was never spent defensively.

**Conclusion to carry forward: byte-equivalence is a good instrument for a
high-surface refactor and a bad permanent fixture.** Retiring it here is not a
judgement that using it was wrong.

## What the freeze now costs

Measured, not hypothetical:

1. **Three follow-ups blocked**: score fusion across the merge layers, dropping
   `mdc-content-sha-registry` from the `gw` status total, and scoping the
   Default_Tenant integrity sampler.
2. **R6.3 preserves a known-wrong number.** `mdc-content-sha-registry` is a
   bookkeeping index. It inflates the `gw` status total today, Phase 79's 10.1
   deliberately left it in, and byte-equivalence is the only reason.
3. **`gw` integrity findings remain unscoped.** The sampler still calls
   `sample_metadata(collection=None)` for the default tenant, so findings
   describe a mixture across every tenant's data. Phase 79 had to narrow
   Property 8 and amend R10.5 to record this.
4. **Baseline serialization.** R6.5 pins the comparison to "a response capture
   recorded from the revision immediately preceding this change." Captures are
   revision-pinned — Phase 79's lives at `4eb4229` and could not be re-recorded
   once rendering paths moved. So the three follow-ups cannot proceed in
   parallel: whichever lands first invalidates the others' reference point.
5. **It has already distorted implementation.** Phase 79 step 10 had to preserve
   every line at or above 894 of `semantic_search.py` byte-for-byte, and use
   integer ceil-division rather than a top-level `import math`, purely to keep a
   pinned-line test's indices stable. That test has since been repaired, but the
   constraint was real and the cost was paid.

## The split: R6.3 and R6.2 freeze different things at different risk

The single most important decision in this phase is to stop treating these as
one rule.

| | **R6.3 — reporting** | **R6.2 — query results** |
|---|---|---|
| Freezes | status, integrity, health diagnostics | tool responses: content and ordering |
| A change alters | wording and layout of a human-facing report | which hits a user sees at a given `k` |
| Current frozen state | preserving a known-wrong count | correct |
| Right gate | structural equivalence | benchmark comparison |
| Unblocks | registry over-count, sampler scoping | score fusion |
| Risk if wrong | a confusing report | wrong answers, silently |

Collapsing these is what makes the freeze look either indispensable or absurd
depending on which one you have in mind. Separated, each has an obvious
proportionate gate.

## Proposed resolution

### Step 1 — wire the post-check first

**This step must land before either relaxation.** See Caveat 1.

The instrument already exists and is stronger than a bespoke check would be.
`mcp_server_python/scripts/run_benchmark_nightly.sh` (Phase 71) runs the RAG
benchmark, normalises each run into `quality_metrics.jsonl`, and **emits a
fail-loud structured ERROR when any category's score drops more than a threshold
below its trailing N-day median.** `get_quality_metrics(compare=true)` reads it
and reports regression against the prior snapshot.

Work here is to make that harness the named acceptance evidence for a
default-tenant output change: confirm it covers the `gw` default path for each
affected tool category, record the pre-change snapshot as the reference, and
document the threshold that constitutes a regression.

### Step 2 — relax R6.3 to structural equivalence

Replace byte-equivalence for the three reporters with **structural
equivalence**, defined precisely (see Caveat 2):

- the same set of Physical_Collections is listed,
- each carries the same document count,
- each check reports the same pass/fail/skip verdict.

Free to change: wording, line order, labels, spacing, added annotations.

Unblocks the registry over-count and the Default_Tenant sampler scoping, and
lets Phase 79's amended R10.5 and Property 8 be restored to their original
"for any tenant" form.

### Step 3 — replace R6.2's byte gate with a benchmark gate

For query tool responses, byte-equivalence is the wrong instrument but nothing
is not the right one. Substitute:

- a **structural** check that the same collections are addressed and no hit
  loses its `physical_collection` provenance (catches "you dropped a
  collection", which a quality score cannot), **plus**
- a **benchmark** comparison showing no category regression beyond threshold
  (catches "you made retrieval worse", which byte-equivalence never could).

This is strictly better evidence than the frozen capture provided, because it
measures the property that actually matters instead of string identity.

Unblocks score fusion.

## Caveats

These are the conditions under which this path is safe. Each is a real failure
mode, not a formality.

1. **Relaxing before the post-check runs leaves no gate at all, and that window
   is open today.** The AgentCore deploy is operator-gated and all three
   live-invocation entries in Phase 79's Verification_Record are BLOCKED — no
   AWS credentials in the implementation environment by design. So "test in
   post" currently evaluates to "do not test." Step 1 is a hard prerequisite,
   not a courtesy.

2. **"Structural equivalence" must be defined in the spec, or it degrades to
   "anything goes."** The three bullets in Step 2 are the definition and belong
   in an acceptance criterion, not in prose. A reviewer must be able to fail a
   change against them.

3. **The benchmark measures quality, not correctness.** A category score can
   stay flat while a collection silently drops out of the fan-out, because the
   remaining collections still answer the benchmark queries. This is why Step 3
   keeps a structural check alongside the benchmark rather than replacing one
   with the other.

4. **Rendered output may have parsers.** MCP responses are consumed by Kiro
   sessions, CI pipelines, and Tier B/C agent wrappers. Before relaxing
   formatting, audit for consumers that pattern-match on response text — the
   `**Collection:**` field in `semantic_search.py` is the known example, and
   Phase 79 deliberately added `physical_collection` as a new key rather than
   repurposing `collection` for exactly this reason. An unaudited formatting
   change is a silent break for anything downstream.

5. **Baselines are revision-pinned and die on first use.** Once `gw` output
   moves, every capture recorded before it is void as a reference. The spec must
   name the new reference revision explicitly and re-capture, rather than
   leaving the next author to discover the old one is stale.

6. **Retire the rule, keep the mechanism.** `tests/baselines/`, `capture.py`,
   the recorded backend responses, and the earned-mask machinery all stay. The
   next high-surface refactor should reach for them. Deleting them because this
   freeze was costly would discard the thing that made Phase 79 safe.

7. **Order the three follow-ups deliberately.** Because of Caveat 5 they
   serialize. Recommended order: registry over-count first (smallest, R6.3
   only, immediately visible as a correctness fix), then sampler scoping (R6.3,
   restores Property 8), then score fusion last (R6.2, largest, needs the
   benchmark gate proven by the two before it).

## Path to resolution — checkable exit criteria

1. `run_benchmark_nightly.sh` confirmed to cover the `gw` default path for every
   affected tool category, with the covering categories named.
2. A pre-change benchmark snapshot recorded and cited as the reference, with the
   regression threshold stated as a number.
3. Consumer audit complete: every parser of rendered response text identified,
   or the absence of any recorded as a finding.
4. R6.3 superseded by a structural-equivalence criterion carrying the three
   bullets from Step 2 verbatim.
5. R6.2 superseded by a paired structural-plus-benchmark criterion.
6. Phase 79's `requirements.md` R10.5 and `design.md` Property 8 restored to
   their unrestricted form, with the amendment notes updated to point here.
7. `tests/baselines/` retained, with its README stating it is a tool for
   high-surface refactors rather than a standing gate.
8. The three follow-ups sequenced per Caveat 7, each citing this phase as the
   authority for changing `gw` output.

## Affected files

| File | Change |
|---|---|
| `.kiro/specs/shared-scope-query-routing/requirements.md` | supersede R6.2, R6.3; restore R10.5 |
| `.kiro/specs/shared-scope-query-routing/design.md` | restore Property 8; record supersession |
| `mcp_server_python/tests/unit/test_default_tenant_byte_equivalence.py` | re-express as structural |
| `mcp_server_python/tests/baselines/README.md` | state tool-not-rule status |
| `mcp_server_python/scripts/run_benchmark_nightly.sh` | confirm `gw` category coverage; no change expected |

## Dependencies

- Phase 71 (`nightly-rag-benchmark-harness`) — supplies the post-check. Must be
  running and producing `quality_metrics.jsonl` entries before Step 2.
- Phase 79 (`shared-scope-query-routing`) — must be deployed and its three live
  Verification_Record entries filled, so the freeze is retired against a known-
  good deployed state rather than an unverified one.

## Notes

- This phase changes no runtime behaviour by itself. It changes which evidence
  is required to change runtime behaviour.
- The `DEFAULT_SEMANTIC_COLLECTION` profile pinning
  (`"mdc-code-context-mpnet768"`, a physical name that bypasses profile
  resolution) is the fourth Phase 79 follow-up and is **not** blocked by the
  freeze. It is independent and can proceed at any time.
- Phase 79's configuration-level rollback remains available throughout and needs
  no code change or redeploy: setting `MCP_COLLECTION_SCOPE_JSON` to a document
  classifying all five collections as `tenant` with an empty `hybrid_domains`
  reproduces pre-change routing exactly.
