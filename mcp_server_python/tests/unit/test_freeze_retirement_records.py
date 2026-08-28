"""Document-content and history assertions for the freeze retirement.

default-tenant-freeze-retirement (SDD Phase 80), Task 10.3.

Task 10 wrote the Retirement_Record and amended the Phase 79 spec, the
Phase 79 design, and the baselines README. This module asserts that those
documents actually carry what the requirements demand, and that the two
supersessions landed in the order and shape Requirement 8 constrains.

Three groups of assertion, each derived from the criterion rather than from
the document -- an assertion shaped to what a document happens to say passes
by construction and would not notice a missing clause:

* **Retirement_Record content.** One assertion per criterion of Requirements
  5, 6, 8.4, 8.5, 12, 13.5, 14, and 15.7, each naming the criterion in its
  failure message so a failure says which clause is missing rather than that
  a document is short. Each predicate is built from the tokens the criterion
  makes mandatory -- config-key names, metric names, revision hashes, the
  Governing_Threshold percentage -- which a legitimate rewording keeps.
* **Amended specs.** The Phase 79 ``requirements.md`` records both
  supersessions naming this feature, carries the three Requirement 9
  criterion 1 conditions as the R6.3 superseding text, restates R10.5 in the
  union form, and replaces its 2026-08-19 amendment note; the Phase 79
  ``design.md`` restores Property 8 over any Tenant; and the baselines
  ``README.md`` records the instrument-not-a-gate status.
* **The staging (R8.1, R8.2, R8.3).** These constrain the *sequence of
  revisions*, not behaviour at any revision, so no sampled code state and no
  property can demonstrate them -- history is not an input. They are checked
  two ways, and neither may skip (10.1 forbids a conditionally-skipped test
  this feature adds):

    - The **primary contract** is a working-tree equivalent that needs no
      git and is always meaningful: for each Phase 79 criterion the
      requirements record as superseded, its replacement check is present in
      the byte-equivalence test module. This is the path that runs after a
      squash merge, where every Phase 80 commit collapses into one and the
      per-commit separation is no longer visible in history.
    - The **stronger check**, available while the branch is intact, walks the
      history. The two supersessions carry the identical marker, so the
      marker cannot say which criterion a commit amended; each is instead
      identified by the distinctive replacement symbol it introduces into the
      test module -- ``parse_structural`` / ``compare_structural`` for the
      R6.3 reporting supersession, ``addressed_set`` /
      ``check_hit_provenance`` for the R6.2 query supersession. The
      Benchmark_Harness must precede both (R8.1), and each supersession
      commit must also carry its replacement (R8.2, R8.3). A missing git is
      a loud failure, not a skip; a collapsed history degrades to the primary
      contract, not a skip.

default-tenant-freeze-retirement Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6,
10.1, 10.2, 10.3, 10.4, 11.1, 11.4, 12.1, 12.2, 12.3, 13.2, 13.3, 13.6, 15.4,
15.6.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Repository anchors
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MCP_PYTHON = _REPO_ROOT / "mcp_server_python"
_REPORTS_DIR = _REPO_ROOT / "docs" / "reports"
_REQ79 = (
    _REPO_ROOT
    / ".kiro"
    / "specs"
    / "shared-scope-query-routing"
    / "requirements.md"
)
_DES79 = (
    _REPO_ROOT
    / ".kiro"
    / "specs"
    / "shared-scope-query-routing"
    / "design.md"
)
_README = _MCP_PYTHON / "tests" / "baselines" / "README.md"
_BYTE_EQ = (
    _MCP_PYTHON
    / "tests"
    / "unit"
    / "test_default_tenant_byte_equivalence.py"
)
_HARNESS = _MCP_PYTHON / "scripts" / "run_benchmark.py"

#: Basename glob for the single Retirement_Record under ``docs/reports/``.
_RECORD_GLOB = "*default-tenant-freeze-retirement*.md"

#: The supersession marker both R6.2 and R6.3 carry, normalized-lowercased.
#: Identical on both, which is exactly why the history walk identifies the
#: commits by their replacement symbols instead of by this marker.
_MARKER = "superseded 2026-08-19 by `default-tenant-freeze-retirement`"


# ---------------------------------------------------------------------------
# Text helpers -- normalize whitespace so a line-wrapped phrase still matches
# ---------------------------------------------------------------------------


def _norm(text: str) -> str:
    """Collapse all runs of whitespace to single spaces and lowercase.

    The documents wrap prose across lines, so a required multi-word phrase
    is frequently split by a newline. Normalizing before a substring test
    makes the assertion insensitive to that wrapping without loosening it.

    Parameters
    ----------
    text
        Raw document text.

    Returns
    -------
    str
        The text with whitespace collapsed and folded to lowercase.
    """
    return " ".join(text.split()).lower()


def _all(text: str, *subs: str) -> bool:
    """Return True when every substring in ``subs`` is present in ``text``."""
    return all(sub in text for sub in subs)


def _record_path() -> Path:
    """Return the single Retirement_Record path under ``docs/reports/``.

    Returns
    -------
    Path
        The one matching markdown document.

    Raises
    ------
    AssertionError
        If zero or more than one candidate is present -- Requirement 5's
        Glossary names a single Retirement_Record, so an ambiguous match is
        itself a defect worth failing on rather than papering over.
    """
    candidates = sorted(_REPORTS_DIR.glob(_RECORD_GLOB))
    assert len(candidates) == 1, (
        "expected exactly one Retirement_Record under docs/reports/ matching "
        f"{_RECORD_GLOB!r}, found {[str(p) for p in candidates]}"
    )
    return candidates[0]


def _record_raw() -> str:
    """Return the raw Retirement_Record text (for the ASCII check)."""
    return _record_path().read_text(encoding="utf-8")


def _record_norm() -> str:
    """Return the normalized-lowercased Retirement_Record text."""
    return _norm(_record_raw())


# ---------------------------------------------------------------------------
# Retirement_Record content -- one check per criterion
#
# Each predicate takes the normalized-lowercased record text and returns
# True when the criterion's mandated element is present. The tokens are
# derived from the criterion: config-key names (R6.1), the four metric names
# and the formula claim (R5.1), the sample sizes (R5.2), the archive filename
# and the restart (R5.4), the six audited files (R12.2), and so on. Every
# token is one a faithful rewording would retain.
# ---------------------------------------------------------------------------

_CONSUMER_AUDIT_FILES = (
    "parity_runner.py",
    "test_self_parity.py",
    "test_tenant_resolver.py",
    "test_config_file_writes.py",
    "test_tenant_tool_exposure.py",
    "test_attribution_branch.py",
)


def _r5_3(n: str) -> bool:
    """R5.3: record one arm of the comparability disjunction."""
    demonstrated_clean = _all(
        n, "no gated_metric", "governing_threshold"
    )
    not_demonstrated = "comparability" in n and "not demonstrated" in n
    return demonstrated_clean or not_demonstrated


def _r12_5(n: str) -> bool:
    """R12.5: pair a consumer with a follow-up, or state none applies."""
    names_pair = "alongside" in n and "follow_up_sequence" in n
    states_none = "no in-repo consumer" in n
    return names_pair or states_none


#: ``(criterion_id, human_description, predicate)``. Parametrized so a
#: failure names exactly which criterion's element is missing.
_RECORD_CHECKS: list[tuple[str, str, object]] = [
    (
        "R5.1",
        "per-metric statement of formula agreement with the Node_Harness",
        lambda n: _all(
            n,
            "precision_at_k",
            "recall_at_k",
            "coverage",
            "mrr",
            "same formula",
        ),
    ),
    (
        "R5.2",
        "the 147/21 mrr==coverage identity as a property of both harnesses",
        lambda n: _all(
            n,
            "147",
            "21",
            "mrr value equal to its coverage",
            "one response text",
        ),
    ),
    (
        "R5.3",
        "either no gated-metric drift or comparability-not-demonstrated",
        _r5_3,
    ),
    (
        "R5.4",
        "the named archive file and the Median_Window restart",
        lambda n: _all(
            n, "archive", "quality_metrics_", ".jsonl.gz", "restart"
        ),
    ),
    (
        "R5.6",
        "the changeover decision as a dated entry",
        lambda n: _all(n, "2026-08-19", "changeover", "median window"),
    ),
    (
        "R6.1",
        "all three pre-existing thresholds and each comparison basis",
        lambda n: _all(
            n,
            "regression_threshold_pct",
            "critical_threshold_pct",
            "mcp_benchmark_regression_pct",
            "previous single run",
            "trailing 7-run median",
        ),
    ),
    (
        "R6.2",
        "exactly one Governing_Threshold as a percentage and its basis",
        lambda n: _all(n, "governing_threshold", "10 percent", "median"),
    ),
    (
        "R6.4",
        "the Median_Window count and the minimum_coverage_pct floor",
        lambda n: _all(n, "median_window", "7", "minimum_coverage_pct", "80"),
    ),
    (
        "R6.6",
        "corpus metrics_config values remain in force for the Node_Harness",
        lambda n: _all(n, "metrics_config", "remain in force", "node_harness"),
    ),
    (
        "R8.4",
        "the two conditions that blocked earlier retirement and their status",
        lambda n: _all(n, "benchmark harness", "live-invocation", "clear"),
    ),
    (
        "R8.5",
        "the three live-invocation entries unmet, operator-gated, stood in",
        lambda n: _all(
            n, "verification_record", "unmet", "operator-gated", "hermetic"
        ),
    ),
    (
        "R12.1",
        "in-repo consumers named with the response element each matches on",
        lambda n: "response element" in n
        and all(f in n for f in _CONSUMER_AUDIT_FILES),
    ),
    (
        "R12.2",
        "the six specifically-required Consumer_Audit files",
        lambda n: all(f in n for f in _CONSUMER_AUDIT_FILES),
    ),
    (
        "R12.3",
        "out-of-repo consumers as a bounded, un-enumerable finding",
        lambda n: _all(n, "cannot be enumerated", "bounded finding"),
    ),
    (
        "R12.4",
        "the Collection field as the Logical name, physical_collection new",
        lambda n: _all(
            n, "physical_collection", "logical_collection", "repurposing"
        ),
    ),
    (
        "R12.5",
        "a consumer paired with the follow-up it is affected by, or none",
        _r12_5,
    ),
    (
        "R13.5",
        "the revision a recorded baseline was captured from, and void-ness",
        lambda n: _all(
            n, "4eb422915bdf2728466e6ff5df449b7a539cdede", "captured", "void"
        ),
    ),
    (
        "R14.1",
        "the Follow_Up_Sequence in order with its governing Phase 79 rule",
        lambda n: _all(
            n,
            "mdc-content-sha-registry",
            "score fusion",
            "criterion 3",
            "criterion 2",
        ),
    ),
    (
        "R14.2",
        "the entries run one after another and each voids prior baselines",
        lambda n: ("one after another" in n or "not concurrently" in n)
        and "void" in n,
    ),
    (
        "R14.3",
        "each entry cites the phase 80 document as the authority",
        lambda n: _all(
            n,
            "phase80_default_tenant_freeze_retirement.md",
            "authority",
        ),
    ),
    (
        "R14.4",
        "the third entry relies on a gate the first two exercised",
        lambda n: _all(n, "third", "exercised", "first two"),
    ),
    (
        "R14.5",
        "DEFAULT_SEMANTIC_COLLECTION is a fourth, ungated follow-up",
        lambda n: _all(n, "default_semantic_collection", "fourth"),
    ),
    (
        "R15.7",
        "the config-level rollback available without code change or redeploy",
        lambda n: _all(
            n,
            "mcp_collection_scope_json",
            "without a code change",
            "without a redeploy",
        ),
    ),
]


def test_retirement_record_exists_and_is_ascii() -> None:
    """The Retirement_Record exists under ``docs/reports/`` and is ASCII.

    Requirement 1.10 / R15.6 constrain the whole feature to ASCII output;
    the Retirement_Record is a produced artefact and is checked on its raw
    bytes (before whitespace normalization, which would hide a non-ASCII
    character).
    """
    raw = _record_raw()
    assert raw.strip(), "the Retirement_Record is empty"
    assert raw.isascii(), (
        "the Retirement_Record contains non-ASCII characters (R1.10/R15.6)"
    )


@pytest.mark.parametrize(
    "criterion, description, predicate",
    _RECORD_CHECKS,
    ids=[c[0] for c in _RECORD_CHECKS],
)
def test_retirement_record_carries_required_element(
    criterion: str, description: str, predicate
) -> None:
    """Each named criterion's mandated element is present in the record.

    One assertion per criterion, so a failure names the missing clause
    rather than reporting that the document is short. The predicate is
    derived from the criterion; a genuinely absent element is a finding to
    report, not a reason to weaken the assertion.
    """
    n = _record_norm()
    assert predicate(n), (
        f"{criterion}: the Retirement_Record does not carry the required "
        f"element -- {description}"
    )


# ---------------------------------------------------------------------------
# Phase 79 spec amendments (R10.1-R10.4, R11.1, R11.4) and README (R13.2,
# R13.3, R13.6)
# ---------------------------------------------------------------------------


def test_phase79_requirements_record_both_supersessions() -> None:
    """R10.1/R11.1: both supersessions name this feature as authority."""
    n = _norm(_REQ79.read_text(encoding="utf-8"))
    assert n.count(_MARKER) >= 2, (
        "the Phase 79 requirements must record both the R6.2 and the R6.3 "
        "supersession naming default-tenant-freeze-retirement (R10.1, R11.1);"
        f" found {n.count(_MARKER)} marker(s)"
    )


def test_phase79_r63_criterion_carries_the_three_conditions() -> None:
    """R10.2: the R6.3 superseding text states the three R9.1 conditions."""
    n = _norm(_REQ79.read_text(encoding="utf-8"))
    conditions = (
        "set of physical_collection names each response lists is equal",
        "document count each response reports for each listed "
        "physical_collection is equal",
        "verdict each response reports for each named check is equal",
    )
    missing = [c for c in conditions if c not in n]
    assert not missing, (
        "R10.2: the R6.3 superseding criterion must carry the three "
        "Structural_Equivalence conditions as its own text; missing: "
        f"{missing}"
    )


def test_phase79_r105_restated_in_union_form_and_note_replaced() -> None:
    """R10.3: R10.5 is union-scoped and its amendment note is replaced."""
    n = _norm(_REQ79.read_text(encoding="utf-8"))
    assert (
        "union of the default_tenant's resolved_collection_sets across all "
        "five" in n
    ), "R10.3: R10.5 is not restated in the union-scoped form"
    assert (
        "resolved 2026-08-19 by `default-tenant-freeze-retirement`" in n
    ), (
        "R10.3: the R10.5 2026-08-19 amendment note is not replaced with a "
        "note naming this feature as the resolution"
    )


def test_phase79_design_restores_property8_over_any_tenant() -> None:
    """R10.4: design Property 8 holds over any Tenant, note replaced."""
    raw = _DES79.read_text(encoding="utf-8")
    start = raw.find("Property 8: Reporting agreement")
    assert start != -1, "Property 8 section not found in the Phase 79 design"
    end = raw.find("**Functions under test:**", start)
    assert end != -1, "Property 8 section end not found in the design"
    section = _norm(raw[start:end])

    # The active statement precedes the resolution note; it must be over any
    # Tenant and must no longer carry the non-empty-index_prefix narrowing.
    statement = section.split("resolved 2026-08-19")[0]
    assert "for any" in statement and "tenant" in statement, (
        "R10.4: the Property 8 statement is not stated over any Tenant"
    )
    assert "index_prefix" not in statement, (
        "R10.4: the Property 8 statement still carries the "
        "non-empty-index_prefix narrowing"
    )
    assert (
        "resolved 2026-08-19 by `default-tenant-freeze-retirement`" in section
    ), (
        "R10.4: the Property 8 2026-08-19 amendment note is not replaced with "
        "a note naming this feature"
    )


def test_baselines_readme_records_instrument_status() -> None:
    """R13.2/R13.3/R13.6: README states the instrument status and contrast."""
    n = _norm(_README.read_text(encoding="utf-8"))
    assert _all(n, "instrument", "not a standing gate"), (
        "R13.2: the README does not state the instrument-not-a-gate status"
    )
    assert "default-tenant-freeze-retirement" in n, (
        "R13.2: the README does not name this feature as the authority"
    )
    assert "4eb422915bdf2728466e6ff5df449b7a539cdede" in n, (
        "R13.3: the README does not retain the Phase 79 Reference_Revision"
    )
    assert "re-recordable from any revision" in n, (
        "R13.6: the README does not state a structural baseline is "
        "re-recordable from any revision"
    )
    assert "revision immediately preceding" in n, (
        "R13.6: the README does not state the byte-baseline "
        "revision-immediately-preceding contrast"
    )


# ---------------------------------------------------------------------------
# The staging (R8.1, R8.2, R8.3): a working-tree contract that always runs,
# and a stronger history walk while the branch is intact. Neither skips.
# ---------------------------------------------------------------------------

#: Each Phase 79 criterion superseded by this feature, keyed by the module
#: the requirements name as its enforcer, mapped to the replacement symbols
#: that must be present in the byte-equivalence test module.
_SUPERSESSIONS = {
    # R6.3 (reporting) -- enforced by tests/baselines/structural.py.
    "structural.py": ("parse_structural", "compare_structural"),
    # R6.2 (query) -- enforced by tests/baselines/addressing.py.
    "addressing.py": ("addressed_set", "check_hit_provenance"),
}


def _run_git(*args: str) -> str:
    """Run ``git`` from the repo root and return stdout, or raise.

    Parameters
    ----------
    *args
        Arguments passed to ``git`` (the ``git`` token is prepended).

    Returns
    -------
    str
        The command's standard output.

    Raises
    ------
    RuntimeError
        If ``git`` is unavailable or the command exits non-zero. This is a
        raise and not a :func:`pytest.skip`: 10.1 forbids a
        conditionally-skipped test this feature adds, so a git-dependent
        assertion that skipped when git was missing would violate the claim
        it makes. A broken git environment is a test failure here.
    """
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:  # git not on PATH
        raise RuntimeError(
            "git is not available; the staging history walk cannot skip "
            "(10.1) and treats a missing git as a broken environment"
        ) from exc
    if completed.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (exit {completed.returncode}): "
            f"{completed.stderr.strip()}"
        )
    return completed.stdout


def _is_ancestor(older: str, newer: str) -> bool:
    """Return True when ``older`` is an ancestor of ``newer``.

    Uses ``git merge-base --is-ancestor``, whose exit code is 0 for an
    ancestor and 1 otherwise; any other exit (or a missing git) is a broken
    environment and raises rather than skipping.
    """
    try:
        completed = subprocess.run(
            ["git", "merge-base", "--is-ancestor", older, newer],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:  # pragma: no cover - see _run_git
        raise RuntimeError("git is not available") from exc
    if completed.returncode not in (0, 1):
        raise RuntimeError(
            "git merge-base --is-ancestor failed "
            f"(exit {completed.returncode}): {completed.stderr.strip()}"
        )
    return completed.returncode == 0


def _repo_rel(path: Path) -> str:
    """Return ``path`` relative to the repo root as git expects it."""
    return str(path.relative_to(_REPO_ROOT))


def _introducing_commit(path: Path, symbol: str) -> str | None:
    """Return the earliest commit that introduced ``symbol`` into ``path``.

    ``git log -S`` lists, newest first, the commits that changed the number
    of occurrences of ``symbol`` in ``path``; the oldest such commit is the
    one that introduced it. Returns ``None`` when the symbol never appears in
    the file's history (for example when it is present only uncommitted).
    """
    out = _run_git(
        "log", "--format=%H", "-S", symbol, "--", _repo_rel(path)
    )
    commits = [line for line in out.splitlines() if line]
    return commits[-1] if commits else None


def _first_add_commit(path: Path) -> str | None:
    """Return the earliest commit that added ``path`` to the tree."""
    out = _run_git(
        "log", "--diff-filter=A", "--format=%H", "--", _repo_rel(path)
    )
    commits = [line for line in out.splitlines() if line]
    return commits[-1] if commits else None


def _added_lines(commit: str, path: Path) -> list[str]:
    """Return the ``+`` lines a ``commit`` added to ``path``."""
    out = _run_git("show", commit, "--", _repo_rel(path))
    return [
        line[1:]
        for line in out.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]


def _diff_adds(commit: str, path: Path, needle: str) -> bool:
    """Return True when ``commit`` added a line containing ``needle``.

    ``needle`` is matched normalized-lowercased against each added line, so
    a wrapped marker still matches.
    """
    return any(needle in _norm(line) for line in _added_lines(commit, path))


def _byte_eq_source() -> str:
    """Return the byte-equivalence test module source (working tree)."""
    return _BYTE_EQ.read_text(encoding="utf-8")


def _requirements_source() -> str:
    """Return the Phase 79 requirements source (working tree)."""
    return _REQ79.read_text(encoding="utf-8")


def _relaxed_criteria() -> dict[str, tuple[str, ...]]:
    """Return the superseded criteria whose enforcer the requirements name.

    A criterion is treated as relaxed when the Phase 79 requirements carry
    the supersession marker *and* name the module that enforces its
    replacement. That keeps the primary contract keyed on what the spec
    actually records rather than on a hardcoded assumption.
    """
    req = _norm(_requirements_source())
    if _MARKER not in req:
        return {}
    return {
        module: symbols
        for module, symbols in _SUPERSESSIONS.items()
        if module in req
    }


def test_each_relaxed_criterion_has_its_replacement_present() -> None:
    """Primary contract (R8.2/R8.3), working-tree, never skips.

    For each Phase 79 criterion the requirements record as superseded, its
    replacement check is present in the byte-equivalence test module. This
    is the always-meaningful contract: it holds whether the branch is intact
    or squash-merged, because it reads the current tree rather than history.
    A revision in which a criterion is relaxed while its replacement is
    absent fails here.
    """
    relaxed = _relaxed_criteria()
    assert relaxed, (
        "the Phase 79 requirements record no superseded criterion with a "
        "named enforcer; expected both R6.2 and R6.3 to be superseded"
    )
    source = _byte_eq_source()
    missing: list[str] = []
    for module, symbols in relaxed.items():
        for symbol in symbols:
            if symbol not in source:
                missing.append(f"{symbol} (for {module})")
    assert not missing, (
        "a Phase 79 criterion is recorded as superseded but its replacement "
        "check is absent from the byte-equivalence test module (R8.2/R8.3): "
        + ", ".join(missing)
    )


def test_supersession_ordering_and_colocation_in_history() -> None:
    """Stronger check (R8.1/R8.2/R8.3): the staged order held in history.

    While the branch is intact the two supersession commits are distinct
    from the Benchmark_Harness commit and from each other; each is identified
    by the replacement symbol it introduces into the test module, never by
    the identical supersession marker. The harness must precede both (R8.1),
    the reporting commit must also add the structural comparison (R8.2), and
    the query commit must also add the addressed-set symbols and the
    benchmark-comparison criterion (R8.3).

    After a squash merge every Phase 80 commit collapses into one, so the
    per-commit separation is no longer visible; the walk then degrades to
    the always-meaningful primary contract rather than skipping.
    """
    harness = _first_add_commit(_HARNESS)
    reporting = _introducing_commit(_BYTE_EQ, "parse_structural")
    query = _introducing_commit(_BYTE_EQ, "addressed_set")

    branch_intact = (
        harness is not None
        and reporting is not None
        and query is not None
        and reporting != harness
        and query != harness
        and reporting != query
    )

    if not branch_intact:
        # Collapsed / uncommitted history: the per-commit ordering cannot be
        # observed. Fall back to the always-meaningful working-tree contract
        # rather than skip (10.1 forbids a conditional skip).
        test_each_relaxed_criterion_has_its_replacement_present()
        return

    # R8.1 -- the Benchmark_Harness exists before either relaxation.
    assert _is_ancestor(harness, reporting), (
        "R8.1: the Benchmark_Harness commit does not precede the R6.3 "
        "(reporting) supersession commit"
    )
    assert _is_ancestor(harness, query), (
        "R8.1: the Benchmark_Harness commit does not precede the R6.2 "
        "(query) supersession commit"
    )
    # Design staging: 6.3 (reporting) lands before 8.3 (query).
    assert _is_ancestor(reporting, query), (
        "the R6.3 (reporting) supersession must precede the R6.2 (query) "
        "supersession per the staged plan"
    )

    # R8.2 -- the reporting supersession commit carries its replacement.
    assert _diff_adds(reporting, _REQ79, _MARKER), (
        "R8.2: the reporting supersession commit does not add a supersession "
        "marker to the Phase 79 requirements"
    )
    assert _diff_adds(reporting, _BYTE_EQ, "parse_structural") and _diff_adds(
        reporting, _BYTE_EQ, "compare_structural"
    ), (
        "R8.2: the reporting supersession commit does not also add the "
        "Structural_Equivalence comparison to the test module"
    )

    # R8.3 -- the query supersession commit carries both replacements.
    assert _diff_adds(query, _REQ79, _MARKER), (
        "R8.3: the query supersession commit does not add a supersession "
        "marker to the Phase 79 requirements"
    )
    assert _diff_adds(query, _REQ79, "benchmark comparison"), (
        "R8.3: the query supersession commit does not add the benchmark "
        "comparison to the Phase 79 requirements"
    )
    assert _diff_adds(query, _BYTE_EQ, "addressed_set") and _diff_adds(
        query, _BYTE_EQ, "check_hit_provenance"
    ), (
        "R8.3: the query supersession commit does not also add the "
        "addressed-set and provenance checks to the test module"
    )
