# Documentation Sources Manifest
**Version:** 4.2.0  
**Last Updated:** November 11, 2025  
**Purpose:** Comprehensive inventory of all documentation sources ingested into ChromaDB

---

## Overview

This manifest lists all documentation sources organized by tier. Each tier represents the priority and relevance to global-workflow operations.

**Total Sources:** 10  
**Target Collection:** `global-workflow-docs-v4-2-0-unified`  
**Expected Chunks:** ~2,000-3,000

---

## Tier 1: Critical Operational Documentation

**Priority:** Highest (1)  
**Purpose:** Core documentation required for daily global-workflow operations

### 1.1 Global Workflow
- **Name:** `global-workflow`
- **URL:** https://global-workflow.readthedocs.io/en/latest/
- **Type:** ReadTheDocs
- **Description:** Main global-workflow documentation covering system architecture, job scripts, configuration, workflow orchestration, and operational procedures
- **Key Content:** 
  - System overview and architecture
  - Job script documentation (J-jobs, ex-scripts)
  - Configuration management
  - Rocoto workflow XML
  - Operational procedures for WCOSS2, Hera, Orion
- **Max Pages:** 100

### 1.2 UFS Utilities
- **Name:** `ufs-utils`
- **URL:** https://noaa-emcufs-utils.readthedocs.io/en/latest/
- **Type:** ReadTheDocs
- **Description:** UFS utilities and pre-processing tools for grid generation, initial conditions, and data preparation
- **Key Content:**
  - chgres_cube: Initial condition generation
  - orog_gsl: Orography processing
  - sfc_climo_gen: Surface climatology
  - Grid generation utilities
- **Max Pages:** 100

---

## Tier 2: Infrastructure & Workflow Execution

**Priority:** High (2)  
**Purpose:** Supporting infrastructure, models, and workflow execution frameworks

### 2.1 UFS Weather Model
- **Name:** `ufs-weather-model`
- **URL:** https://ufs-weather-model.readthedocs.io/en/latest/
- **Type:** ReadTheDocs
- **Description:** Unified Forecast System weather model documentation covering model physics, dynamics, configuration, and coupling
- **Key Content:**
  - Model physics packages
  - FV3 dynamical core
  - CCPP (Common Community Physics Package)
  - Atmosphere-ocean-ice coupling
  - Namelist configuration
- **Max Pages:** 100

### 2.2 wxflow
- **Name:** `wxflow`
- **URL:** https://wxflow.readthedocs.io/en/latest/
- **Type:** ReadTheDocs
- **Description:** Python workflow execution library providing task management, configuration handling, file staging, and utility functions
- **Key Content:**
  - Task class and execution patterns
  - Configuration (AttrDict, YAMLFile)
  - File staging (FileHandler)
  - Template substitution
  - Jinja2 integration
- **Max Pages:** 100

### 2.3 Rocoto Workflow Manager
- **Name:** `rocoto`
- **URL:** http://christopherwharrop.github.io/rocoto/
- **Type:** GitHub Pages
- **Description:** Rocoto workflow management system for defining, executing, and monitoring complex scientific workflows
- **Key Content:**
  - XML workflow syntax
  - Task dependencies
  - Cycle definitions
  - Job submission and monitoring
  - Database management
- **Max Pages:** 50

---

## Tier 3: Build System & Data Assimilation

**Priority:** Medium (2-3)  
**Purpose:** Build infrastructure and data assimilation frameworks

### 3.1 Spack-Stack
- **Name:** `spack-stack`
- **URL:** https://spack-stack.readthedocs.io/en/latest/
- **Type:** ReadTheDocs
- **Description:** Spack-based build system for UFS applications (replaces hpc-stack)
- **Key Content:**
  - Platform-specific configurations
  - Package management with Spack
  - Module system integration (Lmod)
  - Environment setup
  - Common build issues and solutions
- **Max Pages:** 100

### 3.2 JEDI Documentation
- **Name:** `jedi-docs`
- **URL:** https://jointcenterforsatellitedataassimilation-jedi-docs.readthedocs-hosted.com/en/latest/
- **Type:** ReadTheDocs
- **Description:** Joint Effort for Data assimilation Integration (JEDI) framework documentation
- **Key Content:**
  - Data assimilation concepts
  - JEDI architecture
  - Observation operators
  - Variational and ensemble methods
  - YAML configuration
- **Max Pages:** 100

---

## Tier 4: Reference & Style Guides

**Priority:** Low (3)  
**Purpose:** Coding standards, style guides, and documentation conventions

### 4.1 Google Shell Style Guide
- **Name:** `google-shell-style`
- **URL:** https://google.github.io/styleguide/shellguide.html
- **Type:** Single Page
- **Description:** Google's shell scripting style guide for consistent, maintainable bash code
- **Key Content:**
  - Naming conventions
  - Function design
  - Error handling patterns
  - Commenting standards
  - Common pitfalls
- **Max Pages:** 1

### 4.2 PEP 8 Python Style Guide
- **Name:** `pep8`
- **URL:** https://peps.python.org/pep-0008/
- **Type:** Single Page
- **Description:** Python Enhancement Proposal 8 - official Python style guide
- **Key Content:**
  - Code layout and indentation
  - Naming conventions
  - Comments and docstrings
  - Programming recommendations
- **Max Pages:** 1

### 4.3 NumPy Docstring Format
- **Name:** `numpy-docstrings`
- **URL:** https://numpydoc.readthedocs.io/en/latest/format.html
- **Type:** Single Page
- **Description:** NumPy docstring format standard used throughout global-workflow Python code
- **Key Content:**
  - Function and class documentation
  - Parameter descriptions
  - Return value documentation
  - Example sections
- **Max Pages:** 1

---

## Ingestion Configuration

### Rate Limiting
- **Rate:** 1.0 second between requests
- **Respect robots.txt:** Yes
- **Timeout:** 30 seconds per page

### Chunking Strategy
- **Method:** Semantic chunking by headers (H1-H6)
- **Min Chunk Size:** 100 characters
- **Max Chunk Size:** 2000 characters
- **Target Chunk Size:** 200-800 characters

### Quality Filters
- Remove navigation elements
- Skip boilerplate (copyright, "Edit on GitHub")
- Filter low-quality content (< 50 chars)
- Deduplicate by content hash

### Metadata Enrichment
Each chunk includes:
- **source:** Source name (e.g., "global-workflow")
- **tier:** Priority tier (tier1_critical, tier2_infrastructure, etc.)
- **priority:** Numeric priority (1-3)
- **doc_type:** Type (readthedocs, github_pages, single_page)
- **description:** Source description
- **version:** Ingestion version (4.2.0)
- **url:** Source URL
- **section_hierarchy:** Header hierarchy for chunk
- **content_hash:** MD5 hash for deduplication
- **quality_score:** Quality assessment (0.0-1.0)
- **ingestion_date:** ISO 8601 timestamp

---

## Usage

### List All Sources
```bash
cd /mcp_rag_eib/mcp_server_node/scripts
source load_spack_modules.sh
python3 list_documentation_sources.py
```

### Ingest All Sources
```bash
python3 ingest_documentation_v4_2_unified.py
```

### Ingest Specific Tiers
```bash
# Tier 1 only (critical docs)
python3 ingest_documentation_v4_2_unified.py --tiers tier1_critical

# Tiers 1 and 2 (critical + infrastructure)
python3 ingest_documentation_v4_2_unified.py --tiers tier1_critical tier2_infrastructure
```

### Query Ingested Documents
```bash
# Show collection statistics
python3 manage_chromadb.py info global-workflow-docs-v4-2-0-unified

# List all collections
python3 manage_chromadb.py list
```

---

## Version History

### v4.2.0 (November 11, 2025)
- Unified ingestion using base library
- 10 documentation sources across 4 tiers
- Semantic chunking with quality filters
- Content-based deduplication
- Rich metadata enrichment

### v4.1.0 (November 2025)
- Enhanced chunking and metadata
- 2 sources (global-workflow, ee2-standards)
- 222 chunks ingested

### v4.0.0 (October 2025)
- Initial ReadTheDocs ingestion
- Multiple sources, basic chunking
- 1,852 chunks ingested

---

## Maintenance

### Adding New Sources
1. Edit `ingest_documentation_v4_2_unified.py`
2. Add source to appropriate tier in `DOCUMENTATION_SOURCES`
3. Update this manifest
4. Test with single source first
5. Run full ingestion

### Removing Sources
1. Remove from `DOCUMENTATION_SOURCES`
2. Update this manifest
3. Optionally delete old chunks by source metadata

### Updating Existing Sources
1. Clear old collection or create new versioned collection
2. Run ingestion with updated configuration
3. Verify chunk counts and quality
4. Update MCP server to use new collection

---

## Related Files

- **Ingestion Script:** `ingest_documentation_v4_2_unified.py`
- **Base Library:** `ingestion_base.py`
- **DB Management:** `manage_chromadb.py`
- **Module Loader:** `load_spack_modules.sh`
- **List Utility:** `list_documentation_sources.py` (to be created)

---

## Contact

**Maintainer:** MCP Development Team  
**Repository:** global-workflow (MCP_node.js-RAG_ParallelWorks branch)  
**Location:** `/mcp_rag_eib/global-workflow_MCP_node.js-RAG/dev/ci/scripts/utils/Copilot/mcp_server_node/`
