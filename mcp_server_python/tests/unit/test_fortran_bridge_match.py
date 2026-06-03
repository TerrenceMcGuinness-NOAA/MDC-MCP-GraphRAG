"""Unit tests for Shell→Fortran bridge matching.

Validates: R4.2, R4.4 — all 6 matching strategies + known mappings.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))
sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from scripts.create_shell_fortran_bridge import (
    EXEC_PATTERNS,
    KNOWN_EXEC_MAPPINGS,
    extract_exec_references,
    match_exec_to_program,
)


# Canonical program set simulating Neptune FortranProgram nodes
PROGRAMS = {
    "enkf_main": "enkf_main",
    "gsi": "gsi",
    "ufs_model": "ufs_model",
    "calc_increment": "calc_increment",
    "getsfcensmeanp": "getsfcensmeanp",
    "recentersigp": "recentersigp",
    "global_forecast": "global_forecast",
    "global_forecast_nems": "global_forecast_nems",
    "tocsbufr": "TOCSBUFR",
}


class TestMatchExecToProgram:
    """Exercise all 6 matching strategies."""

    def test_strategy0_known_mapping(self):
        """enkf → enkf_main via KNOWN_EXEC_MAPPINGS."""
        assert match_exec_to_program("enkf", PROGRAMS) == "enkf_main"

    def test_strategy0_known_mapping_none(self):
        """wgrib2 → None (known exec with no Fortran node)."""
        assert match_exec_to_program("wgrib2", PROGRAMS) is None

    def test_strategy0_known_mapping_gsi(self):
        """gsi → gsi via known mapping."""
        assert match_exec_to_program("gsi", PROGRAMS) == "gsi"

    def test_strategy1_exact(self):
        """ufs_model → ufs_model (exact match)."""
        assert match_exec_to_program("ufs_model", PROGRAMS) == "ufs_model"

    def test_strategy2_main_suffix(self):
        """enkf without known mapping would try enkf_main."""
        # Use a programs dict without known mapping interference
        progs = {"foo_main": "foo_main"}
        assert match_exec_to_program("foo", progs) == "foo_main"

    def test_strategy3_prefix_match(self):
        """global_forecast → global_forecast (program starts with exec)."""
        progs = {"global_forecast_nems": "global_forecast_nems"}
        assert match_exec_to_program("global_forecast", progs) == "global_forecast_nems"

    def test_strategy3_prefix_requires_underscore(self):
        """Prefix match requires underscore boundary."""
        progs = {"foobar": "foobar"}
        # "foo" should NOT match "foobar" (no underscore boundary)
        assert match_exec_to_program("foo", progs) is None

    def test_strategy4_exec_starts_with_program(self):
        """calc_increment_ens → calc_increment (exec more specific)."""
        progs = {"calc_increment": "calc_increment"}
        assert match_exec_to_program("calc_increment_ens", progs) == "calc_increment"

    def test_strategy4_requires_underscore_boundary(self):
        """Exec must have _ after program name."""
        progs = {"cal": "cal"}
        # "calc" should NOT match "cal" (no underscore at position 3)
        assert match_exec_to_program("calc", progs) is None

    def test_strategy5_progressive_suffix_strip(self):
        """calc_increment_ens_ncio → calc_increment via stripping."""
        progs = {"calc_increment": "calc_increment"}
        assert match_exec_to_program("calc_increment_ens_ncio", progs) == "calc_increment"

    def test_strategy5_main_suffix_after_strip(self):
        """foo_bar_baz → foo_main when foo_main exists."""
        progs = {"foo_main": "foo_main"}
        assert match_exec_to_program("foo_bar_baz", progs) == "foo_main"

    def test_no_match_returns_none(self):
        """Completely unknown executable → None."""
        assert match_exec_to_program("totally_unknown_exec", PROGRAMS) is None

    def test_case_insensitive(self):
        """Matching is case-insensitive on exec name."""
        assert match_exec_to_program("UFS_MODEL", PROGRAMS) == "ufs_model"


class TestExtractExecReferences:
    """R4.1: exec reference extraction from shell content."""

    def test_exec_var_pattern(self):
        content = "${EXECgfs}/ufs_model.x some_arg"
        refs = extract_exec_references(content)
        assert "ufs_model" in refs

    def test_home_exec_pattern(self):
        content = "${HOMEgfs}/exec/global_forecast.x"
        refs = extract_exec_references(content)
        assert "global_forecast" in refs

    def test_export_pgm_pattern(self):
        content = 'export pgm="gsi.x"'
        refs = extract_exec_references(content)
        assert "gsi" in refs

    def test_pgm_assignment(self):
        content = 'pgm="enkf.x"'
        refs = extract_exec_references(content)
        assert "enkf" in refs

    def test_multiple_refs(self):
        content = (
            "${EXECgfs}/ufs_model.x\n"
            "export pgm=gsi.x\n"
            "${HOMEgfs}/exec/global_forecast.x\n"
        )
        refs = extract_exec_references(content)
        assert "ufs_model" in refs
        assert "gsi" in refs
        assert "global_forecast" in refs

    def test_single_char_filtered(self):
        """Single character matches are skipped (len > 1 required)."""
        content = "${EXECgfs}/x.x"
        refs = extract_exec_references(content)
        assert "x" not in refs

    def test_deduplication(self):
        """Same exec referenced multiple times → single entry."""
        content = "${EXECgfs}/gsi.x\n${EXECgfs}/gsi.x"
        refs = extract_exec_references(content)
        assert len([r for r in refs if r == "gsi"]) == 1


class TestExecPatterns:
    """Verify the 4 EXEC_PATTERNS compile and match expected forms."""

    def test_pattern_count(self):
        assert len(EXEC_PATTERNS) == 4

    def test_exec_pattern_matches(self):
        assert EXEC_PATTERNS[0].search("${EXECgfs}/model.x")
        assert EXEC_PATTERNS[1].search("${HOMEgfs}/exec/model.x")
        assert EXEC_PATTERNS[2].search('export pgm="model.x"')
        assert EXEC_PATTERNS[3].search('pgm="model.x"')
