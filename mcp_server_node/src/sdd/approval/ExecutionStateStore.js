/**
 * DORMANT — Reserved for CLI/YOLO execution modality (Phase 4C USD)
 * Not imported by SDDWorkflowTools in IDE mode (Phase 31 session model).
 * Will be re-imported when Claude CLI / GitHub CLI autonomous execution is built.
 *
 * ExecutionStateStore - Persistent storage for workflow execution state
 * 
 * Stores execution state as JSON files for multi-turn approval workflows.
 * Supports TTL-based auto-cleanup of expired states.
 * 
 * Version: 1.0.0
 * Phase: 4B - Interactive Supervised Development
 * Date: January 2, 2026
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// SDD Framework root - uses env var for container, falls back to relative path for local dev
const SDD_FRAMEWORK_ROOT = process.env.SDD_FRAMEWORK_ROOT || 
  path.join(__dirname, '../../../../sdd_framework');

/**
 * Default configuration
 */
const DEFAULT_CONFIG = {
  // State files directory (within sdd_framework)
  stateDir: path.join(SDD_FRAMEWORK_ROOT, 'execution_state'),
  // Time-to-live for execution states (5 minutes default)
  ttlMs: 5 * 60 * 1000,
  // Maximum states to keep (prevent disk bloat)
  maxStates: 100,
  // Cleanup interval (run cleanup every N operations)
  cleanupInterval: 10
};

/**
 * ExecutionStateStore
 * File-based persistent storage for workflow execution states
 */
export class ExecutionStateStore {
  constructor(config = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config };
    this.operationCount = 0;
    
    // Ensure state directory exists
    this.ensureStateDir();
  }

  /**
   * Ensure state directory exists
   */
  ensureStateDir() {
    if (!fs.existsSync(this.config.stateDir)) {
      fs.mkdirSync(this.config.stateDir, { recursive: true });
      console.log(`[ExecutionStateStore] Created state directory: ${this.config.stateDir}`);
    }
  }

  /**
   * Generate state file path for an execution ID
   * @param {string} executionId - Execution ID
   * @returns {string} Full path to state file
   */
  getStatePath(executionId) {
    // Sanitize execution ID for filesystem safety
    const safeId = executionId.replace(/[^a-zA-Z0-9_-]/g, '_');
    return path.join(this.config.stateDir, `${safeId}.json`);
  }

  /**
   * Save execution state
   * @param {string} executionId - Unique execution ID
   * @param {Object} state - Execution state to save
   * @returns {boolean} Success status
   */
  save(executionId, state) {
    try {
      const statePath = this.getStatePath(executionId);
      const stateData = {
        ...state,
        executionId,
        savedAt: Date.now(),
        expiresAt: Date.now() + this.config.ttlMs
      };

      fs.writeFileSync(statePath, JSON.stringify(stateData, null, 2), 'utf-8');
      console.log(`[ExecutionStateStore] Saved state: ${executionId}`);

      // Periodic cleanup
      this.maybeCleanup();

      return true;
    } catch (error) {
      console.error(`[ExecutionStateStore] Failed to save state: ${error.message}`);
      return false;
    }
  }

  /**
   * Load execution state
   * @param {string} executionId - Execution ID to load
   * @returns {Object|null} Saved state or null if not found/expired
   */
  load(executionId) {
    try {
      const statePath = this.getStatePath(executionId);

      if (!fs.existsSync(statePath)) {
        console.log(`[ExecutionStateStore] State not found: ${executionId}`);
        return null;
      }

      const content = fs.readFileSync(statePath, 'utf-8');
      const state = JSON.parse(content);

      // Check if expired
      if (state.expiresAt && Date.now() > state.expiresAt) {
        console.log(`[ExecutionStateStore] State expired: ${executionId}`);
        this.delete(executionId);
        return null;
      }

      console.log(`[ExecutionStateStore] Loaded state: ${executionId}`);
      return state;
    } catch (error) {
      console.error(`[ExecutionStateStore] Failed to load state: ${error.message}`);
      return null;
    }
  }

  /**
   * Delete execution state
   * @param {string} executionId - Execution ID to delete
   * @returns {boolean} Success status
   */
  delete(executionId) {
    try {
      const statePath = this.getStatePath(executionId);

      if (fs.existsSync(statePath)) {
        fs.unlinkSync(statePath);
        console.log(`[ExecutionStateStore] Deleted state: ${executionId}`);
      }

      return true;
    } catch (error) {
      console.error(`[ExecutionStateStore] Failed to delete state: ${error.message}`);
      return false;
    }
  }

  /**
   * List all pending executions
   * @param {boolean} includeExpired - Include expired states in listing
   * @returns {Array} List of execution summaries
   */
  list(includeExpired = false) {
    try {
      this.ensureStateDir();
      
      const files = fs.readdirSync(this.config.stateDir)
        .filter(f => f.endsWith('.json'));

      const executions = [];
      const now = Date.now();

      for (const file of files) {
        try {
          const filePath = path.join(this.config.stateDir, file);
          const content = fs.readFileSync(filePath, 'utf-8');
          const state = JSON.parse(content);

          const isExpired = state.expiresAt && now > state.expiresAt;

          if (!isExpired || includeExpired) {
            executions.push({
              executionId: state.executionId,
              workflowName: state.workflowName,
              currentStep: state.currentStepIndex,
              totalSteps: state.totalSteps,
              status: isExpired ? 'expired' : 'pending',
              savedAt: new Date(state.savedAt).toISOString(),
              expiresAt: new Date(state.expiresAt).toISOString(),
              ttlRemaining: isExpired ? 0 : Math.round((state.expiresAt - now) / 1000)
            });
          }
        } catch (parseError) {
          // Skip malformed files
          console.warn(`[ExecutionStateStore] Skipping malformed file: ${file}`);
        }
      }

      return executions.sort((a, b) => b.savedAt.localeCompare(a.savedAt));
    } catch (error) {
      console.error(`[ExecutionStateStore] Failed to list states: ${error.message}`);
      return [];
    }
  }

  /**
   * Update TTL for an execution (extend timeout)
   * @param {string} executionId - Execution ID
   * @param {number} additionalMs - Additional milliseconds to add
   * @returns {boolean} Success status
   */
  extendTTL(executionId, additionalMs = null) {
    try {
      const state = this.load(executionId);
      if (!state) return false;

      state.expiresAt = Date.now() + (additionalMs || this.config.ttlMs);
      return this.save(executionId, state);
    } catch (error) {
      console.error(`[ExecutionStateStore] Failed to extend TTL: ${error.message}`);
      return false;
    }
  }

  /**
   * Run cleanup if needed (periodic)
   */
  maybeCleanup() {
    this.operationCount++;
    if (this.operationCount >= this.config.cleanupInterval) {
      this.operationCount = 0;
      this.cleanup();
    }
  }

  /**
   * Cleanup expired states and enforce max states limit
   * @returns {Object} Cleanup summary
   */
  cleanup() {
    try {
      this.ensureStateDir();
      
      const files = fs.readdirSync(this.config.stateDir)
        .filter(f => f.endsWith('.json'));

      const now = Date.now();
      let expiredCount = 0;
      let overflowCount = 0;
      const validStates = [];

      // First pass: remove expired and collect valid states
      for (const file of files) {
        const filePath = path.join(this.config.stateDir, file);
        try {
          const content = fs.readFileSync(filePath, 'utf-8');
          const state = JSON.parse(content);

          if (state.expiresAt && now > state.expiresAt) {
            fs.unlinkSync(filePath);
            expiredCount++;
          } else {
            validStates.push({
              file,
              filePath,
              savedAt: state.savedAt || 0
            });
          }
        } catch (parseError) {
          // Remove malformed files
          fs.unlinkSync(filePath);
          expiredCount++;
        }
      }

      // Second pass: enforce max states (remove oldest)
      if (validStates.length > this.config.maxStates) {
        validStates.sort((a, b) => a.savedAt - b.savedAt);
        const toRemove = validStates.slice(0, validStates.length - this.config.maxStates);
        
        for (const state of toRemove) {
          fs.unlinkSync(state.filePath);
          overflowCount++;
        }
      }

      const summary = {
        expiredRemoved: expiredCount,
        overflowRemoved: overflowCount,
        remaining: validStates.length - overflowCount,
        timestamp: new Date().toISOString()
      };

      if (expiredCount > 0 || overflowCount > 0) {
        console.log(`[ExecutionStateStore] Cleanup: removed ${expiredCount} expired, ${overflowCount} overflow`);
      }

      return summary;
    } catch (error) {
      console.error(`[ExecutionStateStore] Cleanup failed: ${error.message}`);
      return { error: error.message };
    }
  }

  /**
   * Get store statistics
   * @returns {Object} Store statistics
   */
  getStats() {
    try {
      const executions = this.list(true);
      const pending = executions.filter(e => e.status === 'pending');
      const expired = executions.filter(e => e.status === 'expired');

      return {
        stateDir: this.config.stateDir,
        ttlMs: this.config.ttlMs,
        maxStates: this.config.maxStates,
        totalStates: executions.length,
        pendingStates: pending.length,
        expiredStates: expired.length,
        timestamp: new Date().toISOString()
      };
    } catch (error) {
      return { error: error.message };
    }
  }
}

// Singleton instance for shared use
let defaultStore = null;

/**
 * Get default store instance
 * @param {Object} config - Optional configuration override
 * @returns {ExecutionStateStore}
 */
export function getDefaultStore(config = {}) {
  if (!defaultStore) {
    defaultStore = new ExecutionStateStore(config);
  }
  return defaultStore;
}

export default ExecutionStateStore;
