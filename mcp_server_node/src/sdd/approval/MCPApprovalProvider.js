/**
 * MCPApprovalProvider - Approval via MCP multi-turn tool calls
 * 
 * For VS Code Copilot and Claude Desktop:
 * - Returns approval request as MCP response
 * - Waits for user's next message with approval decision
 * - Supports multi-turn conversation flow
 * 
 * Version: 1.0.0
 * Phase: 4B - Interactive Supervised Execution
 * Date: December 5, 2025
 */

import { 
  ApprovalProvider, 
  ApprovalResult, 
  ExecutionMode 
} from './ApprovalProvider.js';

/**
 * Pending execution state storage
 * Maps execution IDs to their state
 */
const pendingExecutions = new Map();

/**
 * MCP Approval Provider
 * Uses multi-turn MCP tool calls for approval flow
 */
export class MCPApprovalProvider extends ApprovalProvider {
  constructor(options = {}) {
    super(options);
    this.executionId = options.executionId || null;
    this.pendingApproval = options.pendingApproval || null;
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
   * Save execution state for resumption
   * @param {string} executionId - Unique execution ID
   * @param {Object} state - Execution state to save
   */
  static saveExecutionState(executionId, state) {
    pendingExecutions.set(executionId, {
      ...state,
      savedAt: Date.now()
    });

    // Clean up old executions (older than timeout)
    const timeout = 300000; // 5 minutes
    for (const [id, exec] of pendingExecutions.entries()) {
      if (Date.now() - exec.savedAt > timeout) {
        pendingExecutions.delete(id);
      }
    }
  }

  /**
   * Load execution state for resumption
   * @param {string} executionId - Execution ID to load
   * @returns {Object|null} Saved state or null
   */
  static loadExecutionState(executionId) {
    const state = pendingExecutions.get(executionId);
    if (!state) return null;

    // Check if expired
    const timeout = 300000; // 5 minutes
    if (Date.now() - state.savedAt > timeout) {
      pendingExecutions.delete(executionId);
      return null;
    }

    return state;
  }

  /**
   * Clear execution state
   * @param {string} executionId - Execution ID to clear
   */
  static clearExecutionState(executionId) {
    pendingExecutions.delete(executionId);
  }

  /**
   * List pending executions
   * @returns {Array} List of pending execution IDs
   */
  static listPendingExecutions() {
    const result = [];
    for (const [id, state] of pendingExecutions.entries()) {
      result.push({
        executionId: id,
        workflowName: state.workflowName,
        currentStep: state.currentStepIndex,
        totalSteps: state.totalSteps,
        savedAt: new Date(state.savedAt).toISOString()
      });
    }
    return result;
  }
}

export default MCPApprovalProvider;
