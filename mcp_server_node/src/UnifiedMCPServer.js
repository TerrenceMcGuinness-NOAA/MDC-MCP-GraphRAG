#!/usr/bin/env node

/**
 * Unified MCP Server for Global Workflow
 * 
 * Combines all tool modules with proper separation of concerns:
 * - BaseServer: Core MCP functionality
 * - WorkflowTools: Basic workflow structure and documentation
 * - SemanticSearchTools: Hybrid semantic + graph search
 * - EE2ComplianceTools: EE2 standards compliance validation (extracted v3.6.0)
 * - RAGTools: Semantic search and knowledge retrieval
 * - GitHubTools: Repository integration and analysis
 * 
 * This replaces the previous 3 separate server implementations
 * with a clean, modular architecture.
 * 
 * @version 3.6.2
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
import { EE2ComplianceTools } from './tools/EE2ComplianceTools.js';
import { CodeAnalysisTools } from './tools/CodeAnalysisTools.js';
import { OperationalTools } from './tools/OperationalTools.js';
import { GitHubTools } from './tools/GitHubTools.js';
import { SDDWorkflowTools } from './tools/SDDWorkflowTools.js';
import { SessionManager } from './sdd/SessionManager.js';
import { GraphRAGTools } from './tools/GraphRAGTools.js';
import { UnifiedDataAccess } from './data/UnifiedDataAccess.js';
import { logEnvironment, MCP_ENV } from './config/environment.js';
import path from 'path';
import { readFileSync, readdirSync, existsSync, appendFileSync, mkdirSync } from 'node:fs';

class UnifiedMCPServer {
  constructor(options = {}) {
    // Log environment configuration at startup
    logEnvironment();
    
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
      '3.6.2',  // v3.6.2: Fixed ONNX Runtime conflict (removed @chroma-core/default-embed)
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
      this.ee2ComplianceTools = new EE2ComplianceTools();
      this.operationalTools = new OperationalTools();
    }
    
    if (this.options.enableGitHub) {
      this.githubTools = new GitHubTools(this.options.githubToken);
    }

    // Initialize SDD Workflow Tools (Phase 31: Session-oriented execution model)
    this.sessionManager = new SessionManager();
    this.sddWorkflowTools = new SDDWorkflowTools(
      this.dataAccess,      // Connected to unified data access layer
      null,                 // healthMonitor (uses dataAccess.healthCheck internally)
      this.sessionManager   // Phase 31: Session tracking
    );

    // Initialize GraphRAG Tools (Phase 24H: Agentic tool surface)
    this.graphRAGTools = new GraphRAGTools(null, this.sessionManager);

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

    // Conditionally register semantic search tools (6 tools - SOC: EE2 tools moved to EE2ComplianceTools)
    if (this.options.enableRAG && this.semanticSearchTools) {
      try {
        this.semanticSearchTools.registerWith(this.server);
        console.error('[MCP] Semantic search tools registered');
      } catch (error) {
        console.error(`[WARN] Semantic search tools registration failed: ${error.message}`);
      }
    }

    // Conditionally register EE2 compliance tools (4 tools - extracted for EVS team collaboration)
    if (this.options.enableRAG && this.ee2ComplianceTools) {
      try {
        this.ee2ComplianceTools.registerWith(this.server);
        console.error('[MCP] EE2 compliance tools registered');
      } catch (error) {
        console.error(`[WARN] EE2 compliance tools registration failed: ${error.message}`);
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

    // Register SDD Workflow tools (9 tools) - Phase 31: Session model
    try {
      this.sddWorkflowTools.registerTools(this.server);
      console.error('[MCP] SDD Workflow tools registered');
    } catch (error) {
      console.error(`[WARN] SDD Workflow tools registration failed: ${error.message}`);
    }

    // Register GraphRAG agentic tools (9 tools) - Phase 24H-1/24H-3
    try {
      this.graphRAGTools.registerWith(this.server);
      console.error('[MCP] GraphRAG tools registered');
    } catch (error) {
      console.error(`[WARN] GraphRAG tools registration failed: ${error.message}`);
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
      'Check the health status of all MCP server components with empirical data validation',
      {
        type: 'object',
        properties: {
          detailed: {
            type: 'boolean',
            description: 'Include detailed component status and troubleshooting info',
            default: false
          },
          deep: {
            type: 'boolean',
            description: 'Run deep validation including sample queries (slower but more thorough)',
            default: false
          },
          functional: {
            type: 'boolean',
            description: 'Run functional tests to validate tool effectiveness (tests actual tool queries)',
            default: false
          }
        }
      },
      this.healthCheck.bind(this)
    );

    // Phase 43: Health trending tool
    this.server.registerTool(
      'get_health_trend',
      'Get health trend data from persisted snapshots. Shows count trends, latency trends, and anomaly detection over time.',
      {
        type: 'object',
        properties: {
          limit: {
            type: 'number',
            description: 'Number of recent snapshots to analyze (default: 10)',
            default: 10
          }
        }
      },
      this.getHealthTrend.bind(this)
    );

    this.server.registerTool(
      'get_quality_metrics',
      'Get RAG quality benchmark metrics. Reads latest benchmark results and returns formatted summary with optional regression comparison.',
      {
        type: 'object',
        properties: {
          category: {
            type: 'string',
            description: 'Filter results to a specific category',
            enum: ['code_structure', 'semantic_search', 'architecture', 'ee2_compliance', 'operational', 'cross_language']
          },
          compare: {
            type: 'boolean',
            description: 'Show delta comparison against previous benchmark run',
            default: false
          }
        }
      },
      this.getQualityMetrics.bind(this)
    );

    // Phase 52: Unit test runner tool (vitest)
    this.server.registerTool(
      'run_unit_tests',
      'Run vitest unit tests and return results. REQUIRED before git commit. Runs mocked tests (no DB needed).',
      {
        type: 'object',
        properties: {
          file: {
            type: 'string',
            description: 'Run a specific test file (e.g., "CodeAnalysisTools" or "GraphRAGTools.test.js"). Omit to run all tests.'
          },
          verbose: {
            type: 'boolean',
            description: 'Include full vitest output instead of summary only',
            default: false
          }
        }
      },
      this.runUnitTests.bind(this)
    );
  }

  /**
   * Get server information
   */
  async getServerInfo(args = {}) {
    const { include_capabilities = false } = args;
    const stats = this.server.getStats();
    
    let info = `# ${stats.name} v${stats.version}\n\n`;
    info += `**Architecture**: Week 2 Consolidated + v3.6.0 SOC Refactor (7 modules)\n`;
    info += `**Total Tools**: ${stats.toolCount}\n\n`;
    
    info += `## Tool Categories\n\n`;
    
    info += `### Workflow Info Tools (3 tools - static, no DB)\n`;
    info += `- get_workflow_structure - System architecture overview\n`;
    info += `- get_system_configs - Platform configurations\n`;
    info += `- describe_component - File system-based component info\n\n`;

    info += `### Code Analysis Tools (5 tools - graph DB)\n`;
    info += `- analyze_code_structure - File/function/class analysis\n`;
    info += `- find_dependencies - Dependency mapping\n`;
    info += `- trace_execution_path - Call chain tracing\n`;
    info += `- find_callers_callees - Relationship analysis\n`;
    info += `- find_env_dependencies - Environment variable usage across scripts\n\n`;

    if (this.options.enableRAG) {
      info += `### Semantic Search Tools (6 tools - vector + graph hybrid)\n`;
      info += `- search_documentation - Hybrid semantic search\n`;
      info += `- find_related_files - Dependency relationship search\n`;
      info += `- explain_with_context - Multi-source RAG explanations\n`;
      info += `- get_knowledge_base_status - Vector + graph DB statistics\n`;
      info += `- list_ingested_urls - List all ingested documentation URLs\n`;
      info += `- get_ingested_urls_array - Get URLs as structured array\n\n`;

      info += `### EE2 Compliance Tools (4 tools - vector + Phase 2 patterns)\n`;
      info += `- search_ee2_standards - EE2 documentation search\n`;
      info += `- analyze_ee2_compliance - Code compliance analysis\n`;
      info += `- generate_compliance_report - Structured compliance reports\n`;
      info += `- scan_repository_compliance - Full repository scanning\n\n`;

      info += `### Operational Tools (3 tools - hybrid with DB)\n`;
      info += `- get_operational_guidance - HPC procedures\n`;
      info += `- explain_workflow_component - Graph-enriched explanations\n`;
      info += `- list_job_scripts - Job categorization\n\n`;
    }

    if (this.options.enableGitHub) {
      info += `### GitHub Integration Tools (4 tools)\n`;
      info += `- search_issues - Issue search\n`;
      info += `- get_pull_requests - PR information\n`;
      info += `- analyze_workflow_dependencies - Cross-repo dependency analysis\n`;
      info += `- analyze_repository_structure - Multi-repo structure analysis\n\n`;
    }

    info += `### SDD Workflow Tools (9 tools - Phase 31 Session Model)\n`;
    info += `- list_sdd_workflows - List available workflows\n`;
    info += `- get_sdd_workflow - Get workflow details\n`;
    info += `- start_sdd_session - Start a session for a phase\n`;
    info += `- record_sdd_step - Record step completion\n`;
    info += `- get_sdd_session - Get active session state\n`;
    info += `- complete_sdd_session - Complete or abandon session\n`;
    info += `- get_sdd_execution_history - View session history (JSONL)\n`;
    info += `- validate_sdd_compliance - SDD compliance validation\n`;
    info += `- get_sdd_framework_status - Framework status and metrics\n\n`;

    info += `### Utility Tools (3 tools)\n`;
    info += `- get_server_info - This tool\n`;
    info += `- mcp_health_check - MCP server infrastructure health status\n`;
    info += `- get_quality_metrics - RAG quality benchmark metrics\n\n`;

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
   * Check health status of all components with empirical data validation
   * 
   * Enhanced to prevent false positives by validating:
   * - Service connectivity (heartbeat)
   * - Data accessibility (collection count)
   * - Data population (document count)
   * - Query capability (optional deep check)
   * - Tool effectiveness (optional functional check)
   */
  async healthCheck(args = {}) {
    const { detailed = false, deep = false, functional = false } = args;
    
    let status = `# Server Health Check\n\n`;
    const checks = [];
    let dataValidation = null;

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

    // Semantic search tools check WITH DATA VALIDATION
    if (this.options.enableRAG && this.semanticSearchTools) {
      try {
        if (this.semanticSearchTools.isInitialized && this.semanticSearchTools.dataAccess) {
          // Run empirical validation on vector database
          const vectorHealth = await this.semanticSearchTools.dataAccess.vectorDB.healthCheck({
            deep: deep,
            minCollections: 1,
            minDocuments: 100
          });
          
          dataValidation = vectorHealth;
          
          // Status based on actual data validation, not just connectivity
          let ragStatus = vectorHealth.status;
          let ragDetails = vectorHealth.statusReason;
          
          if (vectorHealth.status === 'healthy') {
            ragDetails = `${vectorHealth.totalDocuments} docs in ${vectorHealth.collections?.length || 0} collections`;
          }
          
          checks.push({
            component: 'Semantic Search Tools',
            status: ragStatus,
            details: ragDetails,
            validation: vectorHealth.validation
          });
        } else if (this.semanticSearchTools.isInitialized) {
          checks.push({
            component: 'Semantic Search Tools',
            status: 'degraded',
            details: 'Initialized but no data access layer'
          });
        } else {
          checks.push({
            component: 'Semantic Search Tools',
            status: 'initializing',
            details: 'Loading vector DB'
          });
        }
      } catch (error) {
        checks.push({
          component: 'Semantic Search Tools',
          status: 'unhealthy',
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

    // Graph database check (Phase 51 fix: sum file/function/class/module counts;
    // GraphDatabase.getStatistics() does NOT return a `nodes` field).
    const graphDB = this.semanticSearchTools?.dataAccess?.graphDB
      || this.codeAnalysisTools?.dataAccess?.graphDB
      || this.operationalTools?.dataAccess?.graphDB;
    if (graphDB) {
      try {
        const stats = await graphDB.getStatistics();
        const nodeCount =
          (stats?.nodes ?? 0) ||
          ((stats?.fileCount ?? 0) +
           (stats?.functionCount ?? 0) +
           (stats?.classCount ?? 0) +
           (stats?.moduleCount ?? 0));
        const ok = nodeCount > 0;
        checks.push({
          component: 'Graph Database (Neo4j)',
          status: ok ? 'healthy' : 'degraded',
          details: ok
            ? `${nodeCount} nodes (files: ${stats.fileCount ?? 0}, functions: ${stats.functionCount ?? 0}, classes: ${stats.classCount ?? 0}, modules: ${stats.moduleCount ?? 0})`
            : 'Graph database has 0 nodes — run code-structure ingestion'
        });
      } catch (error) {
        checks.push({
          component: 'Graph Database (Neo4j)',
          status: 'unhealthy',
          details: `Error: ${error.message}`
        });
      }
    } else {
      checks.push({
        component: 'Graph Database (Neo4j)',
        status: 'disabled',
        details: 'No data-access layer with graphDB available'
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

    // SDD Session tracking check (Phase 31)
    try {
      const activeSession = this.sessionManager.getSessionState();
      checks.push({
        component: 'SDD Session Tracking',
        status: 'healthy',
        details: activeSession 
          ? `Active: ${activeSession.phase} (${activeSession.completedSteps.length}/${activeSession.totalSteps || '?'} steps)` 
          : '9 session tools ready, no active session'
      });
    } catch (error) {
      checks.push({
        component: 'SDD Session Tracking',
        status: 'degraded',
        details: `Error: ${error.message}`
      });
    }

    // Format results
    const healthyCount = checks.filter(c => c.status === 'healthy').length;
    const degradedCount = checks.filter(c => c.status === 'degraded' || c.status === 'unhealthy').length;
    const totalCount = checks.length;
    
    const overallStatus = degradedCount > 0 
      ? (checks.some(c => c.status === 'unhealthy') ? 'UNHEALTHY' : 'DEGRADED')
      : 'HEALTHY';
    
    status += `**Overall Status**: ${overallStatus} (${healthyCount}/${totalCount} components healthy)\n\n`;
    
    checks.forEach(check => {
      const emoji = {
        'healthy': '[OK]',
        'degraded': '[WARN]',
        'unhealthy': '[ERROR]',
        'disabled': '[OFF]',
        'initializing': '[INIT]'
      }[check.status] || '[?]';
      
      status += `${emoji} **${check.component}**: ${check.status}`;
      if (detailed || check.status !== 'healthy') {
        status += ` - ${check.details}`;
      }
      status += '\n';
    });

    status += '\n';
    
    // Data validation details (always show if there are issues)
    if (dataValidation && (detailed || dataValidation.status !== 'healthy')) {
      status += `## Data Validation\n\n`;
      const v = dataValidation.validation;
      
      status += `| Check | Status | Details |\n`;
      status += `|-------|--------|--------|\n`;
      status += `| Heartbeat | ${v.heartbeat.passed ? '[OK]' : '[FAIL]'} | ${v.heartbeat.details} |\n`;
      status += `| Collections | ${v.collections.passed ? '[OK]' : '[FAIL]'} | ${v.collections.count} found (min: ${v.collections.expected}) |\n`;
      status += `| Documents | ${v.documents.passed ? '[OK]' : '[FAIL]'} | ${v.documents.count} total (min: ${v.documents.expected}) |\n`;
      if (!v.sampleQuery.skipped) {
        status += `| Sample Query | ${v.sampleQuery.passed ? '[OK]' : '[FAIL]'} | ${v.sampleQuery.details} |\n`;
      }
      status += '\n';
      
      if (v.documents.perCollection && detailed) {
        status += `### Documents per Collection\n\n`;
        for (const [name, count] of Object.entries(v.documents.perCollection)) {
          status += `- **${name}**: ${count}\n`;
        }
        status += '\n';
      }
    }
    
    if (detailed) {
      status += `## Recommendations\n\n`;
      
      checks.forEach(check => {
        if (check.status === 'unhealthy') {
          status += `- **${check.component}**: CRITICAL - ${check.details}\n`;
        } else if (check.status === 'degraded') {
          status += `- **${check.component}**: Check configuration and dependencies\n`;
        } else if (check.status === 'disabled') {
          status += `- **${check.component}**: Enable in configuration if needed\n`;
        }
      });
      
      // Add specific troubleshooting for data issues
      if (dataValidation && dataValidation.status !== 'healthy') {
        status += `\n### Troubleshooting Data Issues\n\n`;
        if (!dataValidation.validation.collections.passed) {
          status += `**Collections not found**: Check ChromaDB Docker mount path.\n`;
          status += `- Expected: \`-v /mcp_rag_eib/data/chromadb:/data:Z\`\n`;
          status += `- Verify with: \`docker exec chromadb ls -la /data/\`\n\n`;
        }
        if (!dataValidation.validation.documents.passed && dataValidation.validation.collections.passed) {
          status += `**Documents not found**: Data may not be ingested.\n`;
          status += `- Run ingestion: \`python3 scripts/ingest_*.py\`\n\n`;
        }
      }
      
      status += `\n## Week 2 Architecture\n\n`;
      status += `This server uses the consolidated Week 2 architecture with:\n`;
      status += `- Unified data access layer (Week 1)\n`;
      status += `- Modular tool organization (5 modules)\n`;
      status += `- No duplicate tools (21 unique tools)\n`;
      status += `- **Empirical health validation (v3.5.1+)**\n`;
    }

    // Functional validation tests (run actual tool queries to verify effectiveness)
    if (functional) {
      status += `\n## Functional Validation\n\n`;
      status += `Testing actual tool effectiveness with sample queries...\n\n`;
      
      const functionalTests = [];
      
      // Test 1: Can describe_component find J-Jobs in dev/jobs/?
      if (this.workflowInfoTools) {
        try {
          const result = await this.workflowInfoTools.describeComponent({ 
            component: 'JGDAS_FIT2OBS', 
            show_content: false 
          });
          const found = result?.content?.[0]?.text?.includes('dev/jobs/') || 
                        result?.content?.[0]?.text?.includes('JGDAS_FIT2OBS');
          functionalTests.push({
            name: 'Path Resolution (dev/jobs/)',
            tool: 'describe_component',
            query: 'JGDAS_FIT2OBS',
            passed: found,
            details: found ? 'Found J-Job in dev/jobs/' : 'J-Job not found - check path configuration'
          });
        } catch (error) {
          functionalTests.push({
            name: 'Path Resolution (dev/jobs/)',
            tool: 'describe_component',
            query: 'JGDAS_FIT2OBS',
            passed: false,
            details: `Error: ${error.message}`
          });
        }
      }
      
      // Test 2: Can list_job_scripts filter by search term?
      if (this.operationalTools) {
        try {
          const result = await this.operationalTools.listJobScripts({ 
            search: 'fit2obs',
            format: 'summary'
          });
          const text = result?.content?.[0]?.text || '';
          const foundFit2obs = text.includes('JGDAS_FIT2OBS') || text.includes('1 jobs');
          const filtered = !text.includes('89 jobs') && !text.includes('Total: 89');
          functionalTests.push({
            name: 'Search Filter (list_job_scripts)',
            tool: 'list_job_scripts',
            query: 'search: fit2obs',
            passed: foundFit2obs && filtered,
            details: foundFit2obs && filtered 
              ? 'Search filter working correctly' 
              : 'Search filter may not be filtering results'
          });
        } catch (error) {
          functionalTests.push({
            name: 'Search Filter (list_job_scripts)',
            tool: 'list_job_scripts',
            query: 'search: fit2obs',
            passed: false,
            details: `Error: ${error.message}`
          });
        }
      }
      
      // Test 3: Does search_documentation return relevant results?
      if (this.semanticSearchTools?.isInitialized) {
        try {
          const result = await this.semanticSearchTools.searchDocumentation({ 
            query: 'global forecast system initialization',
            max_results: 3
          });
          const text = result?.content?.[0]?.text || '';
          const hasResults = text.includes('Search Results') && !text.includes('No results');
          const relevantContent = text.toLowerCase().includes('forecast') || 
                                  text.toLowerCase().includes('gfs') ||
                                  text.toLowerCase().includes('workflow');
          functionalTests.push({
            name: 'Search Relevance',
            tool: 'search_documentation',
            query: 'global forecast system initialization',
            passed: hasResults && relevantContent,
            details: hasResults && relevantContent 
              ? 'Semantic search returning relevant results'
              : hasResults 
                ? 'Results found but relevance unclear'
                : 'No results found - check ChromaDB ingestion'
          });
        } catch (error) {
          functionalTests.push({
            name: 'Search Relevance',
            tool: 'search_documentation',
            query: 'global forecast system initialization',
            passed: false,
            details: `Error: ${error.message}`
          });
        }
      }
      
      // Test 4: Does Neo4j have code relationships?
      if (this.codeAnalysisTools) {
        try {
          const result = await this.codeAnalysisTools.findCallersCallees({ 
            function_name: 'forecast',
            depth: 1 
          });
          const text = result?.content?.[0]?.text || '';
          const hasRelationships = text.includes('Callers') || text.includes('Callees') || 
                                   text.includes('relationships');
          const notEmpty = !text.includes('not found') && !text.includes('No callers');
          functionalTests.push({
            name: 'Graph Relationships (Neo4j)',
            tool: 'find_callers_callees',
            query: 'function: forecast',
            passed: hasRelationships,
            details: hasRelationships && notEmpty
              ? 'Neo4j returning code relationships'
              : hasRelationships
                ? 'Neo4j connected but limited relationships found'
                : 'Neo4j may not have code indexed'
          });
        } catch (error) {
          functionalTests.push({
            name: 'Graph Relationships (Neo4j)',
            tool: 'find_callers_callees',
            query: 'function: forecast',
            passed: false,
            details: `Error: ${error.message}`
          });
        }
      }
      
      // Test 5: J-Job content in ChromaDB? Search for specific J-Job content
      if (this.semanticSearchTools?.isInitialized) {
        try {
          const result = await this.semanticSearchTools.searchDocumentation({ 
            query: 'JGDAS_FIT2OBS fit to observations verification prepbufr',
            max_results: 5
          });
          const text = result?.content?.[0]?.text || '';
          const hasJJobContent = text.includes('JGDAS') || text.includes('FIT2OBS') || 
                                 text.includes('fit2obs') || text.includes('prepbufr');
          functionalTests.push({
            name: 'J-Job Content in ChromaDB',
            tool: 'search_documentation',
            query: 'JGDAS_FIT2OBS fit to observations',
            passed: hasJJobContent,
            details: hasJJobContent 
              ? 'J-Job content indexed in ChromaDB'
              : 'J-Jobs NOT in ChromaDB - run Phase 27C ingestion'
          });
        } catch (error) {
          functionalTests.push({
            name: 'J-Job Content in ChromaDB',
            tool: 'search_documentation',
            query: 'JGDAS_FIT2OBS fit to observations',
            passed: false,
            details: `Error: ${error.message}`
          });
        }
      }
      
      // Test 6 (Phase 43): Knowledge base integrity check
      if (this.semanticSearchTools?.isInitialized && this.semanticSearchTools.checkKnowledgeIntegrity) {
        try {
          const result = await this.semanticSearchTools.checkKnowledgeIntegrity({ sample_size: 20 });
          const text = result?.content?.[0]?.text || '';
          const allPassed = text.includes('All checks passed');
          functionalTests.push({
            name: 'Knowledge Base Integrity',
            tool: 'check_knowledge_integrity',
            query: 'sample_size: 20',
            passed: allPassed,
            details: allPassed
              ? 'All integrity checks passed'
              : 'Some integrity checks flagged warnings — run check_knowledge_integrity() for details'
          });
        } catch (error) {
          functionalTests.push({
            name: 'Knowledge Base Integrity',
            tool: 'check_knowledge_integrity',
            query: 'sample_size: 20',
            passed: false,
            details: `Error: ${error.message}`
          });
        }
      }
      
      // Format functional test results
      const passedCount = functionalTests.filter(t => t.passed).length;
      const totalTests = functionalTests.length;
      const functionalStatus = passedCount === totalTests ? 'PASS' : 
                               passedCount >= totalTests / 2 ? 'PARTIAL' : 'FAIL';
      
      status += `| Test | Tool | Status | Details |\n`;
      status += `|------|------|--------|--------|\n`;
      functionalTests.forEach(test => {
        status += `| ${test.name} | \`${test.tool}\` | ${test.passed ? '[PASS]' : '[FAIL]'} | ${test.details} |\n`;
      });
      status += `\n**Functional Status**: ${functionalStatus} (${passedCount}/${totalTests} tests passed)\n`;
      
      // Add remediation guidance for failed tests
      const failedTests = functionalTests.filter(t => !t.passed);
      if (failedTests.length > 0) {
        status += `\n### Remediation Required\n\n`;
        for (const test of failedTests) {
          if (test.name.includes('Path Resolution')) {
            status += `- **${test.name}**: Update WorkflowInfoTools.js searchPaths to include \`dev/jobs/\`\n`;
          } else if (test.name.includes('Search Filter')) {
            status += `- **${test.name}**: Check OperationalTools.js list_job_scripts implementation\n`;
          } else if (test.name.includes('Search Relevance')) {
            status += `- **${test.name}**: Verify ChromaDB collections and run documentation ingestion\n`;
          } else if (test.name.includes('Graph Relationships')) {
            status += `- **${test.name}**: Run Neo4j code ingestion for global-workflow repository\n`;
          } else if (test.name.includes('J-Job Content')) {
            status += `- **${test.name}**: Run Phase 27C J-Job ChromaDB ingestion (see phase27_jjob_script_rag_enhancement.md)\n`;
          }
        }
      }
    }

    // Phase 43: Health snapshot persistence + drift detection (deep mode only)
    if (deep) {
      try {
        const healthHistoryPath = join(__dirname, '..', '..', 'sdd_framework', 'execution_state', 'health_history.jsonl');
        const healthHistoryDir = dirname(healthHistoryPath);
        if (!existsSync(healthHistoryDir)) {
          mkdirSync(healthHistoryDir, { recursive: true });
        }

        // Build snapshot from collected health data
        const snapshot = {
          timestamp: new Date().toISOString(),
          source: 'tool_call',
          neo4j: { status: 'unknown', nodes: 0, relationships: 0, latency_ms: null },
          chromadb: { status: 'unknown', collections: 0, total_docs: 0, latency_ms: null },
          drift: { neo4j_node_delta: 0, chromadb_doc_delta: 0 }
        };

        // Populate ChromaDB stats from dataValidation (collected earlier)
        if (dataValidation) {
          snapshot.chromadb.status = dataValidation.status || 'unknown';
          snapshot.chromadb.collections = dataValidation.collections?.length || 0;
          snapshot.chromadb.total_docs = dataValidation.totalDocuments || 0;
          snapshot.chromadb.latency_ms = dataValidation.latencyMs || null;
        }

        // Populate Neo4j stats via graph database query
        const graphDB = this.codeAnalysisTools?.dataAccess?.graphDB || this.graphRAGTools?.dataAccess?.graphDB;
        if (graphDB) {
          try {
            const startMs = Date.now();
            const nodeResult = await graphDB.query(
              'MATCH (n) RETURN count(n) AS count'
            );
            const relResult = await graphDB.query(
              'MATCH ()-[r]->() RETURN count(r) AS count'
            );
            snapshot.neo4j.latency_ms = Date.now() - startMs;
            snapshot.neo4j.status = 'ok';
            snapshot.neo4j.nodes = nodeResult?.[0]?.count || 0;
            snapshot.neo4j.relationships = relResult?.[0]?.count || 0;
          } catch {
            snapshot.neo4j.status = 'error';
          }
        }

        // Compute drift from previous snapshot
        let previousSnapshot = null;
        if (existsSync(healthHistoryPath)) {
          try {
            const lines = readFileSync(healthHistoryPath, 'utf-8').trim().split('\n').filter(l => l);
            if (lines.length > 0) {
              previousSnapshot = JSON.parse(lines[lines.length - 1]);
            }
          } catch {
            // Ignore parse errors on previous snapshot
          }
        }

        if (previousSnapshot) {
          snapshot.drift.neo4j_node_delta = snapshot.neo4j.nodes - (previousSnapshot.neo4j?.nodes || 0);
          snapshot.drift.chromadb_doc_delta = snapshot.chromadb.total_docs - (previousSnapshot.chromadb?.total_docs || 0);

          // Emit drift warnings if >10% change
          const prevNodes = previousSnapshot.neo4j?.nodes || 0;
          const prevDocs = previousSnapshot.chromadb?.total_docs || 0;
          const driftWarnings = [];

          if (prevNodes > 0) {
            const nodePct = Math.abs(snapshot.drift.neo4j_node_delta) / prevNodes;
            if (nodePct > 0.10) {
              driftWarnings.push(`Neo4j node count changed by ${snapshot.drift.neo4j_node_delta} (${(nodePct * 100).toFixed(1)}% from ${prevNodes})`);
            }
          }
          if (prevDocs > 0) {
            const docPct = Math.abs(snapshot.drift.chromadb_doc_delta) / prevDocs;
            if (docPct > 0.10) {
              driftWarnings.push(`ChromaDB document count changed by ${snapshot.drift.chromadb_doc_delta} (${(docPct * 100).toFixed(1)}% from ${prevDocs})`);
            }
          }

          if (driftWarnings.length > 0) {
            status += `\n## Health Drift Warnings\n\n`;
            driftWarnings.forEach(w => {
              status += `[WARN] ${w}\n`;
            });
            status += '\n';
          }
        }

        // Append snapshot
        appendFileSync(healthHistoryPath, JSON.stringify(snapshot) + '\n');
        status += `\n*Health snapshot persisted to health_history.jsonl*\n`;

      } catch (error) {
        console.error(`[WARN] Failed to persist health snapshot: ${error.message}`);
      }
    }

    return status;
  }

  /**
   * Phase 43: Get health trend from persisted snapshots
   */
  async getHealthTrend(args = {}) {
    const { limit = 10 } = args;
    const healthHistoryPath = join(__dirname, '..', '..', 'sdd_framework', 'execution_state', 'health_history.jsonl');

    if (!existsSync(healthHistoryPath)) {
      return {
        content: [{
          type: 'text',
          text: '# Health Trend\n\nNo health history found. Run `mcp_health_check({ deep: true })` to generate the first snapshot.'
        }]
      };
    }

    let snapshots;
    try {
      const lines = readFileSync(healthHistoryPath, 'utf-8').trim().split('\n').filter(l => l);
      snapshots = lines.slice(-limit).map(l => JSON.parse(l));
    } catch (error) {
      return {
        content: [{
          type: 'text',
          text: `# Health Trend\n\n[ERROR] Failed to read health history: ${error.message}`
        }]
      };
    }

    if (snapshots.length === 0) {
      return {
        content: [{
          type: 'text',
          text: '# Health Trend\n\nHealth history file is empty. Run `mcp_health_check({ deep: true })` to generate snapshots.'
        }]
      };
    }

    let md = `# Health Trend (last ${snapshots.length} snapshots)\n\n`;

    // Summary table
    md += '| Timestamp | Neo4j Nodes | Neo4j Rels | ChromaDB Docs | Collections | Node Drift | Doc Drift |\n';
    md += '|-----------|-------------|------------|---------------|-------------|------------|----------|\n';
    for (const s of snapshots) {
      const ts = s.timestamp ? new Date(s.timestamp).toISOString().replace('T', ' ').slice(0, 19) : '?';
      md += `| ${ts} | ${s.neo4j?.nodes ?? '?'} | ${s.neo4j?.relationships ?? '?'} | ${s.chromadb?.total_docs ?? '?'} | ${s.chromadb?.collections ?? '?'} | ${s.drift?.neo4j_node_delta ?? 0} | ${s.drift?.chromadb_doc_delta ?? 0} |\n`;
    }
    md += '\n';

    // Count trends
    if (snapshots.length >= 2) {
      const first = snapshots[0];
      const last = snapshots[snapshots.length - 1];

      const nodeTrend = (last.neo4j?.nodes ?? 0) - (first.neo4j?.nodes ?? 0);
      const docTrend = (last.chromadb?.total_docs ?? 0) - (first.chromadb?.total_docs ?? 0);
      const trendLabel = (v) => v > 0 ? 'increasing' : v < 0 ? 'decreasing' : 'stable';

      md += `## Trends\n\n`;
      md += `- **Neo4j nodes**: ${trendLabel(nodeTrend)} (${nodeTrend >= 0 ? '+' : ''}${nodeTrend} over ${snapshots.length} snapshots)\n`;
      md += `- **ChromaDB docs**: ${trendLabel(docTrend)} (${docTrend >= 0 ? '+' : ''}${docTrend} over ${snapshots.length} snapshots)\n`;

      // Latency trends
      const neo4jLatencies = snapshots.map(s => s.neo4j?.latency_ms).filter(v => v != null);
      const chromaLatencies = snapshots.map(s => s.chromadb?.latency_ms).filter(v => v != null);

      if (neo4jLatencies.length >= 2) {
        const avgLatency = neo4jLatencies.reduce((a, b) => a + b, 0) / neo4jLatencies.length;
        const latTrend = neo4jLatencies[neo4jLatencies.length - 1] - neo4jLatencies[0];
        md += `- **Neo4j latency**: avg ${avgLatency.toFixed(0)}ms, trend ${latTrend >= 0 ? '+' : ''}${latTrend}ms (${latTrend > 0 ? 'degrading' : 'improving'})\n`;
      }
      if (chromaLatencies.length >= 2) {
        const avgLatency = chromaLatencies.reduce((a, b) => a + b, 0) / chromaLatencies.length;
        const latTrend = chromaLatencies[chromaLatencies.length - 1] - chromaLatencies[0];
        md += `- **ChromaDB latency**: avg ${avgLatency.toFixed(0)}ms, trend ${latTrend >= 0 ? '+' : ''}${latTrend}ms (${latTrend > 0 ? 'degrading' : 'improving'})\n`;
      }
      md += '\n';

      // Anomaly detection (>10% change between consecutive snapshots)
      const anomalies = [];
      for (let i = 1; i < snapshots.length; i++) {
        const prev = snapshots[i - 1];
        const curr = snapshots[i];
        const prevNodes = prev.neo4j?.nodes || 0;
        const currNodes = curr.neo4j?.nodes || 0;
        const prevDocs = prev.chromadb?.total_docs || 0;
        const currDocs = curr.chromadb?.total_docs || 0;

        if (prevNodes > 0 && Math.abs(currNodes - prevNodes) / prevNodes > 0.10) {
          anomalies.push(`[WARN] Neo4j node count jumped from ${prevNodes} to ${currNodes} at ${curr.timestamp}`);
        }
        if (prevDocs > 0 && Math.abs(currDocs - prevDocs) / prevDocs > 0.10) {
          anomalies.push(`[WARN] ChromaDB doc count jumped from ${prevDocs} to ${currDocs} at ${curr.timestamp}`);
        }
      }

      if (anomalies.length > 0) {
        md += `## Anomalies Detected\n\n`;
        anomalies.forEach(a => { md += `${a}\n`; });
        md += '\n';
      } else {
        md += `## Anomalies\n\nNo anomalies detected (all consecutive changes within 10% threshold).\n\n`;
      }
    }

    return { content: [{ type: 'text', text: md }] };
  }

  /**
   * Get RAG quality benchmark metrics
   */
  async getQualityMetrics(args = {}) {
    const { category, compare = false } = args;
    const resultsDir = join(__dirname, '..', 'test', 'benchmark', 'results');

    if (!existsSync(resultsDir)) {
      return {
        content: [{
          type: 'text',
          text: '# RAG Quality Metrics\n\nNo benchmark results directory found.\n\nRun the benchmark harness to generate results:\n```\nnpm run benchmark\n```\nExpected path: `test/benchmark/results/`'
        }]
      };
    }

    let jsonFiles;
    try {
      jsonFiles = readdirSync(resultsDir)
        .filter(f => f.endsWith('.json'))
        .sort()
        .reverse();
    } catch (err) {
      return {
        content: [{
          type: 'text',
          text: `# RAG Quality Metrics\n\n[ERROR] Failed to read results directory: ${err.message}`
        }]
      };
    }

    if (jsonFiles.length === 0) {
      return {
        content: [{
          type: 'text',
          text: '# RAG Quality Metrics\n\nNo benchmark result files found.\n\nRun the benchmark harness to generate results:\n```\nnpm run benchmark\n```'
        }]
      };
    }

    let latest;
    try {
      latest = JSON.parse(readFileSync(join(resultsDir, jsonFiles[0]), 'utf-8'));
    } catch (err) {
      return {
        content: [{
          type: 'text',
          text: `# RAG Quality Metrics\n\n[ERROR] Failed to parse latest result (${jsonFiles[0]}): ${err.message}`
        }]
      };
    }

    const fmtPct = (v) => v != null ? `${(v * 100).toFixed(0)}%` : 'N/A';
    const fmtVal = (v) => v != null ? v.toFixed(2) : 'N/A';
    const fmtMs = (v) => v != null ? `${v}ms` : 'N/A';
    const fmtCategoryName = (key) => key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

    let md = '# RAG Quality Metrics\n\n';
    md += `**Benchmark**: ${latest.timestamp || 'Unknown'}\n`;
    md += `**Corpus Version**: ${latest.corpus_version || latest.version || 'Unknown'}`;
    md += ` (${latest.total_queries || 'N/A'} queries)\n\n`;

    // Overall metrics
    if (latest.overall) {
      const o = latest.overall;
      md += '## Overall\n\n';
      md += '| Metric | Value |\n';
      md += '|--------|-------|\n';
      md += `| Precision@5 | ${fmtVal(o.precision_at_k)} |\n`;
      md += `| Recall@5 | ${fmtVal(o.recall_at_k)} |\n`;
      md += `| MRR | ${fmtVal(o.mrr)} |\n`;
      md += `| Coverage | ${fmtPct(o.coverage)} |\n`;
      md += `| Latency P50 | ${fmtMs(o.latency_p50_ms)} |\n`;
      md += `| Latency P95 | ${fmtMs(o.latency_p95_ms)} |\n`;
      md += '\n';
    }

    // Per-category breakdown
    if (latest.categories) {
      const cats = Object.entries(latest.categories);
      const filtered = category
        ? cats.filter(([key]) => key === category)
        : cats;

      if (filtered.length > 0) {
        md += category ? `## Category: ${fmtCategoryName(category)}\n\n` : '## By Category\n\n';
        md += '| Category | P@5 | R@5 | MRR | Coverage | P50 |\n';
        md += '|----------|-----|-----|-----|----------|-----|\n';
        for (const [key, c] of filtered) {
          md += `| ${fmtCategoryName(key)} | ${fmtVal(c.precision_at_k)} | ${fmtVal(c.recall_at_k)} | ${fmtVal(c.mrr)} | ${fmtPct(c.coverage)} | ${fmtMs(c.latency_p50_ms)} |\n`;
        }
        md += '\n';
      } else if (category) {
        md += `## Category: ${fmtCategoryName(category)}\n\nNo results found for category \`${category}\`.\n\n`;
      }
    }

    // Regression comparison
    if (compare && jsonFiles.length >= 2) {
      let previous;
      try {
        previous = JSON.parse(readFileSync(join(resultsDir, jsonFiles[1]), 'utf-8'));
      } catch (err) {
        md += `## Regression\n\n[WARN] Failed to parse previous result (${jsonFiles[1]}): ${err.message}\n`;
      }

      if (previous && previous.categories && latest.categories) {
        md += `## Regression (vs ${previous.timestamp || jsonFiles[1]})\n\n`;
        md += '| Category | Metric | Previous | Current | Delta |\n';
        md += '|----------|--------|----------|---------|-------|\n';

        const metrics = [
          { key: 'precision_at_k', label: 'P@5', fmt: fmtVal },
          { key: 'recall_at_k', label: 'R@5', fmt: fmtVal },
          { key: 'mrr', label: 'MRR', fmt: fmtVal },
          { key: 'coverage', label: 'Coverage', fmt: fmtPct },
          { key: 'latency_p50_ms', label: 'P50', fmt: fmtMs }
        ];

        const allCats = new Set([
          ...Object.keys(latest.categories),
          ...Object.keys(previous.categories)
        ]);
        const filteredCats = category
          ? [...allCats].filter(k => k === category)
          : [...allCats];

        for (const cat of filteredCats) {
          const cur = latest.categories[cat] || {};
          const prev = previous.categories[cat] || {};
          for (const m of metrics) {
            const curVal = cur[m.key];
            const prevVal = prev[m.key];
            if (curVal == null && prevVal == null) continue;

            let deltaStr = 'N/A';
            if (curVal != null && prevVal != null && prevVal !== 0) {
              const deltaPct = ((curVal - prevVal) / Math.abs(prevVal)) * 100;
              const sign = deltaPct >= 0 ? '+' : '';
              // For latency, lower is better (invert tag logic)
              const isLatency = m.key.startsWith('latency_');
              const tag = isLatency
                ? (deltaPct <= 0 ? '[IMPROVED]' : '[DEGRADED]')
                : (deltaPct >= 0 ? '[IMPROVED]' : '[DEGRADED]');
              deltaStr = `${sign}${deltaPct.toFixed(0)}% ${tag}`;
            }

            md += `| ${fmtCategoryName(cat)} | ${m.label} | ${m.fmt(prevVal)} | ${m.fmt(curVal)} | ${deltaStr} |\n`;
          }
        }
        md += '\n';
      }
    } else if (compare) {
      md += '## Regression\n\nOnly one benchmark result available. Run the benchmark again to enable comparison.\n';
    }

    return { content: [{ type: 'text', text: md }] };
  }

  /**
   * Run vitest unit tests and return structured results.
   * Spawns `npx vitest run` as a child process — no database connections needed.
   */
  async runUnitTests(args = {}) {
    const { file, verbose = false } = args;
    const { execSync } = await import('node:child_process');

    const serverRoot = join(__dirname, '..');
    const testDir = 'src/__tests__';
    let target = testDir;
    if (file) {
      const normalized = file.endsWith('.test.js') ? file : `${file}.test.js`;
      target = join(testDir, normalized);
    }

    let md = '# Unit Test Results\n\n';
    let raw = '';
    let exitCode = 0;

    try {
      raw = execSync(`npx vitest run ${target} --reporter=verbose 2>&1`, {
        cwd: serverRoot,
        encoding: 'utf-8',
        timeout: 120_000,
        env: { ...process.env, FORCE_COLOR: '0', NO_COLOR: '1' }
      });
    } catch (err) {
      // vitest exits non-zero when tests fail — still capture stdout
      raw = err.stdout || err.stderr || err.message || 'Unknown error';
      exitCode = err.status || 1;
    }

    // Parse summary line: " Test Files  7 passed (7)" / " Tests  65 passed (65)"
    const filesMatch = raw.match(/Test Files\s+(?:(\d+)\s+failed\s+\|\s+)?(\d+)\s+passed\s+\((\d+)\)/);
    const testsMatch = raw.match(/Tests\s+(?:(\d+)\s+failed\s+\|\s+)?(\d+)\s+passed\s+\((\d+)\)/);
    const durationMatch = raw.match(/Duration\s+([\d.]+s)/);

    const filesFailed = filesMatch ? parseInt(filesMatch[1] || '0', 10) : 0;
    const filesPassed = filesMatch ? parseInt(filesMatch[2], 10) : 0;
    const filesTotal = filesMatch ? parseInt(filesMatch[3], 10) : 0;
    const testsFailed = testsMatch ? parseInt(testsMatch[1] || '0', 10) : 0;
    const testsPassed = testsMatch ? parseInt(testsMatch[2], 10) : 0;
    const testsTotal = testsMatch ? parseInt(testsMatch[3], 10) : 0;
    const duration = durationMatch ? durationMatch[1] : 'unknown';

    const allPass = testsFailed === 0 && filesFailed === 0 && exitCode === 0;

    md += `**Status**: ${allPass ? '[OK] ALL TESTS PASS' : '[FAIL] TEST FAILURES DETECTED'}\n`;
    md += `**Target**: \`${target}\`\n`;
    md += `**Duration**: ${duration}\n\n`;

    md += '| Metric | Passed | Failed | Total |\n';
    md += '|--------|--------|--------|-------|\n';
    md += `| Test Files | ${filesPassed} | ${filesFailed} | ${filesTotal} |\n`;
    md += `| Tests | ${testsPassed} | ${testsFailed} | ${testsTotal} |\n\n`;

    if (!allPass) {
      // Extract failure details
      const failBlocks = raw.match(/FAIL\s+.*?(?=\n\n(?:\s*(?:✓|FAIL|Test Files)|\s*$))/gs);
      if (failBlocks) {
        md += '## Failures\n\n';
        for (const block of failBlocks.slice(0, 10)) {
          md += '```\n' + block.trim() + '\n```\n\n';
        }
      }
      md += '**[WARN] Fix test failures before committing.**\n\n';
    } else {
      md += '[OK] Safe to proceed with `git add` and `git commit`.\n\n';
    }

    if (verbose) {
      md += '## Full Output\n\n```\n' + raw.slice(-8000) + '\n```\n';
    }

    return { content: [{ type: 'text', text: md }] };
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