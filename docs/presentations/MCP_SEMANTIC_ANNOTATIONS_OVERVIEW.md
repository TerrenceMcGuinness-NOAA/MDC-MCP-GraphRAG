# MCP Semantic Annotations for EE2 Compliance

**NOAA/EMC Environmental Information Branch (EIB)**  
**Version**: 2.0.0 | **Date**: December 18, 2025  
**Status**: Production (v7.0.0 Architecture)

---

## Executive Summary

The MCP Semantic Annotation system enables **AI-assisted code compliance checking** for NOAA's operational weather forecasting infrastructure. By embedding machine-readable directives directly into authoritative EE2 standards documentation, we achieve:

| Metric | Result |
|--------|--------|
| **False Positive Reduction** | 85% (328 → 48 violations) |
| **MCP Directives Parsed** | 63 directives |
| **EE2 Chunks Indexed** | 94 chunks |
| **ChromaDB Collections** | 12 collections, 14,856 documents |
| **Code Changes for Rule Updates** | Zero |

---

## What Are Semantic Annotations?

**Semantic annotations** are structured metadata embedded in documentation that AI systems can parse and reason about. Unlike traditional documentation (human-readable only), annotated documentation serves both humans and AI.

### Traditional vs. Annotated Documentation

**Traditional** (Human Only):
```rst
Enable debug logging at the top of each shell script:
    set -x
```

**Annotated** (Human + AI):
```rst
.. mcp:compliance:: script_debug_logging
   :priority: critical
   :category: error_handling

.. mcp:correct_pattern:: ee2_script_header
   :severity: must

Enable debug logging at the top of each shell script:
    set -x
```

The annotations are **invisible in rendered documentation** but parsed during ingestion to create semantically-rich embeddings.

---

## Architecture Overview

### Single Source of Truth (v7.0.0)

```
┌─────────────────────────────────────────────────────────────────┐
│                    AUTHORITATIVE SOURCE                         │
│  supported_repos/nws-hpc-standards/docs/standards.rst           │
│  ════════════════════════════════════════════════════           │
│  • EE2 compliance requirements (human-readable)                 │
│  • MCP directives inline (machine-readable)                     │
│  • 63 semantic annotations embedded                             │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼  ingest_ee2_v7.py
┌─────────────────────────────────────────────────────────────────┐
│                    KNOWLEDGE BASE                               │
│  ChromaDB: global-workflow-docs-v7-0-0                          │
│  ════════════════════════════════════                           │
│  • 94 EE2 document chunks                                       │
│  • Vector embeddings (sentence-transformers)                    │
│  • Directive metadata (searchable filters)                      │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼  generatePhase2Config.js (optional)
┌─────────────────────────────────────────────────────────────────┐
│                 RUNTIME CONFIGURATION                           │
│  mcp_server_node/phase2_anti_patterns.json                      │
│  ═════════════════════════════════════════                      │
│  • Anti-patterns extracted from embeddings                      │
│  • Correct patterns with evidence chains                        │
│  • AI guidance rules for query processing                       │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼  MCP Server loads at startup
┌─────────────────────────────────────────────────────────────────┐
│                  COMPLIANCE TOOLS                               │
│  EE2ComplianceTools.js (32 MCP tools available)                 │
│  ═══════════════════════════════════════════                    │
│  • scan_repository_compliance()                                 │
│  • analyze_ee2_compliance()                                     │
│  • extract_code_for_analysis()                                  │
│  • generate_compliance_report()                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## MCP Directive Types

### 9 Core Directive Types

| Directive | Purpose | Example Use |
|-----------|---------|-------------|
| `mcp:compliance` | Mark compliance category | Error handling, file naming |
| `mcp:intent` | Capture requirement purpose | Why `err_chk` is required |
| `mcp:correct_pattern` | Show approved patterns | Proper script headers |
| `mcp:anti_pattern` | Mark prohibited patterns | `exit 1` in operational scripts |
| `mcp:sme_correction` | Document AI false positives | `set -eu` not required |
| `mcp:ai_guidance_rule` | Control AI behavior | Literal compliance only |
| `mcp:context_types` | Define script contexts | J-job vs ush utility |
| `mcp:utility` | Reference production tools | err_chk, err_exit usage |
| `mcp:llm_validation_prompt` | AI validation instructions | File naming checks |

### Directive Syntax

```rst
.. mcp:<directive_type>:: <identifier>
   :attribute1: value1
   :attribute2: value2
   
   Content describing the directive...
```

---

## The Embedding Pipeline

### How Annotations Become Searchable Knowledge

```
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│   RST Source     │    │  Parsed Chunks   │    │ Vector Embedding │
│                  │───▶│                  │───▶│                  │
│ standards.rst    │    │ Text + Metadata  │    │ 384-dim vector   │
│ + MCP directives │    │ per directive    │    │ + metadata       │
└──────────────────┘    └──────────────────┘    └──────────────────┘
                                                         │
                                                         ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  Semantic Query  │    │  Vector Search   │    │   ChromaDB       │
│                  │◀───│                  │◀───│                  │
│ "error handling" │    │ cosine similarity│    │ Collection store │
│                  │    │ + metadata filter│    │                  │
└──────────────────┘    └──────────────────┘    └──────────────────┘
```

### Metadata Enrichment

Each chunk gets enriched metadata from directive parsing:

```json
{
  "text": "Jobs must fail with err_chk or err_exit...",
  "metadata": {
    "source": "standards.rst",
    "lines": "187-195",
    "directive_type": "mcp:intent",
    "compliance_category": "production_utilities",
    "priority": "critical",
    "severity": "must",
    "context": "operational_job",
    "ee2_section": "Section C: Production Utilities"
  }
}
```

---

## Key Achievements

### False Positive Elimination

| Issue | Before | After | Reduction |
|-------|--------|-------|-----------|
| "Missing set -eu" | 328 files flagged | 0 files | **100%** |
| "Add exit 1" | ~200 files | 0 files | **100%** |
| Total Error Handling FP | 328 | 48 | **85%** |

### SME Corrections Integrated

Three critical SME findings now embedded in `standards.rst`:

1. **`mcp:sme_correction::bash_error_handling_requirement`**
   - AI was recommending `set -eu` (general best practice)
   - EE2 only requires `set -x` (debug logging)

2. **`mcp:sme_correction::forced_exit_prohibition`**
   - AI was recommending `exit 1` statements
   - NCO SPAs prohibit explicit exits in operational scripts

3. **`mcp:sme_correction::ksh_shebang_allowance`**
   - AI was flagging `#!/bin/ksh` as non-compliant
   - EE2 allows both bash and ksh

---

## Update Workflow

### Adding New Compliance Rules (Zero Code Changes)

```bash
# 1. Edit authoritative source
cd supported_repos/nws-hpc-standards/docs
vim standards.rst  # Add mcp: directive inline

# 2. Re-ingest to ChromaDB
cd mcp_server_node
python3 scripts/ingest_ee2_v7.py
# Output: 5 files, 94 chunks, 63 MCP directives

# 3. Restart MCP server (VS Code auto-restarts)
# New rules now active!
```

**Time to deploy new rule**: ~5 minutes  
**Code changes required**: None

---

## EE2 Compliance Categories

| Category | Directives | Coverage |
|----------|------------|----------|
| Error Handling | 15 | err_chk, err_exit, set -x |
| Environment Variables | 12 | PATH, COMROOT, DATA |
| File Naming | 10 | J-jobs, ex-scripts, output files |
| Production Utilities | 8 | prep_step, postmsg, cpreq |
| Workflow Structure | 6 | ecFlow, Rocoto integration |
| Code Standards | 5 | Documentation blocks, formatting |
| Directory Structure | 4 | Vertical structure requirements |
| Logging | 3 | Debug output, timing info |

---

## Tools Available

### MCP Tool Suite (32 Tools)

**EE2 Compliance** (5 tools):
- `scan_repository_compliance` - Full repository scan
- `analyze_ee2_compliance` - Single file/content analysis
- `extract_code_for_analysis` - Pattern extraction with LLM prompts
- `generate_compliance_report` - Formatted reports
- `search_ee2_standards` - Semantic search

**Code Analysis** (4 tools):
- `find_callers_callees` - Function dependency mapping
- `trace_execution_path` - Call chain analysis
- `analyze_code_structure` - AST-based analysis
- `find_dependencies` - Import/include tracking

**Documentation** (3 tools):
- `search_documentation` - Semantic doc search
- `explain_with_context` - Contextual explanations
- `find_related_files` - Dependency-based file discovery

---

## Infrastructure

### Running Services

| Service | Port | Purpose |
|---------|------|---------|
| ChromaDB | 8080 | Vector database (v2 API) |
| Neo4j | 7474/7687 | Knowledge graph |
| MCP Server | stdio | Tool server (32 tools) |

### Collections (v7.0.0)

| Collection | Documents | Purpose |
|------------|-----------|---------|
| global-workflow-docs-v7-0-0 | 3,788 | Primary documentation + EE2 |
| code-with-context-v7-0-0 | 1,431 | Code with surrounding context |
| ee2-standards-v5-0-0-enhanced | 34 | Legacy EE2-specific |

---

## References

### Key Files

| File | Purpose |
|------|---------|
| `supported_repos/nws-hpc-standards/docs/standards.rst` | Authoritative EE2 standards with MCP annotations |
| `mcp_server_node/scripts/ingest_ee2_v7.py` | v7 ingestion with directive parsing |
| `mcp_server_node/src/tools/EE2ComplianceTools.js` | Compliance scanning tools |
| `mcp_server_node/phase2_anti_patterns.json` | Generated runtime configuration |

### Documentation

| Document | Location |
|----------|----------|
| Phase 2 Architecture Spec | `docs/technical_specification/papers/hybrid_annotations/` |
| Directive Reference | `sdd_framework/templates/mcp_rst_enhanced_directives_phase2.md` |
| SME Review Guide | `sdd_framework/templates/sme_review_guide.md` |

---

## Contact

**Terry McGuinness**  
NOAA/EMC/EIB  
terry.mcguinness@noaa.gov

---

*Document generated: December 18, 2025*
