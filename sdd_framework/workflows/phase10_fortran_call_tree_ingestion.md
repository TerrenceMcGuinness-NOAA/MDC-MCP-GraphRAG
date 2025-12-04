# Phase 10: Fortran Call Tree Ingestion Workflow

**SDD Version**: 1.0  
**Created**: December 4, 2025  
**Author**: Terrence McGuinness / Claude Opus 4.5  
**Status**: BACKLOG  
**Priority**: Future - After containerization and deployment

---

## Description

Extend the MCP/RAG knowledge base by ingesting **ground-truth structural relationships** extracted from Fortran compilation. This bridges the gap between shell script invocations (`$EXECseaice_analysis/seaice_blend`) and the actual Fortran call trees, module dependencies, and interface contracts.

**Goal**: Enable queries that trace execution from J-jobs through shell scripts into Fortran code, revealing the complete operational flow.

---

## Mathematical Foundation

Embeddings operate in a 768-dimensional feature space with cosine similarity (pseudo-metric). They capture **semantic similarity** but not **structural relationships**.

Graph databases (Neo4j) operate on explicit **relational structures** - nodes and edges with typed relationships. By ingesting compiler-generated call trees, we encode **ground truth** that embeddings can only approximate.

**Hybrid Query Power**:
```
Semantic: "error handling patterns" → ChromaDB → relevant docs
Structural: "what calls seaice_blend?" → Neo4j → exact call chain
Combined: "EE2 compliance for functions called by JSEAICE_ANALYSIS" → Graph traversal + Embedding match
```

---

## Prerequisites

- [ ] Neo4j operational (currently: ✅ running)
- [ ] Fortran source available in supported_repos/
- [ ] gfortran or Intel Fortran with dump capabilities
- [ ] Python script for parsing compiler output

---

## Phase 8 Steps

### Step 1: Identify Fortran Sources

**Objective**: Catalog all Fortran files in target repositories.

**Actions**:
```bash
# Find all Fortran sources in seaice-concentration
find supported_repos/ -name "*.f" -o -name "*.f90" -o -name "*.F" -o -name "*.F90" | tee fortran_sources.txt

# Categorize by repository
wc -l fortran_sources.txt
```

**Expected Output**: List of Fortran files with paths.

**Validation**: File list exists and contains .f/.f90 files.

---

### Step 2: Extract Call Trees via Compilation

**Objective**: Generate call graph data from Fortran compiler.

**Actions**:
```bash
# For gfortran - generates .original dump files with call info
gfortran -fdump-tree-original -c source.f90

# For Intel Fortran - generates call graph
ifort -opt-report=5 -c source.f90

# Alternative: Use fparser (Python) for AST extraction
pip install fparser
```

**Tool Selection**:
| Compiler | Flag | Output |
|----------|------|--------|
| gfortran | `-fdump-tree-original` | AST with call sites |
| gfortran | `-fdump-ipa-cgraph` | Call graph specifically |
| ifort | `-opt-report` | Optimization report with calls |
| fparser | Python API | Full AST as Python objects |

**Recommended**: Use `fparser` for portability - doesn't require compilation, just parsing.

**Validation**: Dump files or parsed AST available for each source.

---

### Step 3: Create Parser Script

**Objective**: Python script to extract nodes and relationships from Fortran.

**File**: `mcp_server_node/scripts/parse_fortran_structure.py`

**Entities to Extract**:

| Entity Type | Neo4j Label | Properties |
|-------------|-------------|------------|
| Subroutine | `:Subroutine` | name, file, line_start, line_end |
| Function | `:Function` | name, file, return_type, line_start |
| Module | `:Module` | name, file |
| Program | `:Program` | name, file |

**Relationships to Extract**:

| Relationship | Pattern | Example |
|--------------|---------|---------|
| CALLS | `(a:Subroutine)-[:CALLS]->(b:Subroutine)` | seaice_blend CALLS init_grid |
| USES | `(a:Subroutine)-[:USES]->(m:Module)` | seaice_blend USES netcdf |
| CONTAINS | `(m:Module)-[:CONTAINS]->(f:Function)` | ice_module CONTAINS calc_conc |
| INVOKED_BY | `(s:ShellScript)-[:INVOKES]->(p:Program)` | exseaice_analysis.sh INVOKES seaice_blend |

**Script Structure**:
```python
#!/usr/bin/env python3
"""
Parse Fortran sources and extract structural relationships for Neo4j.
"""

from fparser.two.parser import ParserFactory
from fparser.two import Fortran2003
import json

def parse_fortran_file(filepath):
    """Parse a single Fortran file and extract structure."""
    parser = ParserFactory().create(std="f2008")
    with open(filepath, 'r') as f:
        tree = parser(f.read())
    
    nodes = []
    relationships = []
    
    # Walk AST and extract...
    # ... subroutines, functions, modules
    # ... CALL statements → CALLS relationships
    # ... USE statements → USES relationships
    
    return nodes, relationships

def export_to_neo4j_cypher(nodes, relationships):
    """Generate Cypher statements for Neo4j ingestion."""
    ...
```

**Validation**: Script runs on sample file, outputs valid Cypher.

---

### Step 4: Link Shell Scripts to Fortran Executables

**Objective**: Connect `$EXECseaice_analysis/program_name` references to Fortran programs.

**Pattern Recognition**:
```bash
# In shell scripts, find executable references
grep -rh '\$EXEC.*/' scripts/ | grep -oE '[a-z_]+$' | sort -u
```

**Mapping Logic**:
```
Shell: $EXECseaice_analysis/seaice_blend
  ↓ (name extraction)
Executable: seaice_blend
  ↓ (match to PROGRAM statement)
Fortran: sorc/seaice_blend.f90 → PROGRAM seaice_blend
```

**Relationship**:
```cypher
MATCH (s:ShellScript {name: "exseaice_analysis.sh"})
MATCH (p:Program {name: "seaice_blend"})
MERGE (s)-[:INVOKES {line: 425}]->(p)
```

**Validation**: Shell-to-Fortran links exist in graph.

---

### Step 5: Ingest to Neo4j

**Objective**: Load extracted structure into Neo4j graph.

**File**: `mcp_server_node/scripts/ingest_fortran_to_neo4j.py`

**Cypher Patterns**:
```cypher
// Create Fortran nodes
MERGE (f:Function:Fortran {name: $name, file: $file})
SET f.line_start = $line_start, f.line_end = $line_end

// Create CALLS relationships
MATCH (caller:Function {name: $caller_name})
MATCH (callee:Function {name: $callee_name})
MERGE (caller)-[:CALLS {line: $call_line}]->(callee)

// Link to shell scripts
MATCH (s:ShellScript)-[:INVOKES]->(p:Program {name: $prog_name})
MATCH (p)-[:CALLS*1..5]->(f:Function)
// Now we can traverse from shell to any Fortran function
```

**Validation**: 
```cypher
// Verify nodes created
MATCH (n:Fortran) RETURN count(n)

// Verify call chains work
MATCH path = (s:ShellScript)-[:INVOKES]->(:Program)-[:CALLS*1..3]->(:Function)
RETURN path LIMIT 5
```

---

### Step 6: Create MCP Query Tools

**Objective**: Expose Fortran call tree queries via MCP tools.

**New Tools**:

| Tool Name | Purpose |
|-----------|---------|
| `trace_fortran_calls` | Trace call chain from entry point |
| `find_fortran_callers` | What calls this Fortran function? |
| `shell_to_fortran_path` | Full path from J-job to Fortran code |
| `module_dependency_graph` | What modules does this code depend on? |

**Example Queries These Enable**:
```
User: "What Fortran functions are called when JSEAICE_ANALYSIS runs?"

→ Graph traversal:
  JSEAICE_ANALYSIS 
    -[:EXECUTES]-> exseaice_analysis.sh
    -[:INVOKES]-> seaice_blend (Program)
    -[:CALLS]-> init_grid, read_satellite_data, write_output
    -[:CALLS]-> (deeper functions...)
```

**Validation**: MCP tools return correct call paths.

---

### Step 7: Hybrid Query Integration

**Objective**: Combine graph structure with semantic embeddings.

**Use Case**: "Find EE2 compliance issues in functions called by seaice_blend"

**Query Flow**:
1. **Graph**: `MATCH (p:Program {name:"seaice_blend"})-[:CALLS*]->(f) RETURN f.file, f.name`
2. **For each function**: Read source code
3. **Embedding**: Query ChromaDB for relevant EE2 standards
4. **Analysis**: Check code against retrieved standards

**Validation**: End-to-end query returns meaningful compliance results.

---

## Deliverables

| Deliverable | Location | Status |
|-------------|----------|--------|
| Fortran source catalog | `fortran_sources.txt` | ⬜ |
| Parser script | `scripts/parse_fortran_structure.py` | ⬜ |
| Neo4j ingestion script | `scripts/ingest_fortran_to_neo4j.py` | ⬜ |
| Shell-Fortran linker | `scripts/link_shell_to_fortran.py` | ⬜ |
| MCP tools (4) | `src/tools/FortranAnalysisTools.js` | ⬜ |
| Integration tests | `test/test_fortran_graph.js` | ⬜ |

---

## Success Criteria

1. **Graph Coverage**: >90% of Fortran CALL statements represented as edges
2. **Shell Linkage**: All `$EXEC` references linked to Fortran programs
3. **Query Response**: Call tree queries return in <500ms
4. **Hybrid Queries**: Can trace J-job → Fortran → EE2 standards in single workflow

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| fparser can't handle old Fortran77 | Fall back to regex-based extraction for .f files |
| Executable names don't match program names | Build explicit mapping table from Makefile targets |
| Large graphs slow down queries | Add indexes on name properties, limit traversal depth |
| Module dependencies create cycles | Use Cypher `shortestPath` to avoid infinite loops |

---

## Future Extensions

- **C/C++ Integration**: Same approach with clang AST dumps
- **Python Call Graphs**: Use `pycallgraph` or AST parsing
- **Build System Integration**: Extract from CMake/Make dependency graphs
- **Runtime Tracing**: Instrument executables to capture actual call paths (not just static analysis)

---

## Notes

This phase represents a significant capability upgrade - moving from "what does this code look like?" (embeddings) to "how does this code actually execute?" (graph). The combination enables queries that neither system could answer alone.

The shell→Fortran boundary is the critical link. Without it, the two worlds (scripting and computational code) remain disconnected in the knowledge base.

---

*"If it's not in the SDD, it doesn't get coded."*
