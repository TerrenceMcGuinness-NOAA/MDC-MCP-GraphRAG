#!/usr/bin/env node

/**
 * Operational Tools Module
 * 
 * HPC operational procedures, platform guidance, and workflow explanations.
 * Leverages UnifiedDataAccess for context-aware operational assistance.
 * 
 * Features:
 * - Platform-specific operational guidance (HERA, HERCULES, ORION, WCOSS2, GAEA)
 * - Workflow component explanations with graph context
 * - Job script cataloging and categorization
 * - Urgency-based procedure prioritization
 * 
 * @version 2.0.0
 * @author Claude Sonnet 4.5
 * @supervisor Terry McGuinness
 * @date 2025-10-16
 */

import { UnifiedDataAccess } from '../data/UnifiedDataAccess.js';
import fs from 'fs/promises';
import path from 'path';

export class OperationalTools {
  constructor(dataAccess = null) {
    this.dataAccess = dataAccess;  // Accept injected dependency for testing
    this.isInitialized = !!dataAccess;  // Already initialized if dataAccess provided
    this.workflowRoot = process.env.MCP_WORKFLOW_ROOT || process.env.HOMEgfs || '/mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow';
  }

  async initialize() {
    if (this.isInitialized) return;

    console.error('[INIT] Initializing Operational Tools...');
    
    this.dataAccess = new UnifiedDataAccess();
    await this.dataAccess.connect();  // Fixed: connect() not initialize()
    
    this.isInitialized = true;
    console.error('[OK] Operational Tools initialized');
  }

  registerWith(server) {
    // Tool 1: Get Operational Guidance
    server.registerTool(
      'get_operational_guidance',
      'Get operational guidance and best practices for HPC operations',
      {
        type: 'object',
        properties: {
          operation: { type: 'string', description: 'Operation or procedure to get guidance for' },
          platform: {
            type: 'string',
            enum: ['hera', 'hercules', 'orion', 'wcoss2', 'gaea', 'generic'],
            default: 'generic',
            description: 'HPC platform context'
          },
          urgency: {
            type: 'string',
            enum: ['routine', 'urgent', 'emergency'],
            default: 'routine',
            description: 'Operational urgency level'
          }
        },
        required: ['operation']
      },
      this.getOperationalGuidance.bind(this)
    );

    // Tool 2: Explain Workflow Component
    server.registerTool(
      'explain_workflow_component',
      'Get detailed explanation of a workflow component with graph context',
      {
        type: 'object',
        properties: {
          component: { type: 'string', description: 'Component name (job script, config file, or directory)' },
          detail_level: {
            type: 'string',
            enum: ['basic', 'detailed', 'expert'],
            default: 'detailed',
            description: 'Level of detail in explanation'
          }
        },
        required: ['component']
      },
      this.explainWorkflowComponent.bind(this)
    );

    // Tool 3: List Job Scripts
    server.registerTool(
      'list_job_scripts',
      'List and categorize job scripts in the workflow',
      {
        type: 'object',
        properties: {
          category: {
            type: 'string',
            enum: ['analysis', 'forecast', 'post', 'archive', 'all'],
            description: 'Filter by job category'
          },
          format: {
            type: 'string',
            enum: ['summary', 'detailed', 'json'],
            default: 'summary',
            description: 'Output format'
          },
          job_list: {
            type: 'array',
            items: { type: 'string' },
            description: 'List of job script names (for remote MCP access - bypasses filesystem)'
          },
          files: {
            type: 'array',
            items: {
              type: 'object',
              properties: {
                name: { type: 'string', description: 'Job script filename' },
                content: { type: 'string', description: 'Job script content' }
              }
            },
            description: 'Job files with content (for detailed remote analysis)'
          }
        }
      },
      this.listJobScripts.bind(this)
    );

    console.error('[OK] Registered 3 Operational tools');
  }

  async getOperationalGuidance(args) {
    await this.ensureInitialized();
    const { operation, platform = 'generic', urgency = 'routine' } = args;

    try {
      // Search for operational procedures in documentation
      const query = `${operation} ${platform} operational procedure best practices`;
      const results = await this.dataAccess.hybridQuery(query, {
        maxResults: 5,
        includeGraph: true,
        graphDepth: 1
      });

      let output = `# Operational Guidance: ${operation}\n\n`;
      output += `**Platform:** ${platform.toUpperCase()}\n`;
      output += `**Urgency:** ${urgency.toUpperCase()}\n\n`;

      if (urgency === 'emergency') {
        output += `[WARN]  **EMERGENCY PROCEDURE**\n\n`;
        output += `1. Check system logs immediately\n`;
        output += `2. Contact on-call staff if needed\n`;
        output += `3. Follow emergency protocols\n\n`;
      }

      output += `## Procedure\n\n`;

      if (results && results.length > 0) {
        for (const result of results) {
          output += `${result.document || result.text}\n\n`;
        }
      } else {
        output += `### General Guidance\n\n`;
        output += `For ${operation} on ${platform}:\n\n`;
        output += `1. Check environment configuration in env/${platform.toUpperCase()}.env\n`;
        output += `2. Review relevant job scripts in jobs/ directory\n`;
        output += `3. Verify module loads and dependencies\n`;
        output += `4. Monitor job execution logs\n`;
        output += `5. Follow platform-specific submission procedures\n\n`;
      }

      // Add platform-specific notes
      output += `## Platform-Specific Notes\n\n`;
      const platformNotes = {
        'hera': '- NOAA RDHPCS system\n- Use Slurm for job submission\n- Module loads: HERA.env\n',
        'hercules': '- MSU research system\n- Slurm scheduler\n- Module loads: HERCULES.env\n',
        'orion': '- MSU research system\n- Slurm scheduler\n- Module loads: ORION.env\n',
        'wcoss2': '- NOAA operational system\n- PBS scheduler\n- Module loads: WCOSS2.env\n',
        'gaea': '- NOAA operational system\n- Slurm scheduler\n- Module loads: GAEA.env\n',
        'generic': '- Platform-agnostic procedures\n- Adapt to local scheduler\n- Check platform detection\n'
      };
      output += platformNotes[platform] || platformNotes['generic'];

      return { content: [{ type: 'text', text: output }] };
    } catch (error) {
      return {
        content: [{ type: 'text', text: `Error getting operational guidance: ${error.message}` }],
        isError: true
      };
    }
  }

  async explainWorkflowComponent(args) {
    await this.ensureInitialized();
    const { component, detail_level = 'detailed' } = args;

    try {
      // Search for component in both vector DB and graph DB
      const results = await this.dataAccess.multiSourceSearch(component, {
        sources: ['vector', 'graph'],
        maxResults: 5
      });

      let output = `# Workflow Component: ${component}\n\n`;
      output += `**Detail Level:** ${detail_level}\n\n`;

      // Vector search results (documentation)
      if (results.vector && results.vector.length > 0) {
        output += `## Documentation\n\n`;
        for (const result of results.vector.slice(0, 2)) {
          output += `${result.document || result.text}\n\n`;
        }
      }

      // Graph search results (code structure)
      if (results.graph && results.graph.length > 0) {
        output += `## Code Structure\n\n`;
        for (const item of results.graph) {
          output += `### ${item.name || item.file}\n`;
          output += `- **Type:** ${item.type || 'Component'}\n`;
          if (item.path) output += `- **Path:** ${item.path}\n`;
          if (item.language) output += `- **Language:** ${item.language}\n`;
          output += `\n`;
        }
      }

      // Try to find related dependencies
      if (results.graph && results.graph.length > 0) {
        const firstComponent = results.graph[0];
        if (firstComponent.file) {
          const imports = await this.dataAccess.graphDb.findFileImports(firstComponent.file);
          if (imports && imports.length > 0) {
            output += `## Dependencies\n\n`;
            for (const imp of imports.slice(0, 5)) {
              output += `- ${imp.importedFile}\n`;
            }
            output += `\n`;
          }
        }
      }

      if (detail_level === 'expert') {
        output += `## Expert Notes\n\n`;
        output += `- Check source in repository for latest implementation\n`;
        output += `- Review associated test files for usage examples\n`;
        output += `- Consult platform-specific configurations in env/ directory\n`;
        output += `- Verify integration points in workflow XML definitions\n`;
      }

      return { content: [{ type: 'text', text: output }] };
    } catch (error) {
      return {
        content: [{ type: 'text', text: `Error explaining component: ${error.message}` }],
        isError: true
      };
    }
  }

  async listJobScripts(args) {
    const { category, format = 'summary', job_list, files: providedFiles } = args || {};

    try {
      let jobFiles = [];
      let jobsDir = null;
      let contentMap = {};  // For detailed format with provided content
      let sourceNote = '';

      // Priority: job_list > files > filesystem
      if (job_list && job_list.length > 0) {
        // Job list provided directly (remote MCP access)
        jobFiles = job_list.filter(f => f.startsWith('J'));
        sourceNote = '*Source: job_list parameter (remote access)*\n\n';
      } else if (providedFiles && providedFiles.length > 0) {
        // Files with content provided (remote MCP access with details)
        jobFiles = providedFiles.filter(f => f.name && f.name.startsWith('J')).map(f => f.name);
        for (const f of providedFiles) {
          if (f.name && f.content) {
            contentMap[f.name] = f.content;
          }
        }
        sourceNote = '*Source: files parameter (remote access with content)*\n\n';
      } else {
        // Try multiple possible job directory locations (local filesystem)
        const possibleJobDirs = [
          path.join(this.workflowRoot, 'jobs'),
          path.join(this.workflowRoot, 'dev', 'jobs'),
        ];
        
        let files = [];
        
        for (const dir of possibleJobDirs) {
          try {
            files = await fs.readdir(dir);
            jobsDir = dir;
            break;
          } catch {
            continue;
          }
        }
        
        if (!jobsDir) {
          return {
            content: [{ type: 'text', text: `Jobs directory not found: ${this.workflowRoot}/jobs\n\n**Searched paths:**\n${possibleJobDirs.map(p => `- ${p}`).join('\n')}\n\n**Hint:** Use 'job_list' parameter to provide job names directly for remote access.\nOr use 'files' parameter with [{name, content}] for detailed analysis.\nOr set MCP_WORKFLOW_ROOT environment variable to the global-workflow repository root.` }],
            isError: true
          };
        }

        // Filter for job files (J* pattern)
        jobFiles = files.filter(f => f.startsWith('J'));
      }

      // Categorize jobs
      const categories = {
        analysis: jobFiles.filter(f => /atm|anl|anal/i.test(f)),
        forecast: jobFiles.filter(f => /fcst|forecast/i.test(f)),
        post: jobFiles.filter(f => /post|upp|awips/i.test(f)),
        archive: jobFiles.filter(f => /arch|clean/i.test(f)),
        all: jobFiles
      };

      const targetCategory = category || 'all';
      const jobList = categories[targetCategory] || categories['all'];

      let output = `# Job Scripts\n\n`;
      output += `**Category:** ${targetCategory}\n`;
      output += `**Total:** ${jobList.length} jobs\n\n`;

      if (format === 'json') {
        return {
          content: [{ type: 'text', text: JSON.stringify({ category: targetCategory, jobs: jobList }, null, 2) }]
        };
      }

      // Add source note if using provided content
      if (job_list || providedFiles) {
        output += `**Source:** Content provided via parameter (container-compatible mode)\n\n`;
      }

      if (format === 'detailed') {
        for (const job of jobList.sort()) {
          output += `## ${job}\n`;
          // Use contentMap if available, otherwise try filesystem
          if (contentMap[job]) {
            const content = contentMap[job];
            const lines = content.split('\n');
            const descLine = lines.find(l => l.includes('Description') || l.includes('PURPOSE'));
            if (descLine) {
              output += `${descLine.trim()}\n`;
            } else {
              output += `Job control script (content provided)\n`;
            }
          } else {
            // Fallback to filesystem for local mode
            const filePath = path.join(jobsDir, job);
            try {
              const content = await fs.readFile(filePath, 'utf-8');
              const lines = content.split('\n');
              const descLine = lines.find(l => l.includes('Description') || l.includes('PURPOSE'));
              if (descLine) {
                output += `${descLine.trim()}\n`;
              }
            } catch {
              output += `Job control script\n`;
            }
          }
          output += `\n`;
        }
      } else {
        // Summary format
        output += `## Categories\n\n`;
        output += `- **Analysis:** ${categories.analysis.length} jobs\n`;
        output += `- **Forecast:** ${categories.forecast.length} jobs\n`;
        output += `- **Post-Processing:** ${categories.post.length} jobs\n`;
        output += `- **Archive:** ${categories.archive.length} jobs\n\n`;

        output += `## Job List\n\n`;
        for (const job of jobList.sort()) {
          output += `- ${job}\n`;
        }
      }

      return { content: [{ type: 'text', text: output }] };
    } catch (error) {
      return {
        content: [{ type: 'text', text: `Error listing job scripts: ${error.message}` }],
        isError: true
      };
    }
  }

  async ensureInitialized() {
    if (!this.isInitialized) {
      await this.initialize();
    }
  }

  async cleanup() {
    if (this.dataAccess) {
      await this.dataAccess.close();
      this.dataAccess = null;
    }
    this.isInitialized = false;
  }
}

export default OperationalTools;
