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
 * @version 2.1.0 - Phase 27E embedding support
 * @author Claude Sonnet 4.5
 * @supervisor Terry McGuinness
 * @date 2026-02-04
 */

import { UnifiedDataAccess } from '../data/UnifiedDataAccess.js';
import * as embeddings from '../utils/embeddings.js';
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
          topic: { type: 'string', description: 'Operation or procedure to get guidance for (canonical parameter)' },
          operation: { type: 'string', description: 'Alias for `topic` (deprecated; kept for backward compatibility)' },
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
        anyOf: [
          { required: ['topic'] },
          { required: ['operation'] }
        ]
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
            enum: ['analysis', 'forecast', 'post', 'archive', 'verification', 'all'],
            description: 'Filter by job category'
          },
          search: {
            type: 'string',
            description: 'Filter jobs by name or description (case-insensitive substring match)'
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

    // Tool 4: Get Job Details (Phase 27E)
    server.registerTool(
      'get_job_details',
      'Get comprehensive details about a J-Job including inputs, outputs, dependencies, configs, and ChromaDB semantic context',
      {
        type: 'object',
        properties: {
          job_name: {
            type: 'string',
            description: 'J-Job name (e.g., JGDAS_FIT2OBS, JGLOBAL_FORECAST)'
          },
          include_content: {
            type: 'boolean',
            default: false,
            description: 'Include full script content in response'
          },
          include_config: {
            type: 'boolean',
            default: true,
            description: 'Include related config file content'
          },
          include_chromadb: {
            type: 'boolean',
            default: true,
            description: 'Include ChromaDB semantic search results for related documentation'
          }
        },
        required: ['job_name']
      },
      this.getJobDetails.bind(this)
    );

    console.error('[OK] Registered 4 Operational tools');
  }

  async getOperationalGuidance(args) {
    await this.ensureInitialized();
    // Phase 53 D9: accept `topic` as the canonical parameter and `operation`
    // as a backwards-compatible alias. Schema still advertises both.
    if (args.topic && !args.operation) {
      console.error('[INFO] get_operational_guidance: using `topic`; `operation` remains accepted as alias');
    } else if (args.operation && !args.topic) {
      console.error('[WARN] get_operational_guidance: `operation` is now an alias; prefer `topic`');
    }
    const operation = args.topic ?? args.operation;
    const { platform = 'generic', urgency = 'routine' } = args;

    if (!operation) {
      return {
        content: [{
          type: 'text',
          text: 'Error: missing required parameter — pass `topic` (preferred) or `operation`.'
        }],
        isError: true
      };
    }

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
      // Phase 51 fix: multiSourceSearch returns a FLAT array of vector results
      // (each may carry .graphContext from enrichment), not { vector, graph }.
      // We also explicitly query the graph for J-job / script / file nodes when
      // the component name looks operational (e.g., JGLOBAL_FORECAST).
      const vectorResults = await this.dataAccess.multiSourceSearch(component, {
        nResults: 5,
        enrichWithGraph: true
      });

      // Graph arm: match :JJob / :Script / :File nodes by name (and J-pattern
      // names without extensions). Fail soft if graph is unavailable.
      const isJJobLike = /^J(GFS|GDAS|GLOBAL|ENKF|[A-Z]+)/i.test(component);
      let graphResults = [];
      try {
        const graphDB = this.dataAccess.graphDb || this.dataAccess.graphDB;
        if (graphDB && typeof graphDB.query === 'function') {
          const labelClause = isJJobLike
            ? '(n:JJob OR n:Script OR n:File OR n:Function OR n:Class)'
            : '(n:File OR n:Function OR n:Class OR n:Module)';
          const cypher = `
            MATCH (n)
            WHERE ${labelClause}
              AND (n.name = $name OR n.name CONTAINS $name OR n.path CONTAINS $name)
            RETURN n.name AS name, labels(n)[0] AS type,
                   coalesce(n.path, n.absolutePath, '') AS path,
                   coalesce(n.language, '') AS language
            LIMIT 10
          `;
          graphResults = await graphDB.query(cypher, { name: component }) || [];
        }
      } catch {
        graphResults = [];
      }

      let output = `# Workflow Component: ${component}\n\n`;
      output += `**Detail Level:** ${detail_level}\n\n`;

      // Phase 53 D8: when the graph arm directly hit a J-Job, render the
      // job's structured details (sourced scripts, inputs, outputs) instead
      // of falling through to the generic semantic documentation arm.
      const jjobHit = graphResults.find(r => r && r.type === 'JJob');
      if (jjobHit) {
        try {
          const jobDetails = await this.getJobDetails({
            job_name: jjobHit.name || component,
            include_chromadb: false,
            include_config: false,
            include_content: false
          });
          const jobBody = jobDetails?.content?.[0]?.text;
          if (jobBody && typeof jobBody === 'string') {
            output += `## Job Definition\n\n${jobBody}\n\n`;
          } else {
            output += `## Job Definition\n\n- **Name:** ${jjobHit.name}\n- **Type:** ${jjobHit.type}\n`;
            if (jjobHit.path) output += `- **Path:** ${jjobHit.path}\n`;
            output += `\n`;
          }
        } catch (err) {
          // Graceful degradation — emit a minimal block so the body is
          // never empty when we know we matched a J-Job.
          output += `## Job Definition\n\n- **Name:** ${jjobHit.name}\n- **Type:** ${jjobHit.type}\n`;
          if (jjobHit.path) output += `- **Path:** ${jjobHit.path}\n`;
          output += `_(Detailed job extraction unavailable: ${err.message})_\n\n`;
        }
      }

      // Documentation (vector arm)
      if (vectorResults && vectorResults.length > 0) {
        output += `## Documentation\n\n`;
        for (const result of vectorResults.slice(0, 2)) {
          const text = result.document || result.text || '';
          if (text) output += `${text}\n\n`;
        }
      }

      // Code Structure (graph arm)
      if (graphResults.length > 0) {
        output += `## Code Structure\n\n`;
        for (const item of graphResults) {
          output += `### ${item.name}\n`;
          output += `- **Type:** ${item.type || 'Component'}\n`;
          if (item.path) output += `- **Path:** ${item.path}\n`;
          if (item.language) output += `- **Language:** ${item.language}\n`;
          output += `\n`;
        }
      }

      // Dependencies (from first graph hit with a path)
      const firstWithPath = graphResults.find(g => g.path);
      if (firstWithPath) {
        try {
          const graphDB = this.dataAccess.graphDb || this.dataAccess.graphDB;
          if (graphDB && typeof graphDB.findFileImports === 'function') {
            const imports = await graphDB.findFileImports(firstWithPath.path);
            if (imports && imports.length > 0) {
              output += `## Dependencies\n\n`;
              for (const imp of imports.slice(0, 5)) {
                output += `- ${imp.importedFile || imp.path || imp.name}\n`;
              }
              output += `\n`;
            }
          }
        } catch {
          // Silent — dependencies are best-effort
        }
      }

      // No-results guard so callers never get just the heading.
      if ((!vectorResults || vectorResults.length === 0) && graphResults.length === 0) {
        output += `_No documentation or graph nodes matched **${component}**._\n\n`;
        output += `Hints:\n`;
        output += `- For J-jobs, try the exact filename (e.g., \`JGLOBAL_FORECAST\`).\n`;
        output += `- For source files, include the path fragment (e.g., \`ush/forecast_postdet.sh\`).\n`;
        output += `- Run \`get_knowledge_base_status\` to confirm collections are populated.\n\n`;
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
    const { category, search, format = 'summary', job_list, files: providedFiles } = args || {};

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

      // Phase 27D: Apply search filter if provided
      if (search && search.trim()) {
        const searchLower = search.toLowerCase();
        jobFiles = jobFiles.filter(f => f.toLowerCase().includes(searchLower));
      }

      // Categorize jobs (expanded categories per Phase 27)
      const categories = {
        analysis: jobFiles.filter(f => /atm|anl|anal|enkf|letkf/i.test(f)),
        forecast: jobFiles.filter(f => /fcst|forecast/i.test(f)),
        post: jobFiles.filter(f => /post|upp|awips|gempak|prod/i.test(f)),
        archive: jobFiles.filter(f => /arch|clean|globus/i.test(f)),
        verification: jobFiles.filter(f => /verf|fit2obs|cyclone|stat/i.test(f)),
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
        output += `- **Archive:** ${categories.archive.length} jobs\n`;
        output += `- **Verification:** ${categories.verification.length} jobs\n\n`;

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

  /**
   * Phase 27E: Get comprehensive J-Job details with structured metadata
   */
  async getJobDetails(args) {
    const { job_name, include_content = false, include_config = true, include_chromadb = true } = args || {};

    if (!job_name) {
      return {
        content: [{ type: 'text', text: 'Error: job_name parameter is required' }],
        isError: true
      };
    }

    try {
      // 1. Find the J-Job file
      const jobPath = await this.findJobScript(job_name);
      if (!jobPath) {
        return {
          content: [{ type: 'text', text: `J-Job '${job_name}' not found in ${this.workflowRoot}/dev/jobs/` }],
          isError: true
        };
      }

      // 2. Read and parse the script
      const content = await fs.readFile(jobPath, 'utf8');
      const parsed = this.parseJJob(content);

      // 3. Build structured response
      const details = {
        name: job_name,
        path: jobPath,
        line_count: content.split('\n').length,
        category: this.categorizeJob(job_name),
        system: this.extractSystem(job_name),
        
        // Extracted from script
        job_task: parsed.jobTask,
        config_files: parsed.configFiles,
        sources: parsed.sources,
        calls: parsed.calls,
        inputs: parsed.inputs,
        outputs: parsed.outputs,
        environment_variables: parsed.envVars,
        com_templates: parsed.comTemplates,
      };

      // 4. Include config file content if requested
      if (include_config && parsed.configFiles.length > 0) {
        details.config_contents = await this.readConfigFiles(parsed.configFiles);
      }

      // 5. Query ChromaDB for related documentation
      if (include_chromadb) {
        details.chromadb_context = await this.queryJJobChromaDB(job_name);
      }

      // 6. Include full content if requested
      if (include_content) {
        details.content = content;
      }

      // Format output
      let output = `# J-Job Details: ${job_name}\n\n`;
      output += `**Path:** ${jobPath}\n`;
      output += `**Lines:** ${details.line_count}\n`;
      output += `**Category:** ${details.category}\n`;
      output += `**System:** ${details.system}\n`;
      output += `**Task:** ${details.job_task || 'unknown'}\n\n`;

      if (details.config_files.length > 0) {
        output += `## Configuration Files\n\n`;
        for (const cfg of details.config_files) {
          output += `- \`${cfg}\`\n`;
        }
        output += '\n';
      }

      if (details.sources.length > 0) {
        output += `## Sourced Scripts\n\n`;
        for (const src of details.sources) {
          output += `- ${src.script} (line ${src.line})\n`;
        }
        output += '\n';
      }

      if (details.calls.length > 0) {
        output += `## External Script Calls\n\n`;
        for (const call of details.calls) {
          output += `- \`${call.script}\` via \`${call.variable}\` (line ${call.line})\n`;
        }
        output += '\n';
      }

      if (details.inputs.length > 0) {
        output += `## Inputs\n\n`;
        for (const input of details.inputs) {
          output += `- **${input.variable}**: \`${input.pattern}\`\n`;
        }
        output += '\n';
      }

      if (details.outputs.length > 0) {
        output += `## Outputs\n\n`;
        for (const output_item of details.outputs) {
          output += `- **${output_item.variable}**: \`${output_item.path}\`\n`;
        }
        output += '\n';
      }

      if (details.environment_variables.length > 0) {
        output += `## Environment Variables\n\n`;
        output += `| Variable | Value Pattern |\n`;
        output += `|----------|---------------|\n`;
        for (const env of details.environment_variables.slice(0, 15)) {
          const safeValue = env.value.replace(/\|/g, '\\|').substring(0, 50);
          output += `| ${env.name} | \`${safeValue}\` |\n`;
        }
        if (details.environment_variables.length > 15) {
          output += `\n*...and ${details.environment_variables.length - 15} more*\n`;
        }
        output += '\n';
      }

      if (details.config_contents && Object.keys(details.config_contents).length > 0) {
        output += `## Config File Contents\n\n`;
        for (const [name, cfg] of Object.entries(details.config_contents)) {
          if (cfg.content) {
            output += `### ${name}\n\n\`\`\`bash\n${cfg.content.substring(0, 500)}\n`;
            if (cfg.content.length > 500) output += `\n# ... truncated (${cfg.content.length} bytes total)\n`;
            output += `\`\`\`\n\n`;
          } else if (cfg.error) {
            output += `### ${name}\n\n*${cfg.error}*\n\n`;
          }
        }
      }

      if (details.chromadb_context && details.chromadb_context.length > 0) {
        output += `## Related Documentation (ChromaDB)\n\n`;
        for (const doc of details.chromadb_context) {
          output += `- **${doc.source}**: ${doc.summary} (relevance: ${doc.relevance})\n`;
        }
        output += '\n';
      }

      if (include_content) {
        output += `## Full Script Content\n\n\`\`\`bash\n${content}\n\`\`\`\n`;
      }

      return {
        content: [{ type: 'text', text: output }],
        metadata: details
      };

    } catch (error) {
      return {
        content: [{ type: 'text', text: `Error getting job details: ${error.message}` }],
        isError: true
      };
    }
  }

  /**
   * Find a J-Job script by name
   */
  async findJobScript(jobName) {
    const possiblePaths = [
      path.join(this.workflowRoot, 'dev', 'jobs', jobName),
      path.join(this.workflowRoot, 'jobs', jobName),
    ];

    for (const p of possiblePaths) {
      try {
        await fs.access(p);
        return p;
      } catch {
        continue;
      }
    }
    return null;
  }

  /**
   * Parse J-Job script content to extract structured metadata
   */
  parseJJob(content) {
    const lines = content.split('\n');
    const result = {
      jobTask: null,
      configFiles: [],
      sources: [],
      calls: [],
      inputs: [],
      outputs: [],
      envVars: [],
      comTemplates: [],
    };

    // Pattern: source "${HOMEgfs}/ush/jjob_header.sh" -e "task" -c "config1 config2"
    const headerPattern = /source\s+["\']?\$\{?HOMEgfs\}?\/ush\/jjob_header\.sh["\']?\s+-e\s+["']([^"']+)["']\s+-c\s+["']([^"']+)["']/;
    
    // Pattern: source "${path}"
    const sourcePattern = /^\s*(?:source|\.)\s+["']?([^"'\s#]+)["']?/;
    
    // Pattern: "${VARIABLE}/script.sh"
    const scriptCallPattern = /["\']?\$\{?([A-Z_]+)\}?\/([^"'\s]+\.sh)["\']?/g;
    
    // Pattern: export VAR=value
    const exportPattern = /^export\s+([A-Z_][A-Z0-9_]*)=(.+?)$/;
    
    // Pattern: declare_from_tmpl ... VAR:TEMPLATE
    const tmplPattern = /declare_from_tmpl\s+.*?([A-Z_]+):([A-Z_]+_TMPL)/g;
    
    // Pattern: mkdir ... ${VAR}
    const mkdirPattern = /mkdir\s+.*?\$\{?([A-Z_]+)\}?/;
    
    // Pattern: ${COMIN...}/${pattern}
    const inputPattern = /\$\{?(COMIN[A-Z_]*)\}?\/([^\s\}]+)/;

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const lineNum = i + 1;

      // Check for jjob_header source
      const headerMatch = line.match(headerPattern);
      if (headerMatch) {
        result.jobTask = headerMatch[1];
        result.configFiles = headerMatch[2].split(/\s+/);
        result.sources.push({
          script: 'jjob_header.sh',
          path: '${HOMEgfs}/ush/jjob_header.sh',
          line: lineNum
        });
        continue;
      }

      // Check for other source statements
      const sourceMatch = line.match(sourcePattern);
      if (sourceMatch && !line.includes('jjob_header')) {
        result.sources.push({
          script: path.basename(sourceMatch[1]),
          path: sourceMatch[1],
          line: lineNum
        });
      }

      // Check for script calls
      let callMatch;
      while ((callMatch = scriptCallPattern.exec(line)) !== null) {
        if (callMatch[1] !== 'HOMEgfs' && !result.calls.find(c => c.script === callMatch[2])) {
          result.calls.push({
            script: callMatch[2],
            variable: callMatch[1],
            line: lineNum
          });
        }
      }

      // Check for exports
      const exportMatch = line.match(exportPattern);
      if (exportMatch) {
        result.envVars.push({
          name: exportMatch[1],
          value: exportMatch[2].trim()
        });
      }

      // Check for COM templates
      let tmplMatch;
      while ((tmplMatch = tmplPattern.exec(line)) !== null) {
        result.comTemplates.push({
          variable: tmplMatch[1],
          template: tmplMatch[2]
        });
      }

      // Check for mkdir (outputs)
      const mkdirMatch = line.match(mkdirPattern);
      if (mkdirMatch && !mkdirMatch[1].startsWith('COMIN')) {
        if (!result.outputs.find(o => o.variable === mkdirMatch[1])) {
          result.outputs.push({
            variable: mkdirMatch[1],
            path: `\${${mkdirMatch[1]}}`
          });
        }
      }

      // Check for input file patterns
      const inputMatch = line.match(inputPattern);
      if (inputMatch) {
        if (!result.inputs.find(inp => inp.variable === inputMatch[1] && inp.pattern === inputMatch[2])) {
          result.inputs.push({
            variable: inputMatch[1],
            pattern: inputMatch[2]
          });
        }
      }
    }

    return result;
  }

  /**
   * Categorize job by name pattern
   */
  categorizeJob(jobName) {
    const name = jobName.toLowerCase();
    if (/anl|anal|enkf|letkf|chgres/.test(name)) return 'analysis';
    if (/fcst|forecast/.test(name)) return 'forecast';
    if (/post|upp|awips|gempak|prod/.test(name)) return 'post-processing';
    if (/arch|clean|globus/.test(name)) return 'archive';
    if (/verf|fit2obs|cyclone|stat|tracker/.test(name)) return 'verification';
    if (/wave/.test(name)) return 'wave';
    if (/ocean|ice|marine/.test(name)) return 'ocean';
    if (/aero/.test(name)) return 'aerosol';
    return 'general';
  }

  /**
   * Extract system from job name (JGDAS, JGFS, JGLOBAL, JGEFS)
   */
  extractSystem(jobName) {
    if (jobName.startsWith('JGDAS')) return 'gdas';
    if (jobName.startsWith('JGFS')) return 'gfs';
    if (jobName.startsWith('JGLOBAL')) return 'global';
    if (jobName.startsWith('JGEFS')) return 'gefs';
    return 'unknown';
  }

  /**
   * Read config files from parm/config directory
   */
  async readConfigFiles(configNames) {
    const results = {};
    const configDirs = [
      path.join(this.workflowRoot, 'dev', 'parm', 'config', 'gfs'),
      path.join(this.workflowRoot, 'dev', 'parm', 'config'),
      path.join(this.workflowRoot, 'parm', 'config', 'gfs'),
      path.join(this.workflowRoot, 'parm', 'config'),
    ];

    for (const configName of configNames) {
      const fileName = configName.startsWith('config.') ? configName : `config.${configName}`;
      
      let found = false;
      for (const dir of configDirs) {
        const configPath = path.join(dir, fileName);
        try {
          const content = await fs.readFile(configPath, 'utf8');
          results[configName] = { path: configPath, content };
          found = true;
          break;
        } catch {
          continue;
        }
      }

      if (!found) {
        results[configName] = { error: `Config file '${fileName}' not found` };
      }
    }

    return results;
  }

  /**
   * Query ChromaDB jjobs collection for related context
   * Uses MPNet embeddings (768-dim) for semantic search
   */
  async queryJJobChromaDB(jobName) {
    try {
      // Use dataAccess if available (has embedding support)
      if (this.dataAccess && this.dataAccess.vectorSearch) {
        const results = await this.dataAccess.vectorSearch(jobName, {
          collection: 'jjobs-v8-0-0',
          maxResults: 3
        });
        
        return results.map(r => ({
          source: r.metadata?.source_file || 'jjobs-v8-0-0',
          summary: r.content?.substring(0, 100) + '...',
          relevance: (r.score || 0.5).toFixed(2)
        }));
      }

      // Fallback: Use ChromaDB with MPNet embeddings
      try {
        const chromadb = await import('chromadb');
        const client = new chromadb.ChromaClient({ 
          host: process.env.CHROMADB_HOST || 'localhost',
          port: parseInt(process.env.CHROMADB_PORT || '8080')
        });
        const collection = await client.getCollection({ name: 'jjobs-v8-0-0' });
        
        // First try exact match by metadata
        const exactResults = await collection.get({
          where: { name: jobName },
          limit: 3
        });

        if (exactResults.documents && exactResults.documents.length > 0) {
          return exactResults.documents.map((doc, i) => ({
            source: exactResults.metadatas?.[i]?.source_file || 'jjobs-v8-0-0',
            summary: doc.substring(0, 150) + '...',
            relevance: '1.00',  // Exact match
            category: exactResults.metadatas?.[i]?.category || 'unknown',
            system: exactResults.metadatas?.[i]?.system || 'unknown'
          }));
        }
        
        // No exact match - try semantic search with MPNet embeddings
        const semanticResults = await embeddings.queryWithEmbeddings(collection, jobName, 5);

        if (semanticResults.documents?.[0]?.length > 0) {
          return semanticResults.documents[0].map((doc, i) => ({
            source: semanticResults.metadatas?.[0]?.[i]?.source_file || 'jjobs-v8-0-0',
            summary: doc.substring(0, 150) + '...',
            relevance: semanticResults.distances?.[0]?.[i] 
              ? (1 - semanticResults.distances[0][i]).toFixed(2)  // Convert distance to similarity
              : '0.50',
            category: semanticResults.metadatas?.[0]?.[i]?.category || 'unknown',
            system: semanticResults.metadatas?.[0]?.[i]?.system || 'unknown'
          }));
        }
        
        return [{ 
          source: 'jjobs-v8-0-0', 
          summary: `No matches found for '${jobName}' in jjobs-v8-0-0 collection (700 documents).`,
          relevance: '0.00'
        }];
        
      } catch (e) {
        // ChromaDB not available or error
        return [{ source: 'chromadb', summary: `ChromaDB: ${e.message}`, relevance: '0.00' }];
      }

      return [];
    } catch (error) {
      return [{ source: 'error', summary: error.message, relevance: '0.00' }];
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
