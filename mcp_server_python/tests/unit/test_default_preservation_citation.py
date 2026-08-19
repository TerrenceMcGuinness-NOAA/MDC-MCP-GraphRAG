"""R6.4: default-preservation invariant citations must name Property 3.

shared-scope-query-routing Task 8.2. Three comments/docstrings cited the
wrong invariant for default-tenant preservation:

* ``src/tools/semantic_search.py`` lines 476 and 894
* ``src/data/opensearch_adapter.py`` line 274 (``resolve_tenant_index``
  docstring)

The correct citation is Property 3 (Empty-prefix passthrough) of
``.kiro/specs/omd-tenants-1-foundation/design.md`` -- for any tenant with
an empty ``index_prefix`` and any collection ``c``,
``resolve_tenant_index(c, T) == c``. Property 4 is Resolution
determinism (repeated invocations agreeing with each other), a different
claim entirely, and must not remain attached to passthrough/preservation
prose anywhere in either file.

This test is written so it would fail if the mis-citation were
reintroduced anywhere in either file, not just at the three known
lines -- it scans the whole file rather than pinning line numbers.

Deliberately NOT asserted here: the multi-member merge citations near
the ``R3.3``/``R3.7`` comments in ``opensearch_adapter.py``, which
correctly govern sets with more than one member and are a different
invariant from empty-prefix passthrough. Those comments are untouched by
Task 8.2 and are not expected to mention Property 3 or Property 4 at
all.

Repair (2026-08-19)
-------------------
The two ``semantic_search.py`` assertions originally located their target
comment by hardcoded line index (``lines[475]``, ``lines[893]``). That
pinned every line at or above the lower index to its exact position:
Task 10's implementation had to preserve ``semantic_search.py`` byte-for-
byte at and above line 894, and specifically had to avoid a top-level
``import math`` (using integer ceil-division instead) purely to keep
these two indices from shifting. A test dictating implementation choices
this way, for no benefit the content-based scan above does not already
provide, is a brittleness worth removing. Both assertions now locate
their target comment by content -- a stable identifying phrase unique to
each comment -- and read the citation from the line at or shortly after
that phrase, wherever the comment now lives. The identifying phrases (the
``multi_collection_query`` zero-hit context, and the tenant-prefix
status-block context) are stable prose, not line positions, so this test
no longer constrains where either comment may move.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"

_TARGET_FILES = (
    _SRC / "tools" / "semantic_search.py",
    _SRC / "data" / "opensearch_adapter.py",
)

# Matches "Property 4" optionally followed by a parenthetical name such
# as "(Resolution determinism)". Case-sensitive: "Property 4" is the
# exact token used across this codebase's citations (see
# read_router.py, collection_scope.py doc comments).
_PROPERTY_4_RE = re.compile(r"Property\s+4\b")

# Matches the correct citation form so the test can assert it is present
# for the three known preservation-invariant comments, not merely that
# Property 4 is absent (an empty file would vacuously pass a
# absence-only check).
_PROPERTY_3_RE = re.compile(r"Property\s+3\b")

#: Identifying phrase for the ``multi_collection_query`` zero-hit comment
#: in ``semantic_search.py`` (was pinned as ``lines[475]``, 1-indexed 476).
#: Content-based, not position-based: the phrase is stable prose that
#: uniquely marks this comment regardless of where it moves in the file.
#: The phrase is taken from the citation line itself (not the preceding
#: line the same comment wraps onto), so it is robust to re-wrapping.
_MULTI_COLLECTION_ZERO_HIT_MARKER = "swallows per-collection 404s"

#: Identifying phrase for the tenant-prefix status-block comment in
#: ``semantic_search.py`` (was pinned as ``lines[893]``, 1-indexed 894).
_STATUS_BLOCK_PRESERVATION_MARKER = "gw block stays byte-equivalent"

#: Identifying phrases for the two CORRECT multi-member merge citations in
#: ``opensearch_adapter.py`` (were pinned as ``lines[179]`` / ``lines[204]``,
#: 1-indexed 180 and 205). These guard against a future sweep rewriting a
#: correct R3.3/R3.7 citation into Property 3/4 language, so they must keep
#: asserting -- but by content, not position. Pinning them by index re-armed
#: exactly the brittleness this module was repaired to remove: it made any
#: edit earlier in that file a failure of this test.
_SINGLE_MEMBER_IDENTITY_MARKER = "R3.3-R3.8 apply only to multi-member sets"
#: NOTE: anchored on the co-citation pattern, not on the surrounding prose.
#: "shared content precedes branch-local content" appears TWICE in that file
#: -- once in the step-4 bullet that wraps onto this citation line, and once
#: in the score-bucketing semantics comment -- so it is ambiguous and the
#: one-match helper rejects it. "R3.3, R3.7" occurs exactly once, on the
#: citation line the original lines[204] pinned.
_TOTAL_ORDER_TIEBREAK_MARKER = "R3.3, R3.7"


def _find_line_containing(text: str, marker: str) -> str:
    """Return the single line of ``text`` containing ``marker``.

    Content-based lookup, replacing a hardcoded ``lines[N]`` index: the
    comment this test targets is identified by its stable surrounding
    prose, not by its position in the file, so the comment (and every
    other line) is free to move without breaking this test.

    Raises
    ------
    AssertionError
        If ``marker`` is found on zero lines, or on more than one line
        (an ambiguous marker is a test-authoring defect, not a pass).
    """
    matches = [
        line for line in text.splitlines() if marker in line
    ]
    assert matches, (
        f"expected exactly one line containing {marker!r}, found none"
    )
    assert len(matches) == 1, (
        f"expected exactly one line containing {marker!r}, found "
        f"{len(matches)}: {matches!r}"
    )
    return matches[0]


def _find_citation_near(
    text: str, marker: str, *, lookahead: int = 3
) -> str:
    """Return the citation line within ``lookahead`` lines of ``marker``.

    Some multi-line comments carry their identifying prose on one line
    and their ``(Property N / ...)`` citation on a following line (the
    comment wraps). This locates ``marker``'s line by content, then
    returns the first line at or after it -- within ``lookahead`` lines
    -- that mentions either "Property 3" or "Property 4", so the
    citation is found by content on both axes: which comment, and which
    of its lines carries the citation.

    Raises
    ------
    AssertionError
        If ``marker``'s line cannot be found uniquely, or no citation
        line is found within the lookahead window.
    """
    lines = text.splitlines()
    marker_indices = [i for i, line in enumerate(lines) if marker in line]
    assert marker_indices, (
        f"expected exactly one line containing {marker!r}, found none"
    )
    assert len(marker_indices) == 1, (
        f"expected exactly one line containing {marker!r}, found "
        f"{len(marker_indices)}"
    )
    start = marker_indices[0]
    window = lines[start:start + 1 + lookahead]
    for line in window:
        if _PROPERTY_3_RE.search(line) or _PROPERTY_4_RE.search(line):
            return line
    raise AssertionError(
        f"no Property 3/4 citation found within {lookahead} lines after "
        f"the comment identified by {marker!r}; window={window!r}"
    )


@pytest.mark.parametrize("path", _TARGET_FILES, ids=lambda p: p.name)
def test_no_property_4_citation_anywhere(path: Path) -> None:
    """Neither file may cite Property 4 anywhere, under any spelling.

    Property 4 (Resolution determinism) is never the invariant either
    file needs to cite: the only cross-spec property either file's
    comments discuss is default-tenant preservation via empty-prefix
    passthrough, which is Property 3. If a future edit reintroduces a
    "Property 4" citation into one of these two files, this assertion
    fails naming the offending line.
    """
    text = path.read_text(encoding="utf-8")
    offending_lines = [
        f"{path.name}:{i}: {line.strip()}"
        for i, line in enumerate(text.splitlines(), start=1)
        if _PROPERTY_4_RE.search(line)
    ]
    assert not offending_lines, (
        "Found a 'Property 4' citation where the default-preservation "
        "invariant (Property 3, Empty-prefix passthrough) is meant:\n"
        + "\n".join(offending_lines)
    )


def test_semantic_search_cites_property_3_at_known_sites() -> None:
    """The two former Property-4 mis-citations in semantic_search.py now
    cite Property 3.

    Located by content, not by line index (see module docstring "Repair"
    section) -- each comment is found by a stable identifying phrase,
    then Property 3 is asserted on the citation line found near it,
    wherever the comment now lives.
    """
    path = _SRC / "tools" / "semantic_search.py"
    text = path.read_text(encoding="utf-8")

    multi_collection_line = _find_citation_near(
        text, _MULTI_COLLECTION_ZERO_HIT_MARKER
    )
    assert _PROPERTY_3_RE.search(multi_collection_line), (
        "the multi_collection_query zero-hit comment in "
        "semantic_search.py must cite Property 3, got: "
        f"{multi_collection_line!r}"
    )

    status_block_line = _find_citation_near(
        text, _STATUS_BLOCK_PRESERVATION_MARKER
    )
    assert _PROPERTY_3_RE.search(status_block_line), (
        "the tenant-prefix status-block comment in semantic_search.py "
        f"must cite Property 3, got: {status_block_line!r}"
    )


def test_opensearch_adapter_resolve_tenant_index_cites_property_3() -> None:
    """``resolve_tenant_index``'s docstring cites Property 3, not R3.3.

    R3.3 (this spec's numbering) governs the multi-member merge and is
    correctly used elsewhere in this same file (lines 180, 205) for that
    different claim. The docstring at line 274 describes empty-prefix
    passthrough -- a different invariant -- and must cite Property 3 of
    ``omd-tenants-1-foundation`` instead.
    """
    path = _SRC / "data" / "opensearch_adapter.py"
    text = path.read_text(encoding="utf-8")

    import ast

    tree = ast.parse(text)
    docstring = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == (
            "resolve_tenant_index"
        ):
            docstring = ast.get_docstring(node)
            break

    assert docstring is not None, (
        "resolve_tenant_index not found in opensearch_adapter.py"
    )
    assert _PROPERTY_3_RE.search(docstring), (
        "resolve_tenant_index docstring must cite Property 3 "
        f"(Empty-prefix passthrough), got: {docstring!r}"
    )
    assert not _PROPERTY_4_RE.search(docstring), (
        "resolve_tenant_index docstring must not cite Property 4"
    )


def test_multi_member_merge_citations_untouched() -> None:
    """R3.3/R3.7 citations for the genuinely multi-member-scoped claims
    at opensearch_adapter.py lines 180 and 205 remain, and are not
    conflated with Property 3 or Property 4 (a different invariant
    entirely -- these govern sets with more than one member).

    Located by content rather than by line index, for the same reason the
    Property 3 assertions above are: a positional lookup here makes any
    edit earlier in the file fail this test, which already cost one step
    a byte-for-byte line-preservation constraint and forced it to avoid a
    top-level import purely to keep indices stable.
    """
    path = _SRC / "data" / "opensearch_adapter.py"
    text = path.read_text(encoding="utf-8")

    line_180 = _find_line_containing(text, _SINGLE_MEMBER_IDENTITY_MARKER)
    line_205 = _find_line_containing(text, _TOTAL_ORDER_TIEBREAK_MARKER)
    assert "R3.3" in line_180
    # Tautological for line_205 by construction (the marker IS the citation);
    # the load-bearing assertions for it are the two Property 3/4 absence
    # checks below, which are what a careless sweep would break.
    assert "R3.7" in line_205
    # Neither of these two correct, multi-member citations should be
    # rewritten to reference the unrelated Property 3/4 language.
    assert not _PROPERTY_3_RE.search(line_180)
    assert not _PROPERTY_4_RE.search(line_180)
    assert not _PROPERTY_3_RE.search(line_205)
    assert not _PROPERTY_4_RE.search(line_205)
