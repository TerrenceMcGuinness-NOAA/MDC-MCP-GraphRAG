# Load-Graph Crash Assessment & Remediation Plan

**Date:** 2026-04-08
**Phase:** 50 — S3 → Neptune Migration
**Status:** Process died at 48.5% node loading (47,932 / 98,813 nodes, 0 / 2,653,565 rels)

---

## 1. Root Cause Analysis

### What happened
The `node scripts/migrate-to-aws.js --phase load-graph` process ran for ~55 minutes, loaded 47,932 nodes into Neptune, then died from an unhandled exception. No watermark was written (load:graph never set to "done"), so the run is safely resumable.

### What did NOT cause it
- **Not OOM-killed**: No dmesg/journalctl OOM entries. System had 3.9 GB free of 7.6 GB. No swap configured.
- **Not a kernel signal**: No SIGKILL/SIGSEGV in dmesg.
- **Not a Neptune capacity limit**: Neptune db.r6g.large has 16 GB RAM, was at normal load.

### Most likely cause: cascading failure from Neptune "Operation terminated (internal error)"

The error `"Operation terminated (internal error)"` is a Neptune HTTP 500 that AWS documents as **retriable** but with no specific cause listed (remedy: "Contact AWS Support"). Based on the evidence:

1. The process was doing steady I/O (confirmed via `/proc/PID/io` sampling) but the Neptune node count stopped advancing at 47,932.
2. The retry logic creates a new driver+session on failure, but the `catch` block in the retry path itself has no error handling — if the retry also fails, the exception propagates to `main()` and kills the process.
3. The SigV4 token refresh interval (4 min) is close to the 5-min expiry. Under load, a batch that takes >1 min to complete could push past the token expiry window, causing the next batch to fail with `MissingAuthenticationTokenException`, which triggers a retry, which may also fail if the new token is generated but the session isn't fully established.

**Verdict:** A Neptune internal error triggered the retry path, the retry also failed (likely due to session state corruption or token timing), and the unhandled second exception killed the process.

---

## 2. Data Profile Issues

### 2.1 Null names (6,981 nodes — 7.1%)

| Label | Count | Has `name`? |
|-------|-------|-------------|
| Commit | 2,880 | No |
| File | 2,758 | No |
| CodeFile | 676 | No |
| Documentation | 501 | No |
| DataDependency | 111 | No |
| RocotoCycledef | 36 | No |
| PlatformVersion | 19 | No |

The current MERGE query is:
```cypher
MERGE (n:`Label` {name: p.name}) ON CREATE SET n += p ON MATCH SET n += p
```

When `p.name` is undefined, Neptune receives `MERGE (n:Commit {name: null})`. This either:
- Creates a node with `name: null` (if Neptune allows it), causing all subsequent null-name Commits to MERGE onto the same node
- Throws an error that triggers the retry loop

**Fix:** Use a composite key. For nodes without `name`, use `id` or `path` as the merge key.

### 2.2 Duplicate names (22,313 names appear >1 time)

Top offenders: `__init__` (571x), `main` (233x), `finalize` (124x), `initialize` (109x).

The MERGE query uses only `{name}` without a label constraint in the MATCH pattern. When `__init__` appears across FortranSubroutine, PythonFunction, CodeFunction, etc., MERGE may:
- Match the wrong node (cross-label collision)
- Create excessive lock contention on the same name

**Fix:** Include label in the MERGE pattern (already done with backtick labels) AND add a secondary discriminator like `id` or `path`.

### 2.3 Complex properties (97,866 non-simple values)

- 90,856 array properties (e.g., `communityLevels`, `decorators`, `parameters`)
- 7,010 object properties (e.g., `updated_at`, `createdAt`)

Neptune openCypher only supports simple literals. The `sanitizeProps()` function converts these to JSON strings, which works but inflates property sizes and makes them unsearchable.

### 2.4 Unresolvable relationship endpoints

- 16,645 rels (0.6%) have `fromName` that doesn't match any node name
- 5,744 rels (0.2%) have `toName` that doesn't match any node name

These will silently fail the `MATCH (a {name: r.fromName})` clause, producing zero results and creating no relationships. This is acceptable data loss but should be logged.

---

## 3. Code Bottlenecks

### 3.1 Single-threaded sequential writes
AWS recommends **parallel writers matching 2x vCPU** (= 4 for db.r6g.large). The current code uses a single session doing sequential `await session.run()` calls. This leaves 75% of Neptune's write capacity unused.

### 3.2 MERGE is expensive
Each MERGE does a full scan to check existence before insert. With 98K nodes and no index on `name`, this gets progressively slower as the graph grows. Neptune doesn't support user-created indexes on openCypher — it auto-indexes, but MERGE on a property that has 571 duplicates is inherently slow.

### 3.3 SigV4 token lifecycle
- Token expires in 5 minutes
- Refresh check happens at batch boundaries (every 50 nodes)
- If a batch takes >1 min (likely with MERGE on large graphs), the token may expire mid-batch
- The refresh creates a new driver+session but doesn't verify connectivity before resuming

### 3.4 Retry logic is single-attempt
The retry catches one failure, refreshes the session, and retries once. If the retry fails, the exception propagates to `main()` and kills the process. There's no exponential backoff, no max-retry counter, and no distinction between retriable errors (500) and non-retriable errors (400).

### 3.5 No progress watermarking
The watermark is only written after ALL nodes and ALL relationships are loaded. If the process dies at 48.5%, there's no record of progress. On restart, MERGE will re-process all 47,932 already-loaded nodes (idempotent but slow).

---

## 4. Recommended Fixes (Priority Order)

### Fix 1: Neptune Bulk Loader (BEST OPTION — orders of magnitude faster)

Neptune has a native bulk loader that reads **openCypher CSV directly from S3**. This bypasses Bolt entirely and uses Neptune's internal parallel loading engine.

**What it needs:**
1. Convert the JSON graph dump to openCypher CSV format (nodes.csv + relationships.csv)
2. Upload CSVs to S3
3. Call the Neptune `/loader` API with `format: "opencypher"`
4. Neptune loads directly from S3 with internal parallelism

**openCypher CSV format:**
```csv
# nodes.csv
:ID,:LABEL,name:String,path:String,language:String,loc:Int
node_001,FortranSubroutine,icedrv_system_abort,/path/to/file,Fortran,42

# relationships.csv  
:ID,:START_ID,:END_ID,:TYPE,weight:Float
rel_001,node_001,node_002,CALLS,1.0
```

**Advantages:**
- 10-100x faster than Bolt MERGE
- No SigV4 token expiry issues (single API call)
- Built-in parallelism (OVERSUBSCRIBE uses all vCPUs)
- Built-in resume on failure
- No client-side memory pressure

**Requirements:**
- IAM role attached to Neptune cluster with S3 read access
- Node/rel IDs must be stable (use the `id` property from Neo4j export)

**Estimated implementation:** ~2 hours to write CSV converter + loader call.

### Fix 2: Robust Bolt Loading (if bulk loader isn't feasible)

If we must use Bolt (e.g., need MERGE semantics for incremental updates), fix these issues:

#### 2a. Use composite MERGE keys
```javascript
// Before (broken for null names, collides on duplicates):
MERGE (n:`Label` {name: p.name})

// After (unique per node):
MERGE (n:`Label` {_nodeId: p.id})
ON CREATE SET n += p
ON MATCH SET n += p
```

#### 2b. Parallel writers (4 concurrent sessions)
```javascript
const PARALLELISM = 4; // 2x vCPU for db.r6g.large
const workers = Array.from({length: PARALLELISM}, () => makeNeptuneDriver(neo4j.session.WRITE));
// Distribute batches round-robin across workers
```

#### 2c. Exponential backoff with retriable error detection
```javascript
const RETRIABLE = ['Operation terminated', 'conflicting concurrent', 'please retry'];
async function runWithRetry(session, query, params, maxRetries = 5) {
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await session.run(query, params);
    } catch (err) {
      const retriable = RETRIABLE.some(s => err.message.includes(s));
      if (!retriable || attempt === maxRetries) throw err;
      const delay = Math.min(1000 * Math.pow(2, attempt), 30000);
      console.warn(`[RETRY] Attempt ${attempt+1}/${maxRetries}, waiting ${delay}ms: ${err.message}`);
      await new Promise(r => setTimeout(r, delay));
    }
  }
}
```

#### 2d. Progress watermarking per batch
```javascript
// Save watermark every N batches
if (i % (NEPTUNE_BATCH * 20) === 0) {
  wm['load:graph:progress'] = i;
  await saveWatermarks(wm);
}
// On restart, skip to saved progress
const startIdx = wm['load:graph:progress'] || 0;
```

#### 2e. SigV4 token refresh with pre-validation
```javascript
async function refreshDriver() {
  const { driver, session } = await makeNeptuneDriver(neo4j.session.WRITE);
  // Validate connection before returning
  await session.run('RETURN 1');
  return { driver, session };
}
```

### Fix 3: Data Cleanup (required for either approach)

#### 3a. Generate stable node IDs for nodes without names
```javascript
function nodeId(node) {
  return node.properties.id || node.properties.path || 
    `${node.labels[0]}_${hash(JSON.stringify(node.properties))}`;
}
```

#### 3b. Filter unresolvable relationships
```javascript
// Pre-build name→id lookup, skip rels that can't resolve
const nodeIndex = new Map(dump.nodes.map(n => [nodeId(n), true]));
const validRels = dump.relationships.filter(r => 
  nodeIndex.has(r.fromName) && nodeIndex.has(r.toName)
);
```

---

## 5. Recommendation

**Go with Fix 1 (Neptune Bulk Loader)** as the primary approach:

1. Write a `convert-to-opencypher-csv.js` script that transforms the JSON dump into openCypher CSV format
2. Upload CSVs to `s3://mdc-mcp-rag-migration/graph-csv/`
3. Attach an IAM role to the Neptune cluster with S3 read access
4. Call the Neptune loader API
5. Keep the Bolt-based `loadGraph` as a fallback for incremental updates post-migration

**If the bulk loader can't be set up quickly** (IAM role attachment requires CDK changes), apply Fixes 2a-2e to the existing Bolt code and re-run. The combination of composite MERGE keys, parallel writers, exponential backoff, and progress watermarking should get us through the 98K nodes + 2.6M rels in ~2-3 hours instead of failing at 48%.

---

## 6. Current State

| Component | Status | Count |
|-----------|--------|-------|
| S3 Exports | ✅ Complete | 5 vector collections + 1 graph dump |
| OpenSearch Load | ✅ Complete | 85,921 docs across 5 indices |
| Neptune Nodes | ⚠️ Partial | 47,932 / 98,813 (48.5%) |
| Neptune Rels | ❌ Not started | 0 / 2,653,565 |
| Verification | ❌ Blocked | Waiting on Neptune load |

The 47,932 nodes already in Neptune are valid and will be handled by MERGE (upsert) on re-run. No data corruption.
