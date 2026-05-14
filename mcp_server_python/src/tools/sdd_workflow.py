"""SDD workflow tools (Requirements 9.1 – 9.6, Task 14 Phase B10).

Python port of the 9 tools in
``mcp_server_node/src/tools/SDDWorkflowTools.js``. Tool names, input
schemas, and output shapes match the Node.js source so the parity
framework can compare results side-by-side.

Tool overview
-------------

Workflow catalogue (filesystem-backed):

* ``list_sdd_workflows`` — walk ``sdd_framework/workflows/`` for
  ``*.md`` files and emit a markdown listing. With
  ``include_metadata=True`` each entry also shows the parsed title +
  phase/step counts.

* ``get_sdd_workflow`` — read and render one workflow file's
  title, description, phases, steps, and front-matter metadata.

Session lifecycle (``SessionManager``-backed):

* ``start_sdd_session`` — open a new session for a phase. Returns
  the session id, started timestamp, and Next-Steps hint.

* ``record_sdd_step`` — log step completion against the active
  session. ``tag`` is constrained to the SDD vocabulary.

* ``get_sdd_session`` — read the active session state. Optional
  ``resume`` bumps ``lastActivityAt`` and emits a ``resumed`` event
  in ``history.jsonl``.

* ``complete_sdd_session`` — finalize or abandon the active session.

* ``get_sdd_execution_history`` — render recent sessions from
  ``history.jsonl`` grouped by ``sessionId``. With
  ``analytics=True`` adds a Phases-by-Status table, step-tag
  distribution, average duration, and recent velocity.

Compliance + status:

* ``validate_sdd_compliance`` — content-abstracted SDD checks
  (documentation, error handling, shebang, type hints, naming,
  path abstraction). Mirrors the Node.js
  ``performSDDChecks`` implementation byte-for-byte.

* ``get_sdd_framework_status`` — top-level snapshot: workflow
  count, completed/abandoned/in-progress totals, and the active
  session's progress block.

Degraded-mode contract (Requirement 1.7)
----------------------------------------

* The session tools (``start_*``, ``record_*``, ``get_sdd_session``,
  ``complete_*``, ``get_sdd_execution_history``,
  ``get_sdd_framework_status``) only need the file-backed
  :class:`~src.sdd.session_manager.SessionManager` and work fully
  even when ``data=None``.

* ``validate_sdd_compliance`` is pure-content (no I/O) so it works
  in degraded mode.

* ``list_sdd_workflows`` / ``get_sdd_workflow`` only need the
  workflows directory on disk. When the directory is missing
  (the AgentCore microVM does not bind-mount ``sdd_framework/``)
  they return a friendly ``[INFO]`` block — a deviation from
  Node.js ``[ERROR]`` chosen because the missing directory is the
  expected state on the hosted Python port. The Node.js error
  shape is preserved for any other failure path.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Literal

from fastmcp import FastMCP

from src.sdd.session_manager import (
    STATUS_ABANDONED,
    STATUS_COMPLETED,
    SDDSession,
    SessionError,
    SessionManager,
)

log = logging.getLogger(__name__)


# ── constants ──────────────────────────────────────────────────────────


#: SDD step tag vocabulary. Mirrors the Node.js ``record_sdd_step``
#: enum exactly so callers see the same allowed values.
TAG_VALUES: tuple[str, ...] = (
    "research",
    "design",
    "implement",
    "configure",
    "validate",
    "document",
    "ingest",
)

#: Content-type hints accepted by ``validate_sdd_compliance``. The
#: ``auto`` value triggers heuristic detection from the content
#: itself.
CONTENT_TYPE_VALUES: tuple[str, ...] = (
    "bash",
    "python",
    "yaml",
    "json",
    "markdown",
    "auto",
)

#: Default location of the workflow specs directory, relative to the
#: project root. Mirrors the Node.js ``WorkflowExecutor`` default.
DEFAULT_WORKFLOWS_DIR: str = "sdd_framework/workflows"

#: Header rendered by every framework-status block. Matches the
#: Node.js ``getFrameworkStatus`` text exactly.
FRAMEWORK_VERSION_LABEL: str = "6.0 Phase 31"


# ── helpers — workflow parsing ────────────────────────────────────


_HEADING_PHASE = re.compile(
    r"^##\s+(?:Phase\s+)?(\d+)[.:\s-]+(.+?)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_HEADING_STEP = re.compile(
    r"^###\s+(?:Step\s+)?(\d+)[.:\s-]+(.+?)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_FRONT_MATTER = re.compile(
    r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL,
)


def _list_workflow_files(workflows_dir: Path) -> list[dict[str, Any]]:
    """List ``*.md`` files in ``workflows_dir`` (sorted alphabetically).

    Each dict has ``name`` (stem), ``path`` (relative posix), and
    ``size`` (bytes). Returns ``[]`` when the directory is missing —
    callers are expected to surface a friendly message.
    """
    if not workflows_dir.is_dir():
        return []
    entries: list[dict[str, Any]] = []
    for md in sorted(workflows_dir.glob("*.md")):
        try:
            size = md.stat().st_size
        except OSError:
            size = 0
        entries.append(
            {"name": md.stem, "path": md.as_posix(), "size": size}
        )
    return entries


def _parse_workflow_md(content: str, name: str) -> dict[str, Any]:
    """Extract a workflow's title, description, phases, steps, metadata.

    The parser handles the structure the Node.js ``WorkflowExecutor``
    expects: optional YAML front-matter, a ``# Title`` H1, free-text
    description up to the first ``## `` heading, ``## Phase N: name``
    headings, and ``### Step N: name`` headings. Anything missing is
    omitted from the result rather than raising.
    """
    metadata: dict[str, str] = {}
    body = content

    fm = _FRONT_MATTER.match(content)
    if fm is not None:
        body = content[fm.end():]
        for line in fm.group(1).splitlines():
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                metadata[key] = value

    title = name
    description = ""
    lines = body.splitlines()
    title_idx: int | None = None
    for idx, line in enumerate(lines):
        if line.startswith("# ") and title_idx is None:
            title = line.lstrip("# ").strip() or name
            title_idx = idx
            break

    if title_idx is not None:
        desc_lines: list[str] = []
        for line in lines[title_idx + 1:]:
            if line.startswith("## "):
                break
            desc_lines.append(line)
        description = "\n".join(desc_lines).strip()

    phases: list[dict[str, Any]] = []
    for match in _HEADING_PHASE.finditer(body):
        try:
            number = int(match.group(1))
        except (TypeError, ValueError):
            continue
        phases.append({"number": number, "name": match.group(2).strip()})

    steps: list[dict[str, Any]] = []
    for match in _HEADING_STEP.finditer(body):
        try:
            number = int(match.group(1))
        except (TypeError, ValueError):
            continue
        steps.append(
            {
                "number": number,
                "name": match.group(2).strip(),
                "type": "manual",
                "required": True,
                "description": "",
            }
        )

    return {
        "name": name,
        "title": title,
        "description": description,
        "phases": phases,
        "steps": steps,
        "metadata": metadata,
    }


# ── helpers — SDD checks (validate_sdd_compliance) ───────────────


_HARDCODED_PATH_RE = re.compile(r"(/gpfs/|/scratch/|/home/[a-z]+/)")
_TYPE_HINT_RE = re.compile(r"def \w+\([^)]*:")
_UPPER_CASE_VAR_RE = re.compile(r"[A-Z]{2,}_[A-Z]+")


def _detect_content_type(content: str) -> str:
    """Heuristic content-type detection used when ``content_type='auto'``.

    Mirrors the spirit of the Node.js ``ContentResolver`` auto branch
    without re-implementing its full file-extension lookup. Pure
    string analysis — no I/O — so it works in the AgentCore microVM.
    """
    stripped = content.lstrip()
    if stripped.startswith("#!/"):
        first_line = stripped.split("\n", 1)[0].lower()
        if "python" in first_line:
            return "python"
        return "bash"
    if stripped.startswith("{") and stripped.endswith("}"):
        return "json"
    if "def " in content or "import " in content or "class " in content:
        return "python"
    if "function " in content or "const " in content:
        return "javascript"
    if content.startswith("---") or "\n---\n" in content[:100]:
        return "yaml"
    if content.startswith("#") and "\n## " in content:
        return "markdown"
    return "text"


def _perform_sdd_checks(
    content: str, content_type: str
) -> list[dict[str, str]]:
    """Run the Node.js ``performSDDChecks`` battery against ``content``.

    Each entry is ``{name, status, message}`` with ``status`` in
    ``{"pass", "warn", "fail"}``. Pure-string — no I/O.
    """
    checks: list[dict[str, str]] = []

    has_comments = (
        "#" in content
        or "//" in content
        or '"""' in content
        or "/*" in content
    )
    checks.append(
        {
            "name": "Documentation",
            "status": "pass" if has_comments else "warn",
            "message": (
                "Code contains comments/documentation"
                if has_comments
                else "Consider adding documentation"
            ),
        }
    )

    if content_type == "bash":
        has_set_e = "set -e" in content or "set -o errexit" in content
        has_err_chk = "err_chk" in content or "$?" in content
        ok = has_set_e or has_err_chk
        checks.append(
            {
                "name": "Error Handling",
                "status": "pass" if ok else "warn",
                "message": (
                    "Error handling detected"
                    if ok
                    else "Consider adding error handling (set -e or err_chk)"
                ),
            }
        )

        has_shebang = content.startswith("#!/")
        checks.append(
            {
                "name": "Shebang",
                "status": "pass" if has_shebang else "fail",
                "message": (
                    "Valid shebang present"
                    if has_shebang
                    else "Missing shebang (#!/bin/bash)"
                ),
            }
        )

    if content_type == "python":
        has_if_main = "if __name__" in content
        checks.append(
            {
                "name": "Entry Point",
                "status": "pass" if has_if_main else "warn",
                "message": (
                    "Has if __name__ guard"
                    if has_if_main
                    else 'Consider adding if __name__ == "__main__" guard'
                ),
            }
        )

        has_type_hints = bool(_TYPE_HINT_RE.search(content))
        checks.append(
            {
                "name": "Type Hints",
                "status": "pass" if has_type_hints else "warn",
                "message": (
                    "Type hints detected"
                    if has_type_hints
                    else "Consider adding type hints"
                ),
            }
        )

    has_upper_case = bool(_UPPER_CASE_VAR_RE.search(content))
    checks.append(
        {
            "name": "Naming Conventions",
            "status": "pass",
            "message": (
                "Uses UPPER_CASE for constants (NCO style)"
                if has_upper_case
                else "Standard naming detected"
            ),
        }
    )

    has_hardcoded = bool(_HARDCODED_PATH_RE.search(content))
    checks.append(
        {
            "name": "Path Abstraction",
            "status": "fail" if has_hardcoded else "pass",
            "message": (
                "Contains hardcoded paths - use environment variables"
                if has_hardcoded
                else "No hardcoded paths detected"
            ),
        }
    )

    return checks


def _check_icon(status: str) -> str:
    """ASCII status icon used in compliance output."""
    if status == "pass":
        return "[OK]"
    if status == "warn":
        return "[WARN]"
    return "[ERROR]"


# ── helpers — history rendering ────────────────────────────────────


def _group_history(events: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Bucket flat history events by ``sessionId`` (insertion order)."""
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        sid = event.get("sessionId") or ""
        if not sid:
            continue
        buckets[sid].append(event)
    return buckets


def _session_status(events: list[dict[str, Any]]) -> str:
    """Derive a session's terminal status from its event list."""
    for event in events:
        if event.get("event") == "completed":
            return STATUS_COMPLETED
        if event.get("event") == "abandoned":
            return STATUS_ABANDONED
    return "in_progress"


def _status_icon(status: str) -> str:
    if status == STATUS_COMPLETED:
        return "[OK]"
    if status == STATUS_ABANDONED:
        return "[!!]"
    return "[..]"


def _parse_duration_minutes(duration: str | None) -> int | None:
    """Pull a minute count from strings like ``"1h 22m"`` or ``"15m"``."""
    if not duration:
        return None
    total = 0
    matched = False
    hours = re.search(r"(\d+)\s*h", duration)
    if hours:
        total += int(hours.group(1)) * 60
        matched = True
    minutes = re.search(r"(\d+)\s*m", duration)
    if minutes:
        total += int(minutes.group(1))
        matched = True
    return total if matched else None


def _render_history(
    events: list[dict[str, Any]],
    *,
    limit: int,
    analytics: bool,
) -> str:
    """Render ``get_sdd_execution_history`` output (Node.js parity)."""
    output_lines = ["# SDD Session History\n"]
    if not events:
        output_lines.append("*No session history found.*")
        return "\n".join(output_lines) + "\n"

    sessions = _group_history(events)
    session_entries = list(sessions.items())
    display_entries = (
        session_entries[-limit:] if analytics else session_entries
    )
    output_lines.append(
        f"Showing {len(display_entries)} recent sessions\n"
    )

    for session_id, session_events in display_entries:
        started = next(
            (e for e in session_events if e.get("event") == "started"), None
        )
        completed = next(
            (e for e in session_events if e.get("event") == "completed"),
            None,
        )
        abandoned = next(
            (e for e in session_events if e.get("event") == "abandoned"),
            None,
        )
        steps = [
            e for e in session_events if e.get("event") == "step_completed"
        ]
        status = _session_status(session_events)
        icon = _status_icon(status)
        phase = (started or {}).get("phase") or "unknown"

        output_lines.append(f"## {icon} {phase}")
        output_lines.append(f"- **Session**: {session_id}")
        output_lines.append(f"- **Status**: {status}")
        output_lines.append(
            f"- **Started**: {(started or {}).get('timestamp') or 'unknown'}"
        )
        if completed is not None:
            output_lines.append(
                f"- **Completed**: {completed.get('timestamp')}"
            )
            output_lines.append(
                f"- **Duration**: {completed.get('duration') or 'unknown'}"
            )
            if completed.get("summary"):
                output_lines.append(f"- **Summary**: {completed['summary']}")
        if abandoned is not None and completed is None:
            output_lines.append(
                f"- **Abandoned**: {abandoned.get('timestamp')}"
            )
            if abandoned.get("reason"):
                output_lines.append(
                    f"- **Reason**: {abandoned['reason']}"
                )
        if steps:
            output_lines.append(f"- **Steps Completed**: {len(steps)}")
        output_lines.append("")

    if analytics:
        output_lines.append("---\n")
        output_lines.extend(
            _render_analytics_block(session_entries).splitlines()
        )

    return "\n".join(output_lines).rstrip() + "\n"


def _render_analytics_block(
    session_entries: list[tuple[str, list[dict[str, Any]]]],
) -> str:
    """Compute counts/duration/velocity blocks rendered with ``analytics=True``."""
    completed_count = 0
    abandoned_count = 0
    in_progress_count = 0
    tag_counts: dict[str, int] = defaultdict(int)
    durations: list[int] = []
    steps_per_session: list[int] = []

    for _, session_events in session_entries:
        completed = any(
            e.get("event") == "completed" for e in session_events
        )
        abandoned = any(
            e.get("event") == "abandoned" for e in session_events
        )
        steps = [
            e for e in session_events if e.get("event") == "step_completed"
        ]
        if completed:
            completed_count += 1
        elif abandoned:
            abandoned_count += 1
        else:
            in_progress_count += 1
        steps_per_session.append(len(steps))
        for step in steps:
            tag_counts[step.get("tag") or "unknown"] += 1
        if completed:
            completed_event = next(
                (e for e in session_events if e.get("event") == "completed"),
                None,
            )
            duration = _parse_duration_minutes(
                (completed_event or {}).get("duration")
            )
            if duration is not None:
                durations.append(duration)

    out = ["# Session Analytics\n"]
    out.append("## Phases by Status\n")
    out.append("| Status | Count |")
    out.append("|--------|-------|")
    out.append(f"| Completed | {completed_count} |")
    out.append(f"| Abandoned | {abandoned_count} |")
    out.append(f"| In Progress | {in_progress_count} |")
    out.append(f"| **Total** | **{len(session_entries)}** |\n")

    total_steps = sum(tag_counts.values())
    if total_steps > 0:
        out.append("## Step Tag Distribution\n")
        out.append("| Tag | Count | Percent |")
        out.append("|-----|-------|--------|")
        sorted_tags = sorted(
            tag_counts.items(), key=lambda kv: kv[1], reverse=True
        )
        for tag, count in sorted_tags:
            percent = round((count / total_steps) * 100)
            out.append(f"| {tag} | {count} | {percent}% |")
        out.append(f"| **Total** | **{total_steps}** | |\n")

    if durations:
        avg = sum(durations) / len(durations)
        out.append("## Duration\n")
        out.append(f"- Average session duration: {avg:.0f} minutes")
        out.append(
            f"- Shortest: {min(durations)}m, Longest: {max(durations)}m"
        )
        out.append(f"- Sessions with duration data: {len(durations)}\n")

    if steps_per_session:
        recent = steps_per_session[-10:]
        avg = sum(recent) / len(recent)
        out.append("## Velocity\n")
        out.append(
            f"- Average steps per session (last {len(recent)}): {avg:.1f}"
        )
        out.append(
            "- Recent trend: " + ", ".join(str(s) for s in recent) + " steps\n"
        )

    return "\n".join(out)


# ── helpers — formatting (session/workflow output) ──────────────


def _format_session_card(session: SDDSession) -> str:
    """Render the ``# Active SDD Session`` block (used by get_sdd_session)."""
    lines = ["# Active SDD Session\n"]
    lines.append(f"**Session ID**: {session.sessionId}")
    lines.append(f"**Phase**: {session.phase}")
    lines.append(f"**Status**: {session.status}")
    lines.append(f"**Started**: {session.startedAt}")
    lines.append(f"**Last Activity**: {session.lastActivityAt}")
    total = session.totalSteps or "?"
    lines.append(
        f"**Progress**: {len(session.completedSteps)}/{total} steps\n"
    )

    if session.completedSteps:
        lines.append(
            f"## Completed Steps ({len(session.completedSteps)})\n"
        )
        for step in session.completedSteps:
            step_no = step.get("step")
            name = step.get("name", "")
            tag = step.get("tag", "implement")
            done_at = step.get("completedAt", "")
            lines.append(
                f"- [OK] Step {step_no}: {name} ({tag}) — {done_at}"
            )
            if step.get("notes"):
                lines.append(f"  _{step['notes']}_")
        lines.append("")

    if session.skippedSteps:
        lines.append(f"## Skipped Steps ({len(session.skippedSteps)})\n")
        for skip in session.skippedSteps:
            step_no = skip.get("step")
            reason = skip.get("reason", "")
            lines.append(f"- [--] Step {step_no}: {reason}")
        lines.append("")

    if session.blockers:
        lines.append("## Blockers\n")
        for b in session.blockers:
            label = (
                b.get("description")
                if isinstance(b, dict)
                else str(b)
            )
            lines.append(f"- [!!] {label}")
        lines.append("")

    if session.notes:
        lines.append(f"**Notes**: {session.notes}")

    return "\n".join(lines).rstrip() + "\n"


def _error_text(message: str) -> str:
    return f"[ERROR] {message}\n"


def _info_text(message: str) -> str:
    return f"[INFO] {message}\n"


# ── tool implementations ──────────────────────────────────────────


def _tool_list_workflows(
    workflows_dir: Path, *, include_metadata: bool
) -> str:
    files = _list_workflow_files(workflows_dir)
    if not files:
        return (
            "# Available SDD Workflows\n\n"
            f"{_info_text(f'Workflows directory not available: {workflows_dir}')}"
            "\nThe hosted Python runtime does not bind-mount the "
            "`sdd_framework/` tree. Catalogue tools require running with "
            "the workflow specs on disk.\n"
        )

    lines = ["# Available SDD Workflows\n", f"Found {len(files)} workflows\n"]
    for entry in files:
        lines.append(f"## {entry['name']}")
        lines.append(f"- **Path**: {entry['path']}")
        lines.append(f"- **Size**: {entry['size']} bytes")
        if include_metadata:
            try:
                content = (workflows_dir / f"{entry['name']}.md").read_text(
                    encoding="utf-8"
                )
                parsed = _parse_workflow_md(content, entry["name"])
                lines.append(f"- **Title**: {parsed['title']}")
                lines.append(f"- **Phases**: {len(parsed['phases'])}")
                lines.append(f"- **Steps**: {len(parsed['steps'])}")
            except OSError as exc:
                lines.append(f"- **Error**: Could not parse metadata ({exc})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _tool_get_workflow(workflows_dir: Path, *, workflow_name: str) -> str:
    if not workflow_name:
        return _error_text("Failed to get workflow: workflow_name is required")

    target = workflows_dir / f"{workflow_name}.md"
    if not target.is_file():
        return _error_text(
            f"Failed to get workflow: workflow not found ({workflow_name})"
        )

    try:
        content = target.read_text(encoding="utf-8")
    except OSError as exc:
        return _error_text(f"Failed to get workflow: {exc}")

    parsed = _parse_workflow_md(content, workflow_name)
    lines = [f"# {parsed['title']}\n"]
    lines.append(f"**Workflow**: {parsed['name']}\n")

    if parsed["description"]:
        lines.append("## Description")
        lines.append(parsed["description"])
        lines.append("")

    phases = parsed["phases"]
    if phases:
        lines.append(f"## Phases ({len(phases)})\n")
        for phase in phases:
            lines.append(f"{phase['number']}. {phase['name']}")
        lines.append("")

    steps = parsed["steps"]
    if steps:
        lines.append(f"## Steps ({len(steps)})\n")
        for step in steps:
            lines.append(f"### Step {step['number']}: {step['name']}")
            lines.append(f"- **Type**: {step['type']}")
            lines.append(f"- **Required**: {step['required']}")
            if step.get("description"):
                desc = step["description"][:200]
                lines.append(f"- **Description**: {desc}...")
            lines.append("")

    metadata = parsed["metadata"]
    if metadata:
        lines.append("## Metadata\n")
        for key, value in metadata.items():
            lines.append(f"- **{key}**: {value}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _tool_start_session(
    session: SessionManager,
    *,
    phase: str,
    notes: str | None,
    total_steps: int,
) -> str:
    try:
        sdd_session = session.start_session(
            phase, total_steps=total_steps, notes=notes
        )
    except SessionError as exc:
        return _error_text(f"Failed to start session: {exc}")

    lines = ["# SDD Session Started\n"]
    lines.append(f"**Session ID**: {sdd_session.sessionId}")
    lines.append(f"**Phase**: {sdd_session.phase}")
    lines.append(f"**Started**: {sdd_session.startedAt}")
    lines.append(
        f"**Total Steps**: {sdd_session.totalSteps or 'unknown'}"
    )
    if sdd_session.notes:
        lines.append(f"**Notes**: {sdd_session.notes}")
    lines.append("")
    lines.append("## Next Steps\n")
    lines.append(
        "- Use `record_sdd_step` to mark steps complete as you work"
    )
    lines.append("- Use `get_sdd_session` to check current progress")
    lines.append("- Use `complete_sdd_session` when finished")
    return "\n".join(lines).rstrip() + "\n"


def _tool_get_execution_history(
    session: SessionManager,
    *,
    limit: int,
    workflow_name: str | None,
    analytics: bool,
) -> str:
    try:
        # Mirror the Node.js fetch-more-for-analytics quirk so totals
        # don't get truncated by ``limit`` in the analytics view.
        fetch_limit = 1000 if analytics else max(int(limit), 0)
        events = session.get_history(phase=workflow_name, limit=fetch_limit)
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("Failed to read history")
        return _error_text(f"Failed to get history: {exc}")
    return _render_history(events, limit=int(limit), analytics=analytics)


def _tool_validate_compliance(
    *,
    content: str | None,
    target: str | None,
    framework_version: str,
    content_type: str,
) -> str:
    if content is None and not target:
        return _error_text(
            "Content resolution failed: provide either `content` "
            "(preferred for remote MCP) or `target` (a file path).\n\n"
            "**Tip**: For remote MCP access, use the `content` "
            "parameter instead of `target`.\n"
            "Example: validate_sdd_compliance({ content: \"your code here\" })"
        )

    source: str
    metadata_lines: list[str] = []
    if content is not None:
        source_text = content
        source = "direct"
    else:
        source_text = ""
        source = "path"
        metadata_lines.append(f"**Path**: {target}")
        metadata_lines.append(
            "[INFO] File-path resolution is not available on the "
            "hosted Python runtime. Pass the file body via `content` "
            "for an actual compliance scan."
        )
        return _error_text(
            f"Content resolution failed: file-path mode is not "
            f"supported on the hosted Python runtime ({target}).\n\n"
            "**Tip**: For remote MCP access, pass the body via "
            "`content` instead.\n"
            "Example: validate_sdd_compliance({ content: \"your code here\" })"
        )

    resolved_type = content_type
    if content_type == "auto":
        resolved_type = _detect_content_type(source_text)

    line_count = len(source_text.splitlines())

    lines = ["# SDD Compliance Validation\n"]
    lines.append(f"**Framework Version**: {framework_version}")
    lines.append(f"**Content Type**: {resolved_type}")
    lines.append(f"**Source**: {source}")
    if metadata_lines:
        lines.extend(metadata_lines)
    lines.append(f"**Lines**: {line_count}")
    lines.append("")
    lines.append("## Validation Results\n")

    checks = _perform_sdd_checks(source_text, resolved_type)
    for check in checks:
        lines.append(
            f"- {_check_icon(check['status'])} **{check['name']}**: "
            f"{check['message']}"
        )

    lines.append("")
    lines.append("## Summary\n")
    passed = sum(1 for c in checks if c["status"] == "pass")
    warnings = sum(1 for c in checks if c["status"] == "warn")
    failed = sum(1 for c in checks if c["status"] == "fail")
    lines.append(f"- Passed: {passed}")
    lines.append(f"- Warnings: {warnings}")
    lines.append(f"- Failed: {failed}")
    return "\n".join(lines).rstrip() + "\n"


def _tool_get_framework_status(
    session: SessionManager,
    workflows_dir: Path,
    *,
    detailed: bool,
) -> str:
    files = _list_workflow_files(workflows_dir)
    history_events = session.get_history(limit=1000)
    grouped = _group_history(history_events)
    completed_total = 0
    abandoned_total = 0
    for events in grouped.values():
        if any(e.get("event") == "completed" for e in events):
            completed_total += 1
        elif any(e.get("event") == "abandoned" for e in events):
            abandoned_total += 1
    active = session.get_session_state()

    lines = ["# SDD Framework Status\n"]
    lines.append(f"**Version**: {FRAMEWORK_VERSION_LABEL}")
    lines.append("**Status**: Operational")
    lines.append("**Execution Model**: Session-Oriented Tracking\n")

    lines.append("## Components\n")
    lines.append(f"- **Available Workflows**: {len(files)}")
    lines.append(f"- **Total Sessions**: {len(grouped)}")
    lines.append(f"- **Completed**: {completed_total}")
    lines.append(f"- **Abandoned**: {abandoned_total}\n")

    if active is not None:
        progress_total = active.totalSteps or "?"
        lines.append("## Active Session\n")
        lines.append(f"- **Session ID**: {active.sessionId}")
        lines.append(f"- **Phase**: {active.phase}")
        lines.append(
            f"- **Progress**: "
            f"{len(active.completedSteps)}/{progress_total} steps"
        )
        lines.append(f"- **Started**: {active.startedAt}")
        lines.append(f"- **Last Activity**: {active.lastActivityAt}\n")
    else:
        lines.append("## Active Session\n\n*No active session*\n")

    if detailed:
        lines.append("## Session Tools\n")
        lines.append(
            "- [OK] `start_sdd_session` — Activate a phase for tracking"
        )
        lines.append("- [OK] `record_sdd_step` — Record step completion")
        lines.append(
            "- [OK] `get_sdd_session` — Check current session state"
        )
        lines.append("- [OK] `complete_sdd_session` — Finalize session")
        lines.append(
            "- [OK] `get_sdd_execution_history` — Query JSONL history\n"
        )
        lines.append("## Preserved Infrastructure\n")
        lines.append(
            "- [..] ISD approval (dormant — reserved for Phase 4C USD)"
        )
        lines.append(
            "- [..] WorkflowExecutor (filesystem-backed; degraded on "
            "AgentCore microVM)"
        )
        lines.append("- [OK] SpecificationParser (active)")
        lines.append("- [OK] SelfModificationEngine (available)\n")

        if grouped:
            lines.append("## Recent Sessions\n")
            recent = list(grouped.items())[-5:]
            for sid, events in recent:
                started = next(
                    (e for e in events if e.get("event") == "started"), None
                )
                step_count = sum(
                    1 for e in events if e.get("event") == "step_completed"
                )
                status = _session_status(events)
                icon = _status_icon(status)
                phase = (started or {}).get("phase") or sid
                lines.append(
                    f"- {icon} {phase} — {step_count} steps ({status})"
                )

    return "\n".join(lines).rstrip() + "\n"


def _tool_record_step(
    session: SessionManager,
    *,
    step: int,
    name: str,
    tag: str,
    notes: str,
) -> str:
    try:
        sdd_session = session.record_step(step, name, tag, notes)
    except SessionError as exc:
        return _error_text(f"Failed to record step: {exc}")

    lines = [f"# Step {step} Recorded\n"]
    lines.append(f"**Step**: {step} — {name}")
    lines.append(f"**Tag**: {tag}")
    if notes:
        lines.append(f"**Notes**: {notes}")
    lines.append("")
    lines.append("## Session Progress\n")
    lines.append(f"- **Phase**: {sdd_session.phase}")
    total = sdd_session.totalSteps or "?"
    lines.append(
        f"- **Completed**: {len(sdd_session.completedSteps)}/{total} steps"
    )
    lines.append(f"- **Skipped**: {len(sdd_session.skippedSteps)}\n")

    if sdd_session.completedSteps:
        lines.append("### Completed Steps\n")
        for step_record in sdd_session.completedSteps:
            step_no = step_record.get("step")
            step_name = step_record.get("name", "")
            step_tag = step_record.get("tag", "implement")
            lines.append(
                f"- [OK] Step {step_no}: {step_name} ({step_tag})"
            )
    return "\n".join(lines).rstrip() + "\n"


def _tool_get_session(
    session: SessionManager, *, resume: bool
) -> str:
    try:
        if resume:
            sdd_session = session.resume_session()
        else:
            sdd_session = session.get_session_state()
    except SessionError as exc:
        return _error_text(f"Failed to get session: {exc}")

    if sdd_session is None:
        return (
            "# No Active Session\n\n"
            "No SDD session is currently active. Use "
            "`start_sdd_session` to begin one.\n"
        )

    return _format_session_card(sdd_session)


def _tool_complete_session(
    session: SessionManager,
    *,
    summary: str,
    abandon: bool,
    reason: str,
) -> str:
    try:
        if abandon:
            sdd_session = session.abandon_session(reason)
        else:
            sdd_session = session.complete_session(summary)
    except SessionError as exc:
        verb = "abandon" if abandon else "complete"
        return _error_text(f"Failed to {verb} session: {exc}")

    action = "Abandoned" if abandon else "Completed"
    lines = [f"# Session {action}\n"]
    lines.append(f"**Session ID**: {sdd_session.sessionId}")
    lines.append(f"**Phase**: {sdd_session.phase}")
    lines.append(f"**Status**: {sdd_session.status}")
    lines.append(f"**Started**: {sdd_session.startedAt}")
    if abandon:
        lines.append(
            f"**Abandoned**: {sdd_session.abandonedAt}"
        )
        if reason:
            lines.append(f"**Reason**: {reason}")
    else:
        lines.append(f"**Completed**: {sdd_session.completedAt}")
        if summary:
            lines.append(f"**Summary**: {summary}")
    lines.append("")
    lines.append("## Final State\n")
    lines.append(
        f"- Steps Completed: {len(sdd_session.completedSteps)}"
    )
    lines.append(
        f"- Steps Skipped: {len(sdd_session.skippedSteps)}"
    )
    total = sdd_session.totalSteps or "unknown"
    lines.append(f"- Total Steps: {total}")
    return "\n".join(lines).rstrip() + "\n"


# ── public entrypoint ──────────────────────────────────────────────


def register(
    mcp: FastMCP,
    data: Any = None,
    *,
    session_manager: SessionManager | None = None,
    workflows_dir: str | Path | None = None,
) -> None:
    """Register all 9 SDD workflow tools on ``mcp``.

    Parameters
    ----------
    mcp
        The FastMCP server instance.
    data
        Unused by this module — kept in the signature for the
        uniform ``register(mcp, data)`` contract that
        ``mcp_server._register_module`` invokes. SDD tools work in
        full degraded mode (no Neptune, no OpenSearch) because they
        only need local file state.
    session_manager
        Optional :class:`SessionManager` for tests to inject a
        tmp-dir-backed manager. When ``None`` the default
        ``sdd_framework/execution_state`` location is used.
    workflows_dir
        Optional override for the workflow specs directory. When
        ``None`` defaults to ``sdd_framework/workflows`` (the Node.js
        WorkflowExecutor convention). The directory is allowed to be
        missing on the hosted Python runtime — listing tools degrade
        with an ``[INFO]`` block.
    """
    del data  # explicitly unused — kept for register-signature parity
    session = session_manager or SessionManager()
    workflows_path = Path(workflows_dir or DEFAULT_WORKFLOWS_DIR).resolve()

    @mcp.tool(
        name="list_sdd_workflows",
        description=(
            "List all available SDD framework workflows."
        ),
    )
    async def list_sdd_workflows(include_metadata: bool = False) -> str:
        return _tool_list_workflows(
            workflows_path, include_metadata=include_metadata
        )

    @mcp.tool(
        name="get_sdd_workflow",
        description=(
            "Get detailed information about a specific SDD workflow."
        ),
    )
    async def get_sdd_workflow(workflow_name: str) -> str:
        return _tool_get_workflow(
            workflows_path, workflow_name=workflow_name
        )

    @mcp.tool(
        name="start_sdd_session",
        description=(
            "Start a new SDD session for a phase. Activates tracking "
            "for step completions."
        ),
    )
    async def start_sdd_session(
        phase: str,
        notes: str | None = None,
        total_steps: int = 0,
    ) -> str:
        return _tool_start_session(
            session,
            phase=phase,
            notes=notes,
            total_steps=max(int(total_steps), 0),
        )

    @mcp.tool(
        name="get_sdd_execution_history",
        description=(
            "Get history of SDD workflow executions. Pass "
            "`analytics=true` for phase status counts, step tag "
            "distribution, velocity trends, and average duration."
        ),
    )
    async def get_sdd_execution_history(
        limit: int = 10,
        workflow_name: str | None = None,
        analytics: bool = False,
    ) -> str:
        return _tool_get_execution_history(
            session,
            limit=max(int(limit), 1),
            workflow_name=workflow_name,
            analytics=analytics,
        )

    @mcp.tool(
        name="validate_sdd_compliance",
        description=(
            "Validate code or documentation against SDD framework "
            "standards. Pass `content` for remote MCP access; "
            "`target` is local-only."
        ),
    )
    async def validate_sdd_compliance(
        content: str | None = None,
        target: str | None = None,
        framework_version: str = "4.0",
        content_type: Literal[
            "bash", "python", "yaml", "json", "markdown", "auto"
        ] = "auto",
    ) -> str:
        return _tool_validate_compliance(
            content=content,
            target=target,
            framework_version=framework_version,
            content_type=content_type,
        )

    @mcp.tool(
        name="get_sdd_framework_status",
        description=(
            "Get comprehensive status of SDD framework integration."
        ),
    )
    async def get_sdd_framework_status(detailed: bool = False) -> str:
        return _tool_get_framework_status(
            session, workflows_path, detailed=detailed
        )

    @mcp.tool(
        name="record_sdd_step",
        description=(
            "Record completion of a step in the active SDD session."
        ),
    )
    async def record_sdd_step(
        step: int,
        name: str,
        tag: Literal[
            "research",
            "design",
            "implement",
            "configure",
            "validate",
            "document",
            "ingest",
        ] = "implement",
        notes: str = "",
    ) -> str:
        return _tool_record_step(
            session,
            step=int(step),
            name=name,
            tag=tag,
            notes=notes,
        )

    @mcp.tool(
        name="get_sdd_session",
        description=(
            "Get the current active SDD session state. Pass "
            "`resume=true` to bump lastActivityAt and emit a "
            "`resumed` event."
        ),
    )
    async def get_sdd_session(resume: bool = False) -> str:
        return _tool_get_session(session, resume=resume)

    @mcp.tool(
        name="complete_sdd_session",
        description=(
            "Complete the active SDD session. Pass `abandon=true` "
            "with a `reason` to abandon instead of completing."
        ),
    )
    async def complete_sdd_session(
        summary: str = "",
        abandon: bool = False,
        reason: str = "",
    ) -> str:
        return _tool_complete_session(
            session,
            summary=summary,
            abandon=abandon,
            reason=reason,
        )


__all__ = [
    "register",
    "TAG_VALUES",
    "CONTENT_TYPE_VALUES",
    "DEFAULT_WORKFLOWS_DIR",
    "FRAMEWORK_VERSION_LABEL",
]
