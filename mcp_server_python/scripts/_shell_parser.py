"""Shell script parser for graph relationship extraction.

Ported verbatim from mcp_server_node/scripts/ingest_shell_graph_v8.py.
Regex patterns are battle-tested against real GFS scripts — do NOT modify.

Implements: R2.1–R2.8, R1.3, R1.4 of graph-port-shell-ops.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ShellParseResult:
    """Complete parse output for one shell script."""

    path: str
    name: str
    type: str       # jjob | exscript | ush | config | script
    category: str   # analysis | forecast | post | archive | ...
    sources: list[dict] = field(default_factory=list)
    invokes: list[dict] = field(default_factory=list)
    exports: list[dict] = field(default_factory=list)
    env_deps: list[str] = field(default_factory=list)
    functions: list[dict] = field(default_factory=list)
    configs: list[dict] = field(default_factory=list)


# Known external packages (scripts from external repos)
EXTERNAL_PACKAGES: dict[str, str] = {
    "SCRIPTSfit2obs": "Fit2Obs",
    "SCRIPTSgfs_wafs": "WAFS",
    "SCRIPTSprepobs": "PrepObs",
    "SCRIPTSgldas": "GLDAS",
    "SCRIPTSsnow": "Snow",
    "HOMEgfs": "GFS",
    "HOMEgdas": "GDAS",
    "HOMEwave": "Wave",
}


class ShellScriptParser:
    """Regex-based extraction of shell-graph relationships.

    Port of mcp_server_node/scripts/ingest_shell_graph_v8.py::ShellScriptParser.
    The regex patterns are preserved verbatim (they're tuned for GFS scripts).
    """

    # ── Regex patterns (verbatim from legacy) ──────────────────────────
    _SOURCE = re.compile(
        r'(?:source|\.) +["\']?'
        r'([^\s;|&"\']+/[^\s;|&"\']+|[^\s;|&"\']+\.(?:sh|bash|ksh|env|conf))'
        r'["\']?',
        re.MULTILINE,
    )
    _INVOKE_VAR = re.compile(
        r'\$\{?(\w+)\}?/([^;\s\n"\']+\.sh)',
        re.MULTILINE,
    )
    _INVOKE_DIRECT = re.compile(
        r'(?:^|\s)(?:\./|sh\s+|bash\s+)([^;\s\n"\']+\.sh)',
        re.MULTILINE,
    )
    _EXPORT = re.compile(r'^export\s+(\w+)=(.*)$', re.MULTILINE)
    _ENV_USE = re.compile(r'\$\{?(\w+)\}?')
    _FUNCTION = re.compile(
        r'^(?:function\s+)?(\w+)\s*\(\s*\)\s*\{?',
        re.MULTILINE,
    )
    _CONFIG = re.compile(r'config\.(\w+)', re.MULTILINE)

    # ── Filters ────────────────────────────────────────────────────────
    _BUILTIN_VARS: frozenset[str] = frozenset([
        "HOME", "PATH", "PWD", "USER", "SHELL", "TERM",
        "1", "2", "3", "4", "5", "6", "7", "8", "9", "0",
        "i", "j", "n", "x", "y", "z", "file", "line", "err",
    ])
    _BUILTIN_FUNCS: frozenset[str] = frozenset([
        "if", "while", "for", "case", "then", "else", "fi", "do", "done",
    ])

    # ── Variable→path resolution table ─────────────────────────────────
    _PATH_RESOLUTIONS: dict[str, str] = {
        "${USHgfs}": "ush",
        "${HOMEgfs}": "",
        "${PARMgfs}": "parm",
        "${SCRIPTSgfs}": "dev/scripts",
        "${EXPDIR}": "expdir",
    }

    def parse(self, file_path: str, content: str) -> ShellParseResult:
        """Parse a shell script, return structured extraction."""
        result = ShellParseResult(
            path=file_path,
            name=Path(file_path).name,
            type=self._determine_type(file_path),
            category=self._determine_category(file_path, content),
        )

        lines = content.split("\n")
        seen_configs: set[str] = set()

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue

            # Source statements
            for m in self._SOURCE.finditer(line):
                source_path = m.group(1)
                # Post-filter: reject non-path matches
                if (
                    source_path.startswith("-")
                    or source_path in ("*", "...")
                    or (
                        source_path[0:1].isupper()
                        and "/" not in source_path
                        and "." not in source_path
                    )
                ):
                    continue
                result.sources.append({
                    "path": source_path,
                    "line": i,
                    "resolved": self._resolve_path(source_path),
                })

            # Script invocations via variable
            for m in self._INVOKE_VAR.finditer(line):
                result.invokes.append({
                    "script": m.group(2),
                    "variable": m.group(1),
                    "line": i,
                    "package": EXTERNAL_PACKAGES.get(m.group(1), "internal"),
                })

            # Direct script invocations
            for m in self._INVOKE_DIRECT.finditer(line):
                script_name = m.group(1)
                if not script_name.startswith("$"):
                    result.invokes.append({
                        "script": script_name,
                        "variable": None,
                        "line": i,
                        "package": "internal",
                    })

            # Exports
            em = self._EXPORT.match(stripped)
            if em:
                result.exports.append({
                    "name": em.group(1),
                    "value": em.group(2).strip("\"'")[:200],
                    "line": i,
                })

            # Config references
            for m in self._CONFIG.finditer(line):
                config_name = m.group(1)
                if config_name not in seen_configs:
                    seen_configs.add(config_name)
                    result.configs.append({"name": config_name, "line": i})

        # Function definitions (full-content scan)
        for m in self._FUNCTION.finditer(content):
            func_name = m.group(1)
            if func_name not in self._BUILTIN_FUNCS:
                result.functions.append({
                    "name": func_name,
                    "line": content[: m.start()].count("\n") + 1,
                })

        # Environment variable dependencies (unique, filtered)
        env_deps: set[str] = set()
        for m in self._ENV_USE.finditer(content):
            var_name = m.group(1)
            if var_name not in self._BUILTIN_VARS:
                env_deps.add(var_name)
        result.env_deps = sorted(env_deps)

        return result

    def _determine_type(self, file_path: str) -> str:
        """Determine script type from path."""
        name = Path(file_path).name
        if "dev/jobs" in file_path or name.startswith("J"):
            return "jjob"
        elif "dev/scripts" in file_path or name.startswith("ex"):
            return "exscript"
        elif "ush" in file_path:
            return "ush"
        elif "parm" in file_path or "config" in file_path:
            return "config"
        return "script"

    def _determine_category(self, file_path: str, content: str) -> str:
        """Determine operational category from filename patterns."""
        name = Path(file_path).name.upper()

        categories: dict[str, list[str]] = {
            "forecast": ["FCST", "FORECAST", "FV3"],
            "analysis": ["ANAL", "ANALYSIS", "ENKF", "ATMANL", "AERO"],
            "verification": ["VRFY", "FIT2OBS", "VERFRAD", "VERFOZN"],
            "archive": ["ARCH", "ARCHIVE"],
            "preprocessing": ["PREP", "OBSPROC", "BUFR"],
            "post": ["POST", "GEMPAK", "AWIPS", "GRIB"],
            "wave": ["WAVE", "WW3"],
            "ocean": ["OCEAN", "MOM6", "CICE"],
            "aerosol": ["AERO", "GOCART"],
            "land": ["LAND", "NOAHMP"],
            "coupled": ["COUPLED", "UFS"],
            "init": ["INIT", "COLDSTART", "WARMSTART"],
            "cleanup": ["CLEANUP", "EARC"],
        }

        for category, patterns in categories.items():
            for pattern in patterns:
                if pattern in name:
                    return category
        return "general"

    def _resolve_path(self, source_path: str) -> Optional[str]:
        """Try to resolve a source path to relative path via variable table."""
        if "$" not in source_path:
            return None
        for var, base in self._PATH_RESOLUTIONS.items():
            if var in source_path:
                return source_path.replace(var, base)
        return None
