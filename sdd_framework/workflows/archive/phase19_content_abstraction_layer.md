# Phase 19: Content Abstraction Layer for MCP Tools

**Status**: COMPLETE (19A-19D Complete, 19E Deferred)  
**Created**: December 18, 2025  
**Updated**: December 19, 2025  
**Author**: Terrence McGuinness  
**Priority**: HIGH - Enables remote MCP Gateway usage with local file access

## Implementation Progress

| Phase | Status | Deliverable |
|-------|--------|-------------|
| 19A | ✅ COMPLETE | ContentResolver.js module + test suite |
| 19B | ✅ COMPLETE | Tool schema updates (validate_sdd_compliance) |
| 19C | ✅ COMPLETE | EE2 tool implementations (extract_code_for_analysis, scan_repository_compliance) |
| 19D | ✅ COMPLETE | Documentation updates |
| 19E | 📅 DEFERRED | ChromaDBManager (multi-developer sync) |

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

## Phase 19E: ChromaDB Database Abstraction Layer

### Problem Statement

The Content Abstraction Layer solves file access, but **vector database topology** creates additional challenges for multi-developer workflows:

1. **Local Development DB** - Each developer needs isolated ChromaDB for experimentation
2. **Shared Gateway DB** - Production/staging RAG data via MCP Gateway  
3. **No Sync Mechanism** - Cannot copy embeddings between environments
4. **Merge Conflicts** - Multiple developers may add to same collections

### Current Database Topology (Discovered)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     CHROMADB DEPLOYMENT TOPOLOGY                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  DEVELOPER LOCAL (localhost:8080)           SHARED GATEWAY (container)      │
│  ┌─────────────────────────────┐            ┌─────────────────────────────┐ │
│  │  chromadb/chroma:latest     │            │  chromadb:v134clean          │ │
│  │  API: v1 only               │            │  API: v2                     │ │
│  │  Collections: 2             │            │  Collections: 12             │ │
│  │  Documents: ~few            │            │  Documents: 14,856           │ │
│  │  Volume: /mcp_rag_eib/data/ │            │  Volume: container-internal  │ │
│  └─────────────────────────────┘            └─────────────────────────────┘ │
│           ▲                                          ▲                      │
│           │                                          │                      │
│     Developer A                               All Developers                │
│     (isolated experiments)                    (shared knowledge base)       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Requirements: Database Synchronization Tools

#### 19E.1: Deep Copy (Clone) Operations

```javascript
// New MCP Tool: clone_chromadb_collection
{
  name: "clone_chromadb_collection",
  description: "Deep copy a ChromaDB collection between environments",
  parameters: {
    source: {
      type: "object",
      properties: {
        endpoint: { type: "string" },  // "local" | "gateway" | URL
        collection: { type: "string" }
      }
    },
    target: {
      type: "object", 
      properties: {
        endpoint: { type: "string" },
        collection: { type: "string" },  // Can rename during copy
        overwrite: { type: "boolean", default: false }
      }
    },
    options: {
      batch_size: { type: "number", default: 100 },
      include_metadata: { type: "boolean", default: true },
      dry_run: { type: "boolean", default: false }
    }
  }
}
```

**Use Cases**:
- `gateway → local`: Developer pulls production embeddings for local testing
- `local → gateway`: Developer contributes new embeddings to shared DB
- `local → local`: Backup before destructive experiments

#### 19E.2: Bidirectional Sync Operations

```javascript
// New MCP Tool: sync_chromadb_collections
{
  name: "sync_chromadb_collections",
  description: "Synchronize collections between ChromaDB instances",
  parameters: {
    source_endpoint: { type: "string" },
    target_endpoint: { type: "string" },
    collections: {
      type: "array",
      items: { type: "string" },
      description: "Collections to sync (empty = all)"
    },
    direction: {
      enum: ["push", "pull", "bidirectional"],
      default: "pull"
    },
    conflict_resolution: {
      enum: ["source_wins", "target_wins", "newest_wins", "manual"],
      default: "newest_wins"
    }
  }
}
```

#### 19E.3: Merge Operations

```javascript
// New MCP Tool: merge_chromadb_collections
{
  name: "merge_chromadb_collections",
  description: "Merge documents from multiple collections or sources",
  parameters: {
    sources: {
      type: "array",
      items: {
        type: "object",
        properties: {
          endpoint: { type: "string" },
          collection: { type: "string" },
          filter: { type: "object" }  // Optional metadata filter
        }
      }
    },
    target: {
      endpoint: { type: "string" },
      collection: { type: "string" }
    },
    deduplication: {
      strategy: {
        enum: ["by_id", "by_content_hash", "by_metadata_key", "none"],
        default: "by_id"
      },
      metadata_key: { type: "string" }  // If strategy = by_metadata_key
    },
    dry_run: { type: "boolean", default: true }
  }
}
```

**Use Cases**:
- Merge developer branches of embeddings
- Combine specialized collections (EE2 + workflow docs)
- Deduplicate after multiple ingestion runs

#### 19E.4: Database Status & Comparison Tool

```javascript
// New MCP Tool: compare_chromadb_instances
{
  name: "compare_chromadb_instances",
  description: "Compare collections and documents across ChromaDB instances",
  parameters: {
    endpoints: {
      type: "array",
      items: { type: "string" },
      minItems: 2
    },
    comparison_level: {
      enum: ["collections_only", "document_counts", "full_diff"],
      default: "document_counts"
    }
  }
}

// Example Output:
{
  "comparison": {
    "endpoints": ["localhost:8080", "gateway:8888"],
    "collections": {
      "global-workflow-docs-v7-0-0": {
        "localhost:8080": null,  // Does not exist
        "gateway:8888": { "count": 3788 }
      },
      "ee2-standards-v5-0-0-enhanced": {
        "localhost:8080": { "count": 34 },
        "gateway:8888": { "count": 34 },
        "status": "in_sync"
      }
    }
  }
}
```

### Implementation Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    DATABASE ABSTRACTION LAYER                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    ChromaDBManager                                   │   │
│  │  - resolveEndpoint(name) → URL + API version                        │   │
│  │  - getClient(endpoint) → ChromaDB client (v1 or v2 adapter)         │   │
│  │  - listCollections(endpoint)                                         │   │
│  │  - exportCollection(endpoint, collection) → { documents, embeddings }│   │
│  │  - importCollection(endpoint, collection, data)                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              ▲                                              │
│         ┌────────────────────┼────────────────────┐                        │
│         │                    │                    │                        │
│  ┌──────┴──────┐     ┌───────┴───────┐    ┌──────┴──────┐                  │
│  │ V1 Adapter  │     │  V2 Adapter   │    │ Mock/Test   │                  │
│  │ (legacy)    │     │  (current)    │    │ Adapter     │                  │
│  └─────────────┘     └───────────────┘    └─────────────┘                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**File**: `mcp_server_node/src/utils/ChromaDBManager.js`

### Multi-Developer Workflow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    MULTI-DEVELOPER WORKFLOW                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. BOOTSTRAP: Developer pulls from gateway                                 │
│     sync_chromadb_collections({                                             │
│       source: "gateway", target: "local",                                   │
│       direction: "pull", collections: ["global-workflow-docs-v7-0-0"]       │
│     })                                                                      │
│                                                                             │
│  2. DEVELOP: Work with local isolated DB                                    │
│     - Add new embeddings                                                    │
│     - Experiment with different chunking                                    │
│     - Test retrieval quality                                                │
│                                                                             │
│  3. CONTRIBUTE: Push approved changes to gateway                            │
│     merge_chromadb_collections({                                            │
│       sources: [{ endpoint: "local", collection: "my-new-embeddings" }],    │
│       target: { endpoint: "gateway", collection: "global-workflow-docs" },  │
│       deduplication: { strategy: "by_content_hash" },                       │
│       dry_run: false  // After review                                       │
│     })                                                                      │
│                                                                             │
│  4. SYNC: Pull updates from other developers                                │
│     sync_chromadb_collections({                                             │
│       source: "gateway", target: "local", direction: "pull"                 │
│     })                                                                      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Endpoint Registry Configuration

**File**: `mcp_server_node/config/chromadb_endpoints.json`

```json
{
  "endpoints": {
    "local": {
      "url": "http://localhost:8080",
      "api_version": "v1",
      "description": "Developer local ChromaDB"
    },
    "gateway": {
      "url": "http://chromadb:8000",
      "api_version": "v2", 
      "description": "Shared gateway ChromaDB (via MCP gateway network)",
      "requires_gateway": true
    },
    "devops": {
      "url": "http://chromadb-devops:8000",
      "api_version": "v2",
      "description": "DevOps/CI environment"
    }
  },
  "default_source": "gateway",
  "default_target": "local"
}
```

### Validation Criteria (19E)

- [ ] Clone collection from gateway to local works
- [ ] Clone collection from local to gateway works
- [ ] Sync detects and reports differences
- [ ] Merge deduplicates by content hash
- [ ] Compare tool shows collection differences
- [ ] V1 ↔ V2 API adapter works transparently
- [ ] Dry-run mode prevents accidental overwrites

### Updated Timeline

| Step | Duration | Deliverable |
|------|----------|-------------|
| 19A  | 2 hours  | ContentResolver module |
| 19B  | 2 hours  | Schema updates for 5 tools |
| 19C  | 4 hours  | Tool implementation updates |
| 19D  | 2 hours  | Documentation and examples |
| **19E**  | **6 hours**  | **ChromaDBManager + sync tools** |
| Test | 3 hours  | Validation suite (extended) |

**Total**: ~19 hours

---

## Related SDDs

- Phase 11: Docker MCP Gateway (provides the remote access pattern)
- Phase 20: COM Compliance Tools (will use this abstraction)
- Phase 4B: Supervised Execution (approval gates work with content)
