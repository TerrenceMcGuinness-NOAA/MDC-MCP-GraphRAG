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
import { ServerUtilities } from './utils/ServerUtilities.js';
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
      '3.0.0',
      {
        tools: {},
        resources: {},
        prompts: {}
      }
    );

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

    // Initialize server utilities with proper separation of concerns
    this.serverUtilities = new ServerUtilities(this.server, {
      workflowInfoTools: this.workflowInfoTools,
      codeAnalysisTools: this.codeAnalysisTools,
      semanticSearchTools: this.semanticSearchTools,
      operationalTools: this.operationalTools,
      githubTools: this.githubTools
    });

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

    // Register server utilities (2 tools) - PROPER SEPARATION OF CONCERNS
    this.serverUtilities.registerServerUtilities(this.server);

    const stats = this.server.getStats();
    console.error(`[MCP] Total tools registered: ${stats.toolCount} (Week 2 + proper separation)`);
  }

  // ✅ PROPER SEPARATION OF CONCERNS:
  // Server utilities (health_check, get_server_info) now handled by ServerUtilities class
  // This class focuses ONLY on tool coordination and lifecycle management

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