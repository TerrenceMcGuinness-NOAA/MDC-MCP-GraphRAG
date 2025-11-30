/**
 * SDD Workflow Executor
 * Parses and executes workflows defined in sdd_framework/workflows/
 * 
 * Version: 4.0.0 - Phase 4: Bootstrap Capability
 * Date: December 21, 2024
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { execSync } from 'child_process';
import { SelfModificationEngine } from './SelfModificationEngine.js';
import { SpecificationParser } from './SpecificationParser.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export class WorkflowExecutor {
  constructor(dataAccess, healthMonitor = null) {
    this.dataAccess = dataAccess;
    this.healthMonitor = healthMonitor;
    this.workflowDir = path.join(__dirname, '../../../sdd_framework/workflows');
    this.executionHistory = [];
    
    // Phase 4: Bootstrap capability
    this.selfModEngine = new SelfModificationEngine(dataAccess);
    this.specParser = new SpecificationParser();
    this.repoRoot = path.resolve(__dirname, '../../..');
  }

  /**
   * List available SDD workflows
   */
  async listWorkflows() {
    try {
      const files = fs.readdirSync(this.workflowDir);
      const workflows = files
        .filter(f => f.endsWith('.md'))
        .map(f => ({
          name: f.replace('.md', ''),
          path: path.join(this.workflowDir, f),
          size: fs.statSync(path.join(this.workflowDir, f)).size
        }));
      
      return workflows;
    } catch (error) {
      console.error('[ERROR] Failed to list workflows:', error.message);
      return [];
    }
  }

  /**
   * Parse workflow markdown file into structured steps
   */
  async parseWorkflow(workflowName) {
    const workflowPath = path.join(this.workflowDir, `${workflowName}.md`);
    
    if (!fs.existsSync(workflowPath)) {
      throw new Error(`Workflow not found: ${workflowName}`);
    }

    const content = fs.readFileSync(workflowPath, 'utf-8');
    
    // Extract workflow structure
    const workflow = {
      name: workflowName,
      title: this.extractTitle(content),
      description: this.extractDescription(content),
      phases: this.extractPhases(content),
      steps: this.extractSteps(content),
      metadata: this.extractMetadata(content)
    };

    return workflow;
  }

  /**
   * Execute a workflow with health monitoring
   */
  async executeWorkflow(workflowName, params = {}) {
    const startTime = Date.now();
    const executionId = `exec_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    
    console.log(`[WORKFLOW] Starting execution: ${workflowName} (${executionId})`);
    
    try {
      // Parse workflow
      const workflow = await this.parseWorkflow(workflowName);
      
      // Check system health before execution
      if (this.healthMonitor) {
        const health = await this.healthMonitor.checkHealth();
        if (health.status === 'unhealthy') {
          throw new Error(`System unhealthy, cannot execute workflow: ${health.message}`);
        }
      }

      // Execute phases/steps
      const results = {
        executionId,
        workflow: workflowName,
        status: 'success',
        startTime,
        steps: [],
        params
      };

      for (const step of workflow.steps) {
        const stepResult = await this.executeStep(step, params);
        results.steps.push(stepResult);
        
        if (stepResult.status === 'failed' && step.required) {
          results.status = 'failed';
          break;
        }
      }

      results.endTime = Date.now();
      results.duration = results.endTime - startTime;

      // Record execution
      this.executionHistory.push(results);

      console.log(`[WORKFLOW] Completed: ${workflowName} (${results.duration}ms)`);
      
      return results;

    } catch (error) {
      console.error(`[ERROR] Workflow execution failed: ${error.message}`);
      
      const failedResult = {
        executionId,
        workflow: workflowName,
        status: 'error',
        error: error.message,
        startTime,
        endTime: Date.now(),
        duration: Date.now() - startTime
      };
      
      this.executionHistory.push(failedResult);
      throw error;
    }
  }

  /**
   * Execute a single workflow step
   */
  async executeStep(step, params) {
    const stepStart = Date.now();
    
    console.log(`[STEP] Executing: ${step.name}`);
    
    try {
      let result;

      // Execute based on step type
      switch (step.type) {
        case 'health_check':
          result = await this.executeHealthCheck(step, params);
          break;
        
        case 'data_query':
          result = await this.executeDataQuery(step, params);
          break;
        
        case 'validation':
          result = await this.executeValidation(step, params);
          break;
        
        case 'code_generation':
          result = await this.executeCodeGeneration(step, params);
          break;
        
        case 'code_modification':
          result = await this.executeCodeModification(step, params);
          break;
        
        case 'ingestion':
          result = await this.executeIngestion(step, params);
          break;
        
        case 'command':
          result = await this.executeCommand(step, params);
          break;
        
        default:
          result = { status: 'skipped', message: 'Unknown step type' };
      }

      return {
        name: step.name,
        status: 'success',
        result,
        duration: Date.now() - stepStart
      };

    } catch (error) {
      console.error(`[ERROR] Step failed: ${step.name}:`, error.message);
      
      return {
        name: step.name,
        status: 'failed',
        error: error.message,
        duration: Date.now() - stepStart
      };
    }
  }

  /**
   * Execute health check step
   */
  async executeHealthCheck(step, params) {
    if (!this.dataAccess) {
      return { status: 'skipped', message: 'Data access not available' };
    }

    try {
      const health = await this.dataAccess.healthCheck();
      return {
        status: health.status,
        graphDB: health.graph,
        vectorDB: health.vector,
        connected: health.connected,
        metrics: health.metrics,
        timestamp: new Date().toISOString()
      };
    } catch (error) {
      return {
        status: 'unhealthy',
        error: error.message,
        timestamp: new Date().toISOString()
      };
    }
  }

  /**
   * Execute data query step
   */
  async executeDataQuery(step, params) {
    if (!this.dataAccess) {
      throw new Error('Data access not available');
    }

    const query = this.interpolateParams(step.query, params);
    const results = await this.dataAccess.hybridQuery(query, step.options || {});
    
    return {
      query,
      resultCount: results.length,
      results: results.slice(0, 10) // Limit results
    };
  }

  /**
   * Execute validation step
   */
  async executeValidation(step, params) {
    const checks = step.checks || [];
    const results = [];
    let allPassed = true;

    for (const check of checks) {
      try {
        let passed = false;
        let message = '';

        switch (check.type) {
          case 'result_count':
            // Validate result count meets minimum threshold
            const minCount = check.minCount || 0;
            const actualCount = params.resultCount || 0;
            passed = actualCount >= minCount;
            message = passed 
              ? `Result count ${actualCount} meets minimum ${minCount}`
              : `Result count ${actualCount} below minimum ${minCount}`;
            break;

          case 'health_status':
            // Validate health status is healthy
            const status = params.status || 'unknown';
            passed = status === 'healthy';
            message = passed
              ? 'Health status is healthy'
              : `Health status is ${status}`;
            break;

          case 'data_freshness':
            // Validate data is recent enough
            const maxAge = check.maxAgeSeconds || 3600;
            const timestamp = params.timestamp ? new Date(params.timestamp) : new Date();
            const ageSeconds = (Date.now() - timestamp.getTime()) / 1000;
            passed = ageSeconds <= maxAge;
            message = passed
              ? `Data age ${ageSeconds.toFixed(0)}s within limit ${maxAge}s`
              : `Data age ${ageSeconds.toFixed(0)}s exceeds limit ${maxAge}s`;
            break;

          case 'pattern_match':
            // Validate data matches expected pattern
            const pattern = new RegExp(check.pattern || '.*');
            const content = params.content || params.query || '';
            passed = pattern.test(content);
            message = passed
              ? 'Content matches expected pattern'
              : 'Content does not match pattern';
            break;

          default:
            message = `Unknown validation type: ${check.type}`;
            passed = false;
        }

        results.push({
          check: check.type,
          passed,
          message
        });

        if (!passed) {
          allPassed = false;
        }

      } catch (error) {
        results.push({
          check: check.type || 'unknown',
          passed: false,
          message: `Validation error: ${error.message}`
        });
        allPassed = false;
      }
    }

    return {
      status: allPassed ? 'passed' : 'failed',
      checks: results,
      totalChecks: checks.length,
      passedChecks: results.filter(r => r.passed).length,
      timestamp: new Date().toISOString()
    };
  }

  /**
   * Execute ingestion step - Trigger RAG knowledge base re-ingestion
   */
  async executeIngestion(step, params) {
    const { source, target = 'all', updateGraph = true, updateVector = true } = step;
    
    try {
      const results = {
        status: 'in-progress',
        source,
        target,
        operations: []
      };

      // Determine which ingestion scripts to run
      const scripts = [];
      
      if (target === 'all' || target === 'documentation') {
        scripts.push({
          name: 'ingest_documentation',
          script: 'ingest_documentation_v4_2_unified.py',
          collection: 'global-workflow-docs-v5-0-0-consolidated'
        });
      }
      
      if (target === 'all' || target === 'code') {
        scripts.push({
          name: 'ingest_code',
          script: 'ingest_code_graph_enriched_v6.py',
          collection: 'code_with_context_v6_graph_enriched'
        });
      }
      
      if (target === 'all' || target === 'ee2') {
        scripts.push({
          name: 'ingest_ee2',
          script: 'ingest_ee2_enhanced_v5.py',
          collection: 'ee2-standards-v5-0-0-enhanced'
        });
      }

      // Run ingestion scripts
      const scriptsDir = path.join(this.repoRoot, 'mcp_server_node/scripts');
      
      for (const scriptInfo of scripts) {
        try {
          console.error(`[START] Running ${scriptInfo.name}...`);
          
          const scriptPath = path.join(scriptsDir, scriptInfo.script);
          const output = execSync(`python3 "${scriptPath}"`, {
            cwd: scriptsDir,
            timeout: 300000, // 5 minutes
            encoding: 'utf-8'
          });
          
          // Parse output for document count
          const countMatch = output.match(/(\d+)\s+documents?/i);
          const docCount = countMatch ? parseInt(countMatch[1]) : 0;
          
          results.operations.push({
            script: scriptInfo.name,
            collection: scriptInfo.collection,
            documentsProcessed: docCount,
            status: 'completed'
          });
          
          console.error(`[OK] ${scriptInfo.name} completed: ${docCount} documents`);
          
        } catch (error) {
          results.operations.push({
            script: scriptInfo.name,
            status: 'failed',
            error: error.message
          });
          console.error(`[ERROR] ${scriptInfo.name} failed: ${error.message}`);
        }
      }

      // Calculate totals
      const totalDocs = results.operations
        .filter(op => op.status === 'completed')
        .reduce((sum, op) => sum + (op.documentsProcessed || 0), 0);
      
      const allSucceeded = results.operations.every(op => op.status === 'completed');
      
      return {
        status: allSucceeded ? 'completed' : 'partial',
        source,
        target,
        totalDocumentsProcessed: totalDocs,
        operations: results.operations,
        timestamp: new Date().toISOString()
      };
      
    } catch (error) {
      return {
        status: 'failed',
        source: step.source,
        error: error.message,
        timestamp: new Date().toISOString()
      };
    }
  }

  /**
   * Execute command step - Safe system command execution
   */
  async executeCommand(step, params) {
    const { 
      command, 
      sandbox = true, 
      timeout = 30000,
      cwd = this.repoRoot,
      allowedCommands = ['npm', 'git', 'node', 'python3', 'test']
    } = step;
    
    try {
      // Interpolate parameters in command
      const interpolatedCmd = this.interpolateParams(command, params);
      
      // Safety check: validate command against allowlist
      const cmdParts = interpolatedCmd.split(/\s+/);
      const baseCmd = cmdParts[0];
      
      if (sandbox) {
        const isAllowed = allowedCommands.some(allowed => 
          baseCmd === allowed || baseCmd.endsWith(`/${allowed}`)
        );
        
        if (!isAllowed) {
          throw new Error(`Command not allowed in sandbox: ${baseCmd}`);
        }
        
        // Additional safety checks
        if (interpolatedCmd.includes('rm -rf /') || 
            interpolatedCmd.includes('rm -rf ~') ||
            interpolatedCmd.includes('sudo')) {
          throw new Error('Dangerous command blocked');
        }
      }
      
      console.error(`[START] Executing command: ${interpolatedCmd}`);
      
      // Execute command
      const startTime = Date.now();
      const output = execSync(interpolatedCmd, {
        cwd,
        timeout,
        encoding: 'utf-8',
        stdio: 'pipe'
      });
      const duration = Date.now() - startTime;
      
      console.error(`[OK] Command completed in ${duration}ms`);
      
      return {
        status: 'executed',
        command: interpolatedCmd,
        output: output.trim(),
        duration,
        exitCode: 0,
        timestamp: new Date().toISOString()
      };
      
    } catch (error) {
      console.error(`[ERROR] Command failed: ${error.message}`);
      
      return {
        status: 'failed',
        command: step.command,
        error: error.message,
        exitCode: error.status || 1,
        output: error.stdout?.toString() || '',
        timestamp: new Date().toISOString()
      };
    }
  }

  /**
   * Get execution history
   */
  getExecutionHistory(limit = 10) {
    return this.executionHistory.slice(-limit);
  }

  /**
   * Helper: Extract title from markdown
   */
  extractTitle(content) {
    const match = content.match(/^#\s+(.+)$/m);
    return match ? match[1].trim() : 'Untitled Workflow';
  }

  /**
   * Helper: Extract description
   */
  extractDescription(content) {
    const lines = content.split('\n');
    let description = '';
    let inDescription = false;
    
    for (const line of lines) {
      if (line.startsWith('# ')) {
        inDescription = true;
        continue;
      }
      if (line.startsWith('## ')) {
        break;
      }
      if (inDescription && line.trim()) {
        description += line.trim() + ' ';
      }
    }
    
    return description.trim();
  }

  /**
   * Helper: Extract phases from markdown
   */
  extractPhases(content) {
    const phases = [];
    const phaseRegex = /^##\s+Phase\s+(\d+):\s+(.+)$/gm;
    let match;
    
    while ((match = phaseRegex.exec(content)) !== null) {
      phases.push({
        number: parseInt(match[1]),
        name: match[2].trim()
      });
    }
    
    return phases;
  }

  /**
   * Helper: Extract steps from markdown
   */
  extractSteps(content) {
    const steps = [];
    const lines = content.split('\n');
    
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      
      // Look for numbered steps: "1. **Step Name**" or "### Step 1: Step Name"
      const stepMatch1 = line.match(/^(\d+)\.\s+\*\*(.+?)\*\*/);
      const stepMatch2 = line.match(/^###\s+Step\s+(\d+):\s+(.+)$/);
      
      if (stepMatch1 || stepMatch2) {
        const stepNumber = stepMatch1 ? parseInt(stepMatch1[1]) : parseInt(stepMatch2[1]);
        const stepName = stepMatch1 ? stepMatch1[2].trim() : stepMatch2[2].trim();
        
        const step = {
          number: stepNumber,
          name: stepName,
          type: 'manual',  // Will be updated from metadata
          required: true,
          description: '',
          metadata: {}
        };
        
        // Collect metadata and description lines
        for (let j = i + 1; j < lines.length && !lines[j].match(/^(###\s+Step|\d+\.)/); j++) {
          const metaLine = lines[j];
          
          // Extract metadata: **Key**: Value
          const metaMatch = metaLine.match(/^\*\*(.+?)\*\*:\s*(.+)$/);
          if (metaMatch) {
            const key = metaMatch[1].toLowerCase().trim();
            const value = metaMatch[2].trim();
            
            if (key === 'type') {
              step.type = value.toLowerCase();
            } else if (key === 'required') {
              step.required = value.toLowerCase() === 'yes' || value.toLowerCase() === 'true';
            } else {
              step.metadata[key] = value;
              // Promote common properties
              if (['query', 'target', 'source', 'command'].includes(key)) {
                step[key] = value.replace(/^"(.*)"$/, '$1'); // Remove quotes if present
              }
            }
          } else if (metaLine.trim() && !metaLine.startsWith('#')) {
            step.description += metaLine.trim() + ' ';
          }
        }
        
        // Infer type if not specified
        if (step.type === 'manual') {
          step.type = this.inferStepType(stepName);
        }
        
        steps.push(step);
      }
    }
    
    return steps;
  }

  /**
   * Helper: Infer step type from name
   */
  inferStepType(stepName) {
    const lower = stepName.toLowerCase();
    
    if (lower.includes('health') || lower.includes('check status')) {
      return 'health_check';
    }
    if (lower.includes('query') || lower.includes('search')) {
      return 'data_query';
    }
    if (lower.includes('validate') || lower.includes('verify')) {
      return 'validation';
    }
    if (lower.includes('ingest') || lower.includes('import')) {
      return 'ingestion';
    }
    if (lower.includes('run') || lower.includes('execute')) {
      return 'command';
    }
    
    return 'manual'; // Requires manual intervention
  }

  /**
   * Helper: Extract metadata
   */
  extractMetadata(content) {
    const metadata = {};
    
    // Extract key-value pairs from markdown
    const metaRegex = /^\*\*(.+?)\*\*:\s*(.+)$/gm;
    let match;
    
    while ((match = metaRegex.exec(content)) !== null) {
      const key = match[1].toLowerCase().replace(/\s+/g, '_');
      metadata[key] = match[2].trim();
    }
    
    return metadata;
  }

  /**
   * Helper: Interpolate parameters in strings
   */
  interpolateParams(str, params) {
    if (!str) return str;
    
    return str.replace(/\{(\w+)\}/g, (match, key) => {
      return params[key] !== undefined ? params[key] : match;
    });
  }

  /**
   * Execute code generation step (Phase 4: Bootstrap)
   */
  async executeCodeGeneration(step, params) {
    if (!this.selfModEngine.currentTransaction) {
      await this.selfModEngine.beginTransaction('code_generation');
    }

    try {
      const spec = {
        filePath: step.target || step.file,
        template: step.template,
        content: step.content,
        variables: { ...step, ...params }
      };

      const result = await this.selfModEngine.generateFile(spec);
      
      return {
        status: 'generated',
        filePath: result.path,
        size: result.content.length,
        timestamp: new Date().toISOString()
      };
    } catch (error) {
      return {
        status: 'failed',
        error: error.message,
        timestamp: new Date().toISOString()
      };
    }
  }

  /**
   * Execute code modification step (Phase 4: Bootstrap)
   */
  async executeCodeModification(step, params) {
    if (!this.selfModEngine.currentTransaction) {
      await this.selfModEngine.beginTransaction('code_modification');
    }

    try {
      // Parse modification spec
      const spec = this.specParser.parseStep(step);
      
      let result;
      if (spec.type === 'add_method') {
        result = await this.selfModEngine.addMethod(spec.spec);
      } else if (spec.type === 'register_tool') {
        result = await this.selfModEngine.registerTool(spec.spec);
      } else {
        result = await this.selfModEngine.modifyFile(spec.spec);
      }
      
      return {
        status: 'modified',
        filePath: result.path,
        operation: spec.type,
        timestamp: new Date().toISOString()
      };
    } catch (error) {
      return {
        status: 'failed',
        error: error.message,
        timestamp: new Date().toISOString()
      };
    }
  }

  /**
   * Begin self-modification transaction
   */
  async beginSelfModification(name) {
    return await this.selfModEngine.beginTransaction(name);
  }

  /**
   * Commit self-modification transaction
   */
  async commitSelfModification() {
    return await this.selfModEngine.commitTransaction();
  }

  /**
   * Rollback self-modification transaction
   */
  async rollbackSelfModification() {
    return await this.selfModEngine.rollbackTransaction();
  }

  /**
   * Validate current modifications
   */
  async validateModifications() {
    return await this.selfModEngine.validateChanges();
  }
}
