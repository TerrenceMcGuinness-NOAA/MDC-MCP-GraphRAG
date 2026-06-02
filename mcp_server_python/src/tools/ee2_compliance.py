"""EE2 compliance tools (Requirement 1.7, Task 12 Phase B8).

Python port of the 5 tools in
``mcp_server_node/src/tools/EE2ComplianceTools.js``. Tool names and
input schemas match the Node.js ``registerWith`` block exactly so the
parity framework can compare results side-by-side.

Tool overview
-------------

* ``search_ee2_standards`` — semantic search over the
  ``ee2-standards-v5-0-0-enhanced`` vector collection. Vector-backed
  only; degrades to ``[ERROR]`` when ``data`` is unavailable.

* ``analyze_ee2_compliance`` — SME-corrected (Phase 2) compliance
  analysis on a blob of bash / python source. Pure content-based —
  works in degraded mode. Optionally queries vector standards for a
  "Relevant EE2 Standards" appendix when ``vector_db`` is reachable.

* ``generate_compliance_report`` — reference reporting. Pure content-
  based when degraded; pulls standard excerpts from the vector store
  when reachable.

* ``scan_repository_compliance`` — batched scanner over a caller-
  supplied file array. Content-abstracted: the Python port does **not**
  read from ``repository_path`` — that mode is legacy local-filesystem
  behaviour from the Node.js server. Callers passing ``repository_path``
  get a clear ``[ERROR]`` telling them to use ``files`` instead.

* ``extract_code_for_analysis`` — lightweight snippet extractor that
  returns per-category LLM analysis prompts. Also content-abstracted
  in the Python port: ``path`` rejections mirror the scan tool.

SME-corrected behaviour (Phase 2)
---------------------------------

These patterns are the reason the EE2 toolset was extracted into its
own module in the first place, and they are preserved bit-for-bit in
the port:

* ``set -eu`` / ``set -e`` in bash scripts is flagged as an
  **anti-pattern** rather than required. The EE2 standard uses
  ``err_chk`` / ``err_exit`` for controlled error handling.
* A script that sources ``preamble.sh`` **or** calls ``err_chk`` is
  compliant, even without ``set -e``.
* File operations (``cp``, ``mv``, ``ln``) without a trailing
  ``err_chk`` are flagged.
* Unquoted variable references (``$VAR`` outnumbering ``"${VAR}"``)
  are flagged as environment-variable hygiene concerns.

Parity documentation in
``.github/instructions/eib-mcp-tools.instructions.md`` summarizes this
as: "``set -eu`` is NOT required (80% false positive)."

Degraded-mode split (Requirement 1.7)
-------------------------------------

Only ``search_ee2_standards`` strictly requires a vector store; the
other four tools operate on input content and render an ``[INFO]``
note in lieu of the Relevant EE2 Standards section when the vector
store is unavailable. This matches the Node.js initialization
fallback behaviour while making the split explicit rather than
implicit.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Literal

from fastmcp import FastMCP

from src.tenancy.resolver import get_current_tenant_or_none

log = logging.getLogger(__name__)


def _tenant():
    """Return the active tenant or None (for adapter kwarg)."""
    ctx = get_current_tenant_or_none()
    return ctx.tenant if ctx else None


# ── constants ──────────────────────────────────────────────────────────


#: Vector collection that stores the EE2 implementation-standards
#: embeddings. Matches the Node.js ``ee2-standards-v5-0-0-enhanced``
#: hybrid-query target.
EE2_COLLECTION: str = "ee2-standards-v5-0-0-enhanced"

#: Bounds on ``search_ee2_standards``'s ``max_results`` parameter.
#: Matches the Node.js ``minimum`` / ``maximum`` exactly.
SEARCH_RESULTS_MIN: int = 1
SEARCH_RESULTS_MAX: int = 20
SEARCH_RESULTS_DEFAULT: int = 8

#: Bounds on ``scan_repository_compliance``'s ``sample_size`` parameter.
SCAN_SAMPLE_MIN: int = 10
SCAN_SAMPLE_MAX: int = 10_000
SCAN_SAMPLE_DEFAULT: int = 10_000

#: Default ``max_files`` for ``extract_code_for_analysis`` (file-array
#: mode; pathname scanning is not supported on the Python port).
EXTRACT_MAX_FILES_DEFAULT: int = 50

#: Default ``file_pattern`` regex for ``extract_code_for_analysis``.
#: Matches the Node.js default; provided here as an anchor for the
#: schema-parity test.
EXTRACT_FILE_PATTERN_DEFAULT: str = r"\.(sh|py)$"

#: Enum values accepted by ``search_ee2_standards.category`` and the
#: ``generate_compliance_report``'s implicit catalogue. Matches the
#: Node.js ``registerWith`` block's ``category`` enum.
SEARCH_CATEGORY_VALUES: tuple[str, ...] = (
    "environment_variables",
    "workflow_structure",
    "error_handling",
    "file_naming",
    "production_utilities",
    "code_standards",
    "directory_structure",
)

#: Enum values accepted by ``analyze_ee2_compliance.analysis_type``.
#: ``comprehensive`` is the Node.js default; the other values mirror
#: :data:`SEARCH_CATEGORY_VALUES` verbatim.
ANALYSIS_TYPE_VALUES: tuple[str, ...] = (
    "comprehensive",
    "environment_variables",
    "workflow_structure",
    "error_handling",
    "file_naming",
    "production_utilities",
    "code_standards",
    "directory_structure",
)

#: Enum values accepted by ``generate_compliance_report.scope``.
REPORT_SCOPE_VALUES: tuple[str, ...] = ("summary", "detailed", "checklist")

#: Enum values accepted by ``generate_compliance_report.format``.
REPORT_FORMAT_VALUES: tuple[str, ...] = ("markdown", "checklist", "summary")

#: Enum values accepted by each entry of ``scan_repository_compliance.
#: categories``. Note this is a **subset** of
#: :data:`SEARCH_CATEGORY_VALUES` — only 5 categories have scan
#: implementations. Matches Node.js exactly.
SCAN_CATEGORY_VALUES: tuple[str, ...] = (
    "error_handling",
    "environment_variables",
    "file_naming",
    "shebang_compliance",
    "production_utilities",
)

#: Enum values accepted by each entry of
#: ``extract_code_for_analysis.categories``. Smaller still, because
#: each category corresponds to a dedicated LLM prompt in
#: :data:`EE2_ANALYSIS_PROMPTS` below.
EXTRACT_CATEGORY_VALUES: tuple[str, ...] = (
    "output_file_naming",
    "error_handling",
    "shebang_compliance",
    "env_var_validation",
)

#: Enum values accepted by ``extract_code_for_analysis.content_type``.
CONTENT_TYPE_VALUES: tuple[str, ...] = ("bash", "python", "auto")

#: Default ``file_patterns`` for ``scan_repository_compliance``'s local-
#: filesystem mode (which the Python port does not support, but the
#: schema still advertises the defaults for parity).
SCAN_FILE_PATTERNS_DEFAULT: tuple[str, ...] = (
    "**/*.sh",
    "**/*.py",
    "**/JEVS_*",
    "**/exglobal_*",
    "**/*.config",
)


_DEGRADED_VECTOR_MSG = (
    "Vector database unavailable (degraded-mode boot). "
    "search_ee2_standards requires OPENSEARCH_ENDPOINT to be reachable."
)

_INFO_STANDARDS_UNAVAILABLE = (
    "[INFO] Standards context unavailable — vector database not "
    "reachable. Content-based analysis above is still accurate."
)

_ABSTRACTED_SCAN_MSG = (
    "repository_path is not supported on the hosted Python port. "
    "Pass file content directly via the `files` parameter "
    "(array of {name, content} objects) instead."
)

_ABSTRACTED_EXTRACT_MSG = (
    "path is not supported on the hosted Python port. "
    "Pass code directly via the `content` parameter or an array of "
    "{name, content} objects via `files` instead."
)

_REPORT_PASSTHROUGH_NOTE = (
    "## Passthrough Recommendation (Output Naming / COM)\n\n"
    "Run extract_code_for_analysis with categories output_file_naming, "
    "shebang_compliance, env_var_validation on the target repo content "
    "(e.g. scripts/, ush/) to surface COM/COMOUT filename patterns and "
    "env validation that the standard scan does not cover automatically.\n"
)


# ── helpers (private module-level) ─────────────────────────────────────


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(int(value), hi))


def _utc_today_iso_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _error_text(message: str) -> str:
    return f"[ERROR] {message}\n"


def _is_bash_script(content: str) -> bool:
    return bool(re.match(r"^#!/bin/(ba)?sh", content))


def _has_set_eu(content: str) -> bool:
    return bool(re.search(r"set -eu", content))


def _has_set_e(content: str) -> bool:
    return bool(re.search(r"set -e\b", content))


def _has_err_chk(content: str) -> bool:
    return bool(re.search(r"err_chk", content))


def _has_preamble(content: str) -> bool:
    return bool(re.search(r"preamble\.sh", content))


def _has_file_ops(content: str) -> bool:
    return bool(re.search(r"\b(cp|mv|ln)\b", content))


_FILE_OPS_WITHOUT_ERRCHK_RE = re.compile(
    r"\b(cp|mv|ln)\s+[^\n]*\n(?!\s*export\s+err)"
)
_UNQUOTED_VAR_RE = re.compile(r"\$[A-Z_][A-Z0-9_]*")
_QUOTED_VAR_RE = re.compile(r'"\$\{[A-Z_][A-Z0-9_]*\}"')


def _file_ops_without_err_chk(content: str) -> int:
    return len(_FILE_OPS_WITHOUT_ERRCHK_RE.findall(content))


def _count_unquoted_vars(content: str) -> int:
    return len(_UNQUOTED_VAR_RE.findall(content))


def _count_quoted_vars(content: str) -> int:
    return len(_QUOTED_VAR_RE.findall(content))


def _build_standards_query(category: str) -> str:
    """Translate a category name into the same semantic-search query
    the Node.js ``_buildStandardsQuery`` helper uses. Matters for
    parity since the query text is what the vector store sees."""
    queries = {
        "error_handling": (
            "error handling bash scripts set -eu exit codes trap"
        ),
        "environment_variables": (
            "environment variable naming quoting standards ${VAR}"
        ),
        "file_naming": (
            "file naming conventions ex- J- production utilities"
        ),
        "workflow_structure": (
            "workflow structure job scripts directory organization"
        ),
        "production_utilities": (
            "production utilities standard tools logging"
        ),
        "code_standards": (
            "code standards documentation comments best practices"
        ),
        "directory_structure": (
            "directory structure organization requirements"
        ),
    }
    return queries.get(category, category)


def _extract_checklist_items(text: str) -> list[str]:
    """Pull imperative / bulleted items out of a standards document
    body for the ``scope=checklist`` render of
    ``generate_compliance_report``. Mirrors the Node.js
    ``_extractChecklistItems`` helper."""
    items: list[str] = []
    for line in text.splitlines():
        if re.match(r"^[-•*]\s+", line) or re.match(r"^\d+\.\s+", line):
            items.append(re.sub(r"^[-•*\d.]+\s+", "", line).strip())
        elif re.match(
            r"^(Use|Always|Never|Ensure|Check|Verify|Include|Add|Set)\s+",
            line,
            flags=re.IGNORECASE,
        ):
            items.append(line.strip())
    return items[:8]


# ── EE2 analysis prompts (port of EE2AnalysisPrompts.js) ───────────────


#: LLM prompt templates consumed by ``extract_code_for_analysis``. Keys
#: mirror :data:`EXTRACT_CATEGORY_VALUES`. Each entry carries a
#: ``context`` block (what the EE2 standard says), an ``instruction``
#: block (what to check), and an ``sme_corrections`` list (the Phase 2
#: false-positive guard rails).
EE2_ANALYSIS_PROMPTS: dict[str, dict[str, Any]] = {
    "output_file_naming": {
        "context": (
            "EE2 Output File Naming Requirements:\n"
            "- Use periods (.) to separate categories\n"
            "- Use underscores (_) to separate words within same category\n"
            "- Resolution notation: 0p25 not 0.25\n"
            "- Forecast hours: f006 not f6 (padded, with 'f' prefix)\n"
            "- NO uppercase characters in output filenames\n"
            "- NO embedded dates (date goes in directory path)\n"
            "- NO special characters except . and _\n"
            "- NO $job, $envir, $model_ver in final filenames"
        ),
        "instruction": (
            "Analyze the output pattern snippets. For each COMOUT "
            "assignment or cp/mv to COM:\n"
            "1. Identify the final output filename pattern\n"
            "2. Check for uppercase characters (VIOLATION if present)\n"
            "3. Check for embedded dates like YYYYMMDD (VIOLATION if in "
            "filename, OK if in path)\n"
            "4. Check separator usage (periods between categories, "
            "underscores within)\n"
            "5. Check forecast hour format (should be f### like f006)\n"
            "6. Check resolution format (should use 'p' like 0p25)\n\n"
            "Report: COMPLIANT or list specific violations with line "
            "numbers."
        ),
        "sme_corrections": [
            "Uppercase in VARIABLE NAMES (e.g., MODEL=GFS) is NOT a "
            "violation",
            "Only the FINAL resolved filename matters, not intermediate "
            "variables",
            "RTOFS has legacy mixed-case in production - flag but note "
            "exception",
            "Date in DIRECTORY path ($COMOUT/model.YYYYMMDD/) is COMPLIANT",
        ],
    },
    "error_handling": {
        "context": (
            "EE2 Error Handling Requirements:\n"
            "- set -x REQUIRED after shebang for debug logging\n"
            "- set -eu is NOT required (NOT in EE2 standards)\n"
            "- Use err_chk after critical operations\n"
            "- Use err_exit for fatal errors (NOT explicit exit 0/1)\n"
            "- err_chk and err_exit are production utilities"
        ),
        "instruction": (
            "Analyze the error handling snippets:\n"
            "1. Check if 'set -x' is present after shebang (REQUIRED)\n"
            "2. Do NOT flag missing 'set -e' or 'set -eu' (not required)\n"
            "3. Check for 'exit 0' or 'exit 1' usage (should use "
            "err_exit instead)\n"
            "4. Check for err_chk after cp, mv, or script calls\n"
            "5. Note any gaps where err_chk should be added\n\n"
            "Report: List compliant patterns and violations with line "
            "numbers."
        ),
        "sme_corrections": [
            "set -eu is NOT in EE2 standards - do NOT flag as missing",
            "Only set -x is required for debug logging",
            "exit 0/1 should be err_exit, but some legacy patterns "
            "exist",
            "Files using err_chk/err_exit ARE compliant even without "
            "set -e",
        ],
    },
    "shebang_compliance": {
        "context": (
            "EE2 Shebang Requirements:\n"
            "- Shebang MUST be on line 1 (no blank lines before)\n"
            "- Valid shells: #!/bin/bash, #!/bin/sh, #!/bin/ksh\n"
            "- #!/bin/ksh IS allowed for J-jobs (NCO standard)\n"
            "- set -x should follow shortly after shebang"
        ),
        "instruction": (
            "Check the shebang block:\n"
            "1. Is shebang on line 1? (blank line before = VIOLATION)\n"
            "2. Is shell type valid? (bash, sh, ksh all OK)\n"
            "3. Is set -x present in first 10 lines?\n"
            "4. For J-jobs: Is PS4 export present for timing?\n\n"
            "Report: Shebang compliance status with any issues."
        ),
        "sme_corrections": [
            "#!/bin/ksh IS allowed - do NOT flag as non-portable",
            "All of bash, sh, ksh are valid on WCOSS2",
            "J-jobs should have: export PS4='+ $SECONDS + '",
        ],
    },
    "env_var_validation": {
        "context": (
            "EE2 Environment Variable Requirements:\n"
            "- Required vars must use ${VAR:?} for fail-fast\n"
            "- Optional vars should use ${VAR:-default}\n"
            "- Standard vars: PDY, cyc, NET, RUN, COMROOT, etc."
        ),
        "instruction": (
            "Check environment variable usage:\n"
            "1. Are required variables validated with :?\n"
            "2. Are optional variables using :- for defaults\n"
            "3. Are standard EE2 variables used correctly\n\n"
            "Report: Environment variable compliance."
        ),
        "sme_corrections": [
            "Not all variables need :? validation",
            "Focus on critical path variables (COMOUT, DATA, etc.)",
        ],
    },
}


def _generate_analysis_prompt(
    category: str, snippets: list[dict[str, Any]]
) -> dict[str, Any]:
    """Port of the Node.js ``generateAnalysisPrompt`` helper. Returns
    the structured per-category prompt bundle for the host LLM to
    reason over extracted snippets."""
    template = EE2_ANALYSIS_PROMPTS.get(category)
    if template is None:
        return {"error": f"Unknown category: {category}"}
    return {
        "category": category,
        "context": template["context"],
        "instruction": template["instruction"],
        "sme_corrections": list(template["sme_corrections"]),
        "code_snippets": list(snippets),
        "output_format": (
            f"Provide analysis as:\n"
            f"## {category} Analysis\n\n"
            "### Compliant Patterns\n"
            "- [list compliant items with line numbers]\n\n"
            "### Violations Found\n"
            "- [list violations with line numbers and specific issue]\n\n"
            "### Recommendations\n"
            "- [specific fixes needed]"
        ),
    }


# ── code-snippet extractor (port of CodeSnippetExtractor.js) ───────────


#: Regex patterns driving the snippet extractor. Kept aligned with the
#: Node.js ``PATTERNS`` constant so ``extract_code_for_analysis``
#: produces the same hits for the same input.
_SNIPPET_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "output": (
        re.compile(r"\$\{COM(?:OUT|IN)_[A-Z0-9_]+\}[^\n]*"),
        re.compile(r"\$COM(?:OUT|IN)\s*[=/][^\n]*"),
        re.compile(r"COM(?:OUT|IN)[A-Z_]*=\$\{[^}]+\}[^\n]*"),
        re.compile(r"cp\s+[^\n]*\$\{?COM[^\n]*"),
        re.compile(r"mv\s+[^\n]*\$\{?COM[^\n]*"),
        re.compile(r">\s*[\"']?\$\{?COM[^\n]*"),
        re.compile(r"cpreq\s+[^\n]*\$\{?COM[^\n]*"),
        re.compile(r"\$\{COMIN_[A-Z0-9_]+\}[^\n]*"),
    ),
    "error_handling": (
        re.compile(r"set\s+-[xueo]+"),
        re.compile(r"err_chk[^\n]*"),
        re.compile(r"err_exit[^\n]*"),
        re.compile(r"exit\s+[01][^\n]*"),
        re.compile(r"\$\?\s*-ne\s*0[^\n]*"),
        re.compile(r"if\s*\[\s*\$\?\s*[^\]]+\][^\n]*"),
    ),
    "env_vars": (
        re.compile(r"\$\{[A-Z_]+:\?[^}]*\}"),
        re.compile(r"\$\{[A-Z_]+:-[^}]*\}"),
        re.compile(r"export\s+[A-Z_]+=\$\{[^}]+\}"),
    ),
    "shebang": (
        re.compile(
            r"^#!(?:/usr/bin/env\s+|/bin/)(bash|sh|ksh|python[23]?)[^\n]*",
            flags=re.MULTILINE,
        ),
        re.compile(r"^\s*set\s+-[xeuo]+[^\n]*", flags=re.MULTILINE),
        re.compile(r"^\s*export\s+PS4=[^\n]*", flags=re.MULTILINE),
    ),
}


#: Per-extract-category to snippet-extractor category mapping. Mirrors
#: the Node.js translation table in ``extractCodeForAnalysis``.
_EXTRACT_CATEGORY_MAP: dict[str, str] = {
    "output_file_naming": "output",
    "shebang_compliance": "shebang",
    "env_var_validation": "env_vars",
    "error_handling": "error_handling",
}


def _detect_file_type_from_name(filename: str) -> str:
    if re.match(r"^J[A-Z_]+$", filename):
        return "j-job"
    if re.match(r"^ex[a-z_]+\.sh$", filename):
        return "ex-script"
    if re.search(r"\.sh$", filename):
        return "shell"
    if re.search(r"\.py$", filename):
        return "python"
    return "unknown"


def _parse_shebang(line: str) -> str:
    if re.match(r"^#!/usr/bin/env\s+bash", line):
        return "bash"
    if re.match(r"^#!/usr/bin/env\s+sh", line):
        return "sh"
    if re.match(r"^#!/usr/bin/env\s+ksh", line):
        return "ksh"
    if re.match(r"^#!/usr/bin/env\s+python", line):
        return "python"
    if re.match(r"^#!/bin/bash", line):
        return "bash"
    if re.match(r"^#!/bin/sh", line):
        return "sh"
    if re.match(r"^#!/bin/ksh", line):
        return "ksh"
    if re.match(r"^#!.*python", line):
        return "python"
    return "unknown"


def _detect_content_type(content: str, hint: str = "auto") -> str:
    """Infer bash / python / shell content type.

    Mirrors the Node.js ``extractFromContent`` auto-detection logic;
    when the caller passes a concrete ``bash`` / ``python`` hint we
    honour it verbatim.
    """
    if hint != "auto":
        return hint
    if content.startswith("#!/bin/bash") or content.startswith(
        "#!/usr/bin/env bash"
    ):
        return "bash"
    if content.startswith("#!/usr/bin/env python") or content.startswith(
        "#!/usr/bin/python"
    ):
        return "python"
    if re.search(r"^\s*import\s+", content, flags=re.MULTILINE) or re.search(
        r"^\s*def\s+", content, flags=re.MULTILINE
    ):
        return "python"
    if re.search(r"^\s*set\s+-", content, flags=re.MULTILINE) or re.search(
        r"^\s*export\s+", content, flags=re.MULTILINE
    ):
        return "bash"
    return "auto"


def _extract_shebang_block(
    lines: list[str], max_lines: int = 20
) -> dict[str, Any]:
    """Port of ``CodeSnippetExtractor.extractShebangBlock``."""
    block = lines[:max_lines]
    shebang_line = block[0] if block else ""
    has_shebang = bool(re.match(r"^#!", shebang_line))
    has_set_x = any(re.match(r"^\s*set\s+-x", line) for line in block)
    set_x_line = next(
        (
            idx + 1
            for idx, line in enumerate(block)
            if re.match(r"^\s*set\s+-x", line)
        ),
        None,
    )
    return {
        "lines": list(block),
        "shebang": shebang_line if has_shebang else None,
        "shebangType": _parse_shebang(shebang_line),
        "hasSetX": has_set_x,
        "setXLine": set_x_line,
    }


def _extract_patterns(
    content: str,
    lines: list[str],
    patterns: tuple[re.Pattern[str], ...],
    *,
    context_lines: int = 3,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for pat in patterns:
        for match in pat.finditer(content):
            line_num = content[: match.start()].count("\n") + 1
            ctx_start = max(0, line_num - context_lines - 1)
            ctx_end = min(len(lines), line_num + context_lines)
            matches.append(
                {
                    "line": line_num,
                    "match": match.group(0).strip(),
                    "pattern": pat.pattern,
                    "context": "\n".join(lines[ctx_start:ctx_end]),
                }
            )
    # Dedupe by line number, preserve lowest-numbered match per line.
    seen: set[int] = set()
    deduped: list[dict[str, Any]] = []
    for m in sorted(matches, key=lambda m: m["line"]):
        if m["line"] in seen:
            continue
        seen.add(m["line"])
        deduped.append(m)
    return deduped


def _extract_from_content(
    *,
    content: str,
    filename: str = "direct_content",
    content_type_hint: str = "auto",
    categories: list[str],
) -> dict[str, Any]:
    """Extract snippets from a single content blob.

    Returns a structure matching the Node.js ``extractFromContent``
    output: a per-category list of pattern hits plus a ``shebangBlock``
    summary suitable for rendering in the tool response.
    """
    lines = content.split("\n")
    content_type = _detect_content_type(content, content_type_hint)
    result: dict[str, Any] = {
        "filename": filename,
        "fileType": "shell" if content_type == "bash" else content_type,
        "lineCount": len(lines),
        "snippets": {},
        "source": "direct" if filename == "direct_content" else "files_array",
    }
    result["shebangBlock"] = _extract_shebang_block(lines)
    for category in categories:
        mapped = _EXTRACT_CATEGORY_MAP.get(category, category)
        patterns = _SNIPPET_PATTERNS.get(mapped)
        if patterns is None:
            result["snippets"][mapped] = []
            continue
        result["snippets"][mapped] = _extract_patterns(
            content, lines, patterns
        )
    return result


# ── public entrypoint ──────────────────────────────────────────────────


def register(mcp: FastMCP, data: Any = None, *, catalog: "Any | None" = None) -> None:
    """Register all 5 EE2 compliance tools on ``mcp``.

    Parameters
    ----------
    mcp
        The FastMCP server instance.
    data
        ``UnifiedDataAccess``-shaped facade. ``None`` triggers
        degraded-mode for ``search_ee2_standards`` (returns
        ``[ERROR]``). The other four content-scanning tools work
        regardless of ``data`` — they emit an ``[INFO]`` footer when
        the vector store is missing but do not fail.
    """
    from src.tenancy.runtime import get_catalog as _get_catalog
    catalog = catalog or _get_catalog()
    from src.tools._tenant_helper import run_tenant_scoped

    @mcp.tool(
        name="search_ee2_standards",
        description=(
            "Search EE2 compliance standards and documentation via "
            "semantic search over the ee2-standards-v5-0-0-enhanced "
            "collection."
        ),
    )
    async def search_ee2_standards(
        query: str,
        category: Literal[
            "environment_variables",
            "workflow_structure",
            "error_handling",
            "file_naming",
            "production_utilities",
            "code_standards",
            "directory_structure",
        ]
        | None = None,
        max_results: int = SEARCH_RESULTS_DEFAULT,
        include_examples: bool = True,
        tenant_id: str | None = None,
    ) -> str:
        return await run_tenant_scoped(
            tenant_id, catalog,
            lambda: _tool_search_ee2_standards(
                data, query=query, category=category,
                max_results=_clamp(max_results, SEARCH_RESULTS_MIN, SEARCH_RESULTS_MAX),
                include_examples=include_examples,
            ),
        )

    @mcp.tool(
        name="analyze_ee2_compliance",
        description=(
            "Analyze code or documentation for EE2 compliance using "
            "Phase 2 SME-corrected patterns (set -eu and set -e are "
            "NOT required; err_chk / err_exit is the correct "
            "pattern)."
        ),
    )
    async def analyze_ee2_compliance(
        content: str,
        analysis_type: Literal[
            "comprehensive",
            "environment_variables",
            "workflow_structure",
            "error_handling",
            "file_naming",
            "production_utilities",
            "code_standards",
            "directory_structure",
        ] = "comprehensive",
        include_recommendations: bool = True,
    ) -> str:
        return await _tool_analyze_ee2_compliance(
            data,
            content=content,
            analysis_type=analysis_type,
            include_recommendations=include_recommendations,
        )

    @mcp.tool(
        name="generate_compliance_report",
        description=(
            "Generate comprehensive EE2 compliance report with "
            "selectable scope and format. Emits summary / detailed / "
            "checklist renderings over one or more standard "
            "categories."
        ),
    )
    async def generate_compliance_report(
        scope: Literal["summary", "detailed", "checklist"] = "summary",
        categories: list[str] | None = None,
        format: Literal["markdown", "checklist", "summary"] = "markdown",
    ) -> str:
        return await _tool_generate_compliance_report(
            data,
            scope=scope,
            categories=list(categories or []),
            fmt=format,
        )

    @mcp.tool(
        name="scan_repository_compliance",
        description=(
            "Scan a batch of files for EE2 compliance issues. Pass "
            "files directly via the `files` array (each item is "
            "{name, content} with an optional `path` field). Uses "
            "Phase 2 SME-corrected patterns to avoid false positives."
        ),
    )
    async def scan_repository_compliance(
        files: list[dict[str, Any]] | None = None,
        repository_path: str | None = None,
        file_patterns: list[str] | None = None,
        sample_size: int = SCAN_SAMPLE_DEFAULT,
        categories: list[
            Literal[
                "error_handling",
                "environment_variables",
                "file_naming",
                "shebang_compliance",
                "production_utilities",
            ]
        ]
        | None = None,
    ) -> str:
        return await _tool_scan_repository_compliance(
            data,
            files=list(files or []),
            repository_path=repository_path,
            file_patterns=list(file_patterns or SCAN_FILE_PATTERNS_DEFAULT),
            sample_size=_clamp(
                sample_size, SCAN_SAMPLE_MIN, SCAN_SAMPLE_MAX
            ),
            categories=list(categories or SCAN_CATEGORY_VALUES),
        )

    @mcp.tool(
        name="extract_code_for_analysis",
        description=(
            "Extract code snippets from content (bash / python) for "
            "EE2 compliance analysis. Returns structured snippets + "
            "per-category LLM prompts for passthrough reasoning. "
            "Use `content` for a single blob or `files` for a batch."
        ),
    )
    async def extract_code_for_analysis(
        content: str | None = None,
        files: list[dict[str, Any]] | None = None,
        path: str | None = None,
        content_type: Literal["bash", "python", "auto"] = "auto",
        categories: list[
            Literal[
                "output_file_naming",
                "error_handling",
                "shebang_compliance",
                "env_var_validation",
            ]
        ]
        | None = None,
        file_pattern: str = EXTRACT_FILE_PATTERN_DEFAULT,
        max_files: int = EXTRACT_MAX_FILES_DEFAULT,
    ) -> str:
        return await _tool_extract_code_for_analysis(
            content=content,
            files=list(files or []),
            path=path,
            content_type=content_type,
            categories=list(
                categories or ("output_file_naming", "error_handling")
            ),
            file_pattern=file_pattern,
            max_files=max(1, int(max_files)),
        )

    log.info(
        "registered ee2_compliance tools: search_ee2_standards, "
        "analyze_ee2_compliance, generate_compliance_report, "
        "scan_repository_compliance, extract_code_for_analysis"
    )


# ── search_ee2_standards ───────────────────────────────────────────────


async def _tool_search_ee2_standards(
    data: Any,
    *,
    query: str,
    category: str | None,
    max_results: int,
    include_examples: bool,
) -> str:
    if not query or not query.strip():
        return _error_text("query is required.")
    if data is None or getattr(data, "vector_db", None) is None:
        return _error_text(_DEGRADED_VECTOR_MSG)

    enhanced_query = (
        f"{query} {category} EE2 compliance"
        if category
        else f"{query} EE2 compliance"
    )
    try:
        results = await data.vector_db.query(
            EE2_COLLECTION,
            enhanced_query,
            k=max_results,
            similarity_threshold=0.1,
            include_graph=False,
            tenant=_tenant(),
        )
    except Exception as exc:
        log.warning("search_ee2_standards failed: %s", exc)
        return _error_text(f"search_ee2_standards failed: {exc}")

    lines: list[str] = [f"# EE2 Standards Search: {query}", ""]
    if category:
        lines.append(f"**Category:** {category}")
        lines.append("")
    lines.append(f"Found {len(results or [])} standards")
    lines.append("")

    if not results:
        lines.append(f'No EE2 standards found matching: "{query}"')
        return "\n".join(lines) + "\n"

    for idx, result in enumerate(results, start=1):
        lines.append(f"## Standard {idx}")
        metadata = result.get("metadata") or {}
        score = result.get("score")
        distance = result.get("distance")
        if distance is None and score is not None:
            distance = float(score)
        if distance is not None:
            # Node.js renders ``distance * 100`` as similarity %.
            lines.append(f"**Similarity:** {float(distance) * 100:.1f}%")
        if metadata.get("category"):
            lines.append(f"**Category:** {metadata['category']}")
        lines.append("")
        doc = (
            result.get("document")
            or result.get("text")
            or result.get("content")
            or ""
        )
        lines.append(doc)
        lines.append("")
        if include_examples and metadata.get("example"):
            lines.append("**Example:**")
            lines.append("```")
            lines.append(str(metadata["example"]))
            lines.append("```")
            lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ── analyze_ee2_compliance ─────────────────────────────────────────────


async def _tool_analyze_ee2_compliance(
    data: Any,
    *,
    content: str,
    analysis_type: str,
    include_recommendations: bool,
) -> str:
    if content is None or not content.strip():
        return _error_text("content is required.")

    lines: list[str] = ["# EE2 Compliance Review", ""]
    lines.append(
        f"**Analysis Focus:** {analysis_type.replace('_', ' ')}"
    )
    lines.append("")

    # Category set used for both the standards lookup and the
    # pattern-check battery.
    if analysis_type == "comprehensive":
        categories = [
            "error_handling",
            "environment_variables",
            "file_naming",
            "code_standards",
        ]
    else:
        categories = [analysis_type]

    standards = await _fetch_standards_context(
        data, categories=categories, per_category=3
    )

    observations = _analyze_observations(content, categories, standards)

    if not observations:
        lines.append("## Review Summary")
        lines.append("")
        lines.append(
            "The code appears to align well with EE2 guidelines for "
            "the analyzed categories. No significant concerns were "
            "identified."
        )
        lines.append("")
    else:
        lines.append("## Observations & Suggestions")
        lines.append("")
        lines.append(
            "Based on the EE2 implementation standards, here are some "
            "areas you might consider reviewing:"
        )
        lines.append("")
        for obs in observations:
            lines.append(f"### {obs['category']}")
            lines.append("")
            lines.append(f"**Pattern observed:** {obs['pattern']}")
            lines.append("")
            lines.append(f"**Suggestion:** {obs['suggestion']}")
            lines.append("")
            if obs.get("confidence"):
                lines.append(f"**Confidence:** {obs['confidence']}")
                lines.append("")
            lines.append(f"**Why this matters:** {obs['reasoning']}")
            lines.append("")
            lines.append(f"**Reference:** {obs['reference']}")
            lines.append("")
            lines.append("---")
            lines.append("")

    if include_recommendations and standards:
        lines.append("## Relevant EE2 Standards")
        lines.append("")
        lines.append(
            "Here are the applicable guidelines from the EE2 "
            "implementation standards:"
        )
        lines.append("")
        for category, results in standards.items():
            if not results:
                continue
            top = results[0]
            doc = (
                top.get("document")
                or top.get("text")
                or top.get("content")
                or ""
            )
            lines.append(f"### {category.replace('_', ' ').upper()}")
            lines.append("")
            metadata = top.get("metadata") or {}
            if metadata.get("section_headers"):
                lines.append(f"**Section:** {metadata['section_headers']}")
                lines.append("")
            if doc:
                lines.append(doc[:400] + "...")
                lines.append("")
    elif include_recommendations and not standards:
        # Degraded: signal that the standards context was skipped.
        lines.append(_INFO_STANDARDS_UNAVAILABLE)
        lines.append("")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "*Note: These suggestions are based on EE2 implementation "
        "standards and are provided as guidance. Your specific use "
        "case may have valid reasons for different approaches.*"
    )

    return "\n".join(lines).rstrip() + "\n"


def _analyze_observations(
    content: str,
    categories: list[str],
    standards: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Run the Phase-2 SME-corrected pattern battery on *content*.

    Mirrors the Node.js ``analyzeEE2Compliance`` observation loop. The
    ``standards`` argument is forwarded only to anchor reference
    strings — the observation logic itself is content-only.
    """
    observations: list[dict[str, Any]] = []
    is_bash = _is_bash_script(content)
    has_set_eu = _has_set_eu(content)
    has_set_e = _has_set_e(content)
    has_err_chk = _has_err_chk(content)
    has_preamble = _has_preamble(content)
    has_file_ops = _has_file_ops(content)
    file_ops_without_err_chk = _file_ops_without_err_chk(content)

    include_error = "error_handling" in categories
    include_env_vars = "environment_variables" in categories

    if include_error:
        if is_bash and has_set_eu:
            observations.append(
                {
                    "category": "Error Handling",
                    "pattern": (
                        "Script uses set -eu (not required by EE2 "
                        "standards)"
                    ),
                    "suggestion": (
                        "Remove set -eu; use err_chk/err_exit "
                        "utilities instead."
                    ),
                    "reasoning": (
                        "EE2 standards do NOT require set -eu. The "
                        "err_chk/err_exit utilities provide proper "
                        "error handling."
                    ),
                    "reference": "EE2 §4.2.1 Error Handling",
                    "confidence": "HIGH",
                }
            )
        elif is_bash and has_set_e:
            observations.append(
                {
                    "category": "Error Handling",
                    "pattern": (
                        "Script uses set -e (not required by EE2 "
                        "standards)"
                    ),
                    "suggestion": (
                        "Remove set -e; use err_chk after critical "
                        "operations instead."
                    ),
                    "reasoning": (
                        "set -e is not required by EE2. Use err_chk "
                        "for controlled error handling."
                    ),
                    "reference": "EE2 §4.2.1 Error Handling",
                    "confidence": "HIGH",
                }
            )

        if (
            is_bash
            and has_file_ops
            and file_ops_without_err_chk > 0
            and not has_err_chk
        ):
            observations.append(
                {
                    "category": "Error Handling",
                    "pattern": (
                        f"Found {file_ops_without_err_chk} file "
                        "operation(s) without err_chk"
                    ),
                    "suggestion": (
                        "Add 'export err=$?; err_chk' after every cp, "
                        "mv, ln operation."
                    ),
                    "reasoning": (
                        "File operations can fail silently. err_chk "
                        "prevents downstream failures from missing / "
                        "incomplete data."
                    ),
                    "reference": "EE2 §4.2.3 File Operations",
                    "confidence": "HIGH",
                }
            )

        if is_bash and (has_preamble or has_err_chk) and not has_set_eu:
            observations.append(
                {
                    "category": "Error Handling",
                    "pattern": (
                        "Script uses EE2-compliant error handling "
                        "(err_chk/preamble.sh)"
                    ),
                    "suggestion": (
                        "No changes needed — this follows EE2 "
                        "standards correctly."
                    ),
                    "reasoning": (
                        "Using err_chk/err_exit via preamble.sh is "
                        "the correct EE2 pattern."
                    ),
                    "reference": "EE2 §4.2.1 Error Handling",
                    "confidence": "HIGH",
                }
            )

    if include_env_vars:
        unquoted = _count_unquoted_vars(content)
        quoted = _count_quoted_vars(content)
        if unquoted > quoted:
            reference = "Standard Variables"
            env_standards = standards.get("environment_variables") or []
            if env_standards:
                metadata = env_standards[0].get("metadata") or {}
                if metadata.get("section_headers"):
                    reference = str(metadata["section_headers"])
            observations.append(
                {
                    "category": "Environment Variables",
                    "pattern": (
                        f"Found {unquoted} unquoted variable "
                        "references"
                    ),
                    "suggestion": (
                        "You might want to quote variables as "
                        '"${VARIABLE}" to prevent word splitting'
                    ),
                    "reasoning": (
                        "Quoted variables help avoid unexpected "
                        "behavior with spaces or special characters"
                    ),
                    "reference": reference,
                }
            )

    return observations


async def _fetch_standards_context(
    data: Any,
    *,
    categories: list[str],
    per_category: int,
) -> dict[str, list[dict[str, Any]]]:
    """Query the vector store for standard excerpts in each category.

    Returns an empty mapping (not ``None``) whenever ``data`` is
    unavailable so callers can branch on ``if standards:`` without
    fighting a three-way ``None`` / ``{}`` / ``{...}`` distinction.
    """
    if data is None or getattr(data, "vector_db", None) is None:
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for category in categories:
        query = _build_standards_query(category)
        try:
            hits = await data.vector_db.query(
                EE2_COLLECTION,
                query,
                k=per_category,
                include_graph=False,
                tenant=_tenant(),
            )
        except Exception as exc:
            log.debug(
                "standards context fetch failed for %s: %s",
                category,
                exc,
            )
            hits = []
        out[category] = list(hits or [])
    return out


# ── generate_compliance_report ─────────────────────────────────────────


async def _tool_generate_compliance_report(
    data: Any,
    *,
    scope: str,
    categories: list[str],
    fmt: str,
) -> str:
    # ``fmt`` is accepted for schema parity but does not alter the
    # rendered body — the Node.js port is also markdown-only (the two
    # non-markdown enum values remain advisory). Keep the parameter
    # honored in the output metadata so clients can detect it.
    lines: list[str] = ["# EE2 Implementation Standards Reference", ""]
    lines.append(f"**Generated:** {_utc_today_iso_date()}")
    lines.append(f"**Scope:** {scope}")
    if fmt != "markdown":
        lines.append(f"**Format:** {fmt}")
    lines.append("")
    lines.append(
        "This report provides guidance based on the NCEP WCOSS "
        "Implementation Standards (EE2). These are recommendations "
        "to help align code with production best practices."
    )
    lines.append("")

    target_categories = categories or list(SEARCH_CATEGORY_VALUES)

    standards_available = (
        data is not None and getattr(data, "vector_db", None) is not None
    )

    for category in target_categories:
        lines.append(f"## {category.replace('_', ' ').upper()}")
        lines.append("")
        if standards_available:
            query = _build_standards_query(category)
            try:
                results = await data.vector_db.query(
                    EE2_COLLECTION,
                    query,
                    k=2,
                    include_graph=False,
                    tenant=_tenant(),
                )
            except Exception as exc:
                log.debug(
                    "report standards fetch failed for %s: %s",
                    category,
                    exc,
                )
                results = []
        else:
            results = []

        if results:
            top = results[0]
            metadata = top.get("metadata") or {}
            doc = (
                top.get("document")
                or top.get("text")
                or top.get("content")
                or ""
            )
            if metadata.get("section_headers"):
                lines.append(f"**Reference:** {metadata['section_headers']}")
                lines.append("")

            if scope == "summary" and doc:
                lines.append(doc[:300] + "...")
                lines.append("")
            elif scope == "detailed" and doc:
                lines.append(doc)
                lines.append("")
                if len(results) >= 2:
                    doc2 = (
                        results[1].get("document")
                        or results[1].get("text")
                        or results[1].get("content")
                        or ""
                    )
                    if doc2:
                        lines.append("### Additional Context")
                        lines.append("")
                        lines.append(doc2[:400] + "...")
                        lines.append("")
            elif scope == "checklist" and doc:
                for item in _extract_checklist_items(doc):
                    lines.append(f"- [ ] {item}")
                lines.append("")

            if metadata.get("url"):
                lines.append(f"**Documentation:** {metadata['url']}")
                lines.append("")
        else:
            if standards_available:
                lines.append(
                    "*Guidelines for this category are being retrieved "
                    "from the standards documentation.*"
                )
            else:
                lines.append(
                    "*Standards excerpt unavailable — vector store not "
                    "reachable. See the EE2 standards repository for "
                    "authoritative text.*"
                )
            lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("")
    lines.append("## How to Use This Report")
    lines.append("")
    lines.append(
        "- These guidelines are **suggestions** based on NCEP "
        "operational standards"
    )
    lines.append(
        "- Consider your specific use case when applying recommendations"
    )
    lines.append(
        "- Standards help improve maintainability and reliability"
    )
    lines.append(
        "- Consult with your team lead if you have questions about "
        "applicability"
    )
    lines.append("")
    lines.append(
        "**Note:** This is reference material, not a mandated checklist. "
        "Use professional judgment when applying these guidelines to "
        "your code."
    )

    needs_passthrough = (
        not categories
        or "file_naming" in categories
        or "environment_variables" in categories
    )
    if needs_passthrough:
        lines.append("")
        lines.append(_REPORT_PASSTHROUGH_NOTE)

    if not standards_available:
        lines.append("")
        lines.append(_INFO_STANDARDS_UNAVAILABLE)

    return "\n".join(lines).rstrip() + "\n"


# ── scan_repository_compliance ─────────────────────────────────────────


def _file_type_for_entry(filename: str, path: str | None) -> str:
    """Categorize an incoming file into one of the Node.js
    ``filesByType`` buckets: ``shell_scripts``, ``python_scripts``,
    ``job_cards``, ``config_files``, or ``other``."""
    name = filename or (path.rsplit("/", 1)[-1] if path else "")
    if name.startswith("JEVS_") or (name.startswith("J") and name[1:2].isupper()):
        return "job_cards"
    if name.endswith(".sh") or name.startswith("ex"):
        return "shell_scripts"
    if name.endswith(".py"):
        return "python_scripts"
    if name.endswith(".config") or name.endswith(".cfg"):
        return "config_files"
    return "other"


def _analyze_file_for_scan(
    *,
    name: str,
    path: str | None,
    content: str,
    categories: list[str],
) -> dict[str, Any]:
    """Run the scan-mode per-file violation battery.

    Port of the Node.js ``scanRepositoryCompliance`` per-file loop.
    Returns a dict with ``issues`` (list of category names triggered)
    and ``examples`` (list of violation dicts).
    """
    lines = content.split("\n")
    file_type = _file_type_for_entry(name, path)
    rel_path = path or name
    result: dict[str, Any] = {
        "file": rel_path,
        "type": file_type,
        "issues": [],
        "examples": [],
    }

    if "error_handling" in categories:
        violations: list[dict[str, Any]] = []
        if "#!/bin/bash" in content or "#!/bin/sh" in content:
            shebang_line = -1
            for i in range(min(3, len(lines))):
                if lines[i].startswith("#!"):
                    shebang_line = i
                    break
            if shebang_line > 0:
                violations.append(
                    {
                        "issue": (
                            f"Shebang on line {shebang_line + 1}, must "
                            "be line 1"
                        ),
                        "line": shebang_line + 1,
                        "current": lines[shebang_line],
                        "fix": (
                            f"Remove {shebang_line} blank line(s) "
                            "before shebang"
                        ),
                    }
                )
            has_error_handling = bool(
                re.search(r"set -x", content)
                or re.search(r"err_chk|err_exit", content)
            )
            if not has_error_handling:
                shebang_ref = (
                    lines[shebang_line] if shebang_line >= 0 else (
                        lines[0] if lines else ""
                    )
                )
                violations.append(
                    {
                        "issue": (
                            "Missing set -x (EE2 debug logging "
                            "requirement)"
                        ),
                        "line": shebang_line + 2 if shebang_line >= 0 else 2,
                        "current": shebang_ref,
                        "fix": (
                            'Add "set -x" after shebang per EE2 '
                            "standard (NOT set -eu)"
                        ),
                        "phase2_correction": (
                            "set -eu is NOT required by EE2; "
                            "err_chk/err_exit usage indicates "
                            "compliant error handling"
                        ),
                    }
                )
            error_lines = [
                line
                for line in lines
                if re.search(r"echo.*error|exit [1-9]", line)
                and "FATAL ERROR:" not in line
            ]
            if error_lines:
                violations.append(
                    {
                        "issue": (
                            "Error messages missing FATAL ERROR: "
                            "prefix"
                        ),
                        "example": error_lines[0].strip(),
                        "fix": (
                            "Prefix error messages with "
                            '"FATAL ERROR:" per EE2 standard'
                        ),
                    }
                )
        if violations:
            result["issues"].append("error_handling")
            result["examples"].extend(violations)

    if "file_naming" in categories:
        violations = []
        if file_type == "job_cards" and not re.match(
            r"^(J|JEVS_)", name
        ):
            violations.append(
                {
                    "issue": "Job card naming violation",
                    "current": name,
                    "fix": f"Rename to JEVS_{name} or J{name}",
                }
            )
        if file_type == "shell_scripts" and rel_path.startswith("scripts/"):
            if not name.startswith("ex"):
                violations.append(
                    {
                        "issue": "Ex-script naming violation",
                        "current": name,
                        "fix": (
                            "Scripts in scripts/ directory should "
                            "start with 'ex' prefix per EE2 standard"
                        ),
                        "evidence": (
                            "standards.rst - ex-script naming "
                            "convention"
                        ),
                    }
                )
        # COM-based output filename check (line-by-line to avoid
        # regex blowouts on large files).
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            match = re.search(
                r"\$\{?COM(OUT|IN)[^}]*\}?.*[\"']([^\"']+\.[a-zA-Z0-9]+)[\"']",
                line,
            )
            if match:
                filename = match.group(2)
                base = filename.rsplit("/", 1)[-1]
                if base and "$" not in base and base != base.lower():
                    violations.append(
                        {
                            "issue": (
                                "Uppercase characters in output "
                                "filename"
                            ),
                            "current": base,
                            "line": idx + 1,
                            "fix": (
                                "Use lowercase only in output "
                                f"filenames: {base.lower()}"
                            ),
                            "evidence": "EE2 Section B - Output file naming",
                        }
                    )
                    break
        if violations:
            result["issues"].append("file_naming")
            result["examples"].extend(violations)

    if "shebang_compliance" in categories:
        violations = []
        is_shell = file_type == "shell_scripts" or bool(
            re.search(r"^#!.*\b(bash|sh|ksh)\b", content, flags=re.MULTILINE)
        )
        if is_shell:
            first_line = lines[0] if lines else ""
            if not first_line.startswith("#!"):
                shebang_line = -1
                for i in range(min(5, len(lines))):
                    if lines[i].startswith("#!"):
                        shebang_line = i
                        break
                if shebang_line > 0:
                    violations.append(
                        {
                            "issue": (
                                f"Shebang on line {shebang_line + 1}, "
                                "must be line 1"
                            ),
                            "line": shebang_line + 1,
                            "current": lines[shebang_line],
                            "fix": (
                                f"Remove {shebang_line} blank line(s) "
                                "before shebang"
                            ),
                            "evidence": (
                                "EE2 shebang requirement - must be "
                                "first line"
                            ),
                        }
                    )
                elif shebang_line == -1 and lines:
                    violations.append(
                        {
                            "issue": "Missing shebang",
                            "line": 1,
                            "current": first_line[:50],
                            "fix": (
                                "Add shebang as first line: "
                                "#!/bin/bash or #!/bin/sh"
                            ),
                            "evidence": "EE2 shebang requirement",
                        }
                    )
            valid_shebang = bool(
                re.search(
                    r"^#!.*/(bash|sh|ksh|env\s+(bash|sh))",
                    content,
                    flags=re.MULTILINE,
                )
            )
            any_shebang = bool(re.search(r"^#!", content, flags=re.MULTILINE))
            if not valid_shebang and any_shebang:
                actual = next(
                    (line for line in lines if line.startswith("#!")), None
                )
                if actual and not re.search(r"python|perl|ruby", actual):
                    violations.append(
                        {
                            "issue": "Non-standard shebang",
                            "line": 1,
                            "current": actual,
                            "fix": (
                                "Use standard shebang: #!/bin/bash, "
                                "#!/bin/sh, or #!/bin/ksh"
                            ),
                            "evidence": (
                                "EE2 - valid shells: bash, sh, ksh"
                            ),
                        }
                    )
            if (
                "jobs/J" in rel_path
                or re.match(r"^J[A-Z]", name)
            ):
                if "PS4=" not in content and "PS4='" not in content:
                    violations.append(
                        {
                            "issue": "J-job missing PS4 timing export",
                            "fix": (
                                "Add: export PS4='+ $SECONDS + '"
                            ),
                            "evidence": (
                                "standards.rst lines 868-919 - J-job "
                                "timing requirement"
                            ),
                        }
                    )
        if violations:
            result["issues"].append("shebang_compliance")
            result["examples"].extend(violations)

    if "production_utilities" in categories:
        violations = []
        if file_type == "shell_scripts":
            is_operational = bool(
                re.search(r"scripts/ex|jobs/J", rel_path)
            )
            if is_operational:
                has_err_utility = bool(
                    re.search(r"err_chk|err_exit", content)
                )
                has_explicit_exit = bool(re.search(r"\bexit\s+[1-9]", content))
                if has_explicit_exit and not has_err_utility:
                    snippet = re.search(r"\bexit\s+[1-9].*", content)
                    violations.append(
                        {
                            "issue": (
                                "Using explicit exit instead of "
                                "err_exit utility"
                            ),
                            "example": snippet.group(0).strip()
                            if snippet
                            else None,
                            "fix": (
                                'Replace "exit N" with err_exit '
                                "utility for proper NCO error handling"
                            ),
                            "evidence": (
                                "standards.rst - NCO SPA prohibits "
                                "forced exits"
                            ),
                            "phase2_correction": (
                                "Use err_exit utility, NOT explicit "
                                "exit statements"
                            ),
                        }
                    )
                if not re.search(r"set -x", content):
                    violations.append(
                        {
                            "issue": "Missing debug logging",
                            "fix": (
                                'Add "set -x" near top of script for '
                                "debug logging"
                            ),
                            "evidence": (
                                "standards.rst lines 588-595"
                            ),
                        }
                    )
            if (
                re.search(r"jobs/J", rel_path)
                and not re.search(r"postmsg|msg=", content)
            ):
                violations.append(
                    {
                        "issue": "J-job missing postmsg calls",
                        "fix": (
                            "Consider adding postmsg calls for job "
                            "status tracking"
                        ),
                        "evidence": "NCO operational best practice",
                        "severity": "info",
                    }
                )
            if re.search(r"SENDCOM", content) and not re.search(
                r"SENDCOM.*:-|SENDCOM.*:=", content
            ):
                violations.append(
                    {
                        "issue": "SENDCOM without default value",
                        "fix": (
                            "Use ${SENDCOM:-YES} pattern for proper "
                            "default handling"
                        ),
                        "evidence": (
                            "EE2 environment variable defaults"
                        ),
                    }
                )
        if violations:
            result["issues"].append("production_utilities")
            result["examples"].extend(violations)

    # environment_variables: Node.js only runs phase2-validated rules
    # and currently has none configured (see Node.js comments). We
    # preserve that behaviour — the category is reported in the
    # analysis_categories list but produces no violations.

    return result


async def _tool_scan_repository_compliance(
    data: Any,
    *,
    files: list[dict[str, Any]],
    repository_path: str | None,
    file_patterns: list[str],
    sample_size: int,
    categories: list[str],
) -> str:
    # The Python port is hosted — no filesystem access. Advertise the
    # restriction early rather than silently ignoring
    # ``repository_path``.
    if repository_path:
        return _error_text(_ABSTRACTED_SCAN_MSG)

    if not files:
        return _error_text(
            "files array is required (each item must contain "
            "`name` and `content`)."
        )

    issues_by_category: dict[str, dict[str, Any]] = {
        c: {
            "total_files_with_issues": 0,
            "specific_files": [],
            "common_patterns": [],
        }
        for c in categories
    }
    file_issues: list[dict[str, Any]] = []
    files_by_type = {
        "shell_scripts": 0,
        "python_scripts": 0,
        "job_cards": 0,
        "config_files": 0,
    }

    analyzed = 0
    for entry in files[:sample_size]:
        name = str(entry.get("name") or "").strip()
        content = entry.get("content")
        if not name or content is None:
            continue
        analyzed += 1
        path = entry.get("path")
        file_type = _file_type_for_entry(name, path)
        if file_type in files_by_type:
            files_by_type[file_type] += 1
        file_result = _analyze_file_for_scan(
            name=name,
            path=path,
            content=str(content),
            categories=categories,
        )
        if file_result["issues"]:
            file_issues.append(file_result)
            for issue in file_result["issues"]:
                bucket = issues_by_category.get(issue)
                if bucket is None:
                    continue
                bucket["total_files_with_issues"] += 1
                if len(bucket["specific_files"]) < 20:
                    bucket["specific_files"].append(file_result["file"])
                if len(bucket["common_patterns"]) < 3:
                    bucket["common_patterns"].extend(
                        file_result["examples"][:1]
                    )

    categories_with_issues = {
        cat: data_
        for cat, data_ in issues_by_category.items()
        if data_["total_files_with_issues"] > 0
    }

    scan_result = {
        "repository": repository_path,
        "scan_date": _utc_now_iso(),
        "statistics": {
            "total_files": len(files),
            "files_by_type": files_by_type,
            "samples_analyzed": analyzed,
            "files_with_issues": len(file_issues),
        },
        "issues_by_category": categories_with_issues,
        "actionable_examples": [
            {
                "file": f["file"],
                "type": f["type"],
                "violations": f["examples"],
            }
            for f in file_issues[:10]
        ],
        "analysis_categories": list(categories_with_issues.keys()),
        "input_categories": list(categories),
        "file_patterns_advertised": list(file_patterns),
    }

    needs_passthrough = (
        "file_naming" in categories
        or "environment_variables" in categories
    )
    if needs_passthrough:
        scan_result["passthrough_recommendation"] = (
            "Run extract_code_for_analysis with categories "
            "output_file_naming, shebang_compliance, "
            "env_var_validation on the repository content to inspect "
            "COM/COMOUT output-file naming and env validation patterns "
            "that are not auto-checked in this scan."
        )

    # Important: keep the JSON serialization deterministic so tests
    # can assert on structure without being surprised by dict-iteration
    # order on older interpreters.
    import json

    body = json.dumps(scan_result, indent=2, sort_keys=False)

    lines: list[str] = [
        "# EE2 Compliance Scan - Action Items",
        "",
        "```json",
        body,
        "```",
        "",
        "**Instructions for LLM:**",
        "Generate a PRAGMATIC report focused ONLY on actionable findings:",
        "1. Skip any category with 0 issues - do not describe compliant "
        "areas",
        "2. For each issue category, show count of affected files + "
        "example code snippets + specific fix recommendation",
        "3. Create a fix priority list with file paths and exact "
        "changes needed",
        "4. Keep report focused on \"what to change\" not \"what the "
        "standards say\"",
        "5. Use violation examples from actionable_examples field",
        "6. Use generate_compliance_report tool to get EE2 standards "
        "context",
        "7. Maintain consultative tone throughout",
    ]

    if needs_passthrough:
        lines.append("")
        lines.append(
            "## ⚠️ MANDATORY ACTION REQUIRED - DO NOT SKIP"
        )
        lines.append("")
        lines.append(
            "**LLM INSTRUCTION:** Before presenting this report to "
            "the user, you MUST execute the following tool call:"
        )
        lines.append("")
        lines.append("```")
        lines.append("extract_code_for_analysis({")
        lines.append(
            '  categories: ["output_file_naming", "shebang_compliance", '
            '"env_var_validation"],'
        )
        lines.append(
            '  files: [ ...your scanned files... ],'
        )
        lines.append(f"  max_files: {EXTRACT_MAX_FILES_DEFAULT}")
        lines.append("})")
        lines.append("```")
        lines.append("")
        lines.append(
            "**Rationale:** The standard scan does NOT automatically "
            "check COM/COMOUT output file naming, shebang line-1 "
            "compliance, or env validation patterns."
        )

    return "\n".join(lines).rstrip() + "\n"


# ── extract_code_for_analysis ──────────────────────────────────────────


async def _tool_extract_code_for_analysis(
    *,
    content: str | None,
    files: list[dict[str, Any]],
    path: str | None,
    content_type: str,
    categories: list[str],
    file_pattern: str,
    max_files: int,
) -> str:
    # The Python port is hosted — path-based scanning is not supported.
    # Surface the restriction rather than silently ignoring the arg.
    if path and not content and not files:
        return _error_text(_ABSTRACTED_EXTRACT_MSG)
    if content is None and not files:
        return _error_text(
            "Either `content` (single blob) or `files` (batch) must be "
            "provided. Path-based scanning is not supported on the "
            "hosted Python port."
        )

    # Validate categories against the enum. (FastMCP would normally do
    # this, but the schema uses ``list[Literal[...]]`` which does not
    # currently emit runtime validators in fastmcp 2.x.)
    unknown = [c for c in categories if c not in EXTRACT_CATEGORY_VALUES]
    if unknown:
        return _error_text(
            f"Unknown categories: {unknown}. Known: "
            f"{list(EXTRACT_CATEGORY_VALUES)}"
        )

    extracted_results: list[dict[str, Any]] = []
    if content is not None:
        extracted_results.append(
            _extract_from_content(
                content=content,
                filename="direct_content",
                content_type_hint=content_type,
                categories=categories,
            )
        )
    pattern_re: re.Pattern[str] | None = None
    if file_pattern:
        try:
            pattern_re = re.compile(file_pattern)
        except re.error as exc:
            return _error_text(f"Invalid file_pattern: {exc}")
    for entry in files[:max_files]:
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        if pattern_re is not None and not pattern_re.search(name):
            continue
        body = entry.get("content")
        if body is None:
            continue
        result = _extract_from_content(
            content=str(body),
            filename=name,
            content_type_hint=content_type,
            categories=categories,
        )
        result["path"] = entry.get("path")
        extracted_results.append(result)

    if not extracted_results:
        return _error_text(
            "No files matched the `file_pattern` filter. Check the "
            "pattern or pass files via `content` instead."
        )

    # Generate prompt bundle per category.
    llm_prompts: dict[str, dict[str, Any]] = {}
    for category in categories:
        llm_prompts[category] = _generate_analysis_prompt(
            category, extracted_results
        )

    files_scanned = len(extracted_results)
    files_with_matches = sum(
        1
        for r in extracted_results
        if any(bool(v) for v in r.get("snippets", {}).values())
        or r.get("shebangBlock", {}).get("shebang")
    )

    lines: list[str] = ["# Code Extraction for EE2 Analysis", ""]
    source = "direct" if content is not None and not files else "files_array"
    lines.append(f"**Source:** {source}")
    lines.append(f"**Content Type:** {content_type}")
    lines.append(f"**Categories:** {', '.join(categories)}")
    lines.append(f"**Files Scanned:** {files_scanned}")
    lines.append(f"**Files with Matches:** {files_with_matches}")
    lines.append("")
    lines.append("---")
    lines.append("")

    lines.append("## LLM Analysis Instructions")
    lines.append("")
    lines.append(
        "The following prompts and code snippets are provided for "
        "analysis. Please analyze each category using the provided "
        "context and SME corrections."
    )
    lines.append("")
    for category, prompt in llm_prompts.items():
        if prompt.get("error"):
            continue
        lines.append(f"### {category.replace('_', ' ').upper()}")
        lines.append("")
        lines.append("**Context:**")
        lines.append("```")
        lines.append(str(prompt["context"]))
        lines.append("```")
        lines.append("")
        lines.append("**Instruction:**")
        lines.append(str(prompt["instruction"]))
        lines.append("")
        lines.append("**SME Corrections (avoid false positives):**")
        for correction in prompt["sme_corrections"]:
            lines.append(f"- {correction}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Extracted Code Snippets")
    lines.append("")
    for result in extracted_results[:10]:
        if result.get("error"):
            continue
        lines.append(f"### {result['filename']}")
        lines.append(
            f"**Type:** {result['fileType']} | **Lines:** {result['lineCount']}"
        )
        lines.append("")
        sheb = result.get("shebangBlock") or {}
        if sheb:
            lines.append(
                f"**Shebang:** {sheb.get('shebang') or 'MISSING'}"
            )
            set_x_line = sheb.get("setXLine")
            set_x_state = (
                f"Line {set_x_line}"
                if sheb.get("hasSetX") and set_x_line
                else "NOT FOUND"
            )
            lines.append(f"**set -x:** {set_x_state}")
            lines.append("")
        for cat, snippets in (result.get("snippets") or {}).items():
            if not snippets:
                continue
            lines.append(f"**{cat} patterns:** {len(snippets)} found")
            for snip in snippets[:5]:
                line_num = snip.get("line")
                match = str(snip.get("match") or "")
                trimmed = match[:80] + ("..." if len(match) > 80 else "")
                lines.append(f"- Line {line_num}: `{trimmed}`")
            lines.append("")

    if len(extracted_results) > 10:
        lines.append(
            f"\n*... and {len(extracted_results) - 10} more files*"
        )

    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "EE2_COLLECTION",
    "SEARCH_CATEGORY_VALUES",
    "ANALYSIS_TYPE_VALUES",
    "REPORT_SCOPE_VALUES",
    "REPORT_FORMAT_VALUES",
    "SCAN_CATEGORY_VALUES",
    "EXTRACT_CATEGORY_VALUES",
    "CONTENT_TYPE_VALUES",
    "SEARCH_RESULTS_DEFAULT",
    "SEARCH_RESULTS_MIN",
    "SEARCH_RESULTS_MAX",
    "SCAN_SAMPLE_DEFAULT",
    "SCAN_SAMPLE_MIN",
    "SCAN_SAMPLE_MAX",
    "SCAN_FILE_PATTERNS_DEFAULT",
    "EXTRACT_FILE_PATTERN_DEFAULT",
    "EXTRACT_MAX_FILES_DEFAULT",
    "EE2_ANALYSIS_PROMPTS",
    "register",
]
