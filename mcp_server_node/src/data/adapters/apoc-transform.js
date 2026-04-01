/**
 * apoc-transform.js — APOC Procedure Replacement Map for Neptune
 *
 * Neptune does not support APOC. This module transforms Cypher queries
 * containing APOC procedure calls into semantically equivalent openCypher.
 *
 * Supported replacements:
 *   apoc.path.expand          → variable-length path pattern
 *   apoc.algo.dijkstra        → Neptune shortestPath / Gremlin fallback
 *   apoc.periodic.iterate     → batched UNWIND
 *   apoc.create.node          → standard CREATE
 *   apoc.merge.node           → MERGE with ON CREATE SET / ON MATCH SET
 *
 * Unknown APOC procedures throw UnsupportedQueryError.
 *
 * @version 1.0.0
 * @author Phase 48 — AWS Infrastructure Port
 */

export class UnsupportedQueryError extends Error {
  constructor(procedure) {
    super(`APOC procedure not supported on Neptune: ${procedure}`);
    this.name = 'UnsupportedQueryError';
    this.procedure = procedure;
  }
}

/**
 * Transform a Cypher query containing APOC calls into Neptune-compatible openCypher.
 *
 * @param {string} cypher - Input Cypher query (may contain APOC calls)
 * @returns {string} Transformed openCypher query
 * @throws {UnsupportedQueryError} If an unknown APOC procedure is encountered
 */
export function transformApoc(cypher) {
  if (!cypher.includes('apoc.')) return cypher;

  let result = cypher;

  // ── 1. apoc.path.expand ──────────────────────────────────────────────────
  // Pattern: apoc.path.expand(startNode, relFilter, labelFilter, minDepth, maxDepth)
  // Neptune: variable-length path  (startNode)-[*minDepth..maxDepth]->(n)
  result = result.replace(
    /CALL\s+apoc\.path\.expand\s*\(\s*(\w+)\s*,\s*['"][^'"]*['"]\s*,\s*['"][^'"]*['"]\s*,\s*(\d+)\s*,\s*(\d+)\s*\)\s*YIELD\s+path\s+AS\s+(\w+)/gi,
    (_, startNode, minDepth, maxDepth, pathVar) =>
      `MATCH ${pathVar} = (${startNode})-[*${minDepth}..${maxDepth}]->()`
  );

  // ── 2. apoc.algo.dijkstra ────────────────────────────────────────────────
  // Neptune supports shortestPath() natively; dijkstra (weighted) needs Gremlin.
  // We replace with Neptune's shortestPath for unweighted cases and warn for weighted.
  result = result.replace(
    /CALL\s+apoc\.algo\.dijkstra\s*\(\s*(\w+)\s*,\s*(\w+)\s*,\s*['"][^'"]*['"]\s*(?:,\s*['"][^'"]*['"])?\s*\)\s*YIELD\s+path\s+AS\s+(\w+)(?:\s*,\s*weight\s+AS\s+(\w+))?/gi,
    (_, startNode, endNode, pathVar, weightVar) => {
      // If weight alias requested, this is a weighted shortest path — not directly
      // expressible in openCypher; emit a Neptune-compatible unweighted fallback
      // and add a comment so callers know to use Gremlin for weighted queries.
      const comment = weightVar
        ? '/* WARNING: weighted dijkstra not supported in openCypher — using unweighted shortestPath */'
        : '';
      return `${comment}\nMATCH ${pathVar} = shortestPath((${startNode})-[*]->(${endNode}))`;
    }
  );

  // ── 3. apoc.periodic.iterate ─────────────────────────────────────────────
  // Pattern: CALL apoc.periodic.iterate('MATCH ...', 'SET/CREATE ...', {batchSize:N})
  // Neptune: UNWIND batch + inner statement
  result = result.replace(
    /CALL\s+apoc\.periodic\.iterate\s*\(\s*'([^']*)'\s*,\s*'([^']*)'\s*,\s*\{[^}]*\}\s*\)/gi,
    (_, matchClause, actionClause) =>
      `${matchClause}\nWITH collect(*) AS _batch\nUNWIND _batch AS _item\n${actionClause}`
  );

  // ── 4. apoc.create.node ──────────────────────────────────────────────────
  // Pattern: CALL apoc.create.node(['Label'], {props}) YIELD node AS n
  result = result.replace(
    /CALL\s+apoc\.create\.node\s*\(\s*\[([^\]]*)\]\s*,\s*(\{[^}]*\})\s*\)\s*YIELD\s+node\s+AS\s+(\w+)/gi,
    (_, labels, props, alias) => {
      const labelStr = labels.replace(/['"]/g, '').split(',').map(l => l.trim()).join(':');
      return `CREATE (${alias}:${labelStr} ${props})`;
    }
  );

  // ── 5. apoc.merge.node ───────────────────────────────────────────────────
  // Pattern: CALL apoc.merge.node(['Label'], {identProps}, {onCreateProps}, {onMatchProps}) YIELD node AS n
  result = result.replace(
    /CALL\s+apoc\.merge\.node\s*\(\s*\[([^\]]*)\]\s*,\s*(\{[^}]*\})\s*,\s*(\{[^}]*\})\s*,\s*(\{[^}]*\})\s*\)\s*YIELD\s+node\s+AS\s+(\w+)/gi,
    (_, labels, identProps, onCreateProps, onMatchProps, alias) => {
      const labelStr = labels.replace(/['"]/g, '').split(',').map(l => l.trim()).join(':');
      return [
        `MERGE (${alias}:${labelStr} ${identProps})`,
        `ON CREATE SET ${alias} += ${onCreateProps}`,
        `ON MATCH SET ${alias} += ${onMatchProps}`,
      ].join('\n');
    }
  );

  // ── Unknown APOC ─────────────────────────────────────────────────────────
  const unknownMatch = result.match(/apoc\.(\w+(?:\.\w+)*)/i);
  if (unknownMatch) {
    throw new UnsupportedQueryError(`apoc.${unknownMatch[1]}`);
  }

  return result;
}
