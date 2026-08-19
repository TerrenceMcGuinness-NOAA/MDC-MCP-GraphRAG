# Task 6.3 + 6.4 — ATOMIC: take the reporting freeze off

Implement **sub-tasks 6.3 and 6.4 of Task 6 from tasks.md.**

Step 6 built the structural comparison. Nothing calls it. This step makes it the
gate for the three reporting tools and retires byte-equality for them.

## Read this before touching a file

**6.3 is ONE change. Every bullet in it lands together or nothing lands.**

The requirements forbid any revision in which a freeze criterion is relaxed and its
replacement is absent. Not "relaxed before replaced" — *absent at the same commit*.
If you swap the comparison and stop, or amend the spec and stop, the tree passes
through a state where the default-tenant reporting path has no gate at all. That
state is worse than either end, and it is the specific thing the ordering
requirement exists to prevent.

So: make all the edits, run everything, and only then consider yourself done. If
you run out of room partway, **revert your changes and report** rather than leaving
a partial swap.

6.4 is separate and may land after.

## Files you own

- MODIFY `mcp_server_python/tests/unit/test_default_tenant_byte_equivalence.py`  (6.3)
- MODIFY `.kiro/specs/shared-scope-query-routing/requirements.md`                (6.3)
- MODIFY `.kiro/specs/shared-scope-query-routing/design.md`                      (6.3)
- MODIFY `mcp_server_python/tests/baselines/README.md`                           (6.4)

Do not touch `structural.py` — step 6 finished it. Do not touch the recorded
baselines or the masks. Do not touch anything under `src/`.

## The seven scenarios split three and four

The module currently parameterises one comparison test over all of `SCENARIO_IDS`,
comparing every scenario with `capture.matches_baseline`.

Three are reporting tools and move to structural comparison:

```
get_knowledge_base_status
check_knowledge_integrity
mcp_health_check
```

Four are query tools and **stay byte-frozen** until step 9:

```
search_documentation
search_ee2_standards
search_architecture
get_operational_guidance
```

So partition the scenario list and run two comparison tests instead of one. Derive
the partition from the scenario's own tool name rather than hardcoding a second
list, so adding a scenario later cannot land it in neither group.

## What 6.3 changes in the test module

Compare each of the three reporting scenarios against its recorded baseline using
`parse_structural` and `compare_structural` instead of `matches_baseline`. Leave the
four query-tool scenarios exactly as they are.

**Three things must survive, and each guards something specific:**

- **The coverage guard** (`test_required_r63_reporting_tools_are_covered`) stays.
  It asserts a scenario exists for each of the three reporting tools. Relaxing the
  comparison must not become an opportunity to quietly shrink what is compared.
- **The earned-mask tests stay** — all five of them, including the two that reject a
  fabricated mask and an over-broad one. The masks still govern the four query-tool
  scenarios, and the earned-mask guarantee is what stops a mask being used to paper
  over a real regression. Retiring byte-equality for three scenarios does not retire
  that.
- **The attribution-header test stays** for the scenarios it currently covers.

The masks are irrelevant to a structural comparison — it does not read bytes — so
the reporting scenarios simply stop consulting them. Do not delete the mask
machinery on that basis.

## What 6.3 changes in the Phase 79 spec

**In `requirements.md`:**

Requirement 6 criterion 3 is the one being superseded. It currently ends with the
clause "in preference to the scope-labelling and totalling behaviour that
Requirements 9, 10, and 11 require" — that ranking is exactly what this feature
retires. Record it as superseded, name this feature as the authority, and state
that structural comparison replaces byte-equality for the status, integrity, and
health reporters.

**Write the three conditions into the superseding text itself, not as a
cross-reference.** Same set of collection names, same count per collection, same
verdict per check. A criterion that only points elsewhere is one indirection away
from being unenforceable, and a reviewer should be able to fail a change against
the text in front of them.

Then restore Requirement 10 criterion 5. It currently carries an amendment note
(around line 745) explaining that the default-tenant integrity sample could not be
scoped because byte-equality forbade the per-member reporting it needs. That
obstacle is what you are removing. Restate the criterion in its original form —
requiring the no-tenant sample to be drawn from the union of the default tenant's
resolved collections across the five logical collections — and replace the note with
one naming this feature as the resolution.

**In `design.md`:** Property 8 carries a matching amendment note (around line 1376)
narrowing it to tenants with a non-empty prefix. Restore it to "any tenant" and
replace the note the same way.

Be careful here: `design.md` has three other amendment notes from earlier steps,
two on Property 12 and one on finding 9. **Leave those alone.** They record things
that are still true.

## 6.4 — the capture machinery's status

In `tests/baselines/README.md`:

- State that the capture machinery is **an instrument available to a high-surface
  refactor, not a standing gate**, and name this feature as the authority for that.
  That distinction is the whole point of this exercise: the freeze was right for the
  refactor that introduced it and wrong as a permanent rule.
- **Keep** the recorded provenance revision `4eb422915bdf2728466e6ff5df449b7a539cdede`
  as the origin of the pre-change captures.
- State that a **structural baseline is re-recordable from any revision**, unlike a
  byte baseline, which is only valid from the revision immediately preceding the
  change it gates. Step 6's transitivity property is what makes that true rather
  than merely asserted — cite it.
- Record the re-record procedure: when a correction changes which collections the
  default status report lists, the recorded baseline is re-recorded to the corrected
  set **in the same change**, and the final report names the altered collection.
  Without that affordance the comparison would block the very corrections it exists
  to unblock.

Also assert retention: `capture.py`, every recorded backend scenario, and the
`derive_masks` / `verify_masks_earned` / `matches_baseline` helpers are all still
present. Put that wherever it fits — a small test, or fold it into the module step
10 will build.

## What to expect from the suite

**No new failures.** The suite sits at 1869 passed, 4 failed, 0 skipped.

This is worth being clear about, because a fifth failure at this step would be
easy to misread as expected. It is not. You are changing *how* the reporting
scenarios are compared, not what they render — the same recorded responses go in,
so they pass under structural comparison exactly as they passed under byte
comparison. Nothing about the output moves.

A fifth failure becomes expected only later, when a follow-up actually changes
default-tenant reporting output. That is not this step.

If you see one, it is yours.

_Requirements: 8.2, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 13.1, 13.2, 13.3, 13.4, 13.6_
