"""No-runtime-change gate for default-tenant-freeze-retirement (Task 10.1).

This module proves the claim Requirement 15 makes about the whole
feature: retiring the Phase 79 byte-freeze changed no runtime behaviour.
It carries four kinds of assertion, one per criterion it validates.

R15.3 -- nothing under ``mcp_server_python/src/`` changed
--------------------------------------------------------
The task text asks only that ``git diff --stat mcp_server_python/src/``
return empty, which proves nothing under ``src/`` is *uncommitted*. The
requirement's claim is stronger: this feature changed nothing under
``src/`` *at all*, which is a statement about the whole phase, not the
working tree. Phase 80's base revision is ``c5b2ea7`` (the commit before
``8516da5 docs(sdd): Phase 80``). So this module asserts the committed
range ``c5b2ea7..HEAD`` as well as the working tree -- together they say
what the requirement means. Either one alone is a weaker claim than R15.3
makes.

**Amended 2026-08-26 -- one named exception.** R15.3 now admits exactly
three ``src/`` files, the ones that carried Neo4j-APOC calls Amazon
Neptune cannot execute (see :data:`_APOC_REMEDIATION_FILES` for the full
reasoning). Both halves above became set comparisons against that
allowlist rather than emptiness checks, so any *other* ``src/`` file in
the diff still fails. A third assertion was added in the same change:
that no ``apoc.`` call survives anywhere under ``src/`` -- the allowlist
permits the edit, and that assertion pins that the edit achieved its
purpose rather than merely touching the files. The exception is recorded
in the requirement itself, not only here.

R15.1 / R15.2 -- src imports no harness, harness registers no served tool
-------------------------------------------------------------------------
Both are close to *vacuously true by construction*. The Benchmark_Harness
lives under ``scripts/`` and the two comparison modules
(``tests/baselines/structural.py`` and ``tests/baselines/addressing.py``)
were deliberately placed under ``tests/`` rather than ``src/`` (Design
Decision 3). A passing assertion here is therefore not evidence of much
-- it is the tripwire that fires only if a future change moves any of
those into ``src/`` or wires the harness into the served server, which is
the single way either could ever fail. Asserted anyway for exactly that
reason; nobody should read a green result as more than that.

R15.5 -- markers and no conditional skip
----------------------------------------
The tests this feature adds carry only the ``unit``, ``property``, and
``parity`` markers, and none is conditionally skipped on credentials or
backend availability. ``--strict-markers`` (already on) turns a *typo'd*
marker into a collection error, so the marker meta-test earns its place
only against a *well-intentioned new registration* -- someone adding, say,
``benchmark`` to ``pyproject.toml`` and marking the harness tests with it.
That is the case it defends against.

The skip assertion is scoped, per the design's Testing Strategy, to skips
conditioned on *credentials or backend availability* -- the axis the
hermetic constraint removes. It deliberately does not flag a
tool-availability skip (the ``pytest.skip("bash not available ...")`` in
``test_benchmark_wrapper_integration.py``, which is on a different axis and
does not fire in a POSIX environment; the suite reports zero skips). See
the module report for the one place the literal "no conditionally-skipped
test" reading and that landed prior-step skip diverge.

This module cannot skip, and that constraint bites itself: a git-dependent
assertion that reached for ``pytest.skip`` when ``git`` or the base
revision would not resolve would violate the very no-skip claim it is
making. So the git helper here fails loudly instead -- a broken git
environment is a test failure, not a skip.

default-tenant-freeze-retirement Requirements: 15.1, 15.2, 15.3, 15.5.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Repository anchors
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MCP_PYTHON_DIR = _REPO_ROOT / "mcp_server_python"
_SRC_DIR = _MCP_PYTHON_DIR / "src"
_TESTS_DIR = _MCP_PYTHON_DIR / "tests"
_SCRIPTS_DIR = _MCP_PYTHON_DIR / "scripts"

#: Phase 80's base revision -- the commit immediately before
#: ``8516da5 docs(sdd): Phase 80``. The committed diff over
#: ``c5b2ea7..HEAD`` is the range the R15.3 claim is actually about.
_BASE_REVISION = "c5b2ea7"

#: The ``src/``-relative path (as git reports it) that must show no change.
_SRC_PATHSPEC = "mcp_server_python/src/"

#: The ONLY ``src/`` files this feature is permitted to modify, and the reason.
#:
#: Requirement 15 criterion 3 was amended on 2026-08-26 to admit one named
#: exception: the removal of four Neo4j-APOC call sites that cannot execute
#: against Amazon Neptune. ``apoc.convert.toList`` and ``apoc.text.join`` are
#: functions of the APOC *server plugin*; Neptune has no plugin mechanism and
#: no APOC, so every query carrying them returned
#: ``400 Unknown function: 'toList'`` -- a deterministic failure on the
#: platform this server actually runs on. The predicate is now
#: ``toLower(toString(n.name)) CONTAINS toLower($x)``, verified against live
#: Neptune before the edit.
#:
#: The defect is *pre-existing* (identical APOC reference counts at the Phase
#: 80 base ``c5b2ea7``, at the branch merge-base ``48a3d987``, and at HEAD;
#: introduced by ``0dac1e0``, Phases 60/61). It is admitted here rather than
#: deferred because the first live benchmark run showed it is the direct cause
#: of five zero-scoring cases and of every GGSR enrichment failure, so the
#: replacement gate this feature exists to build cannot be calibrated while it
#: stands.
#:
#: This is an allowlist of exactly three paths, not a widening of the
#: assertion: any *other* ``src/`` file appearing in the diff still fails.
#: Keeping it a named set is the whole point -- a blanket exemption would
#: retire the gate instead of recording an exception to it.
_APOC_REMEDIATION_FILES = frozenset({
    "mcp_server_python/src/tools/semantic_search.py",
    "mcp_server_python/src/tools/graph_rag.py",
    "mcp_server_python/src/graphrag/ggsr_traversal.py",
})

#: The Benchmark_Harness module basename. R15.1 forbids any ``src/`` module
#: importing it; the harness lives under ``scripts/``, not ``src/``.
_HARNESS_MODULE = "run_benchmark"

#: The registered marker set (``pyproject.toml``), against which R15.5 checks
#: the markers the feature's added tests carry.
_REGISTERED_MARKERS = frozenset({"unit", "property", "parity"})

#: pytest / pytest-asyncio built-in marks. These are always available and are
#: not "carried" test-categorization markers in the R15.5 sense, so they are
#: excluded before the subset assertion. ``skip`` / ``skipif`` are handled by
#: the dedicated skip assertion below, not here.
_BUILTIN_MARKS = frozenset({
    "parametrize",
    "skip",
    "skipif",
    "xfail",
    "usefixtures",
    "filterwarnings",
    "tryfirst",
    "trylast",
    "asyncio",
})

#: Lowercase substrings that mark a skip as being conditioned on credentials
#: or backend availability -- the axis R15.5 (per the design) forbids. A skip
#: on some other axis (a shell interpreter, say) is out of this scope by the
#: requirement's own wording.
_CREDENTIAL_BACKEND_KEYWORDS = (
    "credential",
    "aws",
    "opensearch",
    "neptune",
    "bedrock",
    "chromadb",
    "neo4j",
    "db_backend",
    "backend",
    "endpoint",
    "boto3",
)


# ---------------------------------------------------------------------------
# git helper -- fails loudly, never skips
# ---------------------------------------------------------------------------


def _run_git(*args: str) -> str:
    """Run ``git`` from the repo root and return stdout, or raise.

    Parameters
    ----------
    *args
        Arguments passed to ``git`` (the ``git`` token itself is prepended).

    Returns
    -------
    str
        The command's standard output.

    Raises
    ------
    RuntimeError
        If ``git`` is unavailable or the command exits non-zero. This is
        deliberately a raise and not a :func:`pytest.skip`: R15.5 forbids a
        conditionally-skipped test, so a git-dependent assertion that skipped
        when git was missing would violate the claim it is making. A broken
        git environment is a test failure here, not a skip.
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
            "git is not available; this no-runtime-change gate cannot skip "
            "(R15.5) and treats a missing git as a broken environment"
        ) from exc
    if completed.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (exit {completed.returncode}): "
            f"{completed.stderr.strip()}"
        )
    return completed.stdout


# ---------------------------------------------------------------------------
# Feature-file enumeration -- files present now, absent at the base revision
# ---------------------------------------------------------------------------


def _base_tests_files() -> set[str]:
    """Return the repo-relative test-tree files present at ``c5b2ea7``."""
    out = _run_git(
        "ls-tree", "-r", "--name-only", _BASE_REVISION,
        "--", "mcp_server_python/tests/",
    )
    return {line for line in out.splitlines() if line}


def _current_tests_py_files() -> set[str]:
    """Return repo-relative ``.py`` files under ``tests/`` on disk now.

    Uses the on-disk tree rather than a git listing so an uncommitted new
    test module -- including this one -- is included. ``__pycache__`` and
    compiled bytecode are excluded.
    """
    found: set[str] = set()
    for path in _TESTS_DIR.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        found.add(str(path.relative_to(_REPO_ROOT)))
    return found


def _feature_added_py_files() -> list[Path]:
    """Return the ``.py`` test-tree files this feature adds, as paths.

    "Adds" means present now and absent at the Phase 80 base revision, so
    files this feature only *modified* (for example ``conftest.py`` or
    ``test_default_tenant_byte_equivalence.py``) are excluded -- R15.5 is
    about the tests this feature *adds*.
    """
    base = _base_tests_files()
    current = _current_tests_py_files()
    added_rel = sorted(current - base)
    return [_REPO_ROOT / rel for rel in added_rel]


def _custom_markers_in(source: str) -> set[str]:
    """Return the custom ``pytest.mark.<name>`` marker names in ``source``.

    Collected from the AST (``pytest.mark.<name>`` attribute access, whether
    bare, called, or assigned to ``pytestmark``) rather than by substring, so
    a marker named in a docstring or comment is not counted. pytest / asyncio
    built-in marks are excluded.
    """
    names: set[str] = set()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        parent = node.value
        if (
            isinstance(parent, ast.Attribute)
            and parent.attr == "mark"
            and isinstance(parent.value, ast.Name)
            and parent.value.id == "pytest"
        ):
            if node.attr not in _BUILTIN_MARKS:
                names.add(node.attr)
    return names


def _string_args_and_keywords(call: ast.Call) -> list[str]:
    """Return the string-literal reason text carried by a call.

    Gathers positional string constants and any ``reason=`` string, plus the
    unparsed first positional (a ``skipif`` condition) so a condition that
    names a credential/backend source is visible to the keyword scan.
    """
    texts: list[str] = []
    for arg in call.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            texts.append(arg.value)
    for kw in call.keywords:
        if (
            kw.arg == "reason"
            and isinstance(kw.value, ast.Constant)
            and isinstance(kw.value.value, str)
        ):
            texts.append(kw.value.value)
    if call.args:
        try:
            texts.append(ast.unparse(call.args[0]))
        except Exception:  # pragma: no cover - unparse is total on 3.12
            pass
    return texts


def _credential_backend_skips_in(source: str) -> list[str]:
    """Return descriptions of credential/backend-conditioned skips.

    A finding for each ``pytest.importorskip(...)`` (a dependency/backend
    availability skip by nature) and each ``pytest.skip`` /
    ``@pytest.mark.skipif`` / ``@pytest.mark.skip`` whose reason text or
    condition names a credential or backend source. Skips on any other axis
    are out of scope by R15.5's wording and are not reported.
    """
    findings: list[str] = []
    tree = ast.parse(source)

    def _is_pytest_attr(func: ast.expr, *, tail: str) -> bool:
        # pytest.<tail>
        if (
            isinstance(func, ast.Attribute)
            and func.attr == tail
            and isinstance(func.value, ast.Name)
            and func.value.id == "pytest"
        ):
            return True
        return False

    def _is_pytest_mark_attr(func: ast.expr, *, tail: str) -> bool:
        # pytest.mark.<tail>
        return (
            isinstance(func, ast.Attribute)
            and func.attr == tail
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "mark"
            and isinstance(func.value.value, ast.Name)
            and func.value.value.id == "pytest"
        )

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if _is_pytest_attr(func, tail="importorskip"):
            findings.append("pytest.importorskip(...)")
            continue
        is_skip = _is_pytest_attr(func, tail="skip") or _is_pytest_mark_attr(
            func, tail="skip"
        )
        is_skipif = _is_pytest_mark_attr(func, tail="skipif")
        if not (is_skip or is_skipif):
            continue
        blob = " ".join(_string_args_and_keywords(node)).lower()
        if any(kw in blob for kw in _CREDENTIAL_BACKEND_KEYWORDS):
            kind = "pytest.mark.skipif" if is_skipif else "pytest.skip"
            findings.append(f"{kind} conditioned on credentials/backend")
    return findings


def _any_skip_construct_in(source: str) -> bool:
    """Return True if ``source`` uses any pytest skip construct at all.

    Used only for this module's self-guard -- the git-dependent assertions
    here must never reach for a skip.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr in {"skip", "importorskip"}
                and isinstance(func.value, ast.Name)
                and func.value.id == "pytest"
            ):
                return True
        if isinstance(node, ast.Attribute) and node.attr in {"skip", "skipif"}:
            parent = node.value
            if (
                isinstance(parent, ast.Attribute)
                and parent.attr == "mark"
                and isinstance(parent.value, ast.Name)
                and parent.value.id == "pytest"
            ):
                return True
    return False


def _src_py_files() -> list[Path]:
    """Return every ``.py`` file under ``mcp_server_python/src/``."""
    return [
        p for p in _SRC_DIR.rglob("*.py") if "__pycache__" not in p.parts
    ]


def _apoc_call_lines(source: str) -> list[int]:
    """Return line numbers of string literals containing an APOC *call*.

    A plain ``"apoc." in text`` scan over the file is wrong, and was caught
    being wrong by this module's own first run: the docstring in
    ``ggsr_traversal.py`` that *explains why APOC was removed* names
    ``apoc.text.join`` and ``apoc.convert.toList`` in prose, and a
    substring scan flags that as a surviving call. Documenting a removal
    must not read as the thing being removed.

    So the scan is AST-based and looks only at string constants that are
    **not** docstrings -- a query lives in a non-docstring literal, while
    an explanation of a query lives in a docstring. Docstring nodes are
    identified by their exact object identity, taken from
    :func:`ast.get_docstring` over the module and every class and function
    in it, which avoids guessing from position.
    """
    tree = ast.parse(source)

    docstring_nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node,
            (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            body = getattr(node, "body", None)
            if not body:
                continue
            first = body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                docstring_nodes.add(id(first.value))

    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant):
            continue
        if not isinstance(node.value, str):
            continue
        if id(node) in docstring_nodes:
            continue
        if "apoc." in node.value:
            lines.append(node.lineno)
    return sorted(set(lines))


def _imports_harness(source: str) -> bool:
    """Return True if ``source`` imports the Benchmark_Harness module."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _HARNESS_MODULE in alias.name.split("."):
                    return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if _HARNESS_MODULE in module.split("."):
                return True
            for alias in node.names:
                if alias.name == _HARNESS_MODULE:
                    return True
    return False


# ---------------------------------------------------------------------------
# R15.3 -- the src/ tree is unchanged, working tree and committed range
# ---------------------------------------------------------------------------


class TestSrcTreeUnchanged:
    """R15.3: this feature changed nothing under ``src/`` -- at all."""

    def test_base_revision_resolves(self):
        """The range assertion is meaningful only if ``c5b2ea7`` resolves.

        Fails loudly (never skips) when the base revision cannot be found,
        because a range diff against a missing base would otherwise pass
        vacuously.
        """
        out = _run_git(
            "rev-parse", "--verify", f"{_BASE_REVISION}^{{commit}}"
        )
        assert out.strip(), (
            f"Phase 80 base revision {_BASE_REVISION} did not resolve"
        )

    def test_src_has_no_unexpected_uncommitted_change(self):
        """R15.3, working-tree half: only the APOC-remediation files differ.

        Uses ``--name-only`` rather than ``--stat`` so the comparison is a
        set of paths, not formatted text. Any ``src/`` file outside
        :data:`_APOC_REMEDIATION_FILES` still fails.
        """
        out = _run_git("diff", "--name-only", "--", _SRC_PATHSPEC)
        changed = {line for line in out.splitlines() if line.strip()}
        unexpected = sorted(changed - _APOC_REMEDIATION_FILES)
        assert not unexpected, (
            "mcp_server_python/src/ has uncommitted changes outside the "
            "named APOC-remediation allowlist; this feature changes no other "
            "runtime behaviour (R15.3 as amended 2026-08-26): "
            + ", ".join(unexpected)
        )

    def test_src_unchanged_across_the_phase_range(self):
        """R15.3, range half: ``c5b2ea7..HEAD`` touches only the allowlist.

        The working-tree check alone proves only that ``src/`` is not
        *uncommitted*; this proves the whole phase changed nothing there
        beyond the named exception, which is the statement R15.3 makes as
        amended.
        """
        out = _run_git(
            "diff", "--name-only", _BASE_REVISION, "HEAD", "--", _SRC_PATHSPEC
        )
        changed = {line for line in out.splitlines() if line.strip()}
        unexpected = sorted(changed - _APOC_REMEDIATION_FILES)
        assert not unexpected, (
            "the committed range c5b2ea7..HEAD modifies mcp_server_python/"
            "src/ outside the named APOC-remediation allowlist (R15.3 as "
            "amended 2026-08-26): " + ", ".join(unexpected)
        )

    def test_no_apoc_call_survives_under_src(self):
        """The APOC remediation is complete: no ``apoc.`` call under ``src/``.

        The allowlist above permits three files to change; this asserts the
        change actually achieved its purpose. Without it the allowlist would
        permit an edit that left an APOC call in place, which is the failure
        mode the exception exists to remove -- an ``apoc.*`` call is a
        deterministic ``400`` against Neptune, not a latent risk.
        """
        offenders: list[str] = []
        for path in _src_py_files():
            for lineno in _apoc_call_lines(path.read_text(encoding="utf-8")):
                offenders.append(f"{path.relative_to(_REPO_ROOT)}:{lineno}")
        assert not offenders, (
            "an APOC call survives under src/; Amazon Neptune has no APOC "
            "plugin, so each of these is a deterministic 400 Unknown "
            "function: " + ", ".join(offenders)
        )


# ---------------------------------------------------------------------------
# R15.1 / R15.2 -- no coupling between src/ and the harness
# ---------------------------------------------------------------------------


class TestNoHarnessCoupling:
    """R15.1 / R15.2: src/ imports no harness; harness serves no tool.

    Both assertions are vacuously true today (Design Decision 3 keeps the
    harness under ``scripts/`` and the evaluators under ``tests/``). They
    exist as the tripwire for a future move into ``src/`` -- see the module
    docstring.
    """

    def test_src_does_not_import_the_benchmark_harness(self):
        """R15.1: no module under ``src/`` imports ``run_benchmark``."""
        offenders = [
            str(p.relative_to(_REPO_ROOT))
            for p in _src_py_files()
            if _imports_harness(p.read_text(encoding="utf-8"))
        ]
        assert not offenders, (
            "a module under src/ imports the Benchmark_Harness (R15.1): "
            + ", ".join(offenders)
        )

    def test_harness_registers_no_tool_on_the_served_server(self):
        """R15.2: the harness collects closures via its own ``_ToolShim``.

        A live tool-count check needs a running server and a backend, so it
        is operator-gated. The hermetic stand-in is structural: the harness
        registers only against ``_ToolShim`` (never a ``FastMCP`` it
        imports), and ``src/mcp_server.py`` -- which builds the served
        instance -- neither imports nor names the harness. If both hold, the
        harness cannot register on the served instance, so the reported tool
        count is unchanged.
        """
        harness_path = _SCRIPTS_DIR / "run_benchmark.py"
        assert harness_path.is_file(), (
            "the Benchmark_Harness must exist by this step"
        )
        harness_src = harness_path.read_text(encoding="utf-8")
        harness_tree = ast.parse(harness_src)

        assert "_ToolShim" in harness_src, (
            "the harness must collect closures through its own _ToolShim "
            "stand-in (R15.2)"
        )

        imports_fastmcp = False
        imports_served_server = False
        for node in ast.walk(harness_tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "fastmcp":
                        imports_fastmcp = True
                    if alias.name == "src.mcp_server":
                        imports_served_server = True
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.split(".")[0] == "fastmcp":
                    imports_fastmcp = True
                if module == "src.mcp_server" or module == "src":
                    for alias in node.names:
                        if alias.name == "mcp_server":
                            imports_served_server = True
        assert not imports_fastmcp, (
            "the harness imports fastmcp; it must register only against its "
            "own _ToolShim so it cannot touch the served instance (R15.2)"
        )
        assert not imports_served_server, (
            "the harness imports the served server module (R15.2)"
        )

        server_path = _SRC_DIR / "mcp_server.py"
        server_src = server_path.read_text(encoding="utf-8")
        assert not _imports_harness(server_src), (
            "src/mcp_server.py imports the Benchmark_Harness (R15.2)"
        )


# ---------------------------------------------------------------------------
# R15.5 -- markers and no conditional skip in the feature's added tests
# ---------------------------------------------------------------------------


class TestMarkerAndSkipDiscipline:
    """R15.5: the feature's added tests carry only registered markers and
    are not conditionally skipped on credentials or backend availability.
    """

    def test_feature_adds_test_files(self):
        """Guard: the enumeration is non-empty.

        A subset assertion over an empty set passes vacuously, which would
        let a broken enumeration hide a real marker regression. This feature
        demonstrably adds test files, so an empty set is itself a defect.
        """
        added = _feature_added_py_files()
        assert added, (
            "no feature-added test files were found; the enumeration against "
            f"{_BASE_REVISION} is broken"
        )

    def test_added_tests_carry_only_registered_markers(self):
        """R15.5: custom markers used by added tests are a subset of the
        three registered names.

        ``--strict-markers`` already fails a typo'd marker at collection, so
        this defends against the case that survives collection: a
        well-intentioned new registration in ``pyproject.toml`` used by these
        tests.
        """
        used: set[str] = set()
        for path in _feature_added_py_files():
            used |= _custom_markers_in(path.read_text(encoding="utf-8"))
        extra = used - _REGISTERED_MARKERS
        assert not extra, (
            "the feature's added tests carry marker(s) outside "
            f"{sorted(_REGISTERED_MARKERS)} (R15.5): {sorted(extra)}"
        )

    def test_added_tests_do_not_skip_on_credentials_or_backend(self):
        """R15.5: no added test is conditionally skipped on credentials or
        backend availability.

        Scoped, per the design's Testing Strategy, to that axis -- the one
        the hermetic constraint removes ("there is nothing to skip for"). A
        skip on a different axis (for example a shell interpreter) is out of
        scope by the requirement's wording and is not reported here.
        """
        findings: list[str] = []
        for path in _feature_added_py_files():
            source = path.read_text(encoding="utf-8")
            for finding in _credential_backend_skips_in(source):
                findings.append(
                    f"{path.relative_to(_REPO_ROOT)}: {finding}"
                )
        assert not findings, (
            "an added test is conditionally skipped on credentials/backend "
            "availability (R15.5): " + "; ".join(findings)
        )

    def test_this_module_never_skips(self):
        """Self-guard: this git-dependent module uses no skip construct.

        The one thing R15.5 forbids is the defensive reflex a git-dependent
        test invites -- skipping when git or the base revision will not
        resolve. This module fails loudly instead, and this assertion pins
        that it contains no ``pytest.skip`` / ``skipif`` / ``importorskip``.
        """
        source = Path(__file__).read_text(encoding="utf-8")
        assert not _any_skip_construct_in(source), (
            "this module must not use any pytest skip construct (R15.5)"
        )
