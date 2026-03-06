# Phase 41: External Framework Documentation Expansion

**Version**: 1.0.0
**Status**: Planned
**Created**: 2026-03-06
**Author**: AI Assistant + Terry McGuinness
**Dependency**: None (independent — can run in parallel with Phases 38-40)
**Gap Analysis**: [docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md](../../docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md) §5, §6, §7-D

---

## 1. Executive Summary

The expert system has **zero documentation coverage** for the ESMF/NUOPC coupling framework — the backbone that connects all UFS model components. Additionally, documentation for MOM6, CICE, WW3, CMEPS, CCPP, UPP, and METplus is either absent or minimal.

This phase adds **11 new documentation sources** to `documentation_sources_config.py` (the SPOT config) and ingests them into the `global-workflow-docs-v8-0-0` ChromaDB collection, adding an estimated **3,000-5,000 new documentation chunks**.

### Impact

| Category | Before | After |
|----------|--------|-------|
| Documentation sources | 24 enabled | 35 enabled |
| Total doc chunks | 5,409 | ~9,000-11,000 |
| ESMF/NUOPC coverage | 0% | ~80% |
| UFS component model docs | ~10% | ~60% |
| Verification framework docs | 0% | ~70% |

### Motivation

Without ESMF/NUOPC documentation, the expert system cannot explain:
- How model components are coupled via NUOPC caps
- ESMF field bundles, states, and data exchange patterns
- The mediator (CMEPS) architecture
- Component initialization/run/finalize phases

These are exactly the questions users ask when working with the coupled model — and the Phase 39 Fortran graph will produce nodes full of ESMF API calls that are meaningless without context.

---

## 2. Documentation Source Inventory

### 2.1 Missing Critical Sources

| Source | URL | Type | Priority | Est. Pages | Est. Chunks |
|--------|-----|------|----------|-----------|-------------|
| **ESMF User Guide** | `https://earthsystemmodeling.org/docs/release/latest/ESMF_usrdoc/` | HTML (Sphinx) | 1 (CRITICAL) | ~200 | ~800 |
| **NUOPC Layer Reference** | `https://earthsystemmodeling.org/docs/release/latest/NUOPC_refdoc/` | HTML (Sphinx) | 1 (CRITICAL) | ~100 | ~400 |
| **CMEPS Documentation** | `https://escomp.github.io/CMEPS/` | GitHub Pages | 2 (HIGH) | ~30 | ~120 |
| **MOM6 Documentation** | `https://mom6.readthedocs.io/en/latest/` | ReadTheDocs | 2 (HIGH) | ~150 | ~600 |
| **CICE Documentation** | `https://cice-consortium-cice.readthedocs.io/en/latest/` | ReadTheDocs | 2 (HIGH) | ~100 | ~400 |
| **WW3 Wiki** | `https://github.com/NOAA-EMC/WW3/wiki` | GitHub Wiki | 3 (MEDIUM) | ~30 | ~100 |
| **CCPP Technical Docs** | `https://ccpp-techdoc.readthedocs.io/en/latest/` | ReadTheDocs | 3 (MEDIUM) | ~80 | ~300 |
| **UPP Documentation** | `https://upp.readthedocs.io/en/latest/` | ReadTheDocs | 3 (MEDIUM) | ~60 | ~250 |
| **METplus Documentation** | `https://metplus.readthedocs.io/en/latest/` | ReadTheDocs | 3 (MEDIUM) | ~200 | ~800 |
| **FV3 Documentation** | `https://noaa-gfdl.github.io/FV3/` | GitHub Pages | 3 (MEDIUM) | ~40 | ~150 |
| **GOCART Documentation** | `https://geos-chem.readthedocs.io/en/latest/` | ReadTheDocs | 4 (LOW) | ~50 | ~200 |

### 2.2 Sources Already Ingested (for reference)

| Source | Chunks | Status |
|--------|--------|--------|
| global-workflow (RTD) | 171 | LOW — only 21 pages |
| ufs-weather-model (RTD) | 249 | Adequate |
| jedi-docs (RTD) | 107 | Adequate |
| fv3-dynamical-core (GFDL single page) | 71 | LOW — single page |
| NCEPLIBS suite (6 libraries) | ~1,582 | Good |
| spack + spack-stack | 2,095 | Over-represented |
| ecflow | 223 | Good |
| wxflow | 92 | Good |

### 2.3 Existing Low Coverage (candidates for re-crawl with higher page limits)

| Source | Current Chunks | Current max_pages | Recommended |
|--------|---------------|-------------------|-------------|
| global-workflow | 171 | 150 | 300 (many new pages since last crawl) |
| ufs-utils | 90 | 100 | Fine |
| rocoto | 74 | 50 | Fine (small site) |

---

## 3. Technical Specification

### Target File

| File | Purpose |
|------|---------|
| `mcp_server_node/scripts/documentation_sources_config.py` | **MODIFY** — add 11 new sources to SPOT config |

### SPOT Compliance

Per project convention, `documentation_sources_config.py` is the **Single Point of Truth** for all documentation URLs. All source additions go here — never in individual ingestion scripts.

### Tier Assignment

| Tier | New Sources |
|------|-------------|
| `tier1_critical` | ESMF User Guide, NUOPC Layer Reference |
| `tier3_models` | CMEPS, MOM6, CICE, WW3 wiki, FV3 expanded, GOCART |
| `tier4_build` | CCPP (physics framework) |
| `tier5_standards` | UPP (post-processing), METplus (verification) |

---

## 4. Implementation Steps

### Step 41-1: Validate Documentation URLs
**Tag**: validate
**Target**: Terminal

Verify each URL is accessible and determine the site structure:

```bash
# Test each URL
for url in \
  "https://earthsystemmodeling.org/docs/release/latest/ESMF_usrdoc/" \
  "https://earthsystemmodeling.org/docs/release/latest/NUOPC_refdoc/" \
  "https://escomp.github.io/CMEPS/" \
  "https://mom6.readthedocs.io/en/latest/" \
  "https://cice-consortium-cice.readthedocs.io/en/latest/" \
  "https://github.com/NOAA-EMC/WW3/wiki" \
  "https://ccpp-techdoc.readthedocs.io/en/latest/" \
  "https://upp.readthedocs.io/en/latest/" \
  "https://metplus.readthedocs.io/en/latest/" \
  "https://noaa-gfdl.github.io/FV3/" \
  "https://geos-chem.readthedocs.io/en/latest/"; do
  status=$(curl -sL -o /dev/null -w "%{http_code}" "$url")
  echo "$status $url"
done
```

**Acceptance**: All 11 URLs return HTTP 200. Any 404s are investigated and alternate URLs found.

---

### Step 41-2: Add ESMF and NUOPC to Tier 1
**Tag**: implement
**Target**: `mcp_server_node/scripts/documentation_sources_config.py`

Add to `tier1_critical`:

```python
{
    'name': 'esmf-user-guide',
    'url': 'https://earthsystemmodeling.org/docs/release/latest/ESMF_usrdoc/',
    'type': 'readthedocs',  # Sphinx-generated HTML
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
},
```

**Acceptance**: `from documentation_sources_config import get_all_sources; len(get_all_sources())` increases by 2.

---

### Step 41-3: Add Model Component Docs to Tier 3
**Tag**: implement
**Target**: `mcp_server_node/scripts/documentation_sources_config.py`

Add to `tier3_models`:

```python
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
    'url': 'https://mom6.readthedocs.io/en/latest/',
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
    'url': 'https://noaa-gfdl.github.io/FV3/',
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
},
```

**Acceptance**: `tier3_models` has 6 new entries.

---

### Step 41-4: Add Framework and Verification Docs
**Tag**: implement
**Target**: `mcp_server_node/scripts/documentation_sources_config.py`

Add CCPP to `tier4_build`:

```python
{
    'name': 'ccpp-techdoc',
    'url': 'https://ccpp-techdoc.readthedocs.io/en/latest/',
    'type': 'readthedocs',
    'priority': 3,
    'description': 'CCPP Common Community Physics Package - physics parameterization framework',
    'max_pages': 100,
    'enabled': True
},
```

Add UPP and METplus to `tier5_standards` (or create a new `tier6_verification` if preferred):

```python
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
},
```

**Acceptance**: Total enabled sources = ~35 (was 24).

---

### Step 41-5: Validate Config Syntax
**Tag**: validate
**Target**: Terminal

```bash
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node
python -c "
from scripts.documentation_sources_config import DOCUMENTATION_SOURCES, get_all_sources, VERSION
sources = get_all_sources()
print(f'Version: {VERSION}')
print(f'Total sources: {len(sources)}')
for s in sources:
    print(f'  [{\"ON\" if s.get(\"enabled\", True) else \"OFF\"}] {s[\"name\"]}: {s[\"url\"][:60]}')
"
```

**Acceptance**: Script runs without error. 35 sources listed. All 11 new sources show `[ON]`.

---

### Step 41-6: Update SPOT Version
**Tag**: implement
**Target**: `mcp_server_node/scripts/documentation_sources_config.py`

Bump version:
```python
VERSION = "8.0.0"  # was 7.0.0
```

Update the `DEFAULT_COLLECTION_NAME`:
```python
DEFAULT_COLLECTION_NAME = "global-workflow-docs-v8-0-0"
```

**Acceptance**: Version = 8.0.0 in config.

---

### Step 41-7: Crawl Tier 1 Critical Sources (ESMF + NUOPC)
**Tag**: execute
**Target**: Terminal

Run the documentation ingestion for the highest-priority sources first:

```bash
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node
python scripts/ingest_documentation_v8.py --sources esmf-user-guide,nuopc-layer-reference \
    2>&1 | tee logs/phase41_esmf_nuopc_ingest.log
```

**Acceptance**: ESMF + NUOPC ingested. `list_ingested_urls` shows new ESMF/NUOPC entries. ~1,200 new chunks.

---

### Step 41-8: Crawl Tier 3 Model Docs (MOM6, CICE, CMEPS, WW3, FV3, GOCART)
**Tag**: execute
**Target**: Terminal

```bash
python scripts/ingest_documentation_v8.py \
    --sources cmeps,mom6,cice,ww3-wiki,fv3-docs,gocart \
    2>&1 | tee logs/phase41_model_docs_ingest.log
```

**Acceptance**: ~1,500-2,500 new chunks across 6 sources.

---

### Step 41-9: Crawl Framework and Verification Docs (CCPP, UPP, METplus)
**Tag**: execute
**Target**: Terminal

```bash
python scripts/ingest_documentation_v8.py \
    --sources ccpp-techdoc,upp,metplus \
    2>&1 | tee logs/phase41_framework_docs_ingest.log
```

**Acceptance**: ~1,000-1,500 new chunks across 3 sources.

---

### Step 41-10: Validate with MCP Tools
**Tag**: validate
**Target**: EIB MCP tools

Test that new documentation is searchable:

```
search_documentation({ query: "ESMF field bundle creation" })
search_documentation({ query: "NUOPC cap initialization phases" })
search_documentation({ query: "MOM6 ocean model configuration" })
search_documentation({ query: "CMEPS mediator data exchange" })
search_documentation({ query: "METplus verification configuration" })
explain_with_context({ topic: "ESMF component coupling" })
```

**Acceptance**: All 6 queries return relevant results from newly ingested sources.

---

### Step 41-11: Update Knowledge Base Status and Gap Analysis
**Tag**: document
**Target**: `docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md`

Update §6 (Documentation Coverage) with new source counts. Update §8 scorecard: "External libs" from F to B, "UFS Coupling" docs from 0% to ~70%.

**Acceptance**: Report reflects Phase 41 completions.

---

## 5. Validation Criteria

| Criterion | Before | After | Method |
|-----------|--------|-------|--------|
| Enabled documentation sources | 24 | ~35 | `get_all_sources()` count |
| Total doc chunks | 5,409 | ~9,000-11,000 | `get_knowledge_base_status` |
| ESMF documentation chunks | 0 | ~800 | `search_documentation` with ESMF query |
| NUOPC documentation chunks | 0 | ~400 | `search_documentation` with NUOPC query |
| Model component doc coverage | ~10% | ~60% | Manual assessment |
| `documentation_sources_config.py` version | 7.0.0 | 8.0.0 | In-file version |

## 6. Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|-----------|
| ESMF docs use non-standard HTML | Crawler fails to extract text | Test crawl with `--max-pages 5` first. Adjust selectors. |
| GitHub wiki requires authentication | WW3 wiki inaccessible | Public wikis typically don't need auth. Fall back to repo README. |
| ReadTheDocs rate limiting | Crawl incomplete | Use crawl delay (1-2s between requests). Existing scripts already do this. |
| METplus site very large (200+ pages) | Slow crawl | Set `max_pages: 250`. Prioritize User's Guide over API docs. |
| URL changes / moved content | 404 errors | Validate URLs in Step 41-1 before committing to config. |

## 7. Cross-References

- **Gap Analysis**: `docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md` §5 (External Libraries), §6 (Documentation Coverage), §7-D
- **SPOT Config**: `mcp_server_node/scripts/documentation_sources_config.py` (the only file modified)
- **Related**: Phase 34 (NCEPLIBS GraphRAG integration — added NCEPLIBS docs)
- **Downstream**: Phase 39 (UFS Fortran graph) produces nodes with ESMF API calls that need these docs for context
- **Downstream**: `explain_with_context` and `search_documentation` will immediately benefit
