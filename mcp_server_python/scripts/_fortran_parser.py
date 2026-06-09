"""Fortran source parser for graph relationship extraction.

Port of mcp_server_node/scripts/ingest_fortran_graph.py::FortranParser to the
Python tenant-aware pipeline. Wraps fparser2's AST traversal with C
preprocessor preprocessing, source sanitization, and include directory
discovery. The sanitization regexes and preprocessing pipeline are preserved
from the legacy script (they're tuned for the GFS / UFS / JEDI source tree).

Implements: R1.1-R1.5, R2.1-R2.5, R3.1-R3.4, R4.1-R4.7, R10.2, R10.3,
R13.1-R13.3 of graph-port-fortran-ast.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from fparser.common.readfortran import FortranFileReader
from fparser.two import Fortran2003 as f2003
from fparser.two.parser import ParserFactory
from fparser.two.utils import walk


@dataclass
class FortranParseResult:
    """Complete parse output for one Fortran source file."""

    file_path: str            # original path (not temp)
    relative_path: str        # relative to worktree_root
    modules: list[dict] = field(default_factory=list)       # {name, line_start}
    subroutines: list[dict] = field(default_factory=list)   # {name, line_start, parent_module}
    functions: list[dict] = field(default_factory=list)     # {name, line_start, parent_module, return_type}
    programs: list[dict] = field(default_factory=list)       # {name, executable_name}
    calls: list[dict] = field(default_factory=list)          # {callee, line, caller}
    uses: list[dict] = field(default_factory=list)           # {module, only}
    # Parse provenance (R4.1, R5.3): "fparser2" for an AST parse, "fallback"
    # for a regex recovery. Defaulted so every existing constructor and test
    # stays valid; placed last so field order is unchanged.
    source: str = "fparser2"


# CPP directives that indicate preprocessing is needed (verbatim from legacy)
_CPP_DIRECTIVES = (
    '#ifdef', '#ifndef', '#if ', '#include', '#define',
    '#else', '#endif', '#undef', '#elif',
)

# Fortran extensions for discovery
FORTRAN_EXTENSIONS = frozenset([
    '.F90', '.f90', '.F', '.f', '.F95', '.f95',
    '.F03', '.f03', '.F08', '.f08',
])

# Directories to exclude from discovery
_EXCLUDED_DIRS = frozenset(['.git', 'build', 'test'])


class FortranParser:
    """Parse Fortran files using fparser2 with preprocessing and sanitization.

    Pipeline per file: sanitize (regex fixes) -> CPP preprocess (if directives
    present) -> fparser2 parse -> AST extraction. Every step is best-effort;
    individual file failures (including fparser2's ``SystemExit``) are caught
    and surfaced as a ``None`` result so the caller can continue (R10.2, R10.3).
    """

    # -- Sanitization patterns ------------------------------------------
    _MERGE_CONFLICT = re.compile(r'^(<{7}|>{7}|={7})')
    _WRITE_COMMA = re.compile(r'(\bwrite\s*\([^)]*\))\s*,', re.IGNORECASE)

    # -- Fallback extractor regexes (fortran-parse-fallback R2, R3, R6) --
    # All IGNORECASE and anchored to the start of the stripped logical line so
    # mid-line identifiers (e.g. ``recall``, ``arr(call_count)``) and control
    # constructs (``IF (``, ``DO ``) can never match a definition/edge keyword.
    _FB_END_MODULE = re.compile(r'^\s*end\s*module\b', re.IGNORECASE)
    _FB_END = re.compile(r'^\s*end\b', re.IGNORECASE)
    # MODULE <name>, excluding ``MODULE PROCEDURE`` and the module-prefixed
    # ``MODULE SUBROUTINE`` / ``MODULE FUNCTION`` definition forms.
    _FB_MODULE = re.compile(
        r'^\s*module\s+(?!procedure\b|subroutine\b|function\b)([a-z]\w*)',
        re.IGNORECASE,
    )
    _FB_PROGRAM = re.compile(r'^\s*program\s+([a-z]\w*)', re.IGNORECASE)
    # Prefix-aware SUBROUTINE (PURE/ELEMENTAL/RECURSIVE/IMPURE/MODULE prefixes).
    _FB_SUBROUTINE = re.compile(
        r'^\s*(?:(?:pure|elemental|recursive|impure|module)\s+)*'
        r'subroutine\s+([a-z]\w*)',
        re.IGNORECASE,
    )
    # Type/attribute-prefixed FUNCTION (e.g. ``REAL FUNCTION``,
    # ``INTEGER(i_kind) FUNCTION``, ``PURE FUNCTION``). The prefix char class
    # excludes ``=`` so assignments like ``r = function(x)`` never match.
    _FB_FUNCTION = re.compile(
        r'^\s*(?:[a-z][\w()*:, ]*?\s+)?function\s+([a-z]\w*)',
        re.IGNORECASE,
    )
    # CALL <name>: name only; an argument list is excluded by the capture.
    _FB_CALL = re.compile(r'^\s*call\s+([a-z]\w*)', re.IGNORECASE)
    # USE <module>[, ONLY: ...]: captures module name and optional ONLY clause.
    _FB_USE = re.compile(
        r'^\s*use\s+([a-z]\w*)\s*(?:,\s*only\s*:\s*(.*))?$',
        re.IGNORECASE,
    )

    # New-statement keywords that signal "this is NOT a continuation".
    _NEW_STMT_KEYWORDS = (
        'TYPE', 'END', 'INTEGER', 'REAL', 'CHARACTER', 'LOGICAL',
        'PUBLIC', 'PRIVATE', 'CONTAINS', 'SUBROUTINE', 'FUNCTION',
        'MODULE', 'PROGRAM', 'USE ', 'IMPLICIT', 'INTERFACE', 'CALL ',
        'IF ', 'IF(', 'DO ', 'SELECT', 'WRITE', 'READ', 'OPEN',
        'CLOSE', 'ALLOCATE', 'DEALLOCATE', 'NULLIFY', 'CLASS',
        'ABSTRACT', 'PROCEDURE', 'GENERIC', 'FINAL', 'DATA ',
    )

    def __init__(self, worktree_root: str | Path):
        self._worktree_root = Path(worktree_root)
        self._parser = ParserFactory().create(std='f2003')
        self._include_dirs: list[str] | None = None
        # Telemetry counters for files needing preprocessing / sanitization
        # (R9.1). Internal to parse_file; otherwise unobservable to the caller.
        self.stats: dict[str, int] = {
            'files_preprocessed': 0,
            'files_sanitized': 0,
            # Parse-provenance counters (R5.1). Incremented in parse_file (the
            # single choke point) so both live and --dry-run see the same split.
            'files_parsed_fparser2': 0,
            'files_parsed_fallback': 0,
            'files_failed': 0,
        }

    # -- Discovery ------------------------------------------------------

    def discover_fortran_files(self) -> list[Path]:
        """Recursively discover Fortran source files under ``sorc/``.

        Returns a sorted list of absolute paths. Excludes ``.git/``,
        ``build/``, and ``test/`` directories (R1.2). Traverses into submodule
        directories when checked out (R1.3).

        Raises
        ------
        FileNotFoundError
            If the ``sorc/`` directory does not exist (R13.2).
        """
        sorc_dir = self._worktree_root / 'sorc'
        if not sorc_dir.is_dir():
            raise FileNotFoundError(
                f"sorc/ directory not found in {self._worktree_root}. "
                "Source files are not available."
            )

        files: list[Path] = []
        for p in sorc_dir.rglob('*'):
            if not p.is_file():
                continue
            if any(part in _EXCLUDED_DIRS for part in p.parts):
                continue
            if p.suffix in FORTRAN_EXTENSIONS:
                files.append(p)
        return sorted(files)

    def discover_include_dirs(self) -> list[str]:
        """Find directories containing ``.h``/``.inc``/``.fh`` files under ``sorc/``.

        Cached after the first call (the tree does not change during a run).
        """
        if self._include_dirs is not None:
            return self._include_dirs

        sorc_dir = self._worktree_root / 'sorc'
        include_dirs: set[str] = set()
        if sorc_dir.is_dir():
            for root, dirs, filenames in os.walk(sorc_dir):
                # Skip excluded dirs in-place so os.walk does not descend.
                dirs[:] = [d for d in dirs if d not in _EXCLUDED_DIRS]
                for f in filenames:
                    if f.endswith(('.h', '.inc', '.fh')):
                        include_dirs.add(root)
                        break  # one hit per directory is enough
        self._include_dirs = sorted(include_dirs)
        return self._include_dirs

    # -- Public parse API -----------------------------------------------

    def parse_file(self, filepath: str | Path) -> FortranParseResult | None:
        """Parse a Fortran file and extract AST structure.

        Pipeline: sanitize -> CPP preprocess (if needed) -> fparser2 parse ->
        extract. Returns ``None`` on any failure (logged by the caller, never
        raised). Catches both ``Exception`` and ``SystemExit`` because fparser2
        raises ``SystemExit`` on some malformed files (R10.2, R10.3).

        Temporary sanitized/preprocessed files are always cleaned up in the
        ``finally`` block (R2.5, R3.4).
        """
        filepath = str(filepath)
        temp_paths: list[str] = []

        try:
            actual_path = filepath

            # Step 1: Sanitize (dangling continuations, merge markers, commas).
            sanitized = self._sanitize(filepath)
            if sanitized:
                actual_path = sanitized
                temp_paths.append(sanitized)
                self.stats['files_sanitized'] += 1

            # Step 2: CPP preprocess if directives present.
            if self._needs_preprocessing(actual_path):
                preprocessed = self._preprocess(actual_path)
                if preprocessed:
                    actual_path = preprocessed
                    temp_paths.append(preprocessed)
                    self.stats['files_preprocessed'] += 1

            # Step 3: Parse with fparser2 (primary path). Wrap in an inner
            # guard so a fparser2 failure (including its ``SystemExit``) falls
            # through to the regex fallback rather than the outer never-raise
            # guard, which would skip the fallback entirely.
            tree = None
            try:
                reader = FortranFileReader(actual_path, ignore_comments=True)
                tree = self._parser(reader)
            except (Exception, SystemExit):
                tree = None

            if tree is not None:
                # Step 4: AST extraction (uses ORIGINAL filepath for metadata).
                result = self._extract_structure(tree, filepath)
                result.source = 'fparser2'
                self.stats['files_parsed_fparser2'] += 1
                return result

            # Step 5: Fallback — regex recovery over the same sanitized /
            # preprocessed text fparser2 was given (R1.2, R1.4).
            result = self._fallback_extract(actual_path, filepath)
            if result is not None:
                self.stats['files_parsed_fallback'] += 1
                return result

            self.stats['files_failed'] += 1
            return None

        except (Exception, SystemExit):
            # Defensive outer guard preserves the never-raise contract even if
            # both branches misbehave (R1.5, R10.2, R10.3).
            self.stats['files_failed'] += 1
            return None
        finally:
            for p in temp_paths:
                try:
                    os.unlink(p)
                except OSError:
                    pass

    # -- Preprocessing --------------------------------------------------

    def _needs_preprocessing(self, filepath: str) -> bool:
        """Check whether the file contains CPP directives."""
        try:
            with open(filepath, 'r', errors='replace') as f:
                for line in f:
                    stripped = line.lstrip()
                    if stripped.startswith('#') and any(
                        stripped.startswith(d) for d in _CPP_DIRECTIVES
                    ):
                        return True
        except OSError:
            return False
        return False

    def _preprocess(self, filepath: str) -> str | None:
        """Run ``cpp -traditional-cpp -nostdinc -P`` with discovered ``-I`` dirs.

        Falls back to directive-stripping mode on timeout/failure (R2.3).
        """
        include_dirs = self.discover_include_dirs()
        cmd = ['cpp', '-traditional-cpp', '-nostdinc', '-P']
        for d in include_dirs:
            cmd.extend(['-I', d])
        cmd.append(filepath)

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0 and result.stdout.strip():
                tmp = tempfile.NamedTemporaryFile(
                    mode='w', suffix='.f90', delete=False
                )
                tmp.write(result.stdout)
                tmp.close()
                return tmp.name
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

        # Fallback: strip directives.
        return self._strip_directives_fallback(filepath)

    def _strip_directives_fallback(self, filepath: str) -> str | None:
        """Comment out all ``#`` directives so fparser2 can parse the file."""
        try:
            with open(filepath, 'r', errors='replace') as f:
                lines = f.readlines()
        except OSError:
            return None

        cleaned = []
        for line in lines:
            if line.lstrip().startswith('#'):
                cleaned.append('! CPP: ' + line)
            else:
                cleaned.append(line)
        try:
            tmp = tempfile.NamedTemporaryFile(
                mode='w', suffix='.f90', delete=False
            )
            tmp.writelines(cleaned)
            tmp.close()
            return tmp.name
        except OSError:
            return None

    # -- Sanitization ---------------------------------------------------

    def _sanitize(self, filepath: str) -> str | None:
        """Fix non-standard patterns that cause fparser2 to fail.

        Fixes (verbatim port from legacy ``_sanitize_fortran_source``):
          1. Dangling assignment continuations: ``VAR = &`` with no value.
          2. Dangling USE/ONLY continuations: ``USE m, ONLY: X, &``.
          3. Non-standard write comma: ``write(6,*),``.
          4. Git merge conflict markers.

        Returns the path to a temp file, or ``None`` if no fixes were needed
        (or the file could not be read).
        """
        try:
            with open(filepath, 'r', errors='replace') as f:
                lines = f.readlines()
        except OSError:
            return None

        modified = False
        i = 0
        while i < len(lines):
            stripped = lines[i].rstrip()
            code_part = stripped.lstrip()

            # Fix 4: merge conflict markers.
            if self._MERGE_CONFLICT.match(code_part):
                lines[i] = '! [SANITIZED] ' + lines[i]
                modified = True
                i += 1
                continue

            # Fix 3: non-standard write comma.
            if re.match(r'.*\bwrite\s*\([^)]*\)\s*,', code_part, re.IGNORECASE):
                new_line = self._WRITE_COMMA.sub(r'\1 ', lines[i])
                if new_line != lines[i]:
                    lines[i] = new_line
                    modified = True
                    i += 1
                    continue

            # Fixes 1 & 2: dangling continuations.
            if stripped.endswith('&') and not code_part.startswith('!'):
                j = i + 1
                while j < len(lines) and (
                    lines[j].strip() == '' or lines[j].strip().startswith('!')
                ):
                    j += 1
                dangling = False
                if j >= len(lines):
                    dangling = True
                elif j > i + 1:
                    next_code = lines[j].strip().upper()
                    if any(next_code.startswith(kw) for kw in self._NEW_STMT_KEYWORDS):
                        dangling = True
                if dangling:
                    if re.search(r',\s*&\s*$', stripped):
                        lines[i] = re.sub(r',\s*&\s*$', '\n', stripped) + '\n'
                        modified = True
                    elif '=' in stripped:
                        lines[i] = stripped[:-1] + "''\n"
                        modified = True
                    else:
                        lines[i] = stripped[:-1] + '\n'
                        modified = True
            i += 1

        if not modified:
            return None

        tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.f90', delete=False
        )
        tmp.writelines(lines)
        tmp.close()
        return tmp.name

    # -- AST extraction -------------------------------------------------

    def _extract_structure(self, tree: Any, filepath: str) -> FortranParseResult:
        """Extract modules, subroutines, functions, programs, calls, uses."""
        rel_path = self._relative_path(filepath)

        modules: list[dict] = []
        subroutines: list[dict] = []
        functions: list[dict] = []
        programs: list[dict] = []
        calls: list[dict] = []
        uses: list[dict] = []

        # Modules
        for node in walk(tree, f2003.Module_Stmt):
            try:
                name = str(node.items[1]).strip()
                modules.append({'name': name, 'line_start': self._line_of(node)})
            except Exception:
                pass

        # Subroutines (parent_module resolved below)
        for node in walk(tree, f2003.Subroutine_Stmt):
            try:
                name = str(node.items[1]).strip()
                subroutines.append({
                    'name': name,
                    'line_start': self._line_of(node),
                    'parent_module': None,
                })
            except Exception:
                pass

        # Functions
        for node in walk(tree, f2003.Function_Stmt):
            try:
                name = str(node.items[1]).strip() if node.items[1] else 'unknown'
                functions.append({
                    'name': name,
                    'line_start': self._line_of(node),
                    'parent_module': None,
                    'return_type': None,
                })
            except Exception:
                pass

        # Programs
        for node in walk(tree, f2003.Program_Stmt):
            try:
                name = str(node.items[1]).strip() if node.items[1] else 'MAIN'
                programs.append({
                    'name': name,
                    'executable_name': self._infer_executable(filepath, name),
                })
            except Exception:
                pass

        # CALL statements
        for node in walk(tree, f2003.Call_Stmt):
            try:
                callee = str(node.items[0]).strip()
                if '(' in callee:
                    callee = callee.split('(')[0].strip()
                calls.append({
                    'callee': callee,
                    'line': self._line_of(node),
                    'caller': None,
                })
            except Exception:
                pass

        # USE statements
        for node in walk(tree, f2003.Use_Stmt):
            try:
                module_name = str(node.items[2]).strip() if node.items[2] else None
                if not module_name:
                    continue
                only_list = None
                if len(node.items) > 4 and node.items[4]:
                    only_list = str(node.items[4])
                uses.append({'module': module_name, 'only': only_list})
            except Exception:
                pass

        # Resolve parent_module for subroutines/functions inside modules.
        self._resolve_containment(tree, subroutines, functions)

        return FortranParseResult(
            file_path=filepath,
            relative_path=rel_path,
            modules=modules,
            subroutines=subroutines,
            functions=functions,
            programs=programs,
            calls=calls,
            uses=uses,
        )

    def _resolve_containment(
        self,
        tree: Any,
        subroutines: list[dict],
        functions: list[dict],
    ) -> None:
        """Assign ``parent_module`` to subroutines/functions within modules.

        Walks each ``Module`` container node and matches its contained
        ``Subroutine_Stmt`` / ``Function_Stmt`` names back to the flat lists
        produced by ``_extract_structure`` (R4.3, R4.4).
        """
        try:
            for mod_node in walk(tree, f2003.Module):
                mod_name = None
                for ms in walk(mod_node, f2003.Module_Stmt):
                    try:
                        mod_name = str(ms.items[1]).strip()
                        break
                    except Exception:
                        pass
                if not mod_name:
                    continue

                for sub_node in walk(mod_node, f2003.Subroutine_Stmt):
                    try:
                        sub_name = str(sub_node.items[1]).strip()
                        for s in subroutines:
                            if s['name'] == sub_name and s['parent_module'] is None:
                                s['parent_module'] = mod_name
                                break
                    except Exception:
                        pass

                for func_node in walk(mod_node, f2003.Function_Stmt):
                    try:
                        func_name = (
                            str(func_node.items[1]).strip()
                            if func_node.items[1] else None
                        )
                        if not func_name:
                            continue
                        for fn in functions:
                            if fn['name'] == func_name and fn['parent_module'] is None:
                                fn['parent_module'] = mod_name
                                break
                    except Exception:
                        pass
        except Exception:
            pass

    # -- Helpers --------------------------------------------------------

    @staticmethod
    def _line_of(node: Any) -> int | None:
        """Best-effort source line number from a statement node's ``.item.span``."""
        item = getattr(node, 'item', None)
        span = getattr(item, 'span', None)
        if span:
            return span[0]
        return None

    def _relative_path(self, filepath: str) -> str:
        """Get the path relative to the worktree root (falls back to absolute)."""
        try:
            return str(Path(filepath).relative_to(self._worktree_root))
        except ValueError:
            return filepath

    def _infer_executable(self, filepath: str, program_name: str) -> str | None:
        """Infer the executable name from a ``sorc/<name>.fd`` path pattern.

        Example: ``sorc/ufs_model.fd/atmos.F90`` -> ``ufs_model.x``.
        """
        for part in Path(filepath).parts:
            if part.endswith('.fd'):
                return part.replace('.fd', '') + '.x'
        return None

    # -- Regex fallback extractor (fortran-parse-fallback) --------------

    @staticmethod
    def _is_full_comment(line: str) -> bool:
        """Return True if a physical line is a whole-line Fortran comment.

        Recognizes free-form ``!`` comments (first non-blank character) and
        fixed-form column-1 comment markers ``*`` (always) and ``c``/``C``
        (only when not the start of an identifier such as ``call`` /
        ``continue`` — i.e. the next character is not a word character).
        Blank lines are not comments (handled separately). (R2.6)
        """
        stripped = line.strip()
        if not stripped:
            return False
        if stripped.startswith('!'):
            return True
        c0 = line[0]
        if c0 == '*':
            return True
        if c0 in ('c', 'C'):
            nxt = line[1] if len(line) > 1 else ''
            if not (nxt.isalnum() or nxt == '_'):
                return True
        return False

    @staticmethod
    def _strip_inline_comment(line: str) -> str:
        """Strip an inline ``!`` comment, ignoring ``!`` inside string literals.

        Handles single- and double-quoted strings and Fortran's doubled-quote
        escape (``''`` / ``""``). (R3, R6.3)
        """
        in_quote: str | None = None
        out: list[str] = []
        i = 0
        n = len(line)
        while i < n:
            ch = line[i]
            if in_quote:
                out.append(ch)
                if ch == in_quote:
                    if i + 1 < n and line[i + 1] == in_quote:
                        out.append(line[i + 1])
                        i += 2
                        continue
                    in_quote = None
                i += 1
                continue
            if ch == '!':
                break
            if ch in ("'", '"'):
                in_quote = ch
            out.append(ch)
            i += 1
        return ''.join(out)

    def _logical_lines(self, text: str) -> list[tuple[int, str]]:
        """Yield ``(physical_line_no, logical_line)`` for the fallback.

        Drops whole-line comments, strips inline ``!`` comments outside string
        literals, and joins free-form trailing-``&`` continuation lines into a
        single logical line carrying the first physical line number. (R2.6,
        R3.3, R6.3)
        """
        physical = text.split('\n')
        n = len(physical)
        results: list[tuple[int, str]] = []
        i = 0
        while i < n:
            raw = physical[i]
            first_line_no = i + 1
            if self._is_full_comment(raw):
                i += 1
                continue
            buf = self._strip_inline_comment(raw).strip()
            if not buf:
                i += 1
                continue
            # Join trailing-'&' continuations.
            while buf.rstrip().endswith('&'):
                buf = buf.rstrip()[:-1].rstrip()
                i += 1
                # Skip interleaved full-line comments inside the continuation.
                while i < n and self._is_full_comment(physical[i]):
                    i += 1
                if i >= n:
                    break
                nxt = self._strip_inline_comment(physical[i]).strip()
                if nxt.startswith('&'):
                    nxt = nxt[1:].lstrip()
                buf = buf + nxt
            results.append((first_line_no, buf))
            i += 1
        return results

    def _fallback_extract(
        self, actual_path: str, original_path: str
    ) -> FortranParseResult | None:
        """Recover structure with line-oriented regex when fparser2 fails.

        Runs only from ``parse_file`` when the fparser2 path yields no tree.
        Reads the already-sanitized/preprocessed text, scans logical lines for
        MODULE/SUBROUTINE/FUNCTION/PROGRAM definitions and CALL/USE edges, and
        returns a ``FortranParseResult(source="fallback")`` — or ``None`` when
        nothing is recovered (counted as failed). The whole body is wrapped so
        it never raises (R1.3, R1.5).
        """
        try:
            try:
                with open(actual_path, 'r', errors='replace') as f:
                    text = f.read()
            except OSError:
                return None

            rel_path = self._relative_path(original_path)
            modules: list[dict] = []
            subroutines: list[dict] = []
            functions: list[dict] = []
            programs: list[dict] = []
            calls: list[dict] = []
            uses: list[dict] = []
            seen_calls: set[tuple[str, int | None]] = set()
            current_module: str | None = None

            for line_no, logical in self._logical_lines(text):
                # Closings first so an ``END FUNCTION foo`` is never mistaken
                # for a definition (R2.7).
                if self._FB_END_MODULE.match(logical):
                    current_module = None
                    continue
                if self._FB_END.match(logical):
                    continue

                m = self._FB_MODULE.match(logical)
                if m:
                    name = m.group(1)
                    current_module = name
                    modules.append({'name': name, 'line_start': line_no})
                    continue

                m = self._FB_PROGRAM.match(logical)
                if m:
                    name = m.group(1)
                    programs.append({
                        'name': name,
                        'executable_name': self._infer_executable(
                            original_path, name
                        ),
                    })
                    continue

                m = self._FB_SUBROUTINE.match(logical)
                if m:
                    subroutines.append({
                        'name': m.group(1),
                        'line_start': line_no,
                        'parent_module': current_module,
                    })
                    continue

                m = self._FB_FUNCTION.match(logical)
                if m:
                    functions.append({
                        'name': m.group(1),
                        'line_start': line_no,
                        'parent_module': current_module,
                        'return_type': None,
                    })
                    continue

                m = self._FB_CALL.match(logical)
                if m:
                    callee = m.group(1)
                    key = (callee, line_no)
                    if key not in seen_calls:
                        seen_calls.add(key)
                        calls.append({
                            'callee': callee,
                            'line': line_no,
                            'caller': None,
                        })
                    continue

                m = self._FB_USE.match(logical)
                if m:
                    only = m.group(2)
                    if only is not None:
                        only = only.strip() or None
                    uses.append({'module': m.group(1), 'only': only})
                    continue

            if not (modules or subroutines or functions
                    or programs or calls or uses):
                return None

            return FortranParseResult(
                file_path=original_path,
                relative_path=rel_path,
                modules=modules,
                subroutines=subroutines,
                functions=functions,
                programs=programs,
                calls=calls,
                uses=uses,
                source='fallback',
            )
        except (Exception, SystemExit):
            return None
