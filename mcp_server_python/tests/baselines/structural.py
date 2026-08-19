"""Structural_Equivalence relation over rendered reporter responses.

Feature: default-tenant-freeze-retirement (SDD Phase 80), Task 6.1.

Phase 79 froze the Status_Reporter, Integrity_Checker, and Health_Reporter
default-tenant output byte-for-byte. Byte equality is too strict: it preserves
a document total known to be wrong and blocks two corrections. This module is
the replacement relation. It must be looser than byte equality -- blind to
rewording, line order, and whitespace -- and yet tight on exactly three things
(Requirement 9 criterion 1, and the phase-doc's settled three-bullet
definition):

  1. which Physical_Collections are listed,
  2. the document count each carries, and
  3. the pass/fail/skip verdict each named check reports.

The relation is expressed as a projection (:class:`StructuralView`) plus a
comparison (:func:`compare_structural`) so that a divergence has a stable name
to report and a recorded baseline can be re-recorded from any revision
(Requirement 13 criterion 6).

Standard library only, by design: a parser that shared a constant with the
renderer it inspects could not notice that constant changing.

Note on the status-report ``- **Status:**`` verdicts (a resolved tension)
--------------------------------------------------------------------------
design.md finding 9 proposes keying the Status_Reporter's two ``Status`` lines
(one for the vector store, one for the graph) by their enclosing section
heading, so the vector and graph statuses stay distinguishable. That is not
realisable against this feature's shared perturbation generators: Requirement 9
criterion 2 requires the relation be insensitive to line order and label text,
and ``render_perturbations`` implements that by flat-permuting lines (which
destroys any heading-proximity association) and by rewording heading lines
(which changes any heading-text key). The two ``Status`` lines are otherwise
byte-identical, so no perturbation-stable, intrinsic key distinguishes them.

The phase doc's settled definition speaks of "each check" reporting a verdict
and does not fix a keying scheme; heading-keying is a non-settled design-level
detail. This module therefore keys both ``Status`` lines under a single stable
check name (:data:`_STATUS_CHECK_KEY`), collapsing them. A total store-status
regression is still caught; the per-store (vector vs graph) distinction is not,
which is the unavoidable cost of Requirement 9 criterion 2. This deviation from
design finding 9 is reported for the record.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import re


class Verdict(StrEnum):
    """A single check's outcome.

    A ``StrEnum`` so ``list(Verdict)`` yields the members (the shared
    generators in ``tests/properties/conftest.py`` iterate it) and so a
    finding string renders the value directly (``f"{Verdict.PASS}"`` ->
    ``"PASS"``). This matches ``CollectionCondition`` in
    ``src/data/read_router.py``, which is a ``StrEnum`` too.
    """

    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass(frozen=True)
class StructuralView:
    """The Requirement 9 projection of one rendered reporter response.

    Attributes
    ----------
    collections : Mapping[str, int | None]
        ``physical_collection_name -> document_count``. A collection rendered
        ``unprovisioned`` maps to ``None``, which is distinct from ``0``:
        absent and present-but-empty are different findings, rendered
        differently by Phase 79 (R9.5/R9.6), and one of the corrections this
        relation unblocks can plausibly move a collection between those two
        states. Collapsing them would blind the relation to exactly that
        transition.
    verdicts : Mapping[str, Verdict]
        ``check_name -> verdict``. Check names are taken from the response's
        own identifying text -- an integrity table's first cell, a health
        line's bolded label -- never from a decorative heading.
    """

    collections: Mapping[str, int | None]
    verdicts: Mapping[str, Verdict]


# ---------------------------------------------------------------------------
# Parse constants
# ---------------------------------------------------------------------------

#: Collapsed key for the Status_Reporter's per-store ``- **Status:**`` lines.
#: See the module docstring for why the two lines are not kept distinct.
_STATUS_CHECK_KEY = "Status"

#: Severity order used when more than one rendered line maps to the same
#: verdict key. Higher wins.
#:
#: This exists because of a real hole found by probing rather than by test:
#: assigning ``verdicts[key] = verdict`` is last-write-wins, so with the two
#: byte-identical ``- **Status:**`` lines collapsed under one key, a FAIL on
#: the vector store followed by a PASS on the graph store yielded PASS and the
#: failure was silently masked. A graph-only failure was caught purely because
#: that line happens to come second in the render. An order-dependent gate is
#: not a gate.
#:
#: FAIL outranks SKIP outranks PASS. SKIP outranking PASS is the same argument
#: the ``[SKIP]``-in-details-cell override rests on: a check that quietly
#: stopped running must not read as a check that passed.
_VERDICT_SEVERITY: dict[Verdict, int] = {
    Verdict.PASS: 0,
    Verdict.SKIP: 1,
    Verdict.FAIL: 2,
}


def _record_verdict(
    verdicts: dict[str, Verdict], key: str, verdict: Verdict
) -> None:
    """Store ``verdict`` under ``key``, keeping the more severe on collision.

    Collisions are expected only for :data:`_STATUS_CHECK_KEY`, where two
    rendered lines deliberately collapse into one key. Applying the rule
    uniformly costs nothing and means a future rendering change that makes two
    integrity rows or two health labels collide cannot mask a failure either.
    """
    existing = verdicts.get(key)
    if existing is None:
        verdicts[key] = verdict
        return
    if _VERDICT_SEVERITY[verdict] > _VERDICT_SEVERITY[existing]:
        verdicts[key] = verdict


#: A markdown list item: optional indent, a ``-`` bullet, then the item text.
_LIST_ITEM_RE = re.compile(r"^\s*-\s+(?P<item>.*)$")

#: A ``<int> documents`` terminal -- the only structural discriminator that
#: separates a collection line from the graph block's same-shaped
#: ``- CALLS: 1020000`` / ``- FortranSubroutine: 29605`` lines. A ``mdc-``
#: name match would break the moment a collection is renamed and would admit
#: nothing useful.
_DOCUMENTS_RE = re.compile(r"^(?P<count>\d+)\s+documents$")

#: A trailing `` (<scope>)`` annotation on a prefixed-tenant collection name,
#: e.g. ``gw_v17_mdc-jjobs-titan1024 (tenant)`` or ``... (shared)``.
_SCOPE_ANNOTATION_RE = re.compile(r"\s*\([^)]*\)$")

#: A health line: a leading bracket token, a bolded label, then ``: status``.
#: The functional-probe table in the health report is a pipe row and falls to
#: the integrity rule instead, whose status cell is explicit there.
_HEALTH_RE = re.compile(
    r"^\[(?P<token>[A-Z]+)\]\s+\*\*(?P<label>[^*]+)\*\*:\s*\S"
)


def _token_to_verdict(text: str) -> Verdict | None:
    """Map the first recognised bracket token in ``text`` to a Verdict.

    ``[SKIP]`` takes precedence over ``[OK]`` so a passing check whose detail
    text opens ``[SKIP]`` scores as a skip (finding 8). Returns ``None`` when
    no recognised token is present, so header and separator rows are ignored.
    """
    if "[SKIP]" in text:
        return Verdict.SKIP
    if "[OK]" in text:
        return Verdict.PASS
    if "[ERROR]" in text:
        return Verdict.FAIL
    return None


def _parse_collection_item(item: str) -> tuple[str, int | None] | None:
    """Parse a list-item ``item`` as a collection line, or return ``None``.

    The item is a collection line when it has the shape
    ``<name>: <int> documents`` or ``<name>: unprovisioned``. The name is the
    text before the first colon, with a trailing `` (<scope>)`` annotation
    stripped. ``unprovisioned`` yields a ``None`` count.

    Raises
    ------
    ValueError
        When the item carries the `` documents`` terminal but the count does
        not parse. A malformed count must raise rather than default: ``None``
        already means unprovisioned and ``0`` already means provisioned-empty,
        so folding a third meaning into either would blind the relation to the
        transition it exists to watch.
    """
    if ":" not in item:
        return None
    name_part, value_part = item.split(":", 1)
    value = value_part.strip()
    if value == "unprovisioned":
        count: int | None = None
    elif value.endswith(" documents"):
        match = _DOCUMENTS_RE.match(value)
        if match is None:
            raise ValueError(
                "structural: malformed document count in collection "
                f"line: {item!r}"
            )
        count = int(match.group("count"))
    else:
        return None
    name = _SCOPE_ANNOTATION_RE.sub("", name_part.strip()).strip()
    return name, count


def _parse_status_verdict(item: str) -> Verdict | None:
    """Parse a Status_Reporter ``- **Status:**`` list item, or ``None``.

    The item is a status verdict when its label (before the first colon,
    stripped of ``*`` markers) is exactly ``Status`` and its value carries an
    ``[OK]`` / ``[ERROR]`` token.
    """
    if ":" not in item:
        return None
    label_part, value_part = item.split(":", 1)
    label = label_part.replace("*", "").strip()
    if label != _STATUS_CHECK_KEY:
        return None
    return _token_to_verdict(value_part)


def _parse_integrity_row(line: str) -> tuple[str, Verdict] | None:
    """Parse an integrity three-cell pipe row, or return ``None``.

    Verdict is taken from cell 2's token and overridden to ``SKIP`` when cell
    3 opens with ``[SKIP]`` (finding 8). Keyed by cell 1. Header and separator
    rows carry no token in cell 2 and are ignored.
    """
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    if len(cells) != 3:
        return None
    name, status_cell, detail_cell = cells
    verdict = _token_to_verdict(status_cell)
    if verdict is None:
        return None
    if detail_cell.startswith("[SKIP]"):
        verdict = Verdict.SKIP
    return name, verdict


def parse_structural(text: str) -> StructuralView:
    """Project a rendered reporter response onto a :class:`StructuralView`.

    Four extraction rules, each verified against a recorded Phase 79 baseline;
    every other line contributes nothing, which is what buys insensitivity to
    rewording, line order, and whitespace (Requirement 9 criterion 2).

    Parameters
    ----------
    text : str
        A rendered Status_Reporter, Integrity_Checker, or Health_Reporter
        response, either freshly rendered or read from a recorded baseline.
        Taking ``str`` is what satisfies Requirement 9 criterion 6: one
        function reads both, so no separate baseline format exists and the two
        cannot drift.

    Returns
    -------
    StructuralView
        The collections and verdicts the response identifies.

    Raises
    ------
    ValueError
        When a collection line carries the `` documents`` terminal but its
        count does not parse (see :func:`_parse_collection_item`).
    """
    collections: dict[str, int | None] = {}
    verdicts: dict[str, Verdict] = {}

    for raw_line in text.split("\n"):
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        # Integrity rows are the only lines that start with a pipe; the
        # inline ``| **Collection:**`` in a query-tool render does not, so it
        # is not mistaken for a verdict row.
        if stripped.startswith("|"):
            parsed_row = _parse_integrity_row(line)
            if parsed_row is not None:
                _record_verdict(verdicts, parsed_row[0], parsed_row[1])
            continue

        health_match = _HEALTH_RE.match(stripped)
        if health_match is not None:
            verdict = _token_to_verdict(f"[{health_match.group('token')}]")
            if verdict is not None:
                _record_verdict(
                    verdicts, health_match.group("label").strip(), verdict
                )
            continue

        item_match = _LIST_ITEM_RE.match(line)
        if item_match is not None:
            item = item_match.group("item").rstrip()
            status_verdict = _parse_status_verdict(item)
            if status_verdict is not None:
                _record_verdict(
                    verdicts, _STATUS_CHECK_KEY, status_verdict
                )
                continue
            parsed_collection = _parse_collection_item(item)
            if parsed_collection is not None:
                collections[parsed_collection[0]] = parsed_collection[1]
            continue

    return StructuralView(collections=collections, verdicts=verdicts)


def _fmt_count(count: int | None) -> str:
    """Render a document count for a finding message.

    ``None`` (unprovisioned) is rendered as the word so a count finding that
    involves the unprovisioned/present-but-empty distinction reads correctly.
    """
    return "unprovisioned" if count is None else str(count)


def compare_structural(
    baseline: StructuralView, candidate: StructuralView
) -> list[str]:
    """Return the Structural_Equivalence findings between two views.

    An empty list means the relation holds. Each divergence yields exactly one
    finding so a set difference of three collections reads as three lines a
    reviewer can act on, not one opaque diff. Findings are ordered collections
    then verdicts and sorted by name, so a failure message is stable across
    runs.

    Parameters
    ----------
    baseline : StructuralView
        The reference view -- typically a recorded baseline.
    candidate : StructuralView
        The view under test.

    Returns
    -------
    list[str]
        One ``structural: ...`` finding per divergence; empty when equivalent.

    Raises
    ------
    ValueError
        When ``baseline`` is empty (no collections and no verdicts). A
        comparison that passes because it found nothing to check is the one
        failure a reviewer never sees -- a reporter whose rendering broke
        entirely would otherwise compare equal to another broken one.
    """
    if not baseline.collections and not baseline.verdicts:
        raise ValueError(
            "structural: baseline view is empty (no collections, no "
            "verdicts); a broken render must not compare equivalent"
        )

    findings: list[str] = []

    base_cols = baseline.collections
    cand_cols = candidate.collections
    for name in sorted(set(base_cols) - set(cand_cols)):
        findings.append(
            f"structural: collection present only in baseline: {name}"
        )
    for name in sorted(set(cand_cols) - set(base_cols)):
        findings.append(
            f"structural: collection present only in candidate: {name}"
        )
    for name in sorted(set(base_cols) & set(cand_cols)):
        if base_cols[name] != cand_cols[name]:
            findings.append(
                f"structural: {name} document count "
                f"{_fmt_count(base_cols[name])} != "
                f"{_fmt_count(cand_cols[name])}"
            )

    base_v = baseline.verdicts
    cand_v = candidate.verdicts
    for name in sorted(set(base_v) - set(cand_v)):
        findings.append(
            f"structural: check present only in baseline: {name}"
        )
    for name in sorted(set(cand_v) - set(base_v)):
        findings.append(
            f"structural: check present only in candidate: {name}"
        )
    for name in sorted(set(base_v) & set(cand_v)):
        if base_v[name] != cand_v[name]:
            findings.append(
                f"structural: check {name} verdict "
                f"{base_v[name]} != {cand_v[name]}"
            )

    return findings
