# SDD: Phase 4C - Code Snippet Extractor with LLM Passthrough

**Version:** 1.1.0  
**Created:** 2025-12-05  
**Updated:** 2025-12-18  
**Author:** AI Assistant + Terry McGuinness  
**Status:** ✅ IMPLEMENTED  
**Priority:** HIGH  
**Prerequisite:** Phase 4B (Interactive Supervised Execution) ✅ COMPLETE

---

## Implementation Status

| Step | Description | Status |
|------|-------------|--------|
| Step 1 | CodeSnippetExtractor.js module | ✅ Complete |
| Step 2 | EE2AnalysisPrompts.js | ✅ Complete |
| Step 3 | Register extract_code_for_analysis tool | ✅ Complete |
| Step 4 | Integration with EE2ComplianceTools | ✅ Complete |
| Step 5 | Syntax validation | ✅ Complete |
| Step 6 | Auto passthrough on full reports | ✅ Complete (2025-12-18) |

### Step 6 Implementation Notes (2025-12-18)
- Updated `scan_repository_compliance` to emit **MANDATORY ACTION** directive
- LLM instructions now explicitly require calling `extract_code_for_analysis`
- Provides exact tool call syntax with repository path pre-filled
- Includes checklist of file naming patterns to verify
- Tested with EVS repository scan - passthrough mechanism works correctly

---

## 1. Description

Implement the **CodeSnippetExtractor** module and **extract_code_for_analysis** MCP tool that:
1. Takes files on disk (local repo path)
2. Extracts relevant code patterns for EE2 compliance analysis
3. Returns structured data with LLM instructions for the host LLM to perform further analysis

**Key Innovation**: Passthrough mode - we don't call external LLM APIs. We return snippets + prompts for the calling LLM (Copilot/Claude) to reason over.

---

## 2. Scope Boundaries

### IN SCOPE (Build Now)
- `CodeSnippetExtractor.js` - Pattern extraction from shell/Python files
- `extract_code_for_analysis` MCP tool - New tool for EE2ComplianceTools
- Passthrough LLM mode - Return prompts for host LLM
- Auto prompt emission on "full" EE2 report requests to run passthrough (`extract_code_for_analysis`) for COM/COMOUT output-file naming, shebang, and env validation

### OUT OF SCOPE (Future)
- GitHub/GitLab URL cloning
- PR/MR file fetching
- External LLM API calls (Gemini, Claude API, OpenAI)
- CI/CD integration
- COM output directory scanning (full filesystem crawl) — instead, we emit a passthrough directive to run targeted extraction

### PLANNED ENHANCEMENT: COM Output Path Direct Analysis
**Status:** Not yet implemented  
**Target:** Phase 4D or later

When a COM output directory is available (e.g., `/lfs/h2/emc/ptmp/User.Name/com/evs/v1.0/`), enable direct file pattern and name analysis:

1. **Input Option:** Accept `com_output_path` parameter in scan tools
2. **Direct Crawl:** List actual output files in COM directory structure
3. **Pattern Validation:** Compare actual filenames against EE2 naming rules:
   - Period separators between categories
   - Resolution notation (0p25 not 0.25)
   - Forecast hour padding (f006 not f6)
   - No uppercase characters
4. **Advantage:** No code parsing needed - analyze actual production output

This bypasses the passthrough mechanism when real output is available, providing definitive compliance verification.

---

## 3. Implementation Steps

### Step 1: Create CodeSnippetExtractor Module
**Type:** code_generation  
**Target:** mcp_server_node/src/tools/CodeSnippetExtractor.js  
**Validation:** `node --check` passes

```javascript
/**
 * CodeSnippetExtractor - Extract code patterns for LLM analysis
 * 
 * Extracts relevant code snippets from shell/Python files for
 * EE2 compliance analysis. Returns structured data suitable for
 * LLM reasoning in passthrough mode.
 * 
 * @version 1.0.0
 * @phase 4C
 */

import fs from 'fs';
import path from 'path';

// Regex patterns for extraction
const PATTERNS = {
  // Output file patterns - $COMOUT assignments, cp/mv to COM
  output: [
    /\$COMOUT\s*[=\/][^\n]*/g,
    /COMOUT=\$\{[^}]+\}[^\n]*/g,
    /cp\s+[^\n]*\$COM[^\n]*/g,
    /mv\s+[^\n]*\$COM[^\n]*/g,
    />\s*\$COM[^\n]*/g,
    /cpreq\s+[^\n]*\$COM[^\n]*/g
  ],
  
  // Error handling patterns
  error_handling: [
    /set\s+-[xueo]+/g,
    /err_chk[^\n]*/g,
    /err_exit[^\n]*/g,
    /exit\s+[01][^\n]*/g,
    /\$\?\s*-ne\s*0[^\n]*/g,
    /if\s*\[\s*\$\?\s*[^\]]+\][^\n]*/g
  ],
  
  // Environment variable patterns
  env_vars: [
    /\$\{[A-Z_]+:\?[^}]*\}/g,
    /\$\{[A-Z_]+:-[^}]*\}/g,
    /export\s+[A-Z_]+=\$\{[^}]+\}/g
  ],
  
  // Shebang and header
  shebang: /^#!\/bin\/(bash|sh|ksh)[^\n]*/
};

export class CodeSnippetExtractor {
  constructor(options = {}) {
    this.maxLines = options.maxLines || 20;
    this.contextLines = options.contextLines || 3;
  }

  /**
   * Extract all relevant patterns from a file
   * @param {string} filePath - Path to file
   * @param {string[]} categories - Categories to extract
   * @returns {Object} Extracted snippets with line numbers
   */
  async extractFromFile(filePath, categories = ['output', 'error_handling']) {
    const content = fs.readFileSync(filePath, 'utf-8');
    const lines = content.split('\n');
    const filename = path.basename(filePath);
    
    const result = {
      file: filePath,
      filename,
      fileType: this.detectFileType(filename),
      lineCount: lines.length,
      snippets: {}
    };

    // Extract shebang block (first N lines)
    result.shebangBlock = this.extractShebangBlock(lines);

    // Extract patterns by category
    for (const category of categories) {
      if (PATTERNS[category]) {
        result.snippets[category] = this.extractPatterns(
          content, 
          lines, 
          PATTERNS[category],
          category
        );
      }
    }

    return result;
  }

  /**
   * Extract shebang and header block
   */
  extractShebangBlock(lines) {
    const block = lines.slice(0, this.maxLines);
    const shebangLine = block[0] || '';
    const hasShebang = /^#!/.test(shebangLine);
    const hasSetX = block.some(l => /^\s*set\s+-x/.test(l));
    
    return {
      lines: block,
      shebang: hasShebang ? shebangLine : null,
      shebangType: this.parseShebang(shebangLine),
      hasSetX,
      setXLine: block.findIndex(l => /^\s*set\s+-x/.test(l)) + 1 || null
    };
  }

  /**
   * Parse shebang to identify shell type
   */
  parseShebang(line) {
    if (/^#!\/bin\/bash/.test(line)) return 'bash';
    if (/^#!\/bin\/sh/.test(line)) return 'sh';
    if (/^#!\/bin\/ksh/.test(line)) return 'ksh';
    if (/^#!.*python/.test(line)) return 'python';
    return 'unknown';
  }

  /**
   * Detect file type from name
   */
  detectFileType(filename) {
    if (/^J[A-Z_]+$/.test(filename)) return 'j-job';
    if (/^ex[a-z_]+\.sh$/.test(filename)) return 'ex-script';
    if (/\.sh$/.test(filename)) return 'shell';
    if (/\.py$/.test(filename)) return 'python';
    return 'unknown';
  }

  /**
   * Extract patterns with context
   */
  extractPatterns(content, lines, patterns, category) {
    const matches = [];
    
    for (const pattern of patterns) {
      let match;
      const regex = new RegExp(pattern.source, pattern.flags);
      
      while ((match = regex.exec(content)) !== null) {
        const lineNum = content.substring(0, match.index).split('\n').length;
        const contextStart = Math.max(0, lineNum - this.contextLines - 1);
        const contextEnd = Math.min(lines.length, lineNum + this.contextLines);
        
        matches.push({
          line: lineNum,
          match: match[0].trim(),
          pattern: pattern.source,
          context: lines.slice(contextStart, contextEnd).join('\n')
        });
      }
    }

    // Deduplicate by line number
    const seen = new Set();
    return matches.filter(m => {
      if (seen.has(m.line)) return false;
      seen.add(m.line);
      return true;
    }).sort((a, b) => a.line - b.line);
  }

  /**
   * Extract from multiple files in a directory
   * @param {string} dirPath - Directory path
   * @param {Object} options - Filter options
   */
  async extractFromDirectory(dirPath, options = {}) {
    const {
      pattern = /\.(sh|py)$/,
      categories = ['output', 'error_handling'],
      maxFiles = 100,
      recursive = true
    } = options;

    const files = this.findFiles(dirPath, pattern, recursive, maxFiles);
    const results = [];

    for (const file of files) {
      try {
        const extracted = await this.extractFromFile(file, categories);
        // Only include files with matches
        const hasMatches = Object.values(extracted.snippets)
          .some(arr => arr.length > 0);
        if (hasMatches || extracted.shebangBlock.shebang) {
          results.push(extracted);
        }
      } catch (error) {
        results.push({
          file,
          error: error.message
        });
      }
    }

    return {
      directory: dirPath,
      filesScanned: files.length,
      filesWithMatches: results.filter(r => !r.error).length,
      results
    };
  }

  /**
   * Find files matching pattern
   */
  findFiles(dirPath, pattern, recursive, maxFiles) {
    const files = [];
    
    const scan = (dir) => {
      if (files.length >= maxFiles) return;
      
      const entries = fs.readdirSync(dir, { withFileTypes: true });
      
      for (const entry of entries) {
        if (files.length >= maxFiles) break;
        
        const fullPath = path.join(dir, entry.name);
        
        if (entry.isDirectory() && recursive) {
          // Skip common non-source directories
          if (!['node_modules', '.git', '__pycache__', 'build'].includes(entry.name)) {
            scan(fullPath);
          }
        } else if (entry.isFile() && pattern.test(entry.name)) {
          files.push(fullPath);
        }
      }
    };

    scan(dirPath);
    return files;
  }
}

export default CodeSnippetExtractor;
```

---

### Step 2: Create LLM Prompt Templates
**Type:** code_generation  
**Target:** mcp_server_node/src/tools/EE2AnalysisPrompts.js  
**Validation:** `node --check` passes

```javascript
/**
 * EE2AnalysisPrompts - LLM prompt templates for EE2 compliance analysis
 * 
 * These prompts are returned to the host LLM (Copilot/Claude) in
 * passthrough mode for reasoning over extracted code snippets.
 * 
 * @version 1.0.0
 * @phase 4C
 */

export const EE2_ANALYSIS_PROMPTS = {
  output_file_naming: {
    context: `EE2 Output File Naming Requirements:
- Use periods (.) to separate categories
- Use underscores (_) to separate words within same category
- Resolution notation: 0p25 not 0.25
- Forecast hours: f006 not f6 (padded, with 'f' prefix)
- NO uppercase characters in output filenames
- NO embedded dates (date goes in directory path)
- NO special characters except . and _
- NO $job, $envir, $model_ver in final filenames`,
    
    instruction: `Analyze the output pattern snippets. For each COMOUT assignment or cp/mv to COM:
1. Identify the final output filename pattern
2. Check for uppercase characters (VIOLATION if present)
3. Check for embedded dates like YYYYMMDD (VIOLATION if in filename, OK if in path)
4. Check separator usage (periods between categories, underscores within)
5. Check forecast hour format (should be f### like f006)
6. Check resolution format (should use 'p' like 0p25)

Report: COMPLIANT or list specific violations with line numbers.`,
    
    sme_corrections: [
      "Uppercase in VARIABLE NAMES (e.g., MODEL=GFS) is NOT a violation",
      "Only the FINAL resolved filename matters, not intermediate variables",
      "RTOFS has legacy mixed-case in production - flag but note exception",
      "Date in DIRECTORY path ($COMOUT/model.YYYYMMDD/) is COMPLIANT"
    ]
  },

  error_handling: {
    context: `EE2 Error Handling Requirements:
- set -x REQUIRED after shebang for debug logging
- set -eu is NOT required (NOT in EE2 standards)
- Use err_chk after critical operations
- Use err_exit for fatal errors (NOT explicit exit 0/1)
- err_chk and err_exit are production utilities`,
    
    instruction: `Analyze the error handling snippets:
1. Check if 'set -x' is present after shebang (REQUIRED)
2. Do NOT flag missing 'set -e' or 'set -eu' (not required)
3. Check for 'exit 0' or 'exit 1' usage (should use err_exit instead)
4. Check for err_chk after cp, mv, or script calls
5. Note any gaps where err_chk should be added

Report: List compliant patterns and violations with line numbers.`,
    
    sme_corrections: [
      "set -eu is NOT in EE2 standards - do NOT flag as missing",
      "Only set -x is required for debug logging",
      "exit 0/1 should be err_exit, but some legacy patterns exist",
      "Files using err_chk/err_exit ARE compliant even without set -e"
    ]
  },

  shebang_compliance: {
    context: `EE2 Shebang Requirements:
- Shebang MUST be on line 1 (no blank lines before)
- Valid shells: #!/bin/bash, #!/bin/sh, #!/bin/ksh
- #!/bin/ksh IS allowed for J-jobs (NCO standard)
- set -x should follow shortly after shebang`,
    
    instruction: `Check the shebang block:
1. Is shebang on line 1? (blank line before = VIOLATION)
2. Is shell type valid? (bash, sh, ksh all OK)
3. Is set -x present in first 10 lines?
4. For J-jobs: Is PS4 export present for timing?

Report: Shebang compliance status with any issues.`,
    
    sme_corrections: [
      "#!/bin/ksh IS allowed - do NOT flag as non-portable",
      "All of bash, sh, ksh are valid on WCOSS2",
      "J-jobs should have: export PS4='+ $SECONDS + '"
    ]
  },

  env_var_validation: {
    context: `EE2 Environment Variable Requirements:
- Required vars must use \${VAR:?} for fail-fast
- Optional vars should use \${VAR:-default}
- Standard vars: PDY, cyc, NET, RUN, COMROOT, etc.`,
    
    instruction: `Check environment variable usage:
1. Are required variables validated with :?
2. Are optional variables using :- for defaults
3. Are standard EE2 variables used correctly

Report: Environment variable compliance.`,
    
    sme_corrections: [
      "Not all variables need :? validation",
      "Focus on critical path variables (COMOUT, DATA, etc.)"
    ]
  }
};

/**
 * Generate analysis prompt for host LLM
 */
export function generateAnalysisPrompt(category, snippets) {
  const template = EE2_ANALYSIS_PROMPTS[category];
  if (!template) {
    return { error: `Unknown category: ${category}` };
  }

  return {
    category,
    context: template.context,
    instruction: template.instruction,
    sme_corrections: template.sme_corrections,
    code_snippets: snippets,
    output_format: `Provide analysis as:
## ${category} Analysis

### Compliant Patterns
- [list compliant items with line numbers]

### Violations Found
- [list violations with line numbers and specific issue]

### Recommendations
- [specific fixes needed]`
  };
}

export default EE2_ANALYSIS_PROMPTS;
```

---

### Step 3: Add extract_code_for_analysis Tool
**Type:** code_modification  
**File:** mcp_server_node/src/tools/EE2ComplianceTools.js  
**Action:** Add new tool registration and handler

**New Tool Schema:**
```javascript
{
  name: 'extract_code_for_analysis',
  description: 'Extract code snippets from files for EE2 compliance analysis. Returns structured data with LLM prompts for the host LLM to perform detailed analysis.',
  inputSchema: {
    type: 'object',
    properties: {
      path: {
        type: 'string',
        description: 'Path to file or directory to analyze'
      },
      categories: {
        type: 'array',
        items: { 
          type: 'string',
          enum: ['output_file_naming', 'error_handling', 'shebang_compliance', 'env_var_validation']
        },
        description: 'Analysis categories to extract patterns for',
        default: ['output_file_naming', 'error_handling']
      },
      file_pattern: {
        type: 'string',
        description: 'Regex pattern for files to include (default: \\.(sh|py)$)',
        default: '\\.(sh|py)$'
      },
      max_files: {
        type: 'number',
        description: 'Maximum files to scan',
        default: 50
      }
    },
    required: ['path']
  }
}
```

**Handler Implementation:**
```javascript
async extractCodeForAnalysis(args) {
  const { 
    path: inputPath, 
    categories = ['output_file_naming', 'error_handling'],
    file_pattern = '\\.(sh|py)$',
    max_files = 50
  } = args;

  // Map category names to extractor categories
  const extractorCategories = categories.map(c => {
    if (c === 'output_file_naming') return 'output';
    if (c === 'shebang_compliance') return 'shebang';
    if (c === 'env_var_validation') return 'env_vars';
    return c.replace('_compliance', '');
  });

  const extractor = new CodeSnippetExtractor();
  
  let extracted;
  if (fs.statSync(inputPath).isDirectory()) {
    extracted = await extractor.extractFromDirectory(inputPath, {
      pattern: new RegExp(file_pattern),
      categories: extractorCategories,
      maxFiles: max_files
    });
  } else {
    extracted = await extractor.extractFromFile(inputPath, extractorCategories);
  }

  // Generate LLM prompts for each category
  const llmPrompts = {};
  for (const category of categories) {
    llmPrompts[category] = generateAnalysisPrompt(
      category,
      extracted.results || [extracted]
    );
  }

  // Format response
  let output = `# Code Extraction for EE2 Analysis\n\n`;
  output += `**Path:** ${inputPath}\n`;
  output += `**Categories:** ${categories.join(', ')}\n`;
  
  if (extracted.filesScanned) {
    output += `**Files Scanned:** ${extracted.filesScanned}\n`;
    output += `**Files with Matches:** ${extracted.filesWithMatches}\n`;
  }
  output += `\n---\n\n`;

  // Include prompts for host LLM
  output += `## LLM Analysis Instructions\n\n`;
  output += `The following prompts and code snippets are provided for analysis.\n`;
  output += `Please analyze each category using the provided context and SME corrections.\n\n`;

  for (const [category, prompt] of Object.entries(llmPrompts)) {
    output += `### ${category}\n\n`;
    output += `**Context:**\n\`\`\`\n${prompt.context}\n\`\`\`\n\n`;
    output += `**Instruction:**\n${prompt.instruction}\n\n`;
    output += `**SME Corrections (avoid false positives):**\n`;
    for (const correction of prompt.sme_corrections) {
      output += `- ${correction}\n`;
    }
    output += `\n`;
  }

  output += `---\n\n## Extracted Code Snippets\n\n`;
  
  // Include actual snippets
  const results = extracted.results || [extracted];
  for (const result of results.slice(0, 10)) { // Limit output
    if (result.error) continue;
    
    output += `### ${result.filename}\n`;
    output += `**Type:** ${result.fileType} | **Lines:** ${result.lineCount}\n\n`;
    
    if (result.shebangBlock) {
      output += `**Shebang:** ${result.shebangBlock.shebang || 'MISSING'}\n`;
      output += `**set -x:** ${result.shebangBlock.hasSetX ? `Line ${result.shebangBlock.setXLine}` : 'NOT FOUND'}\n\n`;
    }

    for (const [cat, snippets] of Object.entries(result.snippets)) {
      if (snippets.length === 0) continue;
      output += `**${cat} patterns:** ${snippets.length} found\n`;
      for (const snip of snippets.slice(0, 5)) {
        output += `- Line ${snip.line}: \`${snip.match.substring(0, 80)}${snip.match.length > 80 ? '...' : ''}\`\n`;
      }
      output += `\n`;
    }
  }

  if (results.length > 10) {
    output += `\n*... and ${results.length - 10} more files*\n`;
  }

  return { 
    content: [{ type: 'text', text: output }],
    // Also return structured data for programmatic use
    _structured: {
      extracted,
      llmPrompts,
      mode: 'passthrough'
    }
  };
}
```

---

### Step 4: Register Tool in EE2ComplianceTools
**Type:** code_modification  
**File:** mcp_server_node/src/tools/EE2ComplianceTools.js  
**Action:** Add import and tool registration

Add to imports:
```javascript
import { CodeSnippetExtractor } from './CodeSnippetExtractor.js';
import { generateAnalysisPrompt } from './EE2AnalysisPrompts.js';
```

Add to registerWith():
```javascript
// Tool 5: Extract code for LLM analysis (Phase 4C)
server.registerTool(
  'extract_code_for_analysis',
  'Extract code snippets from files for EE2 compliance analysis. Returns structured data with LLM prompts for the host LLM to perform detailed analysis.',
  { /* schema from Step 3 */ },
  this.extractCodeForAnalysis.bind(this)
);
```

---

### Step 5: Validate Implementation
**Type:** command  
**Command:** `cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node && node --check src/tools/CodeSnippetExtractor.js && node --check src/tools/EE2AnalysisPrompts.js && echo "[OK] All syntax checks pass"`

---

### Step 6: Add Auto Passthrough Prompt on Full EE2 Reports ✅ COMPLETE
**Type:** code_modification  
**Files:**
- mcp_server_node/src/tools/EE2ComplianceTools.js (scan/generate paths)

**Action:**
- When `scan_repository_compliance` or `generate_compliance_report` is invoked for a "full" report (categories include file_naming or environment_variables), append a short directive telling the host LLM/user to also run `extract_code_for_analysis` with categories `output_file_naming`, `shebang_compliance`, and `env_var_validation` against the target repo paths. This makes the passthrough step discoverable for novices without an explicit prompt.

**Implementation (2025-12-18):**
- Changed "IMPORTANT: Additional Analysis Required" to "⚠️ MANDATORY ACTION REQUIRED - DO NOT SKIP"
- Added explicit tool call syntax with pre-filled repository path
- Changed language from "LLM should" to "LLM MUST execute"
- Added checklist of file naming patterns to verify in analysis
- Tested with EVS repository - passthrough correctly triggered

**Validation:**
- ✅ `node --check` on EE2ComplianceTools.js passes
- ✅ Manual call of scan with file_naming category confirms MANDATORY directive present

---

## 4. Validation Criteria

- [x] `CodeSnippetExtractor.js` created and syntax valid
- [x] `EE2AnalysisPrompts.js` created with 4 category prompts
- [x] `extract_code_for_analysis` tool registered in EE2ComplianceTools
- [x] Tool accepts path and returns structured snippets + LLM prompts
- [x] SME corrections included in all prompts
- [x] Test with sample shell script shows extracted patterns
- [x] Full-report calls emit passthrough directive to run `extract_code_for_analysis` for COM/COMOUT naming and related checks ✅ (2025-12-18)

---

## 5. Test Command

```bash
# After implementation, test with:
# (via MCP tool call)
extract_code_for_analysis({
  path: "/mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow/scripts",
  categories: ["output_file_naming", "error_handling"],
  max_files: 10
})
```

---

## 6. Estimated Effort

| Component | Effort |
|-----------|--------|
| CodeSnippetExtractor.js | 1.5 hours |
| EE2AnalysisPrompts.js | 1 hour |
| EE2ComplianceTools integration | 1 hour |
| Testing | 0.5 hours |
| **Total** | **~4 hours** |

---

## 7. Dependencies

- Phase 4B Complete ✅ (supervised execution available)
- EE2ComplianceTools.js exists ✅
- fs, path modules (Node.js built-in)
