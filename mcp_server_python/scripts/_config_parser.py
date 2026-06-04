"""Config file parser for environment-variable lineage extraction.

Ported verbatim from mcp_server_node/scripts/ingest_config_files.py::ConfigFileParser.
Regex patterns are battle-tested against real GFS config files — do NOT modify.

Implements: R1.2–R1.6 of graph-port-workflow-structure.
"""
from __future__ import annotations

import re
from pathlib import Path

CATEGORY_MAP = {
    'base': 'common', 'fcst': 'forecast', 'anal': 'analysis',
    'analcalc': 'analysis', 'analdiag': 'analysis',
    'resources': 'resources', 'arch': 'archive', 'arch_tars': 'archive',
    'cleanup': 'housekeeping', 'stage_ic': 'initialization',
    'prep': 'preprocessing', 'sfcanl': 'surface_analysis',
    'tracker': 'verification', 'genesis': 'verification',
    'fit2obs': 'verification', 'verfozn': 'verification',
    'verfrad': 'verification', 'metp': 'verification',
    'ocn': 'ocean', 'ice': 'ice', 'wave': 'wave',
    'marineanl': 'marine_analysis', 'marinebmat': 'marine_analysis',
    'aeroanl': 'aerosol_analysis', 'aeroanlvar': 'aerosol_analysis',
    'snowanl': 'snow_analysis', 'esnowanl': 'snow_analysis',
    'ecen': 'ensemble', 'eobs': 'ensemble', 'eupd': 'ensemble',
    'esfc': 'ensemble', 'epos': 'ensemble', 'earc': 'ensemble',
    'atmanl': 'atmospheric_analysis', 'atmensanl': 'ensemble_analysis',
}


class ConfigFileParser:
    """Parse shell config files to extract environment variables and sources."""

    # Matches: export VAR=value, export VAR=${VAR:-default}, VAR=value
    ENV_PATTERN = re.compile(
        r'^(?:export\s+)?([A-Z_][A-Z0-9_]*)=(?:\$\{[^}]*:-)?([^}"\n]*)'
    )
    # Also match: export VAR="${VAR:-default}"
    ENV_PATTERN_QUOTED = re.compile(
        r'^(?:export\s+)?([A-Z_][A-Z0-9_]*)=["\']?\$\{([^}]*):-([^}]*)\}["\']?'
    )
    # Simple export: export VAR="literal"
    ENV_SIMPLE = re.compile(
        r'^(?:export\s+)([A-Z_][A-Z0-9_]*)=["\']([^"\']*)["\']'
    )
    # Source patterns
    SOURCE_PATTERN = re.compile(
        r'(?:source|\.\s+)["\s]*([^\s;|&"\'#]+)'
    )
    # Bare export (no value, just declaring)
    BARE_EXPORT = re.compile(r'^export\s+([A-Z_][A-Z0-9_]*)\s*$')

    @staticmethod
    def parse_config_file(file_path: str) -> dict:
        """Extract environment variables and metadata from a config file.

        Returns
        -------
        dict
            {env_vars: [{name, default_value, is_default}], sources: [...],
             raw_content: str, line_count: int}
        """
        env_vars = []
        sources = []
        seen_vars: set[str] = set()

        try:
            content = Path(file_path).read_text(errors='replace')
        except Exception as e:
            return {'env_vars': [], 'sources': [], 'raw_content': '',
                    'line_count': 0, 'error': str(e)}

        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue

            # Priority order: quoted-with-default → simple → general → bare → source
            m = ConfigFileParser.ENV_PATTERN_QUOTED.match(stripped)
            if m:
                var_name = m.group(1)
                default_val = m.group(3).strip('"\'')
                if var_name not in seen_vars:
                    env_vars.append({'name': var_name,
                                     'default_value': default_val,
                                     'is_default': True})
                    seen_vars.add(var_name)
                continue

            m = ConfigFileParser.ENV_SIMPLE.match(stripped)
            if m:
                var_name, value = m.group(1), m.group(2)
                if var_name not in seen_vars:
                    env_vars.append({'name': var_name,
                                     'default_value': value,
                                     'is_default': False})
                    seen_vars.add(var_name)
                continue

            m = ConfigFileParser.ENV_PATTERN.match(stripped)
            if m:
                var_name = m.group(1)
                value = m.group(2).strip('"\'')
                if var_name not in seen_vars:
                    env_vars.append({'name': var_name,
                                     'default_value': value,
                                     'is_default': ':-' in stripped})
                    seen_vars.add(var_name)
                continue

            m = ConfigFileParser.BARE_EXPORT.match(stripped)
            if m:
                var_name = m.group(1)
                if var_name not in seen_vars:
                    env_vars.append({'name': var_name,
                                     'default_value': '',
                                     'is_default': False})
                    seen_vars.add(var_name)
                continue

            m = ConfigFileParser.SOURCE_PATTERN.search(stripped)
            if m:
                sources.append(m.group(1))

        return {
            'env_vars': env_vars,
            'sources': sources,
            'raw_content': content,
            'line_count': len(content.splitlines()),
        }

    @staticmethod
    def categorize_config(filename: str) -> str:
        """Map config filename to category using CATEGORY_MAP."""
        name = filename.replace('config.', '')
        if name.startswith('resources'):
            return 'resources'
        for key, category in CATEGORY_MAP.items():
            if name.startswith(key):
                return category
        return 'other'

    @staticmethod
    def config_short_name(filename: str) -> str:
        """Extract short name: 'config.fcst' → 'fcst'."""
        if filename.startswith('config.'):
            return filename[7:]
        return filename
