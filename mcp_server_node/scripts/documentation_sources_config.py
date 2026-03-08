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

VERSION = "8.0.0"

# Collection name can be overridden via environment variable
DEFAULT_COLLECTION_NAME = "global-workflow-docs-v8-0-0"
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
            'description': 'NOAA EE2 HPC standards - USE LOCAL RST via ingest_ee2_v7.py instead',
            'max_pages': 100,
            'enabled': False  # Disabled - use local nws-hpc-standards submodule for richer RST parsing
        },
        {
            'name': 'ufs-utils',
            'url': 'https://noaa-emcufs-utils.readthedocs.io/en/latest/',
            'type': 'readthedocs',
            'priority': 1,
            'description': 'UFS utilities - chgres_cube, grid generation, preprocessing',
            'max_pages': 100,
            'enabled': True
        },
        {
            'name': 'esmf-user-guide',
            'url': 'https://earthsystemmodeling.org/docs/release/latest/ESMF_usrdoc/',
            'type': 'readthedocs',
            'priority': 1,
            'description': 'ESMF User Guide - Earth System Modeling Framework (coupling backbone)',
            'max_pages': 250,
            'enabled': True
        },
        {
            'name': 'nuopc-layer-reference',
            'url': 'https://earthsystemmodeling.org/docs/release/latest/NUOPC_refdoc/',
            'type': 'readthedocs',
            'priority': 1,
            'description': 'NUOPC Layer Reference - component model interface standard',
            'max_pages': 150,
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
            'enabled': True,
            # URL patterns to exclude (ecFlow restructured docs in 2024)
            # Old flat structure moved to python_api/, ug/, client_api/ subdirs
            'exclude_url_patterns': [
                # Old flat structure URLs that now 404
                r'/en/latest/[A-Z][a-z]+\.html$',  # e.g., /Suite.html, /Defs.html (now in /python_api/)
                r'/en/latest/user_manual/',        # Moved to /ug/
                r'/en/latest/ecflow_ui/',          # May have moved
                r'/en/latest/get_state\.html$',    # Old CLI docs
                r'/en/latest/complete\.html$',
                r'/en/latest/password\.html$',
                r'/en/latest/plug\.html$',
            ]
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
            'url': 'https://www.gfdl.noaa.gov/fv3/',
            'type': 'single_page',
            'priority': 3,
            'description': 'FV3 Dynamical Core - GFDL cubed sphere atmospheric dynamics (superseded by fv3-docs)',
            'max_pages': 10,
            'enabled': False
        },
        {
            'name': 'cmeps',
            'url': 'https://escomp.github.io/CMEPS/',
            'type': 'github_pages',
            'priority': 2,
            'description': 'CMEPS Community Mediator - inter-model data exchange',
            'max_pages': 50,
            'enabled': True
        },
        {
            'name': 'mom6',
            'url': 'https://mom6.readthedocs.io/en/main/',
            'type': 'readthedocs',
            'priority': 2,
            'description': 'MOM6 Ocean Model - modular ocean model v6',
            'max_pages': 200,
            'enabled': True
        },
        {
            'name': 'cice',
            'url': 'https://cice-consortium-cice.readthedocs.io/en/latest/',
            'type': 'readthedocs',
            'priority': 2,
            'description': 'CICE Sea Ice Model - Los Alamos sea ice model',
            'max_pages': 150,
            'enabled': True
        },
        {
            'name': 'ww3-wiki',
            'url': 'https://github.com/NOAA-EMC/WW3/wiki',
            'type': 'github_pages',
            'priority': 3,
            'description': 'WAVEWATCH III - wave model wiki',
            'max_pages': 50,
            'enabled': True
        },
        {
            'name': 'fv3-docs',
            'url': 'https://github.com/NOAA-GFDL/GFDL_atmos_cubed_sphere/wiki',
            'type': 'github_pages',
            'priority': 3,
            'description': 'FV3 Dynamical Core - GFDL cubed-sphere atmospheric dynamics (expanded)',
            'max_pages': 50,
            'enabled': True
        },
        {
            'name': 'gocart',
            'url': 'https://geos-chem.readthedocs.io/en/latest/',
            'type': 'readthedocs',
            'priority': 4,
            'description': 'GEOS-Chem / GOCART - aerosol transport model',
            'max_pages': 100,
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
        # hpc-stack removed (2026-02-17) - legacy, superseded by spack-stack

        # --- NCEPLIBS: individual library API documentation (Doxygen) ---
        # Dashboard at https://noaa-emc.github.io/NCEPLIBS/ is usage tracking only;
        # actual API docs live at per-library github_pages sites below.
        # Added 2026-02-26 - libraries used by GFS/GEFS/Global Workflow
        {
            'name': 'nceplibs-bufr',
            'url': 'https://noaa-emc.github.io/NCEPLIBS-bufr/',
            'type': 'github_pages',
            'priority': 3,
            'description': 'NCEPLIBS-bufr - BUFR format encoding/decoding (300+ subroutines, Python API)',
            'max_pages': 100,
            'enabled': True
        },
        {
            'name': 'nceplibs-ip',
            'url': 'https://noaa-emc.github.io/NCEPLIBS-ip/',
            'type': 'github_pages',
            'priority': 3,
            'description': 'NCEPLIBS-ip - General interpolation library (6 methods, spectral transforms)',
            'max_pages': 80,
            'enabled': True
        },
        {
            'name': 'nceplibs-w3emc',
            'url': 'https://noaa-emc.github.io/NCEPLIBS-w3emc/',
            'type': 'github_pages',
            'priority': 3,
            'description': 'NCEPLIBS-w3emc - GRIB1 decoder/encoder, date/time, bit manipulation',
            'max_pages': 80,
            'enabled': True
        },
        {
            'name': 'nceplibs-g2',
            'url': 'https://noaa-emc.github.io/NCEPLIBS-g2/',
            'type': 'github_pages',
            'priority': 3,
            'description': 'NCEPLIBS-g2 - GRIB2 encoding/decoding, file API, utilities',
            'max_pages': 80,
            'enabled': True
        },
        {
            'name': 'nceplibs-bacio',
            'url': 'https://noaa-emc.github.io/NCEPLIBS-bacio/',
            'type': 'github_pages',
            'priority': 3,
            'description': 'NCEPLIBS-bacio - Binary I/O for NCEP models',
            'max_pages': 30,
            'enabled': True
        },
        {
            'name': 'nceplibs-g2tmpl',
            'url': 'https://noaa-emc.github.io/NCEPLIBS-g2tmpl/',
            'type': 'github_pages',
            'priority': 3,
            'description': 'NCEPLIBS-g2tmpl - GRIB2 template utilities',
            'max_pages': 40,
            'enabled': True
        },
        {
            'name': 'nceplibs-nemsio',
            'url': 'https://noaa-emc.github.io/NCEPLIBS-nemsio/',
            'type': 'github_pages',
            'priority': 3,
            'description': 'NCEPLIBS-nemsio - I/O for NCEP models using NEMS',
            'max_pages': 40,
            'enabled': True
        },
        {
            'name': 'nceplibs-sfcio',
            'url': 'https://noaa-emc.github.io/NCEPLIBS-sfcio/',
            'type': 'github_pages',
            'priority': 4,
            'description': 'NCEPLIBS-sfcio - Surface files I/O',
            'max_pages': 20,
            'enabled': True
        },
        {
            'name': 'nceplibs-sigio',
            'url': 'https://noaa-emc.github.io/NCEPLIBS-sigio/',
            'type': 'github_pages',
            'priority': 4,
            'description': 'NCEPLIBS-sigio - Sigma restart file I/O for global spectral model',
            'max_pages': 20,
            'enabled': True
        },
        {
            'name': 'wgrib2',
            'url': 'https://www.cpc.ncep.noaa.gov/products/wesley/wgrib2/',
            'type': 'single_page',
            'priority': 3,
            'description': 'wgrib2 - GRIB2 file utility (most loaded NCEP module on Hera/Jet)',
            'max_pages': 30,
            'enabled': True
        },
        {
            'name': 'ccpp-techdoc',
            'url': 'https://ccpp-techdoc.readthedocs.io/en/latest/',
            'type': 'readthedocs',
            'priority': 3,
            'description': 'CCPP Common Community Physics Package - physics parameterization framework',
            'max_pages': 100,
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
        },
        {
            'name': 'upp',
            'url': 'https://upp.readthedocs.io/en/latest/',
            'type': 'readthedocs',
            'priority': 3,
            'description': 'Unified Post Processor - model output post-processing',
            'max_pages': 100,
            'enabled': True
        },
        {
            'name': 'metplus',
            'url': 'https://metplus.readthedocs.io/en/latest/',
            'type': 'readthedocs',
            'priority': 3,
            'description': 'METplus Verification Framework - model verification and diagnostics',
            'max_pages': 250,
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
