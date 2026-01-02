/**
 * MCPApprovalProvider - Approval via MCP multi-turn tool calls
 * 
 * For VS Code Copilot and Claude Desktop:
 * - Returns approval request as MCP response
 * - Waits for user's next message with approval decision
 * - Supports multi-turn conversation flow
 * - Uses persistent file storage for execution state
 * 
 * Version: 2.0.0
 * Phase: 4B - Interactive Supervised Development
 * Date: January 2, 2026
 */

import { 
  ApprovalProvider, 
  ApprovalResult, 
  ExecutionMode 
} from './ApprovalProvider.js';
import { getDefaultStore } from './ExecutionStateStore.js';

/**
 * MCP Approval Provider
 * Uses multi-turn MCP tool calls for approval flow
 * Now with persistent file-based state storage
 */
export class MCPApprovalProvider extends ApprovalProvider {
  constructor(options = {}) {
    super(options);
    this.executionId = options.executionId || null;
    this.pendingApproval = options.pendingApproval || null;
    this.stateStore = options.stateStore || getDefaultStore();
  }

  /**
   * Check provider capabilities
   */
  getCapabilities() {
    return {
      interactive: true,
      multiTurn: true,
      richPreview: true,
      diffView: false,  // Could be added later
      timeout: this.timeout
    };
  }

  /**
   * Check if provider is interactive
   */
  isInteractive() {
    return true;
  }

  /**
   * Request approval via MCP response
   * Returns PENDING with execution state to resume later
   * 
   * @param {Object} step - Step metadata
   * @param {Object} preview - Preview of what will happen
   * @returns {Promise<ApprovalResult|Object>}
   */
  async requestApproval(step, preview) {
    // If we have a pending approval decision from user, process it
    if (this.pendingApproval) {
      return this.processPendingApproval(step);
    }

    // Check deny list first
    if (this.denyTypes.includes(step.type)) {
      this.logAudit(step, 'denied', 'Step type in deny list');
      return ApprovalResult.SKIPPED;
    }

    // Store execution state and return pending
    this.logAudit(step, 'pending', 'Awaiting user approval');
    
    return {
      result: ApprovalResult.PENDING,
      preview: preview,
      formattedPreview: this.formatPreview(preview),
      approvalOptions: this.getApprovalOptions(step),
      message: this.generateApprovalMessage(step, preview)
    };
  }

  /**
   * Process a pending approval decision from user
   * @param {Object} step - Step that was pending
   * @returns {ApprovalResult}
   */
  processPendingApproval(step) {
    const decision = this.normalizeApprovalInput(this.pendingApproval);
    
    switch (decision) {
      case 'approved':
      case 'approve':
      case 'yes':
      case 'y':
      case 'a':
        this.logAudit(step, 'approved', 'User approved');
        return ApprovalResult.APPROVED;
      
      case 'skipped':
      case 'skip':
      case 's':
      case 'n':
      case 'no':
        this.logAudit(step, 'skipped', 'User skipped');
        return ApprovalResult.SKIPPED;
      
      case 'quit':
      case 'abort':
      case 'q':
      case 'cancel':
        this.logAudit(step, 'quit', 'User aborted workflow');
        return ApprovalResult.QUIT;
      
      case 'approve_all':
      case 'approveall':
      case 'all':
      case 'aa':
        this.approvedAll = true;
        this.logAudit(step, 'approve_all', 'User approved all remaining');
        return ApprovalResult.APPROVE_ALL;
      
      default:
        // Unrecognized input - treat as skip for safety
        this.logAudit(step, 'skipped', `Unrecognized input: ${this.pendingApproval}`);
        return ApprovalResult.SKIPPED;
    }
  }

  /**
   * Normalize user input to standard approval values
   * @param {string} input - User input
   * @returns {string} Normalized value
   */
  normalizeApprovalInput(input) {
    if (!input) return 'skipped';
    return input.toLowerCase().trim().replace(/[^a-z_]/g, '');
  }

  /**
   * Get approval options for display
   * @param {Object} step - Step metadata
   * @returns {Array} Available options
   */
  getApprovalOptions(step) {
    const options = [
      { key: 'approved', aliases: ['yes', 'y', 'a'], description: 'Execute this step' },
      { key: 'skipped', aliases: ['skip', 's', 'n', 'no'], description: 'Skip this step, continue workflow' },
      { key: 'quit', aliases: ['abort', 'q', 'cancel'], description: 'Abort entire workflow' },
      { key: 'approve_all', aliases: ['all', 'aa'], description: 'Approve all remaining steps' }
    ];

    return options;
  }

  /**
   * Generate approval message for MCP response
   * @param {Object} step - Step metadata
   * @param {Object} preview - Preview object
   * @returns {string} Message for user
   */
  generateApprovalMessage(step, preview) {
    const lines = [
      '',
      '⏸️ **APPROVAL REQUIRED**',
      '',
      this.formatPreview(preview),
      '',
      '**Options:**',
      '- `approved` (or `yes`, `y`, `a`) - Execute this step',
      '- `skipped` (or `skip`, `s`, `no`) - Skip and continue',
      '- `quit` (or `abort`, `q`) - Abort workflow',
      '- `approve_all` (or `all`) - Approve remaining steps',
      '',
      'Reply with your choice to continue.'
    ];

    return lines.join('\n');
  }

  /**
   * Save execution state for resumption (persistent)
   * @param {string} executionId - Unique execution ID
   * @param {Object} state - Execution state to save
   */
  static saveExecutionState(executionId, state) {
    const store = getDefaultStore();
    store.save(executionId, state);
  }

  /**
   * Load execution state for resumption (persistent)
   * @param {string} executionId - Execution ID to load
   * @returns {Object|null} Saved state or null
   */
  static loadExecutionState(executionId) {
    const store = getDefaultStore();
    return store.load(executionId);
  }

  /**
   * Clear execution state (persistent)
   * @param {string} executionId - Execution ID to clear
   */
  static clearExecutionState(executionId) {
    const store = getDefaultStore();
    store.delete(executionId);
  }

  /**
   * List pending executions (persistent)
   * @returns {Array} List of pending execution IDs
   */
  static listPendingExecutions() {
    const store = getDefaultStore();
    return store.list(false); // Only non-expired
  }

  /**
   * Get store statistics
   * @returns {Object} Store stats
   */
  static getStoreStats() {
    const store = getDefaultStore();
    return store.getStats();
  }

  /**
   * Run cleanup on persistent store
   * @returns {Object} Cleanup summary
   */
  static cleanupStates() {
    const store = getDefaultStore();
    return store.cleanup();
  }
}

export default MCPApprovalProvider;
