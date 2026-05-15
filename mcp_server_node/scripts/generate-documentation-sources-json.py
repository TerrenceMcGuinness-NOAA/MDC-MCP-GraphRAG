#!/usr/bin/env python3
"""
Generate documentation_sources.json from the SPOT Python config.

This script reads the authoritative documentation_sources_config.py and
writes a JSON snapshot to config/documentation_sources.json for consumption
by the Node.js MCP server tools (list_ingested_urls, get_ingested_urls_array).

Usage:
    python3 scripts/generate-documentation-sources-json.py [--dry-run]

SPOT Directive:
    The Python config at scripts/documentation_sources_config.py is the
    SINGLE SOURCE OF TRUTH. This script generates a derived artifact.
    NEVER edit config/documentation_sources.json directly.
"""

import json
import os
import sys

# Resolve paths relative to this script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from documentation_sources_config import (
    DOCUMENTATION_SOURCES,
    VERSION,
    get_all_sources,
    get_tier_names,
    get_total_source_count,
)

OUTPUT_PATH = os.path.join(SCRIPT_DIR, '..', 'config', 'documentation_sources.json')


def generate():
    """Generate the JSON config from the Python SPOT."""
    sources = []
    for tier_name in get_tier_names():
        tier_sources = DOCUMENTATION_SOURCES.get(tier_name, [])
        for s in tier_sources:
            entry = {
                'name': s['name'],
                'url': s['url'],
                'type': s.get('type', 'readthedocs'),
                'tier': tier_name,
                'priority': s.get('priority', 3),
                'description': s.get('description', ''),
                'max_pages': s.get('max_pages', 100),
                'enabled': s.get('enabled', True),
            }
            if s.get('local_path'):
                entry['local_path'] = s['local_path']
            sources.append(entry)

    config = {
        'version': VERSION,
        'description': (
            'Documentation sources for MCP RAG ingestion. '
            'AUTO-GENERATED from scripts/documentation_sources_config.py — DO NOT EDIT.'
        ),
        'generated_by': 'scripts/generate-documentation-sources-json.py',
        'total_sources': len(sources),
        'enabled_sources': sum(1 for s in sources if s['enabled']),
        'sources': sources,
    }
    return config


def main():
    dry_run = '--dry-run' in sys.argv

    config = generate()
    json_str = json.dumps(config, indent=2) + '\n'

    enabled = config['enabled_sources']
    total = config['total_sources']

    if dry_run:
        print(f'[DRY-RUN] Would write {total} sources ({enabled} enabled) to {OUTPUT_PATH}')
        print(f'[DRY-RUN] Version: {config["version"]}')
        for s in config['sources']:
            status = 'ON ' if s['enabled'] else 'OFF'
            print(f'  [{status}] {s["name"]:40s} {s["url"][:70]}')
        return

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w') as f:
        f.write(json_str)

    print(f'[OK] Wrote {total} sources ({enabled} enabled) to {OUTPUT_PATH}')
    print(f'[OK] Version: {config["version"]}')


if __name__ == '__main__':
    main()
