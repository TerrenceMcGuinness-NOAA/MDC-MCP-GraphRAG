/**
 * SDD Workflow Tools
 * MCP tools for session-oriented SDD workflow tracking
 * 
 * Version: 4.0.0 - Phase 31: Session-Oriented Execution Model
 * Date: February 18, 2026
 * 
 * Replaces the Phase 4B approval-centric tools (execute_sdd_workflow,
 * execute_sdd_workflow_supervised, manage_sdd_execution_state) with
 * session tracking tools (start_sdd_session, record_sdd_step,
 * get_sdd_session, complete_sdd_session).
 * 
 * The ISD approval infrastructure is preserved in src/sdd/approval/
 * for future CLI/YOLO modality (Phase 4C USD).
 */

import { WorkflowExecutor } from '../sdd/WorkflowExecutor.js';
import { SessionManager } from '../sdd/SessionManager.js';
import { ContentResolver } from '../utils/ContentResolver.js';

export class SDDWorkflowTools {
  constructor(dataAccess, healthMonitor = null, sessionManager = null) {
    this.dataAccess = dataAccess;
    this.healthMonitor = healthMonitor;
    this.executor = new WorkflowExecutor(dataAccess, healthMonitor);
    this.sessionManager = sessionManager || new SessionManager();
  }

  /**
   * Register all SDD workflow tools
   */
  registerTools(server) {
    // Tool 1: List available workflows
    server.registerTool(
      'list_sdd_workflows',
      'List all available SDD framework workflows',
      {
        type: 'object',
        properties: {
          include_metadata: {
            type: 'boolean',
            description: 'Include workflow metadata',
            default: false
          }
        }
      },
      this.listWorkflows.bind(this)
    );

    // Tool 2: Get workflow details
    server.registerTool(
      'get_sdd_workflow',
      'Get detailed information about a specific SDD workflow',
      {
        type: 'object',
        properties: {
          workflow_name: {
            type: 'string',
            description: 'Name of the workflow (e.g., data_ingestion_workflow)'
          }
        },
        required: ['workflow_name']
      },
      this.getWorkflow.bind(this)
    );

    // Tool 3: Start SDD session (Phase 31: replaces execute_sdd_workflow)
    server.registerTool(
      'start_sdd_session',
      'Start a new SDD session for a phase. Activates tracking for step completions.',
      {
        type: 'object',
        properties: {
          phase: {
            type: 'string',
            description: 'Phase name (e.g., "phase31_sdd_execution_model_refactor")'
          },
          notes: {
            type: 'string',
            description: 'Optional session notes'
          },
          total_steps: {
            type: 'number',
            description: 'Override total step count (auto-detected from spec if omitted)'
          }
        },
        required: ['phase']
      },
      this.startSession.bind(this)
    );

    // Tool 4: Get execution history
    server.registerTool(
      'get_sdd_execution_history',
      'Get history of SDD workflow executions',
      {
        type: 'object',
        properties: {
          limit: {
            type: 'number',
            description: 'Number of recent executions to return',
            default: 10
          },
          workflow_name: {
            type: 'string',
            description: 'Filter by workflow name (optional)'
          }
        }
      },
      this.getExecutionHistory.bind(this)
    );

    // Tool 5: Validate SDD compliance (Phase 19A: Content Abstraction)
    server.registerTool(
      'validate_sdd_compliance',
      'Validate code or documentation against SDD framework standards. Supports both direct content and file paths.',
      {
        type: 'object',
        properties: {
          content: {
            type: 'string',
            description: 'Code/text content to validate directly (preferred for remote MCP access)'
          },
          target: {
            type: 'string',
            description: 'File path to validate (local mode only - use content for remote)'
          },
          framework_version: {
            type: 'string',
            description: 'SDD framework version',
            default: '4.0'
          },
          content_type: {
            type: 'string',
            enum: ['bash', 'python', 'yaml', 'json', 'markdown', 'auto'],
            description: 'Content type hint for parser selection',
            default: 'auto'
          }
        }
      },
      this.validateCompliance.bind(this)
    );

    // Tool 6: Get SDD framework status
    server.registerTool(
      'get_sdd_framework_status',
      'Get comprehensive status of SDD framework integration',
      {
        type: 'object',
        properties: {
          detailed: {
            type: 'boolean',
            description: 'Include detailed metrics',
            default: false
          }
        }
      },
      this.getFrameworkStatus.bind(this)
    );

    // Tool 7: Record SDD step (Phase 31: replaces execute_sdd_workflow_supervised)
    server.registerTool(
      'record_sdd_step',
      'Record completion of a step in the active SDD session.',
      {
        type: 'object',
        properties: {
          step: {
            type: 'number',
            description: 'Step number'
          },
          name: {
            type: 'string',
            description: 'Step name/description'
          },
          tag: {
            type: 'string',
            enum: ['research', 'design', 'implement', 'configure', 'validate', 'document', 'ingest'],
            description: 'Semantic step tag',
            default: 'implement'
          },
          notes: {
            type: 'string',
            description: 'Completion notes'
          }
        },
        required: ['step', 'name']
      },
      this.recordStep.bind(this)
    );

    // Tool 8: Get SDD session (Phase 31: replaces manage_sdd_execution_state)
    server.registerTool(
      'get_sdd_session',
      'Get the current active SDD session state. Returns null if no session is active. Use to resume work across conversations.',
      {
        type: 'object',
        properties: {
          resume: {
            type: 'boolean',
            description: 'If true, marks the session as resumed (updates lastActivityAt)',
            default: false
          }
        }
      },
      this.getSession.bind(this)
    );

    // Tool 9: Complete SDD session (Phase 31: new)
    server.registerTool(
      'complete_sdd_session',
      'Complete the active SDD session. Archives state and records completion in history.',
      {
        type: 'object',
        properties: {
          summary: {
            type: 'string',
            description: 'Completion summary'
          },
          abandon: {
            type: 'boolean',
            description: 'If true, abandons the session instead of completing it',
            default: false
          },
          reason: {
            type: 'string',
            description: 'Reason for abandoning (only used with abandon=true)'
          }
        }
      },
      this.completeSession.bind(this)
    );
  }

  /**
   * List available workflows
   */
  async listWorkflows(args = {}) {
    const { include_metadata = false } = args;

    try {
      const workflows = await this.executor.listWorkflows();
      
      let output = '# Available SDD Workflows\n\n';
      output += `Found ${workflows.length} workflows\n\n`;

      for (const workflow of workflows) {
        output += `## ${workflow.name}\n`;
        output += `- **Path**: ${workflow.path}\n`;
        output += `- **Size**: ${workflow.size} bytes\n`;
        
        if (include_metadata) {
          try {
            const details = await this.executor.parseWorkflow(workflow.name);
            output += `- **Title**: ${details.title}\n`;
            output += `- **Phases**: ${details.phases.length}\n`;
            output += `- **Steps**: ${details.steps.length}\n`;
          } catch (error) {
            output += `- **Error**: Could not parse metadata\n`;
          }
        }
        
        output += '\n';
      }

      return { content: [{ type: 'text', text: output }] };

    } catch (error) {
      return {
        content: [{
          type: 'text',
          text: `[ERROR] Failed to list workflows: ${error.message}`
        }]
      };
    }
  }

  /**
   * Get workflow details
   */
  async getWorkflow(args) {
    // Phase 29: accept workflow_id and phase as aliases for workflow_name
    const workflow_name = args.workflow_name || args.workflow_id || args.phase;

    try {
      const workflow = await this.executor.parseWorkflow(workflow_name);
      
      let output = `# ${workflow.title}\n\n`;
      output += `**Workflow**: ${workflow.name}\n\n`;
      
      if (workflow.description) {
        output += `## Description\n${workflow.description}\n\n`;
      }

      if (workflow.phases.length > 0) {
        output += `## Phases (${workflow.phases.length})\n\n`;
        for (const phase of workflow.phases) {
          output += `${phase.number}. ${phase.name}\n`;
        }
        output += '\n';
      }

      if (workflow.steps.length > 0) {
        output += `## Steps (${workflow.steps.length})\n\n`;
        for (const step of workflow.steps) {
          output += `### Step ${step.number}: ${step.name}\n`;
          output += `- **Type**: ${step.type}\n`;
          output += `- **Required**: ${step.required}\n`;
          if (step.description) {
            output += `- **Description**: ${step.description.substring(0, 200)}...\n`;
          }
          output += '\n';
        }
      }

      if (Object.keys(workflow.metadata).length > 0) {
        output += `## Metadata\n\n`;
        for (const [key, value] of Object.entries(workflow.metadata)) {
          output += `- **${key}**: ${value}\n`;
        }
      }

      return { content: [{ type: 'text', text: output }] };

    } catch (error) {
      return {
        content: [{
          type: 'text',
          text: `[ERROR] Failed to get workflow: ${error.message}`
        }]
      };
    }
  }

  /**
   * Start a new SDD session (Phase 31)
   */
  async startSession(args) {
    const { phase, notes, total_steps } = args;

    try {
      const options = {};
      if (notes) options.notes = notes;
      if (total_steps) options.totalSteps = total_steps;

      const session = this.sessionManager.startSession(phase, options);

      let output = `# SDD Session Started\n\n`;
      output += `**Session ID**: ${session.sessionId}\n`;
      output += `**Phase**: ${session.phase}\n`;
      output += `**Started**: ${session.startedAt}\n`;
      output += `**Total Steps**: ${session.totalSteps || 'unknown'}\n`;

      if (session.notes) {
        output += `**Notes**: ${session.notes}\n`;
      }

      output += `\n## Next Steps\n\n`;
      output += `- Use \`record_sdd_step\` to mark steps complete as you work\n`;
      output += `- Use \`get_sdd_session\` to check current progress\n`;
      output += `- Use \`complete_sdd_session\` when finished\n`;

      return { content: [{ type: 'text', text: output }] };

    } catch (error) {
      return {
        content: [{
          type: 'text',
          text: `[ERROR] Failed to start session: ${error.message}`
        }]
      };
    }
  }

  /**
   * Get execution history from JSONL log (Phase 31: rewritten)
   */
  async getExecutionHistory(args = {}) {
    const { limit = 10, workflow_name } = args;

    try {
      const history = this.sessionManager.getHistory({
        phase: workflow_name,
        limit
      });

      let output = '# SDD Session History\n\n';

      if (history.length === 0) {
        output += '*No session history found.*\n';
        return { content: [{ type: 'text', text: output }] };
      }

      output += `Showing ${history.length} recent events\n\n`;

      // Group by session
      const sessions = {};
      for (const entry of history) {
        if (!sessions[entry.sessionId]) {
          sessions[entry.sessionId] = [];
        }
        sessions[entry.sessionId].push(entry);
      }

      for (const [sessionId, events] of Object.entries(sessions)) {
        const started = events.find(e => e.event === 'started');
        const completed = events.find(e => e.event === 'completed');
        const abandoned = events.find(e => e.event === 'abandoned');
        const steps = events.filter(e => e.event === 'step_completed');

        const status = completed ? 'completed' : abandoned ? 'abandoned' : 'in_progress';
        const statusIcon = status === 'completed' ? '[OK]' :
                          status === 'abandoned' ? '[!!]' : '[..]';

        output += `## ${statusIcon} ${started?.phase || 'unknown'}\n`;
        output += `- **Session**: ${sessionId}\n`;
        output += `- **Status**: ${status}\n`;
        output += `- **Started**: ${started?.timestamp || 'unknown'}\n`;

        if (completed) {
          output += `- **Completed**: ${completed.timestamp}\n`;
          output += `- **Duration**: ${completed.duration || 'unknown'}\n`;
          if (completed.summary) {
            output += `- **Summary**: ${completed.summary}\n`;
          }
        }

        if (steps.length > 0) {
          output += `- **Steps Completed**: ${steps.length}\n`;
        }

        output += '\n';
      }

      return { content: [{ type: 'text', text: output }] };

    } catch (error) {
      return {
        content: [{
          type: 'text',
          text: `[ERROR] Failed to get history: ${error.message}`
        }]
      };
    }
  }

  /**
   * Validate SDD compliance (Phase 19A: Content Abstraction Layer)
   * Supports both direct content and file path input
   */
  async validateCompliance(args) {
    const { framework_version = '4.0' } = args;
    
    // Use ContentResolver for unified content access
    const resolver = new ContentResolver({ throwOnPathError: false });
    let resolved;
    
    try {
      resolved = await resolver.resolve(args);
    } catch (err) {
      return {
        content: [{
          type: 'text',
          text: `[ERROR] Content resolution failed: ${err.message}\n\n` +
                `**Tip**: For remote MCP access, use the 'content' parameter instead of 'target'.\n` +
                `Example: validate_sdd_compliance({ content: "your code here" })`
        }]
      };
    }
    
    // Handle resolution errors gracefully
    if (resolved.type === 'error') {
      return {
        content: [{
          type: 'text',
          text: `[ERROR] ${resolved.metadata.error}\n\n` +
                `**Suggestion**: ${resolved.metadata.suggestion}`
        }]
      };
    }
    
    // Build output
    let output = '# SDD Compliance Validation\n\n';
    output += `**Framework Version**: ${framework_version}\n`;
    output += `**Content Type**: ${resolved.contentType}\n`;
    output += `**Source**: ${resolved.source}\n`;
    
    if (resolved.metadata.originalPath) {
      output += `**Path**: ${resolved.metadata.originalPath}\n`;
    }
    if (resolved.metadata.lineCount) {
      output += `**Lines**: ${resolved.metadata.lineCount}\n`;
    }
    if (resolved.metadata.fileCount) {
      output += `**Files**: ${resolved.metadata.fileCount}\n`;
    }
    
    output += `\n## Validation Results\n\n`;
    
    // Perform basic SDD compliance checks
    const content = ContentResolver.getAllContent(resolved);
    const checks = this.performSDDChecks(content, resolved.contentType);
    
    for (const check of checks) {
      const icon = check.status === 'pass' ? '[OK]' : 
                   check.status === 'warn' ? '[WARN]' : '[ERROR]';
      output += `- ${icon} **${check.name}**: ${check.message}\n`;
    }
    
    output += `\n## Summary\n\n`;
    const passed = checks.filter(c => c.status === 'pass').length;
    const warnings = checks.filter(c => c.status === 'warn').length;
    const failed = checks.filter(c => c.status === 'fail').length;
    output += `- Passed: ${passed}\n`;
    output += `- Warnings: ${warnings}\n`;
    output += `- Failed: ${failed}\n`;
    
    return { content: [{ type: 'text', text: output }] };
  }
  
  /**
   * Perform SDD compliance checks on content
   */
  performSDDChecks(content, contentType) {
    const checks = [];
    
    // Check 1: Has documentation/comments
    const hasComments = content.includes('#') || content.includes('//') || 
                        content.includes('"""') || content.includes('/*');
    checks.push({
      name: 'Documentation',
      status: hasComments ? 'pass' : 'warn',
      message: hasComments ? 'Code contains comments/documentation' : 'Consider adding documentation'
    });
    
    // Check 2: Error handling (bash-specific)
    if (contentType === 'bash') {
      const hasSetE = content.includes('set -e') || content.includes('set -o errexit');
      const hasErrChk = content.includes('err_chk') || content.includes('$?');
      checks.push({
        name: 'Error Handling',
        status: (hasSetE || hasErrChk) ? 'pass' : 'warn',
        message: (hasSetE || hasErrChk) ? 'Error handling detected' : 'Consider adding error handling (set -e or err_chk)'
      });
      
      const hasShebang = content.startsWith('#!/');
      checks.push({
        name: 'Shebang',
        status: hasShebang ? 'pass' : 'fail',
        message: hasShebang ? 'Valid shebang present' : 'Missing shebang (#!/bin/bash)'
      });
    }
    
    // Check 3: Python-specific
    if (contentType === 'python') {
      const hasIfMain = content.includes('if __name__');
      checks.push({
        name: 'Entry Point',
        status: hasIfMain ? 'pass' : 'warn',
        message: hasIfMain ? 'Has if __name__ guard' : 'Consider adding if __name__ == "__main__" guard'
      });
      
      const hasTypeHints = /def \w+\([^)]*:/.test(content);
      checks.push({
        name: 'Type Hints',
        status: hasTypeHints ? 'pass' : 'warn',
        message: hasTypeHints ? 'Type hints detected' : 'Consider adding type hints'
      });
    }
    
    // Check 4: Naming conventions
    const hasUppercaseVars = /[A-Z]{2,}_[A-Z]+/.test(content);
    checks.push({
      name: 'Naming Conventions',
      status: 'pass',
      message: hasUppercaseVars ? 'Uses UPPER_CASE for constants (NCO style)' : 'Standard naming detected'
    });
    
    // Check 5: No hardcoded paths (common issue)
    const hasHardcodedPaths = /(\/gpfs\/|\/scratch\/|\/home\/[a-z]+\/)/.test(content);
    checks.push({
      name: 'Path Abstraction',
      status: hasHardcodedPaths ? 'fail' : 'pass',
      message: hasHardcodedPaths ? 'Contains hardcoded paths - use environment variables' : 'No hardcoded paths detected'
    });
    
    return checks;
  }

  /**
   * Get SDD framework status (Phase 31: session model)
   */
  async getFrameworkStatus(args = {}) {
    const { detailed = false } = args;

    try {
      const workflows = await this.executor.listWorkflows();
      const activeSession = this.sessionManager.getSessionState();
      const summaries = this.sessionManager.getSessionSummaries();
      
      let output = '# SDD Framework Status\n\n';
      output += `**Version**: 6.0 Phase 31\n`;
      output += `**Status**: Operational\n`;
      output += `**Execution Model**: Session-Oriented Tracking\n\n`;

      output += `## Components\n\n`;
      output += `- **Available Workflows**: ${workflows.length}\n`;
      output += `- **Total Sessions**: ${summaries.length}\n`;
      output += `- **Completed**: ${summaries.filter(s => s.status === 'completed').length}\n`;
      output += `- **Abandoned**: ${summaries.filter(s => s.status === 'abandoned').length}\n\n`;

      if (activeSession) {
        output += `## Active Session\n\n`;
        output += `- **Session ID**: ${activeSession.sessionId}\n`;
        output += `- **Phase**: ${activeSession.phase}\n`;
        output += `- **Progress**: ${activeSession.completedSteps.length}/${activeSession.totalSteps || '?'} steps\n`;
        output += `- **Started**: ${activeSession.startedAt}\n`;
        output += `- **Last Activity**: ${activeSession.lastActivityAt}\n\n`;
      } else {
        output += `## Active Session\n\n*No active session*\n\n`;
      }

      if (detailed) {
        output += `## Session Tools\n\n`;
        output += `- [OK] \`start_sdd_session\` — Activate a phase for tracking\n`;
        output += `- [OK] \`record_sdd_step\` — Record step completion\n`;
        output += `- [OK] \`get_sdd_session\` — Check current session state\n`;
        output += `- [OK] \`complete_sdd_session\` — Finalize session\n`;
        output += `- [OK] \`get_sdd_execution_history\` — Query JSONL history\n\n`;

        output += `## Preserved Infrastructure\n\n`;
        output += `- [..] ISD approval (dormant — reserved for Phase 4C USD CLI/YOLO)\n`;
        output += `- [..] WorkflowExecutor (available for spec parsing)\n`;
        output += `- [OK] SpecificationParser (active)\n`;
        output += `- [OK] SelfModificationEngine (available)\n\n`;

        if (summaries.length > 0) {
          output += `## Recent Sessions\n\n`;
          const recent = summaries.slice(-5);
          for (const s of recent) {
            const status = s.status === 'completed' ? '[OK]' : 
                          s.status === 'abandoned' ? '[!!]' : '[..]';
            output += `- ${status} ${s.phase} — ${s.stepsCompleted} steps (${s.status})\n`;
          }
        }
      }

      return { content: [{ type: 'text', text: output }] };

    } catch (error) {
      return {
        content: [{
          type: 'text',
          text: `[ERROR] Failed to get framework status: ${error.message}`
        }]
      };
    }
  }

  /**
   * Record a step completion (Phase 31)
   */
  async recordStep(args) {
    const { step, name, tag = 'implement', notes = '' } = args;

    try {
      const session = this.sessionManager.recordStep(step, name, tag, notes);

      let output = `# Step ${step} Recorded\n\n`;
      output += `**Step**: ${step} — ${name}\n`;
      output += `**Tag**: ${tag}\n`;
      if (notes) {
        output += `**Notes**: ${notes}\n`;
      }
      output += `\n## Session Progress\n\n`;
      output += `- **Phase**: ${session.phase}\n`;
      output += `- **Completed**: ${session.completedSteps.length}/${session.totalSteps || '?'} steps\n`;
      output += `- **Skipped**: ${session.skippedSteps.length}\n\n`;

      // Show completed steps
      if (session.completedSteps.length > 0) {
        output += `### Completed Steps\n\n`;
        for (const s of session.completedSteps) {
          output += `- [OK] Step ${s.step}: ${s.name} (${s.tag})\n`;
        }
      }

      return { content: [{ type: 'text', text: output }] };

    } catch (error) {
      return {
        content: [{
          type: 'text',
          text: `[ERROR] Failed to record step: ${error.message}`
        }]
      };
    }
  }

  /**
   * Get current session state (Phase 31)
   */
  async getSession(args = {}) {
    const { resume = false } = args;

    try {
      let session;
      if (resume) {
        session = this.sessionManager.resumeSession();
      } else {
        session = this.sessionManager.getSessionState();
      }

      if (!session) {
        return {
          content: [{
            type: 'text',
            text: '# No Active Session\n\nNo SDD session is currently active. Use `start_sdd_session` to begin one.'
          }]
        };
      }

      let output = `# Active SDD Session\n\n`;
      output += `**Session ID**: ${session.sessionId}\n`;
      output += `**Phase**: ${session.phase}\n`;
      output += `**Status**: ${session.status}\n`;
      output += `**Started**: ${session.startedAt}\n`;
      output += `**Last Activity**: ${session.lastActivityAt}\n`;
      output += `**Progress**: ${session.completedSteps.length}/${session.totalSteps || '?'} steps\n\n`;

      if (session.completedSteps.length > 0) {
        output += `## Completed Steps (${session.completedSteps.length})\n\n`;
        for (const s of session.completedSteps) {
          output += `- [OK] Step ${s.step}: ${s.name} (${s.tag}) — ${s.completedAt}\n`;
          if (s.notes) {
            output += `  _${s.notes}_\n`;
          }
        }
        output += '\n';
      }

      if (session.skippedSteps.length > 0) {
        output += `## Skipped Steps (${session.skippedSteps.length})\n\n`;
        for (const s of session.skippedSteps) {
          output += `- [--] Step ${s.step}: ${s.reason}\n`;
        }
        output += '\n';
      }

      if (session.blockers.length > 0) {
        output += `## Blockers\n\n`;
        for (const b of session.blockers) {
          output += `- [!!] ${b}\n`;
        }
        output += '\n';
      }

      if (session.notes) {
        output += `**Notes**: ${session.notes}\n`;
      }

      return { content: [{ type: 'text', text: output }] };

    } catch (error) {
      return {
        content: [{
          type: 'text',
          text: `[ERROR] Failed to get session: ${error.message}`
        }]
      };
    }
  }

  /**
   * Complete or abandon the active session (Phase 31)
   */
  async completeSession(args = {}) {
    const { summary = '', abandon = false, reason = '' } = args;

    try {
      let session;
      if (abandon) {
        session = this.sessionManager.abandonSession(reason);
      } else {
        session = this.sessionManager.completeSession(summary);
      }

      const action = abandon ? 'Abandoned' : 'Completed';
      let output = `# Session ${action}\n\n`;
      output += `**Session ID**: ${session.sessionId}\n`;
      output += `**Phase**: ${session.phase}\n`;
      output += `**Status**: ${session.status}\n`;
      output += `**Started**: ${session.startedAt}\n`;

      if (abandon) {
        output += `**Abandoned**: ${session.abandonedAt}\n`;
        if (reason) output += `**Reason**: ${reason}\n`;
      } else {
        output += `**Completed**: ${session.completedAt}\n`;
        if (summary) output += `**Summary**: ${summary}\n`;
      }

      output += `\n## Final State\n\n`;
      output += `- Steps Completed: ${session.completedSteps.length}\n`;
      output += `- Steps Skipped: ${session.skippedSteps.length}\n`;
      output += `- Total Steps: ${session.totalSteps || 'unknown'}\n`;

      return { content: [{ type: 'text', text: output }] };

    } catch (error) {
      return {
        content: [{
          type: 'text',
          text: `[ERROR] Failed to ${args.abandon ? 'abandon' : 'complete'} session: ${error.message}`
        }]
      };
    }
  }
}
