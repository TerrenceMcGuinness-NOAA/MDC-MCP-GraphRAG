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

Deliberately NOT asserted here: the multi-member merge citations at
``opensearch_adapter.py`` lines 180 and 205 (``R3.3``, ``R3.7``), which
correctly govern sets with more than one member and are a different
invariant from empty-prefix passthrough. Those lines are untouched by
Task 8.2 and are not expected to mention Property 3 or Property 4 at
all.
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
    cite Property 3."""
    path = _SRC / "tools" / "semantic_search.py"
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Line 476 (1-indexed): the multi_collection_query zero-hit comment.
    line_476 = lines[475]
    assert _PROPERTY_3_RE.search(line_476), (
        "semantic_search.py:476 must cite Property 3, got: "
        f"{line_476!r}"
    )

    # Line 894 (1-indexed): the tenant-prefix status-block comment.
    line_894 = lines[893]
    assert _PROPERTY_3_RE.search(line_894), (
        "semantic_search.py:894 must cite Property 3, got: "
        f"{line_894!r}"
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
    entirely -- these govern sets with more than one member)."""
    path = _SRC / "data" / "opensearch_adapter.py"
    lines = path.read_text(encoding="utf-8").splitlines()

    line_180 = lines[179]
    line_205 = lines[204]
    assert "R3.3" in line_180
    assert "R3.7" in line_205
    # Neither of these two correct, multi-member citations should be
    # rewritten to reference the unrelated Property 3/4 language.
    assert not _PROPERTY_3_RE.search(line_180)
    assert not _PROPERTY_4_RE.search(line_180)
    assert not _PROPERTY_3_RE.search(line_205)
    assert not _PROPERTY_4_RE.search(line_205)
