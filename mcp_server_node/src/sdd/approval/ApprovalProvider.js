/**
 * ApprovalProvider - Abstract base class for workflow step approval
 * 
 * Provides the interface for different approval mechanisms:
 * - MCPApprovalProvider: Multi-turn MCP tool calls (VS Code Copilot, Claude Desktop)
 * - CLIApprovalProvider: Terminal readline prompts (Claude Code, SSH)
 * - ManifestApprovalProvider: Pre-approved patterns from YAML/JSON files
 * 
 * Version: 2.0.0 - Verb+Noun Paradigm
 * Phase: 4C - Unified Step Type Vocabulary
 * Date: January 8, 2026
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
 * VERB+NOUN PARADIGM (v2.0)
 * 
 * Step types follow the pattern: <verb>_<noun>
 * - VERB determines approval policy (HOW content comes to exist)
 * - NOUN clarifies the target (WHERE/WHAT)
 * 
 * Examples: generate_file, write_file, execute_command, validate_service
 */

/**
 * Verbs that require approval (have side effects)
 */
export const SIDE_EFFECT_VERBS = [
  'generate',   // Non-deterministic content creation (LLM synthesis)
  'write',      // File system modification (literal copy)
  'execute',    // Command/script execution
  'delete',     // Destructive operations
  'ingest'      // Knowledge base updates
];

/**
 * Verbs that are read-only (no approval needed)
 */
export const READ_ONLY_VERBS = [
  'read',       // Data queries
  'validate',   // Condition checks
  'check',      // Status inspection
  'analyze'     // Analysis without modification
];

/**
 * LEGACY SUPPORT: Map old noun-centric types to verb+noun equivalents
 * These are recognized for backward compatibility with existing workflows
 */
export const LEGACY_TYPE_MAP = {
  // Old side-effect types
  'code_generation': 'generate_file',
  'code_modification': 'generate_patch',
  'command': 'execute_command',
  'ingestion': 'execute_ingest',
  'file_delete': 'delete_file',
  'git_operation': 'execute_git',
  // Old intent-vocabulary types (previously unrecognized!)
  'file_creation': 'write_file',
  'file_modification': 'write_patch',
  'shell_command': 'execute_command',
  'docker_operation': 'execute_command',
  // Old read-only types
  'health_check': 'check_health',
  'data_query': 'read_query',
  'validation': 'validate_result',
  'analysis': 'read_analysis'
};

/**
 * LEGACY SUPPORT: Old arrays for imports that use them
 * @deprecated Use getVerb() and SIDE_EFFECT_VERBS instead
 */
export const SIDE_EFFECT_TYPES = [
  // New verb_noun patterns
  'generate_file', 'generate_patch', 'generate_config',
  'write_file', 'write_patch', 'write_config',
  'execute_command', 'execute_git', 'execute_ingest',
  'delete_file', 'delete_directory',
  // Legacy patterns (for backward compat)
  'code_generation', 'code_modification', 'command',
  'ingestion', 'file_delete', 'git_operation',
  'file_creation', 'file_modification'
];

/**
 * @deprecated Use getVerb() and READ_ONLY_VERBS instead
 */
export const READ_ONLY_TYPES = [
  // New verb_noun patterns
  'read_query', 'read_file', 'read_analysis',
  'validate_result', 'validate_service', 'validate_health',
  'check_health', 'check_status',
  'analyze_code', 'analyze_structure',
  // Legacy patterns
  'health_check', 'data_query', 'validation', 'analysis'
];

/**
 * Extract verb from step type
 * Handles both verb_noun format and legacy types
 * @param {string} stepType - Step type (e.g., 'generate_file' or 'code_generation')
 * @returns {string} The verb component
 */
export function getVerb(stepType) {
  if (!stepType) return 'unknown';
  
  const normalizedType = stepType.toLowerCase();
  
  // If legacy type, map it first
  const mappedType = LEGACY_TYPE_MAP[normalizedType] || normalizedType;
  
  // Extract verb (first segment before underscore)
  const verb = mappedType.split('_')[0];
  
  return verb;
}

/**
 * Check if step type has side effects based on its verb
 * @param {string} stepType - Step type
 * @returns {boolean}
 */
export function hasSideEffects(stepType) {
  const verb = getVerb(stepType);
  return SIDE_EFFECT_VERBS.includes(verb);
}

/**
 * Check if step type is read-only based on its verb
 * @param {string} stepType - Step type
 * @returns {boolean}
 */
export function isReadOnly(stepType) {
  const verb = getVerb(stepType);
  return READ_ONLY_VERBS.includes(verb);
}

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
   * Uses verb-based logic (v2.0 paradigm)
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

    // V2.0: Use verb-based logic
    // Read-only verbs don't need approval
    if (isReadOnly(step.type)) {
      return false;
    }

    // Side-effect verbs require approval
    return hasSideEffects(step.type);
  }

  /**
   * Generate preview for step - what will happen if approved
   * Supports both verb_noun format and legacy types
   * @param {Object} step - Step metadata
   * @returns {Object} Preview object
   */
  generatePreview(step) {
    const verb = getVerb(step.type);
    const preview = {
      stepName: step.name,
      stepType: step.type,
      verb: verb,
      hasSideEffects: hasSideEffects(step.type),
      timestamp: new Date().toISOString()
    };

    // Match on verb for consistent handling of both new and legacy types
    switch (verb) {
      case 'generate':
        return {
          ...preview,
          action: 'GENERATE (LLM synthesis)',
          target: step.target || step.file,
          intent: step.intent || step.description,
          contentPreview: step.content?.substring(0, 500),
          contentLength: step.content?.length || 0,
          truncated: (step.content?.length || 0) > 500,
          modality: 'generative'
        };

      case 'write':
        return {
          ...preview,
          action: 'WRITE (literal copy)',
          target: step.target || step.file,
          contentPreview: step.content?.substring(0, 500),
          contentLength: step.content?.length || 0,
          truncated: (step.content?.length || 0) > 500,
          modality: 'literal'
        };

      case 'execute':
        return {
          ...preview,
          action: 'EXECUTE COMMAND',
          command: step.command || step.content,
          workingDirectory: step.cwd || 'repository root',
          sandbox: step.sandbox !== false,
          timeout: step.timeout || 30000,
          riskLevel: this.assessCommandRisk(step.command || step.content)
        };

      case 'delete':
        return {
          ...preview,
          action: 'DELETE',
          target: step.target || step.file,
          riskLevel: 'high'
        };

      case 'ingest':
        return {
          ...preview,
          action: 'INGEST TO KNOWLEDGE BASE',
          target: step.target || 'all',
          source: step.source,
          collections: step.collections || ['default']
        };

      case 'read':
        return {
          ...preview,
          action: 'READ (query)',
          query: step.query,
          readOnly: true
        };

      case 'validate':
        return {
          ...preview,
          action: 'VALIDATE',
          target: step.target,
          checks: step.checks?.map(c => c.type) || [],
          readOnly: true
        };

      case 'check':
        return {
          ...preview,
          action: 'CHECK STATUS',
          components: step.components || step.target || ['all'],
          readOnly: true
        };

      case 'analyze':
        return {
          ...preview,
          action: 'ANALYZE',
          target: step.target,
          readOnly: true
        };

      default:
        // Fallback for any unrecognized types
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
