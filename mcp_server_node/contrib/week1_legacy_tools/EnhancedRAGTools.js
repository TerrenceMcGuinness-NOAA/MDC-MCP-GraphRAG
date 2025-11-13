#!/usr/bin/env node

/**
 * Enhanced RAG Tools Module - Multi-Source Knowledge Retrieval
 *
 * Advanced RAG tools that leverage the enhanced vector store with multiple knowledge sources:
 * - Local repository documentation and code
 * - External documentation (UFS, Rocoto, GSI, HPC systems, etc.)
 * - EE2 compliance standards and policies
 * - GitHub ecosystem knowledge
 *
 * Features:
 * - Intelligent source routing based on query analysis
 * - Source attribution and provenance tracking
 * - Multi-modal search (semantic + keyword + category)
 * - Quality-based result ranking and filtering
 * - Comprehensive explanations with external context
 *
 * @version 1.0.0
 * @author NOAA EMC Global Workflow Team
 */

import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';
import { EnhancedVectorStore } from '../rag/EnhancedVectorStore.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export class EnhancedRAGTools {
  constructor(knowledgeBasePath) {
    this.knowledgeBasePath = knowledgeBasePath || this.findKnowledgeBase();

    // Initialize enhanced vector store
    this.vectorStore = new EnhancedVectorStore({
      knowledgeBasePath: this.knowledgeBasePath,
      enableExternalSources: true
    });

    this.isInitialized = false;

    this.stats = {
      totalQueries: 0,
      queriesBySource: {},
      averageResponseTime: 0,
      lastQuery: null
    };
  }

  /**
   * Find knowledge base directory
   */
  findKnowledgeBase() {
    const currentDir = path.dirname(path.dirname(__dirname));
    return path.join(currentDir, 'knowledge-base');
  }

  /**
   * Initialize Enhanced RAG components
   */
  async initialize() {
    if (this.isInitialized) return;

    console.error('🔄 Initializing Enhanced RAG Tools...');

    await this.vectorStore.initialize();

    this.isInitialized = true;
    console.error('✅ Enhanced RAG Tools initialized');

    // Log knowledge base statistics
    const stats = this.vectorStore.getStats();
    console.error(`📊 Knowledge Base: ${stats.total_chunks?.toLocaleString() || 'Unknown'} chunks from ${stats.totalSources || 0} sources`);
  }

  /**
   * Register Enhanced RAG tools with server
   */
  registerWith(server) {
    // Enhanced search with source selection
    server.registerTool(
      'search_documentation',
      'Semantic search across all workflow documentation sources with intelligent routing',
      {
        type: 'object',
        properties: {
          query: {
            type: 'string',
            description: 'Search query for documentation'
          },
          sources: {
            type: 'array',
            items: {
              type: 'string',
              enum: ['all', 'local', 'external', 'ee2', 'standards']
            },
            description: 'Knowledge sources to search (default: intelligent routing)',
            default: ['all']
          },
          categories: {
            type: 'array',
            items: {
              type: 'string'
            },
            description: 'Specific categories to filter (e.g., "ufs", "rocoto", "gsi")',
            default: []
          },
          max_results: {
            type: 'number',
            description: 'Maximum number of results to return',
            default: 8,
            minimum: 1,
            maximum: 20
          },
          min_quality_score: {
            type: 'number',
            description: 'Minimum quality threshold (0.0-1.0)',
            default: 0.3,
            minimum: 0.0,
            maximum: 1.0
          },
          include_attribution: {
            type: 'boolean',
            description: 'Include source attribution and metadata',
            default: true
          }
        },
        required: ['query']
      },
      this.searchDocumentation.bind(this)
    );

    // Enhanced contextual explanations
    server.registerTool(
      'explain_with_context',
      'Provide comprehensive explanations using multi-source knowledge base',
      {
        type: 'object',
        properties: {
          topic: {
            type: 'string',
            description: 'Topic or component to explain'
          },
          context_type: {
            type: 'string',
            description: 'Type of context to include',
            enum: ['technical', 'operational', 'configuration', 'comprehensive'],
            default: 'comprehensive'
          },
          detail_level: {
            type: 'string',
            description: 'Level of explanation detail',
            enum: ['basic', 'intermediate', 'advanced'],
            default: 'intermediate'
          },
          include_examples: {
            type: 'boolean',
            description: 'Include practical examples and use cases',
            default: true
          },
          focus_sources: {
            type: 'array',
            items: {
              type: 'string'
            },
            description: 'Prioritize specific knowledge sources',
            default: []
          }
        },
        required: ['topic']
      },
      this.explainWithContext.bind(this)
    );

    // Multi-source code pattern discovery
    server.registerTool(
      'find_similar_code',
      'Find similar code patterns across all knowledge sources',
      {
        type: 'object',
        properties: {
          code_pattern: {
            type: 'string',
            description: 'Code pattern or function to find similar examples of'
          },
          file_types: {
            type: 'array',
            items: {
              type: 'string'
            },
            description: 'File types to search in (sh, py, yaml, etc.)',
            default: ['sh', 'py', 'yaml', 'json']
          },
          similarity_threshold: {
            type: 'number',
            description: 'Minimum similarity score (0.0-1.0)',
            default: 0.4,
            minimum: 0.0,
            maximum: 1.0
          },
          include_external: {
            type: 'boolean',
            description: 'Include external documentation sources',
            default: true
          },
          max_results: {
            type: 'number',
            description: 'Maximum similar patterns to return',
            default: 10,
            minimum: 1,
            maximum: 25
          }
        },
        required: ['code_pattern']
      },
      this.findSimilarCode.bind(this)
    );

    // Enhanced operational guidance with external sources
    server.registerTool(
      'get_operational_guidance',
      'Get comprehensive operational procedures from authoritative sources',
      {
        type: 'object',
        properties: {
          operation: {
            type: 'string',
            description: 'Operation or procedure to get guidance for'
          },
          platform: {
            type: 'string',
            description: 'HPC platform context',
            enum: ['hera', 'hercules', 'orion', 'wcoss2', 'gaea', 'generic'],
            default: 'generic'
          },
          urgency: {
            type: 'string',
            description: 'Operational urgency level',
            enum: ['routine', 'urgent', 'emergency'],
            default: 'routine'
          },
          include_external_docs: {
            type: 'boolean',
            description: 'Include external HPC and system documentation',
            default: true
          }
        },
        required: ['operation']
      },
      this.getOperationalGuidance.bind(this)
    );

    // Knowledge source health and statistics
    server.registerTool(
      'get_knowledge_base_status',
      'Get comprehensive status and health of all knowledge sources',
      {
        type: 'object',
        properties: {
          include_detailed_stats: {
            type: 'boolean',
            description: 'Include detailed statistics for each source',
            default: false
          },
          check_source_health: {
            type: 'boolean',
            description: 'Check health status of external sources',
            default: true
          }
        }
      },
      this.getKnowledgeBaseStatus.bind(this)
    );

    // List all ingested URLs with source information
    server.registerTool(
      'list_ingested_urls',
      'List all URLs that have been ingested as embeddings in the knowledge base',
      {
        type: 'object',
        properties: {
          format: {
            type: 'string',
            description: 'Output format',
            enum: ['detailed', 'summary'],
            default: 'detailed'
          },
          category_filter: {
            type: 'string',
            description: 'Filter URLs by category (e.g., "ufs", "rocoto", "gsi")',
            default: null
          }
        }
      },
      this.listIngestedURLs.bind(this)
    );

    // Retrieve specific URL content from knowledge base
    server.registerTool(
      'retrieve_url_content',
      'Retrieve and display content from a specific URL that was ingested into the knowledge base',
      {
        type: 'object',
        properties: {
          url: {
            type: 'string',
            description: 'The URL to retrieve content for',
          },
          include_chunks: {
            type: 'boolean',
            description: 'Include content chunks in the response',
            default: true
          },
          include_metadata: {
            type: 'boolean',
            description: 'Include metadata about the URL',
            default: true
          },
          max_chunks: {
            type: 'number',
            description: 'Maximum number of content chunks to return',
            default: 10,
            minimum: 1,
            maximum: 50
          }
        },
        required: ['url']
      },
      this.retrieveURLContent.bind(this)
    );

    // Get URLs as structured data
    server.registerTool(
      'get_ingested_urls_array',
      'Get all ingested URLs as structured data for programmatic access',
      {
        type: 'object',
        properties: {}
      },
      this.getIngestedURLsArray.bind(this)
    );

    // All existing EE2 compliance tools (inherited functionality)
    this.registerEE2Tools(server);
  }

  /**
   * Register EE2 compliance tools (delegated to vector store)
   */
  registerEE2Tools(server) {
    server.registerTool(
      'analyze_ee2_compliance',
      'Analyze code or documentation for EE2 compliance using comprehensive standards',
      {
        type: 'object',
        properties: {
          content: {
            type: 'string',
            description: 'Code or documentation content to analyze'
          },
          analysis_type: {
            type: 'string',
            description: 'Type of compliance analysis',
            enum: ['environment_variables', 'workflow_structure', 'error_handling', 'file_naming', 'production_utilities', 'code_standards', 'directory_structure', 'comprehensive'],
            default: 'comprehensive'
          },
          include_recommendations: {
            type: 'boolean',
            description: 'Include improvement recommendations',
            default: true
          },
          include_external_standards: {
            type: 'boolean',
            description: 'Include external compliance standards in analysis',
            default: true
          }
        },
        required: ['content']
      },
      this.analyzeEE2Compliance.bind(this)
    );

    server.registerTool(
      'search_ee2_standards',
      'Search comprehensive EE2 compliance standards from all sources',
      {
        type: 'object',
        properties: {
          query: {
            type: 'string',
            description: 'Search query for EE2 standards'
          },
          category: {
            type: 'string',
            description: 'Specific compliance category',
            enum: ['environment_variables', 'workflow_structure', 'error_handling', 'file_naming', 'production_utilities', 'code_standards', 'directory_structure'],
            default: null
          },
          include_examples: {
            type: 'boolean',
            description: 'Include code examples in results',
            default: true
          },
          include_external_standards: {
            type: 'boolean',
            description: 'Include external standards documentation',
            default: true
          },
          max_results: {
            type: 'number',
            description: 'Maximum results to return',
            default: 8,
            minimum: 1,
            maximum: 20
          }
        },
        required: ['query']
      },
      this.searchEE2Standards.bind(this)
    );

    server.registerTool(
      'generate_compliance_report',
      'Generate comprehensive EE2 compliance report using all knowledge sources',
      {
        type: 'object',
        properties: {
          scope: {
            type: 'string',
            description: 'Scope of compliance report',
            enum: ['summary', 'detailed', 'checklist'],
            default: 'summary'
          },
          categories: {
            type: 'array',
            items: {
              type: 'string',
              enum: ['environment_variables', 'workflow_structure', 'error_handling', 'file_naming', 'production_utilities', 'code_standards', 'directory_structure']
            },
            description: 'Specific categories to include',
            default: []
          },
          format: {
            type: 'string',
            description: 'Report format',
            enum: ['markdown', 'checklist', 'summary'],
            default: 'markdown'
          },
          include_external_references: {
            type: 'boolean',
            description: 'Include references to external compliance documentation',
            default: true
          }
        }
      },
      this.generateComplianceReport.bind(this)
    );
  }

  /**
   * Enhanced semantic search across all knowledge sources
   */
  async searchDocumentation(args) {
    await this.initialize();

    const startTime = Date.now();
    this.stats.totalQueries++;
    this.stats.lastQuery = new Date().toISOString();

    const {
      query,
      sources = ['all'],
      categories = [],
      max_results = 8,
      min_quality_score = 0.3,
      include_attribution = true
    } = args;

    try {
      const results = await this.vectorStore.searchWithAttribution(query, {
        sources,
        categories,
        maxResults: max_results,
        minQualityScore: min_quality_score,
        includeMetadata: include_attribution
      });

      // Track query statistics
      const responseTime = Date.now() - startTime;
      this.stats.averageResponseTime =
        (this.stats.averageResponseTime * (this.stats.totalQueries - 1) + responseTime) / this.stats.totalQueries;

      // Track queries by source
      results.forEach(result => {
        const sourceType = result.source_type || 'unknown';
        this.stats.queriesBySource[sourceType] = (this.stats.queriesBySource[sourceType] || 0) + 1;
      });

      if (results.length === 0) {
        return `No documentation found for query: "${query}"\n\nSuggestions:\n- Try broader search terms\n- Check spelling and terminology\n- Use alternative keywords or synonyms\n- Remove category filters if applied`;
      }

      return this.formatEnhancedSearchResults(results, query, {
        searchTime: responseTime,
        totalSources: this.vectorStore.stats.totalSources,
        includeAttribution: include_attribution
      });

    } catch (error) {
      console.error(`Enhanced search error for "${query}":`, error.message);
      return `Search error: ${error.message}`;
    }
  }

  /**
   * Enhanced contextual explanations using multi-source knowledge
   */
  async explainWithContext(args) {
    await this.initialize();

    const {
      topic,
      context_type = 'comprehensive',
      detail_level = 'intermediate',
      include_examples = true,
      focus_sources = []
    } = args;

    try {
      // Gather context from multiple sources
      const contexts = await this.gatherMultiSourceContext(topic, {
        contextType: context_type,
        focusSources: focus_sources,
        maxResultsPerSource: 5
      });

      // Generate comprehensive explanation
      let explanation = `# ${topic}\n\n`;

      // Add overview section
      if (contexts.overview.length > 0) {
        explanation += `## Overview\n`;
        explanation += this.synthesizeOverview(contexts.overview, detail_level);
        explanation += '\n\n';
      }

      // Add technical details
      if (context_type === 'technical' || context_type === 'comprehensive') {
        if (contexts.technical.length > 0) {
          explanation += `## Technical Information\n`;
          explanation += this.synthesizeTechnicalContent(contexts.technical, detail_level);
          explanation += '\n\n';
        }
      }

      // Add operational context
      if (context_type === 'operational' || context_type === 'comprehensive') {
        if (contexts.operational.length > 0) {
          explanation += `## Operational Context\n`;
          explanation += this.synthesizeOperationalContent(contexts.operational, detail_level);
          explanation += '\n\n';
        }
      }

      // Add configuration information
      if (context_type === 'configuration' || context_type === 'comprehensive') {
        if (contexts.configuration.length > 0) {
          explanation += `## Configuration\n`;
          explanation += this.synthesizeConfigurationContent(contexts.configuration, detail_level);
          explanation += '\n\n';
        }
      }

      // Add examples
      if (include_examples && contexts.examples.length > 0) {
        explanation += `## Examples and Usage\n`;
        explanation += this.synthesizeExamples(contexts.examples, detail_level);
        explanation += '\n\n';
      }

      // Add external resources
      const externalRefs = this.extractExternalReferences(contexts);
      if (externalRefs.length > 0) {
        explanation += `## External Resources\n`;
        externalRefs.forEach(ref => {
          explanation += `- [${ref.title}](${ref.url}) - ${ref.description}\n`;
        });
        explanation += '\n';
      }

      // Add source attribution
      const allSources = this.extractUniqueSources(contexts);
      if (allSources.length > 0) {
        explanation += `## Sources\n`;
        explanation += `*Information gathered from ${allSources.length} authoritative sources including `;
        explanation += `${allSources.slice(0, 3).map(s => s.type).join(', ')}`;
        if (allSources.length > 3) {
          explanation += ` and ${allSources.length - 3} others`;
        }
        explanation += '.*\n';
      }

      return explanation;

    } catch (error) {
      console.error(`Contextual explanation error for "${topic}":`, error.message);
      return `Error generating explanation for "${topic}": ${error.message}`;
    }
  }

  /**
   * Enhanced code pattern discovery across all sources
   */
  async findSimilarCode(args) {
    await this.initialize();

    const {
      code_pattern,
      file_types = ['sh', 'py', 'yaml', 'json'],
      similarity_threshold = 0.4,
      include_external = true,
      max_results = 10
    } = args;

    try {
      const sources = include_external ? ['local', 'external'] : ['local'];

      const results = await this.vectorStore.searchDocumentation(code_pattern, {
        sources,
        maxResults: max_results * 2, // Get extra to filter
        minQualityScore: 0.2 // Lower threshold for code
      });

      // Filter for code content and file types
      const codeResults = results.filter(result => {
        const source = result.metadata?.source || '';
        const hasCodeContent = /```|function|class|def |#!/.test(result.content);
        const matchesFileType = file_types.some(ext => source.endsWith(`.${ext}`));

        return hasCodeContent || matchesFileType;
      }).slice(0, max_results);

      if (codeResults.length === 0) {
        return `No similar code patterns found for: "${code_pattern}"\n\n` +
               `Searched in file types: ${file_types.join(', ')}\n` +
               `Try:\n- Using more general terms\n- Including more file types\n- Lowering similarity threshold`;
      }

      return this.formatCodeResults(codeResults, code_pattern, {
        fileTypes: file_types,
        includeExternal: include_external,
        threshold: similarity_threshold
      });

    } catch (error) {
      console.error(`Code search error for "${code_pattern}":`, error.message);
      return `Code search error: ${error.message}`;
    }
  }

  /**
   * Enhanced operational guidance with authoritative external sources
   */
  async getOperationalGuidance(args) {
    await this.initialize();

    const {
      operation,
      platform = 'generic',
      urgency = 'routine',
      include_external_docs = true
    } = args;

    try {
      // Search for operational documentation
      const sources = include_external_docs ? ['local', 'external'] : ['local'];
      const guidanceQuery = `${operation} ${platform} operational procedure installation setup configuration`;

      const results = await this.vectorStore.searchDocumentation(guidanceQuery, {
        sources,
        categories: ['external.hpc_systems', 'standards_and_policies', 'internal'],
        maxResults: 12,
        minQualityScore: 0.25
      });

      // Format comprehensive guidance
      let guidance = `# Operational Guidance: ${operation}\n\n`;
      guidance += `**Platform**: ${platform}\n`;
      guidance += `**Urgency**: ${urgency}\n`;
      if (urgency === 'emergency') {
        guidance += `**🚨 EMERGENCY PROCEDURES - Contact operations team immediately**\n`;
      }
      guidance += '\n';

      // Add relevant documentation
      if (results.length > 0) {
        guidance += `## Relevant Documentation\n\n`;

        const organizedResults = this.organizeOperationalResults(results);

        if (organizedResults.official.length > 0) {
          guidance += `### Official Documentation\n`;
          organizedResults.official.forEach(result => {
            guidance += `- **${this.extractTitle(result)}**\n`;
            guidance += `  ${result.content.substring(0, 200)}...\n`;
            if (result.attribution?.source_url) {
              guidance += `  *Source: ${result.attribution.source_url}*\n`;
            }
            guidance += '\n';
          });
        }

        if (organizedResults.procedures.length > 0) {
          guidance += `### Procedures and Best Practices\n`;
          organizedResults.procedures.forEach(result => {
            guidance += `- ${result.content.substring(0, 300)}...\n`;
            guidance += '\n';
          });
        }
      }

      // Add standard procedures
      guidance += this.getStandardOperationalProcedures(operation, platform, urgency);

      // Add platform-specific guidance
      if (platform !== 'generic') {
        guidance += await this.getPlatformSpecificGuidance(platform, operation);
      }

      return guidance;

    } catch (error) {
      console.error(`Operational guidance error for "${operation}":`, error.message);
      return `Error retrieving operational guidance: ${error.message}`;
    }
  }

  /**
   * Get comprehensive knowledge base status
   */
  async getKnowledgeBaseStatus(args) {
    await this.initialize();

    const {
      include_detailed_stats = false,
      check_source_health = true
    } = args;

    try {
      const stats = this.vectorStore.getStats();
      let status = `# Knowledge Base Status Report\n\n`;
      status += `**Generated**: ${new Date().toISOString()}\n\n`;

      // Overview statistics
      status += `## Overview\n`;
      status += `- **Total Knowledge Sources**: ${stats.totalSources || 0}\n`;
      status += `- **Total Document Chunks**: ${(stats.total_chunks || 0).toLocaleString()}\n`;
      status += `- **Local Repository Chunks**: ${(stats.local_chunks || 0).toLocaleString()}\n`;
      status += `- **External Documentation Chunks**: ${(stats.externalChunks || 0).toLocaleString()}\n`;
      status += `- **EE2 Compliance Chunks**: ${(stats.ee2_chunks || 0).toLocaleString()}\n`;
      if (stats.lastExternalUpdate) {
        status += `- **Last External Update**: ${stats.lastExternalUpdate}\n`;
      }
      status += '\n';

      // Query statistics
      if (this.stats.totalQueries > 0) {
        status += `## Query Statistics\n`;
        status += `- **Total Queries**: ${this.stats.totalQueries}\n`;
        status += `- **Average Response Time**: ${this.stats.averageResponseTime.toFixed(0)}ms\n`;
        status += `- **Last Query**: ${this.stats.lastQuery}\n`;

        if (Object.keys(this.stats.queriesBySource).length > 0) {
          status += `- **Queries by Source**:\n`;
          Object.entries(this.stats.queriesBySource).forEach(([source, count]) => {
            status += `  - ${source}: ${count}\n`;
          });
        }
        status += '\n';
      }

      // Source breakdown
      if (include_detailed_stats && stats.sources) {
        status += `## Source Details\n`;
        Object.entries(stats.sources).forEach(([source, sourceStats]) => {
          status += `### ${source.charAt(0).toUpperCase() + source.slice(1)} Source\n`;
          status += `- Chunks: ${sourceStats.chunkCount?.toLocaleString() || 0}\n`;
          status += `- Avg Quality: ${(sourceStats.avgQualityScore * 100).toFixed(1)}%\n`;
          status += '\n';
        });
      }

      // Category breakdown
      if (include_detailed_stats && stats.categories) {
        status += `## Category Breakdown\n`;
        const sortedCategories = Object.entries(stats.categories)
          .sort(([,a], [,b]) => b - a);

        sortedCategories.forEach(([category, count]) => {
          status += `- **${category}**: ${count.toLocaleString()} chunks\n`;
        });
        status += '\n';
      }

      // Source health check
      if (check_source_health) {
        const healthStatus = this.vectorStore.getSourceHealth();
        status += `## Source Health\n`;

        Object.entries(healthStatus.sources).forEach(([source, health]) => {
          const emoji = health.status === 'healthy' ? '✅' :
                       health.status === 'empty' ? '⚠️' : '❌';
          status += `${emoji} **${source}**: ${health.status}\n`;

          if (include_detailed_stats) {
            status += `  - Chunks: ${health.totalChunks?.toLocaleString() || 0}\n`;
            status += `  - Quality: ${(health.avgQuality * 100).toFixed(1)}%\n`;
            status += `  - Freshness: ${(health.staleness * 100).toFixed(1)}%\n`;
          }
        });
      }

      return status;

    } catch (error) {
      console.error('Knowledge base status error:', error.message);
      return `Error retrieving knowledge base status: ${error.message}`;
    }
  }

  // EE2 compliance methods
  async analyzeEE2Compliance(args) {
    await this.initialize();
    const { content, analysis_type = 'comprehensive', include_recommendations = true } = args;

    if (!this.vectorStore) {
      return 'EE2 compliance analysis not available - vector store not initialized';
    }

    try {
      let analysis = `# EE2 Compliance Analysis\n\n`;
      analysis += `**Analysis Type**: ${analysis_type}\n`;
      analysis += `**Content Length**: ${content.length} characters\n\n`;

      // Analyze content for compliance patterns
      const complianceResults = await this.analyzeContentCompliance(content, analysis_type);

      analysis += `## Compliance Assessment\n\n`;
      analysis += complianceResults.assessment;

      if (complianceResults.violations.length > 0) {
        analysis += `\n## Compliance Issues Found\n\n`;
        complianceResults.violations.forEach((violation, index) => {
          analysis += `${index + 1}. **${violation.category}**: ${violation.description}\n`;
          if (violation.location) {
            analysis += `   - Location: ${violation.location}\n`;
          }
        });
      }

      if (include_recommendations && complianceResults.recommendations.length > 0) {
        analysis += `\n## Recommendations\n\n`;
        complianceResults.recommendations.forEach((rec, index) => {
          analysis += `${index + 1}. ${rec}\n`;
        });
      }

      // Search for relevant standards using enhanced search
      const relevantStandards = await this.vectorStore.searchSource('ee2', `${analysis_type} compliance standards`, {
        maxResults: 3
      });

      if (relevantStandards.length > 0) {
        analysis += `\n## Relevant Standards\n\n`;
        relevantStandards.forEach((standard, index) => {
          analysis += `### ${index + 1}. ${standard.metadata?.source || 'EE2 Standard'}\n`;
          analysis += `${standard.content.substring(0, 300)}...\n\n`;
        });
      }

      return analysis;
    } catch (error) {
      return `EE2 compliance analysis error: ${error.message}`;
    }
  }

  /**
   * Analyze content for compliance patterns
   */
  async analyzeContentCompliance(content, analysisType) {
    const violations = [];
    const recommendations = [];
    let assessmentScore = 100;

    // Environment Variables Analysis
    if (analysisType === 'comprehensive' || analysisType === 'environment_variables') {
      const requiredVars = ['DATAROOT', 'DATA', 'HOMEmodel', 'COMIN', 'COMOUT'];
      const foundVars = requiredVars.filter(varName =>
        content.includes(varName) || content.includes(`\${${varName}}`)
      );

      if (foundVars.length < requiredVars.length) {
        violations.push({
          category: 'Environment Variables',
          description: `Missing required variables: ${requiredVars.filter(v => !foundVars.includes(v)).join(', ')}`,
          severity: 'high'
        });
        assessmentScore -= 20;
      }
    }

    // Error Handling Analysis
    if (analysisType === 'comprehensive' || analysisType === 'error_handling') {
      const errorHandlers = ['err_chk', 'err_exit', 'prep_step'];
      const hasErrorHandling = errorHandlers.some(handler => content.includes(handler));

      if (!hasErrorHandling && content.length > 500) {
        violations.push({
          category: 'Error Handling',
          description: 'No standard error handling functions found (err_chk, err_exit, prep_step)',
          severity: 'high'
        });
        assessmentScore -= 25;
        recommendations.push('Add proper error handling using err_chk and err_exit functions');
      }
    }

    // File Naming Analysis
    if (analysisType === 'comprehensive' || analysisType === 'file_naming') {
      if (content.includes('#!/') && !content.match(/^#!/m)) {
        violations.push({
          category: 'File Naming',
          description: 'Script should start with proper shebang line',
          severity: 'medium'
        });
        assessmentScore -= 10;
      }
    }

    // Generate assessment
    let assessment;
    if (assessmentScore >= 90) {
      assessment = '✅ **EXCELLENT COMPLIANCE** - Code follows EE2 standards very well.';
    } else if (assessmentScore >= 70) {
      assessment = '✅ **GOOD COMPLIANCE** - Code mostly follows EE2 standards with minor issues.';
    } else if (assessmentScore >= 50) {
      assessment = '⚠️ **MODERATE COMPLIANCE** - Code has several compliance issues that should be addressed.';
    } else {
      assessment = '❌ **POOR COMPLIANCE** - Code has significant compliance issues requiring immediate attention.';
    }

    assessment += `\n\n**Compliance Score**: ${assessmentScore}/100`;

    return {
      violations,
      recommendations,
      assessmentScore,
      assessment
    };
  }

  async searchEE2Standards(args) {
    await this.initialize();
    const { query, category = null, include_examples = true, max_results = 8 } = args;

    if (!this.vectorStore) {
      return 'EE2 standards search not available - vector store not initialized';
    }

    try {
      const searchOptions = {
        maxResults: max_results,
        categories: category ? [category] : [],
        sources: ['ee2'],
        includeMetadata: include_examples
      };

      const results = await this.vectorStore.searchDocumentation(query, searchOptions);

      if (results.length === 0) {
        return `No EE2 standards found for query: "${query}"`;
      }

      let response = `# EE2 Standards Search Results\n\n`;
      response += `**Query**: ${query}\n`;
      if (category) {
        response += `**Category**: ${category}\n`;
      }
      response += `**Found ${results.length} results**\n\n`;

      results.forEach((result, index) => {
        response += `## ${index + 1}. ${result.metadata?.title || result.metadata?.source || 'EE2 Standard'}\n\n`;
        response += `${result.content}\n\n`;

        if (result.metadata?.category) {
          response += `**Category**: ${result.metadata.category}\n`;
        }
        if (result.relevance_score) {
          response += `**Relevance**: ${Math.round(result.relevance_score * 100)}%\n`;
        }
        response += `---\n\n`;
      });

      return response;
    } catch (error) {
      return `EE2 standards search error: ${error.message}`;
    }
  }

  async generateComplianceReport(args) {
    await this.initialize();
    return await this.vectorStore.generateComplianceReport(args);
  }

  // Helper methods for content synthesis and formatting

  async gatherMultiSourceContext(topic, options) {
    const contexts = {
      overview: [],
      technical: [],
      operational: [],
      configuration: [],
      examples: []
    };

    // Search different aspects of the topic
    const searchQueries = [
      `${topic} overview introduction`,
      `${topic} technical implementation`,
      `${topic} operational procedures`,
      `${topic} configuration setup`,
      `${topic} example usage tutorial`
    ];

    const sources = options.focusSources.length > 0 ? options.focusSources : ['all'];

    for (let i = 0; i < searchQueries.length; i++) {
      try {
        const results = await this.vectorStore.searchDocumentation(searchQueries[i], {
          sources,
          maxResults: options.maxResultsPerSource || 5,
          minQualityScore: 0.4
        });

        const contextType = Object.keys(contexts)[i];
        contexts[contextType] = results;
      } catch (error) {
        console.warn(`Context gathering failed for ${searchQueries[i]}:`, error.message);
      }
    }

    return contexts;
  }

  synthesizeOverview(overviewResults, detailLevel) {
    if (overviewResults.length === 0) return 'No overview information available.';

    const content = overviewResults
      .slice(0, detailLevel === 'basic' ? 1 : 3)
      .map(result => result.content.substring(0, 400))
      .join('\n\n');

    return content + (content.length > 800 ? '...' : '');
  }

  synthesizeTechnicalContent(technicalResults, detailLevel) {
    if (technicalResults.length === 0) return 'No technical information available.';

    const maxResults = detailLevel === 'basic' ? 1 : detailLevel === 'advanced' ? 4 : 2;
    return technicalResults
      .slice(0, maxResults)
      .map(result => result.content.substring(0, 500))
      .join('\n\n');
  }

  synthesizeOperationalContent(operationalResults, detailLevel) {
    if (operationalResults.length === 0) return 'No operational information available.';

    return operationalResults
      .slice(0, 2)
      .map(result => result.content.substring(0, 400))
      .join('\n\n');
  }

  synthesizeConfigurationContent(configResults, detailLevel) {
    if (configResults.length === 0) return 'No configuration information available.';

    return configResults
      .slice(0, 2)
      .map(result => result.content.substring(0, 300))
      .join('\n\n');
  }

  synthesizeExamples(exampleResults, detailLevel) {
    if (exampleResults.length === 0) return 'No examples available.';

    return exampleResults
      .slice(0, detailLevel === 'basic' ? 1 : 2)
      .map((result, index) => `### Example ${index + 1}\n${result.content.substring(0, 400)}`)
      .join('\n\n');
  }

  extractExternalReferences(contexts) {
    const refs = [];
    const allResults = Object.values(contexts).flat();

    allResults.forEach(result => {
      if (result.attribution?.source_url && result.attribution.source_url.startsWith('http')) {
        refs.push({
          title: result.metadata?.title || 'Documentation',
          url: result.attribution.source_url,
          description: result.attribution.category || 'External documentation'
        });
      }
    });

    // Remove duplicates
    const uniqueRefs = refs.filter((ref, index, array) =>
      array.findIndex(r => r.url === ref.url) === index
    );

    return uniqueRefs.slice(0, 5); // Limit to 5 references
  }

  extractUniqueSources(contexts) {
    const sources = new Set();
    const allResults = Object.values(contexts).flat();

    allResults.forEach(result => {
      if (result.source_type) {
        sources.add({
          type: result.source_type,
          category: result.metadata?.category || 'general'
        });
      }
    });

    return Array.from(sources);
  }

  organizeOperationalResults(results) {
    const organized = {
      official: [],
      procedures: [],
      troubleshooting: []
    };

    results.forEach(result => {
      const content = result.content.toLowerCase();
      const isOfficial = result.attribution?.category?.includes('official') ||
                        result.metadata?.source?.includes('readthedocs') ||
                        result.metadata?.source?.includes('github.io');

      const isProcedural = /procedure|step|install|setup|configure|deploy/.test(content);
      const isTroubleshooting = /error|problem|fix|troubleshoot|debug/.test(content);

      if (isOfficial) {
        organized.official.push(result);
      } else if (isTroubleshooting) {
        organized.troubleshooting.push(result);
      } else if (isProcedural) {
        organized.procedures.push(result);
      } else {
        organized.procedures.push(result); // Default to procedures
      }
    });

    return organized;
  }

  extractTitle(result) {
    return result.metadata?.title ||
           result.attribution?.source_url?.split('/').pop() ||
           'Documentation';
  }

  getStandardOperationalProcedures(operation, platform, urgency) {
    let procedures = `## Standard Procedures\n\n`;

    if (urgency === 'emergency') {
      procedures += `⚠️ **EMERGENCY PROCEDURES**\n`;
      procedures += `1. Alert operations team immediately\n`;
      procedures += `2. Document the issue with timestamps\n`;
      procedures += `3. Follow emergency contact procedures\n`;
      procedures += `4. Implement temporary workarounds if safe\n\n`;
    }

    procedures += `### General Procedure for ${operation}\n`;
    procedures += `1. **Pre-checks**: Verify system status and prerequisites\n`;
    procedures += `2. **Preparation**: Set up environment and load required modules\n`;
    procedures += `3. **Execution**: Perform the operation with monitoring\n`;
    procedures += `4. **Validation**: Verify successful completion\n`;
    procedures += `5. **Documentation**: Log actions and results\n`;
    procedures += `6. **Post-checks**: Verify system state and clean up\n\n`;

    return procedures;
  }

  async getPlatformSpecificGuidance(platform, operation) {
    try {
      const platformResults = await this.vectorStore.searchDocumentation(
        `${platform} ${operation} HPC system specific`,
        {
          categories: ['external.hpc_systems'],
          maxResults: 3
        }
      );

      if (platformResults.length > 0) {
        let guidance = `## ${platform.toUpperCase()} Platform Specific Guidance\n\n`;
        platformResults.forEach(result => {
          guidance += `${result.content.substring(0, 300)}...\n\n`;
        });
        return guidance;
      }
    } catch (error) {
      console.warn(`Platform guidance lookup failed: ${error.message}`);
    }

    return `## ${platform.toUpperCase()} Platform Notes\n\nRefer to ${platform} documentation for platform-specific requirements and procedures.\n\n`;
  }

  formatEnhancedSearchResults(results, query, metadata) {
    let output = `# Enhanced Search Results: "${query}"\n\n`;
    output += `**Search completed in ${metadata.searchTime}ms across ${metadata.totalSources} knowledge sources**\n\n`;

    results.forEach((result, index) => {
      output += `## ${index + 1}. ${this.extractTitle(result)}\n\n`;

      if (metadata.includeAttribution && result.attribution) {
        output += `**Source**: ${result.attribution.source_type} | `;
        output += `**Category**: ${result.attribution.category} | `;
        output += `**Confidence**: ${(result.attribution.confidence * 100).toFixed(1)}%\n`;

        if (result.attribution.source_url) {
          output += `**URL**: ${result.attribution.source_url}\n`;
        }
        output += '\n';
      }

      output += result.content.substring(0, 600);
      if (result.content.length > 600) {
        output += '...\n';
      }
      output += '\n\n---\n\n';
    });

    // Add search suggestions
    if (results.length < 3) {
      output += `## 💡 Search Suggestions\n`;
      output += `- Try broader or alternative terms\n`;
      output += `- Include related concepts or synonyms\n`;
      output += `- Search specific categories or sources\n`;
      output += `- Lower the quality threshold for more results\n`;
    }

    return output;
  }

  formatCodeResults(results, pattern, options) {
    let output = `# Similar Code Patterns: "${pattern}"\n\n`;
    output += `**Found ${results.length} similar patterns`;
    if (options.includeExternal) {
      output += ' across local and external sources';
    }
    output += `**\n\n`;

    results.forEach((result, index) => {
      output += `## ${index + 1}. `;

      if (result.metadata?.source) {
        const filename = result.metadata.source.split('/').pop();
        output += filename;
      } else {
        output += 'Code Example';
      }

      if (result.source_type) {
        output += ` (${result.source_type})`;
      }

      output += `\n\n`;

      if (result.relevance_score) {
        output += `**Similarity**: ${(result.relevance_score * 100).toFixed(1)}%\n`;
      }

      if (result.attribution?.source_url) {
        output += `**Source**: ${result.attribution.source_url}\n`;
      }

      output += '\n```\n';
      output += result.content.substring(0, 500);
      if (result.content.length > 500) {
        output += '\n...';
      }
      output += '\n```\n\n';
    });

    return output;
  }

  /**
   * Get enhanced RAG statistics
   */
  getStats() {
    return {
      ...this.stats,
      vectorStoreStats: this.vectorStore?.getStats() || {},
      isInitialized: this.isInitialized
    };
  }

  /**
   * List all URLs that have been ingested as embeddings
   */
  async listIngestedURLs(args = {}) {
    await this.initialize();
    const { format = 'detailed', category_filter = null } = args;

    try {
      // Load the latest ingestion report
      const knowledgeBasePath = this.vectorStore.options.knowledgeBasePath;

      let latestReport = null;
      try {
        const files = await fs.readdir(knowledgeBasePath);
        const reportFiles = files.filter(f => f.startsWith('final_report_') && f.endsWith('.json'))
          .sort().reverse();

        if (reportFiles.length > 0) {
          const reportContent = await fs.readFile(
            path.join(knowledgeBasePath, reportFiles[0]),
            'utf-8'
          );
          latestReport = JSON.parse(reportContent);
        }
      } catch (error) {
        console.warn(`Could not load ingestion report: ${error.message}`);
      }

      let response = `# RAG System Knowledge Sources\n\n`;
      response += `**Generated**: ${new Date().toISOString()}\n`;

      if (latestReport) {
        response += `**Last Ingestion**: ${latestReport.timestamp}\n`;
        response += `**Total URLs Processed**: ${latestReport.results.totalUrls}\n`;
        response += `**Successfully Ingested**: ${latestReport.results.successfulUrls}\n`;
        response += `**Success Rate**: ${((latestReport.results.successfulUrls / latestReport.results.totalUrls) * 100).toFixed(1)}%\n`;
        response += `**Total Knowledge Chunks**: ${latestReport.results.totalChunks.toLocaleString()}\n`;
        response += `**Average Quality Score**: ${(latestReport.results.averageQualityScore * 100).toFixed(1)}%\n\n`;

        // List URLs by category
        const categoryStats = latestReport.results.categoryStats;
        const categories = Object.keys(categoryStats).sort();

        for (const category of categories) {
          if (category_filter && !category.includes(category_filter)) continue;

          const stats = categoryStats[category];
          response += `## ${category}\n`;
          response += `- **Count**: ${stats.count} URLs\n`;
          if (stats.avgPriority !== undefined) {
            response += `- **Priority**: ${stats.avgPriority}/10\n`;
          }
          response += `- **URLs**:\n`;

          for (const url of stats.urls) {
            response += `  - ${url}\n`;
          }
          response += `\n`;
        }

        // Add error information if any
        if (latestReport.results.errors && latestReport.results.errors.length > 0) {
          response += `## Failed URLs\n\n`;
          latestReport.results.errors.forEach(error => {
            response += `- **${error.url}**: ${error.error}\n`;
          });
          response += `\n`;
        }
      } else {
        // Fallback - use vector store statistics
        const stats = this.vectorStore.getStats();
        response += `**Local EE2 Chunks**: ${stats.chunks || 0}\n`;
        response += `**External Chunks**: ${stats.externalChunks || 0}\n`;
        response += `**Total Sources**: ${stats.totalSources || 0}\n\n`;
        response += `*Note: Detailed URL list unavailable - no ingestion report found*\n`;
      }

      return response;

    } catch (error) {
      return `Error retrieving URL list: ${error.message}`;
    }
  }

  /**
   * Get comprehensive RAG system status
   */
  async getKnowledgeBaseStatus(args = {}) {
    await this.initialize();
    const { include_health = true, include_urls = false } = args;

    try {
      const stats = this.vectorStore.getStats();

      let response = `# Enhanced RAG System Status\n\n`;
      response += `**Status**: ✅ Operational\n`;
      response += `**Timestamp**: ${new Date().toISOString()}\n\n`;

      // Core Statistics
      response += `## Knowledge Base Overview\n\n`;
      response += `- **Total Knowledge Chunks**: ${(stats.chunks || 0) + (stats.externalChunks || 0)}\n`;
      response += `- **Local EE2 Compliance**: ${stats.chunks || 0} chunks\n`;
      response += `- **External Documentation**: ${stats.externalChunks || 0} chunks\n`;
      response += `- **Knowledge Sources**: ${stats.totalSources || 0}\n`;
      response += `- **Categories**: ${Object.keys(stats.categories || {}).length}\n\n`;

      // Source Breakdown
      if (stats.sources) {
        response += `## Sources\n\n`;
        Object.entries(stats.sources).forEach(([source, sourceStats]) => {
          response += `- **${source}**: ${sourceStats.chunkCount} chunks (avg quality: ${(sourceStats.avgQualityScore * 100).toFixed(1)}%)\n`;
        });
        response += `\n`;
      }

      // Categories
      if (stats.categories && Object.keys(stats.categories).length > 0) {
        response += `## Knowledge Categories\n\n`;
        Object.entries(stats.categories)
          .sort(([,a], [,b]) => b - a)
          .slice(0, 10) // Top 10 categories
          .forEach(([category, count]) => {
            response += `- **${category}**: ${count} chunks\n`;
          });
        response += `\n`;
      }

      // Health Check
      if (include_health) {
        const health = this.vectorStore.getSourceHealth();
        response += `## Source Health\n\n`;
        Object.entries(health.sources).forEach(([source, healthStats]) => {
          const status = healthStats.status === 'healthy' ? '✅' : '⚠️';
          response += `- **${source}** ${status}: ${healthStats.totalChunks} chunks, ${(healthStats.avgQuality * 100).toFixed(1)}% avg quality\n`;
        });
        response += `\n`;
      }

      // Capabilities
      response += `## Capabilities\n\n`;
      response += `✅ Multi-source semantic search\n`;
      response += `✅ Intelligent query routing\n`;
      response += `✅ EE2 compliance analysis\n`;
      response += `✅ Source attribution\n`;
      response += `✅ Quality-based ranking\n`;
      response += `✅ External documentation integration\n\n`;

      // URL list if requested
      if (include_urls) {
        const urlList = await this.listIngestedURLs({ format: 'summary' });
        response += urlList;
      }

      return response;

    } catch (error) {
      return `Error retrieving knowledge base status: ${error.message}`;
    }
  }

  /**
   * Retrieve specific URL content or metadata from the knowledge base
   */
  async retrieveURLContent(args = {}) {
    await this.initialize();
    const { url, include_chunks = true, include_metadata = true, max_chunks = 10 } = args;

    if (!url) {
      return 'Error: URL parameter is required';
    }

    try {
      // Search for chunks that came from this URL
      const results = await this.vectorStore.searchDocumentation(`source:${url}`, {
        maxResults: max_chunks,
        sources: ['external'],
        includeMetadata: true
      });

      // Also try searching by the URL itself in metadata
      const allChunks = this.vectorStore.externalChunks || [];
      const urlChunks = allChunks.filter(chunk =>
        chunk.metadata?.source === url ||
        chunk.metadata?.fetchedFrom === url ||
        chunk.metadata?.originalUrl === url
      );

      let response = `# Content from: ${url}\n\n`;

      if (urlChunks.length === 0 && results.length === 0) {
        response += `❌ No content found for this URL in the knowledge base.\n\n`;
        response += `This URL may have:\n`;
        response += `- Failed during ingestion\n`;
        response += `- Been processed but not yet indexed\n`;
        response += `- Not been included in the documentation references\n`;
        return response;
      }

      const relevantChunks = urlChunks.length > 0 ? urlChunks : results;
      const chunk = relevantChunks[0]; // Get first chunk for metadata

      // Show metadata
      if (include_metadata && chunk.metadata) {
        response += `## Metadata\n\n`;
        response += `- **Source**: ${chunk.metadata.source || 'Unknown'}\n`;
        response += `- **Category**: ${chunk.metadata.category || 'Uncategorized'}\n`;
        response += `- **Quality Score**: ${((chunk.qualityScore || chunk.metadata.qualityScore || 0) * 100).toFixed(1)}%\n`;
        response += `- **Last Updated**: ${chunk.metadata.ingestedAt || chunk.metadata.fetchedAt || 'Unknown'}\n`;
        response += `- **Content Type**: ${chunk.metadata.contentType || 'Unknown'}\n`;
        if (chunk.metadata.title) {
          response += `- **Title**: ${chunk.metadata.title}\n`;
        }
        response += `\n`;
      }

      // Show content chunks
      if (include_chunks) {
        response += `## Content Preview (${Math.min(relevantChunks.length, max_chunks)} of ${relevantChunks.length} chunks)\n\n`;

        relevantChunks.slice(0, max_chunks).forEach((chunk, index) => {
          response += `### Chunk ${index + 1}\n`;
          response += `${chunk.content}\n\n`;
          response += `---\n\n`;
        });

        if (relevantChunks.length > max_chunks) {
          response += `*Showing ${max_chunks} of ${relevantChunks.length} total chunks. Use max_chunks parameter to see more.*\n\n`;
        }
      }

      response += `## Usage Statistics\n\n`;
      response += `- **Total Chunks**: ${relevantChunks.length}\n`;
      response += `- **Average Quality**: ${(relevantChunks.reduce((sum, c) => sum + (c.qualityScore || c.metadata?.qualityScore || 0), 0) / relevantChunks.length * 100).toFixed(1)}%\n`;

      return response;

    } catch (error) {
      return `Error retrieving URL content: ${error.message}`;
    }
  }

  /**
   * Get a simple array of all ingested URLs
   */
  async getIngestedURLsArray(args = {}) {
    await this.initialize();

    try {
      const knowledgeBasePath = this.vectorStore.options.knowledgeBasePath;
      const files = await fs.readdir(knowledgeBasePath);
      const reportFiles = files.filter(f => f.startsWith('final_report_') && f.endsWith('.json'))
        .sort().reverse();

      if (reportFiles.length === 0) {
        return { error: 'No ingestion report found', urls: [] };
      }

      const reportContent = await fs.readFile(
        path.join(knowledgeBasePath, reportFiles[0]),
        'utf-8'
      );
      const report = JSON.parse(reportContent);

      const allUrls = [];
      Object.values(report.results.categoryStats).forEach(stats => {
        allUrls.push(...stats.urls);
      });

      const failedUrls = (report.results.errors || []).map(e => e.url);
      const successfulUrls = allUrls.filter(url => !failedUrls.includes(url));

      return {
        totalUrls: allUrls.length,
        successfulUrls: successfulUrls,
        failedUrls: failedUrls,
        successRate: ((successfulUrls.length / allUrls.length) * 100).toFixed(1) + '%',
        lastIngestion: report.timestamp,
        allUrls: allUrls.sort()
      };

    } catch (error) {
      return { error: error.message, urls: [] };
    }
  }
}

export default EnhancedRAGTools;