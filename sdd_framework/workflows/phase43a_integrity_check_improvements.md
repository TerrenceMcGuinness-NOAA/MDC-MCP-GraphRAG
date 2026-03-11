# Phase 43a: Knowledge Integrity Check Improvements

**Version**: 1.0.0
**Status**: Complete
**Created**: 2026-03-11
**Author**: AI Assistant + Terry McGuinness
**Dependency**: Phase 43 (complete)
**Archaeology**: Bug findings from Phase 43 validation — `check_knowledge_integrity` path consistency and stale embeddings checks produce misleading results

---

## 1. Executive Summary

Phase 43 delivered `check_knowledge_integrity` with 4 checks, but post-delivery validation revealed two design flaws that produce misleading results:

1. **Path consistency** uses `collection.peek()` which returns insertion-order documents (not random), biasing toward the oldest data
2. **Stale embeddings** uses a 30-day age threshold with no source comparison, flagging stable (but current) embeddings as stale

Both checks need to use more meaningful heuristics. Additionally, Phase 43a includes the casing bug fix (`graphDb` → `graphDB`) already applied as a hotfix.

### What This Phase Does NOT Cover

- Health snapshot scheduled automation (→ Phase 43, Notional Item A)
- RAG quality metrics benchmark (→ Phase 44)
- Stale embedding auto-refresh (→ Phase 43, Notional Item C)

---

## 2. Current State vs Target State

| Check | Current Behavior | Problem | Target Behavior |
|-------|-----------------|---------|-----------------|
| Path Consistency | `peek({ limit: 100 })` per collection | Returns first 100 by insertion order, not representative | Use ChromaDB `where` filter to query directly for bad prefixes |
| Stale Embeddings | Flags docs with metadata >30 days old | False positive on stable knowledge base (bulk ingested once) | Compare `ingested_at` against repo's current `git log` HEAD date; only flag if source is newer than embedding |

---

## 3. Technical Specification

### 3.1 Path Consistency — Direct Prefix Query

**Current** (SemanticSearchTools.js ~line 725):
```javascript
const peek = await collection.peek({ limit: 100 });
// iterate metadatas, check if file_path starts with '/' or contains '/home/' or '/scratch/'
```

**Problem**: `peek()` always returns the same oldest 100 docs. With 81K+ docs, this is <0.2% coverage and biased.

**Target**: Replace with a `where` metadata filter that directly counts documents matching bad prefixes:
```javascript
// Query for documents with absolute path prefixes (checkout-specific)
const badDocs = await collection.get({
  where: { file_path: { $contains: '/home/' } },
  limit: 1,
  include: []  // only need count, not content
});
```

ChromaDB `get()` with `where` filters scans the full collection, giving an accurate count instead of a biased sample. Check for each known bad prefix pattern (`/home/`, `/scratch/`, `/mcp_rag_eib/`).

**Fallback**: If `where` filter on `file_path` is not available (metadata key may vary), fall back to a larger random-offset `get()`:
```javascript
const total = await collection.count();
const offset = Math.floor(Math.random() * Math.max(0, total - sample_size));
const sample = await collection.get({ limit: sample_size, offset });
```

### 3.2 Stale Embeddings — Source-Aware Comparison

**Current** (SemanticSearchTools.js ~line 800):
```javascript
const thirtyDaysMs = 30 * 24 * 60 * 60 * 1000;
if ((now - modTime) > thirtyDaysMs) staleCount++;
```

**Problem**: The entire knowledge base was bulk-ingested in Feb-March 2026. A static 30-day threshold will flag everything as stale once time passes, even though the source repo hasn't changed.

**Target**: Compare the embedding's `ingested_at` timestamp against the repository's latest commit date for the corresponding file:

1. Get the repo's HEAD commit date:
   ```javascript
   const headDate = execSync(
     `git -C "${repoBase}" log -1 --format=%aI`,
     { encoding: 'utf-8' }
   ).trim();
   ```

2. For sampled documents, check if the embedding was created **before** the latest commit that touched that file:
   ```javascript
   const fileCommitDate = execSync(
     `git -C "${repoBase}" log -1 --format=%aI -- "${relativePath}"`,
     { encoding: 'utf-8' }
   ).trim();
   // Stale = embedding older than the file's last commit
   if (ingestedAt < new Date(fileCommitDate)) staleCount++;
   ```

3. **Performance guard**: Only run git queries for `sample_size` documents (default 50). Cache the repo HEAD date to avoid repeated calls.

4. **Fallback**: If git is unavailable or the file path doesn't resolve, fall back to the 30-day heuristic with a clear note: `[INFO] Git comparison unavailable, using 30-day age threshold`.

---

## 4. Implementation Steps

| Step | Name | Tag | Description |
|------|------|-----|-------------|
| 1 | Path consistency: replace peek with where filter | implement | Use ChromaDB `get()` with `where` metadata filter for bad prefixes instead of `peek()` |
| 2 | Path consistency: fallback random sampling | implement | If `where` filter unsupported, use random-offset `get()` for representative sample |
| 3 | Stale embeddings: git-aware comparison | implement | Compare `ingested_at` against `git log -1 --format=%aI -- <path>` for sampled docs |
| 4 | Stale embeddings: fallback and caching | implement | Cache HEAD date, fall back to 30-day heuristic with `[INFO]` note when git unavailable |
| 5 | Validate all 4 checks end-to-end | validate | Run `check_knowledge_integrity()` and confirm all checks execute (no skips) |
| 6 | Update tool documentation | document | Update `eib-mcp-tools.instructions.md` with improved check descriptions |

---

## 5. Success Criteria

| Metric | Target |
|--------|--------|
| Path consistency check | Uses `where` filter or random sample, not `peek()` |
| Path consistency accuracy | Reports 0 bad-prefix docs (post Phase 38 fix) |
| Stale embeddings | Only flags docs where source file changed after ingestion |
| Stale embeddings on stable repo | Reports 0/50 stale (no false positives) |
| All 4 checks execute | No `[SKIP] Neo4j not available` when Neo4j is healthy (casing fix verified) |

---

## 6. Architecture Notes

### File Changes

| File | Changes |
|------|---------|
| `src/tools/SemanticSearchTools.js` | Path consistency: `where` filter, stale embeddings: git comparison |

### Tool Count Impact

None — no new tools, enhancement only.

### Pre-applied Hotfix (included in this phase scope)

The `graphDb` → `graphDB` casing bug was fixed as a hotfix prior to spec creation:
- `SemanticSearchTools.js`: 4 occurrences in `checkKnowledgeIntegrity()` (Checks 2, 4)
- `UnifiedMCPServer.js`: property path fix + UNION query split into two separate Cypher queries
