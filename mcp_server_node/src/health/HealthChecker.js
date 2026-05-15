/**
 * HealthChecker.js — Unified health check and resilience utilities
 *
 * Provides:
 *   - checkDatabases(vectorDB, graphDB)  → { status, vector, graph }
 *   - withRetry(fn, opts)                → exponential backoff (5s, 10s, 20s, max 60s)
 *   - isDegraded(status)                 → boolean
 *
 * Health rules (Requirements 11.1, 11.2):
 *   healthy  — both DBs connected, vectorDB has ≥5 indices, graphDB has node count > 0
 *   degraded — one or both DBs unreachable, or data thresholds not met
 *
 * @module health/HealthChecker
 */

// Retry delays in ms: 5s, 10s, 20s, then cap at 60s (Requirement 14.4)
const RETRY_DELAYS = [5000, 10000, 20000, 60000];

/**
 * Exponential backoff retry.
 *
 * @param {Function} fn          - Async function to retry
 * @param {object}   opts
 * @param {number}   opts.maxAttempts  - Max attempts (default: 4)
 * @param {Function} opts.onRetry      - Called with (attempt, delayMs, error) before each retry
 * @returns {Promise<*>} Result of fn on success
 * @throws Last error if all attempts exhausted
 */
export async function withRetry(fn, { maxAttempts = 4, onRetry = null } = {}) {
  let lastErr;
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    try {
      return await fn();
    } catch (err) {
      lastErr = err;
      if (attempt < maxAttempts - 1) {
        const delayMs = RETRY_DELAYS[Math.min(attempt, RETRY_DELAYS.length - 1)];
        if (onRetry) onRetry(attempt + 1, delayMs, err);
        await _sleep(delayMs);
      }
    }
  }
  throw lastErr;
}

/**
 * Check health of both database adapters.
 *
 * @param {VectorDatabaseAdapter} vectorDB
 * @param {GraphDatabaseAdapter}  graphDB
 * @param {object} opts
 * @param {number} opts.minIndices   - Minimum vector indices required (default: 5)
 * @returns {Promise<{status:'healthy'|'degraded', vector: object, graph: object}>}
 */
export async function checkDatabases(vectorDB, graphDB, { minIndices = 5 } = {}) {
  const [vectorResult, graphResult] = await Promise.all([
    _checkVector(vectorDB, minIndices),
    _checkGraph(graphDB),
  ]);

  const status = (vectorResult.ok && graphResult.ok) ? 'healthy' : 'degraded';
  return { status, vector: vectorResult, graph: graphResult };
}

/** @returns {boolean} */
export function isDegraded(status) {
  return status !== 'healthy';
}

// ── Private helpers ──────────────────────────────────────────────────────────

async function _checkVector(vectorDB, minIndices) {
  try {
    const collections = await vectorDB.listCollections();
    const ok = collections.length >= minIndices;
    return {
      ok,
      status: ok ? 'healthy' : 'degraded',
      indexCount: collections.length,
      reason: ok ? null : `only ${collections.length} indices (need ≥${minIndices})`,
    };
  } catch (err) {
    return { ok: false, status: 'degraded', indexCount: 0, reason: err.message };
  }
}

async function _checkGraph(graphDB) {
  try {
    const stats = await graphDB.getStatistics();
    const nodeCount = stats?.nodes ?? 0;
    const ok = nodeCount > 0;
    return {
      ok,
      status: ok ? 'healthy' : 'degraded',
      nodeCount,
      reason: ok ? null : 'graph database has 0 nodes',
    };
  } catch (err) {
    return { ok: false, status: 'degraded', nodeCount: 0, reason: err.message };
  }
}

function _sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}
