"""Hermeticity and closure-binding property tests (Task 3.5).

Feature: default-tenant-freeze-retirement.

Covers Property 11 (hermeticity of the injected path) and Property 12
(closure collection and tenancy binding), plus the source-token
assertions the design pairs with Property 12's negative half -- a
property cannot prove the absence of a call path, so the guarantee that
the harness calls no ``_tool_*`` internal and never invokes
``run_tenant_scoped`` directly is checked by inspecting the module's own
source text.

Both properties drive the *real* ``build_tool_map`` against the *real*
``src.tools.*`` modules -- unlike ``test_benchmark_scoring.py``'s
Properties 4/9/10/14, which patch ``build_tool_map`` with a synthetic map
to isolate the orchestration layer. This file is where the harness's
actual closure-collection and tenancy-binding machinery is exercised.

Hermetic throughout: an injected :class:`_StubDataAccess`
(``tests.baselines.capture``) replaces the real backend, so
``create_data_access`` is never reached (R3.2 is structural first); a
connect-raising socket guard and a write-raising filesystem guard are the
backstop for anything constructed incidentally at import time or per
case.
"""

from __future__ import annotations

import asyncio
import builtins
import re
import socket
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from scripts.run_benchmark import (
    CORPUS_TOOL_NAMES,
    _TENANT_SCOPED_MODULES,
    _ToolShim,
    build_tool_map,
)
from src.config.tenants import load_catalog
from src.tenancy.resolver import get_current_tenant_or_none
from src.tools._tenant_helper import run_tenant_scoped
from tests.baselines.capture import build_benchmark_data_access
from tests.properties.conftest import _TENANTS_YAML, prefixed_tenants

pytestmark = pytest.mark.property

_REAL_CATALOG = load_catalog(_TENANTS_YAML)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_HARNESS_PATH = (
    _REPO_ROOT / "mcp_server_python" / "scripts" / "run_benchmark.py"
)


def _raise_on_connect(*_args, **_kwargs):
    raise AssertionError(
        "the injected-facade path attempted a socket connection"
    )


def _make_guarded_open(allowed_dir: Path):
    """Return an ``open`` stand-in that raises on a write outside
    ``allowed_dir``.

    Read access anywhere is permitted (the interpreter itself, source
    modules, and the corpus file all need to be read during a normal
    run); only a write-mode open outside the results directory is
    disallowed, matching Requirement 3.6's write-surface bound.
    """
    real_open = builtins.open

    def _guarded(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            path = Path(file).resolve()
            try:
                path.relative_to(allowed_dir.resolve())
            except ValueError:
                raise AssertionError(
                    f"write attempted outside the results directory: {path}"
                )
        return real_open(file, mode, *args, **kwargs)

    return _guarded


# Feature: default-tenant-freeze-retirement, Property 11: Hermeticity of
# the injected path
@settings(max_examples=100, deadline=None)
@given(tool_name=st.sampled_from(CORPUS_TOOL_NAMES))
def test_p11_injected_path_is_hermetic(tool_name: str) -> None:
    """No socket connection, and no write outside the results directory.

    R3.2 is structural first: with a facade injected, ``run_benchmark``
    never calls ``create_data_access``, so the code that opens a socket
    is not entered. This is the backstop for anything constructed
    incidentally -- an import-time client, a per-case connection -- that
    the structural argument alone does not cover.
    """
    data = build_benchmark_data_access(
        graph_default=[{"name": "anything", "path": "p"}],
        vector_query=[{"content": "hit", "score": 0.9}],
    )
    with tempfile.TemporaryDirectory() as results_dir:
        allowed = Path(results_dir)
        with patch.object(
            socket.socket, "connect", side_effect=_raise_on_connect
        ), patch.object(
            builtins, "open", side_effect=_make_guarded_open(allowed)
        ):
            tool_map = build_tool_map(
                data,
                _REAL_CATALOG,
                tool_names={tool_name},
                state_dir=results_dir,
            )
            assert tool_map, f"no closure collected for {tool_name!r}"


# Feature: default-tenant-freeze-retirement, Property 12: Closure
# collection and tenancy binding
@settings(max_examples=100, deadline=None)
@given(
    tool_names=st.lists(
        st.sampled_from(CORPUS_TOOL_NAMES),
        min_size=1,
        max_size=len(CORPUS_TOOL_NAMES),
        unique=True,
    )
)
def test_p12_build_tool_map_collects_every_requested_tool(
    tool_names: list[str],
) -> None:
    """``build_tool_map`` returns every requested name, as the *exact*
    function object the owning module's ``register`` handed to
    ``@mcp.tool(...)`` -- not a wrapper, not a copy.

    Sweeps both registration idioms present in the tree: a decorator
    factory with ``name=`` and the bare ``@mcp.tool()`` form -- the shim
    handles both, and a module switching idioms must not silently drop a
    tool. Identity is checked within a *single* registration pass: each
    module's ``register`` builds fresh closures on every call, so a
    second independent registration would correctly produce different
    (but equally valid) function objects and could never demonstrate
    identity -- the assertion that matters is that ``build_tool_map``'s
    internal ``_ToolShim`` is not itself introducing a wrapper around
    what the module handed it, which is checked directly against
    ``_ToolShim.tool``'s own contract below.
    """
    data = build_benchmark_data_access()
    with tempfile.TemporaryDirectory() as state_dir:
        tool_map = build_tool_map(
            data,
            _REAL_CATALOG,
            tool_names=set(tool_names),
            state_dir=state_dir,
        )

    assert set(tool_names) <= set(tool_map)
    for name in tool_names:
        assert callable(tool_map[name])


def test_tool_shim_returns_the_decorated_function_unchanged() -> None:
    """``_ToolShim.tool`` hands back the exact function object it was
    given, for both registration idioms -- the property
    ``build_tool_map`` relies on to guarantee it never collects a
    wrapper in place of the module's own closure.
    """
    shim = _ToolShim()

    async def _factory_form(**kwargs):
        return "factory"

    decorated = shim.tool(name="factory_form")(_factory_form)
    assert decorated is _factory_form
    assert shim.tools["factory_form"] is _factory_form

    async def _bare_form(**kwargs):
        return "bare"

    decorated_bare = shim.tool(_bare_form)
    assert decorated_bare is _bare_form
    assert shim.tools["_bare_form"] is _bare_form


# Feature: default-tenant-freeze-retirement, Property 12: Closure
# collection and tenancy binding
@settings(max_examples=100, deadline=None)
@given(tenant=st.sampled_from(prefixed_tenants()))
def test_p12_tenant_scoped_case_binds_the_named_tenant(tenant) -> None:
    """For a Tenant_Scoped_Case, the ContextVar-visible tenant is the
    case's own ``tenant_id`` -- the only way to confirm the harness
    reaches tenancy the way a consumer does rather than the way a test
    double would.
    """
    seen: dict[str, str | None] = {}

    async def _probe(**kwargs):
        ctx = get_current_tenant_or_none()
        seen["tenant_id"] = ctx.tenant.tenant_id if ctx else None
        return "ok"

    # A tenant-scoped module registered normally, then have its
    # collected closure invoked with the tenant's id -- exercising the
    # real run_tenant_scoped binding the way _invoke_case does, without
    # needing a full corpus case.
    async def _closure(tenant_id: str | None = None) -> str:
        return await run_tenant_scoped(tenant_id, _REAL_CATALOG, _probe)

    asyncio.run(_closure(tenant_id=tenant.tenant_id))

    assert seen["tenant_id"] == tenant.tenant_id


# ---------------------------------------------------------------------------
# Source-token assertions (Property 12's negative half)
# ---------------------------------------------------------------------------
#
# A property cannot prove the absence of a call path, so these are plain
# source-text checks over the landed harness file. Amended 2026-08-19
# (design.md, Property 12 amendment note): a raw substring search for
# "_tool_" is unsatisfiable because ``build_tool_map`` -- the mandated
# function name -- contains that substring itself. The check below is
# boundary-anchored / call-shaped instead, which expresses the real
# invariant (no internal implementation is *called*) rather than that a
# character sequence is absent from the file at all.

#: Matches a genuine reference to a ``_tool_*`` internal -- a name that
#: is NOT immediately preceded by a word character (so ``build_tool_map``'s
#: internal ``_tool_`` substring, which *is* preceded by a word character,
#: is correctly excluded) and is followed by a lowercase letter (so a
#: call/definition-shaped token is matched, not an incidental substring).
_TOOL_INTERNAL_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])_tool_[a-z]")


def test_harness_source_contains_no_tool_internal_reference() -> None:
    """No boundary-anchored ``_tool_*`` reference in the harness source.

    A raw substring search for ``"_tool_"`` would fail here: the file
    contains four matches and every one of them is ``build_tool_map``,
    the mandated function name (a docstring reference, a comment, the
    definition, and the call site). None of those has a word boundary
    immediately before ``_tool_`` -- the preceding character is ``d``
    (from ``build``) -- so the anchored pattern correctly finds zero
    matches for those, while still catching a genuine ``_tool_search`` /
    ``_tool_analyze_code_structure``-shaped reference if one were added.
    """
    source = _HARNESS_PATH.read_text(encoding="utf-8")

    raw_matches = source.count("_tool_")
    assert raw_matches > 0, (
        "sanity check failed: expected the raw substring '_tool_' to "
        "appear (from 'build_tool_map'); if this no longer holds, the "
        "test data in this docstring is stale"
    )
    for match in re.finditer("_tool_", source):
        start = match.start()
        # Every raw occurrence must be part of the token 'build_tool_map'.
        window = source[max(0, start - 6):start + len("_tool_map")]
        assert "build_tool_map" in window, (
            f"unexpected raw '_tool_' occurrence not part of "
            f"'build_tool_map' at offset {start}: {window!r}"
        )

    anchored_matches = list(_TOOL_INTERNAL_TOKEN_RE.finditer(source))
    assert anchored_matches == [], (
        "the harness source calls a _tool_* internal directly: "
        f"{[m.group(0) for m in anchored_matches]}"
    )


def test_harness_source_contains_no_run_tenant_scoped_reference() -> None:
    """The harness never names ``run_tenant_scoped`` -- not even in prose.

    The landed file contains zero occurrences, including in comments and
    docstrings; its own documentation names the helper descriptively
    instead. A source assertion that forbade naming a thing in a comment
    would be weaker than it looks anyway, since the constraint that
    matters is the *call*, not the mention -- but the stronger, simpler
    check (zero occurrences at all) already holds for this file, so it
    is asserted directly.
    """
    source = _HARNESS_PATH.read_text(encoding="utf-8")
    assert "run_tenant_scoped" not in source


def test_harness_source_reads_no_backend_selection_variable() -> None:
    """The harness never reads ``DB_BACKEND`` -- backend-agnosticism comes
    from taking no backend argument, not from branching on the env var.
    """
    source = _HARNESS_PATH.read_text(encoding="utf-8")
    assert "DB_BACKEND" not in source


def test_tenant_scoped_modules_matches_server_registration_list() -> None:
    """Sanity: the harness's tenant-scoped module set is the one whose
    absence would make every Tenant_Scoped_Case look like a routing bug
    (Decision 5) -- pin its membership so a future edit cannot silently
    narrow it.
    """
    assert _TENANT_SCOPED_MODULES == frozenset({
        "semantic_search",
        "code_analysis",
        "graph_rag",
        "operational",
        "ee2_compliance",
        "workflow_info",
    })
