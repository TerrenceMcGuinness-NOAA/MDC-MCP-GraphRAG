#!/usr/bin/env node

/**
 * MCP Server for SDD Framework Validation
 * Provides SDD validation tools through proper MCP protocol
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';
import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

/**
 * SDD Framework Validation Class (embedded)
 */
class SDDValidator {
  constructor(frameworkRoot = '/mcp_rag_eib/eib-mcp-rag-server') {
    this.frameworkRoot = frameworkRoot;
    this.sddFrameworkPath = path.join(frameworkRoot, 'sdd_framework');
    this.mcpRuntimePath = path.join(frameworkRoot, 'mcp_server_node', 'src');
    this.architecturePath = path.join(frameworkRoot, 'mcp_architecture');
  }

  async sdd_validate() {
    const results = {
      timestamp: new Date().toISOString(),
      framework_status: 'unknown',
      validation_results: {},
      compliance_score: 0,
      recommendations: []
    };

    try {
      // Check basic structure
      const structureCheck = await this.checkStructure();
      results.validation_results.structure = structureCheck;
      
      // Check methodology files
      const methodologyCheck = await this.checkMethodology();
      results.validation_results.methodology = methodologyCheck;
      
      // Check tools
      const toolsCheck = await this.checkTools();
      results.validation_results.tools = toolsCheck;
      
      // Check workflows
      const workflowsCheck = await this.checkWorkflows();
      results.validation_results.workflows = workflowsCheck;
      
      // Calculate compliance score
      let score = 0;
      if (structureCheck.valid) score += 25;
      if (methodologyCheck.compliant) score += 25;
      if (toolsCheck.functional) score += 25;
      if (workflowsCheck.executable) score += 25;
      
      results.compliance_score = score;
      results.framework_status = score >= 75 ? 'excellent' : score >= 50 ? 'good' : 'needs_work';
      
      return results;
    } catch (error) {
      results.framework_status = 'error';
      results.recommendations.push(`Validation error: ${error.message}`);
      return results;
    }
  }

  async checkStructure() {
    const requiredDirs = ['methodology', 'validation', 'tools', 'workflows', 'templates'];
    const present = [];
    const missing = [];
    
    for (const dir of requiredDirs) {
      const dirPath = path.join(this.sddFrameworkPath, dir);
      try {
        await fs.access(dirPath);
        present.push(dir);
      } catch {
        missing.push(dir);
      }
    }
    
    return {
      valid: missing.length === 0,
      missing,
      present
    };
  }

  async checkMethodology() {
    const methodologyPath = path.join(this.sddFrameworkPath, 'methodology');
    const requiredFiles = ['spec_driven_design_core.md', 'historical_manifest.md'];
    const files = {};
    let compliant = true;
    
    for (const file of requiredFiles) {
      const filePath = path.join(methodologyPath, file);
      try {
        const stats = await fs.stat(filePath);
        files[file] = { exists: true, size: stats.size };
      } catch {
        files[file] = { exists: false, size: 0 };
        compliant = false;
      }
    }
    
    return { compliant, files };
  }

  async checkTools() {
    const toolsPath = path.join(this.sddFrameworkPath, 'tools');
    const available = [];
    let functional = false;
    
    try {
      const toolFiles = await fs.readdir(toolsPath);
      for (const file of toolFiles) {
        if (file.endsWith('.js')) {
          available.push(file);
          functional = true;
        }
      }
    } catch (error) {
      // Tools directory might not exist
    }
    
    return { available, functional };
  }

  async checkWorkflows() {
    const workflowsPath = path.join(this.sddFrameworkPath, 'workflows');
    const defined = [];
    let executable = false;
    
    try {
      const workflowFiles = await fs.readdir(workflowsPath);
      for (const file of workflowFiles) {
        if (file.endsWith('.md')) {
          defined.push(file);
          executable = true;
        }
      }
    } catch (error) {
      // Workflows directory might not exist
    }
    
    return { defined, executable };
  }

  async framework_integrity() {
    const integrity = {
      timestamp: new Date().toISOString(),
      structural_integrity: 'unknown',
      component_status: {},
      integration_health: 'unknown'
    };

    try {
      integrity.component_status.sdd_framework = await this.checkSDDComponents();
      integrity.component_status.mcp_runtime = await this.checkMCPIntegration();
      integrity.component_status.architecture = await this.checkArchitectureSeparation();
      integrity.structural_integrity = this.assessStructuralIntegrity(integrity.component_status);
      integrity.integration_health = this.assessIntegrationHealth(integrity.component_status);
      return integrity;
    } catch (error) {
      integrity.structural_integrity = 'compromised';
      integrity.component_status.error = error.message;
      return integrity;
    }
  }

  async development_status() {
    const status = {
      timestamp: new Date().toISOString(),
      phase: 'unknown',
      progress_metrics: {},
      milestone_completion: {},
      next_actions: []
    };

    try {
      status.phase = await this.identifyDevelopmentPhase();
      status.progress_metrics = await this.calculateProgressMetrics();
      status.milestone_completion = await this.checkMilestones();
      status.next_actions = await this.identifyNextActions();
      return status;
    } catch (error) {
      status.phase = 'error';
      status.progress_metrics.error = error.message;
      return status;
    }
  }

  async bootstrap_progress() {
    const bootstrap = {
      timestamp: new Date().toISOString(),
      bootstrap_phase: 'unknown',
      self_development_capability: 'unknown',
      system_maturity: 0,
      bootstrap_metrics: {}
    };

    try {
      bootstrap.bootstrap_phase = await this.assessBootstrapPhase();
      bootstrap.self_development_capability = await this.evaluateSelfDevelopment();
      bootstrap.system_maturity = await this.calculateSystemMaturity();
      bootstrap.bootstrap_metrics = await this.gatherBootstrapMetrics();
      return bootstrap;
    } catch (error) {
      bootstrap.bootstrap_phase = 'initialization_error';
      bootstrap.bootstrap_metrics.error = error.message;
      return bootstrap;
    }
  }

  // Helper methods for framework_integrity
  async checkSDDComponents() {
    try {
      await fs.access(this.sddFrameworkPath);
      return { status: 'operational', path: this.sddFrameworkPath };
    } catch {
      return { status: 'missing', path: this.sddFrameworkPath };
    }
  }

  async checkMCPIntegration() {
    try {
      await fs.access(this.mcpRuntimePath);
      return { status: 'integrated', path: this.mcpRuntimePath };
    } catch {
      return { status: 'disconnected', path: this.mcpRuntimePath };
    }
  }

  async checkArchitectureSeparation() {
    try {
      await fs.access(this.architecturePath);
      return { status: 'separated', path: this.architecturePath };
    } catch {
      return { status: 'coupled', path: this.architecturePath };
    }
  }

  assessStructuralIntegrity(components) {
    const operational = Object.values(components).filter(c => 
      c.status === 'operational' || c.status === 'integrated' || c.status === 'separated'
    ).length;
    const total = Object.keys(components).length;
    
    if (operational === total) return 'intact';
    if (operational >= total * 0.7) return 'stable';
    return 'compromised';
  }

  assessIntegrationHealth(components) {
    if (components.mcp_runtime?.status === 'integrated' && 
        components.architecture?.status === 'separated') {
      return 'healthy';
    }
    return 'requires_attention';
  }

  // Helper methods for development_status
  async identifyDevelopmentPhase() {
    // SPOT: Read from PRIORITY_ROADMAP.md
    try {
      const roadmapPath = path.join(this.sddFrameworkPath, 'PRIORITY_ROADMAP.md');
      const content = await fs.readFile(roadmapPath, 'utf-8');
      
      // Extract phase from "**Status**: Phase XX" pattern in header
      const statusMatch = content.match(/\*\*Status\*\*:\s*Phase\s+(\d+[A-Za-z]?)\s+(Complete|In Progress)/i);
      if (statusMatch) {
        return `Phase ${statusMatch[1]} ${statusMatch[2]}`;
      }
      
      // Fallback: find first 🔴 NEXT priority phase
      const nextPhaseMatch = content.match(/###\s+🔴\s+Phase\s+(\d+[A-Za-z]?):\s+([^\n]+)\s+\(NEXT\)/);
      if (nextPhaseMatch) {
        return `Phase ${nextPhaseMatch[1]} Next: ${nextPhaseMatch[2]}`;
      }
      
      return 'implementation';
    } catch {
      return 'unknown';
    }
  }

  async calculateProgressMetrics() {
    const validation = await this.sdd_validate();
    
    // SPOT: Read additional metrics from PRIORITY_ROADMAP.md
    let toolCount = 0;
    let workflowCount = 0;
    try {
      const roadmapPath = path.join(this.sddFrameworkPath, 'PRIORITY_ROADMAP.md');
      const content = await fs.readFile(roadmapPath, 'utf-8');
      
      // Extract tool count from "XX tools" pattern
      const toolMatch = content.match(/(\d+)\s+tools/i);
      if (toolMatch) toolCount = parseInt(toolMatch[1]);
      
      // Extract workflow count from "## SDD Workflow Inventory (XX Workflows)"
      const workflowMatch = content.match(/SDD Workflow Inventory\s*\((\d+)\s+Workflows\)/i);
      if (workflowMatch) workflowCount = parseInt(workflowMatch[1]);
    } catch {
      // Use defaults
    }
    
    return {
      completion_percentage: validation.compliance_score,
      framework_maturity: validation.framework_status,
      active_components: Object.keys(validation.validation_results).length,
      mcp_tools: toolCount,
      sdd_workflows: workflowCount
    };
  }

  async checkMilestones() {
    // SPOT: Read milestone status from PRIORITY_ROADMAP.md
    const milestones = {
      systematic_organization: true,
      sdd_framework_creation: true,
      tool_implementation: true,
      workflow_integration: false,
      bootstrap_capability: false,
      docker_gateway: false,
      n8n_integration: false,
      devops_gitflow: false
    };
    
    try {
      const roadmapPath = path.join(this.sddFrameworkPath, 'PRIORITY_ROADMAP.md');
      const content = await fs.readFile(roadmapPath, 'utf-8');
      
      // Check for completed phases
      if (content.includes('Phase 11E') && content.includes('COMPLETE')) {
        milestones.n8n_integration = true;
      }
      if (content.includes('Phase 12') && content.includes('COMPLETE')) {
        milestones.devops_gitflow = true;
      }
      if (content.includes('Docker MCP Gateway') && content.includes('✅ Complete')) {
        milestones.docker_gateway = true;
      }
      if (content.includes('SDD Validator Server') && content.includes('✅ Operational')) {
        milestones.workflow_integration = true;
      }
      if (content.includes('Bootstrap Capability') && content.includes('🔒 ON HOLD')) {
        milestones.bootstrap_capability = false;
      }
    } catch {
      // Use defaults
    }
    
    return milestones;
  }

  async identifyNextActions() {
    // SPOT: Read next actions from PRIORITY_ROADMAP.md
    const actions = [];
    
    try {
      const roadmapPath = path.join(this.sddFrameworkPath, 'PRIORITY_ROADMAP.md');
      const content = await fs.readFile(roadmapPath, 'utf-8');
      
      // Extract from "## Next Actions" section
      const actionsMatch = content.match(/## Next Actions\s+([\s\S]*?)(?=---|\n## )/);
      if (actionsMatch) {
        const lines = actionsMatch[1].split('\n');
        for (const line of lines) {
          const itemMatch = line.match(/^\d+\.\s+\*\*[^*]+\*\*:\s*(.+)/);
          if (itemMatch) {
            actions.push(itemMatch[1].trim());
          }
        }
      }
      
      // If no actions found, check for NEXT phase
      if (actions.length === 0) {
        const nextPhaseMatch = content.match(/###\s+🔴\s+Phase\s+\d+[A-Za-z]?:\s+([^\n]+)\s+\(NEXT\)/);
        if (nextPhaseMatch) {
          actions.push(`Complete ${nextPhaseMatch[1]}`);
        }
      }
    } catch {
      actions.push('Review PRIORITY_ROADMAP.md for current priorities');
    }
    
    return actions;
  }

  // Helper methods for bootstrap_progress
  async assessBootstrapPhase() {
    const tools = await this.checkTools();
    if (tools.available.length > 0) {
      return 'tooling_development';
    }
    return 'framework_establishment';
  }

  async evaluateSelfDevelopment() {
    const hasValidationTools = (await this.checkTools()).available.length > 0;
    const hasMethodology = (await this.checkMethodology()).compliant;
    
    if (hasValidationTools && hasMethodology) {
      return 'emerging';
    }
    return 'dependent';
  }

  async calculateSystemMaturity() {
    const validation = await this.sdd_validate();
    const integrity = await this.framework_integrity();
    
    let maturity = validation.compliance_score * 0.7;
    if (integrity.integration_health === 'healthy') {
      maturity += 30;
    }
    
    return Math.min(100, Math.round(maturity));
  }

  async gatherBootstrapMetrics() {
    return {
      self_modification_capability: await this.evaluateSelfDevelopment(),
      tool_autonomy_level: (await this.checkTools()).available.length,
      system_maturity_score: await this.calculateSystemMaturity(),
      bootstrap_readiness: await this.assessBootstrapPhase()
    };
  }
}

/**
 * Create and configure the MCP server
 */
function createServer() {
  const server = new Server(
    {
      name: 'sdd-framework-validator',
      version: '1.0.0',
    },
    {
      capabilities: {
        tools: {},
      },
    }
  );

  const validator = new SDDValidator();

  /**
   * List available tools
   */
  server.setRequestHandler(ListToolsRequestSchema, async () => {
    return {
      tools: [
        {
          name: 'sdd_validate',
          description: 'Validate SDD framework integrity and compliance',
          inputSchema: {
            type: 'object',
            properties: {},
            additionalProperties: false,
          },
        },
        {
          name: 'framework_integrity',
          description: 'Check framework structural integrity',
          inputSchema: {
            type: 'object',
            properties: {},
            additionalProperties: false,
          },
        },
        {
          name: 'development_status',
          description: 'Get current development status',
          inputSchema: {
            type: 'object',
            properties: {},
            additionalProperties: false,
          },
        },
        {
          name: 'bootstrap_progress',
          description: 'Check bootstrap development progress',
          inputSchema: {
            type: 'object',
            properties: {},
            additionalProperties: false,
          },
        },
      ],
    };
  });

  /**
   * Handle tool execution
   */
  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name } = request.params;

    try {
      let result;
      
      switch (name) {
        case 'sdd_validate':
          result = await validator.sdd_validate();
          break;
        case 'framework_integrity':
          result = await validator.framework_integrity();
          break;
        case 'development_status':
          result = await validator.development_status();
          break;
        case 'bootstrap_progress':
          result = await validator.bootstrap_progress();
          break;
        default:
          throw new Error(`Unknown tool: ${name}`);
      }

      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    } catch (error) {
      return {
        content: [
          {
            type: 'text',
            text: `Error: ${error.message}`,
          },
        ],
        isError: true,
      };
    }
  });

  return server;
}

/**
 * Start the server
 */
async function main() {
  const server = createServer();
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error('SDD Framework MCP Server running on stdio');
}

main().catch((error) => {
  console.error('Server error:', error);
  process.exit(1);
});