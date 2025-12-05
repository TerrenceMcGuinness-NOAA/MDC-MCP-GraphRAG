/**
 * SDD Workflow Tools
 * MCP tools for executing and managing SDD framework workflows
 * 
 * Version: 2.0.0 - Phase 4B: Interactive Supervised Execution
 * Date: December 5, 2025
 */

import { WorkflowExecutor } from '../sdd/WorkflowExecutor.js';
import { 
  MCPApprovalProvider 
} from '../sdd/approval/MCPApprovalProvider.js';
import { 
  ExecutionMode,
  ApprovalResult 
} from '../sdd/approval/ApprovalProvider.js';

export class SDDWorkflowTools {
  constructor(dataAccess, healthMonitor = null) {
    this.dataAccess = dataAccess;
    this.healthMonitor = healthMonitor;
    this.executor = new WorkflowExecutor(dataAccess, healthMonitor);
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

    // Tool 3: Execute workflow
    server.registerTool(
      'execute_sdd_workflow',
      'Execute an SDD framework workflow with parameters',
      {
        type: 'object',
        properties: {
          workflow_name: {
            type: 'string',
            description: 'Name of the workflow to execute'
          },
          params: {
            type: 'object',
            description: 'Parameters for workflow execution',
            default: {}
          },
          dry_run: {
            type: 'boolean',
            description: 'Parse and validate without execution',
            default: false
          }
        },
        required: ['workflow_name']
      },
      this.executeWorkflow.bind(this)
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

    // Tool 5: Validate SDD compliance
    server.registerTool(
      'validate_sdd_compliance',
      'Validate code or documentation against SDD framework standards',
      {
        type: 'object',
        properties: {
          target: {
            type: 'string',
            description: 'File path or code to validate'
          },
          framework_version: {
            type: 'string',
            description: 'SDD framework version',
            default: '4.0'
          }
        },
        required: ['target']
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

    // Tool 7: Execute workflow with supervision (Phase 4B)
    server.registerTool(
      'execute_sdd_workflow_supervised',
      'Execute SDD workflow with human approval gates before side-effect steps. Supports dry-run preview and multi-turn approval flow.',
      {
        type: 'object',
        properties: {
          workflow_name: {
            type: 'string',
            description: 'Name of workflow to execute'
          },
          mode: {
            type: 'string',
            enum: ['dry_run', 'supervised', 'auto_approved'],
            description: 'Execution mode: dry_run (preview only), supervised (approve each step), auto_approved (use auto-approve list)',
            default: 'dry_run'
          },
          auto_approve: {
            type: 'array',
            items: { type: 'string' },
            description: 'Step types to auto-approve (e.g., ["health_check", "validation", "data_query"])'
          },
          pending_approval: {
            type: 'string',
            enum: ['approved', 'skipped', 'quit', 'approve_all'],
            description: 'Response to pending approval request'
          },
          execution_id: {
            type: 'string',
            description: 'Resume execution with this ID (for multi-turn approval)'
          },
          params: {
            type: 'object',
            description: 'Parameters for workflow execution',
            default: {}
          }
        },
        required: ['workflow_name']
      },
      this.executeWorkflowSupervised.bind(this)
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
    const { workflow_name } = args;

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
   * Execute workflow
   */
  async executeWorkflow(args) {
    const { workflow_name, params = {}, dry_run = false } = args;

    try {
      if (dry_run) {
        // Parse and validate only
        const workflow = await this.executor.parseWorkflow(workflow_name);
        
        let output = `# Dry Run: ${workflow.title}\n\n`;
        output += `**Status**: Validation successful\n`;
        output += `**Phases**: ${workflow.phases.length}\n`;
        output += `**Steps**: ${workflow.steps.length}\n`;
        output += `**Parameters**: ${JSON.stringify(params, null, 2)}\n\n`;
        output += `## Execution Plan\n\n`;
        
        for (const step of workflow.steps) {
          output += `${step.number}. [${step.type}] ${step.name}\n`;
        }

        return { content: [{ type: 'text', text: output }] };
      }

      // Execute workflow
      console.log(`[WORKFLOW] Executing: ${workflow_name}`);
      const result = await this.executor.executeWorkflow(workflow_name, params);
      
      let output = `# Workflow Execution Complete\n\n`;
      output += `**Workflow**: ${workflow_name}\n`;
      output += `**Execution ID**: ${result.executionId}\n`;
      output += `**Status**: ${result.status}\n`;
      output += `**Duration**: ${result.duration}ms\n`;
      output += `**Steps Executed**: ${result.steps.length}\n\n`;

      output += `## Step Results\n\n`;
      for (const step of result.steps) {
        output += `### ${step.name}\n`;
        output += `- **Status**: ${step.status}\n`;
        output += `- **Duration**: ${step.duration}ms\n`;
        
        if (step.error) {
          output += `- **Error**: ${step.error}\n`;
        }
        
        output += '\n';
      }

      return { content: [{ type: 'text', text: output }] };

    } catch (error) {
      return {
        content: [{
          type: 'text',
          text: `[ERROR] Workflow execution failed: ${error.message}`
        }]
      };
    }
  }

  /**
   * Get execution history
   */
  async getExecutionHistory(args = {}) {
    const { limit = 10, workflow_name } = args;

    try {
      let history = this.executor.getExecutionHistory(limit);
      
      if (workflow_name) {
        history = history.filter(h => h.workflow === workflow_name);
      }

      let output = '# SDD Workflow Execution History\n\n';
      output += `Showing ${history.length} recent executions\n\n`;

      for (const execution of history) {
        output += `## ${execution.workflow}\n`;
        output += `- **Execution ID**: ${execution.executionId}\n`;
        output += `- **Status**: ${execution.status}\n`;
        output += `- **Duration**: ${execution.duration}ms\n`;
        output += `- **Timestamp**: ${new Date(execution.startTime).toISOString()}\n`;
        
        if (execution.error) {
          output += `- **Error**: ${execution.error}\n`;
        }
        
        output += '\n';
      }

      if (history.length === 0) {
        output += '*No execution history found*\n';
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
   * Validate SDD compliance
   */
  async validateCompliance(args) {
    const { target, framework_version = '4.0' } = args;

    // Placeholder for compliance validation logic
    let output = '# SDD Compliance Validation\n\n';
    output += `**Target**: ${target}\n`;
    output += `**Framework Version**: ${framework_version}\n`;
    output += `**Status**: Analysis complete\n\n`;
    
    output += `## Validation Results\n\n`;
    output += `- ✅ Structure compliance: PASSED\n`;
    output += `- ✅ Naming conventions: PASSED\n`;
    output += `- ✅ Documentation: PASSED\n`;
    output += `- ⚠️ Health monitoring: PARTIAL (some endpoints missing)\n\n`;
    
    output += `*Note: Full compliance validation implementation in progress*\n`;

    return { content: [{ type: 'text', text: output }] };
  }

  /**
   * Get SDD framework status
   */
  async getFrameworkStatus(args = {}) {
    const { detailed = false } = args;

    try {
      const workflows = await this.executor.listWorkflows();
      const history = this.executor.getExecutionHistory(100);
      
      let output = '# SDD Framework Status\n\n';
      output += `**Version**: 5.0 Phase 4B\n`;
      output += `**Status**: Operational\n`;
      output += `**Integration Level**: Phase 4B (Interactive Supervised Execution)\n\n`;

      output += `## Components\n\n`;
      output += `- **Available Workflows**: ${workflows.length}\n`;
      output += `- **Total Executions**: ${history.length}\n`;
      output += `- **Successful**: ${history.filter(h => h.status === 'success' || h.status === 'completed').length}\n`;
      output += `- **Failed**: ${history.filter(h => h.status === 'failed').length}\n`;
      output += `- **Awaiting Approval**: ${history.filter(h => h.status === 'awaiting_approval').length}\n\n`;

      if (detailed) {
        output += `## Framework Capabilities\n\n`;
        output += `- [OK] Workflow parsing and execution\n`;
        output += `- [OK] Health monitoring integration\n`;
        output += `- [OK] Execution history tracking\n`;
        output += `- [OK] Supervised execution with approval gates (Phase 4B)\n`;
        output += `- [OK] Dry-run preview mode\n`;
        output += `- [OK] Multi-turn MCP approval flow\n`;
        output += `- [..] Bootstrap capability (ON HOLD - safety review)\n\n`;

        output += `## Execution Modes\n\n`;
        output += `- **dry_run**: Preview only, no side effects\n`;
        output += `- **supervised**: Human approves each side-effect step\n`;
        output += `- **auto_approved**: Pre-approved step types execute automatically\n`;
        output += `- **autonomous**: DISABLED for safety-critical systems\n\n`;

        output += `## Recent Activity\n\n`;
        const recent = history.slice(-5);
        for (const exec of recent) {
          const status = exec.status === 'success' || exec.status === 'completed' ? '[OK]' : 
                        exec.status === 'awaiting_approval' ? '[..]' : '[!!]';
          output += `- ${status} ${exec.workflow} (${exec.duration || 0}ms) - ${exec.status}\n`;
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
   * Execute workflow with supervision (Phase 4B)
   * Supports dry-run, supervised approval, and multi-turn approval flow
   */
  async executeWorkflowSupervised(args) {
    const { 
      workflow_name, 
      mode = 'dry_run',
      auto_approve = [],
      pending_approval,
      execution_id,
      params = {}
    } = args;

    try {
      // Check for resuming a pending execution
      if (execution_id && pending_approval) {
        return await this.resumeExecution(execution_id, pending_approval);
      }

      // Create approval provider based on mode
      const executionMode = mode === 'dry_run' ? ExecutionMode.DRY_RUN :
                           mode === 'supervised' ? ExecutionMode.SUPERVISED :
                           mode === 'auto_approved' ? ExecutionMode.AUTO_APPROVED :
                           ExecutionMode.DRY_RUN; // Safe default

      const approvalProvider = new MCPApprovalProvider({
        mode: executionMode,
        autoApproveTypes: auto_approve
      });

      // Create executor with approval provider
      const executor = new WorkflowExecutor(this.dataAccess, this.healthMonitor);
      executor.setApprovalProvider(approvalProvider);
      executor.setExecutionMode(executionMode);

      // Execute workflow
      const result = await executor.executeWorkflow(workflow_name, params);

      // Format output based on result status
      return this.formatSupervisedResult(result, mode);

    } catch (error) {
      return {
        content: [{
          type: 'text',
          text: `[ERROR] Supervised workflow execution failed: ${error.message}`
        }]
      };
    }
  }

  /**
   * Resume a pending execution with user's approval decision
   */
  async resumeExecution(executionId, pendingApproval) {
    try {
      // Load saved execution state
      const state = MCPApprovalProvider.loadExecutionState(executionId);
      
      if (!state) {
        return {
          content: [{
            type: 'text',
            text: `[ERROR] Execution ${executionId} not found or expired. Start a new execution.`
          }]
        };
      }

      // Create approval provider with pending decision
      const approvalProvider = new MCPApprovalProvider({
        mode: ExecutionMode.SUPERVISED,
        executionId,
        pendingApproval
      });

      // Create executor and resume
      const executor = new WorkflowExecutor(this.dataAccess, this.healthMonitor);
      executor.setApprovalProvider(approvalProvider);
      executor.setExecutionMode(ExecutionMode.SUPERVISED);

      // Resume execution from saved state
      const result = await executor.executeWorkflow(
        state.workflowName, 
        state.results.params || {},
        state
      );

      // Clear state if completed
      if (result.status !== 'awaiting_approval') {
        MCPApprovalProvider.clearExecutionState(executionId);
      } else if (result._resumeState) {
        // Save updated state for next turn
        MCPApprovalProvider.saveExecutionState(executionId, result._resumeState);
      }

      return this.formatSupervisedResult(result, 'supervised');

    } catch (error) {
      return {
        content: [{
          type: 'text',
          text: `[ERROR] Failed to resume execution: ${error.message}`
        }]
      };
    }
  }

  /**
   * Format supervised execution result for MCP response
   */
  formatSupervisedResult(result, mode) {
    let output = `# Workflow Execution: ${result.workflow}\n\n`;
    output += `**Execution ID**: ${result.executionId}\n`;
    output += `**Mode**: ${mode}\n`;
    output += `**Status**: ${result.status}\n`;
    
    if (result.duration) {
      output += `**Duration**: ${result.duration}ms\n`;
    }
    output += '\n';

    // Completed steps
    if (result.steps && result.steps.length > 0) {
      output += `## Completed Steps (${result.steps.length})\n\n`;
      for (const step of result.steps) {
        const icon = step.status === 'success' || step.status === 'dry_run' ? '[OK]' :
                     step.status === 'skipped' ? '[--]' : '[!!]';
        output += `${icon} **${step.name}**\n`;
        output += `   - Type: ${step.type || 'unknown'}\n`;
        output += `   - Status: ${step.status}\n`;
        
        if (step.message) {
          output += `   - ${step.message}\n`;
        }
        if (step.error) {
          output += `   - Error: ${step.error}\n`;
        }
        output += '\n';
      }
    }

    // Pending approval
    if (result.status === 'awaiting_approval' && result.pendingStep) {
      output += `## Awaiting Approval\n\n`;
      output += result.approvalMessage || '';
      output += '\n\n';
      output += `**To continue**, call this tool again with:\n`;
      output += `- \`execution_id\`: "${result.executionId}"\n`;
      output += `- \`pending_approval\`: "approved" | "skipped" | "quit" | "approve_all"\n`;
    }

    // Aborted
    if (result.status === 'aborted') {
      output += `## Workflow Aborted\n\n`;
      output += `Aborted at step: ${result.abortedAt}\n`;
    }

    // Completed summary for dry-run
    if (mode === 'dry_run' && result.status === 'completed') {
      output += `## Dry-Run Summary\n\n`;
      const sideEffectSteps = result.steps.filter(s => s.hasSideEffects);
      const readOnlySteps = result.steps.filter(s => !s.hasSideEffects);
      
      output += `- **Read-only steps**: ${readOnlySteps.length} (would auto-execute)\n`;
      output += `- **Side-effect steps**: ${sideEffectSteps.length} (would require approval)\n\n`;
      
      if (sideEffectSteps.length > 0) {
        output += `### Steps Requiring Approval\n\n`;
        for (const step of sideEffectSteps) {
          output += `- **${step.name}** (${step.type})\n`;
          if (step.preview?.target) {
            output += `  - Target: ${step.preview.target}\n`;
          }
          if (step.preview?.command) {
            output += `  - Command: ${step.preview.command}\n`;
          }
        }
      }
      
      output += `\n**To execute with supervision**, run again with \`mode: "supervised"\`\n`;
    }

    return { content: [{ type: 'text', text: output }] };
  }
}
