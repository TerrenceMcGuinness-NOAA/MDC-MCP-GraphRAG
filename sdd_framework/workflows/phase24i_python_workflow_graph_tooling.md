# SDD: Phase 24I - Python Workflow Tooling Graph Enhancement

**Version:** 1.0.0  
**Created:** 2026-02-10  
**Author:** Terry McGuinness + AI Assistant  
**Status:** Planning  
**Dependencies:** Phase 24F-0 (Python Graph Ingestion), Phase 28 (GraphRAG Acceleration)  
**Vision Reference:** [phase24_consolidated_architecture.md](phase24_consolidated_architecture.md) Section 2 (24F)  
**Downstream:** Phase 22 (Validation Benchmarking), Phase 24H (Agentic Tool Surface)

---

## 1. Executive Summary

Phase 24F-0 ingested 624 `PythonModule` and 3,267 `PythonFunction` nodes into Neo4j. However, empirical testing reveals **three critical gaps** that prevent the MCP tool suite from leveraging this data for Python workflow tooling analysis:

1. **Missing file paths** — All Python nodes have `file: NULL`, making path-based lookups impossible
2. **Noisy relationships** — Duplicate edges and over-broad CALLS (e.g., 19 identical `setup_expt→main`) degrade query quality
3. **MCP tool blind spot** — `find_callers_callees`, `trace_execution_path`, and `analyze_code_structure` only query `Function`/`File`/`ShellScript`/`FortranSubroutine` labels, ignoring `PythonFunction`/`PythonModule`

### Empirical Evidence (2026-02-10)

```
Query: find_callers_callees(function_name="update_configs")
Result: "Entity not found" 

Direct Neo4j:
  MATCH (f:PythonFunction {name: 'update_configs'}) RETURN f
  → Found, but f.file = NULL, 10 CALLS relationships (including builtins like 'split', 'join')

Query: trace_execution_path(entry_point="setup_expt.py", function_name="update_configs")
Result: "Entity not found in function, Fortran, or shell script graphs"
```

### Key Capability After This Phase

```
Query: "What does setup_expt.py do with the base: tag from marine3dvar.yaml?"

Before (current):
  - MCP tools return nothing (Python not queryable)

After (24I):
  - find_callers_callees → update_configs CALLS _update_defaults, map_inputs_to_configs, parse_j2yaml
  - trace_execution_path → setup_expt.py → update_configs → _update_defaults → AttrDict.update
  - analyze_code_structure → Full class/function/import map with file paths
```

---

## 2. Problem Statement

### 2.1 Current State Assessment

| Component | Status | Issue |
|-----------|--------|-------|
| Neo4j Python nodes | 3,891 nodes exist | Missing `file` property on all nodes |
| Neo4j Python relationships | ~15K edges exist | Duplicates, builtins mixed with user code |
| `find_callers_callees` | Does not query Python | Cypher queries only `Function`, `File`, `ShellScript` labels |
| `trace_execution_path` | Does not query Python | Same label restriction |
| `analyze_code_structure` | Does not query Python | Same label restriction |
| `find_dependencies` | Does not query Python | Same label restriction |
| Cross-language Shell→Python | Not traced | No `INVOKES` relationships from shell to Python scripts |

### 2.2 Python Workflow Tooling Scope

The Global Workflow Python tooling is the **configuration and orchestration layer** — it processes YAML configs, generates Rocoto XML, and manages experiment setup. It is structurally critical.

| Directory | Files | Purpose |
|-----------|-------|---------|
| `dev/workflow/` | 45 .py | Experiment setup, workflow generation, host configs |
| `dev/workflow/applications/` | 9 .py | Application definitions (GFS, GEFS, SFS, GCAFS) |
| `dev/workflow/rocoto/` | 18 .py | Rocoto XML generation, task definitions |
| `ush/python/pygfs/task/` | 20+ .py | Task implementations (forecast, analysis, archive) |
| `ush/python/pygfs/jedi/` | ~5 .py | JEDI analysis integration |
| `dev/ci/scripts/` | 11 .py | CI/CD test utilities |
| **Total in scope** | **~145 .py** | **(excluding sorc/ build artifacts)** |

### 2.3 Key Classes and Functions Requiring Graph Coverage

| File | Key Symbols | Why Critical |
|------|------------|--------------|
| `setup_expt.py` | `update_configs`, `_update_defaults`, `map_inputs_to_configs` | Processes YAML `base:` tag overrides into `config.*` files |
| `applications.py` | `AppConfig`, `get_task_names`, `_get_run_options` | Defines which tasks run for each application mode |
| `gfs_cycled.py` | `GFSCycledApp`, `_get_app_configs` | GFS cycled DA application config |
| `workflow_tasks.py` | `Tasks`, `get_task` | Rocoto task generation (what jobs run when) |
| `rocoto.py` | `rocoto_xml`, `create_xml` | Generates the actual Rocoto XML |
| `pygfs/task/*.py` | `Task` subclasses | Runtime task execution (calls `cpfs`, `cpreq`, etc.) |

---

## 3. Technical Specification

### 3.1 Milestone 1: Fix Python Node Properties (Data Quality)

**Objective:** Populate `file` property on all `PythonModule` and `PythonFunction` nodes; deduplicate relationships.

#### 3.1.1 Add File Paths

```cypher
// Pattern: Reconstruct file paths from module names
// e.g., PythonModule "setup_expt" → "dev/workflow/setup_expt.py"
MATCH (m:PythonModule)
WHERE m.file IS NULL
SET m.file = <resolved_path>
```

**Implementation approach:**
1. Re-run Python AST ingestion with file path preservation
2. OR: Build a mapping script that resolves module names to paths using `find` + module name matching

#### 3.1.2 Deduplicate Relationships

```cypher
// Remove duplicate CALLS edges
MATCH (a)-[r:CALLS]->(b)
WITH a, b, type(r) as relType, collect(r) as rels
WHERE size(rels) > 1
UNWIND tail(rels) as dupRel
DELETE dupRel
```

#### 3.1.3 Filter Builtin Noise

```cypher
// Remove CALLS to Python builtins that add noise
MATCH (f:PythonFunction)-[r:CALLS]->(builtin:PythonFunction)
WHERE builtin.name IN ['split', 'join', 'keys', 'copy', 'endswith', 'append', 
                         'listdir', 'exists', 'items', 'get', 'format', 'strip',
                         'replace', 'lower', 'upper', 'startswith', 'pop', 'update']
DELETE r
```

### 3.2 Milestone 2: Shell→Python INVOKES Relationships

**Objective:** Create cross-language edges from shell scripts that call Python scripts.

Many ex-scripts and J-Jobs invoke Python via patterns like:  
```bash
${USHgfs}/python_script.py  
python3 ${HOMEgfs}/ush/python/pygfs/...  
```

```cypher
// Create INVOKES relationships: Shell → Python
MATCH (shell:ShellScript), (py:PythonModule)
WHERE shell.content =~ ('.*' + py.name + '\\.py.*')
CREATE (shell)-[:INVOKES {language_boundary: 'shell_to_python'}]->(py)
```

**Target relationships:**
- `exglobal_forecast.sh` → `pygfs/task/gfs_forecast.py`
- `exglobal_atm_analysis.sh` → `pygfs/task/atm_analysis.py`
- CI scripts → `setup_expt.py`, `create_experiment.py`

### 3.3 Milestone 3: MCP Tool Query Updates

**Objective:** Update `find_callers_callees`, `trace_execution_path`, `analyze_code_structure`, and `find_dependencies` to include Python node labels.

#### 3.3.1 find_callers_callees Enhancement

```javascript
// Current query (Code Analysis tools)
MATCH (f:Function|FortranSubroutine|ShellScript {name: $name})

// Updated query
MATCH (f:Function|FortranSubroutine|ShellScript|PythonFunction|PythonModule {name: $name})
```

#### 3.3.2 trace_execution_path Enhancement

```javascript
// Current: Only traverses Function/File/ShellScript
// Updated: Include PythonFunction/PythonModule with INVOKES cross-language edge
MATCH path = (start)-[:CALLS|SOURCES|INVOKES|EXECUTES*1..{depth}]->(target)
WHERE start.name =~ $pattern
  AND any(label IN labels(start) WHERE label IN 
    ['Function', 'ShellScript', 'FortranSubroutine', 'PythonFunction', 'PythonModule'])
```

#### 3.3.3 analyze_code_structure Enhancement

```javascript
// Add Python-specific structure query
if (nodeType === 'python' || autoDetect) {
  const result = await session.run(`
    MATCH (m:PythonModule {file: $filePath})-[:DEFINES]->(f:PythonFunction)
    OPTIONAL MATCH (f)-[:CALLS]->(called:PythonFunction)
    RETURN m.name as module, collect(DISTINCT f.name) as functions, 
           collect(DISTINCT called.name) as calls
  `, { filePath });
}
```

### 3.4 Milestone 4: YAML Config → Python Tracing

**Objective:** Enable tracing from CI YAML config files through Python to config.* file generation.

```cypher
// Trace: YAML case file → setup_expt.py → config.base generation
MATCH (yaml:File)-[:REFERENCED_BY]->(setup:PythonModule {name: 'setup_expt'})
MATCH (setup)-[:DEFINES]->(fn:PythonFunction {name: 'update_configs'})
MATCH (fn)-[:CALLS]->(inner:PythonFunction)
RETURN yaml.name, fn.name, collect(inner.name) as called_functions
```

New relationship type: `REFERENCED_BY` — connects YAML config files to the Python modules that parse them.

---

## 4. Implementation Plan

### 24I-M1: Data Quality Fix (Week 1)
- [ ] Write path-resolution script mapping `PythonModule.name` → filesystem paths
- [ ] Run batch `SET m.file = ...` updates on all 624 PythonModule nodes
- [ ] Run batch `SET f.file = ...` updates on all 3,267 PythonFunction nodes  
- [ ] Deduplicate CALLS relationships
- [ ] Remove builtin function CALLS noise
- [ ] **Validate:** `MATCH (m:PythonModule) WHERE m.file IS NULL RETURN count(m)` → 0
- [ ] **Validate:** `find_callers_callees` returns results for `update_configs`

### 24I-M2: Shell→Python Cross-Language Edges (Week 2)
- [ ] Scan shell scripts for Python invocation patterns
- [ ] Create `INVOKES` relationships with `language_boundary` property
- [ ] Create `REFERENCED_BY` for YAML → Python connections
- [ ] **Validate:** `MATCH ()-[r:INVOKES]->(:PythonModule) RETURN count(r)` → >10
- [ ] **Validate:** End-to-end trace from J-Job → Shell → Python works

### 24I-M3: MCP Tool Updates (Week 3)
- [ ] Update `find_callers_callees` Cypher to include `PythonFunction|PythonModule`
- [ ] Update `trace_execution_path` to traverse Python nodes
- [ ] Update `analyze_code_structure` with Python file detection
- [ ] Update `find_dependencies` for Python IMPORTS
- [ ] Add unit tests for Python-specific queries
- [ ] **Validate:** All 4 MCP tools return Python results

### 24I-M4: Integration Testing & Documentation (Week 4)
- [ ] Test: `analyze_code_structure` for `dev/workflow/setup_expt.py`
- [ ] Test: `find_callers_callees` for `update_configs` → `_update_defaults`, `map_inputs_to_configs`
- [ ] Test: `trace_execution_path` from `setup_expt.py` depth=3
- [ ] Test: Cross-language trace J-Job → Shell → Python → function
- [ ] Update `copilot-instructions.md` tool categories to document Python coverage
- [ ] Update `phase24_consolidated_architecture.md` 24F-0 status from "Done" to accurate state
- [ ] Update CHANGELOG.md

---

## 5. Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| PythonModule nodes with file path | 0/624 | 624/624 (100%) |
| PythonFunction nodes with file path | 0/3267 | 3267/3267 (100%) |
| Duplicate CALLS relationships removed | ~50% dupes | 0% dupes |
| Builtin noise edges removed | ~30% of edges | 0 builtin edges |
| Shell→Python INVOKES relationships | 0 | >10 |
| YAML→Python REFERENCED_BY | 0 | >5 |
| MCP tools returning Python results | 0/4 | 4/4 |
| `find_callers_callees("update_configs")` | "Not found" | Returns callers + callees |
| `trace_execution_path("setup_expt.py")` | "Not found" | Returns execution tree |

---

## 6. Files to Modify

| File | Change | Milestone |
|------|--------|-----------|
| `mcp_server_node/src/tools/CodeAnalysisTools.js` | Add Python labels to Cypher queries | M3 |
| `mcp_server_node/scripts/ingest_python_graph.py` | Fix file path preservation (or create new) | M1 |
| `mcp_server_node/scripts/fix_python_graph_quality.py` | New: dedup + filter builtins + add paths | M1 |
| `mcp_server_node/scripts/create_shell_python_edges.py` | New: Shell→Python INVOKES creation | M2 |
| `.github/copilot-instructions.md` | Document Python coverage in tool categories | M4 |
| `CHANGELOG.md` | Version bump with Python graph enhancement | M4 |
| `phase24_consolidated_architecture.md` | Update 24F-0 status accurately | M4 |

---

## 7. Dependencies

### Required (Complete)
- [x] Neo4j operational with Python nodes (624 modules, 3267 functions)
- [x] Phase 27B Shell Script Graph (314 scripts)
- [x] Phase 10 Fortran Graph (17K nodes)
- [x] MCP Code Analysis tools framework (CodeAnalysisTools.js)

### Required (In Progress)
- [ ] Phase 24F cross-language traversal patterns (GGSR weight matrix)

### Blocked By
- Nothing — can proceed immediately

---

## 8. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Module name → file path ambiguity (same name in different dirs) | Medium | Medium | Use full path resolution with filesystem scan |
| Python AST re-ingestion breaks existing relationships | Low | High | Script operates as additive update, not re-ingestion |
| MCP tool query performance with 3 additional labels | Low | Low | Neo4j handles OR-label queries efficiently |
| Builtin filtering removes legitimate user functions named `get`, `update` | Medium | Medium | Filter only when source module is `builtins`/stdlib |

---

## 9. Roadmap Alignment

### Vision → Implementation Chain
```
ADVANCED_FUTURE_WORK.md §3 (True GraphRAG) 
  → Phase 24 Consolidated Architecture (GGSR)
    → Phase 24F (Cross-Language Integration)
      → Phase 24I (Python Workflow Tooling) ← THIS DOCUMENT
        → Phase 22 (Validation Benchmarking)
```

### Novel Contribution Beyond Vision
The original Phase 24 vision focused on Fortran↔Shell cross-language tracing. This phase adds:
- **Python↔Shell** cross-language tracing (INVOKES)
- **YAML→Python** configuration tracing (REFERENCED_BY)
- **MCP tool parity** across all three languages (Shell, Fortran, Python)

---

*Document created as part of SDD Phase 24I - February 2026*
