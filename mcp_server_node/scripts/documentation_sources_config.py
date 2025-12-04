#!/usr/bin/env python3
"""
================================================================================
SINGLE POINT OF TRUTH (SPOT) - Documentation Sources Configuration
================================================================================

This file is the AUTHORITATIVE SOURCE for all documentation URLs used in the
MCP RAG ingestion pipeline. 

╔══════════════════════════════════════════════════════════════════════════════╗
║  SPOT DIRECTIVE: DO NOT DUPLICATE THIS CONFIGURATION                        ║
║                                                                              ║
║  All ingestion scripts MUST import from this file:                           ║
║                                                                              ║
║    from documentation_sources_config import (                                ║
║        DOCUMENTATION_SOURCES,                                                ║
║        VERSION,                                                              ║
║        get_all_sources,                                                      ║
║        get_tier_names                                                        ║
║    )                                                                         ║
║                                                                              ║
║  NEVER copy-paste source definitions into other scripts.                     ║
║  If you need to modify sources, modify THIS FILE ONLY.                       ║
╚══════════════════════════════════════════════════════════════════════════════╝

Version: 7.0.0
Last Updated: December 4, 2025
Maintainer: NOAA EMC Global Workflow MCP Team
"""

import os

# =============================================================================
# VERSION CONFIGURATION
# =============================================================================

VERSION = "7.0.0"

# Collection name can be overridden via environment variable
DEFAULT_COLLECTION_NAME = "global-workflow-docs-v7-0-0"
COLLECTION_NAME = os.getenv("DOCS_COLLECTION", DEFAULT_COLLECTION_NAME)

# =============================================================================
# DOCUMENTATION SOURCES - SINGLE POINT OF TRUTH
# =============================================================================
#
# Tier Organization:
#   tier1_critical     - Core workflow documentation (must ingest first)
#   tier2_workflow     - Workflow orchestration tools (Rocoto, ecFlow, wxflow)
#   tier3_models       - UFS models and components
#   tier4_build        - Build systems and package management
#   tier5_standards    - Coding standards and style guides
#
# Source Fields:
#   name        : Unique identifier (used in metadata and deduplication)
#   url         : Base URL to crawl (include trailing slash for directories)
#   type        : readthedocs | github_pages | single_page
#   priority    : 1 (critical) to 5 (reference)
#   description : Human-readable purpose
#   max_pages   : Crawl limit (default: 100)
#   enabled     : Set to False to skip during ingestion (default: True)
#
# =============================================================================

DOCUMENTATION_SOURCES = {
    # =========================================================================
    # TIER 1: CRITICAL - Core Global Workflow Documentation
    # =========================================================================
    'tier1_critical': [
        {
            'name': 'global-workflow',
            'url': 'https://global-workflow.readthedocs.io/en/latest/',
            'type': 'readthedocs',
            'priority': 1,
            'description': 'Main global-workflow documentation - GFS/GEFS/SFS operations',
            'max_pages': 150,
            'enabled': True
        },
        {
            'name': 'ee2-standards',
            'url': 'https://nws-hpc-standards.readthedocs.io/en/latest/',
            'type': 'readthedocs',
            'priority': 1,
            'description': 'NOAA EE2 HPC standards and compliance requirements',
            'max_pages': 100,
            'enabled': True
        },
        {
            'name': 'ufs-utils',
            'url': 'https://noaa-emcufs-utils.readthedocs.io/en/latest/',
            'type': 'readthedocs',
            'priority': 1,
            'description': 'UFS utilities - chgres_cube, grid generation, preprocessing',
            'max_pages': 100,
            'enabled': True
        }
    ],

    # =========================================================================
    # TIER 2: WORKFLOW - Workflow Orchestration Tools
    # =========================================================================
    'tier2_workflow': [
        {
            'name': 'rocoto',
            'url': 'https://christopherwharrop.github.io/rocoto/',
            'type': 'github_pages',
            'priority': 2,
            'description': 'Rocoto workflow manager - XML-based job orchestration',
            'max_pages': 50,
            'enabled': True
        },
        {
            'name': 'ecflow',
            'url': 'https://ecflow.readthedocs.io/en/latest/',
            'type': 'readthedocs',
            'priority': 2,
            'description': 'ecFlow workflow scheduler (ECMWF) - suite definitions',
            'max_pages': 150,
            'enabled': True
        },
        {
            'name': 'wxflow',
            'url': 'https://wxflow.readthedocs.io/en/latest/',
            'type': 'readthedocs',
            'priority': 2,
            'description': 'wxflow Python library - workflow execution utilities',
            'max_pages': 100,
            'enabled': True
        },
        {
            'name': 'pyflow',
            'url': 'https://pyflow-workflow-generator.readthedocs.io/en/latest/',
            'type': 'readthedocs',
            'priority': 2,
            'description': 'Pyflow - Python ecFlow workflow generator',
            'max_pages': 100,
            'enabled': True
        }
    ],

    # =========================================================================
    # TIER 3: MODELS - UFS Models and Components
    # =========================================================================
    'tier3_models': [
        {
            'name': 'ufs-weather-model',
            'url': 'https://ufs-weather-model.readthedocs.io/en/latest/',
            'type': 'readthedocs',
            'priority': 2,
            'description': 'UFS Weather Model - atmospheric model documentation',
            'max_pages': 150,
            'enabled': True
        },
        {
            'name': 'jedi-docs',
            'url': 'https://jointcenterforsatellitedataassimilation-jedi-docs.readthedocs-hosted.com/en/latest/',
            'type': 'readthedocs',
            'priority': 3,
            'description': 'JEDI - Joint Effort for Data Assimilation Integration',
            'max_pages': 150,
            'enabled': True
        },
        {
            'name': 'fv3-dynamical-core',
            'url': 'https://noaa-gfdl.github.io/GFDL_atmos_cubed_sphere/',
            'type': 'github_pages',
            'priority': 3,
            'description': 'FV3 Dynamical Core - cubed sphere atmospheric dynamics',
            'max_pages': 50,
            'enabled': True
        }
    ],

    # =========================================================================
    # TIER 4: BUILD - Build Systems and Package Management
    # =========================================================================
    'tier4_build': [
        {
            'name': 'spack-stack',
            'url': 'https://spack-stack.readthedocs.io/en/latest/',
            'type': 'readthedocs',
            'priority': 2,
            'description': 'spack-stack - HPC software stack (NOAA/NASA/Navy)',
            'max_pages': 150,
            'enabled': True
        },
        {
            'name': 'spack',
            'url': 'https://spack.readthedocs.io/en/latest/',
            'type': 'readthedocs',
            'priority': 3,
            'description': 'Spack package manager - LLNL HPC package management',
            'max_pages': 100,
            'enabled': True
        },
        {
            'name': 'hpc-stack',
            'url': 'https://hpc-stack.readthedocs.io/en/latest/',
            'type': 'readthedocs',
            'priority': 3,
            'description': 'HPC-Stack - legacy NOAA HPC software stack',
            'max_pages': 50,
            'enabled': True
        }
    ],

    # =========================================================================
    # TIER 5: STANDARDS - Coding Standards and Style Guides
    # =========================================================================
    'tier5_standards': [
        {
            'name': 'google-shell-style',
            'url': 'https://google.github.io/styleguide/shellguide.html',
            'type': 'single_page',
            'priority': 4,
            'description': 'Google Shell Style Guide - bash best practices',
            'max_pages': 1,
            'enabled': True
        },
        {
            'name': 'pep8',
            'url': 'https://peps.python.org/pep-0008/',
            'type': 'single_page',
            'priority': 4,
            'description': 'PEP 8 - Python Style Guide',
            'max_pages': 1,
            'enabled': True
        },
        {
            'name': 'numpy-docstrings',
            'url': 'https://numpydoc.readthedocs.io/en/latest/format.html',
            'type': 'single_page',
            'priority': 4,
            'description': 'NumPy docstring format - Python documentation standard',
            'max_pages': 1,
            'enabled': True
        },
        {
            'name': 'fortran-best-practices',
            'url': 'https://fortran-lang.org/learn/best_practices/',
            'type': 'single_page',
            'priority': 4,
            'description': 'Fortran best practices - modern Fortran guidelines',
            'max_pages': 10,
            'enabled': True
        }
    ]
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_all_sources(enabled_only=True):
    """
    Return flat list of all sources.
    
    Args:
        enabled_only: If True, only return sources with enabled=True (default)
    
    Returns:
        List of source dicts with 'tier' field added
    """
    all_sources = []
    for tier_name, sources in DOCUMENTATION_SOURCES.items():
        for source in sources:
            if enabled_only and not source.get('enabled', True):
                continue
            source_copy = source.copy()
            source_copy['tier'] = tier_name
            all_sources.append(source_copy)
    return all_sources


def get_sources_by_tier(tier_name, enabled_only=True):
    """Get sources for specific tier"""
    sources = DOCUMENTATION_SOURCES.get(tier_name, [])
    if enabled_only:
        return [s for s in sources if s.get('enabled', True)]
    return sources


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
    """Return list of tier names in order"""
    return list(DOCUMENTATION_SOURCES.keys())


def get_total_source_count(enabled_only=True):
    """Return total number of sources"""
    if enabled_only:
        return len(get_all_sources(enabled_only=True))
    return sum(len(sources) for sources in DOCUMENTATION_SOURCES.values())


def get_sources_by_priority(max_priority=5, enabled_only=True):
    """Get all sources up to specified priority level"""
    sources = get_all_sources(enabled_only=enabled_only)
    return [s for s in sources if s.get('priority', 5) <= max_priority]


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
            
            # Validate URL format
            url = source.get('url', '')
            if not url.startswith(('http://', 'https://')):
                errors.append(f"{name}: Invalid URL format (must start with http:// or https://)")
    
    return errors


# =============================================================================
# COMMAND LINE INTERFACE
# =============================================================================

if __name__ == '__main__':
    import sys
    
    print("="*80)
    print(f"DOCUMENTATION SOURCES - SINGLE POINT OF TRUTH (SPOT) v{VERSION}")
    print("="*80)
    
    # Validate first
    errors = validate_sources()
    if errors:
        print("\n[ERROR] Configuration errors found:")
        for error in errors:
            print(f"  - {error}")
        sys.exit(1)
    
    print(f"\n[OK] Configuration valid")
    print(f"Collection: {COLLECTION_NAME}")
    print(f"Total sources: {get_total_source_count()} enabled ({get_total_source_count(enabled_only=False)} total)")
    
    # Print each tier
    for tier_name in get_tier_names():
        sources = get_sources_by_tier(tier_name)
        print(f"\n{tier_name.upper().replace('_', ' ')}")
        print("-"*80)
        print(f"{'Name':<22} {'Type':<14} {'Pri':<4} {'Max':<5} {'URL'}")
        print("-"*80)
        
        for source in sources:
            name = source['name']
            url = source['url']
            src_type = source['type']
            priority = source['priority']
            max_pages = source.get('max_pages', 100)
            enabled = source.get('enabled', True)
            
            status = "" if enabled else " [DISABLED]"
            print(f"{name:<22} {src_type:<14} {priority:<4} {max_pages:<5} {url}{status}")
    
    print("\n" + "="*80)
    print("Use: python3 list_documentation_sources.py --format detailed")
    print("="*80)
