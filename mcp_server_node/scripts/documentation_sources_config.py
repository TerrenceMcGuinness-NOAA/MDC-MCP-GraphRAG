#!/usr/bin/env python3
"""
Documentation Sources Configuration
Central registry of all documentation sources for ingestion

This is the SINGLE SOURCE OF TRUTH for documentation URLs.
All ingestion and listing scripts MUST import from this file.

Version: 4.2.1
Last Updated: November 14, 2025
"""

# Current active version
VERSION = "4.2.1"
COLLECTION_NAME = "global-workflow-docs-v4-2-0-unified"

# Documentation sources organized by tier
# Format:
#   'name': Unique identifier for source
#   'url': Base URL to crawl
#   'type': readthedocs | github_pages | single_page
#   'priority': Numeric priority (1=highest, 3=lowest)
#   'description': Human-readable purpose
#   'max_pages': Optional crawl limit (default: 100)

DOCUMENTATION_SOURCES = {
    'tier1_critical': [
        {
            'name': 'global-workflow',
            'url': 'https://global-workflow.readthedocs.io/en/latest/',
            'type': 'readthedocs',
            'priority': 1,
            'description': 'Main global-workflow documentation',
            'max_pages': 100
        },
        {
            'name': 'ee2-standards',
            'url': 'https://nws-hpc-standards.readthedocs.io/en/latest/',
            'type': 'readthedocs',
            'priority': 1,
            'description': 'NOAA EE2 HPC standards and compliance',
            'max_pages': 100
        },
        {
            'name': 'ufs-utils',
            'url': 'https://noaa-emcufs-utils.readthedocs.io/en/latest/',
            'type': 'readthedocs',
            'priority': 1,
            'description': 'UFS utilities and pre-processing tools',
            'max_pages': 100
        }
    ],
    'tier2_infrastructure': [
        {
            'name': 'ufs-weather-model',
            'url': 'https://ufs-weather-model.readthedocs.io/en/latest/',
            'type': 'readthedocs',
            'priority': 2,
            'description': 'UFS Weather Model documentation',
            'max_pages': 100
        },
        {
            'name': 'wxflow',
            'url': 'https://wxflow.readthedocs.io/en/latest/',
            'type': 'readthedocs',
            'priority': 2,
            'description': 'Python workflow execution library',
            'max_pages': 100
        },
        {
            'name': 'rocoto',
            'url': 'http://christopherwharrop.github.io/rocoto/',
            'type': 'github_pages',
            'priority': 2,
            'description': 'Rocoto workflow manager',
            'max_pages': 50
        },
        {
            'name': 'ecflow',
            'url': 'https://ecflow.readthedocs.io/en/develop/',
            'type': 'readthedocs',
            'priority': 2,
            'description': 'ecFlow workflow scheduler and manager (ECMWF)',
            'max_pages': 100
        },
        {
            'name': 'pyflow',
            'url': 'https://pyflow-workflow-generator.readthedocs.io/en/latest/',
            'type': 'readthedocs',
            'priority': 2,
            'description': 'Pyflow Python workflow generator',
            'max_pages': 100
        }
    ],
    'tier3_build_system': [
        {
            'name': 'spack-stack',
            'url': 'https://spack-stack.readthedocs.io/en/latest/',
            'type': 'readthedocs',
            'priority': 2,
            'description': 'Spack-stack build system',
            'max_pages': 100
        },
        {
            'name': 'jedi-docs',
            'url': 'https://jointcenterforsatellitedataassimilation-jedi-docs.readthedocs-hosted.com/en/latest/',
            'type': 'readthedocs',
            'priority': 3,
            'description': 'JEDI data assimilation framework',
            'max_pages': 100
        }
    ],
    'tier4_reference': [
        {
            'name': 'google-shell-style',
            'url': 'https://google.github.io/styleguide/shellguide.html',
            'type': 'single_page',
            'priority': 3,
            'description': 'Google Shell Style Guide',
            'max_pages': 1
        },
        {
            'name': 'pep8',
            'url': 'https://peps.python.org/pep-0008/',
            'type': 'single_page',
            'priority': 3,
            'description': 'PEP 8 Python Style Guide',
            'max_pages': 1
        },
        {
            'name': 'numpy-docstrings',
            'url': 'https://numpydoc.readthedocs.io/en/latest/format.html',
            'type': 'single_page',
            'priority': 3,
            'description': 'NumPy docstring format',
            'max_pages': 1
        }
    ]
}


def get_all_sources():
    """Return flat list of all sources"""
    all_sources = []
    for tier_name, sources in DOCUMENTATION_SOURCES.items():
        for source in sources:
            source_copy = source.copy()
            source_copy['tier'] = tier_name
            all_sources.append(source_copy)
    return all_sources


def get_sources_by_tier(tier_name):
    """Get sources for specific tier"""
    return DOCUMENTATION_SOURCES.get(tier_name, [])


def get_source_by_name(name):
    """Find source by name across all tiers"""
    for tier_name, sources in DOCUMENTATION_SOURCES.items():
        for source in sources:
            if source['name'] == name:
                result = source.copy()
                result['tier'] = tier_name
                return result
    return None


def get_tier_names():
    """Return list of tier names"""
    return list(DOCUMENTATION_SOURCES.keys())


def get_total_source_count():
    """Return total number of sources"""
    return sum(len(sources) for sources in DOCUMENTATION_SOURCES.values())


def validate_sources():
    """Validate source configuration"""
    errors = []
    names_seen = set()
    
    for tier_name, sources in DOCUMENTATION_SOURCES.items():
        for source in sources:
            # Check required fields
            required = ['name', 'url', 'type', 'priority', 'description']
            for field in required:
                if field not in source:
                    errors.append(f"{tier_name}/{source.get('name', 'unknown')}: Missing '{field}'")
            
            # Check for duplicate names
            name = source.get('name')
            if name in names_seen:
                errors.append(f"Duplicate source name: {name}")
            names_seen.add(name)
            
            # Validate type
            valid_types = ['readthedocs', 'github_pages', 'single_page']
            if source.get('type') not in valid_types:
                errors.append(f"{name}: Invalid type '{source.get('type')}' (must be one of {valid_types})")
            
            # Validate priority
            if not isinstance(source.get('priority'), int) or source.get('priority') < 1:
                errors.append(f"{name}: Invalid priority (must be integer >= 1)")
    
    return errors


if __name__ == '__main__':
    # Self-test when run directly
    print(f"Documentation Sources Configuration v{VERSION}")
    print("="*70)
    print(f"Total sources: {get_total_source_count()}")
    print(f"Tiers: {', '.join(get_tier_names())}")
    print("\nValidating configuration...")
    
    errors = validate_sources()
    if errors:
        print("\n[ERROR] Configuration errors found:")
        for error in errors:
            print(f"  - {error}")
    else:
        print("[OK] Configuration is valid")
    
    print("\nSource breakdown by tier:")
    for tier in get_tier_names():
        sources = get_sources_by_tier(tier)
        print(f"  {tier}: {len(sources)} sources")
