# Spack Unified Compiler Rebuild Workflow

**Version**: 1.0.0
**Date**: December 9, 2025
**Status**: TODO (Background Task)
**Priority**: Medium
**Estimated Effort**: 4-8 hours

## Problem Statement

The current spack installation has **gcc-runtime hash conflicts** between Python packages that prevent them from being loaded together. Specifically:

| Package | gcc-runtime Hash | Conflict |
|---------|------------------|----------|
| `py-pydantic` | `gcc-runtime/11.5.0-kfpu42e` | Required by chromadb |
| `py-lxml` | `gcc-runtime/11.5.0-qa4ruhy` | Required by BeautifulSoup HTML parsing |
| `py-beautifulsoup4` | `gcc-runtime/11.5.0-qa4ruhy` | Required for web scraping/ingestion |

When `py-lxml` is loaded, it causes Lmod to reload `gcc-runtime` with a different hash, which unloads `py-pydantic` and breaks `chromadb` imports.

### Current Workaround

As documented in `SETUP/mcp-env.sh`:
- `py-lxml` and `py-beautifulsoup4` are installed via `pip install` instead of spack modules
- Spack module loads for these packages are commented out with TODO notes
- This works but bypasses the spack-first policy

## Root Cause

The packages were built at different times or with different spack concretization settings, resulting in different `gcc-runtime` dependency hashes even though they use the same gcc version (11.5.0).

## Solution: Unified Spack Rebuild

Rebuild all Python packages in a single concretization pass to ensure consistent `gcc-runtime` hashes across the entire dependency tree.

## Phases

### Phase 1: Audit Current State
- [ ] List all py-* packages with their gcc-runtime hashes
- [ ] Identify all packages with conflicting hashes
- [ ] Document current package versions for rollback if needed

```bash
# Audit command
spack find -lv --deps py-pydantic py-lxml py-beautifulsoup4 | grep gcc-runtime
```

### Phase 2: Create Unified Spack Environment
- [ ] Create a new spack environment for MCP RAG
- [ ] Add all required Python packages to spack.yaml
- [ ] Use `unify: true` in concretization settings

```yaml
# spack.yaml
spack:
  specs:
    # Core Python
    - python@3.11
    - py-pip
    
    # Pydantic ecosystem (chromadb deps)
    - py-pydantic
    - py-pydantic-core
    - py-typing-extensions
    - py-annotated-types
    
    # Web scraping/parsing
    - py-lxml
    - py-beautifulsoup4
    - py-soupsieve
    
    # HTTP clients
    - py-requests
    - py-httpx
    - py-certifi
    - py-idna
    - py-anyio
    - py-sniffio
    
    # ML/Data science
    - py-numpy
    - py-scipy
    - py-pillow
    - py-tokenizers
    - py-tqdm
    - py-pyyaml
    
    # Database
    - py-neo4j
    
  concretizer:
    unify: true
    reuse: false
  
  compilers:
    - gcc@11.5.0
```

### Phase 3: Rebuild All Packages
- [ ] Activate the spack environment
- [ ] Run `spack concretize` to verify unified hashes
- [ ] Run `spack install` to rebuild all packages
- [ ] Verify all gcc-runtime hashes match

```bash
# Rebuild commands
cd /mcp_rag_eib/spack
spack env create mcp-rag-unified ./spack.yaml
spack env activate mcp-rag-unified
spack concretize -f
spack install
```

### Phase 4: Generate New Module Files
- [ ] Regenerate Lmod module files
- [ ] Test module loads without conflicts
- [ ] Verify all imports work together

```bash
spack module lmod refresh --delete-tree -y
```

### Phase 5: Update mcp-env.sh
- [ ] Remove pip workaround for lxml/beautifulsoup4
- [ ] Re-enable spack module loads
- [ ] Remove TODO comments about conflicts
- [ ] Test full environment

### Phase 6: Validation
- [ ] Run all MCP health checks
- [ ] Test documentation ingestion
- [ ] Test code ingestion
- [ ] Verify no module conflicts in `module list`

## Validation Criteria

```bash
# All these should work together without Lmod warnings:
source /mcp_rag_eib/eib-mcp-rag-server/SETUP/mcp-env.sh
module list 2>&1 | grep -c "Warning"  # Should be 0

python3 -c "
import pydantic
import lxml.etree
from bs4 import BeautifulSoup
import chromadb
print('All imports successful - no conflicts!')
"
```

## Rollback Plan

If rebuild fails or causes issues:
1. Keep current pip-installed lxml/beautifulsoup4
2. Revert mcp-env.sh changes
3. Document specific failure for future resolution

## Files to Update After Resolution

- [ ] `SETUP/mcp-env.sh` - Remove TODO comments, re-enable module loads
- [ ] `.github/copilot-instructions.md` - Update PIP-ONLY section
- [ ] `SETUP/provisioning/05-python-spack.sh` - Add unified environment setup

## References

- Spack documentation: https://spack.readthedocs.io/en/latest/environments.html
- Lmod hierarchical modules: https://lmod.readthedocs.io/en/latest/
- Current workaround: `SETUP/mcp-env.sh` lines 93-97
