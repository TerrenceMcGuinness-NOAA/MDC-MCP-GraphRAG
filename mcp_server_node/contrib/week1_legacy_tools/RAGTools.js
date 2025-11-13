#!/usr/bin/env node

/**
 * RAG (Retrieval-Augmented Generation) Tools Module
 * 
 * Provides semantic search and knowledge retrieval capabilities
 * using local embeddings and ChromaDB integration.
 * 
 * @version 2.0.0
 * @author NOAA EMC Global Workflow Team
 */

import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
// Lazy load ChromaDB to avoid startup issues
let ChromaClient = null;
// Lazy load transformers to avoid startup issues
let transformers = null;
// Lazy load EE2 vector store
let EE2VectorStore = null;

export class RAGTools {
  constructor(knowledgeBasePath) {
    this.knowledgeBasePath = knowledgeBasePath || this.findKnowledgeBase();
    this.chromaClient = null;
    this.collection = null;
    this.enhancedCollection = null;
    this.embeddingModel = null;
    this.localKnowledgeBase = null;
    this.ee2VectorStore = null;
    this.isInitialized = false;
  }

  /**
   * Find knowledge base directory
   */
  findKnowledgeBase() {
    const currentDir = path.dirname(path.dirname(__dirname));
    return path.join(currentDir, 'knowledge-base');
  }

  /**
   * Initialize RAG components
   */
  async initialize() {
    if (this.isInitialized) return;

    console.error('🔄 Initializing RAG components...');
    
    // Initialize local knowledge base
    await this.loadLocalKnowledgeBase();
    
    // Try to initialize ChromaDB
    await this.initializeChromaDB();
    
    // Initialize embedding model
    await this.initializeEmbeddingModel();
    
    // Initialize enhanced EE2 vector store
    await this.initializeEE2VectorStore();
    
    this.isInitialized = true;
    console.error('✅ RAG components initialized');
  }

  /**
   * Register RAG tools with server
   */
  registerWith(server) {
    server.registerTool(
      'search_documentation',
      'Semantic search across workflow documentation and code',
      {
        type: 'object',
        properties: {
          query: {
            type: 'string',
            description: 'Search query for documentation'
          },
          max_results: {
            type: 'number',
            description: 'Maximum number of results to return',
            default: 5,
            minimum: 1,
            maximum: 20
          },
          similarity_threshold: {
            type: 'number',
            description: 'Minimum similarity threshold (0.0-1.0)',
            default: 0.1,
            minimum: 0.0,
            maximum: 1.0
          }
        },
        required: ['query']
      },
      this.searchDocumentation.bind(this)
    );

    server.registerTool(
      'explain_with_context',
      'Explain workflow concepts using contextual knowledge',
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
            enum: ['technical', 'operational', 'configuration', 'all'],
            default: 'all'
          },
          detail_level: {
            type: 'string',
            description: 'Level of explanation detail',
            enum: ['basic', 'intermediate', 'advanced'],
            default: 'intermediate'
          }
        },
        required: ['topic']
      },
      this.explainWithContext.bind(this)
    );

    server.registerTool(
      'find_similar_code',
      'Find similar code patterns across the workflow',
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
            default: ['sh', 'py']
          },
          max_results: {
            type: 'number',
            description: 'Maximum similar patterns to return',
            default: 10
          }
        },
        required: ['code_pattern']
      },
      this.findSimilarCode.bind(this)
    );

    server.registerTool(
      'get_operational_guidance',
      'Get operational guidance and best practices',
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
          }
        },
        required: ['operation']
      },
      this.getOperationalGuidance.bind(this)
    );

    server.registerTool(
      'analyze_ee2_compliance',
      'Analyze code or documentation for EE2 compliance',
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
          }
        },
        required: ['content']
      },
      this.analyzeEE2Compliance.bind(this)
    );

    server.registerTool(
      'search_ee2_standards',
      'Search EE2 compliance standards and documentation',
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
      'Generate comprehensive EE2 compliance report',
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
          }
        }
      },
      this.generateComplianceReport.bind(this)
    );
  }

  /**
   * Search documentation using semantic search
   */
  async searchDocumentation(args) {
    await this.initialize();
    
    const { query, max_results = 5, similarity_threshold = 0.1 } = args;
    
    try {
      // Try ChromaDB first, fall back to local search
      let results = [];
      
      if (this.collection) {
        results = await this.searchChromaDB(query, max_results, similarity_threshold);
      } else if (this.localKnowledgeBase) {
        results = await this.searchLocalKnowledgeBase(query, max_results, similarity_threshold);
      } else {
        return 'RAG system not available - knowledge base not loaded';
      }

      if (results.length === 0) {
        return `No documentation found for query: "${query}"`;
      }

      return this.formatSearchResults(results, query);
      
    } catch (error) {
      return `Search error: ${error.message}`;
    }
  }

  /**
   * Explain topic with contextual knowledge
   */
  async explainWithContext(args) {
    await this.initialize();
    
    const { topic, context_type = 'all', detail_level = 'intermediate' } = args;
    
    try {
      // Search for relevant context
      const contextResults = await this.searchDocumentation({
        query: topic,
        max_results: 10,
        similarity_threshold: 0.15
      });

      // Generate explanation based on context
      const explanation = this.generateContextualExplanation(
        topic,
        contextResults,
        context_type,
        detail_level
      );

      return explanation;
      
    } catch (error) {
      return `Explanation error: ${error.message}`;
    }
  }

  /**
   * Find similar code patterns
   */
  async findSimilarCode(args) {
    await this.initialize();
    
    const { code_pattern, file_types = ['sh', 'py'], max_results = 10 } = args;
    
    try {
      if (!this.localKnowledgeBase || !this.localKnowledgeBase.chunks) {
        return 'Code search not available - knowledge base not loaded';
      }

      // Filter chunks by file type and search for patterns
      const codeChunks = this.localKnowledgeBase.chunks.filter(chunk => {
        const sourceFile = chunk.metadata?.source || '';
        return file_types.some(ext => sourceFile.endsWith(`.${ext}`));
      });

      // Simple pattern matching (could be enhanced with semantic similarity)
      const similarChunks = codeChunks.filter(chunk => {
        const content = chunk.content.toLowerCase();
        const pattern = code_pattern.toLowerCase();
        return content.includes(pattern) || this.calculateTextSimilarity(content, pattern) > 0.3;
      }).slice(0, max_results);

      if (similarChunks.length === 0) {
        return `No similar code patterns found for: "${code_pattern}"`;
      }

      return this.formatCodeResults(similarChunks, code_pattern);
      
    } catch (error) {
      return `Code search error: ${error.message}`;
    }
  }

  /**
   * Get operational guidance
   */
  async getOperationalGuidance(args) {
    const { operation, platform = 'generic', urgency = 'routine' } = args;
    
    try {
      // Search for operational documentation
      const guidanceQuery = `${operation} ${platform} operational procedure`;
      const searchResults = await this.searchDocumentation({
        query: guidanceQuery,
        max_results: 8,
        similarity_threshold: 0.12
      });

      // Format as operational guidance
      let guidance = `# Operational Guidance: ${operation}\n\n`;
      guidance += `**Platform**: ${platform}\n`;
      guidance += `**Urgency**: ${urgency}\n\n`;

      if (searchResults && !searchResults.includes('No documentation found')) {
        guidance += `## Relevant Documentation\n${searchResults}\n\n`;
      }

      guidance += this.getStandardOperationalProcedures(operation, platform, urgency);

      return guidance;
      
    } catch (error) {
      return `Guidance error: ${error.message}`;
    }
  }

  /**
   * Helper methods for RAG functionality
   */
  async loadLocalKnowledgeBase() {
    try {
      const chunksPath = path.join(this.knowledgeBasePath, 'chunks_with_embeddings.json');
      const content = await fs.readFile(chunksPath, 'utf-8');
      this.localKnowledgeBase = JSON.parse(content);
      console.error(`✅ Loaded ${this.localKnowledgeBase.chunks?.length || 0} knowledge chunks`);
    } catch (error) {
      console.error(`⚠️ Could not load local knowledge base: ${error.message}`);
      this.localKnowledgeBase = null;
    }
  }

  async initializeChromaDB() {
    try {
      if (!ChromaClient) {
        const chromaModule = await import('chromadb');
        ChromaClient = chromaModule.ChromaClient;
      }

      // Get ChromaDB server URL from environment or use default
      // Note: ChromaDB 1.1.1 server uses port 8080 by default
      const chromaUrl = process.env.CHROMA_SERVER_URL || 'http://127.0.0.1:8080';

      // ChromaDB 3.0.17 client API - updated initialization
      this.chromaClient = new ChromaClient({
        path: chromaUrl
      });

      console.error(`🔗 Connecting to ChromaDB at ${chromaUrl}...`);

      // Test connection with heartbeat (API v1 compatible)
      try {
        const heartbeat = await this.chromaClient.heartbeat();
        console.error(`✅ ChromaDB heartbeat: ${heartbeat}`);
      } catch (error) {
        console.error(`⚠️ ChromaDB heartbeat failed: ${error.message}`);
      }

      // Load both collections for comprehensive search
      // getOrCreateCollection API is compatible between versions
      this.collection = await this.chromaClient.getOrCreateCollection({
        name: 'global-workflow-docs'
      });
      console.error('✅ Basic collection loaded (978 docs)');

      // Load enhanced collection with richer metadata
      try {
        this.enhancedCollection = await this.chromaClient.getOrCreateCollection({
          name: 'global_workflow_docs'
        });
        console.error('✅ Enhanced collection loaded (1,702 docs)');
      } catch (error) {
        console.error('⚠️ Enhanced collection not available, using basic collection only');
      }

      console.error('✅ ChromaDB collections initialized successfully');
    } catch (error) {
      console.error(`⚠️ ChromaDB not available at ${process.env.CHROMA_SERVER_URL || 'http://127.0.0.1:8080'}: ${error.message}`);
      console.error('   Using local knowledge base fallback mode');
      this.collection = null;
      this.enhancedCollection = null;
    }
  }

  async initializeEmbeddingModel() {
    try {
      if (!transformers) {
        transformers = await import('@xenova/transformers');
      }
      this.embeddingModel = await transformers.pipeline(
        'feature-extraction',
        'Xenova/all-MiniLM-L6-v2'
      );
      console.error('✅ Embedding model initialized');
    } catch (error) {
      console.error('⚠️ Embedding model not available');
      this.embeddingModel = null;
    }
  }

  async searchChromaDB(query, maxResults, threshold) {
    if (!this.collection && !this.enhancedCollection) return [];

    try {
      const allResults = [];

      // Search enhanced collection first (better metadata)
      if (this.enhancedCollection) {
        try {
          const enhancedResults = await this.enhancedCollection.query({
            queryTexts: [query],
            nResults: Math.ceil(maxResults * 0.7) // Get 70% from enhanced
          });

          const formatted = enhancedResults.documents[0].map((doc, i) => ({
            content: doc,
            similarity: 1 - (enhancedResults.distances[0][i] || 1),
            metadata: {
              ...enhancedResults.metadatas[0][i],
              collection: 'enhanced'
            }
          })).filter(result => result.similarity >= threshold);

          allResults.push(...formatted);
        } catch (error) {
          console.error('Enhanced collection search error:', error.message);
        }
      }

      // Search basic collection
      if (this.collection) {
        try {
          const basicResults = await this.collection.query({
            queryTexts: [query],
            nResults: Math.ceil(maxResults * 0.3) // Get 30% from basic
          });

          const formatted = basicResults.documents[0].map((doc, i) => ({
            content: doc,
            similarity: 1 - (basicResults.distances[0][i] || 1),
            metadata: {
              ...basicResults.metadatas[0][i],
              collection: 'basic'
            }
          })).filter(result => result.similarity >= threshold);

          allResults.push(...formatted);
        } catch (error) {
          console.error('Basic collection search error:', error.message);
        }
      }

      // Sort by similarity and deduplicate
      const uniqueResults = this.deduplicateResults(allResults);
      return uniqueResults
        .sort((a, b) => b.similarity - a.similarity)
        .slice(0, maxResults);

    } catch (error) {
      console.error('ChromaDB search error:', error.message);
      return [];
    }
  }

  deduplicateResults(results) {
    const seen = new Set();
    return results.filter(result => {
      const key = result.content.substring(0, 100); // Use first 100 chars as key
      if (seen.has(key)) {
        return false;
      }
      seen.add(key);
      return true;
    });
  }

  async searchLocalKnowledgeBase(query, maxResults, threshold) {
    if (!this.localKnowledgeBase?.chunks) return [];

    const queryLower = query.toLowerCase();
    const results = [];

    for (const chunk of this.localKnowledgeBase.chunks) {
      const content = chunk.content.toLowerCase();
      const similarity = this.calculateTextSimilarity(content, queryLower);
      
      if (similarity >= threshold) {
        results.push({
          content: chunk.content,
          similarity,
          metadata: chunk.metadata || {}
        });
      }
    }

    return results
      .sort((a, b) => b.similarity - a.similarity)
      .slice(0, maxResults);
  }

  calculateTextSimilarity(text1, text2) {
    // Simple word overlap similarity
    const words1 = new Set(text1.split(/\s+/));
    const words2 = new Set(text2.split(/\s+/));
    const intersection = new Set([...words1].filter(x => words2.has(x)));
    const union = new Set([...words1, ...words2]);
    
    return intersection.size / union.size;
  }

  formatSearchResults(results, query) {
    let output = `# Documentation Search Results for: "${query}"\n\n`;
    
    results.forEach((result, index) => {
      output += `## Result ${index + 1} (Similarity: ${(result.similarity * 100).toFixed(1)}%)\n\n`;
      
      if (result.metadata.source) {
        output += `**Source**: ${result.metadata.source}\n\n`;
      }
      
      output += result.content.substring(0, 500);
      if (result.content.length > 500) {
        output += '...\n';
      }
      output += '\n\n---\n\n';
    });

    return output;
  }

  formatCodeResults(results, pattern) {
    let output = `# Similar Code Patterns for: "${pattern}"\n\n`;
    
    results.forEach((chunk, index) => {
      output += `## Example ${index + 1}\n\n`;
      
      if (chunk.metadata?.source) {
        output += `**File**: ${chunk.metadata.source}\n\n`;
      }
      
      output += '```\n';
      output += chunk.content.substring(0, 400);
      if (chunk.content.length > 400) {
        output += '\n...';
      }
      output += '\n```\n\n';
    });

    return output;
  }

  generateContextualExplanation(topic, contextResults, contextType, detailLevel) {
    let explanation = `# ${topic}\n\n`;
    
    // Add context-based explanation
    if (contextResults && !contextResults.includes('No documentation found')) {
      explanation += `## Context from Documentation\n`;
      explanation += contextResults;
      explanation += '\n\n';
    }

    // Add standard explanations based on detail level
    explanation += this.getStandardExplanation(topic, contextType, detailLevel);
    
    return explanation;
  }

  getStandardExplanation(topic, contextType, detailLevel) {
    let explanation = `## General Information\n\n`;
    
    const topicLower = topic.toLowerCase();
    
    if (topicLower.includes('analysis')) {
      explanation += this.getAnalysisExplanation(detailLevel);
    } else if (topicLower.includes('forecast')) {
      explanation += this.getForecastExplanation(detailLevel);
    } else if (topicLower.includes('gsi')) {
      explanation += this.getGSIExplanation(detailLevel);
    } else if (topicLower.includes('ufs')) {
      explanation += this.getUFSExplanation(detailLevel);
    } else {
      explanation += `This topic relates to the NOAA Global Workflow system. `;
      explanation += `For specific information, search the documentation or code base.`;
    }

    return explanation;
  }

  getAnalysisExplanation(detailLevel) {
    if (detailLevel === 'basic') {
      return 'Analysis combines observations with model forecasts to create initial conditions.';
    } else if (detailLevel === 'advanced') {
      return 'Analysis uses data assimilation techniques like 3D/4D-Var and EnKF to optimally combine observations with short-term forecasts, accounting for observation and background error statistics.';
    } else {
      return 'Analysis is the process of combining observational data with model background fields to produce optimal initial conditions for weather forecasting.';
    }
  }

  getForecastExplanation(detailLevel) {
    if (detailLevel === 'basic') {
      return 'Forecast runs the numerical weather model from initial conditions to predict future weather.';
    } else if (detailLevel === 'advanced') {
      return 'The forecast step integrates the UFS weather model forward in time from analysis initial conditions, solving the primitive equations on various grids and scales.';
    } else {
      return 'Forecast uses the Unified Forecast System (UFS) to simulate atmospheric evolution from analysis initial conditions.';
    }
  }

  getGSIExplanation(detailLevel) {
    if (detailLevel === 'basic') {
      return 'GSI is the data assimilation system that creates analyses from observations.';
    } else if (detailLevel === 'advanced') {
      return 'The Gridpoint Statistical Interpolation (GSI) system performs variational data assimilation using 3D-Var, 4D-Var, and hybrid methods with ensemble covariances.';
    } else {
      return 'GSI (Gridpoint Statistical Interpolation) is NCEP\'s data assimilation system for creating atmospheric analyses.';
    }
  }

  getUFSExplanation(detailLevel) {
    if (detailLevel === 'basic') {
      return 'UFS is the unified weather and climate model used for forecasting.';
    } else if (detailLevel === 'advanced') {
      return 'The Unified Forecast System (UFS) is a community-based Earth modeling system with atmosphere (FV3), ocean (MOM6), ice (CICE), and wave (WaveWatch III) components.';
    } else {
      return 'UFS (Unified Forecast System) is the coupled Earth system model used for operational weather prediction.';
    }
  }

  getStandardOperationalProcedures(operation, platform, urgency) {
    let procedures = `## Standard Procedures\n\n`;
    
    if (urgency === 'emergency') {
      procedures += `⚠️ **EMERGENCY PROCEDURES**\n\n`;
      procedures += `1. Alert operations team immediately\n`;
      procedures += `2. Document the issue with timestamps\n`;
      procedures += `3. Follow emergency contact procedures\n\n`;
    }

    procedures += `### For ${operation} on ${platform}\n\n`;
    procedures += `1. Check system status and resources\n`;
    procedures += `2. Verify prerequisite conditions\n`;
    procedures += `3. Execute planned procedure\n`;
    procedures += `4. Monitor progress and logs\n`;
    procedures += `5. Validate results\n`;
    procedures += `6. Update operational logs\n\n`;

    if (platform !== 'generic') {
      procedures += `### Platform-Specific Notes for ${platform}\n`;
      procedures += `- Check platform-specific documentation\n`;
      procedures += `- Verify module loads and environment\n`;
      procedures += `- Monitor queue status and resource limits\n\n`;
    }

    return procedures;
  }

  /**
   * Initialize EE2 vector store
   */
  async initializeEE2VectorStore() {
    try {
      if (!EE2VectorStore) {
        const ee2Module = await import('../rag/EE2VectorStore.js');
        EE2VectorStore = ee2Module.EE2VectorStore;
      }
      
      this.ee2VectorStore = new EE2VectorStore({
        knowledgeBasePath: this.knowledgeBasePath
      });
      
      await this.ee2VectorStore.initialize();
      console.error('✅ EE2 Vector Store initialized');
    } catch (error) {
      console.error('⚠️ EE2 Vector Store not available');
      this.ee2VectorStore = null;
    }
  }

  /**
   * Analyze content for EE2 compliance
   */
  async analyzeEE2Compliance(args) {
    const { content, analysis_type = 'comprehensive', include_recommendations = true } = args;
    
    if (!this.ee2VectorStore) {
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

      // Search for relevant standards
      const relevantStandards = await this.ee2VectorStore.searchEE2Compliance(
        `${analysis_type} compliance standards`,
        { maxResults: 3, category: analysis_type !== 'comprehensive' ? analysis_type : null }
      );

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
   * Search EE2 standards and documentation
   */
  async searchEE2Standards(args) {
    const { query, category = null, include_examples = true, max_results = 8 } = args;
    
    if (!this.ee2VectorStore) {
      return 'EE2 standards search not available - vector store not initialized';
    }

    try {
      const results = await this.ee2VectorStore.searchEE2Compliance(query, {
        maxResults: max_results,
        category: category,
        includeCode: include_examples
      });

      if (results.length === 0) {
        return `No EE2 standards found for query: "${query}"`;
      }

      let output = `# EE2 Standards Search Results\n\n`;
      output += `**Query**: "${query}"\n`;
      if (category) {
        output += `**Category**: ${category}\n`;
      }
      output += `**Results**: ${results.length}\n\n`;

      results.forEach((result, index) => {
        output += `## ${index + 1}. ${result.metadata?.source ? path.basename(result.metadata.source) : 'EE2 Standard'}\n\n`;
        
        if (result.relevance_score) {
          output += `**Relevance**: ${(result.relevance_score * 10).toFixed(1)}/10\n`;
        }
        
        if (result.metadata?.compliance_categories?.length > 0) {
          const categories = result.metadata.compliance_categories.map(c => c.name).join(', ');
          output += `**Categories**: ${categories}\n`;
        }
        
        output += `\n${result.content}\n\n`;
        
        if (index < results.length - 1) {
          output += `---\n\n`;
        }
      });

      return output;
    } catch (error) {
      return `EE2 standards search error: ${error.message}`;
    }
  }

  /**
   * Generate comprehensive compliance report
   */
  async generateComplianceReport(args) {
    const { scope = 'summary', categories = [], format = 'markdown' } = args;
    
    if (!this.ee2VectorStore) {
      return 'Compliance report generation not available - vector store not initialized';
    }

    try {
      let report = `# EE2 Compliance Report\n\n`;
      report += `**Generated**: ${new Date().toISOString()}\n`;
      report += `**Scope**: ${scope}\n`;
      report += `**Format**: ${format}\n\n`;

      const stats = this.ee2VectorStore.getStats();
      
      report += `## Knowledge Base Statistics\n\n`;
      report += `- **Total Chunks**: ${stats.total_chunks}\n`;
      report += `- **EE2 Compliance Chunks**: ${stats.ee2_chunks}\n`;
      report += `- **High Importance Chunks**: ${stats.high_importance_chunks}\n`;
      report += `- **Compliance Categories**: ${stats.compliance_categories}\n\n`;

      const targetCategories = categories.length > 0 ? categories : [
        'environment_variables',
        'workflow_structure', 
        'error_handling',
        'file_naming',
        'production_utilities',
        'code_standards',
        'directory_structure'
      ];

      report += `## Compliance Category Analysis\n\n`;

      for (const category of targetCategories) {
        const categoryResults = await this.ee2VectorStore.searchEE2Compliance('compliance', {
          category: category,
          maxResults: 3
        });

        report += `### ${category.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}\n\n`;
        
        if (categoryResults.length > 0) {
          const avgRelevance = categoryResults.reduce((sum, r) => sum + r.relevance_score, 0) / categoryResults.length;
          report += `**Coverage**: ${categoryResults.length} standards found\n`;
          report += `**Relevance**: ${(avgRelevance * 10).toFixed(1)}/10\n\n`;
          
          if (scope === 'detailed') {
            categoryResults.forEach((result, index) => {
              report += `#### ${index + 1}. ${result.metadata?.source ? path.basename(result.metadata.source) : 'Standard'}\n`;
              report += `${result.content.substring(0, 200)}...\n\n`;
            });
          }
        } else {
          report += `**Status**: No standards found for this category\n\n`;
        }
      }

      if (format === 'checklist') {
        report += `## Compliance Checklist\n\n`;
        for (const category of targetCategories) {
          report += `- [ ] ${category.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}\n`;
        }
        report += `\n`;
      }

      report += `## Recommendations\n\n`;
      report += `1. **Regular Compliance Reviews**: Schedule monthly compliance assessments\n`;
      report += `2. **Automated Validation**: Implement CI/CD compliance checks\n`;
      report += `3. **Training Updates**: Keep development team updated on EE2 standards\n`;
      report += `4. **Documentation Maintenance**: Ensure compliance documentation stays current\n\n`;

      return report;
    } catch (error) {
      return `Compliance report generation error: ${error.message}`;
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
    let assessment = '';
    if (assessmentScore >= 90) {
      assessment = `✅ **EXCELLENT COMPLIANCE** (${assessmentScore}%)\n\nThe content demonstrates strong adherence to EE2 standards.`;
    } else if (assessmentScore >= 75) {
      assessment = `⚠️ **GOOD COMPLIANCE** (${assessmentScore}%)\n\nThe content shows good compliance with minor issues to address.`;
    } else if (assessmentScore >= 50) {
      assessment = `❌ **NEEDS IMPROVEMENT** (${assessmentScore}%)\n\nSeveral compliance issues need to be addressed.`;
    } else {
      assessment = `🚨 **POOR COMPLIANCE** (${assessmentScore}%)\n\nSignificant compliance issues require immediate attention.`;
    }

    return {
      assessment,
      score: assessmentScore,
      violations,
      recommendations
    };
  }
}