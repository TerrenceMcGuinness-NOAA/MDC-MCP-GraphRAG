# Phase 38: Knowledge Base Data Quality Normalization

**Version**: 1.0.0
**Status**: Planned
**Created**: 2026-03-06
**Author**: AI Assistant + Terry McGuinness
**Dependency**: None (standalone — must execute BEFORE Phases 39-42)
**Gap Analysis**: [docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md](../../docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md) §4, §7-A

---

## 1. Executive Summary

The knowledge base has three data quality issues that degrade cross-database joins, tool accuracy, and user trust:

1. **ChromaDB path prefix inconsistency** — 29,495 of 58,761 code documents (50.2%) use a checkout-specific `global-workflow/` prefix; 29,205 (49.7%) use the correct repo-relative paths (`sorc/`, `dev/`, `ush/`)
2. **Neo4j stale File nodes** — 178 `File` nodes reference `/mcp_rag_eib/global-workflow_MCP_node.js-RAG/`, an old checkout that no longer exists
3. **Spurious ShellScript nodes** — ~60 graph nodes created from regex parse artifacts (error messages, flags, and string literals matched as source paths)
4. **Missing ex-scripts** — 42 of 82 ex-scripts in `dev/scripts/` are absent from the Neo4j shell graph

These issues cause silent failures in path-matching tools (`find_related_files`, `get_code_context`, `analyze_code_structure`) where one database has `global-workflow/sorc/foo.F90` and another has `sorc/foo.F90`.

### Motivation

This is **prerequisite work** — fixing data quality before ingesting 3,500+ new Fortran files (Phase 39) prevents compounding the inconsistency.

---

## 2. Problem Analysis

### 2.1 ChromaDB Path Prefix Distribution

Collection: `code-with-context-v8-0-0` (58,761 documents)

| Prefix Pattern | Count | Percentage | Correct? |
|---------------|-------|-----------|----------|
| `global-workflow/sorc/...` | 29,495 | 50.2% | NO — checkout name is arbitrary |
| `sorc/...` | 29,205 | 49.7% | YES |
| `dev/...` | 61 | 0.1% | YES |

**Root cause**: `ingest_code_v8.py` uses `os.path.relpath(file_path, WORKFLOW_ROOT)` which produces correct relative paths. But some documents were ingested when the source tree was at a different path, or the `WORKFLOW_ROOT` env var was set incorrectly, causing the prefix to include the checkout directory name.

### 2.2 Neo4j File Node Paths

All 178 `File` nodes have `absolutePath` pointing to:
```
/mcp_rag_eib/global-workflow_MCP_node.js-RAG/sorc/...
```

The current repo location is:
```
/mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow/sorc/...
```

**Root cause**: `ingest-code.js` (legacy JS ingestion) baked absolute paths. The v8 Python scripts use relative paths for Fortran/Python/Shell nodes but File nodes were not updated.

### 2.3 Spurious ShellScript Nodes

`ingest_shell_graph_v8.py` uses a regex to detect `source` and `.` (dot-source) commands:
```python
re.compile(r'(?:source|\.) +([^\s;|&]+)')
```

This matches error messages and string literals that happen to follow `source` or `.` in shell text, creating nodes like:
```
ABORT!, Aborting., -maxdepth, -name, -type, Adding, Check, Exiting., Hera,, Must, Override, etc.
```

### 2.4 Missing Ex-Scripts

`dev/scripts/` contains 82 ex-scripts but only 40 have `ShellScript` nodes in Neo4j. The shell graph ingestion scans `dev/scripts` but some files fail to parse or are skipped by file-extension filters.

---

## 3. Technical Specification

### Target Files

| File | Purpose | Changes |
|------|---------|---------|
| `mcp_server_node/scripts/fix_chromadb_paths.py` | **NEW** — batch update ChromaDB metadata | Strip `global-workflow/` prefix |
| `mcp_server_node/scripts/fix_neo4j_file_nodes.py` | **NEW** — update File node paths | Replace old absolute with relative |
| `mcp_server_node/scripts/purge_shell_artifacts.py` | **NEW** — clean spurious ShellScript nodes | Delete ~60 garbage nodes |
| `mcp_server_node/scripts/ingest_shell_graph_v8.py` | **MODIFY** — fix source regex | Prevent future parse artifacts |
| `mcp_server_node/scripts/ingest_code_v8.py` | **MODIFY** — add path normalization guard | Prevent future prefix drift |

### Database Connections

- **ChromaDB**: `http://localhost:8080` API v2, collection `code-with-context-v8-0-0`
- **Neo4j**: `bolt://localhost:7687`, user `neo4j`

---

## 4. Implementation Steps

### Step 38-1: Audit and Validate Path Distribution
**Tag**: validate
**Target**: Terminal (Cypher + ChromaDB API queries)

Query both databases to establish exact baseline counts before any modifications. Record counts in the SDD session.

```cypher
-- Neo4j File node path audit
MATCH (f:File) RETURN LEFT(f.absolutePath, 50) AS prefix, COUNT(*) AS count
ORDER BY count DESC LIMIT 10;

-- ShellScript artifact audit
MATCH (s:ShellScript) WHERE NOT s.path CONTAINS '/' 
   OR s.path =~ '^[A-Z][a-z]+[.!,]?$'
RETURN s.path ORDER BY s.path;
```

**Acceptance**: Baseline counts documented for pre/post comparison.

---

### Step 38-2: Create ChromaDB Path Normalization Script
**Tag**: implement
**Target**: `mcp_server_node/scripts/fix_chromadb_paths.py`

Batch-process all documents in `code-with-context-v8-0-0`. For each document where `file_path` metadata starts with `global-workflow/`, strip that prefix.

**Logic**:
```python
# ChromaDB v2 API — get/update in batches of 5000
collection = client.get_collection("code-with-context-v8-0-0")
total = collection.count()
for offset in range(0, total, 5000):
    batch = collection.get(limit=5000, offset=offset, include=["metadatas"])
    for i, metadata in enumerate(batch["metadatas"]):
        if metadata.get("file_path", "").startswith("global-workflow/"):
            new_path = metadata["file_path"][len("global-workflow/"):]
            # Update metadata in place
            collection.update(ids=[batch["ids"][i]], metadatas=[{**metadata, "file_path": new_path}])
```

**Features**:
- `--dry-run` mode that reports what would change without writing
- Progress counter every 1000 documents
- Summary: `Updated N of M documents`

**Acceptance**: 29,495 documents updated. All `file_path` values start with `sorc/`, `dev/`, `ush/`, `workflow/`, or `scripts/`.

---

### Step 38-3: Create Neo4j File Node Path Update Script
**Tag**: implement
**Target**: `mcp_server_node/scripts/fix_neo4j_file_nodes.py`

Update all 178 `File` nodes: replace the old absolute path with a repo-relative path.

**Logic**:
```python
OLD_PREFIX = "/mcp_rag_eib/global-workflow_MCP_node.js-RAG/"
# Strip to repo-relative path (e.g., "sorc/gdas.cd/ush/...")
session.run("""
    MATCH (f:File) WHERE f.absolutePath STARTS WITH $old_prefix
    SET f.absolutePath = REPLACE(f.absolutePath, $old_prefix, ''),
        f.relativePath = REPLACE(f.absolutePath, $old_prefix, '')
    RETURN COUNT(f) AS updated
""", old_prefix=OLD_PREFIX)
```

**Acceptance**: 178 File nodes updated. All paths start with `sorc/`, `dev/`, `ush/`, or `scripts/`.

---

### Step 38-4: Create ShellScript Artifact Purge Script
**Tag**: implement
**Target**: `mcp_server_node/scripts/purge_shell_artifacts.py`

Delete spurious ShellScript nodes that are clearly not file paths. Criteria:
1. Path does not contain `/`
2. Path matches known garbage patterns (single words, punctuation)
3. Path does not end with a shell extension

```cypher
MATCH (s:ShellScript)
WHERE NOT s.path CONTAINS '/'
  AND NOT s.path ENDS WITH '.sh'
  AND NOT s.path ENDS WITH '.bash'
  AND NOT s.path ENDS WITH '.ksh'
DETACH DELETE s
RETURN COUNT(*) AS deleted;
```

**Features**:
- `--dry-run` prints nodes that would be deleted
- Logs each deleted node for audit trail

**Acceptance**: ~60 spurious nodes removed. Remaining ShellScript nodes all have path-like values.

---

### Step 38-5: Fix Source Regex in Shell Graph Ingestion
**Tag**: implement
**Target**: `mcp_server_node/scripts/ingest_shell_graph_v8.py`

Tighten the `source`/`.` regex to require that the matched path contains at least one `/` or ends with a shell extension:

```python
# Before (too loose):
# re.compile(r'(?:source|\.) +([^\s;|&]+)')

# After (require path-like structure):
SOURCE_PATTERN = re.compile(
    r'(?:source|\.) +([^\s;|&]+/[^\s;|&]+|[^\s;|&]+\.(?:sh|bash|ksh|env))'
)
```

Also add a post-filter to reject matched strings that look like error messages or flags.

**Acceptance**: Re-running `ingest_shell_graph_v8.py --dry-run` produces zero artifact nodes.

---

### Step 38-6: Add Path Normalization Guard to Code v8
**Tag**: implement
**Target**: `mcp_server_node/scripts/ingest_code_v8.py`

Add an explicit guard after computing `rel_path` to strip any leading repo directory name:

```python
rel_path = os.path.relpath(file_path, WORKFLOW_ROOT)
# Guard: strip checkout directory name if present
REPO_DIR_NAME = os.path.basename(WORKFLOW_ROOT)  # e.g., "global-workflow"
if rel_path.startswith(REPO_DIR_NAME + "/"):
    rel_path = rel_path[len(REPO_DIR_NAME) + 1:]
```

**Acceptance**: All new ingestions produce paths starting with `sorc/`, `dev/`, `ush/`, etc. — never with a repo directory prefix.

---

### Step 38-7: Re-ingest Missing Ex-Scripts
**Tag**: execute
**Target**: `mcp_server_node/scripts/ingest_shell_graph_v8.py`

Run the shell graph ingestion with the fixed regex targeting `dev/scripts/` to pick up the 42 missing ex-scripts.

```bash
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node
python scripts/ingest_shell_graph_v8.py --directory dev/scripts
```

**Acceptance**: `MATCH (s:ShellScript) WHERE s.category = 'ex-script' RETURN COUNT(s)` returns >= 80 (was 40).

---

### Step 38-8: Validate Cross-Database Path Consistency
**Tag**: validate
**Target**: Terminal

Run join validation: for a sample of 100 files, confirm that the ChromaDB `file_path` matches the Neo4j node `file_path` property exactly.

```cypher
MATCH (n) WHERE n.file_path IS NOT NULL
WITH n.file_path AS path, LABELS(n)[0] AS label
RETURN label, LEFT(path, 30) AS prefix_sample, COUNT(*) AS count
ORDER BY count DESC LIMIT 20;
```

Cross-reference with ChromaDB:
```python
sample = collection.get(limit=100, include=["metadatas"])
for m in sample["metadatas"]:
    assert not m["file_path"].startswith("global-workflow/")
```

**Acceptance**: Zero path mismatches in sample. Pre/post comparison shows improvement from 50% → 100% path consistency.

---

### Step 38-9: Update Gap Analysis Report
**Tag**: document
**Target**: `docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md`

Update the Data Quality section (§4) with post-remediation status. Update the Coverage Scorecard (§8) "Path consistency" row from D to A.

**Acceptance**: Report reflects resolved status for Phase A items.

---

## 5. Validation Criteria

| Criterion | Before | After | Method |
|-----------|--------|-------|--------|
| ChromaDB docs with `global-workflow/` prefix | 29,495 (50.2%) | 0 (0%) | Batch metadata query |
| Neo4j File node stale paths | 178 | 0 | Cypher COUNT |
| Spurious ShellScript nodes | ~60 | 0 | Cypher WHERE NOT path CONTAINS '/' |
| Ex-scripts in graph | 40 | >= 80 | Cypher COUNT WHERE category = 'ex-script' |
| Path consistency score | D | A | Manual spot-check |

## 6. Risk Assessment

| Risk | Mitigation |
|------|-----------|
| ChromaDB update corrupts embeddings | Updates only modify metadata, not embeddings. Dry-run first. |
| Neo4j detach-delete removes wanted edges | Purge script only targets nodes without `/` in path. Dry-run first. |
| Regex tightening misses legitimate sources | Test against known `source` commands in ex-scripts before deploying. |

## 7. Cross-References

- **Gap Analysis**: `docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md` §4 (Data Quality), §7-A (Remediation Phase A)
- **Downstream**: Phase 39 (Fortran graph) depends on clean paths
- **Related SDD**: Phase 27B (shell graph v8), Phase 24F (cross-language bridges)
- **SPOT**: Path convention must be documented once paths are normalized
