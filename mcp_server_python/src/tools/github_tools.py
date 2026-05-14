"""GitHub integration tools (Requirements 11.1 – 11.5, Task 16 Phase B11).

Python port of the 4 tools in
``mcp_server_node/src/tools/GitHubTools.js``. Tool names, input
schemas, and output shapes match the Node.js source so the parity
framework can compare results side-by-side.

These tools are GitHub-API-backed (REST v3 via ``httpx`` instead of
Octokit). They have NO database dependency — Neptune and OpenSearch
are bypassed entirely. The whole module is data-access-free.

Tool overview
-------------

* ``analyze_workflow_dependencies`` — code-search-driven dependency
  analysis for a named component. Searches
  ``NOAA-EMC/global-workflow`` for references, then renders four
  optional sections (Upstream / Downstream / Circular / External)
  according to ``analysis_type``. ``include_external=true`` adds a
  cross-repo block over GSI / UFS_UTILS / GDASApp / wxflow.

* ``search_issues`` — wraps the GitHub ``search/issues`` endpoint
  with a NOAA-EMC repo prefix, optional state + labels filters,
  sorted by ``updated`` desc, top 20.

* ``get_pull_requests`` — wraps the ``pulls`` endpoint for a
  NOAA-EMC repo, sorted by ``updated`` desc, capped at 50.

* ``analyze_repository_structure`` — multi-repo analysis: per-repo
  metadata (description, language, size, last update) +
  top-level directory listing. ``analysis_depth='deep'`` adds an
  item-count breakdown for ``jobs / scripts / parm / src / sorc``
  when those directories exist.

Authentication (Requirement 11.4)
---------------------------------

Token sourcing precedence: explicit ``register(...github_token=...)``
arg → ``GITHUB_TOKEN`` env var. With no token every tool returns
``[ERROR] GitHub integration not available - no API access`` —
matching the Node.js degraded-mode contract. Unauthenticated REST
access is technically supported by GitHub at low rate limits, but
the operational expectation is that the AgentCore Runtime always
supplies a token via the secret-injection path; the no-token branch
exists for graceful boot only.

Rate-limit handling
-------------------

Every response is checked for the ``X-RateLimit-Remaining`` /
``X-RateLimit-Reset`` headers. When ``Remaining=0`` (or a 403 body
contains ``"rate limit exceeded"``) the tool prepends a ``[WARN]``
block with the reset timestamp before the operation continues or
returns. 401/403 (auth failure) responses surface as
``[ERROR] GitHub authentication failed: <status>`` rather than
crashing.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
from fastmcp import FastMCP

log = logging.getLogger(__name__)


# ── constants ──────────────────────────────────────────────────────


#: GitHub REST API base URL. Hard-coded to public github.com — the
#: Node.js port has no GHE support either.
GITHUB_API_BASE: str = "https://api.github.com"

#: Owner under which all NOAA Global Workflow repositories live.
#: Hard-coded to match the Node.js source.
NOAA_OWNER: str = "NOAA-EMC"

#: User-Agent string sent on every request. The Octokit client in the
#: Node.js port uses this exact string; preserve for parity.
USER_AGENT: str = "global-workflow-mcp-server/2.0.0"

#: Default repository when the caller omits the ``repository`` arg.
DEFAULT_REPOSITORY: str = "global-workflow"

#: Default repository trio for ``analyze_repository_structure``. Order
#: matches the Node.js source.
DEFAULT_STRUCTURE_REPOS: tuple[str, ...] = (
    "global-workflow",
    "GSI",
    "UFS_UTILS",
)

#: External NOAA-EMC repositories searched by
#: ``analyze_workflow_dependencies(include_external=true)``.
EXTERNAL_DEPENDENCY_REPOS: tuple[str, ...] = (
    "GSI",
    "UFS_UTILS",
    "GDASApp",
    "wxflow",
)

#: Directories whose item count is reported in the deep analysis
#: branch of ``analyze_repository_structure``. Order matches Node.js.
DEEP_KEY_DIRECTORIES: tuple[str, ...] = (
    "jobs",
    "scripts",
    "parm",
    "src",
    "sorc",
)

#: Per-page limits for each search endpoint. Match the Node.js source.
ISSUES_PER_PAGE: int = 20
CODE_PER_PAGE: int = 30
EXTERNAL_CODE_PER_PAGE: int = 5
PR_LIST_MAX: int = 50

#: Default HTTP timeout (seconds) for any GitHub API request. Long
#: enough for code-search to complete on busy repos but short enough
#: that AgentCore session timeouts don't fire first.
DEFAULT_TIMEOUT: float = 30.0

#: Issue/PR description previews — Node.js uses 200 chars for issues
#: and 150 for PRs.
ISSUE_PREVIEW_CHARS: int = 200
PR_PREVIEW_CHARS: int = 150


_DEGRADED_MSG: str = (
    "GitHub integration not available - no API access. Provide a "
    "GITHUB_TOKEN environment variable (or pass `github_token=...` "
    "when registering the module) to enable the GitHub tools."
)


# ── helpers — token resolution ────────────────────────────────────


def _resolve_token(token: str | None) -> str | None:
    """Pick the token from explicit arg → ``GITHUB_TOKEN`` env var.

    Treats empty strings as missing so blank ``GITHUB_TOKEN`` values
    do not produce malformed Authorization headers.
    """
    candidate = token if token else os.environ.get("GITHUB_TOKEN")
    if not candidate:
        return None
    candidate = candidate.strip()
    return candidate or None


# ── helpers — formatting ─────────────────────────────────────────


def _error_text(message: str) -> str:
    """Match the Node.js error-envelope shape (no ``[ERROR]`` prefix)
    for the GitHubTools branch, which historically returns plain
    text for the no-API-access path. Other paths (auth failure,
    network errors) DO use ``[ERROR]`` so callers can tell them apart.
    """
    return message


def _fmt_iso_to_date(iso: str | None) -> str:
    """Render an ISO-8601 timestamp as a locale-style date string.

    Mirrors ``new Date(...).toLocaleDateString()`` in the Node.js
    source — we render ``M/D/YYYY`` to keep parity output stable
    regardless of caller locale.
    """
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    return f"{dt.month}/{dt.day}/{dt.year}"


def _fmt_unix_to_iso(unix: int | str | None) -> str:
    """Render a Unix-epoch timestamp as an ISO-8601 UTC string."""
    if unix is None:
        return ""
    try:
        return (
            datetime.fromtimestamp(int(unix), tz=timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )
    except (TypeError, ValueError):
        return str(unix)


def _truncate(text: str | None, length: int) -> tuple[str, bool]:
    """Return ``(preview, truncated)`` matching Node.js
    ``substring(0, N)`` + length-check pattern.
    """
    if not text:
        return "", False
    if len(text) <= length:
        return text, False
    return text[:length], True


# ── helpers — HTTP layer ─────────────────────────────────────────


class _GitHubClient:
    """Thin async wrapper over ``httpx.AsyncClient`` for the GitHub
    REST API. Adds Authorization, Accept, and User-Agent headers,
    converts non-2xx responses to a structured ``GitHubAPIError``,
    and tracks the most recent rate-limit headers so callers can
    surface a ``[WARN]`` when the limit is hit.
    """

    def __init__(
        self,
        token: str,
        *,
        base_url: str = GITHUB_API_BASE,
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        # Allow tests to inject a mocked AsyncClient with a custom
        # transport (httpx.MockTransport).
        self._owned_client = client is None
        self._client = client
        self.last_rate_limit_remaining: int | None = None
        self.last_rate_limit_reset: int | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def aclose(self) -> None:
        if self._owned_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _headers(self, *, accept: str | None = None) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": accept or "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _record_rate_limit(self, response: httpx.Response) -> None:
        remaining = response.headers.get("X-RateLimit-Remaining")
        reset = response.headers.get("X-RateLimit-Reset")
        if remaining is not None:
            try:
                self.last_rate_limit_remaining = int(remaining)
            except ValueError:
                self.last_rate_limit_remaining = None
        if reset is not None:
            try:
                self.last_rate_limit_reset = int(reset)
            except ValueError:
                self.last_rate_limit_reset = None

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        accept: str | None = None,
    ) -> dict[str, Any] | list[Any]:
        """GET ``{base_url}{path}`` and return the parsed JSON body.

        Raises :class:`GitHubAPIError` on non-2xx. The status code
        and the ``X-RateLimit-*`` headers are preserved for the
        caller's diagnostics.
        """
        client = await self._ensure_client()
        url = f"{self._base_url}{path}"
        try:
            response = await client.get(
                url,
                params=params,
                headers=self._headers(accept=accept),
            )
        except httpx.HTTPError as exc:
            raise GitHubAPIError(
                status=0, message=f"network error: {exc}"
            ) from exc

        self._record_rate_limit(response)

        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            message = (
                payload.get("message") if isinstance(payload, dict) else None
            ) or response.text or "unknown GitHub API error"
            raise GitHubAPIError(
                status=response.status_code,
                message=message,
                rate_limit_remaining=self.last_rate_limit_remaining,
                rate_limit_reset=self.last_rate_limit_reset,
            )

        try:
            return response.json()
        except ValueError as exc:
            raise GitHubAPIError(
                status=response.status_code,
                message=f"invalid JSON in response: {exc}",
            ) from exc


class GitHubAPIError(RuntimeError):
    """A GitHub REST call returned a non-2xx response (or networked)."""

    def __init__(
        self,
        *,
        status: int,
        message: str,
        rate_limit_remaining: int | None = None,
        rate_limit_reset: int | None = None,
    ) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message
        self.rate_limit_remaining = rate_limit_remaining
        self.rate_limit_reset = rate_limit_reset

    @property
    def is_auth_failure(self) -> bool:
        return self.status in (401, 403) and (
            self.rate_limit_remaining is None
            or self.rate_limit_remaining > 0
        )

    @property
    def is_rate_limited(self) -> bool:
        return (
            self.status == 403
            and self.rate_limit_remaining is not None
            and self.rate_limit_remaining == 0
        )


def _rate_limit_warning(client: _GitHubClient) -> str:
    """Render a ``[WARN]`` block when the most recent response had
    ``X-RateLimit-Remaining: 0`` — empty string when no warning is
    warranted.
    """
    if client.last_rate_limit_remaining != 0:
        return ""
    reset = _fmt_unix_to_iso(client.last_rate_limit_reset)
    suffix = f" Resets at {reset}." if reset else ""
    return (
        "[WARN] GitHub API rate limit exhausted "
        f"(X-RateLimit-Remaining=0).{suffix}\n\n"
    )


def _format_api_error(operation: str, error: GitHubAPIError) -> str:
    """Map a :class:`GitHubAPIError` to the user-facing markdown."""
    if error.is_rate_limited:
        reset = _fmt_unix_to_iso(error.rate_limit_reset)
        suffix = f" Resets at {reset}." if reset else ""
        return (
            f"[WARN] GitHub API rate limit exceeded during {operation}."
            f"{suffix}\n"
        )
    if error.is_auth_failure:
        return (
            f"[ERROR] GitHub authentication failed during "
            f"{operation}: HTTP {error.status} ({error.message}). "
            "Check that GITHUB_TOKEN is valid.\n"
        )
    return f"{operation} error: {error.message}\n"


# ── helpers — query construction ─────────────────────────────────


def _build_issue_search_query(
    *,
    repository: str,
    query: str,
    state: str,
    labels: list[str] | None,
) -> str:
    """Replicate the Node.js search-string assembly verbatim."""
    parts: list[str] = [f"repo:{NOAA_OWNER}/{repository}", query]
    if state != "all":
        parts.append(f"state:{state}")
    if labels:
        parts.extend(f'label:"{label}"' for label in labels)
    return " ".join(parts)


_DEPENDENCY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"import\s+(\w+)"),
    re.compile(r"from\s+(\w+)\s+import"),
    re.compile(r"source\s+([^\s]+)"),
    re.compile(r"\$\{(\w+)\}"),
)


def _extract_upstream_dependencies(content: str) -> list[str]:
    """Port of the Node.js ``extractDependencies(content, 'upstream')``
    helper — same regex set, same order, same dedup semantics
    (we collapse via ``dict.fromkeys`` to preserve first-seen order)."""
    matches: list[str] = []
    for pattern in _DEPENDENCY_PATTERNS:
        matches.extend(pattern.findall(content))
    return list(dict.fromkeys(matches))


# ── tool implementations ──────────────────────────────────────────


async def _tool_analyze_workflow_dependencies(
    client: _GitHubClient | None,
    *,
    component: str,
    analysis_type: str,
    include_external: bool,
) -> str:
    if client is None:
        return _error_text(_DEGRADED_MSG)

    output = [_rate_limit_warning(client), f"# Dependency Analysis: {component}\n"]

    try:
        search_results = await _search_code_references(client, component)
    except GitHubAPIError as exc:
        return _format_api_error("dependency analysis", exc)

    if analysis_type in ("upstream", "all"):
        output.append(_render_upstream(component, search_results))
    if analysis_type in ("downstream", "all"):
        output.append(_render_downstream(component, search_results))
    if analysis_type in ("circular", "all"):
        output.append(_render_circular_check())

    if include_external:
        try:
            output.append(
                await _render_external_dependencies(client, component)
            )
        except GitHubAPIError as exc:
            output.append(
                f"## External Dependencies\n\n"
                f"External dependency search error: {exc.message}\n\n"
            )

    return "".join(output).rstrip() + "\n"


async def _search_code_references(
    client: _GitHubClient, component: str
) -> list[dict[str, Any]]:
    """Run the per-component code search used by dependency analysis."""
    query = f"{component} repo:{NOAA_OWNER}/{DEFAULT_REPOSITORY}"
    try:
        payload = await client.get(
            "/search/code",
            params={
                "q": query,
                "sort": "indexed",
                "per_page": CODE_PER_PAGE,
            },
            accept="application/vnd.github.text-match+json",
        )
    except GitHubAPIError as exc:
        if exc.is_auth_failure:
            raise
        log.warning("Code search error: %s", exc.message)
        return []
    if isinstance(payload, dict):
        items = payload.get("items") or []
        return [item for item in items if isinstance(item, dict)]
    return []


def _render_upstream(component: str, results: list[dict[str, Any]]) -> str:
    lines = [
        "## Upstream Dependencies\n",
        f"Components that {component} depends on:\n",
    ]
    deps: dict[str, None] = {}
    for item in results:
        text_matches = item.get("text_matches") or []
        for match in text_matches:
            if isinstance(match, dict):
                fragment = match.get("fragment") or ""
                for dep in _extract_upstream_dependencies(fragment):
                    deps.setdefault(dep, None)
    if deps:
        lines.extend(f"- {dep}" for dep in deps)
    else:
        lines.append("No clear upstream dependencies found in search results.")
    lines.append("")
    return "\n".join(lines) + "\n"


def _render_downstream(component: str, results: list[dict[str, Any]]) -> str:
    lines = [
        "## Downstream Dependencies\n",
        f"Components that depend on {component}:\n",
    ]
    by_file: dict[str, int] = {}
    for item in results:
        path = item.get("path") or ""
        if not path:
            continue
        by_file[path] = by_file.get(path, 0) + 1
    if by_file:
        for path, count in by_file.items():
            label = "reference" if count == 1 else "references"
            lines.append(f"- **{path}**: {count} {label}")
    else:
        lines.append(
            "No downstream dependencies found in search results."
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def _render_circular_check() -> str:
    return (
        "## Circular Dependency Check\n\n"
        "Circular dependency detection requires deeper code analysis.\n"
        "Manual review recommended for critical components.\n\n"
    )


async def _render_external_dependencies(
    client: _GitHubClient, component: str
) -> str:
    lines = ["## External Dependencies\n"]
    for repo in EXTERNAL_DEPENDENCY_REPOS:
        try:
            payload = await client.get(
                "/search/code",
                params={
                    "q": f"{component} repo:{NOAA_OWNER}/{repo}",
                    "per_page": EXTERNAL_CODE_PER_PAGE,
                },
            )
        except GitHubAPIError:
            # Repository might not be accessible; skip silently like
            # the Node.js source.
            continue
        total = payload.get("total_count") if isinstance(payload, dict) else 0
        if total and total > 0:
            label = "reference" if total == 1 else "references"
            lines.append(f"- **{repo}**: {total} {label}")
    lines.append("")
    return "\n".join(lines) + "\n"


async def _tool_search_issues(
    client: _GitHubClient | None,
    *,
    query: str,
    repository: str,
    state: str,
    labels: list[str] | None,
) -> str:
    if client is None:
        return _error_text(_DEGRADED_MSG)

    search_query = _build_issue_search_query(
        repository=repository,
        query=query,
        state=state,
        labels=labels,
    )

    try:
        payload = await client.get(
            "/search/issues",
            params={
                "q": search_query,
                "sort": "updated",
                "order": "desc",
                "per_page": ISSUES_PER_PAGE,
            },
        )
    except GitHubAPIError as exc:
        return _format_api_error("issue search", exc)

    if not isinstance(payload, dict):
        return f'Issue search error: unexpected response shape\n'

    total = payload.get("total_count") or 0
    items = payload.get("items") or []
    if total == 0 or not items:
        return f'No issues found for query: "{query}"\n'

    return _rate_limit_warning(client) + _format_issue_results(items, query)


async def _tool_get_pull_requests(
    client: _GitHubClient | None,
    *,
    repository: str,
    state: str,
    limit: int,
) -> str:
    if client is None:
        return _error_text(_DEGRADED_MSG)

    per_page = min(max(int(limit), 1), PR_LIST_MAX)
    path = f"/repos/{NOAA_OWNER}/{repository}/pulls"
    try:
        payload = await client.get(
            path,
            params={
                "state": state,
                "sort": "updated",
                "direction": "desc",
                "per_page": per_page,
            },
        )
    except GitHubAPIError as exc:
        return _format_api_error("pull request", exc)

    if not isinstance(payload, list) or not payload:
        return f"No {state} pull requests found in {repository}\n"

    return _rate_limit_warning(client) + _format_pr_results(
        payload, repository
    )


async def _tool_analyze_repository_structure(
    client: _GitHubClient | None,
    *,
    repositories: list[str],
    analysis_depth: str,
) -> str:
    if client is None:
        return _error_text(_DEGRADED_MSG)

    output = [_rate_limit_warning(client), "# Multi-Repository Structure Analysis\n\n"]

    for repo in repositories:
        output.append(f"## {repo}\n\n")
        try:
            repo_info = await client.get(f"/repos/{NOAA_OWNER}/{repo}")
        except GitHubAPIError as exc:
            output.append(f"Error analyzing {repo}: {exc.message}\n\n")
            continue
        if not isinstance(repo_info, dict):
            output.append(f"Error analyzing {repo}: unexpected response\n\n")
            continue

        description = repo_info.get("description") or "No description"
        language = repo_info.get("language") or "Mixed"
        size = repo_info.get("size", 0)
        updated_at = repo_info.get("updated_at")
        output.append(f"**Description**: {description}\n")
        output.append(f"**Language**: {language}\n")
        output.append(f"**Size**: {size} KB\n")
        output.append(
            f"**Last Updated**: {_fmt_iso_to_date(updated_at)}\n\n"
        )

        try:
            contents = await client.get(
                f"/repos/{NOAA_OWNER}/{repo}/contents/", params={"ref": ""}
            )
        except GitHubAPIError as exc:
            output.append(f"Error analyzing {repo}: {exc.message}\n\n")
            continue
        if not isinstance(contents, list):
            output.append(f"Error analyzing {repo}: unexpected contents\n\n")
            continue

        directories = [
            item for item in contents
            if isinstance(item, dict) and item.get("type") == "dir"
        ]
        dir_names = [d.get("name", "") for d in directories]
        output.append(
            f"**Top-level directories**: {', '.join(dir_names)}\n\n"
        )

        if analysis_depth == "deep":
            present_names = {name for name in dir_names}
            for key_dir in DEEP_KEY_DIRECTORIES:
                if key_dir not in present_names:
                    continue
                try:
                    dir_contents = await client.get(
                        f"/repos/{NOAA_OWNER}/{repo}/contents/{key_dir}"
                    )
                except GitHubAPIError:
                    output.append(f"- **{key_dir}**: Could not analyze\n")
                    continue
                count = (
                    len(dir_contents)
                    if isinstance(dir_contents, list)
                    else 0
                )
                output.append(f"- **{key_dir}**: {count} items\n")
            output.append("\n")

    return "".join(output).rstrip() + "\n"


# ── helpers — output rendering ───────────────────────────────────


def _format_issue_results(
    issues: list[dict[str, Any]], query: str
) -> str:
    lines = [
        f'# GitHub Issues for: "{query}"\n',
        f"Found {len(issues)} issues:\n",
    ]
    for index, issue in enumerate(issues, start=1):
        is_pr = " (PR)" if issue.get("pull_request") else ""
        title = issue.get("title", "(untitled)")
        lines.append(f"## {index}. {title}{is_pr}\n")
        lines.append(f"**Number**: #{issue.get('number')}")
        lines.append(f"**State**: {issue.get('state', 'unknown')}")
        user = issue.get("user") or {}
        lines.append(f"**Author**: {user.get('login', 'unknown')}")
        lines.append(
            f"**Updated**: {_fmt_iso_to_date(issue.get('updated_at'))}"
        )
        labels = issue.get("labels") or []
        label_names = [
            (lbl.get("name") if isinstance(lbl, dict) else str(lbl))
            for lbl in labels
        ]
        label_names = [name for name in label_names if name]
        if label_names:
            lines.append(f"**Labels**: {', '.join(label_names)}")
        lines.append(f"**URL**: {issue.get('html_url', '')}\n")

        body = issue.get("body") or ""
        if body:
            preview, truncated = _truncate(body, ISSUE_PREVIEW_CHARS)
            suffix = "..." if truncated else ""
            lines.append(f"**Description**: {preview}{suffix}")

        lines.append("")
        lines.append("---\n")

    return "\n".join(lines).rstrip() + "\n"


def _format_pr_results(
    prs: list[dict[str, Any]], repository: str
) -> str:
    lines = [
        f"# Pull Requests for {repository}\n",
        f"Found {len(prs)} pull requests:\n",
    ]
    for index, pr in enumerate(prs, start=1):
        title = pr.get("title", "(untitled)")
        lines.append(f"## {index}. {title}\n")
        lines.append(f"**Number**: #{pr.get('number')}")
        lines.append(f"**State**: {pr.get('state', 'unknown')}")
        user = pr.get("user") or {}
        lines.append(f"**Author**: {user.get('login', 'unknown')}")
        head = (pr.get("head") or {}).get("ref", "?")
        base = (pr.get("base") or {}).get("ref", "?")
        lines.append(f"**Branch**: {head} \u2192 {base}")
        lines.append(
            f"**Updated**: {_fmt_iso_to_date(pr.get('updated_at'))}"
        )
        labels = pr.get("labels") or []
        label_names = [
            (lbl.get("name") if isinstance(lbl, dict) else str(lbl))
            for lbl in labels
        ]
        label_names = [name for name in label_names if name]
        if label_names:
            lines.append(f"**Labels**: {', '.join(label_names)}")
        lines.append(f"**URL**: {pr.get('html_url', '')}\n")

        body = pr.get("body") or ""
        if body:
            preview, truncated = _truncate(body, PR_PREVIEW_CHARS)
            suffix = "..." if truncated else ""
            lines.append(f"**Description**: {preview}{suffix}")

        lines.append("")
        lines.append("---\n")

    return "\n".join(lines).rstrip() + "\n"


# ── public entrypoint ──────────────────────────────────────────────


def register(
    mcp: FastMCP,
    data: Any = None,
    *,
    github_token: str | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> None:
    """Register all 4 GitHub tools on ``mcp``.

    Parameters
    ----------
    mcp
        The FastMCP server instance.
    data
        Unused — kept for the uniform ``register(mcp, data)`` contract
        invoked by ``mcp_server._register_module``. The GitHub tools
        have no database dependency; ``data`` is discarded.
    github_token
        Optional explicit token. When ``None`` the module reads
        ``GITHUB_TOKEN`` from the process environment. When neither
        is set the module still registers (Requirement 1.7) but each
        tool returns a clear ``no API access`` message at call time.
    http_client
        Optional pre-built ``httpx.AsyncClient`` for tests to inject
        a ``MockTransport`` without monkey-patching. Production
        deployments should leave this as ``None`` so each tool call
        gets its own connection (the AgentCore microVM is short-lived
        enough that pooling across calls isn't necessary).
    """
    del data  # explicitly unused — uniform register() contract
    token = _resolve_token(github_token)
    client: _GitHubClient | None = (
        _GitHubClient(token, client=http_client) if token else None
    )

    @mcp.tool(
        name="analyze_workflow_dependencies",
        description=(
            "Analyze dependencies and relationships between workflow "
            "components."
        ),
    )
    async def analyze_workflow_dependencies(
        component: str,
        analysis_type: Literal[
            "upstream", "downstream", "circular", "all"
        ] = "all",
        include_external: bool = False,
    ) -> str:
        return await _tool_analyze_workflow_dependencies(
            client,
            component=component,
            analysis_type=analysis_type,
            include_external=include_external,
        )

    @mcp.tool(
        name="search_issues",
        description=(
            "Search GitHub issues across workflow repositories."
        ),
    )
    async def search_issues(
        query: str,
        repository: str = DEFAULT_REPOSITORY,
        state: Literal["open", "closed", "all"] = "open",
        labels: list[str] | None = None,
    ) -> str:
        return await _tool_search_issues(
            client,
            query=query,
            repository=repository,
            state=state,
            labels=labels,
        )

    @mcp.tool(
        name="get_pull_requests",
        description=(
            "Get pull request information and changes."
        ),
    )
    async def get_pull_requests(
        repository: str = DEFAULT_REPOSITORY,
        state: Literal["open", "closed", "all"] = "open",
        limit: int = 10,
    ) -> str:
        return await _tool_get_pull_requests(
            client,
            repository=repository,
            state=state,
            limit=limit,
        )

    @mcp.tool(
        name="analyze_repository_structure",
        description=(
            "Analyze structure and components across multiple "
            "repositories."
        ),
    )
    async def analyze_repository_structure(
        repositories: list[str] | None = None,
        analysis_depth: Literal["shallow", "deep"] = "shallow",
    ) -> str:
        repos = list(repositories) if repositories else list(
            DEFAULT_STRUCTURE_REPOS
        )
        return await _tool_analyze_repository_structure(
            client,
            repositories=repos,
            analysis_depth=analysis_depth,
        )


__all__ = [
    "register",
    "GitHubAPIError",
    "GITHUB_API_BASE",
    "NOAA_OWNER",
    "USER_AGENT",
    "DEFAULT_REPOSITORY",
    "DEFAULT_STRUCTURE_REPOS",
    "EXTERNAL_DEPENDENCY_REPOS",
    "DEEP_KEY_DIRECTORIES",
    "ISSUES_PER_PAGE",
    "CODE_PER_PAGE",
    "PR_LIST_MAX",
    "ISSUE_PREVIEW_CHARS",
    "PR_PREVIEW_CHARS",
]
