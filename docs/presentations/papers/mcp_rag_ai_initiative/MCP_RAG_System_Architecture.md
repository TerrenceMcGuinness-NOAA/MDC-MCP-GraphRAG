# MCP/RAG System Architecture for AI-Assisted Weather Forecasting Operations

**NOAA Environmental Modeling Center — EIB AI Software Development Initiative**

**Version:** 2.0.0  
**Date:** January 6, 2026  
**Status:** SPOT (Single Point of Truth)  
**Classification:** Technical Reference Document

---

## Executive Summary

This document serves as the authoritative technical reference for the **Model Context Protocol (MCP) with Retrieval-Augmented Generation (RAG)** system developed by the Environmental Information Branch (EIB) to support NOAA's flagship Global Forecast System (GFS). The system provides AI-assisted code analysis, compliance validation, and operational guidance for the Global Workflow—a complex multi-repository codebase spanning Fortran, Python, Bash, and C that produces operational weather forecasts for the National Weather Service.

**Key Capabilities:**
- 38 MCP tools for code analysis, semantic search, and compliance checking
- Hybrid retrieval combining vector similarity (ChromaDB) and graph relationships (Neo4j)
- EE2 (EMC Environment 2.0) compliance validation against NCO production standards
- Multi-platform HPC operational guidance (Hera, WCOSS2, Orion, Hercules, Gaea)
- COTS LLM independence—works with Claude, GPT-4, Gemini, and local models

---

## Table of Contents

1. [Mission and Scope](#1-mission-and-scope)
2. [System Architecture](#2-system-architecture)
3. [Knowledge Base Design](#3-knowledge-base-design)
4. [Hybrid Retrieval Algorithm](#4-hybrid-retrieval-algorithm)
5. [Semantic Annotation System](#5-semantic-annotation-system)
6. [MCP Tool Inventory](#6-mcp-tool-inventory)
7. [Configuration Reference](#7-configuration-reference)
8. [Deployment Procedures](#8-deployment-procedures)
9. [Performance Specifications](#9-performance-specifications)
10. [Troubleshooting Guide](#10-troubleshooting-guide)
11. [Reproducibility Checklist](#11-reproducibility-checklist)

---

## 1. Mission and Scope

### 1.1 Problem Statement

The Global Workflow represents one of NOAA's most complex software systems:
- **2,744+ files** across multiple repositories (global-workflow, GSI, UFS, etc.)
- **1,540+ functions** with **86,189 call relationships**
- **5 HPC platforms** with distinct configurations
- **Strict NCO production standards** (EE2) for operational deployment

Traditional documentation and manual code review cannot scale to support:
- New developer onboarding
- Cross-platform troubleshooting
- Compliance validation before NCO submission
- Understanding legacy code patterns

### 1.2 Solution: AI-Assisted Operations

The MCP/RAG system provides AI assistants (VS Code Copilot, Claude Desktop, n8n) with:

| Capability | Implementation | Benefit |
|------------|----------------|---------|
| **Code Understanding** | Neo4j call graphs + semantic search | "What functions call `err_chk`?" |
| **Compliance Checking** | EE2 standards in ChromaDB + SME annotations | "Is this script EE2 compliant?" |
| **Operational Guidance** | Platform-specific docs + runbooks | "How do I run GFS on Hera?" |
| **Dependency Analysis** | Graph traversal + file relationships | "What depends on this module?" |

### 1.3 Design Principles

1. **COTS LLM Independence**: No vendor lock-in; works with any MCP-compatible client
2. **SPOT (Single Point of Truth)**: One authoritative source per configuration domain
3. **MCP-First Policy**: AI uses MCP tools before falling back to shell commands
4. **Offline Capable**: Full functionality without internet after initial setup

---

## 2. System Architecture

### 2.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        AI Client Layer                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
│  │ VS Code     │  │ Claude      │  │ n8n         │  │ Local LLM   │ │
│  │ Copilot     │  │ Desktop     │  │ (HTTP/SSE)  │  │ (Ollama)    │ │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘ │
└─────────┼────────────────┼────────────────┼────────────────┼────────┘
          │                │                │                │
          │         Model Context Protocol (stdio/SSE)       │
          │                │                │                │
┌─────────▼────────────────▼────────────────▼────────────────▼────────┐
│                      MCP Server Layer                                │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │              UnifiedMCPServer.js (v3.6.2)                      │ │
│  │                     38 Tools Registered                        │ │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │ │
│  │  │Workflow  │ │Code      │ │Semantic  │ │EE2       │          │ │
│  │  │Info      │ │Analysis  │ │Search    │ │Compliance│ ...      │ │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘          │ │
│  └────────────────────────────────────────────────────────────────┘ │
└─────────────────────────┬───────────────────┬───────────────────────┘
                          │                   │
┌─────────────────────────▼───────────────────▼───────────────────────┐
│                     Knowledge Base Layer                             │
│  ┌─────────────────────────┐    ┌─────────────────────────────────┐ │
│  │      ChromaDB           │    │           Neo4j                 │ │
│  │   (Vector Store)        │    │      (Graph Database)           │ │
│  │                         │    │                                 │ │
│  │ • 14,968 documents      │    │ • 2,744 File nodes              │ │
│  │ • 12 collections        │    │ • 1,540 Function nodes          │ │
│  │ • 768-dim embeddings    │    │ • 86,189 relationships          │ │
│  │ • all-mpnet-base-v2     │    │ • CALLS, IMPORTS, DEFINES       │ │
│  └─────────────────────────┘    └─────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────────────┐
│                     Source Code Layer                                │
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │                   supported_repos/ (Git Submodules)             ││
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐            ││
│  │  │global-       │ │nws-hpc-      │ │GSI, UFS,     │            ││
│  │  │workflow      │ │standards     │ │UPP, etc.     │            ││
│  │  │(GFS/GEFS)    │ │(EE2 docs)    │ │(submodules)  │            ││
│  │  └──────────────┘ └──────────────┘ └──────────────┘            ││
│  └─────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 Component Inventory

**Core Infrastructure:**

| Component | Technology | Version | Port | Purpose |
|-----------|-----------|---------|------|---------|
| MCP Server | Node.js | v3.6.2 | stdio | Tool orchestration |
| Vector DB | ChromaDB | 0.5.x | 8080 | Semantic similarity search |
| Graph DB | Neo4j | 5.13.0 | 7474/7687 | Code structure relationships |
| Embedding Model | all-mpnet-base-v2 | Latest | — | 768-dim text embeddings |
| Gateway | Docker MCP | 1.0.x | 8888 | SSE transport |
| Workflow | n8n | 2.1.x | 5678 | Automation orchestration |

> **Technology Change (December 2025):** LangFlow v1.6.9 was replaced with n8n due to critical bugs in LangFlow's MCP client (dict race condition, asyncio scoping errors). n8n provides stable workflow automation with JSON-importable workflow definitions.

**Tool Modules (9 files, 38 tools):**

| Module | Tool Count | DB Dependency |
|--------|------------|---------------|
| WorkflowInfoTools | 4 | Filesystem only |
| CodeAnalysisTools | 5 | Neo4j |
| SemanticSearchTools | 4 | ChromaDB + Neo4j |
| EE2ComplianceTools | 4 | ChromaDB |
| OperationalTools | 3 | ChromaDB |
| SDDWorkflowTools | 4 | Filesystem |
| GitHubTools | 2 | GitHub API |
| SystemHealthTools | 2 | All |

### 2.3 Data Flow

```
┌─────────────────┐
│ Code Repository │ (Git submodules: global-workflow, nws-hpc-standards)
└────────┬────────┘
         │
         ├──> [Tree-sitter Parser]
         │         │
         │         ├──> AST extraction (functions, classes, imports)
         │         └──> Metadata extraction (LOC, language, module)
         │
         ├──> [Neo4j Ingestion]
         │         │
         │         └──> Graph relationships (CALLS, IMPORTS, DEFINES)
         │
         └──> [ChromaDB Ingestion]
                   │
                   ├──> Sentence Transformers (768-dim embeddings)
                   ├──> Graph metadata enrichment
                   └──> Semantic annotation extraction (MCP directives)

┌──────────────┐
│ User Query   │
└──────┬───────┘
       │
       ├──> [Query Type Detection] → Adjust weights (α, β, γ)
       │
       ├──> [ChromaDB Search] → Top 50 semantic results
       │
       ├──> [Neo4j Traversal] → Graph context for entities
       │
       ├──> [Result Merging] → Hybrid scoring function
       │
       └──> [Top-k Selection] → Return ranked results (k=10)
```

---

## 3. Knowledge Base Design

### 3.1 ChromaDB Collections

| Collection | Documents | Purpose |
|------------|-----------|---------|
| `global-workflow-docs-v6` | 5,307 | GFS/GEFS documentation |
| `ee2-standards-v2` | 1,245 | EE2 compliance standards |
| `operational-guidance` | 892 | HPC runbooks and procedures |
| `code-snippets` | 3,124 | Indexed code with context |
| `sme-annotations` | 568 | SME corrections and guidance |
| *Others* | 3,832 | GitHub issues, PRs, etc. |
| **Total** | **14,968** | |

### 3.2 Neo4j Graph Schema

**Node Types:**

```cypher
(:File {path, name, language, loc, module})
(:Function {name, signature, file_path, start_line, end_line})
(:Class {name, file_path, methods})
(:Module {name, type})
```

**Relationship Types:**

```cypher
(:Function)-[:CALLS]->(:Function)
(:File)-[:IMPORTS]->(:Module)
(:Function)-[:DEFINED_IN]->(:File)
(:Class)-[:HAS_METHOD]->(:Function)
(:File)-[:DEPENDS_ON]->(:File)
```

**Statistics:**
- 2,744 File nodes
- 1,540 Function nodes
- 86,189 relationships
- Average 31.4 relationships per file

### 3.3 Storage Requirements

```
/mcp_rag_eib/eib-mcp-rag-server/
├── mcp_server_node/
│   ├── chromadb_data/      # 2.3 GB (embeddings)
│   ├── knowledge-base/     # 850 MB (cached docs)
│   └── logs/               # 120 MB
│
/mcp_rag_eib/data/
├── chromadb/               # 2.5 GB (persistent)
└── neo4j/                  # 1.8 GB (graph + indexes)

Total: ~9.2 GB
```

---

## 4. Hybrid Retrieval Algorithm

### 4.1 Scoring Function

The hybrid score combines three components:

```
hybrid_score = α × vector_score + β × graph_score + γ × annotation_score
```

Where:
- **α (vector_score)**: Cosine similarity from ChromaDB embeddings
- **β (graph_score)**: Structural relevance from Neo4j traversal
- **γ (annotation_score)**: Semantic annotation intent matching

### 4.2 Query Type Detection

```python
def detect_query_type(query: str) -> str:
    """
    Automatically detect query type to adjust retrieval weights.
    Returns: 'concept' | 'usage' | 'structure' | 'compliance' | 'troubleshoot'
    """
    query_lower = query.lower()
    
    # Concept queries: "What is X?"
    if any(kw in query_lower for kw in ['what is', 'explain', 'describe']):
        return 'concept'
    
    # Structure queries: "What calls X?"
    if any(kw in query_lower for kw in ['calls', 'imports', 'depends on']):
        return 'structure'
    
    # Compliance queries: "Is this EE2 compliant?"
    if any(kw in query_lower for kw in ['compliant', 'ee2', 'standard']):
        return 'compliance'
    
    # Troubleshooting: "Why does X fail?"
    if any(kw in query_lower for kw in ['error', 'fail', 'broken']):
        return 'troubleshoot'
    
    return 'usage'  # Default
```

### 4.3 Weight Matrix

| Query Type | α (vector) | β (graph) | γ (annotation) |
|------------|------------|-----------|----------------|
| concept | 0.7 | 0.1 | 0.2 |
| usage | 0.5 | 0.3 | 0.2 |
| structure | 0.2 | 0.7 | 0.1 |
| compliance | 0.3 | 0.2 | 0.5 |
| troubleshoot | 0.4 | 0.4 | 0.2 |

### 4.4 Graph Relevance Scoring

```python
def compute_graph_relevance(result: dict, graph_results: list) -> float:
    """PageRank-inspired structural scoring."""
    score = 0.0
    
    # Appearances in graph traversal results
    appearances = sum(1 for gr in graph_results if result['id'] in gr.get('related', []))
    score += min(appearances / 10.0, 1.0) * 0.4
    
    # Hub score (many outgoing relationships)
    relationship_count = len(result.get('calls_functions', []))
    score += min(relationship_count / 20.0, 1.0) * 0.3
    
    # Authority score (frequently called)
    caller_count = len(result.get('called_by_files', []))
    score += min(caller_count / 10.0, 1.0) * 0.3
    
    return score
```

---

## 5. Semantic Annotation System

### 5.1 Overview

The semantic annotation system embeds machine-readable directives in RST documentation that:
- Guide AI compliance analysis
- Prevent false positives via SME corrections
- Provide platform-specific operational guidance
- Are invisible to human readers (RST comments)

### 5.2 Directive Types

| Directive | Purpose | Example |
|-----------|---------|---------|
| `mcp:compliance::` | Mark EE2 requirements | `mcp:compliance:: environment_variables` |
| `mcp:intent::` | Describe enforcement rationale | `mcp:intent:: environment_validation` |
| `mcp:severity::` | RFC 2119 levels | `mcp:severity:: must` |
| `mcp:utility::` | Document prod utilities | `mcp:utility:: err_chk` |
| `mcp:sme_correction::` | Correct AI false positives | `mcp:sme_correction:: bash_error_handling` |
| `mcp:guidance::` | Platform-specific guidance | `mcp:guidance:: hera_environment` |
| `mcp:anti_pattern::` | Mark incorrect patterns | `mcp:anti_pattern:: bare_exit` |

### 5.3 Example: EE2 Standards Annotation

```rst
.. mcp:compliance:: environment_variables
   :priority: critical
   :type: mandatory
   :category: environment_variables
   :platforms: hera,hercules,orion,wcoss2,gaea

.. mcp:intent:: environment_validation
   :description: All production scripts must validate required environment variables
   :enforcement: runtime_check
   :rationale: Missing environment variables cause silent failures

.. mcp:sme_guidance:: required_variable_validation
   :severity: must
   :description: Scripts must exit with non-zero status if required variables undefined
   :critical_variables: COMROOT, DATAROOT, cyc, PDY, NET, RUN
   :validation_pattern: Check with ${VAR:?} or explicit test before proceeding
```

### 5.4 SME Corrections (Critical Feature)

SME corrections address systematic AI false positives:

```rst
.. mcp:sme_correction:: bash_error_handling_requirement
   :date: 2025-11-19
   :severity: critical
   :false_positive_rate: ~80%

**AI-Generated Recommendation (INCORRECT)**:
   ❌ "Missing set -eu in scripts"

**SME Correction**:
   - ❌ set -eu is NOT in EE2 standards
   - ✅ set -e is NOT required in operational scripts
   - ✅ Only set -x is shown in EE2 examples for debug logging
```

### 5.5 JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "MCP Directive Schema",
  "description": "JSON schema for semantic annotations in RST documentation",
  "definitions": {
    "compliance": {
      "type": "object",
      "properties": {
        "directive": {"const": "mcp:compliance"},
        "category": {"type": "string"},
        "priority": {"enum": ["critical", "high", "medium", "low"]},
        "type": {"enum": ["mandatory", "recommended", "optional"]},
        "scope": {"enum": ["global", "system-specific", "component-specific"]}
      },
      "required": ["directive", "category", "priority", "type", "scope"]
    },
    "intent": {
      "type": "object",
      "properties": {
        "directive": {"const": "mcp:intent"},
        "identifier": {"type": "string"},
        "description": {"type": "string"},
        "enforcement": {"enum": ["runtime_check", "compile_check", "manual_review"]},
        "rationale": {"type": "string"}
      },
      "required": ["directive", "identifier", "description", "enforcement", "rationale"]
    },
    "severity": {
      "type": "object",
      "properties": {
        "directive": {"const": "mcp:severity"},
        "level": {"enum": ["must", "must-not", "should", "should-not", "may"]},
        "rationale": {"type": "string"},
        "exceptions": {"type": "string"}
      },
      "required": ["directive", "level", "rationale"]
    },
    "sme_correction": {
      "type": "object",
      "properties": {
        "directive": {"const": "mcp:sme_correction"},
        "identifier": {"type": "string"},
        "date": {"type": "string"},
        "severity": {"enum": ["critical", "high", "medium", "low"]},
        "false_positive_rate": {"type": "string"},
        "ai_recommendation": {"type": "string"},
        "sme_correction": {"type": "string"}
      },
      "required": ["directive", "identifier", "severity"]
    }
  }
}
```

---

## 6. MCP Tool Inventory

### 6.1 Complete Tool List (38 Tools)

**Workflow Information (4 tools)**

| Tool | Description | DB |
|------|-------------|-----|
| `get_workflow_structure` | Overview of global workflow system | — |
| `describe_component` | Basic description of a component | — |
| `get_system_configs` | HPC platform configurations | — |
| `list_job_scripts` | List and categorize job scripts | — |

**Code Analysis (5 tools)**

| Tool | Description | DB |
|------|-------------|-----|
| `analyze_code_structure` | File structure and dependencies | Neo4j |
| `analyze_workflow_dependencies` | Upstream/downstream analysis | Neo4j |
| `find_callers_callees` | Function call relationships | Neo4j |
| `trace_execution_path` | Execution path tracing | Neo4j |
| `find_related_files` | File relationship discovery | Neo4j |

**Semantic Search (4 tools)**

| Tool | Description | DB |
|------|-------------|-----|
| `search_documentation` | Hybrid semantic + graph search | Both |
| `explain_with_context` | Comprehensive explanations | Both |
| `get_knowledge_base_status` | KB statistics | Both |
| `get_ingested_urls_array` | List ingested documentation | — |

**EE2 Compliance (4 tools)**

| Tool | Description | DB |
|------|-------------|-----|
| `analyze_ee2_compliance` | Code/doc compliance analysis | ChromaDB |
| `scan_repository_compliance` | Full repo scan | ChromaDB |
| `generate_compliance_report` | Comprehensive reports | ChromaDB |
| `validate_sdd_compliance` | SDD framework validation | ChromaDB |

**Operational (3 tools)**

| Tool | Description | DB |
|------|-------------|-----|
| `get_operational_guidance` | HPC operational procedures | ChromaDB |
| `explain_workflow_component` | Detailed component explanation | ChromaDB |
| `list_ingested_urls` | Documentation source listing | — |

**SDD Workflow (4 tools)**

| Tool | Description | DB |
|------|-------------|-----|
| `list_sdd_workflows` | List available workflows | — |
| `get_sdd_workflow` | Workflow details | — |
| `execute_sdd_workflow` | Execute workflow | — |
| `execute_sdd_workflow_supervised` | Supervised execution | — |

**GitHub Integration (2 tools)**

| Tool | Description | DB |
|------|-------------|-----|
| `search_issues` | Search GitHub issues | API |
| `get_pull_requests` | PR information | API |

**System Health (2 tools)**

| Tool | Description | DB |
|------|-------------|-----|
| `mcp_health_check` | System health status | All |
| `get_server_info` | Server information | — |

### 6.2 Tool Selection Guide

```
User Question
    │
    ├─► "Show me the code structure of X" 
    │       → analyze_code_structure (Neo4j)
    │
    ├─► "What does this error mean?" / "How do I run GFS?"
    │       → search_documentation (ChromaDB + Neo4j)
    │
    ├─► "Is this code EE2 compliant?"
    │       → analyze_ee2_compliance (ChromaDB)
    │
    ├─► "What calls this function?"
    │       → find_callers_callees (Neo4j)
    │
    ├─► "How do I run jobs on HERA?"
    │       → get_operational_guidance (ChromaDB)
    │
    └─► "What are the open GFS PRs?"
            → get_pull_requests (GitHub API)
```

---

## 7. Configuration Reference

### 7.1 Environment Variables

**File:** `mcp_server_node/mcp-config.env`

```bash
# MCP Server Configuration
MCP_SERVER_VERSION=3.6.2
MCP_SERVER_MODE=full  # Options: full, core, lite

# Database Connections
CHROMADB_HOST=localhost
CHROMADB_PORT=8080
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

# Knowledge Base Paths
MCP_WORKFLOW_ROOT=/mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow
KNOWLEDGE_BASE_PATH=/mcp_rag_eib/eib-mcp-rag-server/mcp_server_node/knowledge-base

# Performance Tuning
MAX_QUERY_RESULTS=50
SEMANTIC_THRESHOLD=0.1
GRAPH_TRAVERSAL_DEPTH=3

# Logging
LOG_LEVEL=info
LOG_PATH=/mcp_rag_eib/eib-mcp-rag-server/mcp_server_node/logs
```

### 7.2 VS Code MCP Configuration

**File:** `.vscode/mcp.json`

```json
{
  "servers": {
    "eib-mcp-rag-full": {
      "type": "stdio",
      "command": "node",
      "args": ["mcp_server_node/src/UnifiedMCPServer.js", "full"],
      "env": {
        "CHROMADB_HOST": "localhost",
        "NEO4J_URI": "bolt://localhost:7687"
      }
    }
  }
}
```

### 7.3 Docker Gateway Configuration

**File:** `~/.docker/mcp/catalogs/eib-local.yaml`

```yaml
version: 3
name: eib-local
registry:
  eib-mcp-rag:
    title: EIB MCP RAG Server
    type: server
    image: eib-mcp-rag:latest
    env:
      - name: CHROMADB_HOST
        value: "172.17.0.1"
      - name: NEO4J_URI
        value: bolt://172.17.0.1:7687
    volumes:
      - /mcp_rag_eib/eib-mcp-rag-server/supported_repos:/app/supported_repos:ro
      - /mcp_rag_eib/eib-mcp-rag-server/sdd_framework:/app/sdd_framework:ro
```

---

## 8. Deployment Procedures

### 8.1 Fresh Deployment

```bash
# Step 1: Clone repository
cd /mcp_rag_eib
git clone https://vlab.noaa.gov/gitlab-licensed/NWS/Operations/NCEP/EMC/EIB/eib-mcp-rag-server.git
cd eib-mcp-rag-server

# Step 2: Initialize Git submodules
git submodule update --init --recursive

# Step 3: Start infrastructure
docker compose -f docker-compose.devops.yaml up -d

# Step 4: Verify services
curl http://localhost:8080/api/v2/heartbeat  # ChromaDB
curl http://localhost:7474                    # Neo4j

# Step 5: Install Node.js dependencies
cd mcp_server_node && npm install

# Step 6: Ingest documentation (first time)
python3 scripts/ingest_ee2_v7.py
node scripts/build_code_graph.js

# Step 7: Start MCP server
node src/UnifiedMCPServer.js full
```

### 8.2 Docker Gateway Deployment

```bash
# Build MCP server container
docker compose -f docker-compose.mcp-standalone.yaml build

# Start gateway with SSE transport
SETUP/bin/start-mcp-gateway.sh --background

# Gateway outputs:
# > Gateway URL: http://localhost:8888/sse
# > Bearer token: <generated-token>

# Connect from n8n via HTTP Request node:
# URL: http://host.docker.internal:8888/sse
# Authorization: Bearer <token>
# n8n workflows can be imported via JSON files for reproducibility
```

### 8.3 Update Procedure

```bash
# Pull latest changes
git fetch origin && git pull

# Update submodules
git submodule update --remote

# Rebuild container (if using gateway)
docker compose -f docker-compose.mcp-standalone.yaml build

# Restart services
docker compose -f docker-compose.devops.yaml restart
```

---

## 9. Performance Specifications

### 9.1 Response Time Targets

| Query Type | Target | Typical |
|------------|--------|---------|
| Concept queries | <500ms | 350ms |
| Usage queries | <1000ms | 650ms |
| Structure queries | <1500ms | 1100ms |
| Compliance queries | <800ms | 550ms |
| Graph traversal | <2000ms | 1400ms |

### 9.2 Resource Requirements

**Minimum:**
- 4 CPU cores
- 8 GB RAM
- 20 GB storage

**Recommended (Production):**
- 8 CPU cores
- 16 GB RAM
- 100 GB storage

**Memory Breakdown:**

| Process | RSS | VSZ |
|---------|-----|-----|
| ChromaDB | 1.2 GB | 3.8 GB |
| Neo4j | 2.1 GB | 4.5 GB |
| Node.js (MCP) | 380 MB | 1.2 GB |
| **Total** | **~3.7 GB** | **~9.5 GB** |

### 9.3 Tuning Parameters

| Parameter | Default | Range | Impact |
|-----------|---------|-------|--------|
| `MAX_QUERY_RESULTS` | 50 | 30-100 | ↑ = slower, better recall |
| `SEMANTIC_THRESHOLD` | 0.1 | 0.05-0.3 | ↑ = fewer results, faster |
| `GRAPH_TRAVERSAL_DEPTH` | 3 | 2-4 | ↑ = exponentially slower |

---

## 10. Troubleshooting Guide

### 10.1 ChromaDB Connection Errors

**Symptom:** `Connection refused to http://localhost:8080`

```bash
# Check service status
docker ps | grep chromadb

# View logs
docker logs chromadb --tail 50

# Restart
docker compose -f docker-compose.devops.yaml restart chromadb
```

### 10.2 Neo4j Query Timeouts

**Symptom:** `Query exceeded 30000 ms limit`

```cypher
-- Add indexes
CREATE INDEX function_name_index FOR (f:Function) ON (f.name);
CREATE INDEX file_path_index FOR (f:File) ON (f.path);

-- Verify
SHOW INDEXES;
```

### 10.3 Empty Search Results

**Diagnostic:**

```javascript
// Check collection
const status = await mcp_health_check({ detailed: true });
console.log('Documents:', status.chromadb.document_count);
console.log('Collections:', status.chromadb.collections);
```

### 10.4 MCP Tool "Disabled by User"

This typically means the tool errored (VS Code quirk). Check MCP server logs:

```bash
tail -f mcp_server_node/logs/mcp-server.log
```

---

## 11. Reproducibility Checklist

### 11.1 Full System Reproduction

- [ ] **Hardware:** 8-core CPU, 16GB RAM, 100GB storage
- [ ] **OS:** Rocky Linux 8.6+ or Ubuntu 22.04+
- [ ] **Software:**
  - [ ] Git 2.30+
  - [ ] Docker 20.10+
  - [ ] Node.js 18.0+
  - [ ] Python 3.11+
- [ ] **Network:** Access to vlab.noaa.gov, Docker Hub, Hugging Face Hub

**Steps:**

1. Clone repository
2. Initialize submodules: `git submodule update --init --recursive`
3. Start infrastructure: `docker compose -f docker-compose.devops.yaml up -d`
4. Install dependencies: `cd mcp_server_node && npm install`
5. Ingest data: `python3 scripts/ingest_ee2_v7.py`
6. Build graph: `node scripts/build_code_graph.js`
7. Start MCP: `node src/UnifiedMCPServer.js full`
8. Test: `curl http://localhost:8080/api/v2/heartbeat`

**Expected deployment time:** 2-3 hours (including data ingestion)

### 11.2 Validation Tests

```bash
# Health check
npm run test:health

# Integration tests
npm run test:integration

# Compliance validation
node scripts/validate-ee2-search.js
```

---

## Appendix A: Related Documentation

| Document | Location | Purpose |
|----------|----------|---------|
| SDD Framework | `sdd_framework/` | Development workflow orchestration |
| Bootstrap Capability | `presentations/papers/sdd_framework/` | Autonomous code generation |
| Docker Gateway | `presentations/papers/docker_mcp_gateway/` | Container deployment |
| Copilot Instructions | `.github/copilot-instructions.md` | AI agent guidance |

---

## Appendix B: Glossary

| Term | Definition |
|------|------------|
| **EE2** | EMC Environment 2.0 — NCO production coding standards |
| **MCP** | Model Context Protocol — AI tool integration standard |
| **RAG** | Retrieval-Augmented Generation |
| **GFS** | Global Forecast System — NOAA's flagship weather model |
| **GEFS** | Global Ensemble Forecast System |
| **HPC** | High-Performance Computing platforms (Hera, WCOSS2, etc.) |
| **NCO** | NCEP Central Operations — production deployment authority |
| **SDD** | Spec-Driven Development — workflow orchestration methodology |
| **SPOT** | Single Point of Truth — authoritative configuration source |

---

**Document Control:**

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | Nov 19, 2025 | EIB Team | Initial appendix |
| 2.0 | Jan 6, 2026 | EIB Team | Elevated to SPOT; comprehensive rewrite |

**Contact:** Terry.McGuinness@noaa.gov

**Repository:** https://vlab.noaa.gov/gitlab-licensed/NWS/Operations/NCEP/EMC/EIB/eib-mcp-rag-server
