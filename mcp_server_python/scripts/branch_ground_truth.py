#!/usr/bin/env python3
"""branch_ground_truth.py — Source-derived expectation extractors for Phase 60.

Derives expected code structure, imports, call chains, and environment variable
dependencies directly from the on-disk git checkouts to act as the Ground-Truth Oracle.
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, Set

def extract_imports_from_file(file_path: Path) -> Set[str]:
    """Extract imported modules/scripts from a file."""
    if not file_path.is_file():
        return set()
    imports = set()
    try:
        content = file_path.read_text(errors="ignore")
    except Exception:
        return set()

    # Python imports
    for match in re.finditer(r"^\s*(?:import|from)\s+([a-zA-Z0-9_\.]+)", content, re.MULTILINE):
        imports.add(match.group(1).split(".")[0])

    # Bash sources and dot commands
    # Matches: source "${HOMEglobal}/ush/jjob_header.sh"
    # Match non-quote, non-whitespace characters
    for match in re.finditer(r"^\s*(?:source|\.)\s+[\"']?([^\"'\s]+)[\"']?", content, re.MULTILINE):
        p = match.group(1)
        # Normalize: get basename and strip extension / path variables
        p = p.split("/")[-1]
        p = re.sub(r"[\{\}\$]", "", p)
        p = p.replace(".sh", "").replace(".ecf", "").replace(".py", "")
        if p and not p.startswith("."):
            imports.add(p)

    # Fortran modules/use
    for match in re.finditer(r"^\s*use\s+([a-zA-Z0-9_]+)", content, re.IGNORECASE | re.MULTILINE):
        imports.add(match.group(1).lower())

    return imports

def extract_structure_from_file(file_path: Path) -> Dict[str, list]:
    """Extract functions and classes from a file."""
    if not file_path.is_file():
        return {"functions": [], "classes": []}
    try:
        content = file_path.read_text(errors="ignore")
    except Exception:
        return {"functions": [], "classes": []}

    functions = []
    classes = []

    # Python defs & classes
    for match in re.finditer(r"^\s*def\s+([a-zA-Z0-9_]+)\b", content, re.MULTILINE):
        functions.append(match.group(1))
    for match in re.finditer(r"^\s*class\s+([a-zA-Z0-9_]+)\b", content, re.MULTILINE):
        classes.append(match.group(1))

    # Bash functions: func() { or function func {
    for match in re.finditer(r"^\s*([a-zA-Z0-9_-]+)\s*\(\s*\)\s*\{", content, re.MULTILINE):
        functions.append(match.group(1))
    for match in re.finditer(r"^\s*function\s+([a-zA-Z0-9_-]+)\b", content, re.MULTILINE):
        functions.append(match.group(1))

    # Fortran subroutine / function
    for match in re.finditer(r"^\s*(?:subroutine|function)\s+([a-zA-Z0-9_]+)\b", content, re.IGNORECASE | re.MULTILINE):
        functions.append(match.group(1).lower())

    # De-duplicate lists while preserving order
    functions = list(dict.fromkeys(functions))
    classes = list(dict.fromkeys(classes))

    return {"functions": functions, "classes": classes}

def extract_env_dependencies(variable_name: str, checkout_root: Path) -> Dict[str, Set[str]]:
    """Find files that export or use an environment variable."""
    exports = set()
    uses = set()

    subdirs = ["dev", "jobs", "ush", "env", "scripts", "ecf"]
    for sd in subdirs:
        sd_path = checkout_root / sd
        if not sd_path.is_dir():
            continue
        for root, _, files in os.walk(sd_path):
            for file in files:
                if file.startswith(".") or file.endswith((".png", ".jpg", ".o", ".a", ".pdf")):
                    continue
                fp = Path(root) / file
                try:
                    content = fp.read_text(errors="ignore")
                except Exception:
                    continue
                rel_path = fp.relative_to(checkout_root).as_posix()

                # Check exports
                if re.search(r"\b(?:export|declare\s+-rx)\s+" + re.escape(variable_name) + r"\b", content):
                    exports.add(rel_path)
                # Check uses
                if re.search(r"\$(?:\{" + re.escape(variable_name) + r"\}|" + re.escape(variable_name) + r"\b)", content):
                    uses.add(rel_path)

    return {"exports": exports, "uses": uses}

def extract_callers_callees(function_name: str, checkout_root: Path) -> Dict[str, Set[str]]:
    """Lightweight search for potential callers/callees of a function."""
    callers = set()
    callees = set()

    subdirs = ["dev", "ush", "scripts", "ecf"]
    for sd in subdirs:
        sd_path = checkout_root / sd
        if not sd_path.is_dir():
            continue
        for root, _, files in os.walk(sd_path):
            for file in files:
                if file.startswith(".") or file.endswith((".png", ".o", ".a")):
                    continue
                fp = Path(root) / file
                try:
                    content = fp.read_text(errors="ignore")
                except Exception:
                    continue
                rel_path = fp.relative_to(checkout_root).as_posix()

                # Check caller: is function_name invoked in this file?
                # (simple substring/regex to avoid false negatives)
                if function_name in content:
                    # Check if it's defining it
                    is_def = False
                    if re.search(r"^\s*(?:def|subroutine|function)\s+" + re.escape(function_name) + r"\b", content, re.IGNORECASE | re.MULTILINE):
                        is_def = True
                    if not is_def:
                        callers.add(rel_path)

    return {"callers": callers, "callees": callees}


if __name__ == "__main__":
    # Smoke test the extractors
    repo_root = Path(__file__).resolve().parent.parent.parent
    gw_root = repo_root / "supported_repos" / "global-workflow_develop"
    v17_root = repo_root / "supported_repos" / "global-workflow_dev-gfs.v17"

    print("[INFO] Ground-truth extractors smoke test:")
    if gw_root.is_dir():
        print(f"  [OK] gw_root: {gw_root}")
        imports = extract_imports_from_file(gw_root / "dev/jobs/JGLOBAL_FORECAST")
        print(f"    extracted {len(imports)} imports from JGLOBAL_FORECAST: {list(imports)[:5]}")
        struct = extract_structure_from_file(gw_root / "ush/err_exit.sh")
        print(f"    extracted structure from err_exit.sh: {struct}")
    if v17_root.is_dir():
        print(f"  [OK] v17_root: {v17_root}")
        env_deps = extract_env_dependencies("ROTDIR", v17_root)
        print(f"    found {len(env_deps['exports'])} exports and {len(env_deps['uses'])} uses of ROTDIR in v17")
