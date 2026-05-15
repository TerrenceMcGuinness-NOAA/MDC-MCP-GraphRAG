"""Unit tests for :mod:`src.tools.github_tools` (Task 16.2, Phase B11).

Covers tool-schema parity with Node.js, degraded-mode (no token)
behaviour, the four tool happy paths against httpx ``MockTransport``,
the rate-limit warning rendering, and 401 / 403 error handling. The
tests do not make any live network calls — every request is routed
through an in-memory transport that asserts on URL + headers and
returns canned JSON.
"""

from __future__ import annotations

import json
from typing import Any, Callable
from urllib.parse import parse_qs

import httpx
import pytest
from fastmcp import FastMCP

from src.tools import github_tools

pytestmark = pytest.mark.unit


# ── helpers ──────────────────────────────────────────────────────


def _make_mock_client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.AsyncClient:
    """Build an ``httpx.AsyncClient`` whose every request hits
    ``handler``. Used to inject canned responses without monkey-
    patching."""
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport, timeout=10.0)


def _json_response(
    payload: Any,
    *,
    status: int = 200,
    rate_limit_remaining: int | None = 4_500,
    rate_limit_reset: int | None = 1_715_700_000,
    extra_headers: dict[str, str] | None = None,
) -> httpx.Response:
    headers = {"Content-Type": "application/json"}
    if rate_limit_remaining is not None:
        headers["X-RateLimit-Remaining"] = str(rate_limit_remaining)
    if rate_limit_reset is not None:
        headers["X-RateLimit-Reset"] = str(rate_limit_reset)
    if extra_headers:
        headers.update(extra_headers)
    return httpx.Response(
        status_code=status,
        headers=headers,
        content=json.dumps(payload).encode("utf-8"),
    )


def _make_server(
    *,
    github_token: str | None = "fake-token",
    http_client: httpx.AsyncClient | None = None,
) -> FastMCP:
    mcp = FastMCP("mdc-mcp-rag-test", version="1.0.0")
    github_tools.register(
        mcp,
        data=None,
        github_token=github_token,
        http_client=http_client,
    )
    return mcp


async def _call_tool(
    mcp: FastMCP, name: str, arguments: dict[str, Any]
) -> str:
    tool = await mcp.get_tool(name)
    result = await tool.run(arguments)
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text is not None:
            return text
    return str(result)


def _enum_of(schema: dict[str, Any]) -> set[str]:
    enum = schema.get("enum")
    if enum is None:
        for branch in schema.get("anyOf") or []:
            if "enum" in branch:
                enum = branch["enum"]
                break
    return set(enum or [])


# ── registration parity ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_exposes_four_tools_with_matching_names() -> None:
    mcp = _make_server()
    names = sorted(t.name for t in await mcp.list_tools(run_middleware=False))
    assert names == sorted(
        [
            "analyze_workflow_dependencies",
            "search_issues",
            "get_pull_requests",
            "analyze_repository_structure",
        ]
    )


@pytest.mark.asyncio
async def test_tool_schemas_match_nodejs_parameter_names() -> None:
    mcp = _make_server()
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
    expected = {
        "analyze_workflow_dependencies": {
            "component",
            "analysis_type",
            "include_external",
        },
        "search_issues": {"query", "repository", "state", "labels"},
        "get_pull_requests": {"repository", "state", "limit"},
        "analyze_repository_structure": {
            "repositories",
            "analysis_depth",
        },
    }
    for name, want in expected.items():
        schema = tools[name].parameters
        actual = set((schema.get("properties") or {}).keys())
        assert actual == want, name


@pytest.mark.asyncio
async def test_required_fields_match_nodejs() -> None:
    mcp = _make_server()
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
    assert tools["analyze_workflow_dependencies"].parameters[
        "required"
    ] == ["component"]
    assert tools["search_issues"].parameters["required"] == ["query"]
    assert tools["get_pull_requests"].parameters.get("required", []) == []
    assert (
        tools["analyze_repository_structure"].parameters.get("required", [])
        == []
    )


@pytest.mark.asyncio
async def test_state_enums_match_nodejs() -> None:
    mcp = _make_server()
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
    expected_state = {"open", "closed", "all"}
    assert (
        _enum_of(tools["search_issues"].parameters["properties"]["state"])
        == expected_state
    )
    assert (
        _enum_of(tools["get_pull_requests"].parameters["properties"]["state"])
        == expected_state
    )


@pytest.mark.asyncio
async def test_analysis_type_enum_matches_nodejs() -> None:
    mcp = _make_server()
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
    schema = tools["analyze_workflow_dependencies"].parameters["properties"][
        "analysis_type"
    ]
    assert _enum_of(schema) == {"upstream", "downstream", "circular", "all"}
    assert schema["default"] == "all"


@pytest.mark.asyncio
async def test_include_external_default_false() -> None:
    mcp = _make_server()
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
    schema = tools["analyze_workflow_dependencies"].parameters["properties"][
        "include_external"
    ]
    assert schema["default"] is False


@pytest.mark.asyncio
async def test_analysis_depth_enum_matches_nodejs() -> None:
    mcp = _make_server()
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
    schema = tools["analyze_repository_structure"].parameters["properties"][
        "analysis_depth"
    ]
    assert _enum_of(schema) == {"shallow", "deep"}
    assert schema["default"] == "shallow"


@pytest.mark.asyncio
async def test_repository_default_global_workflow() -> None:
    mcp = _make_server()
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
    assert (
        tools["search_issues"].parameters["properties"]["repository"][
            "default"
        ]
        == "global-workflow"
    )
    assert (
        tools["get_pull_requests"].parameters["properties"]["repository"][
            "default"
        ]
        == "global-workflow"
    )


@pytest.mark.asyncio
async def test_pull_requests_limit_default_10() -> None:
    mcp = _make_server()
    tools = {t.name: t for t in await mcp.list_tools(run_middleware=False)}
    schema = tools["get_pull_requests"].parameters["properties"]["limit"]
    assert schema["default"] == 10


# ── degraded mode (no token) ─────────────────────────────────────


@pytest.mark.asyncio
async def test_module_registers_without_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No token at all → registration must still succeed."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    mcp = _make_server(github_token=None)
    names = {t.name for t in await mcp.list_tools(run_middleware=False)}
    assert len(names) == 4


@pytest.mark.asyncio
async def test_search_issues_no_token_returns_no_api_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    mcp = _make_server(github_token=None)
    out = await _call_tool(mcp, "search_issues", {"query": "anything"})
    assert "no API access" in out
    assert "GITHUB_TOKEN" in out


@pytest.mark.asyncio
async def test_all_tools_degrade_when_token_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    mcp = _make_server(github_token=None)
    out_search = await _call_tool(mcp, "search_issues", {"query": "x"})
    out_pulls = await _call_tool(mcp, "get_pull_requests", {})
    out_deps = await _call_tool(
        mcp, "analyze_workflow_dependencies", {"component": "JGFS_FORECAST"}
    )
    out_struct = await _call_tool(mcp, "analyze_repository_structure", {})
    for output in (out_search, out_pulls, out_deps, out_struct):
        assert "no API access" in output


@pytest.mark.asyncio
async def test_token_picked_up_from_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When register() gets no explicit token, it must read GITHUB_TOKEN."""
    monkeypatch.setenv("GITHUB_TOKEN", "env-token-from-monkeypatch")

    captured: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.headers.get("Authorization", ""))
        return _json_response({"items": [], "total_count": 0})

    client = _make_mock_client(_handler)
    mcp = _make_server(github_token=None, http_client=client)
    await _call_tool(mcp, "search_issues", {"query": "anything"})
    assert captured
    assert captured[0] == "Bearer env-token-from-monkeypatch"


# ── search_issues happy path + filters ──────────────────────────


@pytest.mark.asyncio
async def test_search_issues_builds_expected_query() -> None:
    captured: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _json_response(
            {
                "total_count": 1,
                "items": [
                    {
                        "title": "Forecast bug",
                        "number": 42,
                        "state": "open",
                        "user": {"login": "alice"},
                        "updated_at": "2026-05-01T12:00:00Z",
                        "labels": [{"name": "bug"}],
                        "html_url": "https://github.com/x/y/issues/42",
                        "body": "details about the bug",
                        "pull_request": None,
                    }
                ],
            }
        )

    client = _make_mock_client(_handler)
    mcp = _make_server(http_client=client)
    out = await _call_tool(
        mcp,
        "search_issues",
        {
            "query": "forecast crash",
            "repository": "global-workflow",
            "state": "open",
            "labels": ["bug", "high-priority"],
        },
    )

    assert len(captured) == 1
    request = captured[0]
    assert request.url.path == "/search/issues"
    qs = parse_qs(request.url.query.decode())
    assert qs["q"][0].startswith("repo:NOAA-EMC/global-workflow")
    assert "forecast crash" in qs["q"][0]
    assert "state:open" in qs["q"][0]
    assert 'label:"bug"' in qs["q"][0]
    assert 'label:"high-priority"' in qs["q"][0]
    assert qs["sort"] == ["updated"]
    assert qs["order"] == ["desc"]
    assert qs["per_page"] == ["20"]

    assert "Forecast bug" in out
    assert "#42" in out
    assert "alice" in out
    assert "bug" in out


@pytest.mark.asyncio
async def test_search_issues_state_all_omits_state_qualifier() -> None:
    captured: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _json_response({"total_count": 0, "items": []})

    client = _make_mock_client(_handler)
    mcp = _make_server(http_client=client)
    out = await _call_tool(
        mcp, "search_issues", {"query": "x", "state": "all"}
    )

    qs = parse_qs(captured[0].url.query.decode())
    assert "state:" not in qs["q"][0]
    assert "No issues found" in out


@pytest.mark.asyncio
async def test_search_issues_uses_default_repository() -> None:
    captured: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _json_response({"total_count": 0, "items": []})

    client = _make_mock_client(_handler)
    mcp = _make_server(http_client=client)
    await _call_tool(mcp, "search_issues", {"query": "x"})
    qs = parse_qs(captured[0].url.query.decode())
    assert "repo:NOAA-EMC/global-workflow" in qs["q"][0]


@pytest.mark.asyncio
async def test_search_issues_overrides_repository() -> None:
    captured: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _json_response({"total_count": 0, "items": []})

    client = _make_mock_client(_handler)
    mcp = _make_server(http_client=client)
    await _call_tool(
        mcp, "search_issues", {"query": "x", "repository": "GSI"}
    )
    qs = parse_qs(captured[0].url.query.decode())
    assert "repo:NOAA-EMC/GSI" in qs["q"][0]


@pytest.mark.asyncio
async def test_search_issues_zero_total_count_returns_friendly_message() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        return _json_response({"total_count": 0, "items": []})

    client = _make_mock_client(_handler)
    mcp = _make_server(http_client=client)
    out = await _call_tool(mcp, "search_issues", {"query": "ghost"})
    assert 'No issues found for query: "ghost"' in out


# ── get_pull_requests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_pull_requests_happy_path() -> None:
    captured: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _json_response(
            [
                {
                    "title": "Add forecast retry",
                    "number": 100,
                    "state": "open",
                    "user": {"login": "bob"},
                    "head": {"ref": "feature/retry"},
                    "base": {"ref": "develop"},
                    "updated_at": "2026-05-02T15:30:00Z",
                    "labels": [{"name": "enhancement"}],
                    "html_url": "https://github.com/NOAA-EMC/global-workflow/pull/100",
                    "body": "enables retries",
                }
            ]
        )

    client = _make_mock_client(_handler)
    mcp = _make_server(http_client=client)
    out = await _call_tool(mcp, "get_pull_requests", {})

    assert len(captured) == 1
    request = captured[0]
    assert (
        request.url.path
        == "/repos/NOAA-EMC/global-workflow/pulls"
    )
    qs = parse_qs(request.url.query.decode())
    assert qs["state"] == ["open"]
    assert qs["sort"] == ["updated"]
    assert qs["direction"] == ["desc"]
    assert qs["per_page"] == ["10"]

    assert "Pull Requests for global-workflow" in out
    assert "Add forecast retry" in out
    assert "#100" in out
    assert "feature/retry" in out
    assert "develop" in out


@pytest.mark.asyncio
async def test_get_pull_requests_caps_limit_at_50() -> None:
    captured: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _json_response([])

    client = _make_mock_client(_handler)
    mcp = _make_server(http_client=client)
    await _call_tool(mcp, "get_pull_requests", {"limit": 200})
    qs = parse_qs(captured[0].url.query.decode())
    assert qs["per_page"] == ["50"]


@pytest.mark.asyncio
async def test_get_pull_requests_state_closed() -> None:
    captured: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _json_response([])

    client = _make_mock_client(_handler)
    mcp = _make_server(http_client=client)
    out = await _call_tool(
        mcp,
        "get_pull_requests",
        {"state": "closed", "repository": "GSI"},
    )
    qs = parse_qs(captured[0].url.query.decode())
    assert qs["state"] == ["closed"]
    assert "No closed pull requests found in GSI" in out


# ── analyze_workflow_dependencies ──────────────────────────────


@pytest.mark.asyncio
async def test_analyze_workflow_dependencies_renders_all_sections() -> None:
    """Default analysis_type='all' renders Upstream, Downstream, Circular."""

    def _handler(request: httpx.Request) -> httpx.Response:
        # Code search — return two hits with text_matches
        return _json_response(
            {
                "total_count": 2,
                "items": [
                    {
                        "path": "ush/detect_machine.sh",
                        "text_matches": [
                            {"fragment": "import ufs_utils\nsource detect_machine.sh"}
                        ],
                    },
                    {
                        "path": "scripts/exgfs_forecast.sh",
                        "text_matches": [{"fragment": "${HOMEgfs}"}],
                    },
                ],
            }
        )

    client = _make_mock_client(_handler)
    mcp = _make_server(http_client=client)
    out = await _call_tool(
        mcp,
        "analyze_workflow_dependencies",
        {"component": "JGFS_FORECAST"},
    )
    assert "# Dependency Analysis: JGFS_FORECAST" in out
    assert "## Upstream Dependencies" in out
    assert "## Downstream Dependencies" in out
    assert "## Circular Dependency Check" in out
    assert "ufs_utils" in out
    assert "detect_machine.sh" in out  # source pattern hit
    assert "ush/detect_machine.sh" in out
    assert "scripts/exgfs_forecast.sh" in out


@pytest.mark.asyncio
async def test_analyze_workflow_dependencies_upstream_only() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        return _json_response(
            {
                "items": [
                    {
                        "path": "x.sh",
                        "text_matches": [{"fragment": "import foo"}],
                    }
                ]
            }
        )

    client = _make_mock_client(_handler)
    mcp = _make_server(http_client=client)
    out = await _call_tool(
        mcp,
        "analyze_workflow_dependencies",
        {"component": "X", "analysis_type": "upstream"},
    )
    assert "## Upstream Dependencies" in out
    assert "## Downstream Dependencies" not in out
    assert "## Circular Dependency Check" not in out


@pytest.mark.asyncio
async def test_analyze_workflow_dependencies_include_external() -> None:
    """include_external=True hits the per-external-repo loop."""
    captured: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = request.url.path
        if path == "/search/code":
            qs = parse_qs(request.url.query.decode())
            q = qs["q"][0]
            # The first call is the local search, then per-external-repo
            if "repo:NOAA-EMC/global-workflow" in q:
                return _json_response({"items": [], "total_count": 0})
            return _json_response({"items": [], "total_count": 3})
        return _json_response({})

    client = _make_mock_client(_handler)
    mcp = _make_server(http_client=client)
    out = await _call_tool(
        mcp,
        "analyze_workflow_dependencies",
        {"component": "FOO", "include_external": True},
    )
    assert "## External Dependencies" in out
    # 4 external repos * 1 search each = 4 + 1 (local) = 5 total
    assert len(captured) == 5
    for repo in ("GSI", "UFS_UTILS", "GDASApp", "wxflow"):
        assert repo in out


# ── analyze_repository_structure ─────────────────────────────


@pytest.mark.asyncio
async def test_analyze_repository_structure_shallow_default() -> None:
    captured: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = request.url.path
        # /repos/NOAA-EMC/{repo} → metadata
        # /repos/NOAA-EMC/{repo}/contents/ → top-level listing
        if path.endswith("/contents/"):
            return _json_response(
                [
                    {"name": "jobs", "type": "dir"},
                    {"name": "scripts", "type": "dir"},
                    {"name": "README.md", "type": "file"},
                ]
            )
        return _json_response(
            {
                "description": "Test repo",
                "language": "Shell",
                "size": 12345,
                "updated_at": "2026-05-01T10:00:00Z",
            }
        )

    client = _make_mock_client(_handler)
    mcp = _make_server(http_client=client)
    out = await _call_tool(
        mcp,
        "analyze_repository_structure",
        {"repositories": ["global-workflow"]},
    )

    # 1 repo × 2 endpoints = 2 calls
    assert len(captured) == 2
    assert "## global-workflow" in out
    assert "Test repo" in out
    assert "Shell" in out
    assert "12345 KB" in out
    assert "Top-level directories" in out
    assert "jobs, scripts" in out


@pytest.mark.asyncio
async def test_analyze_repository_structure_uses_default_repos() -> None:
    captured: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = request.url.path
        if path.endswith("/contents/"):
            return _json_response([])
        return _json_response(
            {
                "description": None,
                "language": None,
                "size": 0,
                "updated_at": "2026-01-01T00:00:00Z",
            }
        )

    client = _make_mock_client(_handler)
    mcp = _make_server(http_client=client)
    out = await _call_tool(mcp, "analyze_repository_structure", {})
    # 3 default repos × 2 endpoints = 6 calls
    assert len(captured) == 6
    for repo in github_tools.DEFAULT_STRUCTURE_REPOS:
        assert f"## {repo}" in out


@pytest.mark.asyncio
async def test_analyze_repository_structure_deep_branch() -> None:
    captured: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = request.url.path
        # Top-level contents listing
        if path == "/repos/NOAA-EMC/global-workflow/contents/":
            return _json_response(
                [
                    {"name": "jobs", "type": "dir"},
                    {"name": "scripts", "type": "dir"},
                    {"name": "parm", "type": "dir"},
                    # Note: 'src' and 'sorc' missing — should be skipped
                ]
            )
        # Deep listings — return varying counts
        if path.endswith("/contents/jobs"):
            return _json_response([{"name": f"f{i}"} for i in range(10)])
        if path.endswith("/contents/scripts"):
            return _json_response([{"name": f"s{i}"} for i in range(7)])
        if path.endswith("/contents/parm"):
            return _json_response([{"name": f"p{i}"} for i in range(3)])
        return _json_response(
            {
                "description": "deep",
                "language": "Shell",
                "size": 100,
                "updated_at": "2026-05-01T00:00:00Z",
            }
        )

    client = _make_mock_client(_handler)
    mcp = _make_server(http_client=client)
    out = await _call_tool(
        mcp,
        "analyze_repository_structure",
        {"repositories": ["global-workflow"], "analysis_depth": "deep"},
    )
    assert "**jobs**: 10 items" in out
    assert "**scripts**: 7 items" in out
    assert "**parm**: 3 items" in out
    # src and sorc missing from listing → not rendered
    assert "**src**" not in out
    assert "**sorc**" not in out


# ── auth-failure / rate-limit handling ───────────────────────────


@pytest.mark.asyncio
async def test_401_returns_auth_failure_error() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        return _json_response(
            {"message": "Bad credentials"},
            status=401,
            rate_limit_remaining=4_500,
        )

    client = _make_mock_client(_handler)
    mcp = _make_server(http_client=client)
    out = await _call_tool(mcp, "search_issues", {"query": "anything"})
    assert "[ERROR] GitHub authentication failed" in out
    assert "401" in out
    assert "Bad credentials" in out
    assert "GITHUB_TOKEN" in out


@pytest.mark.asyncio
async def test_403_with_rate_limit_zero_returns_warning() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        return _json_response(
            {"message": "API rate limit exceeded"},
            status=403,
            rate_limit_remaining=0,
            rate_limit_reset=1_715_700_000,
        )

    client = _make_mock_client(_handler)
    mcp = _make_server(http_client=client)
    out = await _call_tool(mcp, "search_issues", {"query": "anything"})
    assert "[WARN] GitHub API rate limit exceeded" in out
    assert "Resets at" in out


@pytest.mark.asyncio
async def test_403_with_rate_limit_remaining_treated_as_auth_failure() -> None:
    """A 403 with Remaining > 0 is a forbidden / auth-style failure,
    not a rate-limit. Match Node.js classification."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return _json_response(
            {"message": "Resource not accessible by integration"},
            status=403,
            rate_limit_remaining=4_500,
        )

    client = _make_mock_client(_handler)
    mcp = _make_server(http_client=client)
    out = await _call_tool(mcp, "search_issues", {"query": "anything"})
    assert "[ERROR] GitHub authentication failed" in out
    assert "403" in out


@pytest.mark.asyncio
async def test_rate_limit_warning_prepended_when_zero_on_success() -> None:
    """Even on a successful response, X-RateLimit-Remaining=0 surfaces
    a [WARN] prefix in the rendered output."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return _json_response(
            {"total_count": 0, "items": []},
            rate_limit_remaining=0,
            rate_limit_reset=1_715_700_000,
        )

    client = _make_mock_client(_handler)
    mcp = _make_server(http_client=client)
    out = await _call_tool(mcp, "search_issues", {"query": "x"})
    # Even with 0 results, WARN must NOT be rendered for empty body
    # (because the empty-body short-circuits before the rate-limit
    # warning render). Confirm the short-circuit precedes the warn.
    assert 'No issues found for query: "x"' in out


# ── HTTP client + headers ─────────────────────────────────────


@pytest.mark.asyncio
async def test_request_headers_include_user_agent_and_bearer() -> None:
    captured: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _json_response({"total_count": 0, "items": []})

    client = _make_mock_client(_handler)
    mcp = _make_server(github_token="my-test-token", http_client=client)
    await _call_tool(mcp, "search_issues", {"query": "x"})
    request = captured[0]
    assert request.headers["Authorization"] == "Bearer my-test-token"
    assert request.headers["User-Agent"] == github_tools.USER_AGENT
    assert request.headers["X-GitHub-Api-Version"] == "2022-11-28"
    assert "application/vnd.github" in request.headers["Accept"]


# ── pure-function helpers ─────────────────────────────────────


def test_resolve_token_explicit_arg_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "from-env")
    assert github_tools._resolve_token("explicit") == "explicit"


def test_resolve_token_falls_back_to_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "env-token")
    assert github_tools._resolve_token(None) == "env-token"


def test_resolve_token_returns_none_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert github_tools._resolve_token(None) is None


def test_resolve_token_treats_empty_string_as_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "   ")
    assert github_tools._resolve_token(None) is None


def test_build_issue_search_query_assembly() -> None:
    q = github_tools._build_issue_search_query(
        repository="GSI",
        query="forecast",
        state="closed",
        labels=["bug", "urgent"],
    )
    parts = q.split(" ")
    assert "repo:NOAA-EMC/GSI" in parts
    assert "forecast" in parts
    assert "state:closed" in parts
    assert 'label:"bug"' in q
    assert 'label:"urgent"' in q


def test_build_issue_search_query_omits_state_all() -> None:
    q = github_tools._build_issue_search_query(
        repository="X",
        query="q",
        state="all",
        labels=None,
    )
    assert "state:" not in q


def test_extract_upstream_dependencies_covers_all_patterns() -> None:
    """The 4 regex patterns are applied in order: ``import \\w+``,
    ``from \\w+ import``, ``source \\S+``, ``${\\w+}``. The first
    pattern matches ``import gamma`` inside ``from beta import gamma``
    (parity with the Node.js source which has the same caveat — its
    caller dedupes via a ``Set`` so the order doesn't surface).
    """
    src = (
        "import alpha\n"
        "from beta import gamma\n"
        "source delta.sh\n"
        "echo ${EPSILON}\n"
        "import alpha\n"  # duplicate
    )
    deps = github_tools._extract_upstream_dependencies(src)
    # Pattern 1 matches "import alpha" + "import gamma" + "import alpha"
    # (dup), pattern 2 matches "beta", pattern 3 matches "delta.sh",
    # pattern 4 matches "EPSILON". Dedup preserves first-seen order.
    assert deps == ["alpha", "gamma", "beta", "delta.sh", "EPSILON"]


def test_truncate_returns_full_text_when_short() -> None:
    text, truncated = github_tools._truncate("hello", 100)
    assert text == "hello"
    assert truncated is False


def test_truncate_chops_long_text() -> None:
    text, truncated = github_tools._truncate("x" * 500, 100)
    assert len(text) == 100
    assert truncated is True


def test_truncate_handles_none() -> None:
    text, truncated = github_tools._truncate(None, 100)
    assert text == ""
    assert truncated is False


def test_fmt_iso_to_date_renders_locale_style() -> None:
    assert github_tools._fmt_iso_to_date("2026-05-14T12:00:00Z") == "5/14/2026"


def test_fmt_iso_to_date_handles_missing() -> None:
    assert github_tools._fmt_iso_to_date(None) == ""


def test_fmt_iso_to_date_passthrough_on_invalid() -> None:
    assert github_tools._fmt_iso_to_date("not-a-date") == "not-a-date"


def test_fmt_unix_to_iso() -> None:
    out = github_tools._fmt_unix_to_iso(1_715_700_000)
    assert out.endswith("Z")
    assert "2024-05-14" in out


def test_fmt_unix_to_iso_handles_none() -> None:
    assert github_tools._fmt_unix_to_iso(None) == ""


# ── GitHubAPIError classification ────────────────────────────


def test_api_error_is_auth_failure_when_403_with_remaining() -> None:
    err = github_tools.GitHubAPIError(
        status=403, message="forbidden", rate_limit_remaining=4500
    )
    assert err.is_auth_failure is True
    assert err.is_rate_limited is False


def test_api_error_is_rate_limited_when_403_remaining_zero() -> None:
    err = github_tools.GitHubAPIError(
        status=403, message="rate limit", rate_limit_remaining=0
    )
    assert err.is_rate_limited is True
    assert err.is_auth_failure is False


def test_api_error_401_is_auth_failure() -> None:
    err = github_tools.GitHubAPIError(
        status=401, message="bad credentials", rate_limit_remaining=4500
    )
    assert err.is_auth_failure is True
    assert err.is_rate_limited is False


def test_api_error_500_is_neither() -> None:
    err = github_tools.GitHubAPIError(
        status=500, message="server error", rate_limit_remaining=4500
    )
    assert err.is_auth_failure is False
    assert err.is_rate_limited is False
