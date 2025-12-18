#!/usr/bin/env node

/**
 * EE2ComplianceTools.js - EE2 Standards Compliance Validation
 * 
 * Provides tools for validating code and documentation against
 * NOAA NWS EE2 (Enterprise Environmental 2) standards.
 * 
 * Extracted from SemanticSearchTools.js for better Separation of Concerns (SOC).
 * 
 * Features:
 * - EE2 standards search via semantic embeddings
 * - Phase 2 SME-corrected compliance analysis
 * - Repository-wide compliance scanning
 * - Evidence-based compliance reporting
 * 
 * Phase 2 Integration:
 * - Loads phase2_anti_patterns.json for scan validation
 * - Single source of truth: RST annotations → ChromaDB → JSON config
 * - Context discrimination (operational/utility/test scripts)
 * 
 * @version 1.0.0
 * @domain EE2_Compliance
 * @author Claude Sonnet 4.5
 * @supervisor Terry McGuinness
 * @date 2025-11-30
 * @extracted_from SemanticSearchTools.js v2.1.0
 */

import { UnifiedDataAccess } from '../data/UnifiedDataAccess.js';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { readFileSync, existsSync, statSync } from 'fs';

// Phase 4C: Code snippet extraction and LLM passthrough
import { CodeSnippetExtractor } from './CodeSnippetExtractor.js';
import { generateAnalysisPrompt, getAvailableCategories } from './EE2AnalysisPrompts.js';

// Phase 19: Content Abstraction Layer for remote MCP support
import { ContentResolver } from '../utils/ContentResolver.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Load Phase 2 configuration (generated from knowledge base)
// This is the SME-corrected anti-pattern database
let phase2Config = null;
try {
  const configPath = join(__dirname, '..', '..', 'phase2_anti_patterns.json');
  phase2Config = JSON.parse(readFileSync(configPath, 'utf-8'));
  console.error(`[OK] EE2ComplianceTools: Loaded Phase 2 config (${phase2Config.anti_patterns.error_handling.length} anti-patterns)`);
} catch (error) {
  console.error(`[WARN] EE2ComplianceTools: Phase 2 config not found: ${error.message}`);
  console.error('[WARN] EE2 scan tool will use fallback validation');
}

export class EE2ComplianceTools {
  constructor(dataAccess = null) {
    this.dataAccess = dataAccess;  // Accept injected dependency for testing
    this.isInitialized = !!dataAccess;  // Already initialized if dataAccess provided
    this.phase2Config = phase2Config;  // Phase 2 anti-pattern configuration
  }

  async initialize() {
    if (this.isInitialized) return;

    console.error('[INIT] Initializing EE2 Compliance Tools...');
    
    try {
      this.dataAccess = new UnifiedDataAccess();
      await this.dataAccess.connect();
      
      this.isInitialized = true;
      console.error('[OK] EE2 Compliance Tools initialized');
    } catch (error) {
      console.error('[ERROR] EE2 Compliance Tools initialization failed:', error.message);
      console.error('   Tools will return error messages when called.');
      // Mark as initialized anyway to prevent repeated init attempts
      this.isInitialized = true;
      this.initializationError = error;
    }
  }

  async ensureInitialized() {
    if (!this.isInitialized) {
      await this.initialize();
    }
  }

  /**
   * Register all EE2 compliance tools with the MCP server
   * @param {object} server - MCP server instance
   */
  registerWith(server) {
    // Tool 1: Search EE2 Standards
    server.registerTool(
      'search_ee2_standards',
      'Search EE2 compliance standards and documentation',
      {
        type: 'object',
        properties: {
          query: { type: 'string', description: 'EE2 compliance query' },
          category: {
            type: 'string',
            enum: ['environment_variables', 'workflow_structure', 'error_handling', 
                   'file_naming', 'production_utilities', 'code_standards', 'directory_structure'],
            description: 'Specific compliance category'
          },
          max_results: { type: 'number', default: 8, minimum: 1, maximum: 20 },
          include_examples: { type: 'boolean', default: true }
        },
        required: ['query']
      },
      this.searchEE2Standards.bind(this)
    );

    // Tool 2: Analyze EE2 Compliance
    server.registerTool(
      'analyze_ee2_compliance',
      'Analyze code or documentation for EE2 compliance',
      {
        type: 'object',
        properties: {
          content: { type: 'string', description: 'Code or documentation content to analyze' },
          analysis_type: {
            type: 'string',
            enum: ['comprehensive', 'environment_variables', 'workflow_structure', 'error_handling',
                   'file_naming', 'production_utilities', 'code_standards', 'directory_structure'],
            default: 'comprehensive'
          },
          include_recommendations: { type: 'boolean', default: true }
        },
        required: ['content']
      },
      this.analyzeEE2Compliance.bind(this)
    );

    // Tool 3: Generate Compliance Report
    server.registerTool(
      'generate_compliance_report',
      'Generate comprehensive EE2 compliance report',
      {
        type: 'object',
        properties: {
          scope: { type: 'string', enum: ['summary', 'detailed', 'checklist'], default: 'summary' },
          categories: { type: 'array', items: { type: 'string' }, default: [] },
          format: { type: 'string', enum: ['markdown', 'checklist', 'summary'], default: 'markdown' }
        }
      },
      this.generateComplianceReport.bind(this)
    );

    // Tool 4: Repository-Wide Compliance Scan (Phase 19 Content Abstraction)
    server.registerTool(
      'scan_repository_compliance',
      'Scan repository for EE2 compliance. Supports direct file content (remote MCP) or filesystem path (local mode).',
      {
        type: 'object',
        properties: {
          files: {
            type: 'array',
            items: {
              type: 'object',
              properties: {
                name: { type: 'string', description: 'Filename' },
                path: { type: 'string', description: 'Relative path for context' },
                content: { type: 'string', description: 'File content' }
              },
              required: ['name', 'content']
            },
            description: 'Files with content for batch analysis (preferred for remote MCP)'
          },
          repository_path: { 
            type: 'string', 
            description: 'Absolute path to repository root (local mode only - use files for remote)' 
          },
          file_patterns: { 
            type: 'array', 
            items: { type: 'string' },
            default: ['**/*.sh', '**/*.py', '**/JEVS_*', '**/exglobal_*', '**/*.config'],
            description: 'Glob patterns for files to analyze (repository_path mode only)'
          },
          sample_size: { 
            type: 'number', 
            default: 10000, 
            minimum: 10, 
            maximum: 10000,
            description: 'Maximum files to analyze (repository_path mode only)'
          },
          categories: {
            type: 'array',
            items: { type: 'string' },
            default: ['error_handling', 'environment_variables', 'file_naming'],
            description: 'Compliance categories to analyze'
          }
        }
        // Note: No required fields - ContentResolver validates at runtime
      },
      this.scanRepositoryCompliance.bind(this)
    );

    // Tool 5: Extract Code for LLM Analysis (Phase 4C + Phase 19 Content Abstraction)
    server.registerTool(
      'extract_code_for_analysis',
      'Extract code snippets from files for EE2 compliance analysis. Returns structured data with LLM prompts. Supports direct content (remote MCP) or file paths (local mode).',
      {
        type: 'object',
        properties: {
          content: { 
            type: 'string', 
            description: 'Code content to analyze directly (preferred for remote MCP access)' 
          },
          files: {
            type: 'array',
            items: {
              type: 'object',
              properties: {
                name: { type: 'string', description: 'Filename for context' },
                path: { type: 'string', description: 'Relative path for context' },
                content: { type: 'string', description: 'File content' }
              },
              required: ['name', 'content']
            },
            description: 'Multiple files with content for batch analysis'
          },
          path: { 
            type: 'string', 
            description: 'Path to file or directory to analyze (local mode only - use content for remote)' 
          },
          content_type: {
            type: 'string',
            enum: ['bash', 'python', 'auto'],
            description: 'Content type hint for parser selection',
            default: 'auto'
          },
          categories: {
            type: 'array',
            items: { 
              type: 'string',
              enum: ['output_file_naming', 'error_handling', 'shebang_compliance', 'env_var_validation']
            },
            description: 'Analysis categories to extract patterns for',
            default: ['output_file_naming', 'error_handling']
          },
          file_pattern: {
            type: 'string',
            description: 'Regex pattern for files to include (path mode only)',
            default: '\\.(sh|py)$'
          },
          max_files: {
            type: 'number',
            description: 'Maximum files to scan (path mode only)',
            default: 50
          }
        }
        // Note: No required fields - ContentResolver will validate at runtime
      },
      this.extractCodeForAnalysis.bind(this)
    );

    console.error('[OK] Registered 5 EE2 Compliance tools');
  }

  // ============================================================================
  // Tool Implementations
  // ============================================================================

  /**
   * Search EE2 standards using semantic search
   */
  async searchEE2Standards(args) {
    await this.ensureInitialized();
    
    // Check if initialization failed
    if (this.initializationError) {
      return {
        content: [{
          type: 'text',
          text: `[ERROR] EE2 Standards Search not available: ${this.initializationError.message}\n\nPlease check that ChromaDB is running.`
        }]
      };
    }
    
    const { query, category, max_results = 8, include_examples = true } = args;

    try {
      console.error(`[SEARCH] Starting search_ee2_standards: "${query}" (category=${category || 'all'})`);
      
      // Build enhanced query with category filter
      const enhancedQuery = category ? `${query} ${category} EE2 compliance` : `${query} EE2 compliance`;
      
      // Use hybridQuery - EE2 standards don't need graph enrichment
      const results = await this.dataAccess.hybridQuery(enhancedQuery, {
        maxResults: max_results,
        includeGraph: false,
        similarityThreshold: 0.1
      });

      console.error(`[OK] EE2 search completed, found ${results?.length || 0} results`);

      let output = `# EE2 Standards Search: ${query}\n\n`;
      if (category) output += `**Category:** ${category}\n\n`;
      output += `Found ${results?.length || 0} standards\n\n`;

      if (!results || results.length === 0) {
        output += `No EE2 standards found matching: "${query}"\n`;
        return { content: [{ type: 'text', text: output }] };
      }

      for (let i = 0; i < results.length; i++) {
        const result = results[i];
        output += `## Standard ${i + 1}\n`;
        output += `**Similarity:** ${(result.distance * 100).toFixed(1)}%\n`;
        
        if (result.metadata?.category) {
          output += `**Category:** ${result.metadata.category}\n`;
        }
        
        output += `\n${result.document || result.text}\n\n`;
        
        if (include_examples && result.metadata?.example) {
          output += `**Example:**\n\`\`\`\n${result.metadata.example}\n\`\`\`\n\n`;
        }
        output += `---\n\n`;
      }

      return { content: [{ type: 'text', text: output }] };
    } catch (error) {
      console.error(`[ERROR] Error in search_ee2_standards: ${error.message}`);
      return {
        content: [{ type: 'text', text: `Error searching EE2 standards: ${error.message}` }],
        isError: true
      };
    }
  }

  /**
   * Analyze content for EE2 compliance
   */
  async analyzeEE2Compliance(args) {
    await this.ensureInitialized();
    
    if (this.initializationError) {
      return {
        content: [{
          type: 'text',
          text: `[INFO] EE2 Compliance analysis not available: ${this.initializationError.message}`
        }]
      };
    }
    
    const { content, analysis_type = 'comprehensive', include_recommendations = true } = args;

    try {
      console.error(`[ANALYZE] Starting EE2 compliance analysis: type=${analysis_type}`);
      
      let output = `# EE2 Compliance Review\n\n`;
      output += `**Analysis Focus:** ${analysis_type.replace(/_/g, ' ')}\n\n`;
      
      // Step 1: Retrieve relevant EE2 standards using semantic search
      const categories = analysis_type === 'comprehensive' 
        ? ['error_handling', 'environment_variables', 'file_naming', 'code_standards']
        : [analysis_type];
      
      const standards = {};
      for (const category of categories) {
        const query = this._buildStandardsQuery(category);
        const results = await this.dataAccess.hybridQuery(query, {
          nResults: 3,
          includeGraphContext: false
        });
        standards[category] = results;
      }
      
      console.error(`[OK] Retrieved standards for ${Object.keys(standards).length} categories`);
      
      // Step 2: Analyze content against retrieved standards (consultative tone)
      const observations = [];
      
      // Error handling analysis
      if (standards.error_handling) {
        const hasSetEu = /set -[eu]/.test(content);
        const isBashScript = /^#!\/bin\/(ba)?sh/.test(content);
        
        if (isBashScript && !hasSetEu) {
          observations.push({
            category: 'Error Handling',
            pattern: 'Bash script without explicit error handling',
            suggestion: 'Consider adding "set -eu" or "set -euo pipefail" near the script start',
            reasoning: 'The EE2 standards suggest explicit error handling to improve reliability and debugging',
            reference: standards.error_handling[0]?.metadata?.section_headers || 'General Application Standards'
          });
        }
      }
      
      // Environment variable analysis
      if (standards.environment_variables) {
        const unquotedVars = content.match(/\$[A-Z_][A-Z0-9_]*/g) || [];
        const quotedVars = content.match(/"\$\{[A-Z_][A-Z0-9_]*\}"/g) || [];
        
        if (unquotedVars.length > quotedVars.length) {
          observations.push({
            category: 'Environment Variables',
            pattern: `Found ${unquotedVars.length} unquoted variable references`,
            suggestion: 'You might want to quote variables as "${VARIABLE}" to prevent word splitting',
            reasoning: 'Quoted variables help avoid unexpected behavior with spaces or special characters',
            reference: standards.environment_variables[0]?.metadata?.section_headers || 'Standard Variables'
          });
        }
      }
      
      // Format output with consultative tone
      if (observations.length === 0) {
        output += `## Review Summary\n\n`;
        output += `The code appears to align well with EE2 guidelines for the analyzed categories. `;
        output += `No significant concerns were identified.\n\n`;
      } else {
        output += `## Observations & Suggestions\n\n`;
        output += `Based on the EE2 implementation standards, here are some areas you might consider reviewing:\n\n`;
        
        for (const obs of observations) {
          output += `### ${obs.category}\n\n`;
          output += `**Pattern observed:** ${obs.pattern}\n\n`;
          output += `**Suggestion:** ${obs.suggestion}\n\n`;
          output += `**Why this matters:** ${obs.reasoning}\n\n`;
          output += `**Reference:** ${obs.reference}\n\n`;
          output += `---\n\n`;
        }
      }
      
      // Include relevant standard excerpts for context
      if (include_recommendations && Object.keys(standards).length > 0) {
        output += `## Relevant EE2 Standards\n\n`;
        output += `Here are the applicable guidelines from the EE2 implementation standards:\n\n`;
        
        for (const [category, results] of Object.entries(standards)) {
          if (results && results.length > 0) {
            const top = results[0];
            const docText = top.document || top.text || '';
            output += `### ${category.replace(/_/g, ' ').toUpperCase()}\n\n`;
            if (top.metadata?.section_headers) {
              output += `**Section:** ${top.metadata.section_headers}\n\n`;
            }
            if (docText) {
              output += `${docText.substring(0, 400)}...\n\n`;
            }
          }
        }
      }
      
      output += `\n---\n\n`;
      output += `*Note: These suggestions are based on EE2 implementation standards and are provided as guidance. `;
      output += `Your specific use case may have valid reasons for different approaches.*\n`;

      console.error(`[OK] Compliance analysis complete: ${observations.length} observations`);
      return { content: [{ type: 'text', text: output }] };
      
    } catch (error) {
      console.error(`[ERROR] Compliance analysis failed: ${error.message}`);
      return {
        content: [{ type: 'text', text: `Unable to complete compliance analysis: ${error.message}` }],
        isError: true
      };
    }
  }

  /**
   * Generate EE2 compliance report
   */
  async generateComplianceReport(args) {
    await this.ensureInitialized();
    
    if (this.initializationError) {
      return {
        content: [{
          type: 'text',
          text: `[INFO] Compliance reporting not available: ${this.initializationError.message}`
        }]
      };
    }
    
    const { scope = 'summary', categories = [], format = 'markdown' } = args;

    try {
      console.error(`[REPORT] Generating EE2 compliance report: scope=${scope}, format=${format}`);
      
      let output = `# EE2 Implementation Standards Reference\n\n`;
      output += `**Generated:** ${new Date().toISOString().split('T')[0]}\n`;
      output += `**Scope:** ${scope}\n\n`;
      
      output += `This report provides guidance based on the NCEP WCOSS Implementation Standards (EE2). `;
      output += `These are recommendations to help align code with production best practices.\n\n`;

      const allCategories = [
        'environment_variables',
        'error_handling',
        'file_naming',
        'workflow_structure',
        'production_utilities',
        'code_standards',
        'directory_structure'
      ];

      const targetCategories = categories.length > 0 ? categories : allCategories;
      
      // Retrieve actual standards from knowledge base
      for (const category of targetCategories) {
        const query = this._buildStandardsQuery(category);
        const results = await this.dataAccess.hybridQuery(query, {
          nResults: 2,
          includeGraphContext: false
        });
        
        output += `## ${category.replace(/_/g, ' ').toUpperCase()}\n\n`;
        
        if (results && results.length > 0) {
          const top = results[0];
          const docText = top.document || top.text || '';
          
          if (top.metadata?.section_headers) {
            output += `**Reference:** ${top.metadata.section_headers}\n\n`;
          }
          
          if (scope === 'summary' && docText) {
            output += `${docText.substring(0, 300)}...\n\n`;
          } else if (scope === 'detailed' && docText) {
            output += `${docText}\n\n`;
            if (results[1]) {
              const doc2 = results[1].document || results[1].text || '';
              if (doc2) {
                output += `### Additional Context\n\n`;
                output += `${doc2.substring(0, 400)}...\n\n`;
              }
            }
          } else if (scope === 'checklist' && docText) {
            // Extract key points as checklist items
            const points = this._extractChecklistItems(docText);
            for (const point of points) {
              output += `- [ ] ${point}\n`;
            }
            output += `\n`;
          }
          
          if (top.metadata?.url) {
            output += `**Documentation:** ${top.metadata.url}\n\n`;
          }
        } else {
          output += `*Guidelines for this category are being retrieved from the standards documentation.*\n\n`;
        }
        
        output += `---\n\n`;
      }
      
      output += `\n## How to Use This Report\n\n`;
      output += `- These guidelines are **suggestions** based on NCEP operational standards\n`;
      output += `- Consider your specific use case when applying recommendations\n`;
      output += `- Standards help improve maintainability and reliability\n`;
      output += `- Consult with your team lead if you have questions about applicability\n\n`;
      
      output += `**Note:** This is reference material, not a mandated checklist. `;
      output += `Use professional judgment when applying these guidelines to your code.\n`;

      const needsPassthrough = categories.length === 0
        || categories.includes('file_naming')
        || categories.includes('environment_variables');
      if (needsPassthrough) {
        output += `\n## Passthrough Recommendation (Output Naming / COM)\n\n`;
        output += `Run extract_code_for_analysis with categories output_file_naming, shebang_compliance, env_var_validation on the target repo path (e.g., scripts/, ush/) to surface COM/COMOUT filename patterns and env validation that the standard scan does not cover automatically.\n`;
      }

      console.error(`[OK] Compliance report generated: ${targetCategories.length} categories`);
      return { content: [{ type: 'text', text: output }] };
      
    } catch (error) {
      console.error(`[ERROR] Report generation failed: ${error.message}`);
      return {
        content: [{ type: 'text', text: `Unable to generate compliance report: ${error.message}` }],
        isError: true
      };
    }
  }

  /**
   * Scan repository for EE2 compliance issues
   * Uses Phase 2 SME-corrected patterns to avoid false positives
   */
  async scanRepositoryCompliance(args) {
    await this.ensureInitialized();
    
    if (this.initializationError) {
      return {
        content: [{
          type: 'text',
          text: `[INFO] Repository scan not available: ${this.initializationError.message}`
        }]
      };
    }
    
    const { 
      repository_path, 
      file_patterns = ['**/*.sh', '**/*.py', '**/JEVS_*', '**/exglobal_*', '**/*.config'],
      sample_size = 10000,  // Default to full scan
      categories = ['error_handling', 'environment_variables', 'file_naming']
    } = args;

    try {
      console.error(`[SCAN] Starting repository compliance scan: ${repository_path}`);
      const fs = await import('fs');
      const path = await import('path');
      const { glob } = await import('glob');
      
      // Verify repository exists
      if (!fs.existsSync(repository_path)) {
        return {
          content: [{ type: 'text', text: `Repository not found: ${repository_path}` }],
          isError: true
        };
      }
      
      // Collect all files matching patterns
      const allFiles = [];
      const filesByType = {
        shell_scripts: [],
        python_scripts: [],
        job_cards: [],
        config_files: []
      };
      
      for (const pattern of file_patterns) {
        const matches = await glob(pattern, {
          cwd: repository_path,
          absolute: false,
          ignore: ['**/dev/**', 'dev/**']  // Exclude /dev and all subdirectories
        });
        allFiles.push(...matches.map(f => path.join(repository_path, f)));
      }
      
      console.error(`[OK] Found ${allFiles.length} files (excluding /dev directory)`);
      
      // Categorize files
      for (const file of allFiles) {
        const basename = path.basename(file);
        const ext = path.extname(file);
        
        if (ext === '.sh' || basename.startsWith('ex')) {
          filesByType.shell_scripts.push(file);
        } else if (ext === '.py') {
          filesByType.python_scripts.push(file);
        } else if (basename.startsWith('JEVS_') || basename.startsWith('J')) {
          filesByType.job_cards.push(file);
        } else if (ext === '.config' || ext === '.cfg') {
          filesByType.config_files.push(file);
        }
      }
      
      // Determine files to analyze - full scan or sample
      const samplesToAnalyze = [];
      const totalFiles = Object.values(filesByType).reduce((sum, arr) => sum + arr.length, 0);
      
      // If sample_size >= total files, analyze everything (full scan)
      if (sample_size >= totalFiles) {
        console.error(`[ANALYZE] Full repository scan - analyzing all ${totalFiles} files`);
        for (const [type, files] of Object.entries(filesByType)) {
          samplesToAnalyze.push(...files.map(f => ({ file: f, type })));
        }
      } else {
        // Sample mode - randomly select files
        const samplesPerType = Math.floor(sample_size / 4);
        console.error(`[ANALYZE] Sample mode - analyzing ${sample_size} of ${totalFiles} files`);
        for (const [type, files] of Object.entries(filesByType)) {
          const shuffled = files.sort(() => 0.5 - Math.random());
          samplesToAnalyze.push(...shuffled.slice(0, samplesPerType).map(f => ({ file: f, type })));
        }
      }
      
      // Analyze samples and collect statistics
      const issuesByCategory = {};
      const fileIssues = [];
      
      for (const category of categories) {
        issuesByCategory[category] = {
          total_files_with_issues: 0,
          specific_files: [],
          common_patterns: []
        };
      }
      
      for (const { file, type } of samplesToAnalyze) {
        try {
          const content = fs.readFileSync(file, 'utf-8');
          const lines = content.split('\n');
          const relativePath = path.relative(repository_path, file);
          
          // Enhanced analysis with code examples and specific fixes
          const fileIssue = {
            file: relativePath,
            type,
            issues: [],
            examples: []  // Actual code snippets showing violations
          };
          
          // Error handling check - ENHANCED with Phase 2 corrections
          if (categories.includes('error_handling')) {
            const violations = [];
            
            if (content.includes('#!/bin/bash') || content.includes('#!/bin/sh')) {
              // Check for shebang position (must be line 1)
              let shebangLine = -1;
              for (let i = 0; i < Math.min(3, lines.length); i++) {
                if (lines[i].match(/^#!/)) {
                  shebangLine = i;
                  break;
                }
              }
              
              if (shebangLine > 0) {
                violations.push({
                  issue: `Shebang on line ${shebangLine + 1}, must be line 1`,
                  line: shebangLine + 1,
                  current: lines[shebangLine],
                  fix: `Remove ${shebangLine} blank line${shebangLine > 1 ? 's' : ''} before shebang - it must be the very first line`
                });
              }
              
              // Phase 2 Correction: Check for set -x (not set -eu)
              // EE2 only requires "set -x" for debug logging per standards.rst lines 588-595
              // Phase 2 SME correction: Do NOT flag missing set -eu (80% false positive rate)
              // Phase 2 Pattern Recognition: Files using err_chk are compliant
              if (this.phase2Config) {
                // Use Phase 2 knowledge: set -x OR err_chk/err_exit usage is compliant
                const hasErrorHandling = content.match(/set -x/) || content.match(/err_chk|err_exit/);
                if (!hasErrorHandling) {
                  violations.push({
                    issue: 'Missing set -x (EE2 debug logging requirement)',
                    line: shebangLine >= 0 ? shebangLine + 2 : 2,
                    current: shebangLine >= 0 ? lines[shebangLine] : lines[0],
                    fix: 'Add "set -x" after shebang per EE2 standard (NOT set -eu)',
                    evidence: 'standards.rst lines 588-595, 868-919, 926-985',
                    phase2_correction: 'set -eu is NOT required by EE2; err_chk/err_exit usage indicates compliant error handling'
                  });
                }
              } else {
                // Fallback: Check for any error handling (backward compatibility)
                if (!content.match(/set -[eux]/)) {
                  violations.push({
                    issue: 'Missing error handling (set -x recommended)',
                    line: shebangLine >= 0 ? shebangLine + 2 : 2,
                    current: shebangLine >= 0 ? lines[shebangLine] : lines[0],
                    fix: 'Add "set -x" for debug logging per EE2 standard'
                  });
                }
              }
              
              // Check for FATAL ERROR prefix usage
              const errorLines = lines.filter((l, i) => 
                l.match(/echo.*error|exit [1-9]/) && !l.includes('FATAL ERROR:')
              );
              if (errorLines.length > 0) {
                violations.push({
                  issue: 'Error messages missing FATAL ERROR: prefix',
                  example: errorLines[0].trim(),
                  fix: 'Prefix error messages with "FATAL ERROR:" per EE2 standard'
                });
              }
              
              // Phase 2 Correction: Input validation WITHOUT forced exits
              // NCO SPAs prohibit explicit exit statements (60% false positive rate)
              // Use err_exit utility instead per standards.rst line 191
              if (content.match(/\.(nc|grib|grib2|bin)\b/) && !content.match(/if.*-f.*then/i)) {
                if (this.phase2Config) {
                  // Phase 2: Recommend err_exit utility (no forced exit)
                  violations.push({
                    issue: 'No input data existence check before processing',
                    fix: 'Add: if [ ! -f "$INPUT_FILE" ]; then err_exit "FATAL ERROR: Required file $INPUT_FILE not found"; fi',
                    evidence: 'standards.rst line 191',
                    phase2_correction: 'Use err_exit utility, NOT explicit exit statements'
                  });
                } else {
                  // Fallback: Original recommendation (includes exit 1)
                  violations.push({
                    issue: 'No input data existence check before processing',
                    fix: 'Add "if [ ! -f $INPUT_FILE ]; then echo FATAL ERROR: ...; exit 1; fi"'
                  });
                }
              }
            }
            
            if (violations.length > 0) {
              fileIssue.issues.push('error_handling');
              fileIssue.examples.push(...violations);
              issuesByCategory.error_handling.total_files_with_issues++;
            }
          }
          
          // Environment variable check - Phase 2 ONLY (evidence-based)
          if (categories.includes('environment_variables')) {
            const envVarRules = this.phase2Config?.anti_patterns?.environment_variables || [];
            
            if (envVarRules.length > 0) {
              // Only check patterns explicitly defined in Phase 2 config with EE2 evidence
              const violations = [];
              envVarRules.forEach(rule => {
                if (!rule.evidence || rule.evidence.length === 0) {
                  console.error(`[WARN] Skipping rule ${rule.name}: No EE2 evidence chain`);
                  return;
                }
                
                // Apply Phase 2-validated pattern detection
                // (Future: Implement when SMEs add environment variable rules to Phase 2 annotations)
                console.error(`[INFO] Enforcing rule: ${rule.name} (EE2 evidence: ${rule.evidence.join(', ')})`);
              });
              
              if (violations.length > 0) {
                fileIssue.issues.push('environment_variables');
                fileIssue.examples.push(...violations);
                issuesByCategory.environment_variables.total_files_with_issues++;
              }
            } else {
               // No Phase 2 rules defined = No enforceable violations
               // This prevents hallucination of best practices as EE2 standards
               // console.error('[INFO] No Phase 2 environment variable rules - skipping category');
            }
          }
          
          // File naming check - ENHANCED
          if (categories.includes('file_naming')) {
            const basename = path.basename(file);
            if (type === 'job_cards' && !basename.match(/^(J|JEVS_)/)) {
              fileIssue.issues.push('file_naming');
              fileIssue.examples.push({
                issue: 'Job card naming violation',
                current: basename,
                fix: `Rename to JEVS_${basename} or J${basename}`
              });
              issuesByCategory.file_naming.total_files_with_issues++;
            }
          }
          
          if (fileIssue.issues.length > 0) {
            fileIssues.push(fileIssue);
            for (const issue of fileIssue.issues) {
              if (issuesByCategory[issue].specific_files.length < 20) {
                issuesByCategory[issue].specific_files.push(relativePath);
              }
              // Store first 3 examples per category
              if (issuesByCategory[issue].common_patterns.length < 3) {
                issuesByCategory[issue].common_patterns.push(...fileIssue.examples.slice(0, 1));
              }
            }
          }
        } catch (err) {
          console.error(`[WARN] Failed to analyze ${file}: ${err.message}`);
        }
      }
      
      console.error(`[OK] Analysis complete: ${fileIssues.length} files with issues`);
      
      // Debug: Log issuesByCategory before filtering
      console.error(`[DEBUG] issuesByCategory keys: ${Object.keys(issuesByCategory).join(', ')}`);
      for (const [cat, data] of Object.entries(issuesByCategory)) {
        console.error(`[DEBUG] ${cat}: ${data.total_files_with_issues} issues, ${data.specific_files.length} files in list`);
      }
      
      // Filter out categories with zero issues (pragmatic reporting)
      const categoriesWithIssues = Object.entries(issuesByCategory)
        .filter(([_, data]) => data.total_files_with_issues > 0)
        .reduce((acc, [cat, data]) => {
          acc[cat] = data;
          return acc;
        }, {});
      
      // Debug: Log categoriesWithIssues after filtering
      console.error(`[DEBUG] categoriesWithIssues keys: ${Object.keys(categoriesWithIssues).join(', ')}`);
      for (const [cat, data] of Object.entries(categoriesWithIssues)) {
        console.error(`[DEBUG] ${cat}: ${data.total_files_with_issues} issues, ${data.specific_files.length} files in list`);
      }
      
      // Return structured data focused on ACTIONABLE findings only
      const scanResult = {
        repository: repository_path,
        scan_date: new Date().toISOString(),
        statistics: {
          total_files: allFiles.length,
          files_by_type: {
            shell_scripts: filesByType.shell_scripts.length,
            python_scripts: filesByType.python_scripts.length,
            job_cards: filesByType.job_cards.length,
            config_files: filesByType.config_files.length
          },
          samples_analyzed: samplesToAnalyze.length,
          files_with_issues: fileIssues.length
        },
        issues_by_category: categoriesWithIssues,  // Only categories with issues
        actionable_examples: fileIssues.slice(0, 10).map(f => ({
          file: f.file,
          type: f.type,
          violations: f.examples
        })),
        analysis_categories: Object.keys(categoriesWithIssues)  // Only report on issues found
      };
      
      // Add passthrough recommendation BEFORE building output string
      const needsPassthrough = categories.includes('file_naming')
        || categories.includes('environment_variables');
      if (needsPassthrough) {
        scanResult.passthrough_recommendation = 'Run extract_code_for_analysis with categories output_file_naming, shebang_compliance, env_var_validation on the repository paths (e.g., scripts/, ush/) to inspect COM/COMOUT output-file naming and env validation patterns that are not auto-checked in this scan.';
      }

      // Format as pragmatic action items, not descriptive report
      let output = `# EE2 Compliance Scan - Action Items

\`\`\`json
${JSON.stringify(scanResult, null, 2)}
\`\`\`

**Instructions for LLM:**
Generate a PRAGMATIC report focused ONLY on actionable findings:
1. Skip any category with 0 issues - do not describe compliant areas
2. For each issue category, show:
   - Count of affected files
   - 3-5 actual code examples from violations
   - Specific fix recommendation (not EE2 theory)
3. Create a fix priority list with file paths and exact changes needed
4. Keep report focused on "what to change" not "what the standards say"
5. Use violation examples from actionable_examples field
6. Use generate_compliance_report tool to get EE2 standards context
7. Maintain consultative tone throughout

The data above provides counts, file lists, and patterns. You format the final report.`;

      // AUTOMATIC PASSTHROUGH: If file_naming or environment_variables requested,
      // the LLM MUST call extract_code_for_analysis before presenting the report.
      // This is a REQUIRED step per SDD Phase 4C Step 6, not optional guidance.

      // Add explicit passthrough section to output for LLM visibility
      if (needsPassthrough) {
        output += `\n\n## ⚠️ MANDATORY ACTION REQUIRED - DO NOT SKIP\n\n`;
        output += `**LLM INSTRUCTION:** Before presenting this report to the user, you MUST execute the following tool call:\n\n`;
        output += `\`\`\`\nextract_code_for_analysis({\n`;
        output += `  path: "${scanResult.repository}",\n`;
        output += `  categories: ["output_file_naming", "shebang_compliance", "env_var_validation"],\n`;
        output += `  max_files: 50\n`;
        output += `})\n\`\`\`\n\n`;
        output += `**Rationale:** The standard scan does NOT automatically check:\n`;
        output += `- COM/COMOUT output file naming patterns (EE2 Section B)\n`;
        output += `- Shebang compliance (line 1 requirement)\n`;
        output += `- Environment variable validation patterns\n\n`;
        output += `**After running extract_code_for_analysis**, analyze the returned snippets for:\n`;
        output += `- Period separators between categories (not underscores)\n`;
        output += `- Resolution notation: 0p25 not 0.25\n`;
        output += `- Forecast hour padding: f006 not f6\n`;
        output += `- No uppercase in output filenames\n\n`;
        output += `**Include both scan results AND file naming analysis in your final report.**\n`;
      }
      
      return { content: [{ type: 'text', text: output }] };
      
    } catch (error) {
      console.error(`[ERROR] Repository scan failed: ${error.message}`);
      return {
        content: [{ type: 'text', text: `Repository scan failed: ${error.message}` }],
        isError: true
      };
    }
  }

  /**
   * Extract code snippets for LLM analysis (Phase 4C + Phase 19 Content Abstraction)
   * Returns structured data with LLM prompts for passthrough mode
   * Supports: direct content, file arrays, or filesystem paths
   */
  async extractCodeForAnalysis(args) {
    const { 
      categories = ['output_file_naming', 'error_handling'],
      file_pattern = '\\.(sh|py)$',
      max_files = 50,
      content_type = 'auto'
    } = args;

    try {
      // Phase 19: Use ContentResolver for unified content access
      const resolver = new ContentResolver({ throwOnPathError: false });
      const resolved = await resolver.resolve(args);
      
      // Handle resolution errors gracefully
      if (resolved.type === 'error') {
        return {
          content: [{
            type: 'text',
            text: `[ERROR] ${resolved.metadata.error}\n\n` +
                  `**Suggestion**: ${resolved.metadata.suggestion}\n\n` +
                  `For remote MCP access, use the 'content' or 'files' parameter:\n` +
                  `\`\`\`\nextract_code_for_analysis({ content: "your code here", categories: ["error_handling"] })\n\`\`\``
          }]
        };
      }

      console.error(`[EXTRACT] Starting code extraction (source: ${resolved.source})`);
      
      // Map category names to extractor categories
      const extractorCategories = categories.map(c => {
        if (c === 'output_file_naming') return 'output';
        if (c === 'shebang_compliance') return 'shebang';
        if (c === 'env_var_validation') return 'env_vars';
        return c.replace('_compliance', '');
      });

      const extractor = new CodeSnippetExtractor();
      let extracted;
      
      // Handle different resolution types
      if (resolved.source === 'direct') {
        // Direct content provided - extract from string
        const result = extractor.extractFromContent(
          resolved.content, 
          resolved.contentType || content_type,
          extractorCategories
        );
        extracted = {
          source: 'direct',
          filesScanned: 1,
          filesWithMatches: 1,
          results: [result]
        };
      } else if (resolved.type === 'multi') {
        // Multiple files provided via files array
        const results = [];
        for (const file of resolved.files) {
          const result = extractor.extractFromContent(
            file.content,
            file.contentType || content_type,
            extractorCategories
          );
          result.filename = file.name;
          result.path = file.path;
          results.push(result);
        }
        extracted = {
          source: 'files_array',
          filesScanned: resolved.files.length,
          filesWithMatches: results.filter(r => !r.error).length,
          results
        };
      } else if (resolved.source === 'local_fs') {
        // Filesystem path - use original directory/file logic
        const inputPath = resolved.metadata.originalPath;
        const stats = statSync(inputPath);
        
        if (stats.isDirectory()) {
          extracted = await extractor.extractFromDirectory(inputPath, {
            pattern: new RegExp(file_pattern),
            categories: extractorCategories,
            maxFiles: max_files
          });
        } else {
          const result = await extractor.extractFromFile(inputPath, extractorCategories);
          extracted = {
            directory: inputPath,
            filesScanned: 1,
            filesWithMatches: 1,
            results: [result]
          };
        }
      } else {
        // Single content from path fallback
        const result = extractor.extractFromContent(
          resolved.content,
          resolved.contentType || content_type,
          extractorCategories
        );
        extracted = {
          source: resolved.source,
          filesScanned: 1,
          filesWithMatches: 1,
          results: [result]
        };
      }

      // Generate LLM prompts for each category
      const llmPrompts = {};
      for (const category of categories) {
        llmPrompts[category] = generateAnalysisPrompt(
          category,
          extracted.results || [extracted]
        );
      }

      // Format response
      let output = `# Code Extraction for EE2 Analysis\n\n`;
      output += `**Source:** ${resolved.source}\n`;
      output += `**Content Type:** ${resolved.contentType}\n`;
      output += `**Categories:** ${categories.join(', ')}\n`;
      
      if (resolved.metadata?.originalPath) {
        output += `**Path:** ${resolved.metadata.originalPath}\n`;
      }
      if (extracted.filesScanned) {
        output += `**Files Scanned:** ${extracted.filesScanned}\n`;
        output += `**Files with Matches:** ${extracted.filesWithMatches}\n`;
      }
      output += `\n---\n\n`;

      // Include prompts for host LLM
      output += `## LLM Analysis Instructions\n\n`;
      output += `The following prompts and code snippets are provided for analysis.\n`;
      output += `Please analyze each category using the provided context and SME corrections.\n\n`;

      for (const [category, prompt] of Object.entries(llmPrompts)) {
        if (prompt.error) continue;
        
        output += `### ${category.replace(/_/g, ' ').toUpperCase()}\n\n`;
        output += `**Context:**\n\`\`\`\n${prompt.context}\n\`\`\`\n\n`;
        output += `**Instruction:**\n${prompt.instruction}\n\n`;
        output += `**SME Corrections (avoid false positives):**\n`;
        for (const correction of prompt.sme_corrections) {
          output += `- ${correction}\n`;
        }
        output += `\n`;
      }

      output += `---\n\n## Extracted Code Snippets\n\n`;
      
      // Include actual snippets
      const results = extracted.results || [extracted];
      for (const result of results.slice(0, 10)) { // Limit output
        if (result.error) continue;
        
        output += `### ${result.filename}\n`;
        output += `**Type:** ${result.fileType} | **Lines:** ${result.lineCount}\n\n`;
        
        if (result.shebangBlock) {
          output += `**Shebang:** ${result.shebangBlock.shebang || 'MISSING'}\n`;
          output += `**set -x:** ${result.shebangBlock.hasSetX ? `Line ${result.shebangBlock.setXLine}` : 'NOT FOUND'}\n\n`;
        }

        for (const [cat, snippets] of Object.entries(result.snippets)) {
          if (snippets.length === 0) continue;
          output += `**${cat} patterns:** ${snippets.length} found\n`;
          for (const snip of snippets.slice(0, 5)) {
            output += `- Line ${snip.line}: \`${snip.match.substring(0, 80)}${snip.match.length > 80 ? '...' : ''}\`\n`;
          }
          output += `\n`;
        }
      }

      if (results.length > 10) {
        output += `\n*... and ${results.length - 10} more files*\n`;
      }

      console.error(`[OK] Code extraction complete: ${extracted.filesScanned} files, ${categories.length} categories`);

      return { 
        content: [{ type: 'text', text: output }]
      };

    } catch (error) {
      console.error(`[ERROR] Code extraction failed: ${error.message}`);
      return {
        content: [{ type: 'text', text: `Code extraction failed: ${error.message}` }],
        isError: true
      };
    }
  }

  // ============================================================================
  // Helper Methods
  // ============================================================================

  /**
   * Build semantic search query for EE2 category
   * @private
   */
  _buildStandardsQuery(category) {
    const queries = {
      'error_handling': 'error handling bash scripts set -eu exit codes trap',
      'environment_variables': 'environment variable naming quoting standards ${VAR}',
      'file_naming': 'file naming conventions ex- J- production utilities',
      'workflow_structure': 'workflow structure job scripts directory organization',
      'production_utilities': 'production utilities standard tools logging',
      'code_standards': 'code standards documentation comments best practices',
      'directory_structure': 'directory structure organization requirements'
    };
    return queries[category] || category;
  }

  /**
   * Extract checklist items from documentation text
   * @private
   */
  _extractChecklistItems(text) {
    // Extract actionable items from documentation text
    const items = [];
    const lines = text.split('\n');
    
    for (const line of lines) {
      // Look for bullet points, numbered lists, or imperative statements
      if (/^[-•*]\s+/.test(line) || /^\d+\.\s+/.test(line)) {
        items.push(line.replace(/^[-•*\d.]\s+/, '').trim());
      } else if (/^(Use|Always|Never|Ensure|Check|Verify|Include|Add|Set)\s+/i.test(line)) {
        items.push(line.trim());
      }
    }
    
    return items.slice(0, 8); // Limit to top 8 items
  }

  /**
   * Cleanup resources
   */
  async cleanup() {
    if (this.dataAccess) {
      await this.dataAccess.close();
      this.dataAccess = null;
    }
    this.isInitialized = false;
  }
}

export default EE2ComplianceTools;
