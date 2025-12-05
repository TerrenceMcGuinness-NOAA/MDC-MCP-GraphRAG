/**
 * ApprovalProvider - Abstract base class for workflow step approval
 * 
 * Provides the interface for different approval mechanisms:
 * - MCPApprovalProvider: Multi-turn MCP tool calls (VS Code Copilot, Claude Desktop)
 * - CLIApprovalProvider: Terminal readline prompts (Claude Code, SSH)
 * - ManifestApprovalProvider: Pre-approved patterns from YAML/JSON files
 * 
 * Version: 1.0.0
 * Phase: 4B - Interactive Supervised Execution
 * Date: December 5, 2025
 */

/**
 * Approval result enum
 */
export const ApprovalResult = {
  APPROVED: 'approved',       // Execute the step
  SKIPPED: 'skipped',         // Skip this step, continue workflow
  QUIT: 'quit',               // Abort entire workflow
  APPROVE_ALL: 'approve_all', // Approve this and all remaining steps
  PENDING: 'pending'          // Awaiting user response (MCP multi-turn)
};

/**
 * Execution modes enum
 */
export const ExecutionMode = {
  DRY_RUN: 'dry_run',           // Preview only, no side effects
  SUPERVISED: 'supervised',      // Human approves each side-effect step
  AUTO_APPROVED: 'auto_approved', // Pre-approved via manifest
  AUTONOMOUS: 'autonomous'       // Full automation (disabled for safety)
};

/**
 * Step types that require approval (have side effects)
 */
export const SIDE_EFFECT_TYPES = [
  'code_generation',
  'code_modification', 
  'command',
  'ingestion',
  'file_delete',
  'git_operation'
];

/**
 * Step types that are read-only (no approval needed)
 */
export const READ_ONLY_TYPES = [
  'health_check',
  'data_query',
  'validation',
  'analysis'
];

/**
 * Abstract Approval Provider
 * Base class for different approval mechanisms
 */
export class ApprovalProvider {
  constructor(options = {}) {
    this.options = options;
    this.approvedAll = false;
    this.executionMode = options.mode || ExecutionMode.SUPERVISED;
    this.autoApproveTypes = options.autoApproveTypes || [];
    this.denyTypes = options.denyTypes || [];
    this.timeout = options.timeout || 300000; // 5 minutes default
    this.auditLog = [];
  }

  /**
   * Check if step requires approval based on type and mode
   * @param {Object} step - Step metadata
   * @returns {boolean}
   */
  requiresApproval(step) {
    // Dry run never executes, so no approval needed (just preview)
    if (this.executionMode === ExecutionMode.DRY_RUN) {
      return false;
    }

    // Autonomous mode skips all approvals (disabled for safety-critical)
    if (this.executionMode === ExecutionMode.AUTONOMOUS) {
      return false;
    }

    // If user approved all remaining, skip approval
    if (this.approvedAll) {
      return false;
    }

    // Check if type is auto-approved
    if (this.autoApproveTypes.includes(step.type)) {
      this.logAudit(step, 'auto_approved', 'Step type in auto-approve list');
      return false;
    }

    // Check if type is denied (will be rejected, but still needs to go through approval flow)
    if (this.denyTypes.includes(step.type)) {
      return true; // Will be denied in approval
    }

    // Read-only steps don't need approval
    if (READ_ONLY_TYPES.includes(step.type)) {
      return false;
    }

    // Side-effect steps require approval
    return SIDE_EFFECT_TYPES.includes(step.type);
  }

  /**
   * Generate preview for step - what will happen if approved
   * @param {Object} step - Step metadata
   * @returns {Object} Preview object
   */
  generatePreview(step) {
    const preview = {
      stepName: step.name,
      stepType: step.type,
      hasSideEffects: SIDE_EFFECT_TYPES.includes(step.type),
      timestamp: new Date().toISOString()
    };

    switch (step.type) {
      case 'code_generation':
        return {
          ...preview,
          action: 'CREATE FILE',
          target: step.target || step.file,
          contentPreview: step.content?.substring(0, 500),
          contentLength: step.content?.length || 0,
          truncated: (step.content?.length || 0) > 500
        };

      case 'code_modification':
        return {
          ...preview,
          action: 'MODIFY FILE',
          target: step.file || step.target,
          modification: step.action || step.operation,
          description: step.description
        };

      case 'command':
        return {
          ...preview,
          action: 'RUN COMMAND',
          command: step.command,
          workingDirectory: step.cwd || 'repository root',
          sandbox: step.sandbox !== false,
          timeout: step.timeout || 30000,
          riskLevel: this.assessCommandRisk(step.command)
        };

      case 'ingestion':
        return {
          ...preview,
          action: 'UPDATE KNOWLEDGE BASE',
          target: step.target || 'all',
          source: step.source,
          collections: step.collections || ['default']
        };

      case 'file_delete':
        return {
          ...preview,
          action: 'DELETE FILE',
          target: step.target || step.file,
          riskLevel: 'high'
        };

      case 'git_operation':
        return {
          ...preview,
          action: 'GIT OPERATION',
          operation: step.operation,
          target: step.target,
          riskLevel: step.operation === 'push' ? 'high' : 'medium'
        };

      case 'health_check':
        return {
          ...preview,
          action: 'CHECK HEALTH',
          components: step.components || ['all'],
          readOnly: true
        };

      case 'data_query':
        return {
          ...preview,
          action: 'QUERY DATA',
          query: step.query,
          readOnly: true
        };

      case 'validation':
        return {
          ...preview,
          action: 'VALIDATE',
          checks: step.checks?.map(c => c.type) || [],
          readOnly: true
        };

      default:
        return {
          ...preview,
          action: step.type?.toUpperCase() || 'UNKNOWN',
          description: step.description
        };
    }
  }

  /**
   * Assess risk level of a command
   * @param {string} command - Command string
   * @returns {string} Risk level: low, medium, high
   */
  assessCommandRisk(command) {
    if (!command) return 'low';
    
    const lowerCmd = command.toLowerCase();
    
    // High risk patterns
    if (lowerCmd.includes('rm -rf') ||
        lowerCmd.includes('sudo') ||
        lowerCmd.includes('chmod 777') ||
        lowerCmd.includes('> /dev/') ||
        lowerCmd.includes('mkfs') ||
        lowerCmd.includes('dd if=')) {
      return 'high';
    }
    
    // Medium risk patterns
    if (lowerCmd.includes('rm ') ||
        lowerCmd.includes('mv ') ||
        lowerCmd.includes('git push') ||
        lowerCmd.includes('npm publish') ||
        lowerCmd.includes('pip install')) {
      return 'medium';
    }
    
    return 'low';
  }

  /**
   * Format preview for display
   * @param {Object} preview - Preview object
   * @returns {string} Formatted string for display
   */
  formatPreview(preview) {
    const lines = [
      `┌─────────────────────────────────────────────────────────────`,
      `│ STEP: ${preview.stepName}`,
      `│ TYPE: ${preview.stepType}`,
      `│ ACTION: ${preview.action}`,
    ];

    if (preview.target) {
      lines.push(`│ TARGET: ${preview.target}`);
    }

    if (preview.command) {
      lines.push(`│ COMMAND: ${preview.command}`);
    }

    if (preview.riskLevel) {
      const riskIcon = preview.riskLevel === 'high' ? '[!]' : 
                       preview.riskLevel === 'medium' ? '[~]' : '[.]';
      lines.push(`│ RISK: ${riskIcon} ${preview.riskLevel.toUpperCase()}`);
    }

    if (preview.contentPreview) {
      lines.push(`│ CONTENT PREVIEW:`);
      const contentLines = preview.contentPreview.split('\n').slice(0, 10);
      contentLines.forEach(line => {
        lines.push(`│   ${line.substring(0, 60)}`);
      });
      if (preview.truncated) {
        lines.push(`│   ... (${preview.contentLength} total characters)`);
      }
    }

    lines.push(`└─────────────────────────────────────────────────────────────`);
    
    return lines.join('\n');
  }

  /**
   * Log approval decision for audit trail
   * @param {Object} step - Step metadata
   * @param {string} decision - Approval decision
   * @param {string} reason - Reason for decision
   */
  logAudit(step, decision, reason = '') {
    this.auditLog.push({
      timestamp: new Date().toISOString(),
      stepName: step.name,
      stepType: step.type,
      decision,
      reason,
      executionMode: this.executionMode
    });
  }

  /**
   * Get audit log
   * @returns {Array} Audit log entries
   */
  getAuditLog() {
    return [...this.auditLog];
  }

  /**
   * Request approval - MUST be implemented by subclasses
   * @param {Object} step - Step metadata
   * @param {Object} preview - Preview of what will happen
   * @returns {Promise<ApprovalResult>}
   */
  async requestApproval(step, preview) {
    throw new Error('requestApproval must be implemented by subclass');
  }

  /**
   * Check provider capabilities
   * @returns {Object} Capability flags
   */
  getCapabilities() {
    return {
      interactive: false,
      multiTurn: false,
      richPreview: false,
      diffView: false,
      timeout: this.timeout
    };
  }

  /**
   * Check if provider is interactive (can request user input)
   * @returns {boolean}
   */
  isInteractive() {
    return false;
  }
}

export default ApprovalProvider;
