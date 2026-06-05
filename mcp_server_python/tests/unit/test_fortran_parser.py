"""Unit tests for FortranParser (extraction, preprocessing, sanitization,
resilience) and Fortran file discovery.

Validates: R1.1–R1.5, R2.1–R2.5, R3.1–R3.4, R4.1–R4.7, R10.2, R10.3,
R13.1–R13.3 of graph-port-fortran-ast.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))
sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from scripts._fortran_parser import (
    FORTRAN_EXTENSIONS,
    FortranParser,
    FortranParseResult,
)


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


# ════════════════════════════════════════════════════════════════════════
# Task 1.1 — AST extraction
# ════════════════════════════════════════════════════════════════════════


class TestModuleExtraction:
    """R4.2: MODULE <name> extraction."""

    def test_module_name_and_line(self, tmp_path):
        f = _write(tmp_path / "m.f90", "module weather_mod\nimplicit none\nend module weather_mod\n")
        r = FortranParser(tmp_path).parse_file(f)
        assert r is not None
        names = [m["name"] for m in r.modules]
        assert "weather_mod" in names
        mod = next(m for m in r.modules if m["name"] == "weather_mod")
        assert mod["line_start"] == 1


class TestSubroutineExtraction:
    """R4.3: SUBROUTINE <name> extraction + parent_module."""

    def test_standalone_subroutine_no_parent(self, tmp_path):
        f = _write(tmp_path / "s.f90",
                   "subroutine compute(x)\n  integer :: x\nend subroutine compute\n")
        r = FortranParser(tmp_path).parse_file(f)
        assert r is not None
        sub = next(s for s in r.subroutines if s["name"] == "compute")
        assert sub["parent_module"] is None
        assert sub["line_start"] == 1

    def test_module_subroutine_has_parent(self, tmp_path):
        src = (
            "module mymod\ncontains\n"
            "  subroutine inner()\n  end subroutine inner\n"
            "end module mymod\n"
            "subroutine outer()\nend subroutine outer\n"
        )
        f = _write(tmp_path / "mix.f90", src)
        r = FortranParser(tmp_path).parse_file(f)
        assert r is not None
        inner = next(s for s in r.subroutines if s["name"] == "inner")
        outer = next(s for s in r.subroutines if s["name"] == "outer")
        assert inner["parent_module"] == "mymod"
        assert outer["parent_module"] is None


class TestFunctionExtraction:
    """R4.4: FUNCTION <name> extraction + parent_module."""

    def test_module_function_has_parent(self, tmp_path):
        src = (
            "module fmod\ncontains\n"
            "  function square(y) result(r)\n    real :: y, r\n    r = y*y\n"
            "  end function square\n"
            "end module fmod\n"
        )
        f = _write(tmp_path / "fn.f90", src)
        r = FortranParser(tmp_path).parse_file(f)
        assert r is not None
        fn = next(x for x in r.functions if x["name"] == "square")
        assert fn["parent_module"] == "fmod"
        assert "return_type" in fn


class TestProgramExtraction:
    """R4.5: PROGRAM <name> + executable inference."""

    def test_program_name(self, tmp_path):
        f = _write(tmp_path / "p.f90", "program driver\nimplicit none\nend program driver\n")
        r = FortranParser(tmp_path).parse_file(f)
        assert r is not None
        assert any(p["name"] == "driver" for p in r.programs)

    def test_program_executable_inference_from_fd_path(self, tmp_path):
        # File lives under sorc/ufs_model.fd/ → executable ufs_model.x
        f = _write(tmp_path / "sorc" / "ufs_model.fd" / "drv.f90",
                   "program drv\nend program drv\n")
        r = FortranParser(tmp_path).parse_file(f)
        assert r is not None
        prog = next(p for p in r.programs if p["name"] == "drv")
        assert prog["executable_name"] == "ufs_model.x"


class TestCallExtraction:
    """R4.6: CALL <name> extraction."""

    def test_calls_extracted(self, tmp_path):
        src = (
            "subroutine driver()\n"
            "  call alpha(1)\n"
            "  call beta()\n"
            "end subroutine driver\n"
        )
        f = _write(tmp_path / "c.f90", src)
        r = FortranParser(tmp_path).parse_file(f)
        assert r is not None
        callees = sorted(c["callee"] for c in r.calls)
        assert callees == ["alpha", "beta"]
        # line numbers captured
        assert all(c["line"] is not None for c in r.calls)


class TestUseExtraction:
    """R4.7: USE <module> extraction + ONLY clause."""

    def test_use_with_and_without_only(self, tmp_path):
        src = (
            "program p\n"
            "  use kinds_mod, only: r8\n"
            "  use util_mod\n"
            "  implicit none\n"
            "end program p\n"
        )
        f = _write(tmp_path / "u.f90", src)
        r = FortranParser(tmp_path).parse_file(f)
        assert r is not None
        by_mod = {u["module"]: u["only"] for u in r.uses}
        assert "kinds_mod" in by_mod
        assert by_mod["kinds_mod"] is not None
        assert "r8" in by_mod["kinds_mod"]
        assert "util_mod" in by_mod
        assert by_mod["util_mod"] is None


# ════════════════════════════════════════════════════════════════════════
# Task 1.1 — preprocessing detection + cpp pipeline
# ════════════════════════════════════════════════════════════════════════


class TestPreprocessingDetection:
    """R2.1: CPP directive detection."""

    def test_detects_cpp_directives(self, tmp_path):
        f = _write(tmp_path / "pp.F90",
                   "#ifdef USE_FOO\nmodule a\nend module a\n#endif\n")
        parser = FortranParser(tmp_path)
        assert parser._needs_preprocessing(str(f)) is True

    def test_plain_fortran_not_flagged(self, tmp_path):
        f = _write(tmp_path / "plain.f90", "module a\nend module a\n")
        parser = FortranParser(tmp_path)
        assert parser._needs_preprocessing(str(f)) is False

    def test_cpp_file_parses_via_pipeline(self, tmp_path):
        # Without -DUSE_FOO, cpp takes the #else branch → bar_mod.
        src = (
            "#ifdef USE_FOO\n"
            "module foo_mod\nend module foo_mod\n"
            "#else\n"
            "module bar_mod\nend module bar_mod\n"
            "#endif\n"
        )
        f = _write(tmp_path / "cond.F90", src)
        parser = FortranParser(tmp_path)
        r = parser.parse_file(f)
        assert r is not None
        names = [m["name"] for m in r.modules]
        assert "bar_mod" in names
        assert "foo_mod" not in names
        assert parser.stats["files_preprocessed"] == 1

    def test_strip_directives_fallback(self, tmp_path):
        f = _write(tmp_path / "x.F90",
                   "#define N 4\nmodule m\nend module m\n")
        parser = FortranParser(tmp_path)
        out = parser._strip_directives_fallback(str(f))
        assert out is not None
        content = Path(out).read_text()
        assert "! CPP: #define N 4" in content
        Path(out).unlink()


# ════════════════════════════════════════════════════════════════════════
# Task 1.1 — source sanitization
# ════════════════════════════════════════════════════════════════════════


class TestSanitization:
    """R3.1–R3.2: dangling continuations, merge markers, write commas."""

    def test_merge_conflict_markers_commented(self, tmp_path):
        src = (
            "module m\n"
            "<<<<<<< HEAD\n"
            "  integer :: a\n"
            "=======\n"
            "  integer :: b\n"
            ">>>>>>> branch\n"
            "end module m\n"
        )
        f = _write(tmp_path / "conflict.f90", src)
        parser = FortranParser(tmp_path)
        out = parser._sanitize(str(f))
        assert out is not None
        content = Path(out).read_text()
        assert "! [SANITIZED] <<<<<<< HEAD" in content
        assert "! [SANITIZED] =======" in content
        assert "! [SANITIZED] >>>>>>> branch" in content
        Path(out).unlink()

    def test_nonstandard_write_comma_repaired(self, tmp_path):
        f = _write(tmp_path / "w.f90",
                   "subroutine s()\n  write(6,*), 'hi'\nend subroutine s\n")
        parser = FortranParser(tmp_path)
        out = parser._sanitize(str(f))
        assert out is not None
        content = Path(out).read_text()
        # The comma after the format spec is replaced with a space (legacy
        # behavior leaves the original space → two spaces before the arg).
        assert "write(6,*)," not in content
        assert "write(6,*)" in content
        Path(out).unlink()

    def test_dangling_continuation_at_eof_fixed(self, tmp_path):
        # Trailing assignment continuation with no value, followed by a
        # blank-line gap before a new statement (CVS $Id$ stripped scenario).
        f = _write(tmp_path / "d.f90",
                   "subroutine s()\n  character(len=80) :: id = &\n\nend subroutine s\n")
        parser = FortranParser(tmp_path)
        out = parser._sanitize(str(f))
        assert out is not None
        content = Path(out).read_text()
        # '= &' becomes "= ''"
        assert "= ''" in content
        Path(out).unlink()

    def test_clean_file_returns_none(self, tmp_path):
        f = _write(tmp_path / "clean.f90", "module m\nend module m\n")
        parser = FortranParser(tmp_path)
        assert parser._sanitize(str(f)) is None


# ════════════════════════════════════════════════════════════════════════
# Task 1.1 — resilience (R10.2, R10.3)
# ════════════════════════════════════════════════════════════════════════


class TestResilience:
    """Parse failures return None, never raise."""

    def test_systemexit_caught(self, tmp_path):
        f = _write(tmp_path / "ok.f90", "module m\nend module m\n")
        parser = FortranParser(tmp_path)

        def _boom(_reader):
            raise SystemExit("fparser2 bailed")

        parser._parser = _boom
        assert parser.parse_file(f) is None  # no SystemExit propagates

    def test_none_return_handled(self, tmp_path):
        f = _write(tmp_path / "ok.f90", "module m\nend module m\n")
        parser = FortranParser(tmp_path)
        parser._parser = lambda _reader: None
        assert parser.parse_file(f) is None

    def test_generic_exception_caught(self, tmp_path):
        f = _write(tmp_path / "ok.f90", "module m\nend module m\n")
        parser = FortranParser(tmp_path)

        def _raise(_reader):
            raise ValueError("kaboom")

        parser._parser = _raise
        assert parser.parse_file(f) is None

    def test_missing_file_returns_none(self, tmp_path):
        parser = FortranParser(tmp_path)
        assert parser.parse_file(tmp_path / "does_not_exist.f90") is None


class TestExecutableInference:
    """R4.5: sorc/<name>.fd → <name>.x."""

    def test_fd_path(self, tmp_path):
        parser = FortranParser(tmp_path)
        assert parser._infer_executable("sorc/ufs_model.fd/atmos.F90", "x") == "ufs_model.x"

    def test_no_fd_returns_none(self, tmp_path):
        parser = FortranParser(tmp_path)
        assert parser._infer_executable("sorc/util/helper.f90", "x") is None


# ════════════════════════════════════════════════════════════════════════
# Task 2.1 — file discovery (R1.1–R1.5, R13.1–R13.3)
# ════════════════════════════════════════════════════════════════════════


class TestDiscovery:
    """R1: discovery of Fortran files under sorc/."""

    def test_all_extensions_discovered(self, tmp_path):
        sorc = tmp_path / "sorc"
        for ext in FORTRAN_EXTENSIONS:
            _write(sorc / f"file{ext}", "module a\nend module a\n")
        # Non-Fortran files ignored.
        _write(sorc / "readme.txt", "hello")
        _write(sorc / "build.py", "print('x')")
        files = FortranParser(tmp_path).discover_fortran_files()
        suffixes = {p.suffix for p in files}
        assert suffixes == set(FORTRAN_EXTENSIONS)
        assert len(files) == len(FORTRAN_EXTENSIONS)

    def test_excluded_dirs_skipped(self, tmp_path):
        sorc = tmp_path / "sorc"
        _write(sorc / "keep.f90", "module a\nend module a\n")
        _write(sorc / ".git" / "hook.f90", "module g\nend module g\n")
        _write(sorc / "build" / "gen.f90", "module b\nend module b\n")
        _write(sorc / "test" / "t.f90", "module t\nend module t\n")
        files = FortranParser(tmp_path).discover_fortran_files()
        rels = {str(p.relative_to(tmp_path)) for p in files}
        assert rels == {"sorc/keep.f90"}

    def test_traverses_submodule_dirs(self, tmp_path):
        sorc = tmp_path / "sorc"
        _write(sorc / "ufs_model.fd" / "atm.F90", "module a\nend module a\n")
        _write(sorc / "gdas.cd" / "sorc" / "crtm" / "rt.f90", "module c\nend module c\n")
        files = FortranParser(tmp_path).discover_fortran_files()
        rels = {str(p.relative_to(tmp_path)) for p in files}
        assert "sorc/ufs_model.fd/atm.F90" in rels
        assert "sorc/gdas.cd/sorc/crtm/rt.f90" in rels

    def test_missing_sorc_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            FortranParser(tmp_path).discover_fortran_files()

    def test_empty_submodule_no_crash(self, tmp_path):
        sorc = tmp_path / "sorc"
        _write(sorc / "main.f90", "module a\nend module a\n")
        (sorc / "ufs_model.fd").mkdir(parents=True)  # empty submodule
        files = FortranParser(tmp_path).discover_fortran_files()
        assert len(files) == 1
        assert files[0].name == "main.f90"

    def test_sorted_output(self, tmp_path):
        sorc = tmp_path / "sorc"
        _write(sorc / "zeta.f90", "module z\nend module z\n")
        _write(sorc / "alpha.f90", "module a\nend module a\n")
        files = FortranParser(tmp_path).discover_fortran_files()
        assert files == sorted(files)


class TestIncludeDirDiscovery:
    """R2.2: include directory discovery for cpp -I flags."""

    def test_dirs_with_headers_found(self, tmp_path):
        sorc = tmp_path / "sorc"
        _write(sorc / "inc" / "consts.h", "#define X 1\n")
        _write(sorc / "fh" / "macros.fh", "#define Y 2\n")
        _write(sorc / "incdir" / "table.inc", "data\n")
        _write(sorc / "nodir" / "plain.f90", "module a\nend module a\n")
        dirs = FortranParser(tmp_path).discover_include_dirs()
        names = {Path(d).name for d in dirs}
        assert {"inc", "fh", "incdir"}.issubset(names)
        assert "nodir" not in names

    def test_cached(self, tmp_path):
        sorc = tmp_path / "sorc"
        _write(sorc / "inc" / "consts.h", "#define X 1\n")
        parser = FortranParser(tmp_path)
        first = parser.discover_include_dirs()
        second = parser.discover_include_dirs()
        assert first is second  # cached list object reused
