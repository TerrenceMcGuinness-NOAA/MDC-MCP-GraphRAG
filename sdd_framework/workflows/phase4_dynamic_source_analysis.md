# SDD: Phase 4 - Dynamic Source Analysis with LLM Reasoning

**Version:** 1.0.0  
**Created:** 2025-12-05  
**Author:** AI Assistant + Terry McGuinness  
**Status:** Draft  

---

## 1. Description

Enhance the EE2 compliance tools to support dynamic source input (file paths, URLs, branches) and inject LLM reasoning prompts directly into the analysis pipeline. This enables the MCP server to operate in multiple deployment contexts:

- **Local Development:** VS Code with file paths
- **CI/CD Pipelines:** GitHub Actions / GitLab CI with repository URLs and branch refs
- **Containerized Service:** Standalone analysis service with API endpoints

The key innovation is bridging RAG retrieval with LLM reasoning by including actual code snippets and structured prompts in tool output.

---

## 2. Use Cases

| Context | Input Type | Example |
|---------|------------|---------|
| Local file | Absolute path | `/path/to/repo/scripts/exglobal_*.sh` |
| Local repo | Directory path | `/path/to/EVS` |
| GitHub URL | HTTPS URL | `https://github.com/NOAA-EMC/EVS` |
| GitHub URL + Branch | URL + ref | `https://github.com/NOAA-EMC/EVS@develop` |
| GitHub PR | PR URL | `https://github.com/NOAA-EMC/EVS/pull/123` |
| GitLab URL | HTTPS URL | `https://gitlab.com/org/repo` |
| GitLab MR | MR URL | `https://gitlab.com/org/repo/-/merge_requests/456` |
| COM output path | Directory path | `/lfs/h2/emc/ptmp/User.Name/com/evs/v1.0/` |
| Output file pattern | Glob pattern | `/com/gfs/v16.3/gfs.20251205/*/gfs.t*.pgrb2.*` |

### 2.1 Output File Analysis (Ground Truth Validation)

When a user provides a path to actual output files (COM directory or similar), the tool performs **ground truth validation** - checking the actual filenames that exist on disk rather than inferring from script code.

**Use Cases:**
- Validate production output compliance after a run
- Compare expected vs actual filenames
- Discover naming violations in existing data
- Audit legacy output directories

**Input Detection:**
```
/com/*, /lfs/*/com/*, /ptmp/*/com/*  →  COM output directory
*.grib2, *.nc, *.bufr, *.idx        →  Output file patterns
```

**Analysis Mode:**
- Scan directory recursively for output files
- Check each filename against EE2 naming rules
- Report uppercase chars, special chars, embedded dates
- Group violations by pattern (e.g., all files with same naming issue)

---

## 3. Architecture Changes

### 3.1 Input Parser Module

New module: `src/tools/SourceResolver.js`

```
Input String
    │
    ▼
┌─────────────────────────────────────┐
│         SourceResolver              │
├─────────────────────────────────────┤
│ - detectInputType(input)            │
│ - resolveLocalPath(path)            │
│ - resolveOutputDirectory(path)      │  ← NEW: COM/output paths
│ - cloneGitHubRepo(url, branch)      │
│ - cloneGitLabRepo(url, branch)      │
│ - fetchPRChangedFiles(pr_url)       │
│ - fetchMRChangedFiles(mr_url)       │
│ - discoverOutputFiles(pattern)      │  ← NEW: glob pattern discovery
│ - getWorkingDirectory()             │
└─────────────────────────────────────┘
    │
    ▼
Resolved Local Path (temporary or persistent)
    OR
List of Output Files (for ground truth validation)
```

**Input Type Detection Logic:**
```javascript
function detectInputType(input) {
  // COM/output directories (ground truth validation)
  if (input.match(/\/(com|ptmp|stmp|dcom)\//) || 
      input.match(/\.(grib2|nc|bufr|idx|txt)$/)) {
    return 'output_files';
  }
  // Git forges
  if (input.includes('github.com')) return 'github_url';
  if (input.includes('gitlab.com')) return 'gitlab_url';
  if (input.includes('/pull/')) return 'github_pr';
  if (input.includes('/merge_requests/')) return 'gitlab_mr';
  // Local paths
  if (fs.existsSync(input)) {
    return fs.statSync(input).isDirectory() ? 'local_dir' : 'local_file';
  }
  // Glob pattern
  if (input.includes('*')) return 'glob_pattern';
  return 'unknown';
}
```

### 3.2 Code Snippet Extractor

New module: `src/tools/CodeSnippetExtractor.js`

```
File Path
    │
    ▼
┌─────────────────────────────────────┐
│      CodeSnippetExtractor           │
├─────────────────────────────────────┤
│ - extractOutputPatterns(file)       │  ← COMOUT, cp, mv to COM
│ - extractShebangBlock(file)         │  ← First 20 lines
│ - extractErrorHandling(file)        │  ← err_chk, err_exit usage
│ - extractEnvVarUsage(file)          │  ← ${VAR:?} patterns
│ - extractFunctionDefs(file)         │  ← For call chain analysis
└─────────────────────────────────────┘
    │
    ▼
Structured Code Snippets (for LLM analysis)
```

### 3.3 LLM Abstraction Layer

New module: `src/tools/LLMProvider.js`

The LLM abstraction layer enables the same analysis logic to work across multiple deployment contexts and LLM providers.

```
┌─────────────────────────────────────────────────────────────────┐
│                     LLMProvider Interface                        │
├─────────────────────────────────────────────────────────────────┤
│  analyze(snippets, prompts, options) → Promise<AnalysisResult>  │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│ PassthroughLLM│    │  GeminiLLM    │    │  ClaudeLLM    │
│  (Copilot)    │    │  (API)        │    │  (API)        │
├───────────────┤    ├───────────────┤    ├───────────────┤
│ Returns prompt│    │ google-genai  │    │ @anthropic-ai │
│ for host LLM  │    │ gemini-pro-3  │    │ claude-3-opus │
│ to process    │    │               │    │               │
└───────────────┘    └───────────────┘    └───────────────┘
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  OpenAILLM    │    │  OllamaLLM    │    │  AzureLLM     │
│  (API)        │    │  (Local)      │    │  (Enterprise) │
├───────────────┤    ├───────────────┤    ├───────────────┤
│ gpt-4-turbo   │    │ llama3, etc.  │    │ Azure OpenAI  │
│ gpt-4o        │    │ codellama     │    │ Gov Cloud     │
└───────────────┘    └───────────────┘    └───────────────┘
```

**Provider Interface:**
```javascript
class LLMProvider {
  constructor(config) {
    this.provider = config.provider;  // 'passthrough', 'gemini', 'claude', 'openai', 'ollama', 'azure'
    this.model = config.model;
    this.apiKey = config.apiKey;
    this.endpoint = config.endpoint;  // For Azure/custom endpoints
  }

  /**
   * Analyze code snippets using LLM reasoning
   * @param {Object} snippets - Extracted code snippets
   * @param {Object} prompts - Analysis prompts with SME corrections
   * @param {Object} options - Temperature, max_tokens, etc.
   * @returns {Promise<AnalysisResult>} - Structured analysis output
   */
  async analyze(snippets, prompts, options = {}) {
    throw new Error('Subclass must implement analyze()');
  }

  /**
   * Check if provider is available and configured
   */
  async healthCheck() {
    throw new Error('Subclass must implement healthCheck()');
  }
}
```

**Passthrough Provider (Copilot Mode):**
```javascript
class PassthroughLLM extends LLMProvider {
  /**
   * In Copilot mode, we don't call an API - we return structured
   * data + prompts for the host LLM (Copilot) to process.
   */
  async analyze(snippets, prompts, options) {
    return {
      mode: 'passthrough',
      requires_host_llm: true,
      snippets: snippets,
      analysis_prompts: prompts,
      instruction: 'Host LLM should analyze snippets using provided prompts'
    };
  }
}
```

**API Provider (CI/CD Mode):**
```javascript
class GeminiLLM extends LLMProvider {
  constructor(config) {
    super(config);
    this.client = new GoogleGenerativeAI(config.apiKey);
    this.model = config.model || 'gemini-pro-3';
  }

  async analyze(snippets, prompts, options) {
    const model = this.client.getGenerativeModel({ model: this.model });
    
    const systemPrompt = this.buildSystemPrompt(prompts);
    const userPrompt = this.buildUserPrompt(snippets);
    
    const result = await model.generateContent({
      contents: [{ role: 'user', parts: [{ text: systemPrompt + userPrompt }] }],
      generationConfig: {
        temperature: options.temperature || 0.1,
        maxOutputTokens: options.max_tokens || 4096
      }
    });
    
    return this.parseResponse(result.response.text());
  }
}
```

**Provider Factory:**
```javascript
function createLLMProvider(config) {
  const providers = {
    'passthrough': PassthroughLLM,    // Copilot/VS Code
    'gemini': GeminiLLM,              // Google Gemini Pro 3
    'claude': ClaudeLLM,              // Anthropic Claude
    'openai': OpenAILLM,              // OpenAI GPT-4
    'ollama': OllamaLLM,              // Local Ollama
    'azure': AzureOpenAILLM           // Azure OpenAI (Gov Cloud)
  };
  
  const Provider = providers[config.provider];
  if (!Provider) {
    throw new Error(`Unknown LLM provider: ${config.provider}`);
  }
  return new Provider(config);
}

// Auto-detect from environment
function autoDetectProvider() {
  if (process.env.GOOGLE_API_KEY) return 'gemini';
  if (process.env.ANTHROPIC_API_KEY) return 'claude';
  if (process.env.OPENAI_API_KEY) return 'openai';
  if (process.env.AZURE_OPENAI_ENDPOINT) return 'azure';
  if (process.env.OLLAMA_HOST) return 'ollama';
  return 'passthrough';  // Default: Copilot mode
}
```

**Configuration via Environment:**
```bash
# Gemini Pro 3 (preferred for CI/CD)
export LLM_PROVIDER=gemini
export GOOGLE_API_KEY=your-key
export LLM_MODEL=gemini-pro-3

# Claude (alternative)
export LLM_PROVIDER=claude
export ANTHROPIC_API_KEY=your-key
export LLM_MODEL=claude-3-opus-20240229

# Azure OpenAI (enterprise/gov)
export LLM_PROVIDER=azure
export AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
export AZURE_OPENAI_KEY=your-key
export LLM_MODEL=gpt-4-turbo

# Local Ollama (air-gapped)
export LLM_PROVIDER=ollama
export OLLAMA_HOST=http://localhost:11434
export LLM_MODEL=codellama:34b
```

### 3.4 LLM Prompt Injection

Enhanced tool output format:

```json
{
  "scan_metadata": {
    "source_type": "github_url",
    "source": "https://github.com/NOAA-EMC/EVS",
    "branch": "develop",
    "commit": "abc123",
    "scan_date": "2025-12-05T20:00:00Z"
  },
  "file_analysis": [
    {
      "file": "scripts/prep/rtofs/exevs_prep_rtofs.sh",
      "code_snippets": {
        "output_patterns": [
          {"line": 45, "code": "cp ${DATA}/rtofs.${PDY}.nc $COMOUT/rtofs.t${cyc}z.nc"},
          {"line": 67, "code": "COMOUT=${COMROOT}/evs/${evs_ver}/rtofs.${PDY}"}
        ],
        "shebang_block": "#!/bin/bash\nset -x\n...",
        "error_handling": [
          {"line": 89, "code": "if [ $err -ne 0 ]; then err_exit 'Failed'; fi"}
        ]
      }
    }
  ],
  "llm_analysis_prompts": {
    "output_file_naming": {
      "context": "EE2 requires lowercase output filenames, no special chars except . and _, no embedded dates",
      "instruction": "Analyze the output_patterns snippets above. For each, determine: (1) Is the output filename compliant? (2) Are there uppercase chars? (3) Are there embedded dates? (4) Is the separator usage correct (. for categories, _ for words)?",
      "sme_corrections": [
        "Uppercase in variable names (e.g., MODEL=GFS) is NOT a violation",
        "Only the FINAL resolved filename matters, not intermediate variables",
        "RTOFS has legacy mixed-case in production - flag but don't block"
      ]
    },
    "error_handling": {
      "context": "EE2 requires set -x for debug logging, err_chk/err_exit for error handling",
      "instruction": "Check if set -x is present after shebang. Check if error handling uses err_chk/err_exit (compliant) vs exit 0/1 (non-compliant).",
      "sme_corrections": [
        "set -eu is NOT required by EE2",
        "Only set -x is mandatory for debug logging"
      ]
    }
  }
}
```

---

## 4. Implementation Steps

### Step 1: Create SourceResolver Module

**File:** `mcp_server_node/src/tools/SourceResolver.js`

**Functions:**
- `detectInputType(input)` - Returns: `local_file`, `local_dir`, `output_files`, `github_url`, `github_pr`, `gitlab_url`, `gitlab_mr`
- `resolveSource(input, options)` - Returns: `{ workDir, cleanup, metadata }`
- `resolveOutputDirectory(path)` - Returns: `{ files, metadata }` for COM paths
- `discoverOutputFiles(pattern)` - Glob-based file discovery
- `cloneRepo(url, branch, shallow)` - Clones to temp dir, returns path
- `fetchPRFiles(owner, repo, pr_number)` - Uses GitHub API to get changed files
- `cleanup(workDir)` - Removes temp directories

**Dependencies:**
- `simple-git` for git operations
- `@octokit/rest` for GitHub API (already in package.json)
- `glob` for pattern matching
- Temp directory management

### Step 2: Create CodeSnippetExtractor Module

**File:** `mcp_server_node/src/tools/CodeSnippetExtractor.js`

**Functions:**
- `extractOutputPatterns(filePath)` - Regex for COMOUT, cp, mv patterns
- `extractShebangBlock(filePath, lines=20)` - First N lines
- `extractErrorHandling(filePath)` - err_chk, err_exit, set -x patterns
- `extractEnvVarUsage(filePath)` - ${VAR:?}, ${VAR:-default} patterns
- `analyzeOutputFilenames(files)` - Check actual filenames against EE2 rules

**Regex Patterns:**
```javascript
const OUTPUT_PATTERNS = [
  /\$COMOUT\s*[=\/]/,
  /cp\s+.*\$COM/,
  /mv\s+.*\$COM/,
  />\s*\$COM/,
  /COMROOT.*=/
];

const ERROR_PATTERNS = [
  /err_chk/,
  /err_exit/,
  /set\s+-x/,
  /set\s+-eu?/,
  /exit\s+[01]/
];

const FILENAME_VIOLATIONS = [
  /[A-Z]/,                    // Uppercase characters
  /[^a-z0-9._-]/,             // Special characters (except . _ -)
  /\d{8}/,                    // Embedded dates (YYYYMMDD)
  /\d{6}/                     // Embedded dates (YYMMDD)
];
```

### Step 3: Create LLM Provider Abstraction

**File:** `mcp_server_node/src/tools/LLMProvider.js`

**Classes:**
- `LLMProvider` - Base interface
- `PassthroughLLM` - Copilot/VS Code mode (returns prompts for host LLM)
- `GeminiLLM` - Google Gemini Pro 3 API
- `ClaudeLLM` - Anthropic Claude API
- `OpenAILLM` - OpenAI GPT-4 API
- `OllamaLLM` - Local Ollama models
- `AzureOpenAILLM` - Azure OpenAI (Gov Cloud)

**Factory Function:**
- `createLLMProvider(config)` - Returns appropriate provider instance
- `autoDetectProvider()` - Detect from environment variables

**Dependencies:**
- `@google/generative-ai` for Gemini
- `@anthropic-ai/sdk` for Claude
- `openai` for OpenAI/Azure
- Native fetch for Ollama

### Step 4: Update EE2ComplianceTools.scanRepositoryCompliance

**Changes:**
1. Accept `source` parameter (path OR URL)
2. Use SourceResolver to get working directory
3. Use CodeSnippetExtractor to get actual code
4. Include snippets in output JSON
5. Include LLM analysis prompts with SME corrections

### Step 4: Add CI/CD Environment Detection

**Environment Variables to Check:**
```javascript
const CI_ENVIRONMENTS = {
  github_actions: process.env.GITHUB_ACTIONS === 'true',
  gitlab_ci: process.env.GITLAB_CI === 'true',
  jenkins: !!process.env.JENKINS_URL,
  container: !!process.env.CONTAINER_MODE
};
```

**Behavior Adjustments:**
- In CI: Output JSON only (no markdown formatting)
- In CI: Return exit codes for pass/fail
- In CI: Support `--strict` mode for blocking violations

### Step 5: Update Tool Schema

```javascript
{
  name: 'scan_repository_compliance',
  description: 'Scan repository for EE2 compliance. Accepts local path, GitHub URL, or PR URL.',
  inputSchema: {
    type: 'object',
    properties: {
      source: {
        type: 'string',
        description: 'Local path, GitHub URL (with optional @branch), or PR URL'
      },
      branch: {
        type: 'string',
        description: 'Branch to analyze (if not specified in URL)'
      },
      categories: {
        type: 'array',
        items: { type: 'string' },
        description: 'Compliance categories to check'
      },
      include_snippets: {
        type: 'boolean',
        default: true,
        description: 'Include code snippets for LLM analysis'
      },
      ci_mode: {
        type: 'boolean',
        default: false,
        description: 'Output JSON only, return exit codes'
      }
    },
    required: ['source']
  }
}
```

---

## 5. Validation Criteria

### Step 1 Complete When:
- [ ] `SourceResolver.detectInputType()` correctly identifies all input types
- [ ] GitHub URLs clone successfully to temp directory
- [ ] PR URLs fetch only changed files
- [ ] Cleanup removes temp directories

### Step 2 Complete When:
- [ ] `extractOutputPatterns()` finds COMOUT assignments
- [ ] `extractShebangBlock()` returns first 20 lines
- [ ] `extractErrorHandling()` identifies err_chk/err_exit usage
- [ ] Snippets include line numbers

### Step 3 Complete When:
- [ ] Tool accepts both path and URL inputs
- [ ] Output JSON includes `code_snippets` for each file
- [ ] Output includes `llm_analysis_prompts` with SME corrections
- [ ] LLM can analyze snippets and identify violations

### Step 4 Complete When:
- [ ] CI environment auto-detected
- [ ] JSON-only output in CI mode
- [ ] Exit codes returned (0=pass, 1=fail)

### Step 5 Complete When:
- [ ] Updated schema in tool definition
- [ ] VS Code recognizes new parameters
- [ ] Backward compatible with existing calls

---

## 6. Testing Plan

### Unit Tests
- `test/SourceResolver.test.js` - Input type detection, URL parsing
- `test/CodeSnippetExtractor.test.js` - Pattern extraction accuracy

### Integration Tests
- Local path scan (existing behavior)
- GitHub URL scan (new)
- GitHub PR scan (new)
- CI mode output format

### Manual Validation
- Run against EVS repository via URL
- Run in GitHub Action (test workflow)
- Verify LLM can analyze returned snippets

---

## 7. CI/CD Integration Examples

### GitHub Action Usage

```yaml
name: EE2 Compliance Check
on: [pull_request]

jobs:
  compliance:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Run EE2 Compliance Scan
        uses: noaa-emc/mcp-ee2-action@v1
        with:
          source: ${{ github.event.pull_request.html_url }}
          categories: error_handling,file_naming
          strict: true  # Fail on violations
```

### GitLab CI Usage

```yaml
ee2_compliance:
  stage: test
  image: noaa-emc/mcp-ee2:latest
  script:
    - mcp-ee2-scan --source $CI_MERGE_REQUEST_URL --ci-mode
  rules:
    - if: $CI_MERGE_REQUEST_ID
```

---

## 8. Future Extensions

- **Phase 4B:** Auto-fix suggestions with code patches
- **Phase 4C:** Integration with GitHub Check Runs API
- **Phase 4D:** Caching layer for repeated scans
- **Phase 4E:** Multi-repo batch scanning

---

## 9. Dependencies

| Package | Purpose | Version |
|---------|---------|---------|
| `simple-git` | Git clone/operations | ^3.x |
| `@octokit/rest` | GitHub API | existing |
| `tmp-promise` | Temp directory management | ^3.x |
| `glob` | File pattern matching | ^10.x |
| `@google/generative-ai` | Gemini Pro 3 API | ^0.21.x |
| `@anthropic-ai/sdk` | Claude API | ^0.30.x |
| `openai` | OpenAI/Azure API | ^4.x |

**Note:** LLM provider packages are optional - only install what you need:
```bash
# For Gemini (recommended for CI/CD)
npm install @google/generative-ai

# For Claude
npm install @anthropic-ai/sdk

# For OpenAI/Azure
npm install openai

# Ollama uses native fetch - no package needed
```

---

## 10. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Large repos slow to clone | High latency | Shallow clone (--depth 1) |
| GitHub API rate limits | Scan failures | Token auth, caching |
| Temp directory cleanup failure | Disk space | Periodic cleanup job |
| Snippet extraction misses patterns | False negatives | Configurable regex, SME review |

---

**Next Steps:**
1. Review and approve SDD
2. Create SourceResolver module (Step 1)
3. Create CodeSnippetExtractor module (Step 2)
4. Update EE2ComplianceTools (Step 3-5)
5. Add tests and validate
