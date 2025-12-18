# Phase 19: Content Abstraction Layer for MCP Tools

**Status**: PLANNED  
**Created**: December 18, 2025  
**Author**: Terrence McGuinness  
**Priority**: HIGH - Enables remote MCP Gateway usage with local file access

---

## Problem Statement

MCP tools that require file system access fail when running through Docker MCP Gateway because:

1. **Remote Gateway** runs on AWS EC2 instance
2. **Local Workspace** exists on HPC systems (Hercules, Hera, etc.)
3. **No filesystem bridge** exists between them

Current tools like `scan_repository_compliance`, `extract_code_for_analysis`, and `validate_sdd_compliance` use path-based parameters that only work when the MCP server has direct filesystem access.

### Current Architecture (Broken for Remote)

```
┌─────────────────────────┐         ┌──────────────────────────────────┐
│  VS Code on Hercules    │   SSH   │  Docker MCP Gateway (AWS EC2)    │
│  /work2/noaa/global/    │ ──────► │  localhost:8888/mcp              │
│  mterry/global-workflow │ tunnel  │  Can only access files INSIDE    │
│                         │         │  the Docker container            │
└─────────────────────────┘         └──────────────────────────────────┘
      ▲                                        ▲
      │ LOCAL FILES                            │ REMOTE FILES
      │ [OK] Accessible by VS Code             │ /mcp_rag_eib/...
      │ [ERROR] NOT accessible by MCP Gateway  │ [OK] Accessible by MCP
```

---

## Solution: Content Abstraction Layer

Modify MCP tools to accept **content directly** instead of (or in addition to) **file paths**, creating a universal interface that works regardless of deployment topology.

### Target Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    CONTENT ABSTRACTION LAYER                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  analyze_ee2_compliance({ content: "..." })                         │
│                           ▲                                         │
│                           │                                         │
│         ┌─────────────────┼─────────────────┐                       │
│         │                 │                 │                       │
│    ┌────┴────┐      ┌─────┴────┐     ┌──────┴─────┐                 │
│    │ Local   │      │ VS Code  │     │  GitHub    │                 │
│    │ File    │      │ read_file│     │  API       │                 │
│    │ System  │      │ Tool     │     │  Fetch     │                 │
│    └─────────┘      └──────────┘     └────────────┘                 │
│                                                                     │
│    Source 1:        Source 2:        Source 3:                      │
│    Docker FS        Remote HPC       Repository                     │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Tool Parameter Schema Updates

### Universal Content Input Schema

All tools that currently accept `path` or `file_path` parameters will be updated to support:

```javascript
{
  // Option A: Content directly provided (preferred for remote)
  content: {
    type: "string",
    description: "Code/text content to analyze directly"
  },
  
  // Option B: Multiple files with content
  files: {
    type: "array",
    items: {
      type: "object",
      properties: {
        name: { type: "string" },      // Filename (for context/reporting)
        path: { type: "string" },      // Relative path (for context)
        content: { type: "string" }    // Actual file content
      }
    },
    description: "Multiple files for batch analysis"
  },
  
  // Option C: Path (only works with local filesystem access)
  path: {
    type: "string",
    description: "File path (local mode only - falls back if content not provided)"
  },
  
  // Metadata
  content_type: {
    enum: ["bash", "python", "yaml", "json", "config", "directory_listing", "auto"],
    description: "Content type hint for parser selection"
  },
  
  source_hint: {
    enum: ["local_fs", "vscode_read", "github_api", "user_input", "ci_artifact"],
    description: "Where content originated (for context in reports)"
  }
}
```

---

## Implementation Plan

### Phase 19A: Core Content Resolver Module

**File**: `mcp_server_node/src/utils/ContentResolver.js`

```javascript
/**
 * ContentResolver - Universal content access layer
 * 
 * Resolves content from multiple sources with consistent interface.
 * Enables tools to work with content regardless of origin.
 */
class ContentResolver {
  /**
   * Resolve content from parameters
   * @param {Object} params - Tool parameters
   * @param {string} params.content - Direct content
   * @param {Array} params.files - Array of {name, path, content} objects
   * @param {string} params.path - Filesystem path (fallback)
   * @returns {Promise<ResolvedContent>}
   */
  async resolve(params) {
    // Priority: content > files > path
    if (params.content) {
      return this.fromDirect(params.content, params);
    }
    if (params.files && params.files.length > 0) {
      return this.fromFiles(params.files, params);
    }
    if (params.path) {
      return this.fromPath(params.path, params);
    }
    throw new Error("Either 'content', 'files', or 'path' parameter required");
  }

  async fromDirect(content, params) {
    return {
      type: 'single',
      content: content,
      contentType: params.content_type || this.detectType(content),
      source: params.source_hint || 'direct',
      metadata: { providedDirectly: true }
    };
  }

  async fromFiles(files, params) {
    return {
      type: 'multi',
      files: files.map(f => ({
        name: f.name,
        path: f.path,
        content: f.content,
        contentType: params.content_type || this.detectType(f.content, f.name)
      })),
      source: params.source_hint || 'batch',
      metadata: { fileCount: files.length }
    };
  }

  async fromPath(path, params) {
    // Only works with local filesystem access
    const fs = require('fs').promises;
    try {
      const content = await fs.readFile(path, 'utf8');
      return {
        type: 'single',
        content: content,
        contentType: params.content_type || this.detectType(content, path),
        source: 'local_fs',
        metadata: { originalPath: path }
      };
    } catch (err) {
      throw new Error(`Cannot read path '${path}': ${err.message}. ` +
        `Use 'content' parameter for remote access.`);
    }
  }

  detectType(content, filename = '') {
    if (filename.endsWith('.sh') || content.startsWith('#!/bin/bash'))
      return 'bash';
    if (filename.endsWith('.py') || content.startsWith('#!/usr/bin/env python'))
      return 'python';
    if (filename.endsWith('.yaml') || filename.endsWith('.yml'))
      return 'yaml';
    if (filename.endsWith('.json'))
      return 'json';
    return 'auto';
  }
}

module.exports = { ContentResolver };
```

### Phase 19B: Update Tool Schemas

**Tools to Update**:

| Tool | Current Param | New Params | Priority |
|------|---------------|------------|----------|
| `analyze_ee2_compliance` | `content` (already has!) | Add `files`, `source_hint` | LOW |
| `scan_repository_compliance` | `repository_path` | Add `content`, `files` | HIGH |
| `extract_code_for_analysis` | `path` | Add `content`, `files` | HIGH |
| `validate_sdd_compliance` | `target` (path) | Add `content` | MEDIUM |
| `analyze_code_structure` | `file_path` | Add `content` | MEDIUM |

### Phase 19C: Tool Implementation Updates

**Example Update for `scan_repository_compliance`**:

```javascript
// BEFORE (path-only)
async function scanRepositoryCompliance(params) {
  const { repository_path, categories } = params;
  const files = await scanDirectory(repository_path);
  // ... analyze files
}

// AFTER (content abstraction)
async function scanRepositoryCompliance(params) {
  const resolver = new ContentResolver();
  const resolved = await resolver.resolve(params);
  
  let files;
  if (resolved.type === 'multi') {
    // Content provided directly - use it
    files = resolved.files;
  } else if (resolved.type === 'single') {
    // Single content block (e.g., concatenated or manifest)
    files = [{ name: 'input', content: resolved.content }];
  } else {
    // Fallback to path scanning (local only)
    files = await scanDirectory(params.repository_path);
  }
  
  // ... analyze files (same logic, different source)
}
```

### Phase 19D: Documentation and Examples

**Usage Patterns**:

```javascript
// Pattern 1: Direct content (works everywhere)
analyze_ee2_compliance({
  content: "#!/bin/bash\nset -x\nexport err=$?\nerr_chk",
  content_type: "bash"
})

// Pattern 2: VS Code reads local, passes to remote MCP
// Step 1: VS Code tool reads file
const content = await read_file("/work2/noaa/.../script.sh");
// Step 2: Pass to MCP gateway
analyze_ee2_compliance({ content: content })

// Pattern 3: Batch analysis of multiple files
scan_repository_compliance({
  files: [
    { name: "JGFS_FORECAST", path: "jobs/JGFS_FORECAST", content: "..." },
    { name: "exgfs_forecast.sh", path: "scripts/exgfs_forecast.sh", content: "..." }
  ],
  categories: ["error_handling", "file_naming"]
})

// Pattern 4: Path (local mode only - backwards compatible)
scan_repository_compliance({
  repository_path: "/local/path/to/repo",
  categories: ["error_handling"]
})
```

---

## Validation Criteria

### Unit Tests

- [ ] ContentResolver resolves direct content
- [ ] ContentResolver resolves file arrays
- [ ] ContentResolver falls back to path when available
- [ ] ContentResolver throws helpful error when path unavailable remotely
- [ ] Type detection works for bash, python, yaml, json

### Integration Tests

- [ ] `analyze_ee2_compliance` works with content parameter via Gateway
- [ ] `scan_repository_compliance` works with files array via Gateway
- [ ] `extract_code_for_analysis` works with content via Gateway
- [ ] Error messages guide users to content parameter when path fails

### End-to-End Test

- [ ] From VS Code on Hercules, read local file, pass to remote MCP Gateway, get analysis results

---

## Dependencies

- None (pure JavaScript implementation)
- Uses existing `fs.promises` for path fallback

## Timeline

| Step | Duration | Deliverable |
|------|----------|-------------|
| 19A  | 2 hours  | ContentResolver module |
| 19B  | 2 hours  | Schema updates for 5 tools |
| 19C  | 4 hours  | Tool implementation updates |
| 19D  | 2 hours  | Documentation and examples |
| Test | 2 hours  | Validation suite |

**Total**: ~12 hours

---

## Benefits

1. **Location Agnostic** - Tools work from any deployment
2. **Source Agnostic** - Content from local FS, GitHub, CI artifacts, user paste
3. **Backwards Compatible** - Path parameter still works locally
4. **Testable** - Easy to unit test with mock content
5. **Pipeline Ready** - Works in CI/CD without filesystem access
6. **Security** - No file path traversal risks with content mode

---

## Related SDDs

- Phase 11: Docker MCP Gateway (provides the remote access pattern)
- Phase 20: COM Compliance Tools (will use this abstraction)
- Phase 4B: Supervised Execution (approval gates work with content)
