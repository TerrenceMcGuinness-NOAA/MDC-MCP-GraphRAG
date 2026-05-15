# Spack Package Requirements

**Version**: 1.0.0  
**Last Updated**: 2026-02-05

## Required Spack Packages

These packages must be installed via Spack before the MCP RAG environment is fully functional.

### Compiler (Required First)

```bash
spack install gcc@11.5.0
spack module lmod refresh gcc
```

### Core Python Environment

```bash
spack install python@3.11
spack install py-pip
```

### MCP RAG Dependencies

| Package | Purpose | Install Command |
|---------|---------|-----------------|
| `py-neo4j` | Neo4j graph database driver | `spack install py-neo4j` |
| `py-pydantic` | Data validation (ChromaDB dep) | `spack install py-pydantic` |
| `py-fparser` | Fortran AST parser (Phase 10) | `spack install py-fparser` |
| `py-httpx` | HTTP client (ChromaDB dep) | `spack install py-httpx` |
| `py-requests` | HTTP client (legacy) | `spack install py-requests` |
| `py-certifi` | SSL certificates | `spack install py-certifi` |
| `py-idna` | Internationalized domains | `spack install py-idna` |
| `py-anyio` | Async I/O | `spack install py-anyio` |
| `py-sniffio` | Async library detection | `spack install py-sniffio` |
| `py-pillow` | Image processing | `spack install py-pillow` |
| `py-scipy` | Scientific computing | `spack install py-scipy` |
| `py-numpy` | Numerical arrays | `spack install py-numpy` |
| `py-tokenizers` | Text tokenization | `spack install py-tokenizers` |
| `py-tqdm` | Progress bars | `spack install py-tqdm` |
| `py-pyyaml` | YAML parsing | `spack install py-pyyaml` |

### Batch Installation

```bash
# Install all packages at once
spack install gcc@11.5.0
spack install python@3.11 py-pip py-neo4j py-pydantic py-fparser \
    py-httpx py-requests py-certifi py-idna py-anyio py-sniffio \
    py-pillow py-scipy py-numpy py-tokenizers py-tqdm py-pyyaml

# Regenerate Lmod modules
spack module lmod refresh --delete-tree -y
```

### Pip-Only Packages (NOT in Spack)

These must be installed separately via pip:

```bash
python3 -m pip install --user chromadb sentence-transformers lxml beautifulsoup4
```

| Package | Reason Not in Spack |
|---------|---------------------|
| `chromadb` | Vector DB client - not packaged |
| `sentence-transformers` | Complex torch dependency |
| `lxml` | gcc-runtime hash conflict with py-pydantic |
| `beautifulsoup4` | Depends on lxml |

## Ruby / Rocoto Dependencies

Rocoto (workflow manager in `supported_repos/rocoto`) requires Ruby and several gems.
System packages are installed by `02-system-deps.sh`; gems by `05-python-spack.sh`.

### System Packages (dnf)

| Package | Purpose |
|---------|---------|
| `ruby` | Ruby interpreter (3.0+) |
| `ruby-devel` | Headers for building native gem extensions |
| `sqlite-devel` | SQLite headers (already in dev libs) |
| `libxml2-devel` | libxml2 headers for libxml-ruby gem |

### Ruby Gems (gem install --user-install)

| Gem | Purpose |
|-----|---------|
| `sqlite3` | Rocoto workflow database |
| `libxml-ruby` | XML workflow parsing |
| `open4` | Process management (job submission) |
| `lockfile` | Workflow lock files |

### Verification

```bash
ruby -e "require 'sqlite3'; puts '[OK] sqlite3'"
ruby -e "require 'libxml'; puts '[OK] libxml-ruby'"
ruby -e "require 'open4'; puts '[OK] open4'"
ruby -e "require 'lockfile'; puts '[OK] lockfile'"

# Smoke test
cd supported_repos/rocoto && bash test/rocoto_full_smoke.sh
```

## Verification

After installation, verify with:

```bash
# Source environment
source /mcp_rag_eib/eib-mcp-rag-server/SETUP/mcp-env.sh

# Verify module loads
module list

# Verify imports
python3 -c "from fparser.two.parser import ParserFactory; print('[OK] fparser2')"
python3 -c "from neo4j import GraphDatabase; print('[OK] neo4j')"
python3 -c "import pydantic; print('[OK] pydantic')"
python3 -c "import chromadb; print('[OK] chromadb')"
```

## Module Load Order

The correct order for loading modules (handled by mcp-env.sh):

1. `gcc/11.5.0` - Exposes compiler-dependent py-* modules
2. `python/3.11 py-pip` - Core Python
3. `py-neo4j` - Graph database driver
4. `py-fparser` - Fortran parser (Phase 10)
5. `py-pydantic ...` - ChromaDB dependencies

## Notes

- **SPOT Principle**: mcp-env.sh is the single point of truth for module loads
- **bash_profile_template**: Sources mcp-env.sh for consistency
- **Phase 10**: py-fparser added for Fortran call graph ingestion (2026-02-05)
