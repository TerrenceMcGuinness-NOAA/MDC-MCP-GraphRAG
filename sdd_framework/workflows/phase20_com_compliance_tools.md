# Phase 20: EE2 COM/COMOUT Compliance Tools

**Status**: PLANNED  
**Created**: December 18, 2025  
**Author**: Terrence McGuinness  
**Priority**: HIGH - Critical for NCO production compliance  
**Depends On**: Phase 19 (Content Abstraction Layer)

---

## Problem Statement

NOAA operational workflows must follow strict EE2 standards for COM (Common Output) directory structure and file naming. Current MCP tools can analyze scripts but lack specialized support for:

1. **Output File Naming** - Validating `${NET}.t${cyc}z.${product}.${grid}.f${fhr}` patterns
2. **COM Path Construction** - Checking how `COMOUT`, `COMIN` paths are built in code
3. **Live Directory Validation** - Comparing actual COM directory contents against standards
4. **Cross-Source Analysis** - Analyzing patterns from code, live dirs, and documentation

### Use Cases

| Scenario | Content Source | Analysis Type |
|----------|----------------|---------------|
| PR Review | GitHub/local code | Path construction patterns |
| CI Pipeline | CTest artifacts | Output file naming validation |
| Production Audit | Live COMOUT listing | Standards compliance check |
| Documentation | EE2 standards docs | Reference pattern extraction |

---

## Solution: Multi-Source COM Compliance Tool

A new MCP tool leveraging the **Content Abstraction Layer** (Phase 19) to analyze COM compliance from any source.

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    EE2 COM COMPLIANCE TOOL                              │
│                                                                         │
│   analyze_com_compliance({                                              │
│     content: "...",           // Code or file listing                   │
│     content_type: "script" | "directory_listing" | "config",            │
│     context: { NET, RUN, PDY, cyc, ... }  // For pattern validation     │
│   })                                                                    │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
┌───────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Source 1:    │     │  Source 2:      │     │  Source 3:      │
│  LIVE COM     │     │  REPO CODE      │     │  CI TEST        │
│  DIRECTORY    │     │                 │     │  OUTPUT         │
├───────────────┤     ├─────────────────┤     ├─────────────────┤
│ ls $COMOUT/*  │     │ GitHub/local    │     │ CTest artifacts │
│               │     │ script content  │     │                 │
│ gfs.t00z.     │     │ ${COM}/${NET}.  │     │ Validation logs │
│ pgrb2.0p25.   │     │ ${cyc}.${type}  │     │                 │
│ f000.grib2    │     │                 │     │                 │
└───────────────┘     └─────────────────┘     └─────────────────┘
     Actual               Patterns              Test Results
     Files                in Code               Verification
```

---

## Tool Interface Design

### New Tool: `analyze_com_compliance`

```javascript
{
  name: "analyze_com_compliance",
  description: "Analyze COM output file naming and path construction for EE2 compliance",
  inputSchema: {
    type: "object",
    properties: {
      // CONTENT SOURCES (uses Phase 19 ContentResolver)
      content: {
        type: "string",
        description: "Script content, directory listing, or config file"
      },
      files: {
        type: "array",
        items: {
          type: "object",
          properties: {
            name: { type: "string" },
            path: { type: "string" },
            content: { type: "string" }
          }
        },
        description: "Multiple files for batch analysis"
      },
      path: {
        type: "string",
        description: "File or directory path (local mode only)"
      },
      
      // CONTENT TYPE
      content_type: {
        enum: [
          "script",            // Bash/Python script to analyze
          "directory_listing", // ls output or file manifest
          "config",            // Config file with COM settings
          "auto"               // Auto-detect
        ],
        default: "auto"
      },
      
      // ANALYSIS MODE
      analysis_type: {
        enum: [
          "output_naming",      // Check COMOUT file naming patterns
          "path_construction",  // Check how COM paths are built in code
          "variable_usage",     // Check COM-related env var usage
          "directory_structure",// Validate directory hierarchy
          "full"                // All checks
        ],
        default: "full"
      },
      
      // CONTEXT (for pattern validation)
      context: {
        type: "object",
        properties: {
          NET: { type: "string", description: "Network: gfs, gefs, gdas" },
          RUN: { type: "string", description: "Run identifier" },
          PDY: { type: "string", description: "Processing date YYYYMMDD" },
          cyc: { type: "string", description: "Cycle hour: 00, 06, 12, 18" },
          component: { type: "string", description: "atmos, ocean, wave, ice" }
        },
        description: "Runtime context for pattern substitution validation"
      },
      
      // SOURCE HINT
      source: {
        enum: ["live_com", "repo_code", "ci_output", "user_input"],
        description: "Content source for context in reports"
      }
    }
  }
}
```

---

## EE2 COM Standards Reference

### Output File Naming Patterns

```javascript
const COM_NAMING_PATTERNS = {
  // Standard pattern: ${NET}.t${cyc}z.${product}.${grid}.f${fhr}
  
  grib2: {
    pattern: /^(gfs|gefs|gdas)\.t(\d{2})z\.(\w+)\.(0p\d+|1p\d+)\.f(\d{3})(\.grib2)?$/,
    example: "gfs.t00z.pgrb2.0p25.f000.grib2",
    components: {
      NET: "gfs|gefs|gdas",
      cyc: "00|06|12|18",
      product: "pgrb2|pgrb2b|flux|goesim|...",
      grid: "0p25|0p50|1p00",
      fhr: "000-384"
    }
  },
  
  bufr: {
    pattern: /^(gfs|gefs|gdas)\.t(\d{2})z\.(\w+)\.bufr$/,
    example: "gfs.t00z.prepbufr.bufr"
  },
  
  netcdf: {
    pattern: /^(gfs|gefs|gdas)\.t(\d{2})z\.(\w+)\.nc$/,
    example: "gfs.t00z.sfcanl.nc"
  },
  
  index: {
    pattern: /^(gfs|gefs|gdas)\.t(\d{2})z\.(\w+)\.(0p\d+|1p\d+)\.f(\d{3})\.idx$/,
    example: "gfs.t00z.pgrb2.0p25.f000.idx"
  }
};
```

### COM Path Construction Patterns

```javascript
const COM_PATH_PATTERNS = {
  correct: [
    // Standard EE2 COM path patterns
    '${COMOUT}/${NET}.t${cyc}z.',
    '${COM_ATMOS_GRIB}/',
    '${COM_ATMOS_BUFR}/',
    'COMOUT=${COMROOT}/${NET}/${ver}/${RUN}.${PDY}/${cyc}/atmos',
    'COMIN=${COMROOT}/${NET}/${ver}/${RUN}.${PDY}/${cyc}/atmos',
    '${COMIN}/${NET}.t${cyc}z.',
  ],
  
  incorrect: [
    // Anti-patterns to flag
    { pattern: '/com/gfs/', reason: "Hardcoded absolute path" },
    { pattern: '$COMOUT/gfs.t', reason: "Missing braces around variable" },
    { pattern: '${COMOUT}/output_', reason: "Non-standard prefix" },
    { pattern: 'COMOUT=/scratch', reason: "Hardcoded scratch path" },
    { pattern: '> ${COMOUT}', reason: "Direct redirect instead of cp/mv" },
  ]
};
```

### Required Environment Variables

```javascript
const COM_REQUIRED_VARS = {
  paths: [
    'COMROOT',    // Root COM directory
    'COMOUT',     // Current output directory
    'COMIN',      // Current input directory
    'COMINgfs',   // GFS input COM
    'COMINgdas',  // GDAS input COM
  ],
  
  component_specific: [
    'COM_ATMOS_GRIB_0p25',
    'COM_ATMOS_GRIB_0p50', 
    'COM_ATMOS_GRIB_1p00',
    'COM_ATMOS_BUFR',
    'COM_ATMOS_ANALYSIS',
    'COM_OBS',
    'COM_OCEAN_HISTORY',
    'COM_ICE_HISTORY',
    'COM_WAVE_GRID',
  ],
  
  temporal: [
    'NET',        // Network identifier
    'RUN',        // Run identifier
    'PDY',        // Processing date
    'cyc',        // Cycle hour
    'CDATE',      // Full cycle datetime
  ]
};
```

---

## Implementation Plan

### Phase 20A: COM Pattern Library

**File**: `mcp_server_node/src/ee2/com_patterns.js`

Centralized COM pattern definitions extracted from EE2 standards.

### Phase 20B: COM Analyzer Module

**File**: `mcp_server_node/src/ee2/COMAnalyzer.js`

```javascript
class COMAnalyzer {
  constructor(patterns = COM_NAMING_PATTERNS) {
    this.patterns = patterns;
  }

  /**
   * Analyze content for COM compliance
   * @param {ResolvedContent} resolved - From ContentResolver
   * @param {Object} options - Analysis options
   */
  async analyze(resolved, options = {}) {
    const { analysis_type = 'full', context = {} } = options;
    
    const results = {
      score: 0,
      maxScore: 0,
      findings: [],
      recommendations: []
    };

    if (resolved.contentType === 'directory_listing') {
      // Analyze actual file names
      this.analyzeDirectoryListing(resolved.content, context, results);
    } else {
      // Analyze code patterns
      this.analyzeScriptPatterns(resolved.content, context, results);
    }

    results.score = Math.round((results.score / results.maxScore) * 100);
    return results;
  }

  analyzeDirectoryListing(listing, context, results) {
    const files = listing.split('\n').filter(f => f.trim());
    
    for (const file of files) {
      results.maxScore += 1;
      const match = this.matchPattern(file);
      
      if (match.valid) {
        results.score += 1;
      } else {
        results.findings.push({
          severity: 'error',
          category: 'output_naming',
          file: file,
          expected: match.expected,
          reason: match.reason,
          ee2_reference: 'Section 4.2: Output File Naming'
        });
      }
    }
  }

  analyzeScriptPatterns(content, context, results) {
    // Check variable usage
    this.checkVariableUsage(content, results);
    
    // Check path construction
    this.checkPathConstruction(content, results);
    
    // Check for anti-patterns
    this.checkAntiPatterns(content, results);
  }

  // ... additional methods
}
```

### Phase 20C: MCP Tool Integration

**File**: `mcp_server_node/src/tools/EE2ComplianceTools.js`

Add `analyze_com_compliance` tool using ContentResolver and COMAnalyzer.

### Phase 20D: ChromaDB Integration

Ingest COM-specific documentation into dedicated collection for RAG-enhanced guidance.

---

## Tool Response Format

```javascript
{
  compliance_score: 87,
  summary: "23/26 patterns compliant",
  source: "repo_code",
  context: { NET: "gfs", cyc: "00" },
  
  findings: [
    {
      severity: "error",        // error, warning, info
      category: "output_naming",
      location: "line 145",
      pattern: "gfs_output.grb2",
      expected: "gfs.t00z.pgrb2.0p25.f000.grib2",
      reason: "Missing cycle time and forecast hour in filename",
      ee2_reference: "Section 4.2: Output File Naming"
    },
    {
      severity: "warning",
      category: "path_construction",
      location: "line 89",
      pattern: "$COMOUT/gfs",
      expected: "${COMOUT}/${NET}",
      reason: "Use braces around variable names",
      ee2_reference: "Section 3.1: Variable Usage"
    }
  ],
  
  recommendations: [
    "Use ${VAR} syntax instead of $VAR for all COM variables",
    "Follow naming: ${NET}.t${cyc}z.${product}.${grid}.f${fhr}",
    "Ensure COMOUT is set via J-job, not hardcoded"
  ],
  
  patterns_checked: {
    output_naming: { passed: 20, failed: 3, skipped: 0 },
    path_construction: { passed: 15, failed: 2, skipped: 0 },
    variable_usage: { passed: 8, failed: 1, skipped: 0 }
  }
}
```

---

## Usage Examples

### Example 1: Check Live COM Directory

```javascript
// VS Code reads directory listing locally
const listing = await run_in_terminal("ls -1 $COMOUT/");

// Pass to MCP tool
analyze_com_compliance({
  content: listing,
  content_type: "directory_listing",
  analysis_type: "output_naming",
  context: { NET: "gfs", RUN: "gfs", PDY: "20251218", cyc: "00" },
  source: "live_com"
})
```

### Example 2: Check Script Code

```javascript
// Read script from repo
const script = await read_file("scripts/exgfs_atmos_products.sh");

analyze_com_compliance({
  content: script,
  content_type: "script",
  analysis_type: "path_construction",
  context: { NET: "gfs" },
  source: "repo_code"
})
```

### Example 3: Batch Analysis from CI

```javascript
analyze_com_compliance({
  files: [
    { name: "JGFS_ATMOS_PRODUCTS", path: "jobs/JGFS_ATMOS_PRODUCTS", content: "..." },
    { name: "exgfs_atmos_products.sh", path: "scripts/exgfs_atmos_products.sh", content: "..." }
  ],
  analysis_type: "full",
  source: "ci_output"
})
```

### Example 4: Compare Code vs Live Output

```javascript
// Two-step analysis
const codeResult = await analyze_com_compliance({
  content: scriptContent,
  content_type: "script",
  analysis_type: "output_naming"
});

const liveResult = await analyze_com_compliance({
  content: directoryListing,
  content_type: "directory_listing",
  analysis_type: "output_naming",
  context: runtimeContext
});

// Compare findings between code patterns and actual output
```

---

## Validation Criteria

### Unit Tests

- [ ] COM_NAMING_PATTERNS correctly match valid filenames
- [ ] COM_NAMING_PATTERNS reject invalid filenames
- [ ] Path construction checks identify anti-patterns
- [ ] Variable usage checks flag missing braces
- [ ] Context substitution validates against provided values

### Integration Tests

- [ ] Tool works via Docker MCP Gateway with content parameter
- [ ] Batch file analysis produces aggregated report
- [ ] Directory listing analysis extracts filenames correctly
- [ ] Script analysis identifies COM-related code sections

### Compliance Tests

- [ ] Run against known-compliant GFS scripts (expect high score)
- [ ] Run against known-issue scripts (expect specific findings)
- [ ] Run against sample COMOUT listing (validate patterns)

---

## Dependencies

- **Phase 19**: Content Abstraction Layer (ContentResolver)
- **ChromaDB**: EE2 standards collection for RAG context
- **EE2 Standards**: Reference documentation ingested

## Timeline

| Step | Duration | Deliverable |
|------|----------|-------------|
| 20A  | 3 hours  | COM pattern library |
| 20B  | 4 hours  | COMAnalyzer module |
| 20C  | 3 hours  | MCP tool integration |
| 20D  | 2 hours  | ChromaDB integration |
| Test | 4 hours  | Validation suite |

**Total**: ~16 hours

---

## Future Enhancements

- **COM Diff Tool**: Compare COM outputs between versions/runs
- **Template Generator**: Generate compliant COM path code from context
- **CI Gate**: Block PRs with COM compliance score below threshold
- **Historical Analysis**: Track COM compliance trends over time

---

## Related SDDs

- Phase 19: Content Abstraction Layer (prerequisite)
- Phase 4C: Code Snippet Extractor (integration point)
- EE2 Enhanced Embeddings Workflow (COM documentation ingestion)
