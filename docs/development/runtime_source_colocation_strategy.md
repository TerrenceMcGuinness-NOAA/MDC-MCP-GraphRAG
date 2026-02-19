# Runtime-Source Control Co-location Strategy
**Eliminating artificial runtime/source split through proper .gitignore**

## Problem Statement

### Previous Architecture (Problematic)
```
eib-mcp-rag-server/          # Source control repo
  ├── mcp_server_node/       # MCP server source
  └── scripts/               # Build scripts

/runtime/somewhere/          # Runtime deployment (separate location)
  └── mcp_server_node/       # Copied at runtime
```

**Issues:**
- ❌ Artificial separation of runtime vs source
- ❌ Confusion about "where does this file live?"
- ❌ Sync problems between source and runtime
- ❌ Deployment complexity
- ❌ Unclear what to version control

### New Architecture (Co-located)
```
eib-mcp-rag-server/          # Source control + runtime
  ├── mcp_server_node/       # MCP servers (versioned)
  ├── chromadb_data/         # Runtime data (ignored)
  ├── vector_store/          # Runtime indexes (ignored)
  ├── logs/                  # Runtime logs (ignored)
  ├── node_modules/          # Dependencies (ignored)
  └── .gitignore            # Defines runtime vs source split
```

**Benefits:**
- ✅ Single source of truth
- ✅ Clear .gitignore-based separation
- ✅ No deployment sync issues
- ✅ Simpler mental model
- ✅ VS Code MCP can reference directly

---

## Architecture Principles

### 1. Co-location is Default
**Rule:** Source code and runtime execution happen in the same directory tree.

**Separation:** Achieved through .gitignore, not physical directory separation.

### 2. .gitignore Defines Boundaries
**Source Control (Versioned):**
- MCP server implementations (`mcp_server_node/*.js`)
- Configuration templates (`config/*.template.json`)
- Documentation (`docs/`, `sdd_framework/`)
- Build scripts (`scripts/`)
- Package definitions (`package.json`, `package-lock.json`)

**Runtime-Only (Ignored):**
- Vector databases (`chromadb_data/`, `vector_store/`)
- Logs (`logs/`, `*.log`)
- Dependencies (`node_modules/`, `__pycache__/`)
- Runtime state (`*.pid`, `*.lock`)
- Environment configs (`config/*.env`, `.env`)
- Temporary files (`tmp/`, `*.tmp`)

### 3. Naming Conventions
**Source Files:** Clear, descriptive names indicating purpose
```
mcp_server_node/
  ├── mcp-server-sdd.js           # SDD validation MCP server
  ├── mcp-server-full.js          # Full RAG search MCP server
  ├── UnifiedMCPServer.js         # Runtime operations MCP server
  └── mcp-server-ee2-enhanced.js  # Enhanced EE2 compliance (new)
```

**No Ambiguity:** Filenames clearly indicate what they do, no "runtime" vs "source" prefix needed.

---

## Implementation Plan

### Phase 1: Update .gitignore ✅
```gitignore
# Runtime Data - NEVER commit
chromadb_data/
vector_store/
*.chroma/
*.faiss/

# Logs - NEVER commit
logs/
*.log
*.log.*

# Dependencies - NEVER commit
node_modules/
__pycache__/
*.pyc
.Python
venv/
env/

# Runtime State - NEVER commit
*.pid
*.lock
*.sock

# Environment Configs - NEVER commit
.env
.env.*
config/*.env
secrets/

# Temporary Files - NEVER commit
tmp/
temp/
*.tmp
*.cache

# IDE - Project-specific OK, user-specific NO
.vscode/settings.json  # Project settings - commit
.vscode/*.code-workspace  # User workspaces - ignore
.idea/

# Build Artifacts - NEVER commit
dist/
build/
*.egg-info/

# OS Files - NEVER commit
.DS_Store
Thumbs.db
```

### Phase 2: Rename Scripts for Clarity ✅
**Old Confusion:**
- `mcp-server.js` - What server? Runtime or source?
- `server.js` - Too generic
- `runtime-server.js` vs `source-server.js` - Artificial split

**New Clarity:**
```
mcp_server_node/
  ├── mcp-server-sdd.js              # SDD validation tools
  ├── mcp-server-full.js             # Full RAG search
  ├── UnifiedMCPServer.js            # Runtime operations
  ├── mcp-server-ee2-enhanced.js     # Enhanced EE2 (future)
  └── src/
      ├── SDDValidator.js            # SDD validation logic
      ├── RagSearchEngine.js         # RAG search logic
      └── utils/
          ├── chromadb-client.js     # ChromaDB interface
          └── logger.js              # Logging utilities
```

### Phase 3: Update VS Code MCP Configuration ✅
**`.vscode/mcp.json` - Direct References:**
```json
{
  "mcpServers": {
    "eib-mcp-rag-full": {
      "command": "node",
      "args": ["/mcp_rag_eib/eib-mcp-rag-server/mcp_server_node/mcp-server-full.js"]
    },
    "eib-mcp-rag-runtime": {
      "command": "node",
      "args": ["/mcp_rag_eib/eib-mcp-rag-server/mcp_server_node/UnifiedMCPServer.js"]
    },
    "eib-sdd-validator": {
      "command": "node",
      "args": ["/mcp_rag_eib/eib-mcp-rag-server/mcp_server_node/mcp-server-sdd.js"]
    },
    "global-workflow-core": {
      "command": "node",
      "args": ["/mcp_rag_eib/global-workflow_MCP_node.js-RAG/mcp_server_node/global-workflow-mcp.js"]
    }
  }
}
```

**Benefits:**
- Direct file references, no deployment step
- Changes to source immediately available
- Clear what's running where

### Phase 4: Documentation Updates ✅
Update all docs to reference co-located model:
- ✅ `QUICK_START_GUIDE.md` - Remove deployment steps
- ✅ `MCP_SYSTEM_STATUS_REPORT.md` - Update architecture section
- ✅ `SDD framework docs` - Reflect new structure

---

## Directory Structure (Reference)

```
eib-mcp-rag-server/
├── .git/                          # Git repository
├── .gitignore                     # Runtime vs source boundary
├── .vscode/
│   ├── mcp.json                   # MCP server configs (versioned)
│   └── settings.json              # Project settings (versioned)
│
├── mcp_server_node/               # MCP SERVERS (VERSIONED)
│   ├── mcp-server-sdd.js          # SDD validation
│   ├── mcp-server-full.js         # Full RAG search
│   ├── UnifiedMCPServer.js        # Runtime operations
│   ├── mcp-server-ee2-enhanced.js # Enhanced EE2 (future)
│   ├── package.json               # Dependencies
│   └── src/                       # Supporting modules
│       ├── SDDValidator.js
│       ├── RagSearchEngine.js
│       └── utils/
│
├── sdd_framework/                 # SDD FRAMEWORK (VERSIONED)
│   ├── architecture/
│   ├── workflows/
│   ├── templates/
│   └── validation/
│
├── docs/                          # DOCUMENTATION (VERSIONED)
│   ├── QUICK_START_GUIDE.md
│   └── ...
│
├── scripts/                       # BUILD SCRIPTS (VERSIONED)
│   ├── setup_environment.sh
│   └── test_mcp_servers.sh
│
├── config/                        # CONFIGS
│   ├── *.template.json            # Templates (versioned)
│   └── *.env                      # Runtime (ignored)
│
├── chromadb_data/                 # RUNTIME DATA (IGNORED)
├── vector_store/                  # RUNTIME DATA (IGNORED)
├── logs/                          # RUNTIME DATA (IGNORED)
├── node_modules/                  # RUNTIME DATA (IGNORED)
└── tmp/                           # RUNTIME DATA (IGNORED)
```

---

## Migration Checklist

### Immediate Actions
- [x] Create this documentation
- [ ] Update .gitignore with runtime exclusions
- [ ] Verify all MCP servers use clear names
- [ ] Update .vscode/mcp.json paths
- [ ] Test all MCP servers start correctly
- [ ] Update documentation references

### Validation
- [ ] `git status` shows no runtime data
- [ ] All MCP servers operational via VS Code
- [ ] No confusion about "where does this file go?"
- [ ] Clear separation in .gitignore

### Communication
- [ ] Update team on new co-location strategy
- [ ] Document in SDD framework
- [ ] Update onboarding guides

---

## Anti-Patterns to Avoid

### ❌ Don't: Separate Runtime and Source Physically
```bash
# WRONG
/source/eib-mcp-rag/          # Source code
/runtime/eib-mcp-rag/         # Deployed runtime
```

### ✅ Do: Co-locate with .gitignore Separation
```bash
# RIGHT
/eib-mcp-rag-server/          # Everything here
  ├── mcp_server_node/        # Source (versioned)
  ├── chromadb_data/          # Runtime (ignored)
  └── .gitignore              # Defines boundary
```

### ❌ Don't: Ambiguous Filenames
```javascript
// WRONG
server.js              // What server?
runtime.js             // Runtime what?
mcp.js                 // MCP what?
```

### ✅ Do: Clear, Purpose-Driven Names
```javascript
// RIGHT
mcp-server-sdd.js           // SDD validation MCP server
mcp-server-full.js          // Full RAG search MCP server
UnifiedMCPServer.js         // Runtime operations MCP server
```

### ❌ Don't: Mix Runtime Data in Source Dirs
```bash
# WRONG
mcp_server_node/
  ├── mcp-server-sdd.js
  ├── server.log            # Runtime data in source dir!
  └── temp_data/            # Runtime data in source dir!
```

### ✅ Do: Clear Runtime Data Locations
```bash
# RIGHT
mcp_server_node/
  ├── mcp-server-sdd.js     # Source only

logs/
  └── server.log            # Runtime data in ignored dir

tmp/
  └── temp_data/            # Runtime data in ignored dir
```

---

## Benefits Summary

### For Developers
- ✅ Single location to work from
- ✅ Changes immediately testable
- ✅ No sync/deployment steps
- ✅ Clear .gitignore-based boundaries

### For Operations
- ✅ Simple mental model
- ✅ No confusion about "which version is running?"
- ✅ Direct reference from VS Code MCP
- ✅ Easy troubleshooting

### For Maintenance
- ✅ Reduced cognitive load
- ✅ No artificial runtime/source split
- ✅ Clear naming conventions
- ✅ Version control works as expected

---

## Next Steps

1. **Update .gitignore** - Add runtime exclusions
2. **Verify naming** - All MCP servers clearly named
3. **Test configuration** - All servers start from co-located paths
4. **Update docs** - Remove references to runtime/source split
5. **Validate** - `git status` shows clean separation

**Status:** Implementation ready, awaiting final updates.
