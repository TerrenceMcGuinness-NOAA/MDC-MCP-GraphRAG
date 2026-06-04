"""Unit test for discover_config_files.

Validates: R1.1 (discovery + exclusion + system assignment).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))
sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from scripts.ingest_config_files_v8 import discover_config_files


def _make_tree(root: Path):
    for system in ("gfs", "gefs"):
        d = root / "parm" / "config" / system
        d.mkdir(parents=True)
        (d / "config.fcst").write_text("export A=1")
        (d / "config.base").write_text("export B=2")
        (d / "config.fcst.j2").write_text("{{ x }}")      # excluded
        (d / "config.yaml").write_text("a: 1")            # excluded
        (d / ".hidden").write_text("x")                   # excluded
        (d / "subdir").mkdir()                            # not a file


class TestDiscovery:
    def test_includes_only_plain_configs(self, tmp_path):
        _make_tree(tmp_path)
        configs = discover_config_files(tmp_path)
        names = {c['filename'] for c in configs}
        assert names == {'config.fcst', 'config.base'}

    def test_system_assignment(self, tmp_path):
        _make_tree(tmp_path)
        configs = discover_config_files(tmp_path)
        gfs = {c['filename'] for c in configs if c['system'] == 'gfs'}
        gefs = {c['filename'] for c in configs if c['system'] == 'gefs'}
        assert gfs == {'config.fcst', 'config.base'}
        assert gefs == {'config.fcst', 'config.base'}

    def test_rel_path_is_relative(self, tmp_path):
        _make_tree(tmp_path)
        configs = discover_config_files(tmp_path)
        for c in configs:
            assert c['rel_path'].startswith('parm/config/')
            assert not c['rel_path'].startswith('/')

    def test_missing_dirs_skipped(self, tmp_path):
        # only gfs present
        d = tmp_path / "parm" / "config" / "gfs"
        d.mkdir(parents=True)
        (d / "config.fcst").write_text("export A=1")
        configs = discover_config_files(tmp_path)
        assert len(configs) == 1
        assert configs[0]['system'] == 'gfs'

    def test_empty_when_no_config_root(self, tmp_path):
        assert discover_config_files(tmp_path) == []
