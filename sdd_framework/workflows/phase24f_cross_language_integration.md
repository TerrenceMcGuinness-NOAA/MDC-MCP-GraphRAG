# SDD: Phase 24F - Cross-Language Graph Integration

**Version:** 2.0.0
**Created:** 2026-02-05
**Updated:** 2026-02-23
**Author:** Terry McGuinness + AI Assistant
**Status:** Ready for Execution
**Execution Mode:** ISD (Interactive Supervised Development)
**Dependencies:** Phase 10 (Fortran Ingestion), Phase 27B/F/I (Shell Graph + Bridges), Phase 24A-D (GGSR)
**Downstream:** Phase 24G (Benchmark & Validation), Phase 24H (Agentic Tool Surface)
**Estimated Effort:** 12 hours across 10 steps

---

## 1. Executive Summary

Phase 10 delivered 368K Fortran relationships to Neo4j. Phase 27 delivered 314 shell scripts with 9,155 relationships, 16 EXECUTES bridge edges, and 4 INVOKES cross-language edges. Despite all this data existing in the graph, **no MCP tool can traverse across language boundaries in a single query**. The `find_callers_callees` tool picks one language and stays within it. The bridge edges exist but are stranded on `File` nodes that are disconnected from the `ShellScript` nodes.

This phase unifies the node model, creates a cross-language traversal engine, and updates existing MCP tools to walk execution chains from J-Job shell scripts through Fortran subroutine call trees (and back).

### Key Capability

```
Query: "What Fortran code does JGLOBAL_ATMOS_ANALYSIS execute?"

Before (current state):
  find_callers_callees("JGLOBAL_ATMOS_ANALYSIS") → Shell: jjob_header.sh, exglobal_atmos_analysis.sh
  find_callers_callees("gsi")                    → Fortran: setup(), read_obs(), ...
  *** No connection between these two results ***

After (Phase 24F):
  find_callers_callees("JGLOBAL_ATMOS_ANALYSIS", cross_language=true)
  → Shell:   JGLOBAL_ATMOS_ANALYSIS → exglobal_atmos_analysis.sh
  → Bridge:  exglobal_atmos_analysis.sh ═══EXECUTES═══> gsi [Fortran]
  → Fortran: gsi → setup() → read_obs() → setuprad() → ...
  Complete execution chain in one call.
```

---

## 2. Problem Statement

### 2.1 The Dual-Ingester Node Split

Two separate ingesters created **parallel, disconnected node populations** for the same shell scripts:

| Ingester | Node Label | Count | Has EXECUTES? | Has SOURCES/INVOKES? |
|----------|-----------|-------|---------------|----------------------|
| `ingest_code_v8.py` | `File` | 2,744 | **Yes** (16 edges → FortranProgram) | No |
| `ingest_shell_graph_v8.py` | `ShellScript` | 383 | **No** | **Yes** (393 SOURCES, 352 INVOKES) |

**Zero nodes have both labels.** There are no edges connecting `ShellScript` → `File` even though they represent the same scripts. The ShellScript nodes use relative paths (`dev/jobs/JGLOBAL_FORECAST`) while File nodes use absolute paths (`/mcp_rag_eib/global-workflow_.../scripts/exglobal_atmos_analysis.sh`).

### 2.2 Tool Isolation by Language

`find_callers_callees` handler in CodeAnalysisTools.js (lines 748-960) uses sequential fallback:

```
1. Try Function/PythonFunction → CALLS
2. Try FortranSubroutine/FortranFunction/FortranProgram → CALLS
3. Try ShellScript → SOURCES|INVOKES
```

Once it matches a graph type, it stays within that type's relationships. No step crosses into another language's edges.

### 2.3 Existing Cross-Language Code (Partial)

Two methods already exist but are underutilized:

- **`GraphDatabase.traceCrossLanguagePath()`** (line 704): Queries `CodeFile` label (but bridge edges are on `File` label — mismatch)
- **`GGSRTraversalPrototypes.crossLanguageTrace()`** (line 537): Queries `File` label for EXECUTES bridges — **correct label** but only called as a supplementary append in `trace_execution_path`, not integrated into the main result

### 2.4 Additional Label Inconsistency

| Code Location | Label Used for Shell | Reality |
|---------------|---------------------|---------|
| `traceCrossLanguagePath` | `CodeFile` | Bridge edges are on `File` nodes |
| `crossLanguageTrace` | `File` | Correct |
| `findScriptCallers` | `ShellScript` | Shell graph nodes |
| Bridge ingester output | `File` | Created by `ingest_cross_language_bridges.py` |

---

## 3. Current Graph State (as of 2026-02-23)

### Node Inventory

| Label | Count | Source |
|-------|-------|--------|
| FortranSubroutine | 13,537 | Phase 10 |
| CodeFunction | 5,059 | Code ingestion |
| PythonFunction | 3,267 | Python ingestion |
| File | 2,744 | Code ingestion |
| EnvironmentVariable | 2,489 | Shell graph |
| FortranFunction | 2,355 | Phase 10 |
| Function | 1,763 | Code ingestion |
| FortranModule | 1,539 | Phase 10 |
| ShellScript | 383 | Shell graph |
| PythonModule | 624 | Python ingestion |
| FortranProgram | 153 | Phase 10 + 27I placeholders |
| ShellFunction | 63 | Shell graph |

### Bridge Edges

| Type | Count | Source Label | Target Label |
|------|-------|-------------|--------------|
| EXECUTES | 16 | `File` | `FortranProgram` |
| INVOKES (cross-lang) | 4 | `File` | `PythonModule` |

### Total Relationships: 567,665

---

## 4. Technical Specification

### 4.1 Extended Relationship Weight Matrix

Current GGSR weights in `GGSRTraversalPrototypes.js` (lines 24-50):

| Relationship | Weight | Language Scope |
|--------------|--------|---------------|
| `CALLS` | 1.0 | Within-language |
| `EXECUTES` | 1.0 | **Cross-language** (Shell → Fortran) |
| `SOURCES` | 0.95 | Shell |
| `INVOKES` | 0.9 | Shell / **Cross-language** (Shell → Python) |
| `CALLED_BY` | 0.9 | Within-language |
| `DEPENDS_ON` | 0.8 | Both |
| `DEPENDS_ON_ENV` | 0.8 | Both |
| `IMPORTS` | 0.7 | Both |
| `USES` | 0.7 | Fortran |

Weights are already correct. The problem is **traversal queries don't follow them across label boundaries**.

### 4.2 Cross-Language Traversal Cypher

#### Forward Chain: J-Job → Fortran

```cypher
// Step 1: Shell chain (ShellScript nodes)
MATCH shellPath = (job:ShellScript)-[:SOURCES|INVOKES*1..3]->(exScript:ShellScript)
WHERE job.name =~ $pattern

// Step 2: Bridge hop (ShellScript name → File node → FortranProgram)
WITH exScript
MATCH (f:File)-[:EXECUTES]->(prog:FortranProgram)
WHERE f.absolutePath CONTAINS exScript.name

// Step 3: Fortran chain (FortranProgram → Subroutines)
OPTIONAL MATCH fortranPath = (prog)-[:CALLS*1..{depth}]->(sub)
WHERE sub:FortranSubroutine OR sub:FortranFunction

RETURN job.name AS source, exScript.name AS bridge_script,
       prog.name AS fortran_program,
       [node IN nodes(fortranPath) | node.name] AS fortran_chain
```

#### Reverse Chain: Fortran → J-Job

```cypher
MATCH (prog:FortranProgram)
WHERE prog.name = $name
MATCH (f:File)-[:EXECUTES]->(prog)
WITH prog, f
MATCH (s:ShellScript)
WHERE f.absolutePath CONTAINS s.name
OPTIONAL MATCH callerPath = (job:ShellScript)-[:SOURCES|INVOKES*1..3]->(s)
WHERE job.type = 'j-job'
RETURN prog.name AS fortran_program, s.name AS bridge_script,
       job.name AS triggering_jjob
```

### 4.3 Node Unification Strategy

**Option A — Label merge**: Add `:ShellScript` label to `File` nodes that have EXECUTES edges.
**Option B — Bridge edges**: Create EXECUTES edges directly on ShellScript nodes matching File nodes by name.

**Decision: Option B** — Adding labels to File nodes risks polluting the code-structure ingester's data model. Creating parallel EXECUTES edges on ShellScript nodes is additive and doesn't alter existing ingestion output.

---

## 5. Implementation Steps

### Step 1: Node Unification — Bridge EXECUTES to ShellScript Nodes
- **Type:** data
- **Required:** true
- **Estimated:** 1 hour
- **Files:** `mcp_server_node/scripts/ingest_cross_language_bridges.py`

**Task:** For each `(f:File)-[:EXECUTES]->(p:FortranProgram)` edge, find the corresponding `ShellScript` node by matching the filename from `f.absolutePath`, then create a parallel `(s:ShellScript)-[:EXECUTES]->(p:FortranProgram)` edge.

**Cypher:**
```cypher
// Find unlinked EXECUTES and create parallel edges on ShellScript nodes
MATCH (f:File)-[r:EXECUTES]->(p:FortranProgram)
WITH f, p, split(f.absolutePath, '/')[-1] AS filename
MATCH (s:ShellScript)
WHERE s.name = filename OR s.path ENDS WITH filename
MERGE (s)-[:EXECUTES {source: 'bridge_unification', bridged_from: f.absolutePath}]->(p)
RETURN s.name AS shell_script, p.name AS fortran_program
```

**Also:** Create `(s:ShellScript)-[:INVOKES]->(m:PythonModule)` for the 4 existing File→PythonModule INVOKES edges using the same name-matching strategy.

**Validation:**
- `MATCH (s:ShellScript)-[:EXECUTES]->(p:FortranProgram) RETURN count(*)` should go from 0 to ~16
- `MATCH (s:ShellScript)-[r:INVOKES]->(p:PythonModule) RETURN count(*)` should go from 0 to ~4

---

### Step 2: Unified Traversal Method in GraphDatabase.js
- **Type:** implement
- **Required:** true
- **Estimated:** 1.5 hours
- **Files:** `mcp_server_node/src/data/GraphDatabase.js`

**Task:** Add new method `traceCrossLanguageChain(name, depth, direction)` that:

1. Finds the starting node by name across all labels (`ShellScript`, `File`, `FortranProgram`, `FortranSubroutine`, `PythonFunction`)
2. Identifies the node's language from its labels
3. Walks outward following ALL relationship types: `CALLS|SOURCES|INVOKES|EXECUTES|USES`
4. Returns a unified result with language annotations per hop

**Method Signature:**
```javascript
/**
 * Trace execution chain across language boundaries.
 * @param {string} name - Starting node name (J-Job, script, Fortran program, etc.)
 * @param {number} depth - Maximum hops per language segment (default: 5)
 * @param {'forward'|'reverse'|'both'} direction - Traversal direction
 * @returns {Object} { chain: [{name, label, language, hop, relType}], bridges: [{from, to, type}] }
 */
async traceCrossLanguageChain(name, depth = 5, direction = 'forward')
```

**Forward traversal Cypher:**
```cypher
// Find start node
MATCH (start)
WHERE start.name =~ $pattern
WITH start, labels(start)[0] AS startLabel

// Shell segment
OPTIONAL MATCH shellPath = (start)-[:SOURCES|INVOKES*0..3]->(exScript)
WHERE exScript:ShellScript

// Bridge: Shell → Fortran
OPTIONAL MATCH (exScript)-[:EXECUTES]->(prog:FortranProgram)

// Fortran segment
OPTIONAL MATCH fortranPath = (prog)-[:CALLS*1..{depth}]->(sub)
WHERE sub:FortranSubroutine OR sub:FortranFunction

// Bridge: Shell → Python
OPTIONAL MATCH (exScript)-[:INVOKES]->(pyMod:PythonModule)
OPTIONAL MATCH (pyMod)-[:DEFINES]->(pyFunc:PythonFunction)
OPTIONAL MATCH pyPath = (pyFunc)-[:CALLS*1..{depth}]->(pyCalled:PythonFunction)

RETURN start, collect(DISTINCT exScript) AS shellHops,
       collect(DISTINCT prog) AS fortranPrograms,
       collect(DISTINCT sub) AS fortranSubs,
       collect(DISTINCT pyFunc) AS pythonFuncs
```

**Also fix:** Update `traceCrossLanguagePath()` (line 704) to query `File` label instead of `CodeFile` (the actual label on bridge nodes).

**Validation:**
- `traceCrossLanguageChain('JGLOBAL_ATMOS_ANALYSIS', 3, 'forward')` returns shell + bridge + Fortran nodes
- `traceCrossLanguageChain('gsi', 3, 'reverse')` finds shell scripts that execute gsi

---

### Step 3: Update `find_callers_callees` for Cross-Language
- **Type:** implement
- **Required:** true
- **Estimated:** 2 hours
- **Files:** `mcp_server_node/src/tools/CodeAnalysisTools.js` (lines 748-960)

**Task:** Add `cross_language` boolean parameter to `find_callers_callees` tool schema and handler.

**Schema change:**
```javascript
{
  name: 'find_callers_callees',
  inputSchema: {
    // ... existing params ...
    cross_language: {
      type: 'boolean',
      description: 'When true, follow EXECUTES/INVOKES edges across language boundaries (Shell↔Fortran, Shell↔Python). Default: false for backward compatibility.'
    }
  }
}
```

**Handler changes:**

When `cross_language === true` and graph type is `shell`:
1. Run existing shell traversal (SOURCES/INVOKES within ShellScript)
2. For each shell callee, check for EXECUTES edges → continue into Fortran
3. For each shell callee, check for INVOKES edges → continue into Python
4. Format output with language annotations:

```
## Callees (Cross-Language)

### Shell Layer
- JGLOBAL_ATMOS_ANALYSIS → exglobal_atmos_analysis.sh (INVOKES)

### Language Bridge (Shell → Fortran)
- exglobal_atmos_analysis.sh ═══EXECUTES═══> gsi
- exglobal_atmos_analysis.sh ═══EXECUTES═══> calc_analysis
- exglobal_atmos_analysis.sh ═══EXECUTES═══> calc_increment_main

### Fortran Layer (from gsi)
- gsi → setup (CALLS, depth: 1)
- gsi → read_obs (CALLS, depth: 1)
- setup → setuprad (CALLS, depth: 2)
```

When `cross_language === true` and graph type is `fortran`:
1. Run existing Fortran traversal (CALLS within Fortran)
2. Check if starting node is a FortranProgram with incoming EXECUTES edges
3. Prepend shell callers: which ShellScript EXECUTES this program?
4. Continue upstream: which J-Job INVOKES/SOURCES that script?

**Backward compatibility:** When `cross_language` is omitted or false, behavior is identical to current.

**Validation:**
- `find_callers_callees({ function_name: 'JGLOBAL_ATMOS_ANALYSIS', direction: 'callees', cross_language: true })` returns Shell + Fortran results
- `find_callers_callees({ function_name: 'gsi', direction: 'callers', cross_language: true })` returns Fortran + Shell callers
- `find_callers_callees({ function_name: 'JGLOBAL_FORECAST', direction: 'callees' })` (no cross_language) returns Shell-only (backward compat)

---

### Step 4: Update `trace_execution_path` for Integrated Output
- **Type:** implement
- **Required:** true
- **Estimated:** 1.5 hours
- **Files:** `mcp_server_node/src/tools/CodeAnalysisTools.js` (lines 471-745)

**Task:** Currently `trace_execution_path` appends GGSR cross-language traces as a separate "Cross-Language" section at the end. Integrate it into the main output so the result is one continuous execution path.

**Changes:**
1. After main shell/fortran/python trace, call `traceCrossLanguageChain()` (Step 2)
2. Merge results into a single ordered path
3. Annotate bridge hops with `[BRIDGE]` markers
4. Fix the `CodeFile` → `File` label in `traceCrossLanguagePath()` (line 704)

**Output format:**
```
## Execution Path: JGLOBAL_ATMOS_ANALYSIS

1. [Shell]   JGLOBAL_ATMOS_ANALYSIS
2. [Shell]   → exglobal_atmos_analysis.sh (INVOKES)
3. [Bridge]  ═══ EXECUTES ═══> gsi [FortranProgram]
4. [Fortran] → setup (CALLS)
5. [Fortran] → read_obs (CALLS)
6. [Fortran]   → setuprad (CALLS, depth: 2)
```

**Validation:**
- `trace_execution_path({ start_point: 'JGLOBAL_ATMOS_ANALYSIS', max_depth: 4 })` returns integrated Shell→Fortran path
- No separate "Cross-Language Bridges" section at the bottom

---

### Step 5: New Tool — `trace_full_execution_chain`
- **Type:** implement
- **Required:** true
- **Estimated:** 2 hours
- **Files:** `mcp_server_node/src/tools/CodeAnalysisTools.js` or `GraphRAGTools.js`

**Task:** Dedicated MCP tool for end-to-end cross-language execution chain traces. This is the flagship tool of Phase 24F.

**Schema:**
```javascript
{
  name: 'trace_full_execution_chain',
  description: 'Trace complete execution chain across Shell, Python, and Fortran language boundaries. Starting from any node (J-Job, script, Fortran program, Python task), follows SOURCES, INVOKES, EXECUTES, CALLS, USES, and DEFINES edges to build the full execution tree.',
  inputSchema: {
    type: 'object',
    properties: {
      start: {
        type: 'string',
        description: 'Starting point: J-Job name (JGLOBAL_FORECAST), script name (exglobal_forecast.sh), Fortran program (gsi), or Python module (pygfs.task.gfs_forecast)'
      },
      direction: {
        type: 'string',
        enum: ['forward', 'reverse', 'both'],
        description: 'forward: trace what this node executes. reverse: trace what triggers this node. both: full bidirectional context. Default: forward'
      },
      max_depth: {
        type: 'number',
        description: 'Maximum hops per language segment (default: 5)'
      },
      languages: {
        type: 'array',
        items: { type: 'string', enum: ['shell', 'fortran', 'python'] },
        description: 'Limit to specific languages. Default: all'
      }
    },
    required: ['start']
  }
}
```

**Handler:** Calls `traceCrossLanguageChain()` from Step 2 and formats the result as a tree:

```
## Full Execution Chain: JGLOBAL_ATMOS_ANALYSIS

### Forward Direction

[J-Job] JGLOBAL_ATMOS_ANALYSIS
├── [Shell] ush/jjob_header.sh (SOURCES)
├── [Shell] exglobal_atmos_analysis.sh (INVOKES)
│   ├── [Fortran] gsi (EXECUTES)
│   │   ├── setup (CALLS)
│   │   ├── read_obs (CALLS)
│   │   │   └── setuprad (CALLS)
│   │   └── minimize (CALLS)
│   ├── [Fortran] calc_analysis (EXECUTES)
│   ├── [Fortran] calc_increment_main (EXECUTES)
│   ├── [Fortran] enkf_chgres_recenter_nc (EXECUTES)
│   └── [Fortran] interp_inc (EXECUTES)

### Statistics
- Languages traversed: Shell, Fortran
- Total nodes: 14
- Bridge crossings: 5 (Shell → Fortran)
- Max depth: 4 hops
- Query time: 87ms
```

**Tool registration:** Add to CodeAnalysisTools.js `getToolDefinitions()` and `handleToolCall()`.

**Validation:**
- 5 test cases (see Step 10)
- Returns results for all 3 starting point types (J-Job, script, Fortran)
- Reverse direction works (Fortran → Shell → J-Job)

---

### Step 6: GGSR Weight Matrix — Language Bridge Compensation
- **Type:** implement
- **Required:** false (optimization)
- **Estimated:** 1 hour
- **Files:** `mcp_server_node/src/graphrag/GGSRTraversalPrototypes.js`

**Task:** When GGSR traversal crosses a language boundary (detected by change in node label category), reduce the hop decay penalty. The bridge hop is structural infrastructure, not a semantic distance — penalizing it equally with normal hops undervalues cross-language neighbors.

**Changes at lines 24-52:**

```javascript
// Add bridge bonus constant
static BRIDGE_DECAY_OVERRIDE = 0.8; // Instead of standard HOP_DECAY (0.5)

// In scoring logic, detect language transition
const isLanguageBridge = (prevLabel, currLabel) => {
  const shellLabels = new Set(['ShellScript', 'File', 'CodeFile']);
  const fortranLabels = new Set(['FortranProgram', 'FortranSubroutine', 'FortranFunction', 'FortranModule']);
  const pythonLabels = new Set(['PythonFunction', 'PythonModule', 'PythonClass']);
  const prevLang = shellLabels.has(prevLabel) ? 'shell' : fortranLabels.has(prevLabel) ? 'fortran' : pythonLabels.has(prevLabel) ? 'python' : 'other';
  const currLang = shellLabels.has(currLabel) ? 'shell' : fortranLabels.has(currLabel) ? 'fortran' : pythonLabels.has(currLabel) ? 'python' : 'other';
  return prevLang !== currLang && prevLang !== 'other' && currLang !== 'other';
};
```

**Effect:** A 2-hop path Shell→EXECUTES→FortranProgram→CALLS→FortranSub would score:
- Before: `1.0 × 0.5 × 1.0 × 0.5 = 0.25`
- After:  `1.0 × 0.8 × 1.0 × 0.5 = 0.40` (bridge hop uses 0.8 instead of 0.5)

**Validation:**
- `get_code_context({ symbol: 'exglobal_atmos_analysis.sh' })` returns higher-scored Fortran neighbors than before
- No regression: within-language scores unchanged

---

### Step 7: Neo4j Index Optimization
- **Type:** data
- **Required:** true
- **Estimated:** 0.5 hours
- **Files:** `mcp_server_node/scripts/ingest_cross_language_bridges.py` (add index creation)

**Task:** Create indexes to support the new cross-language queries:

```cypher
// Composite indexes for bridge lookups
CREATE INDEX shell_executes_idx IF NOT EXISTS FOR (s:ShellScript) ON (s.name);
CREATE INDEX fortran_program_name_idx IF NOT EXISTS FOR (p:FortranProgram) ON (p.name);
CREATE INDEX fortran_sub_name_idx IF NOT EXISTS FOR (s:FortranSubroutine) ON (s.name);
CREATE INDEX python_module_name_idx IF NOT EXISTS FOR (m:PythonModule) ON (m.name);

// Full-text index for cross-language name search
CREATE FULLTEXT INDEX cross_language_names IF NOT EXISTS
  FOR (n:ShellScript|FortranProgram|FortranSubroutine|PythonFunction|PythonModule)
  ON EACH [n.name];
```

**Profile target:** Cross-language 5-hop queries under 200ms.

**Validation:**
- `PROFILE` on the Step 2 Cypher queries shows index hits, not node scans
- Measure latency before and after

---

### Step 8: Reverse Direction Support
- **Type:** implement
- **Required:** true
- **Estimated:** 1.5 hours
- **Files:** `mcp_server_node/src/tools/CodeAnalysisTools.js`, `mcp_server_node/src/data/GraphDatabase.js`

**Task:** Enable "upstream" tracing from any Fortran node back through EXECUTES bridges to shell scripts and J-Jobs.

**New method in GraphDatabase.js:**
```javascript
async findUpstreamExecutors(fortranName) {
  // What shell scripts EXECUTE this Fortran program?
  // And what J-Jobs trigger those scripts?
  const query = `
    MATCH (prog:FortranProgram)<-[:EXECUTES]-(script)
    WHERE prog.name = $name
    OPTIONAL MATCH callerPath = (jjob:ShellScript)-[:SOURCES|INVOKES*1..3]->(script)
    WHERE jjob.type = 'j-job'
    RETURN prog.name AS program, script.name AS executor_script,
           labels(script)[0] AS script_label,
           collect(DISTINCT jjob.name) AS triggering_jjobs
  `;
  return this.query(query, { name: fortranName });
}
```

**Integration with `get_change_impact`** (GraphRAGTools.js):
- When analyzing impact of a Fortran subroutine change, trace upstream to affected J-Jobs
- Add "Operational Impact" section showing which workflow tasks would be affected

**Validation:**
- `findUpstreamExecutors('gsi')` returns `exglobal_atmos_analysis.sh` → `JGLOBAL_ATMOS_ANALYSIS`
- `get_change_impact({ symbol: 'setup', scope: 'full' })` includes upstream shell/J-Job impact

---

### Step 9: Fix Label Inconsistency in Existing Code
- **Type:** implement
- **Required:** true
- **Estimated:** 0.5 hours
- **Files:** `mcp_server_node/src/data/GraphDatabase.js`

**Task:** Fix the `CodeFile` vs `File` label mismatch in `traceCrossLanguagePath()` (line 704).

**Current (broken):**
```cypher
MATCH (shell:CodeFile)
WHERE shell.language = 'shell' AND (shell.name =~ $pattern OR shell.path =~ $pattern)
```

**Fixed:**
```cypher
MATCH (shell)
WHERE (shell:File OR shell:ShellScript OR shell:CodeFile)
AND (shell.name =~ $pattern OR shell.path =~ $pattern OR shell.absolutePath =~ $pattern)
```

This makes the existing `traceCrossLanguagePath` method work with with all three node types that might represent shell scripts.

**Validation:**
- `traceCrossLanguagePath('exglobal_atmos_analysis', 3)` returns Fortran results
- Previously returned empty due to label mismatch

---

### Step 10: Validation & End-to-End Testing
- **Type:** validate
- **Required:** true
- **Estimated:** 1 hour
- **Files:** `mcp_server_node/src/__tests__/CrossLanguageTraversal.test.js` (new)

**5 Required Test Cases:**

| # | Test | Input | Expected |
|---|------|-------|----------|
| 1 | Shell → Fortran (forward) | `JGLOBAL_ATMOS_ANALYSIS` → forward | Chain: J-Job → exglobal_atmos_analysis.sh → gsi, calc_analysis, calc_increment_main, enkf_chgres_recenter_nc, interp_inc |
| 2 | Fortran → Shell (reverse) | `enkf_chgres_recenter` → reverse | Chain: enkf_chgres_recenter ← exgdas_atmos_chgres_forenkf.sh ← JGDAS_ATMOS_CHGRES_FORENKF |
| 3 | Shell → Python (forward) | `exglobal_atmos_analysis.sh` → forward+python | At least 1 PythonModule via INVOKES |
| 4 | Fortran reverse to J-Job | `calc_analysis` → reverse | Must reach JGLOBAL_ATMOS_ANALYSIS_CALC |
| 5 | Latency benchmark | 5 cross-language queries | All under 200ms |

**Update `mcp_health_check` functional tests:**
- Add test 6: "Cross-Language Traversal" — `find_callers_callees({ function_name: 'gsi', direction: 'callers', cross_language: true })` must return at least one ShellScript

**Docker image rebuild required** after all code changes.

---

## 6. Dependency Order

```
Step 1 (data: bridge EXECUTES to ShellScript) ←── prerequisite for everything
  ↓
Step 9 (fix: label inconsistency) ←── quick win, unblocks existing code
  ↓
Step 2 (code: unified traversal method in GraphDatabase.js)
  ↓
Step 3 + Step 4 (code: update find_callers_callees + trace_execution_path) ←── can parallelize
  ↓
Step 5 (code: new trace_full_execution_chain tool)
  ↓
Step 6 + Step 7 + Step 8 (optimization: GGSR weights + indexes + reverse direction) ←── can parallelize
  ↓
Step 10 (validate: end-to-end tests + health check update)
```

---

## 7. Files Modified

| File | Changes |
|------|---------|
| `scripts/ingest_cross_language_bridges.py` | Add ShellScript EXECUTES/INVOKES edge creation + Neo4j indexes |
| `src/data/GraphDatabase.js` | New `traceCrossLanguageChain()`, `findUpstreamExecutors()`, fix `traceCrossLanguagePath` label |
| `src/tools/CodeAnalysisTools.js` | `find_callers_callees` cross_language param, `trace_execution_path` integration, new `trace_full_execution_chain` tool |
| `src/graphrag/GGSRTraversalPrototypes.js` | Bridge decay override constant, language transition detection |
| `src/__tests__/CrossLanguageTraversal.test.js` | New test file with 5 end-to-end cases |
| `src/tools/SemanticSearchTools.js` | Update `mcp_health_check` functional tests |

---

## 8. Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| `ShellScript -[:EXECUTES]-> FortranProgram` edges | 0 | 16+ |
| `find_callers_callees` cross-language results | 0 | All bridge paths traversed |
| Fortran subroutines reachable from J-Jobs | 0 | >10,000 (via CALLS chains) |
| Cross-language path query latency (5-hop) | N/A | <200ms |
| `trace_full_execution_chain` tool | Does not exist | Operational |
| Reverse trace (Fortran → J-Job) | Not possible | Working |
| Health check cross-language test | Does not exist | PASS |

---

## 9. Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| ShellScript↔File name matching misses some scripts | Medium | Log unmatched, manual review, accept partial coverage |
| Query performance degrades with larger traversal depth | Low | Neo4j indexes (Step 7), depth limits, LIMIT clauses |
| `cross_language: true` breaks existing tool consumers | Low | Default is `false`, opt-in only |
| Label inconsistency remains across future ingestions | Medium | Add label unification to post-ingestion hook, document in ingestion README |

---

## 10. Post-Implementation

- Update `CHANGELOG.md` with Phase 24F version entry
- Rebuild Docker image: `docker build -f SETUP/dockerfiles/Dockerfile.mcp-server -t eib-mcp-rag:latest ./mcp_server_node`
- Restart MCP gateway
- Run full `mcp_health_check({ functional: true })` to verify
- Update Phase 24G benchmark spec with cross-language retrieval quality metrics

---

*Comprehensive spec — ready for SDD session execution.*
