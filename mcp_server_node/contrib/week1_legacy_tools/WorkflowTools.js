#!/usr/bin/env node

/**
 * Core Workflow Tools Module
 * 
 * Contains basic workflow structure and documentation tools.
 * These tools provide foundational workflow information without RAG dependencies.
 * 
 * @version 2.0.0
 * @author NOAA EMC Global Workflow Team
 */

import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export class WorkflowTools {
  constructor(workflowRoot) {
    this.workflowRoot = workflowRoot || this.findWorkflowRoot();
  }

  /**
   * Find the workflow root directory
   */
  findWorkflowRoot() {
    let currentDir = __dirname;
    while (currentDir !== '/') {
      const parentDir = path.dirname(currentDir);
      if (path.basename(parentDir).includes('global-workflow')) {
        return parentDir;
      }
      currentDir = parentDir;
    }
    return path.resolve(__dirname, '../../../../../../../../../../..');
  }

  /**
   * Register all workflow tools with a server
   */
  registerWith(server) {
    server.registerTool(
      'get_workflow_structure',
      'Get the structure and overview of the global workflow system',
      {
        type: 'object',
        properties: {
          component: {
            type: 'string',
            description: 'Optional specific component to focus on',
            enum: ['jobs', 'scripts', 'parm', 'ush', 'sorc', 'docs', 'env']
          }
        }
      },
      this.getWorkflowStructure.bind(this)
    );

    server.registerTool(
      'list_job_scripts',
      'List and categorize job scripts in the workflow',
      {
        type: 'object',
        properties: {
          category: {
            type: 'string',
            description: 'Filter by job category',
            enum: ['analysis', 'forecast', 'post', 'archive', 'all']
          },
          format: {
            type: 'string',
            description: 'Output format',
            enum: ['summary', 'detailed', 'json'],
            default: 'summary'
          }
        }
      },
      this.listJobScripts.bind(this)
    );

    server.registerTool(
      'get_system_configs',
      'Get system configuration information for different HPC platforms',
      {
        type: 'object',
        properties: {
          platform: {
            type: 'string',
            description: 'HPC platform name',
            enum: ['hera', 'hercules', 'orion', 'wcoss2', 'gaea', 'all']
          },
          config_type: {
            type: 'string',
            description: 'Type of configuration',
            enum: ['modules', 'resources', 'paths', 'all']
          }
        }
      },
      this.getSystemConfigs.bind(this)
    );

    server.registerTool(
      'explain_workflow_component',
      'Get detailed explanation of a workflow component',
      {
        type: 'object',
        properties: {
          component: {
            type: 'string',
            description: 'Component name (job script, config file, or directory)',
          },
          detail_level: {
            type: 'string',
            description: 'Level of detail in explanation',
            enum: ['basic', 'detailed', 'expert'],
            default: 'detailed'
          }
        },
        required: ['component']
      },
      this.explainWorkflowComponent.bind(this)
    );
  }

  /**
   * Get workflow structure overview
   */
  async getWorkflowStructure(args = {}) {
    const { component } = args;
    
    try {
      const structure = {
        root: this.workflowRoot,
        overview: 'NOAA Global Workflow - Unified weather prediction system',
        components: {}
      };

      const mainDirs = ['jobs', 'scripts', 'parm', 'ush', 'sorc', 'docs', 'env'];
      
      for (const dir of mainDirs) {
        if (component && component !== dir) continue;
        
        const dirPath = path.join(this.workflowRoot, dir);
        try {
          const stats = await fs.stat(dirPath);
          if (stats.isDirectory()) {
            const files = await fs.readdir(dirPath);
            structure.components[dir] = {
              path: dirPath,
              fileCount: files.length,
              description: this.getComponentDescription(dir)
            };
          }
        } catch (err) {
          structure.components[dir] = {
            path: dirPath,
            status: 'not_found',
            description: this.getComponentDescription(dir)
          };
        }
      }

      return JSON.stringify(structure, null, 2);
    } catch (error) {
      return `Error getting workflow structure: ${error.message}`;
    }
  }

  /**
   * List job scripts with categorization
   */
  async listJobScripts(args = {}) {
    const { category = 'all', format = 'summary' } = args;
    
    try {
      const jobsDir = path.join(this.workflowRoot, 'jobs');
      const devJobsDir = path.join(this.workflowRoot, 'dev/jobs');
      
      const jobs = {
        production: [],
        development: []
      };

      // Read production jobs
      try {
        const prodFiles = await fs.readdir(jobsDir);
        jobs.production = prodFiles.filter(file => file.startsWith('J'));
      } catch (err) {
        jobs.production = [];
      }

      // Read development jobs
      try {
        const devFiles = await fs.readdir(devJobsDir);
        jobs.development = devFiles.filter(file => file.endsWith('.sh'));
      } catch (err) {
        jobs.development = [];
      }

      const categorized = this.categorizeJobs(jobs, category);
      
      if (format === 'json') {
        return JSON.stringify(categorized, null, 2);
      } else if (format === 'detailed') {
        return this.formatJobsDetailed(categorized);
      } else {
        return this.formatJobsSummary(categorized);
      }
    } catch (error) {
      return `Error listing job scripts: ${error.message}`;
    }
  }

  /**
   * Get system configuration information
   */
  async getSystemConfigs(args = {}) {
    const { platform = 'all', config_type = 'all' } = args;
    
    try {
      const configs = {};
      const configDirs = [
        'dev/workflow/hosts',
        'modulefiles', 
        'versions'
      ];

      for (const configDir of configDirs) {
        const fullPath = path.join(this.workflowRoot, configDir);
        try {
          const files = await fs.readdir(fullPath);
          configs[configDir] = files.filter(file => {
            if (platform === 'all') return true;
            return file.toLowerCase().includes(platform.toLowerCase());
          });
        } catch (err) {
          configs[configDir] = [];
        }
      }

      return JSON.stringify(configs, null, 2);
    } catch (error) {
      return `Error getting system configs: ${error.message}`;
    }
  }

  /**
   * Explain a workflow component in detail
   */
  async explainWorkflowComponent(args) {
    const { component, detail_level = 'detailed' } = args;
    
    try {
      // Search for the component in various locations
      const searchPaths = [
        'jobs',
        'dev/jobs', 
        'scripts',
        'parm',
        'ush'
      ];

      let componentPath = null;
      let componentType = null;

      for (const searchPath of searchPaths) {
        const fullPath = path.join(this.workflowRoot, searchPath);
        try {
          const files = await fs.readdir(fullPath);
          const found = files.find(file => 
            file === component || 
            file.includes(component) ||
            file.replace(/\.[^/.]+$/, '') === component
          );
          
          if (found) {
            componentPath = path.join(fullPath, found);
            componentType = searchPath;
            break;
          }
        } catch (err) {
          continue;
        }
      }

      if (!componentPath) {
        return `Component '${component}' not found in standard workflow locations.`;
      }

      const explanation = await this.generateComponentExplanation(
        componentPath, 
        componentType, 
        detail_level
      );
      
      return explanation;
    } catch (error) {
      return `Error explaining component: ${error.message}`;
    }
  }

  /**
   * Helper methods
   */
  getComponentDescription(component) {
    const descriptions = {
      'jobs': 'Production job scripts for workflow execution',
      'scripts': 'Execution scripts called by jobs',
      'parm': 'Parameter files and configuration templates',
      'ush': 'Utility shell scripts and functions',
      'sorc': 'Source code and build scripts',
      'docs': 'Documentation and user guides',
      'env': 'Environment setup scripts'
    };
    return descriptions[component] || 'Workflow component';
  }

  categorizeJobs(jobs, category) {
    const categories = {
      analysis: /anal|gdas|gsi/i,
      forecast: /fcst|gfs|forecast/i,
      post: /post|upp|products/i,
      archive: /arch|cleanup|globus/i
    };

    const result = {
      production: {},
      development: {}
    };

    for (const [jobType, jobList] of Object.entries(jobs)) {
      for (const [cat, pattern] of Object.entries(categories)) {
        if (category === 'all' || category === cat) {
          result[jobType][cat] = jobList.filter(job => pattern.test(job));
        }
      }
      if (category === 'all') {
        result[jobType].other = jobList.filter(job => 
          !Object.values(categories).some(pattern => pattern.test(job))
        );
      }
    }

    return result;
  }

  formatJobsSummary(categorized) {
    let output = '# Global Workflow Job Scripts Summary\n\n';
    
    for (const [jobType, categories] of Object.entries(categorized)) {
      output += `## ${jobType.charAt(0).toUpperCase() + jobType.slice(1)} Jobs\n`;
      for (const [category, jobs] of Object.entries(categories)) {
        if (jobs.length > 0) {
          output += `- **${category}**: ${jobs.length} scripts\n`;
        }
      }
      output += '\n';
    }
    
    return output;
  }

  formatJobsDetailed(categorized) {
    let output = '# Global Workflow Job Scripts Detailed\n\n';
    
    for (const [jobType, categories] of Object.entries(categorized)) {
      output += `## ${jobType.charAt(0).toUpperCase() + jobType.slice(1)} Jobs\n\n`;
      for (const [category, jobs] of Object.entries(categories)) {
        if (jobs.length > 0) {
          output += `### ${category.charAt(0).toUpperCase() + category.slice(1)} (${jobs.length})\n`;
          jobs.forEach(job => output += `- ${job}\n`);
          output += '\n';
        }
      }
    }
    
    return output;
  }

  async generateComponentExplanation(componentPath, componentType, detailLevel) {
    let explanation = `# Component: ${path.basename(componentPath)}\n\n`;
    explanation += `**Type**: ${componentType}\n`;
    explanation += `**Path**: ${componentPath}\n\n`;

    try {
      const stats = await fs.stat(componentPath);
      explanation += `**Size**: ${stats.size} bytes\n`;
      explanation += `**Modified**: ${stats.mtime.toISOString()}\n\n`;

      if (detailLevel === 'detailed' || detailLevel === 'expert') {
        // Read first few lines for context
        try {
          const content = await fs.readFile(componentPath, 'utf-8');
          const lines = content.split('\n').slice(0, 20);
          explanation += `## Content Preview\n\`\`\`\n${lines.join('\n')}\n\`\`\`\n\n`;
        } catch (err) {
          explanation += `## Content\nBinary file or read error: ${err.message}\n\n`;
        }
      }

      explanation += this.getComponentTypeExplanation(componentType, detailLevel);
      
    } catch (err) {
      explanation += `**Error reading file**: ${err.message}\n`;
    }

    return explanation;
  }

  getComponentTypeExplanation(componentType, detailLevel) {
    const explanations = {
      'jobs': 'Job scripts define workflow tasks and their dependencies. They set up environment and execute scripts.',
      'dev/jobs': 'Development job scripts contain the core logic executed by production jobs.',
      'scripts': 'Execution scripts contain the actual implementation of workflow tasks.',
      'parm': 'Parameter files contain configuration settings and templates for workflow execution.',
      'ush': 'Utility scripts provide common functions used across the workflow system.'
    };
    
    return `## Purpose\n${explanations[componentType] || 'Workflow component file.'}\n`;
  }
}