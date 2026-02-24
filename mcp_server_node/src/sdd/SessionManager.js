/**
 * SessionManager.js - Session-Oriented SDD Execution State Tracking
 * 
 * Replaces the Phase 4B approval-centric execution model with a lightweight
 * session-tracking model for IDE modality. Tracks which phase is active,
 * which steps are complete, and persists state across server restarts.
 * 
 * State files:
 * - active_session.json — current session state (single active session)
 * - history.jsonl — append-only event log for audit trail
 * 
 * Phase: 31 - SDD Execution Model Refactor
 * Date: February 2026
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// SDD Framework root - uses env var for container, falls back to relative path for local dev
const SDD_FRAMEWORK_ROOT = process.env.SDD_FRAMEWORK_ROOT || 
  path.join(__dirname, '../../../sdd_framework');

const STATE_DIR = path.join(SDD_FRAMEWORK_ROOT, 'execution_state');
const ACTIVE_SESSION_FILE = path.join(STATE_DIR, 'active_session.json');
const HISTORY_FILE = path.join(STATE_DIR, 'history.jsonl');
const CHECKPOINTS_DIR = path.join(STATE_DIR, 'checkpoints');

// Valid semantic step tags
const VALID_TAGS = ['research', 'design', 'implement', 'configure', 'validate', 'document', 'ingest'];

export class SessionManager {
  constructor() {
    this.ensureStateDir();
  }

  /**
   * Ensure state directory exists
   */
  ensureStateDir() {
    if (!fs.existsSync(STATE_DIR)) {
      fs.mkdirSync(STATE_DIR, { recursive: true });
    }
    if (!fs.existsSync(CHECKPOINTS_DIR)) {
      fs.mkdirSync(CHECKPOINTS_DIR, { recursive: true });
    }
  }

  /**
   * Start a new session for a phase
   * @param {string} phaseName - Phase name (e.g., "phase31_sdd_execution_model_refactor")
   * @param {Object} options - Optional metadata
   * @returns {Object} Session state
   */
  startSession(phaseName, options = {}) {
    // Check for existing active session
    const existing = this.getSessionState();
    if (existing) {
      throw new Error(
        `Active session already exists for "${existing.phase}". ` +
        `Complete or abandon it before starting a new one.`
      );
    }

    const now = new Date().toISOString();
    const sessionId = `session_${now.split('T')[0]}_${Math.random().toString(36).substr(2, 6)}`;

    // Parse step count from workflow spec if available
    const totalSteps = options.totalSteps || this._parseStepCount(phaseName);

    const session = {
      sessionId,
      phase: phaseName,
      startedAt: now,
      lastActivityAt: now,
      status: 'in_progress',
      currentStep: 0,
      totalSteps,
      completedSteps: [],
      skippedSteps: [],
      blockers: [],
      notes: options.notes || null,
      // Phase 24H-3: Session state tracking for agent workflows
      modifications: [],
      examined: [],
      checkpoints: []
    };

    // Write active session file
    this._writeSession(session);

    // Append to history log
    this._appendHistory({
      sessionId,
      phase: phaseName,
      event: 'started',
      timestamp: now
    });

    return session;
  }

  /**
   * Record a step completion
   * @param {number} stepNumber - Step number
   * @param {string} name - Step name/description
   * @param {string} tag - Semantic tag (research, implement, validate, etc.)
   * @param {string} notes - Optional completion notes
   * @returns {Object} Updated session state
   */
  recordStep(stepNumber, name, tag, notes = '') {
    const session = this.getSessionState();
    if (!session) {
      throw new Error('No active session. Call startSession first.');
    }

    // Validate tag
    if (tag && !VALID_TAGS.includes(tag)) {
      console.log(`[WARN] Unknown step tag "${tag}". Valid tags: ${VALID_TAGS.join(', ')}`);
    }

    const now = new Date().toISOString();

    // Check for duplicate step recording
    const alreadyRecorded = session.completedSteps.some(s => s.step === stepNumber);
    if (alreadyRecorded) {
      throw new Error(`Step ${stepNumber} already recorded as complete.`);
    }

    const stepRecord = {
      step: stepNumber,
      name,
      tag: tag || 'implement',
      completedAt: now,
      notes
    };

    session.completedSteps.push(stepRecord);
    session.currentStep = Math.max(session.currentStep, stepNumber);
    session.lastActivityAt = now;

    // Write updated session
    this._writeSession(session);

    // Append to history log
    this._appendHistory({
      sessionId: session.sessionId,
      phase: session.phase,
      event: 'step_completed',
      step: stepNumber,
      name,
      tag: stepRecord.tag,
      notes,
      timestamp: now
    });

    return session;
  }

  /**
   * Record a skipped step
   * @param {number} stepNumber - Step number
   * @param {string} reason - Why the step was skipped
   * @returns {Object} Updated session state
   */
  skipStep(stepNumber, reason = '') {
    const session = this.getSessionState();
    if (!session) {
      throw new Error('No active session. Call startSession first.');
    }

    const now = new Date().toISOString();

    session.skippedSteps.push({
      step: stepNumber,
      reason,
      skippedAt: now
    });
    session.lastActivityAt = now;

    this._writeSession(session);

    this._appendHistory({
      sessionId: session.sessionId,
      phase: session.phase,
      event: 'step_skipped',
      step: stepNumber,
      reason,
      timestamp: now
    });

    return session;
  }

  /**
   * Get current active session state
   * @returns {Object|null} Session state or null if no active session
   */
  getSessionState() {
    try {
      if (!fs.existsSync(ACTIVE_SESSION_FILE)) {
        return null;
      }
      const content = fs.readFileSync(ACTIVE_SESSION_FILE, 'utf-8');
      return JSON.parse(content);
    } catch (error) {
      console.log(`[WARN] Failed to read active session: ${error.message}`);
      return null;
    }
  }

  /**
   * Resume an existing session (alias for getSessionState with validation)
   * @returns {Object} Session state
   */
  resumeSession() {
    const session = this.getSessionState();
    if (!session) {
      throw new Error('No active session to resume.');
    }

    if (session.status !== 'in_progress') {
      throw new Error(`Session "${session.sessionId}" has status "${session.status}" and cannot be resumed.`);
    }

    // Update last activity timestamp
    const now = new Date().toISOString();
    session.lastActivityAt = now;
    this._writeSession(session);

    this._appendHistory({
      sessionId: session.sessionId,
      phase: session.phase,
      event: 'resumed',
      timestamp: now
    });

    return session;
  }

  /**
   * Complete the active session
   * @param {string} summary - Completion summary
   * @returns {Object} Final session state
   */
  completeSession(summary = '') {
    const session = this.getSessionState();
    if (!session) {
      throw new Error('No active session to complete.');
    }

    const now = new Date().toISOString();
    session.status = 'completed';
    session.completedAt = now;
    session.lastActivityAt = now;
    session.summary = summary;

    // Append completion event to history
    this._appendHistory({
      sessionId: session.sessionId,
      phase: session.phase,
      event: 'completed',
      summary,
      completedSteps: session.completedSteps.length,
      skippedSteps: session.skippedSteps.length,
      totalSteps: session.totalSteps,
      duration: this._calculateDuration(session.startedAt, now),
      timestamp: now
    });

    // Remove active session file (archived in history)
    try {
      fs.unlinkSync(ACTIVE_SESSION_FILE);
    } catch (e) {
      // File may not exist, that's fine
    }

    return session;
  }

  /**
   * Abandon the active session without completing it
   * @param {string} reason - Why the session was abandoned
   * @returns {Object} Final session state
   */
  abandonSession(reason = '') {
    const session = this.getSessionState();
    if (!session) {
      throw new Error('No active session to abandon.');
    }

    const now = new Date().toISOString();
    session.status = 'abandoned';
    session.abandonedAt = now;
    session.lastActivityAt = now;
    session.abandonReason = reason;

    this._appendHistory({
      sessionId: session.sessionId,
      phase: session.phase,
      event: 'abandoned',
      reason,
      completedSteps: session.completedSteps.length,
      timestamp: now
    });

    try {
      fs.unlinkSync(ACTIVE_SESSION_FILE);
    } catch (e) {
      // File may not exist
    }

    return session;
  }

  /**
   * Query execution history
   * @param {Object} options - Filter options
   * @param {string} options.phase - Filter by phase name
   * @param {string} options.event - Filter by event type
   * @param {number} options.limit - Max entries to return (default 50)
   * @returns {Array} History entries
   */
  getHistory(options = {}) {
    const { phase, event, limit = 50 } = options;

    try {
      if (!fs.existsSync(HISTORY_FILE)) {
        return [];
      }

      const content = fs.readFileSync(HISTORY_FILE, 'utf-8');
      const lines = content.split('\n').filter(l => l.trim());

      let entries = lines.map(line => {
        try {
          return JSON.parse(line);
        } catch (e) {
          return null;
        }
      }).filter(Boolean);

      // Apply filters
      if (phase) {
        entries = entries.filter(e => e.phase && e.phase.includes(phase));
      }
      if (event) {
        entries = entries.filter(e => e.event === event);
      }

      // Return most recent entries (tail of file)
      if (entries.length > limit) {
        entries = entries.slice(-limit);
      }

      return entries;
    } catch (error) {
      console.log(`[WARN] Failed to read history: ${error.message}`);
      return [];
    }
  }

  /**
   * Get a summary of all sessions from history
   * @returns {Array} Session summaries
   */
  getSessionSummaries() {
    const history = this.getHistory({ limit: 1000 });
    const sessions = {};

    for (const entry of history) {
      if (!sessions[entry.sessionId]) {
        sessions[entry.sessionId] = {
          sessionId: entry.sessionId,
          phase: entry.phase,
          events: []
        };
      }
      sessions[entry.sessionId].events.push(entry);
    }

    return Object.values(sessions).map(s => {
      const started = s.events.find(e => e.event === 'started');
      const completed = s.events.find(e => e.event === 'completed');
      const abandoned = s.events.find(e => e.event === 'abandoned');
      const stepsCompleted = s.events.filter(e => e.event === 'step_completed').length;

      return {
        sessionId: s.sessionId,
        phase: s.phase,
        status: completed ? 'completed' : abandoned ? 'abandoned' : 'in_progress',
        startedAt: started?.timestamp,
        completedAt: completed?.timestamp || abandoned?.timestamp,
        stepsCompleted,
        summary: completed?.summary || abandoned?.reason || null
      };
    });
  }

  // --- Phase 24H-3: Session State Methods ---

  /**
   * Record a file modification in the active session
   * @param {string} filePath - Path of the modified file
   * @param {string} changeType - Type of change (content, signature, delete, rename)
   * @param {string} description - What was changed
   * @returns {Object} Updated session state
   */
  markAsModified(filePath, changeType = 'content', description = '') {
    const session = this.getSessionState();
    if (!session) {
      throw new Error('No active session. Call startSession first.');
    }

    const now = new Date().toISOString();
    const modifications = session.modifications || [];

    modifications.push({
      filePath,
      changeType,
      description,
      modifiedAt: now
    });

    session.modifications = modifications;
    session.lastActivityAt = now;
    this._writeSession(session);

    this._appendHistory({
      sessionId: session.sessionId,
      phase: session.phase,
      event: 'file_modified',
      filePath,
      changeType,
      description,
      timestamp: now
    });

    return session;
  }

  /**
   * Record an examined symbol in the active session (deduplicated)
   * @param {string} symbol - Symbol name that was examined
   * @param {Object} context - Optional context about the examination
   * @returns {Object} Updated session state
   */
  recordExamined(symbol, context = {}) {
    const session = this.getSessionState();
    if (!session) {
      return null; // Silent — called internally from getCodeContext
    }

    const examined = session.examined || [];

    // Deduplicate by symbol name
    if (examined.some(e => e.symbol === symbol)) {
      return session;
    }

    const now = new Date().toISOString();
    examined.push({
      symbol,
      examinedAt: now,
      ...context
    });

    session.examined = examined;
    session.lastActivityAt = now;
    this._writeSession(session);

    this._appendHistory({
      sessionId: session.sessionId,
      phase: session.phase,
      event: 'symbol_examined',
      symbol,
      timestamp: now
    });

    return session;
  }

  /**
   * Create a checkpoint of the current session state
   * @param {string} name - Checkpoint name
   * @param {string} description - What this checkpoint represents
   * @returns {Object} Checkpoint metadata
   */
  createCheckpoint(name, description = '') {
    const session = this.getSessionState();
    if (!session) {
      throw new Error('No active session. Call startSession first.');
    }

    const now = new Date().toISOString();
    const checkpointId = `chk_${now.split('T')[0]}_${Math.random().toString(36).substr(2, 6)}`;

    const checkpoint = {
      checkpointId,
      name,
      description,
      createdAt: now,
      modifications: [...(session.modifications || [])],
      examined: [...(session.examined || [])],
      currentStep: session.currentStep,
      completedSteps: [...session.completedSteps]
    };

    // Write checkpoint file
    this.ensureStateDir();
    const checkpointFile = path.join(CHECKPOINTS_DIR, `${checkpointId}.json`);
    fs.writeFileSync(checkpointFile, JSON.stringify(checkpoint, null, 2), 'utf-8');

    // Record in session
    const checkpoints = session.checkpoints || [];
    checkpoints.push({
      checkpointId,
      name,
      description,
      createdAt: now
    });
    session.checkpoints = checkpoints;
    session.lastActivityAt = now;
    this._writeSession(session);

    this._appendHistory({
      sessionId: session.sessionId,
      phase: session.phase,
      event: 'checkpoint_created',
      checkpointId,
      name,
      description,
      timestamp: now
    });

    return checkpoint;
  }

  /**
   * Restore session state from a checkpoint
   * @param {string} checkpointId - Checkpoint ID to restore
   * @returns {Object} Updated session state
   */
  restoreCheckpoint(checkpointId) {
    const session = this.getSessionState();
    if (!session) {
      throw new Error('No active session. Call startSession first.');
    }

    const checkpointFile = path.join(CHECKPOINTS_DIR, `${checkpointId}.json`);
    if (!fs.existsSync(checkpointFile)) {
      throw new Error(`Checkpoint "${checkpointId}" not found.`);
    }

    const checkpoint = JSON.parse(fs.readFileSync(checkpointFile, 'utf-8'));
    const now = new Date().toISOString();

    // Restore session state from checkpoint
    session.modifications = checkpoint.modifications || [];
    session.examined = checkpoint.examined || [];
    session.lastActivityAt = now;
    this._writeSession(session);

    this._appendHistory({
      sessionId: session.sessionId,
      phase: session.phase,
      event: 'checkpoint_restored',
      checkpointId,
      name: checkpoint.name,
      timestamp: now
    });

    return session;
  }

  /**
   * Get aggregated session context for agent workflows
   * @returns {Object} Session context with examined, modifications, checkpoints
   */
  getSessionContext() {
    const session = this.getSessionState();
    if (!session) {
      return {
        active: false,
        message: 'No active session.'
      };
    }

    return {
      active: true,
      sessionId: session.sessionId,
      phase: session.phase,
      startedAt: session.startedAt,
      lastActivityAt: session.lastActivityAt,
      currentStep: session.currentStep,
      totalSteps: session.totalSteps,
      stepsCompleted: session.completedSteps.length,
      examined: session.examined || [],
      modifications: session.modifications || [],
      checkpoints: session.checkpoints || [],
      summary: {
        filesModified: (session.modifications || []).length,
        symbolsExamined: (session.examined || []).length,
        checkpointsCreated: (session.checkpoints || []).length,
        stepsCompleted: session.completedSteps.length,
        stepsRemaining: session.totalSteps - session.completedSteps.length
      }
    };
  }

  // --- Private helpers ---

  _writeSession(session) {
    this.ensureStateDir();
    fs.writeFileSync(ACTIVE_SESSION_FILE, JSON.stringify(session, null, 2), 'utf-8');
  }

  _appendHistory(entry) {
    this.ensureStateDir();
    const line = JSON.stringify(entry) + '\n';
    fs.appendFileSync(HISTORY_FILE, line, 'utf-8');
  }

  _parseStepCount(phaseName) {
    try {
      const workflowDir = path.join(SDD_FRAMEWORK_ROOT, 'workflows');
      const filePath = path.join(workflowDir, `${phaseName}.md`);
      if (!fs.existsSync(filePath)) {
        return 0;
      }
      const content = fs.readFileSync(filePath, 'utf-8');
      // Count "### Step N:" patterns
      const stepMatches = content.match(/###\s+Step\s+\d+:/g);
      return stepMatches ? stepMatches.length : 0;
    } catch (e) {
      return 0;
    }
  }

  _calculateDuration(startIso, endIso) {
    const start = new Date(startIso).getTime();
    const end = new Date(endIso).getTime();
    const durationMs = end - start;
    const minutes = Math.floor(durationMs / 60000);
    const hours = Math.floor(minutes / 60);
    if (hours > 0) {
      return `${hours}h ${minutes % 60}m`;
    }
    return `${minutes}m`;
  }
}
