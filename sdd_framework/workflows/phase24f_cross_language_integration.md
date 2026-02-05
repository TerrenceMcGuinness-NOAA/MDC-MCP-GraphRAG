# SDD: Phase 24F - Cross-Language Graph Integration

**Version:** 1.0.0  
**Created:** 2026-02-05  
**Author:** Terry McGuinness + AI Assistant  
**Status:** Prospectus (Q2-Q3 2026)  
**Dependencies:** Phase 10 (Fortran Ingestion), Phase 24A-D (GGSR)

---

## 1. Executive Summary

Phase 10 delivered 368K Fortran relationships to Neo4j. This phase integrates that Fortran call graph into the GGSR retrieval system, enabling **cross-language execution tracing** from J-Jobs through shell scripts into Fortran subroutines.

### Key Capability

```
Query: "What Fortran code does JGFS_FORECAST execute?"

Before (24D only): 
- Finds shell scripts
- Cannot cross into Fortran

After (24F):
- Traces: JGFS_FORECAST → exglobal_forecast.sh → ufs_model.x
- Continues: ufs_model → atmosphere_init → fv_dynamics → fv_update_phys
- Returns complete execution tree spanning both languages
```

---

## 2. Problem Statement

### The Language Boundary Gap

Phase 24D's GGSR traverses shell relationships effectively:
- `SOURCES`: Shell sourcing other shells
- `INVOKES`: Shell calling shell functions
- `DEPENDS_ON_ENV`: Environment variable dependencies

But it **stops at language boundaries**:
- Shell scripts execute Fortran binaries via `$EXEC*` variables
- The GGSR traversal doesn't cross into Fortran CALLS/USES graphs

### Solution: EXECUTES Bridge

Phase 10 M4 created 35 `EXECUTES` relationships:
```cypher
(shell:ShellScript)-[:EXECUTES]->(program:FortranProgram)
```

This phase extends GGSR to:
1. Include EXECUTES in traversal patterns
2. Add Fortran relationship weights (CALLS: 1.0, USES: 0.7)
3. Enable end-to-end path queries

---

## 3. Technical Specification

### 3.1 Extended Relationship Weight Matrix

| Relationship | Weight | Language | Notes |
|--------------|--------|----------|-------|
| `CALLS` (Shell) | 1.0 | Shell | Function calls |
| `SOURCES` | 0.95 | Shell | Tight coupling |
| `INVOKES` | 0.9 | Shell | Script invocation |
| **`EXECUTES`** | **1.0** | **Cross** | **Shell → Fortran** |
| **`CALLS` (Fortran)** | **1.0** | **Fortran** | **Subroutine calls** |
| **`USES`** | **0.7** | **Fortran** | **Module imports** |
| `DEPENDS_ON` | 0.8 | Both | Config dependencies |

### 3.2 Cross-Language Traversal Query

```cypher
// Extended GGSR traversal including Fortran
MATCH path = (start:ShellScript|FortranSubroutine)
  -[r:CALLS|SOURCES|INVOKES|EXECUTES|USES*1..{depth}]->
  (target)
WHERE start.name =~ $pattern
WITH path, 
     [rel IN relationships(path) | type(rel)] as relTypes,
     reduce(w = 1.0, rel IN relationships(path) | 
       w * CASE type(rel)
         WHEN 'CALLS' THEN 1.0
         WHEN 'EXECUTES' THEN 1.0
         WHEN 'SOURCES' THEN 0.95
         WHEN 'INVOKES' THEN 0.9
         WHEN 'USES' THEN 0.7
         WHEN 'DEPENDS_ON' THEN 0.8
         ELSE 0.5
       END
     ) as pathWeight
RETURN path, pathWeight, relTypes
ORDER BY pathWeight DESC
LIMIT 50
```

### 3.3 End-to-End Trace Query

```cypher
// Full execution chain: J-Job → Shell → Fortran → Subroutine
MATCH chain = (job:ShellScript)
  -[:SOURCES|INVOKES*1..3]->(ex:ShellScript)
  -[:EXECUTES]->(prog:FortranProgram)
  -[:CALLS*1..5]->(sub:FortranSubroutine)
WHERE job.name =~ '(?i).*JGFS.*'
RETURN 
  job.name as job,
  ex.name as script,
  prog.name as fortran_program,
  collect(DISTINCT sub.name)[..10] as subroutines,
  length(chain) as depth
ORDER BY depth
```

---

## 4. Implementation Phases

### 24F-1: Weight Matrix Extension (Week 13)

**Objective:** Update GraphGuidedRetrieval to include Fortran relationships

**Steps:**
- [ ] Add CALLS (Fortran), USES, EXECUTES to weight matrix
- [ ] Update traversal queries to include Fortran node types
- [ ] Test: Verify Shell→Fortran paths are traversed
- [ ] Validate: Weight decay across language boundary

### 24F-2: Path Query Optimization (Week 14)

**Objective:** Optimize cross-language path queries for latency

**Steps:**
- [ ] Create Neo4j indexes on Fortran node names
- [ ] Profile query execution plans
- [ ] Add path caching for common starting points
- [ ] Target: <200ms for 5-hop cross-language paths

### 24F-3: MCP Tool Update (Weeks 15-16)

**Objective:** Update `trace_execution_path` and `find_callers_callees`

**New query patterns:**
```javascript
// trace_execution_path enhancement
if (options.include_fortran) {
  query = `
    MATCH path = (start)-[:SOURCES|INVOKES*0..3]->
                 ()-[:EXECUTES]->
                 (prog:FortranProgram)-[:CALLS*1..${depth}]->(target)
    WHERE start.name =~ $pattern
    RETURN path
  `;
}
```

---

## 5. Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Cross-language paths returned | 0 | 100% available |
| Path query latency (5-hop) | N/A | <200ms |
| Fortran subroutines reachable from J-Jobs | 0 | >10,000 |

---

## 6. Dependencies

### Phase 10 Deliverables (Complete ✓)
- [x] 268K CALLS relationships
- [x] 91K USES relationships  
- [x] 35 EXECUTES relationships
- [x] 17K Fortran nodes

### Phase 24D Deliverables (Required)
- [ ] GraphGuidedRetrieval class
- [ ] Weight matrix infrastructure
- [ ] Token budget management

---

*Stub document - to be expanded during implementation*
