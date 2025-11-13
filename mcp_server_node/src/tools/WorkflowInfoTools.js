#!/usr/bin/env node

/**
 * Workflow Information Tools Module
 * 
 * Static workflow information tools - NO database dependencies.
 * Provides file system-based access to workflow structure, configurations,
 * and component descriptions.
 * 
 * Features:
 * - Workflow structure overview
 * - System configuration retrieval
 * - Component descriptions (static analysis)
 * 
 * Note: This module is intentionally lightweight and does NOT use UnifiedDataAccess.
 * For graph-enriched component explanations, use OperationalTools.explain_workflow_component.
 * 
 * @version 2.0.0
 * @author Claude Sonnet 4.5
 * @supervisor Terry McGuinness
 * @date 2025-10-16
 */

import fs from 'fs/promises';
import path from 'path';

export class WorkflowInfoTools {
  constructor() {
    this.workflowRoot = process.env.HOMEgfs || '/mcp_rag_eib/global-workflow_MCP_node.js-RAG';
  }

  registerWith(server) {
    // Tool 1: Get Workflow Structure
    server.registerTool(
      'get_workflow_structure',
      'Get the structure and overview of the global workflow system',
      {
        type: 'object',
        properties: {
          component: {
            type: 'string',
            enum: ['jobs', 'scripts', 'parm', 'ush', 'sorc', 'docs', 'env'],
            description: 'Optional specific component to focus on'
          }
        }
      },
      this.getWorkflowStructure.bind(this)
    );

    // Tool 2: Get System Configs
    server.registerTool(
      'get_system_configs',
      'Get system configuration information for different HPC platforms',
      {
        type: 'object',
        properties: {
          platform: {
            type: 'string',
            enum: ['hera', 'hercules', 'orion', 'wcoss2', 'gaea', 'all'],
            description: 'HPC platform name'
          },
          config_type: {
            type: 'string',
            enum: ['modules', 'resources', 'paths', 'all'],
            description: 'Type of configuration'
          }
        }
      },
      this.getSystemConfigs.bind(this)
    );

    // Tool 3: Describe Component (static file-based analysis)
    server.registerTool(
      'describe_component',
      'Get basic description of a workflow component (file system only)',
      {
        type: 'object',
        properties: {
          component: { type: 'string', description: 'Component name or path' },
          show_content: { type: 'boolean', default: false, description: 'Include file content preview' }
        },
        required: ['component']
      },
      this.describeComponent.bind(this)
    );

    console.error('[OK] Registered 3 Workflow Info tools');
  }

  async getWorkflowStructure(args) {
    const { component } = args || {};

    try {
      let output = `# Global Workflow Structure\n\n`;
      output += `**Root:** ${this.workflowRoot}\n\n`;

      const structure = {
        jobs: {
          desc: 'Production Job Control Language (JCL) scripts',
          pattern: 'J*',
          note: 'Entry points for operational jobs'
        },
        scripts: {
          desc: 'Execution scripts called by jobs',
          pattern: 'ex*.{sh,py}',
          note: 'Implementation logic for each component'
        },
        parm: {
          desc: 'Parameter files and configuration templates',
          subdirs: ['archive', 'gdas', 'post', 'ufs', 'wave', 'product'],
          note: 'System configuration templates'
        },
        ush: {
          desc: 'Utility shell scripts and functions',
          key_files: ['detect_machine.sh', 'jjob_header.sh', 'bash_utils.sh'],
          note: 'Shared utilities and platform detection'
        },
        sorc: {
          desc: 'Source code and build infrastructure',
          key_files: ['build_all.sh', 'CMakeLists.txt'],
          subdirs: ['ufs_model.fd', 'gfs_utils.fd', 'gsi_*.fd', 'wxflow'],
          note: 'Source compilation and dependencies'
        },
        env: {
          desc: 'HPC platform environment configurations',
          platforms: ['WCOSS2', 'HERA', 'HERCULES', 'ORION', 'GAEA'],
          note: 'Platform-specific settings'
        },
        docs: {
          desc: 'Documentation and user guides',
          note: 'System documentation'
        }
      };

      if (component && structure[component]) {
        output += `## Component: ${component}\n\n`;
        const info = structure[component];
        output += `**Description:** ${info.desc}\n\n`;
        if (info.pattern) output += `**Pattern:** ${info.pattern}\n`;
        if (info.subdirs) output += `**Subdirectories:** ${info.subdirs.join(', ')}\n`;
        if (info.key_files) output += `**Key Files:** ${info.key_files.join(', ')}\n`;
        if (info.platforms) output += `**Platforms:** ${info.platforms.join(', ')}\n`;
        output += `\n**Note:** ${info.note}\n`;
      } else {
        output += `## System Components\n\n`;
        for (const [key, info] of Object.entries(structure)) {
          output += `### ${key}/\n`;
          output += `${info.desc}\n`;
          output += `*${info.note}*\n\n`;
        }

        output += `## Execution Flow\n\n`;
        output += `1. **Jobs (jobs/J*)** - Entry points defining environment\n`;
        output += `2. **Scripts (scripts/ex*)** - Implementation logic\n`;
        output += `3. **Utilities (ush/)** - Shared functions\n`;
        output += `4. **Parameters (parm/)** - Configuration templates\n`;
        output += `5. **Build System (sorc/)** - Source compilation\n`;
      }

      return { content: [{ type: 'text', text: output }] };
    } catch (error) {
      return {
        content: [{ type: 'text', text: `Error getting workflow structure: ${error.message}` }],
        isError: true
      };
    }
  }

  async getSystemConfigs(args) {
    const { platform, config_type } = args || {};

    try {
      let output = `# System Configurations\n\n`;

      if (platform) {
        output += `**Platform:** ${platform.toUpperCase()}\n`;
      }
      if (config_type) {
        output += `**Config Type:** ${config_type}\n`;
      }
      output += `\n`;

      // Try to read env files
      const envDir = path.join(this.workflowRoot, 'env');
      
      if (platform && platform !== 'all') {
        const envFile = path.join(envDir, `${platform.toUpperCase()}.env`);
        try {
          const content = await fs.readFile(envFile, 'utf-8');
          output += `## ${platform.toUpperCase()} Environment\n\n`;
          output += `\`\`\`bash\n${content.slice(0, 2000)}\n\`\`\`\n\n`;
        } catch {
          output += `Environment file not found: ${envFile}\n\n`;
        }
      } else {
        // List all platforms
        try {
          const files = await fs.readdir(envDir);
          const envFiles = files.filter(f => f.endsWith('.env'));
          
          output += `## Available Platforms\n\n`;
          for (const file of envFiles) {
            const platformName = file.replace('.env', '');
            output += `### ${platformName}\n`;
            output += `**File:** env/${file}\n\n`;
          }
        } catch {
          output += `Could not read env directory\n`;
        }
      }

      // Add config type specific info
      if (config_type === 'modules' || config_type === 'all') {
        output += `## Module Configuration\n\n`;
        output += `Module files are located in: modulefiles/\n`;
        output += `Use: \`module use \${HOMEgfs}/modulefiles\`\n`;
        output += `Load: \`module load module_gwsetup.\${MACHINE_ID}\`\n\n`;
      }

      if (config_type === 'resources' || config_type === 'all') {
        output += `## Resource Configuration\n\n`;
        output += `Resource requirements defined in: parm/config/\n`;
        output += `Platform-specific resources in workflow XML\n\n`;
      }

      if (config_type === 'paths' || config_type === 'all') {
        output += `## Path Configuration\n\n`;
        output += `- **HOMEgfs:** ${this.workflowRoot}\n`;
        output += `- **Jobs:** \${HOMEgfs}/jobs\n`;
        output += `- **Scripts:** \${HOMEgfs}/scripts\n`;
        output += `- **Utilities:** \${HOMEgfs}/ush\n`;
        output += `- **Parameters:** \${HOMEgfs}/parm\n`;
        output += `- **Source:** \${HOMEgfs}/sorc\n\n`;
      }

      return { content: [{ type: 'text', text: output }] };
    } catch (error) {
      return {
        content: [{ type: 'text', text: `Error getting system configs: ${error.message}` }],
        isError: true
      };
    }
  }

  async describeComponent(args) {
    const { component, show_content = false } = args;

    try {
      let output = `# Component: ${component}\n\n`;

      // Try to find the file/directory
      const searchPaths = [
        path.join(this.workflowRoot, 'jobs', component),
        path.join(this.workflowRoot, 'scripts', component),
        path.join(this.workflowRoot, 'ush', component),
        path.join(this.workflowRoot, 'parm', component),
        path.join(this.workflowRoot, component)
      ];

      let found = false;
      for (const searchPath of searchPaths) {
        try {
          const stats = await fs.stat(searchPath);
          found = true;
          
          output += `**Path:** ${searchPath.replace(this.workflowRoot, '${HOMEgfs}')}\n`;
          output += `**Type:** ${stats.isDirectory() ? 'Directory' : 'File'}\n`;
          
          if (stats.isFile()) {
            output += `**Size:** ${stats.size} bytes\n`;
            
            if (show_content) {
              try {
                const content = await fs.readFile(searchPath, 'utf-8');
                const lines = content.split('\n');
                output += `\n## Content Preview\n\n`;
                output += `\`\`\`\n${lines.slice(0, 50).join('\n')}\n`;
                if (lines.length > 50) output += `\n... (${lines.length - 50} more lines)\n`;
                output += `\`\`\`\n`;
              } catch {
                output += `\nCould not read file content\n`;
              }
            }
          } else if (stats.isDirectory()) {
            try {
              const contents = await fs.readdir(searchPath);
              output += `**Contents:** ${contents.length} items\n\n`;
              output += `### Files/Directories\n\n`;
              for (const item of contents.slice(0, 20)) {
                output += `- ${item}\n`;
              }
              if (contents.length > 20) {
                output += `\n... (${contents.length - 20} more items)\n`;
              }
            } catch {
              output += `\nCould not list directory contents\n`;
            }
          }
          
          break;
        } catch {
          continue;
        }
      }

      if (!found) {
        output += `Component not found in standard locations.\n\n`;
        output += `Searched paths:\n`;
        for (const p of searchPaths) {
          output += `- ${p}\n`;
        }
      }

      return { content: [{ type: 'text', text: output }] };
    } catch (error) {
      return {
        content: [{ type: 'text', text: `Error describing component: ${error.message}` }],
        isError: true
      };
    }
  }
}

export default WorkflowInfoTools;
