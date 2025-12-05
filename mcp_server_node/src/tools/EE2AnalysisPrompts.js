/**
 * EE2AnalysisPrompts - LLM prompt templates for EE2 compliance analysis
 * 
 * These prompts are returned to the host LLM (Copilot/Claude) in
 * passthrough mode for reasoning over extracted code snippets.
 * 
 * @version 1.0.0
 * @phase 4C
 * @author AI Assistant + Terry McGuinness
 * @created 2025-12-05
 */

/**
 * EE2 Analysis Prompts by Category
 * Each prompt includes:
 * - context: Background information for the LLM
 * - instruction: Specific analysis to perform
 * - sme_corrections: Known false-positive corrections from domain experts
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
 * @param {string} category - Analysis category
 * @param {Object[]} snippets - Extracted code snippets
 * @returns {Object} Formatted prompt for LLM
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

/**
 * Get available analysis categories
 * @returns {string[]} List of category names
 */
export function getAvailableCategories() {
  return Object.keys(EE2_ANALYSIS_PROMPTS);
}

/**
 * Get category description for help text
 * @param {string} category - Category name
 * @returns {string} Short description
 */
export function getCategoryDescription(category) {
  const descriptions = {
    output_file_naming: 'Analyze output file naming conventions',
    error_handling: 'Check error handling patterns (set -x, err_chk)',
    shebang_compliance: 'Verify shebang and script header',
    env_var_validation: 'Check environment variable usage'
  };
  return descriptions[category] || 'Unknown category';
}

export default EE2_ANALYSIS_PROMPTS;
