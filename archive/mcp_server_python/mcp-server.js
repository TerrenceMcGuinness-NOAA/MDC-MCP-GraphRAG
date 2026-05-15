#!/usr/bin/env node

/**
 * Model Context Protocol (MCP) Server for Global Workflow
 * Provides context about the global-workflow repository structure and functionality
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
 * Create and configure the MCP server
 */
function createServer() {
  const server = new Server(
    {
      name: 'global-workflow-mcp',
      version: '1.0.0',
    },
    {
      capabilities: {
        tools: {},
      },
    }
  );

  /**
   * List available tools
   */
  server.setRequestHandler(ListToolsRequestSchema, async () => {
    return {
      tools: [
        {
          name: 'get_workflow_structure',
          description: 'Get the structure and overview of the global workflow system',
          inputSchema: {
            type: 'object',
            properties: {
              component: {
                type: 'string',
                description: 'Specific component to focus on (optional)',
                enum: ['jobs', 'scripts', 'configs', 'overview']
              }
            }
          }
        },
        {
          name: 'list_job_scripts',
          description: 'List all available job scripts in the workflow',
          inputSchema: {
            type: 'object',
            properties: {}
          }
        },
        {
          name: 'get_system_configs',
          description: 'Get configuration information for different HPC systems',
          inputSchema: {
            type: 'object',
            properties: {
              system: {
                type: 'string',
                description: 'HPC system name',
                enum: ['hera', 'orion', 'hercules', 'wcoss2', 'gaeac5', 'gaeac6']
              }
            }
          }
        },
        {
          name: 'explain_workflow_component',
          description: 'Explain a specific workflow component or directory',
          inputSchema: {
            type: 'object',
            properties: {
              component: {
                type: 'string',
                description: 'Component name (e.g., rocoto, gsi, ufs)',
                required: true
              }
            },
            required: ['component']
          }
        }
      ]
    };
  });

  /**
   * Handle tool calls
   */
  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params;

    try {
      switch (name) {
        case 'get_workflow_structure':
          return await getWorkflowStructure(args?.component);
        
        case 'list_job_scripts':
          return await listJobScripts();
        
        case 'get_system_configs':
          return await getSystemConfigs(args?.system);
        
        case 'explain_workflow_component':
          return await explainWorkflowComponent(args?.component);
        
        default:
          throw new Error(`Unknown tool: ${name}`);
      }
    } catch (error) {
      return {
        content: [
          {
            type: 'text',
            text: `Error: ${error.message}`
          }
        ]
      };
    }
  });

  return server;
}

/**
 * Get workflow structure information
 */
async function getWorkflowStructure(component) {
  const structure = {
    overview: `
Global Workflow - NOAA's Operational Weather Prediction System

Key Components:
- Jobs: Batch job scripts for various workflow tasks
- Scripts: Shell scripts that implement job functionality  
- USH: Utility shell scripts and common functions
- Parm: Parameter files and configuration templates
- Fix: Fixed input data files and tables
- Sorc: Source code for models and utilities
- Modulefiles: Environment modules for different systems

Workflow Management:
- Uses Rocoto XML workflow engine
- Supports multiple HPC systems (Hera, Orion, WCOSS2, etc.)
- Runs GFS, GDAS, and GEFS forecast systems
`,
    jobs: `
Job Scripts (jobs/ directory):
- JGDAS_* : GDAS (Global Data Assimilation System) jobs
- JGFS_* : GFS (Global Forecast System) jobs  
- JGEFS_* : GEFS (Global Ensemble Forecast System) jobs
- Each job sets up environment and calls corresponding script
`,
    scripts: `
Scripts (scripts/ directory):
- exgdas_* : GDAS execution scripts
- exgfs_* : GFS execution scripts
- Implement the actual workflow logic called by jobs
`,
    configs: `
Configuration Files (parm/ directory):
- config/ : System-specific configuration files
- globus/ : Globus data transfer configurations
- product/ : Product generation parameters
- wave/ : Wave model configurations
`
  };

  const content = component && structure[component] 
    ? structure[component] 
    : structure.overview;

  return {
    content: [
      {
        type: 'text',
        text: content.trim()
      }
    ]
  };
}

/**
 * List job scripts
 */
async function listJobScripts() {
  try {
    const jobsDir = path.join(__dirname, 'jobs');
    const files = await fs.readdir(jobsDir);
    const jobScripts = files
      .filter(file => file.startsWith('J') && !file.includes('.'))
      .sort();

    const jobList = jobScripts.map(job => `- ${job}`).join('\n');
    
    return {
      content: [
        {
          type: 'text',
          text: `Available Job Scripts:\n\n${jobList}`
        }
      ]
    };
  } catch (error) {
    return {
      content: [
        {
          type: 'text',
          text: `Error listing job scripts: ${error.message}`
        }
      ]
    };
  }
}

/**
 * Get system configuration information
 */
async function getSystemConfigs(system) {
  const systemInfo = {
    hera: 'NOAA RDHPCS Hera - Primary development and testing system',
    orion: 'NOAA RDHPCS Orion - Research and development system',
    hercules: 'NOAA RDHPCS Hercules - Newest HPC system',
    wcoss2: 'NOAA WCOSS2 - Operational production system (Dogwood/Cactus)',
    gaeac5: 'NOAA Cloud - AWS-based compute environment',
    gaeac6: 'NOAA Cloud - Azure-based compute environment'
  };

  const info = system && systemInfo[system] 
    ? systemInfo[system]
    : 'Available systems: ' + Object.keys(systemInfo).join(', ');

  const configPath = system ? `env/${system.toUpperCase()}.env` : 'env/';
  
  return {
    content: [
      {
        type: 'text',
        text: `System: ${system || 'All systems'}\n\n${info}\n\nConfiguration files: ${configPath}`
      }
    ]
  };
}

/**
 * Explain workflow components
 */
async function explainWorkflowComponent(component) {
  const explanations = {
    rocoto: 'Rocoto is the workflow engine that manages job dependencies and execution scheduling',
    gsi: 'Gridpoint Statistical Interpolation - the data assimilation system',
    ufs: 'Unified Forecast System - the atmospheric model component',
    mom6: 'Modular Ocean Model version 6 - ocean model component',
    cice: 'Community Ice CodE - sea ice model component',
    ww3: 'WaveWatch III - ocean wave model component',
    gefs: 'Global Ensemble Forecast System - ensemble prediction system',
    gdas: 'Global Data Assimilation System - analysis and reanalysis system',
    gfs: 'Global Forecast System - deterministic forecast system'
  };

  const explanation = explanations[component?.toLowerCase()] || 
    `Component "${component}" not found. Available components: ${Object.keys(explanations).join(', ')}`;

  return {
    content: [
      {
        type: 'text', 
        text: explanation
      }
    ]
  };
}

/**
 * Main function to start the server
 */
async function main() {
  const server = createServer();
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error('Global Workflow MCP Server running on stdio');
}

main().catch((error) => {
  console.error('Server error:', error);
  process.exit(1);
});
