"""Unit tests for ConfigFileParser.

Validates: R1.2–R1.6 (env-var extraction, sources, category, short-name).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))
sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from scripts._config_parser import CATEGORY_MAP, ConfigFileParser


def _write(tmp_path, content: str) -> str:
    p = tmp_path / "config.test"
    p.write_text(content)
    return str(p)


class TestEnvVarExtraction:
    """R1.2: export VAR=value / ${VAR:-default} / VAR=value."""

    def test_quoted_with_default(self, tmp_path):
        path = _write(tmp_path, 'export COMROOT="${COMROOT:-/com}"')
        r = ConfigFileParser.parse_config_file(path)
        assert r['env_vars'] == [{'name': 'COMROOT',
                                  'default_value': '/com',
                                  'is_default': True}]

    def test_simple_literal(self, tmp_path):
        path = _write(tmp_path, 'export ATM="cubed_sphere"')
        r = ConfigFileParser.parse_config_file(path)
        assert r['env_vars'][0]['name'] == 'ATM'
        assert r['env_vars'][0]['default_value'] == 'cubed_sphere'
        assert r['env_vars'][0]['is_default'] is False

    def test_general_no_export(self, tmp_path):
        path = _write(tmp_path, 'CASE=C384')
        r = ConfigFileParser.parse_config_file(path)
        assert r['env_vars'][0]['name'] == 'CASE'
        assert r['env_vars'][0]['default_value'] == 'C384'

    def test_bare_export(self, tmp_path):
        path = _write(tmp_path, 'export DONST_ON')
        r = ConfigFileParser.parse_config_file(path)
        assert r['env_vars'][0] == {'name': 'DONST_ON',
                                    'default_value': '',
                                    'is_default': False}


class TestSourceExtraction:
    """R1.3: . path and source path → sources."""

    def test_dot_source(self, tmp_path):
        path = _write(tmp_path, '. config.base')
        r = ConfigFileParser.parse_config_file(path)
        assert r['sources'] == ['config.base']

    def test_source_keyword(self, tmp_path):
        path = _write(tmp_path, 'source ${HOMEgfs}/ush/load.sh')
        r = ConfigFileParser.parse_config_file(path)
        assert r['sources'] == ['${HOMEgfs}/ush/load.sh']


class TestSkipAndDedupe:
    """R1.4: skip comments/empty; dedupe vars first-wins."""

    def test_comment_and_empty_skipped(self, tmp_path):
        path = _write(tmp_path, '# comment\n\nexport FOO=1')
        r = ConfigFileParser.parse_config_file(path)
        assert [v['name'] for v in r['env_vars']] == ['FOO']

    def test_duplicate_first_wins(self, tmp_path):
        path = _write(tmp_path, 'export FOO=1\nexport FOO=2')
        r = ConfigFileParser.parse_config_file(path)
        assert len(r['env_vars']) == 1
        assert r['env_vars'][0]['default_value'] == '1'

    def test_line_count(self, tmp_path):
        path = _write(tmp_path, 'export A=1\nexport B=2\n')
        r = ConfigFileParser.parse_config_file(path)
        assert r['line_count'] == 2

    def test_read_error_returns_empty(self):
        r = ConfigFileParser.parse_config_file('/nonexistent/config.x')
        assert r['env_vars'] == []
        assert 'error' in r


class TestCategorize:
    """R1.5: filename → category via CATEGORY_MAP."""

    def test_forecast(self):
        assert ConfigFileParser.categorize_config('config.fcst') == 'forecast'

    def test_resources(self):
        assert ConfigFileParser.categorize_config('config.resources.HERA') == 'resources'

    def test_ensemble(self):
        assert ConfigFileParser.categorize_config('config.eobs') == 'ensemble'

    def test_unknown_other(self):
        assert ConfigFileParser.categorize_config('config.zzz') == 'other'

    def test_map_is_populated(self):
        assert CATEGORY_MAP['base'] == 'common'


class TestShortName:
    """config_short_name strips config. prefix."""

    def test_strip_prefix(self):
        assert ConfigFileParser.config_short_name('config.fcst') == 'fcst'

    def test_no_prefix_unchanged(self):
        assert ConfigFileParser.config_short_name('fcst') == 'fcst'
