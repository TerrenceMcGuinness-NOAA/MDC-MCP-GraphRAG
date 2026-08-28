# Task 2 — add tenant-scoped benchmark cases

Implement **Task 2 (sub-tasks 2.1 and 2.2) from tasks.md.**

Step 1 landed the scoring arithmetic and recorded the corpus fingerprint. Your job
is to add cases that run as a non-default tenant, without disturbing the 60 that
already exist.

## Files you own

- MODIFY `mcp_server_node/test/benchmark/ground_truth.json`         (2.1)
- NEW    `mcp_server_python/tests/unit/test_benchmark_corpus.py`    (2.2)

Do not touch `scripts/run_benchmark.py` — steps 3 and 4 own it. Do not touch
`tests/baselines/expected/corpus_categories_digest.json`; step 1 recorded it and
your work is verified against it.

## Why the new cases go in a separate top-level section

Add one sibling key, `tenant_categories`, alongside the existing `categories`.
Same six category names as keys. Move `version` to `1.1.0`.

**Leave `categories` byte-for-byte unchanged.**

The reason is mechanical, not stylistic. The older Node benchmark reads the same
file, and its loader spreads the top-level object then iterates
`Object.entries(raw.categories)` only — so an unfamiliar top-level key passes
through untouched. Putting the new cases inside `categories` instead would do two
things: every category's case count as Node sees it would go from 10 to 11, which
shifts the per-category averages that the shared history is compared against; and
Node would start handing a `tenant_id` argument to handlers that have no concept
of tenants.

## The eight cases

Tenant is `gw_v17` throughout — the only non-default tenant with documented
populated data. Each case carries exactly the eight fields the existing cases use
and no more, with the tenant selection riding inside `tool_args` as
`"tenant_id": "gw_v17"`.

| id | category | tool | what it is for |
|---|---|---|---|
| `cs_t01` | code_structure | `analyze_code_structure` | tenant graph labels resolve |
| `ss_t01` | semantic_search | `search_documentation` | the two-collection docs case |
| `ar_t01` | architecture | `search_architecture` | tripwire, expected to score 0 |
| `ee_t01` | ee2_compliance | `search_ee2_standards` | shared content is reachable |
| `op_t01` | operational | `get_job_details` | tenant job routing |
| `kb_t01` | operational | `get_knowledge_base_status` | status report lists the right collections |
| `ki_t01` | operational | `check_knowledge_integrity` | integrity report runs its checks |
| `cl_t01` | cross_language | `trace_full_execution_chain` | cross-language traversal under a tenant |

Set `expected_min_results` to `len(expected_results)` on each. Neither harness
reads that field — confirmed absent from the Node scorer, aggregator, and
regression detector — so it is there for schema conformance only. Do not build
anything on it.

## The substring trap, which is now concrete rather than theoretical

I resolved what `gw_v17` actually addresses. Six collections:

```
mdc-workflow-docs-titan1024              shared, unprefixed
gw_v17_mdc-workflow-docs-titan1024       shared, prefixed
mdc-ee2-standards-titan1024              shared, unprefixed
mdc-community-summaries-titan1024        shared, unprefixed
gw_v17_mdc-code-context-titan1024        tenant, prefixed
gw_v17_mdc-jjobs-titan1024               tenant, prefixed
```

**Look at the first two. Both are addressed, and the first name is contained
inside the second.** Scoring is case-insensitive substring matching, so an
expectation written as the bare `mdc-workflow-docs-titan1024` would be satisfied
by a report that listed only the prefixed one. If the shared-content fix ever
regressed to prefixing everything, that case would still pass. It would report
green while testing nothing.

Write the expectation with the list marker the report uses, so it reads
`"- mdc-workflow-docs-titan1024"`. That two-character prefix appears before the
name in both status render paths and does not appear before the prefixed name.

**Then prove the anchoring works** — 2.2 must feed in a synthetic report that
contains *only* the prefixed names and assert these expectations do **not** match
it. Without that guard the anchoring can be stripped later and the case quietly
stops discriminating, which is the same failure in a new coat.

## What to expect in a status report versus an integrity report

These two cases are unlike the other six, and the difference is worth
understanding before you write their expected values.

For a search tool, a match means the store returned the right content, so the
score measures retrieval. For these two, the report text is determined by the
tenant and the router before any store is consulted — so the score measures
structure, even though it lands in a field named `coverage`. The design accepts
this rather than pretending it fits, and the practical consequence is that these
two are the only cases in the corpus whose expected values you can work out
offline, without a live backend.

**`kb_t01`** — expect collection names, anchored as above. There are six
addressed collections but cap the list at five. The reason is arithmetic: when the
expected count is at or below the cutoff of 5, the precision denominator becomes
the expected count itself, and precision then equals recall. Recall is not one of
the gated numbers and precision is, so staying at or under five is what puts this
case's signal where the gate can see it. Drop
`mdc-community-summaries-titan1024`, which is redundant with the EE2 collection
for the shared-reachability claim this case is making.

**`ki_t01`** — expect check names. Four are fixed strings in the code:
`Path Consistency`, `Sampled Collections`, `Orphaned Graph Nodes`,
`Stale Embeddings`. There is also a coverage-gap family whose names are built
per-language, so do not hard-code those.

**One thing to verify rather than assume:** `Sampled Collections` comes from the
router-driven sampler that Phase 79 added, and the amended requirement scopes that
work to tenants with a non-empty prefix. So it may render only for a prefixed
tenant. If that is true it is an excellent discriminator for this case. If it
renders for everyone, it is still fine but weaker. Check which, and say what you
found.

## Two cases worth understanding before you write them

**`ee_t01` is the strongest of the eight.** EE2 standards are shared content, so a
correct read reaches the unprefixed collection and returns what the default tenant
gets. The tenant's own EE2 collection exists and is empty. So this case scores near
1.0 when shared-content routing works and 0 if it ever regresses to prefixing
everything — which is precisely the bug the previous phase existed to fix. Choose
expected terms that would actually appear in EE2 standards content.

**`ar_t01` is expected to score 0, and that is deliberate.** The architecture
summaries were never generated for this tenant, so the tool returns a skip notice.
It is included as a tripwire that starts passing when someone generates that data.
Say so in the case's `notes` field, plainly, so a reader does not mistake it for a
miscalibration.

Including a case designed to fail is only safe because the new cases are scored
separately from the original 60. Do not undermine that: step 3 owns the
partitioning, and nothing you write here should assume the two sets are pooled.

## The rest of the expected values need a live run, and you cannot do one

For `cs_t01`, `op_t01`, `cl_t01`, and `ss_t01`'s content terms, draw expected
values from facts recorded in the repository — the gap tracker's verified query
results and label resolutions, the tenant catalog, recorded node counts. That is
the best basis available here and it is not the same as observation. The first real
run against a live backend is a calibration pass, and the final report names every
case that scored 0 so an expected zero can be told apart from a wrong guess.

Say in your report which expected values you inferred rather than verified.

## 2.2 — the verification tests

New `mcp_server_python/tests/unit/test_benchmark_corpus.py`, marker `unit`.

- **The original 60 are untouched.** Compare field-by-field against step 1's
  pinned values, and compare the whole `categories` object against step 1's
  recorded fingerprint. Assert each of the six lists still holds exactly 10 cases
  — that count is the specific guard against a tenant case being filed in the
  wrong place, since it would show up as 11.
- **The new cases are well-formed.** Exactly the eight expected fields, a
  `tenant_id` inside `tool_args`, and that tenant has a non-empty prefix in the
  catalog.
- **Classification agrees with placement** for all 68 cases: the derived
  tenant-scoped flag matches which section the case came from. A misfiled case
  should be caught, not silently reclassified.
- **Coverage.** At least one new case per category. At least one naming
  `get_knowledge_base_status`, at least one naming `check_knowledge_integrity`,
  and at least one whose docs read resolves to more than one collection. **Compute
  that last one through the router** rather than asserting a collection name, so
  the assertion follows the routing logic instead of a string that could go stale.
- **The anchoring guard** described above.

_Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_
