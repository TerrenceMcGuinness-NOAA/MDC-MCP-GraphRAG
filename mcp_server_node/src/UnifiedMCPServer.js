#!/usr/bin/env node

/**
 * Unified MCP Server for Global Workflow
 * 
 * Combines all tool modules with proper separation of concerns:
 * - BaseServer: Core MCP functionality
 * - WorkflowTools: Basic workflow structure and documentation
 * - RAGTools: Semantic search and knowledge retrieval
 * - GitHubTools: Repository integration and analysis
 * 
 * This replaces the previous 3 separate server implementations
 * with a clean, modular architecture.
 * 
 * @version 3.0.1
 * @author NOAA EMC Global Workflow Team
 */

// CRITICAL: Enable quiet mode FIRST to prevent console pollution of MCP protocol
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
// Import quiet-console using absolute path to avoid relative path issues
const quietConsole = await import(join(__dirname, '../utils/quiet-console.js'));
// ACTIVATE quiet mode to redirect console.log/error to log file
quietConsole.enableQuietMode();

import { BaseServer } from './core/BaseServer.js';
import { WorkflowInfoTools } from './tools/WorkflowInfoTools.js';
import { SemanticSearchTools } from './tools/SemanticSearchTools.js';
import { CodeAnalysisTools } from './tools/CodeAnalysisTools.js';
import { OperationalTools } from './tools/OperationalTools.js';
import { GitHubTools } from './tools/GitHubTools.js';
import { SDDWorkflowTools } from './tools/SDDWorkflowTools.js';
import { UnifiedDataAccess } from './data/UnifiedDataAccess.js';
import path from 'path';

class UnifiedMCPServer {
  constructor(options = {}) {
    this.options = {
      enableRAG: options.enableRAG !== false,
      enableGitHub: options.enableGitHub !== false,
      githubToken: options.githubToken || process.env.GITHUB_TOKEN,
      workflowRoot: options.workflowRoot,
      knowledgeBasePath: options.knowledgeBasePath,
      ...options
    };

    // Initialize base server
    this.server = new BaseServer(
      'global-workflow-unified-mcp',
      '3.1.0',  // Phase 3A: SDD Workflow Automation
      {
        tools: {},
        resources: {},
        prompts: {}
      }
    );

    // Initialize unified data access layer (shared across all RAG-enabled tools)
    this.dataAccess = new UnifiedDataAccess();

    // Initialize tool modules (Week 2 consolidated architecture)
    this.workflowInfoTools = new WorkflowInfoTools();
    this.codeAnalysisTools = new CodeAnalysisTools();
    
    if (this.options.enableRAG) {
      this.semanticSearchTools = new SemanticSearchTools();
      this.operationalTools = new OperationalTools();
    }
    
    if (this.options.enableGitHub) {
      this.githubTools = new GitHubTools(this.options.githubToken);
    }

    // Initialize SDD Workflow Tools (Phase 3C: Connected to runtime)
    this.sddWorkflowTools = new SDDWorkflowTools(
      this.dataAccess,  // Connected to unified data access layer
      null              // healthMonitor (uses dataAccess.healthCheck internally)
    );

    this.registerAllTools();
  }

  /**
   * Register all tool modules with the server
   */
  registerAllTools() {
    console.error('[MCP] Registering tool modules (Week 2 consolidated architecture)...');

    // Always register core static workflow info tools (3 tools)
    this.workflowInfoTools.registerWith(this.server);
    console.error('[MCP] Workflow info tools registered');

    // Always register code analysis tools (4 tools)
    this.codeAnalysisTools.registerWith(this.server);
    console.error('[MCP] Code analysis tools registered');

    // Conditionally register semantic search tools (7 tools)
    if (this.options.enableRAG && this.semanticSearchTools) {
      try {
        this.semanticSearchTools.registerWith(this.server);
        console.error('[MCP] Semantic search tools registered');
      } catch (error) {
        console.error(`[WARN] Semantic search tools registration failed: ${error.message}`);
      }
    }

    // Conditionally register operational tools (3 tools)
    if (this.options.enableRAG && this.operationalTools) {
      try {
        this.operationalTools.registerWith(this.server);
        console.error('[MCP] Operational tools registered');
      } catch (error) {
        console.error(`[WARN] Operational tools registration failed: ${error.message}`);
      }
    }

    // Conditionally register GitHub tools (4 tools)
    if (this.options.enableGitHub && this.githubTools) {
      try {
        this.githubTools.registerWith(this.server);
        console.error('[MCP] GitHub tools registered');
      } catch (error) {
        console.error(`[WARN] GitHub tools registration failed: ${error.message}`);
      }
    }

    // Register SDD Workflow tools (6 tools) - Phase 3A
    try {
      this.sddWorkflowTools.registerTools(this.server);
      console.error('[MCP] SDD Workflow tools registered');
    } catch (error) {
      console.error(`[WARN] SDD Workflow tools registration failed: ${error.message}`);
    }

    // Register utility tools (2 tools)
    this.registerUtilityTools();

    const stats = this.server.getStats();
    console.error(`[MCP] Total tools registered: ${stats.toolCount}`);
  }

  /**
   * Register additional utility tools
   */
  registerUtilityTools() {
    this.server.registerTool(
      'get_server_info',
      'Get information about the MCP server and available tools',
      {
        type: 'object',
        properties: {
          include_capabilities: {
            type: 'boolean',
            description: 'Include detailed capability information',
            default: false
          }
        }
      },
      this.getServerInfo.bind(this)
    );

    this.server.registerTool(
      'mcp_health_check',
      'Check the health status of all MCP server components',
      {
        type: 'object',
        properties: {
          detailed: {
            type: 'boolean',
            description: 'Include detailed component status',
            default: false
          }
        }
      },
      this.healthCheck.bind(this)
    );
  }

  /**
   * Get server information
   */
  async getServerInfo(args = {}) {
    const { include_capabilities = false } = args;
    const stats = this.server.getStats();
    
    let info = `# ${stats.name} v${stats.version}\n\n`;
    info += `**Architecture**: Week 2 Consolidated + Phase 3A SDD Automation (27 tools)\n`;
    info += `**Total Tools**: ${stats.toolCount}\n\n`;
    
    info += `## Tool Categories\n\n`;
    
    info += `### Workflow Info Tools (3 tools - static, no DB)\n`;
    info += `- get_workflow_structure - System architecture overview\n`;
    info += `- get_system_configs - Platform configurations\n`;
    info += `- describe_component - File system-based component info\n\n`;

    info += `### Code Analysis Tools (4 tools - graph DB)\n`;
    info += `- analyze_code_structure - File/function/class analysis\n`;
    info += `- find_dependencies - Dependency mapping\n`;
    info += `- trace_execution_path - Call chain tracing\n`;
    info += `- find_callers_callees - Relationship analysis\n\n`;

    if (this.options.enableRAG) {
      info += `### Semantic Search Tools (7 tools - vector + graph)\n`;
      info += `- search_documentation - Hybrid semantic search\n`;
      info += `- search_ee2_standards - EE2 compliance search\n`;
      info += `- find_similar_code - Vector similarity + graph context\n`;
      info += `- explain_with_context - Multi-source explanations\n`;
      info += `- analyze_ee2_compliance - Compliance analysis\n`;
      info += `- generate_compliance_report - Report generation\n`;
      info += `- get_knowledge_base_status - System statistics\n\n`;

      info += `### Operational Tools (3 tools - hybrid with DB)\n`;
      info += `- get_operational_guidance - HPC procedures\n`;
      info += `- explain_workflow_component - Graph-enriched explanations\n`;
      info += `- list_job_scripts - Job categorization\n\n`;
    }

    if (this.options.enableGitHub) {
      info += `### GitHub Integration Tools (4 tools)\n`;
      info += `- search_issues - Issue search\n`;
      info += `- get_pull_requests - PR information\n`;
      info += `- get_ingested_urls_array - URL tracking\n`;
      info += `- list_ingested_urls - Ingestion status\n\n`;
    }

    info += `### SDD Workflow Tools (6 tools - Phase 3A)\n`;
    info += `- list_sdd_workflows - List available workflows\n`;
    info += `- get_sdd_workflow - Get workflow details\n`;
    info += `- execute_sdd_workflow - Execute workflow with parameters\n`;
    info += `- get_sdd_execution_history - View execution history\n`;
    info += `- validate_sdd_compliance - SDD compliance validation\n`;
    info += `- get_sdd_framework_status - Framework status and metrics\n\n`;

    info += `### Utility Tools (2 tools)\n`;
    info += `- get_server_info - This tool\n`;
    info += `- mcp_health_check - MCP server infrastructure health status\n\n`;

    if (include_capabilities) {
      info += `## Configuration\n`;
      info += `- **RAG Enabled**: ${this.options.enableRAG}\n`;
      info += `- **GitHub Enabled**: ${this.options.enableGitHub}\n`;
      info += `- **GitHub Auth**: ${this.options.githubToken ? 'Yes' : 'No'}\n`;
      info += `- **Workflow Root**: ${this.options.workflowRoot || 'Auto-detected'}\n`;
      info += `- **Knowledge Base**: ${this.options.knowledgeBasePath || 'Default'}\n\n`;
      
      info += `## Week 2 Consolidation Benefits\n`;
      info += `- [OK] Eliminated 8 duplicate tools\n`;
      info += `- [OK] Unified data access via Week 1 layer\n`;
      info += `- [OK] Clear separation of concerns\n`;
      info += `- [OK] Improved maintainability\n`;
      info += `- [OK] Consistent error handling\n\n`;
    }

    info += `## Usage\n`;
    info += `This unified server provides comprehensive workflow analysis with Week 2 architecture.\n`;
    info += `Use static tools for fast queries, graph tools for code analysis, `;
    info += `and semantic tools for context-aware search.\n`;

    return info;
  }

  /**
   * Check health status of all components
   */
  async healthCheck(args = {}) {
    const { detailed = false } = args;
    
    let status = `# Server Health Check\n\n`;
    const checks = [];

    // Base server check
    checks.push({
      component: 'Base Server',
      status: 'healthy',
      details: `${this.server.tools.size} tools registered`
    });

    // Workflow info tools check (always available)
    checks.push({
      component: 'Workflow Info Tools', 
      status: 'healthy',
      details: '3 static tools available'
    });

    // Code analysis tools check (always available)
    checks.push({
      component: 'Code Analysis Tools', 
      status: 'healthy',
      details: '4 graph-based tools available'
    });

    // Semantic search tools check
    if (this.options.enableRAG && this.semanticSearchTools) {
      try {
        const ragStatus = this.semanticSearchTools.isInitialized ? 'healthy' : 'initializing';
        checks.push({
          component: 'Semantic Search Tools',
          status: ragStatus,
          details: ragStatus === 'healthy' ? '7 hybrid search tools ready' : 'Loading vector DB'
        });
      } catch (error) {
        checks.push({
          component: 'Semantic Search Tools',
          status: 'degraded',
          details: `Error: ${error.message}`
        });
      }
    } else {
      checks.push({
        component: 'Semantic Search Tools',
        status: 'disabled',
        details: 'RAG functionality disabled'
      });
    }

    // Operational tools check
    if (this.options.enableRAG && this.operationalTools) {
      try {
        const opStatus = this.operationalTools.isInitialized ? 'healthy' : 'initializing';
        checks.push({
          component: 'Operational Tools',
          status: opStatus,
          details: opStatus === 'healthy' ? '3 operational tools ready' : 'Loading data access'
        });
      } catch (error) {
        checks.push({
          component: 'Operational Tools',
          status: 'degraded',
          details: `Error: ${error.message}`
        });
      }
    } else {
      checks.push({
        component: 'Operational Tools',
        status: 'disabled',
        details: 'Operational guidance disabled'
      });
    }

    // GitHub tools check
    if (this.options.enableGitHub && this.githubTools) {
      const githubStatus = this.githubTools.octokit ? 'healthy' : 'degraded';
      checks.push({
        component: 'GitHub Tools',
        status: githubStatus,
        details: githubStatus === 'healthy' ? '4 GitHub tools accessible' : 'GitHub API connection failed'
      });
    } else {
      checks.push({
        component: 'GitHub Tools',
        status: 'disabled', 
        details: 'GitHub integration disabled'
      });
    }

    // Format results
    const healthyCount = checks.filter(c => c.status === 'healthy').length;
    const totalCount = checks.length;
    
    status += `**Overall Status**: ${healthyCount}/${totalCount} components healthy\n\n`;
    
    checks.forEach(check => {
      const emoji = {
        'healthy': '[OK]',
        'degraded': '[WARN]',
        'disabled': '⭕',
        'initializing': '[INIT]'
      }[check.status] || '❓';
      
      status += `${emoji} **${check.component}**: ${check.status}`;
      if (detailed) {
        status += ` - ${check.details}`;
      }
      status += '\n';
    });

    status += '\n';
    
    if (detailed) {
      status += `## Recommendations\n\n`;
      
      checks.forEach(check => {
        if (check.status === 'degraded') {
          status += `- **${check.component}**: Check configuration and dependencies\n`;
        } else if (check.status === 'disabled') {
          status += `- **${check.component}**: Enable in configuration if needed\n`;
        }
      });
      
      status += `\n## Week 2 Architecture\n\n`;
      status += `This server uses the consolidated Week 2 architecture with:\n`;
      status += `- Unified data access layer (Week 1)\n`;
      status += `- Modular tool organization (5 modules)\n`;
      status += `- No duplicate tools (21 unique tools)\n`;
    }

    return status;
  }

  /**
   * Start the unified server
   */
  async start() {
    console.error('[MCP] Starting Unified MCP Server (Week 2 architecture)...');
    
    // Initialize RAG components BEFORE starting server
    if (this.options.enableRAG) {
      if (this.semanticSearchTools) {
        console.error('[MCP] Initializing semantic search tools (blocking)...');
        try {
          await this.semanticSearchTools.initialize();
          console.error('[MCP] [OK] Semantic search tools initialized');
        } catch (error) {
          console.error(`[ERROR] Semantic search initialization failed: ${error.message}`);
          console.error('[WARN] Semantic search tools will be unavailable');
        }
      }
      
      if (this.operationalTools) {
        console.error('[MCP] Initializing operational tools (blocking)...');
        try {
          await this.operationalTools.initialize();
          console.error('[MCP] [OK] Operational tools initialized');
        } catch (error) {
          console.error(`[ERROR] Operational tools initialization failed: ${error.message}`);
          console.error('[WARN] Operational tools will be unavailable');
        }
      }
    }

    await this.server.start();
    console.error('[MCP] Unified MCP Server ready (Week 2 consolidation complete)');
  }

  /**
   * Get configuration for different deployment scenarios
   */
  static getConfiguration(scenario = 'full') {
    const configs = {
      // Full functionality - all tools enabled
      full: {
        enableRAG: true,
        enableGitHub: true,
        githubToken: process.env.GITHUB_TOKEN
      },
      
      // Core only - just workflow tools
      core: {
        enableRAG: false,
        enableGitHub: false
      },
      
      // RAG only - workflow + semantic search
      rag: {
        enableRAG: true,
        enableGitHub: false
      },
      
      // GitHub only - workflow + repository integration
      github: {
        enableRAG: false,
        enableGitHub: true,
        githubToken: process.env.GITHUB_TOKEN
      }
    };

    return configs[scenario] || configs.full;
  }
}

// Main execution when run as script
if (import.meta.url === `file://${process.argv[1]}`) {
  // Add global error handlers to prevent crashes
  process.on('unhandledRejection', (reason, promise) => {
    console.error('[ERROR] Unhandled Promise Rejection:', reason);
    console.error('Promise:', promise);
  });

  process.on('uncaughtException', (error) => {
    console.error('[ERROR] Uncaught Exception:', error);
  });

  const scenario = process.argv[2] || 'full';
  const config = UnifiedMCPServer.getConfiguration(scenario);
  
  console.error(`[MCP] Starting with '${scenario}' configuration`);
  
  const server = new UnifiedMCPServer(config);
  server.start().catch(error => {
    console.error(`[ERROR] Server startup failed: ${error.message}`);
    console.error('Stack:', error.stack);
    process.exit(1);
  });
}

export { UnifiedMCPServer };