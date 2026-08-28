# Task 6.1 + 6.2 — the structural comparison that replaces byte-equality

Implement **sub-tasks 6.1 and 6.2 of Task 6 from tasks.md.** Not 6.3, not 6.4 —
step 7 owns those, and 6.3 is atomic for reasons that matter.

This is where the freeze starts coming off. You build the comparison; step 7 swaps
it in.

## Files you own

- NEW    `mcp_server_python/tests/baselines/structural.py`                    (6.1)
- NEW    `mcp_server_python/tests/properties/test_structural_equivalence.py`  (6.2)
- MODIFY `mcp_server_python/tests/properties/conftest.py`                     (only if 6.2 needs it)

**Nothing you write is called by anything yet.** Byte-equality is still fully in
force for all seven scenarios throughout your step. That is deliberate: it means
you cannot break the existing gate, and it is why 6.1/6.2 are separated from the
atomic swap in step 7.

Do not touch `test_default_tenant_byte_equivalence.py`, the recorded baselines, or
anything under `src/`.

## Why this exists

Byte-equality currently freezes the status, integrity, and health reports. It is
preserving a document total that is known to be wrong, and it blocks two
corrections. The replacement has to be looser than byte-equality but not so loose
it permits anything — it must be blind to rewording and sensitive to three things:
which collections are listed, what count each has, and what verdict each check
got.

## 6.1 — the parser and the comparison

Two functions and a value type. Import **standard library only**. A parser that
shared a constant with the code it inspects could not notice that constant
changing.

```python
@dataclass(frozen=True)
class StructuralView:
    collections: Mapping[str, int | None]
    verdicts: Mapping[str, Verdict]

def parse_structural(text: str) -> StructuralView: ...
def compare_structural(baseline, candidate) -> list[str]: ...
```

**Make `Verdict` a `StrEnum`** with `PASS`, `FAIL`, `SKIP`. Step 1 already wrote
generators that build views for you, and they assume the type is an enum you can
iterate with `list(Verdict)`. `CollectionCondition` in `src/data/read_router.py` is
a `StrEnum` too, so this matches what's already in the tree. If you deviate, you
must update `structural_views` and `triple_perturbations` in the properties
conftest — step 1 flagged them as awaiting your confirmation.

**`None` means unprovisioned, and it is not `0`.** Absent and present-but-empty are
different findings, rendered differently, and one of the corrections this unblocks
can plausibly move a collection between those states. Collapse them and the
comparison goes blind to exactly that transition.

### The four extraction rules, each verified against a real recorded baseline

**Collection lines.** A list item whose text ends in ` <int> documents` or
` unprovisioned`. The name is the token before the first colon, with a trailing
` (<scope>)` annotation stripped when present.

The terminal is the discriminator and it is the only one available. From the real
default-tenant capture:

```
  - mdc-workflow-docs-titan1024: 35980 documents     <- collection
  - CALLS: 1020000                                    <- graph relationship
  - FortranSubroutine: 29605                           <- graph label
```

Identical list-item-with-colon shape. Only the ` documents` suffix separates them.
Matching on `mdc-` instead would work today and break the moment a collection is
renamed, while admitting nothing you actually need.

The prefixed render adds the annotation, so both of these must parse:

```
  - mdc-jjobs-titan1024: 751 documents
  - gw_v17_mdc-jjobs-titan1024 (tenant): 92 documents
  - gw_v17_mdc-ee2-standards-titan1024 (shared): unprovisioned
```

**Status verdicts.** A `Status` field line carrying an `[OK]` or `[ERROR]` token,
keyed by the enclosing section heading. There are two such lines — one for the
vector store, one for the graph — so the heading is what tells them apart. Keying
on the field name alone would collapse them and lose a real signal.

Do not capture `**Overall Status**: HEALTHY (4/4 components healthy)` from the
health report as a verdict; it carries no bracket token.

**Integrity verdicts.** A three-cell pipe row. Verdict from cell 2's token, keyed
by cell 1. **But override to `SKIP` when cell 3 opens with `[SKIP]`.**

That override is the highest-value rule in the module, and here is why it is not
obvious. Four checks return a passing result whose detail text begins `[SKIP]`, so
the row renders as:

```
| Path Consistency | [OK] | [SKIP] vector adapter does not expose a metadata sampler |
```

An extractor reading only the status column scores a real pass and a silent skip as
**equal**. That is precisely the degradation this comparison exists to catch: a
correction that accidentally turned a working check into a skipped one would pass
unnoticed.

**The recorded baseline does not contain this shape** — every row in it has `[OK]`
in both cells. So you cannot discover this by looking at the capture, and a random
generator will not construct it. 6.2 must pin it as an explicit input.

Note the check names include per-language variants — `Coverage Gap (Fortran)`,
`Coverage Gap (Python)`, `Coverage Gap (Shell)` — built dynamically. Key on
whatever cell 1 holds; do not enumerate names.

**Health verdicts.** A line opening with a bracket token, carrying a bolded label,
then `: status`. Real shape:

```
[OK] **Vector Database**: healthy
```

Keyed by the label. The health report's functional-probe table is a pipe row and
correctly falls to the integrity rule, whose status cell is explicit there.

**Everything else is ignored.** That is what buys insensitivity to rewording: the
two mappings make line order irrelevant, headings are never captured except as
verdict keys, whitespace is normalised per line, and a line matching no rule
contributes nothing.

### The comparison

Return a **list of findings**, not a bool. Empty means equivalent. One finding per
divergence, ordered collections then verdicts, sorted by name so a failure message
is stable across runs.

```
structural: collection present only in baseline: mdc-content-sha-registry
structural: collection present only in candidate: <name>
structural: mdc-workflow-docs-titan1024 document count 129013 != 128262
structural: check Path Consistency verdict PASS != SKIP
```

A set difference of three names produces three findings, not one opaque diff. The
first correction this unblocks changes exactly one collection in the default
total, and whoever reviews it needs to read "this one moved" straight off the
failure.

Two parse-time conditions:

- **An empty view must not silently compare equal to another empty view.** A
  reporter whose rendering broke entirely would produce no collections and no
  verdicts, and the comparison would pass. Assert the baseline view is non-empty
  before comparing, and fail naming the scenario. A comparison that passes because
  it found nothing to check is the one failure a reviewer never sees.
- **A count that does not parse must raise**, not default. `None` already means
  unprovisioned and `0` already means present-but-empty; folding a third meaning
  into either blinds the comparison to the transition it exists to watch.

## 6.2 — three properties, and why it takes three

New `tests/properties/test_structural_equivalence.py`. Hypothesis, `deadline=None`,
tagged `# Feature: default-tenant-freeze-retirement, Property N: <title>`.

Step 1 built `structural_views`, `render_perturbations`, and
`triple_perturbations` for you. They lazily import your type, so they start working
the moment 6.1 lands.

**Property 1 — it is an equivalence relation.** Reflexive, symmetric, transitive.

Not academic. Reflexivity is what makes a re-recorded baseline a valid reference at
all. Symmetry is what makes the two-directional collection finding well defined —
a comparison whose verdict depended on argument order would report a dropped
collection one way and nothing the other. Transitivity is what lets three
successive corrections re-record in sequence without the third quietly diverging
from the first.

**Property 2 — blind to non-identifying variation.** Over the recorded reporter
baselines and any sequence of perturbations from `render_perturbations` — line
permutation, heading rewrite, caption rewrite, whitespace, an inserted line naming
nothing — the comparison returns no findings.

**Property 3 — sensitive to the three things, with attribution.** A single
perturbation from `triple_perturbations` yields a non-empty finding list in which
**exactly one** finding names the perturbed element, and each kind of finding names
what it should.

**Properties 2 and 3 exist as a pair and neither is sufficient alone.** A
comparison that ignores everything passes 2. Byte-equality passes 3. Only both
together say the relation is loose in the right place and tight in the right place.
Put that in a comment.

Pin two inputs alongside the generators, because each is a real shape a plausible
extractor gets wrong and a generator will not build:

1. The `[SKIP]`-in-details row above, with `[OK]` in the status cell.
2. A render listing only `gw_v17_mdc-workflow-docs-titan1024`, compared against a
   baseline expecting `mdc-workflow-docs-titan1024`. Bare-substring extraction
   finds the short name inside the long one and passes. This is the same
   containment trap step 2 hit from the other direction.

Use `max_examples=200` on Properties 2 and 3 rather than 100. The perturbation
space is small and discrete, and the interesting draws — one landing on the single
collection whose count is `None`, a permutation moving a table row across its
header — are individually unlikely.

## Suite state

**1854 passed, 4 failed, 0 skipped.** A fifth failure is yours. Your work adds
tests and changes no existing behaviour, so nothing should move.

_Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 13.6_
