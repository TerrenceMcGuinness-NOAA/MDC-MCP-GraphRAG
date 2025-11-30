#!/usr/bin/env node

/**
 * Semantic Search Tools Module
 * 
 * Consolidated RAG tools leveraging Week 1 UnifiedDataAccess Layer.
 * Combines the best of RAGTools + EnhancedRAGTools with graph enrichment.
 * 
 * Features:
 * - Hybrid semantic + graph search via UnifiedDataAccess
 * - Multi-source knowledge retrieval
 * - Code similarity detection with graph context
 * - Contextual explanations
 * - Knowledge base status and health
 * 
 * NOTE: EE2 compliance tools have been extracted to EE2ComplianceTools.js
 * for better Separation of Concerns (SOC). See that module for:
 * - search_ee2_standards
 * - analyze_ee2_compliance
 * - generate_compliance_report
 * - scan_repository_compliance
 * 
 * @version 3.0.0
 * @author Claude Sonnet 4.5
 * @supervisor Terry McGuinness
 * @date 2025-11-30
 */

import { UnifiedDataAccess } from '../data/UnifiedDataAccess.js';

export class SemanticSearchTools {
  constructor(dataAccess = null) {
    this.dataAccess = dataAccess;  // Accept injected dependency for testing
    this.isInitialized = !!dataAccess;  // Already initialized if dataAccess provided
  }

  async initialize() {
    if (this.isInitialized) return;

    console.error('[INIT] Initializing Semantic Search Tools...');
    
    try {
      this.dataAccess = new UnifiedDataAccess();
      await this.dataAccess.connect();
      
      this.isInitialized = true;
      console.error('[OK] Semantic Search Tools initialized');
    } catch (error) {
      console.error('[ERROR] Semantic Search Tools initialization failed:', error.message);
      console.error('   Tools will return error messages when called.');
      // Mark as initialized anyway to prevent repeated init attempts
      this.isInitialized = true;
      this.initializationError = error;
    }
  }

  registerWith(server) {
    // Tool 1: Search Documentation (Hybrid)
    server.registerTool(
      'search_documentation',
      'Hybrid semantic + graph search across workflow documentation and code',
      {
        type: 'object',
        properties: {
          query: { type: 'string', description: 'Search query' },
          max_results: { type: 'number', default: 8, minimum: 1, maximum: 20 },
          include_graph: { type: 'boolean', default: true, description: 'Include graph enrichment' },
          similarity_threshold: { type: 'number', default: 0.1, minimum: 0, maximum: 1 }
        },
        required: ['query']
      },
      this.searchDocumentation.bind(this)
    );

    // Tool 2: Find Related Files by Dependencies
    server.registerTool(
      'find_related_files',
      'Find files with similar dependencies and import relationships',
      {
        type: 'object',
        properties: {
          file_path: { type: 'string', description: 'File path to analyze for related files (e.g., "scripts/exglobal_forecast.py")' },
          max_results: { type: 'number', default: 10, minimum: 1, maximum: 20 },
          include_documentation: { type: 'boolean', default: true, description: 'Include related documentation' }
        },
        required: ['file_path']
      },
      this.findRelatedFiles.bind(this)
    );

    // Tool 3: Explain with Context
    server.registerTool(
      'explain_with_context',
      'Provide comprehensive explanations using hybrid search',
      {
        type: 'object',
        properties: {
          topic: { type: 'string', description: 'Topic or component to explain' },
          context_type: {
            type: 'string',
            enum: ['technical', 'operational', 'configuration', 'all'],
            default: 'all'
          },
          detail_level: { type: 'string', enum: ['basic', 'intermediate', 'advanced'], default: 'intermediate' }
        },
        required: ['topic']
      },
      this.explainWithContext.bind(this)
    );

    // Tool 4: Get Knowledge Base Status
    server.registerTool(
      'get_knowledge_base_status',
      'Get comprehensive knowledge base statistics',
      {
        type: 'object',
        properties: {
          include_graph: { type: 'boolean', default: true },
          include_vector: { type: 'boolean', default: true }
        }
      },
      this.getKnowledgeBaseStatus.bind(this)
    );

    console.error('[OK] Registered 4 Semantic Search tools');
  }

  async searchDocumentation(args) {
    await this.ensureInitialized();
    
    // Check if initialization failed
    if (this.initializationError) {
      return {
        content: [{
          type: 'text',
          text: `[ERROR] Semantic Search Tools not available: ${this.initializationError.message}\n\nPlease check that ChromaDB and Neo4j are running.`
        }]
      };
    }
    
    const { query, max_results = 8, include_graph = true, similarity_threshold = 0.1 } = args;

    try {
      console.error(`[SEARCH] Starting search_documentation: "${query}" (max_results=${max_results})`);
      const startTime = Date.now();
      
      const results = await this.dataAccess.hybridQuery(query, {
        maxResults: max_results,
        includeGraph: include_graph,
        graphDepth: 2,
        similarityThreshold: similarity_threshold
      });
      
      const elapsed = Date.now() - startTime;
      console.error(`[OK] Search completed in ${elapsed}ms, found ${results?.length || 0} results`);

      if (!results || results.length === 0) {
        return {
          content: [{ type: 'text', text: `No results found for: "${query}"` }]
        };
      }

      let output = `# Search Results: ${query}\n\n`;
      output += `Found ${results.length} results (hybrid semantic + graph search)\n\n`;

      for (const result of results) {
        output += `## ${result.metadata?.title || result.document || 'Result'}\n`;
        output += `**Similarity:** ${(result.distance * 100).toFixed(1)}%\n`;
        output += `**Source:** ${result.metadata?.source || 'Unknown'}\n`;
        if (result.graphContext) {
          output += `**Graph Context:** ${result.graphContext.length} related entities\n`;
        }
        output += `\n${result.document || result.text}\n\n`;
        output += `---\n\n`;
      }

      return { content: [{ type: 'text', text: output }] };
    } catch (error) {
      return {
        content: [{ type: 'text', text: `Error searching documentation: ${error.message}` }],
        isError: true
      };
    }
  }

  async findRelatedFiles(args) {
    await this.ensureInitialized();
    const { file_path, max_results = 10, include_documentation = true } = args;

    try {
      const relatedData = await this.dataAccess.findRelatedCode(file_path, {
        maxResults: max_results,
        includeDocumentation: include_documentation
      });

      // Handle null/undefined results defensively
      if (!relatedData || (!relatedData.relatedFiles && !relatedData.imports)) {
        return {
          content: [{ type: 'text', text: `No related files found for: "${file_path}"\n\nThis tool finds files with similar import dependencies. The file must exist in the Neo4j graph database.` }]
        };
      }

      let output = `# Related Files by Dependencies\n\n`;
      output += `Query: "${file_path}"\n\n`;

      // Display related files
      const relatedFiles = relatedData.relatedFiles || [];
      output += `Found ${relatedFiles.length} related files\n\n`;

      if (relatedFiles.length > 0) {
        output += `## Files with Similar Dependencies\n\n`;
        for (const file of relatedFiles.slice(0, max_results)) {
          const fileName = typeof file === 'string' ? file : (file.filePath || file.target || 'Unknown');
          output += `- \`${fileName}\`\n`;
        }
        output += `\n`;
      }

      // Display imports/dependencies
      const imports = relatedData.imports || [];
      if (imports.length > 0) {
        output += `## Shared Dependencies (${imports.length})\n\n`;
        for (const imp of imports.slice(0, 10)) {
          const importName = typeof imp === 'string' ? imp : (imp.moduleName || imp.target || 'Unknown');
          output += `- \`${importName}\`\n`;
        }
        if (imports.length > 10) {
          output += `- *... and ${imports.length - 10} more*\n`;
        }
        output += `\n`;
      }

      // Display documentation if available
      if (include_documentation && relatedData.documentation?.length > 0) {
        output += `## Related Documentation (${relatedData.documentation.length})\n\n`;
        for (const doc of relatedData.documentation.slice(0, 3)) {
          const docText = typeof doc === 'string' ? doc : (doc.document || doc.text || '');
          output += `${docText.substring(0, 200)}...\n\n`;
        }
      }

      return { content: [{ type: 'text', text: output }] };
    } catch (error) {
      console.error('findRelatedFiles error:', error);
      return {
        content: [{ type: 'text', text: `Error finding related files: ${error.message}\n\nThis tool searches for files with similar import dependencies based on Neo4j graph relationships.` }],
        isError: true
      };
    }
  }

  async explainWithContext(args) {
    await this.ensureInitialized();
    const { topic, context_type = 'all', detail_level = 'intermediate' } = args;

    try {
      const results = await this.dataAccess.multiSourceSearch(topic, {
        sources: ['vector', 'graph'],
        maxResults: 5
      });

      let output = `# Explanation: ${topic}\n\n`;
      output += `**Context Type:** ${context_type}\n`;
      output += `**Detail Level:** ${detail_level}\n\n`;

      if (results.vector && results.vector.length > 0) {
        output += `## Documentation Context\n\n`;
        for (const result of results.vector.slice(0, 3)) {
          output += `${result.document || result.text}\n\n`;
        }
      }

      if (results.graph && results.graph.length > 0) {
        output += `## Code Structure Context\n\n`;
        for (const result of results.graph.slice(0, 3)) {
          output += `- **${result.name || result.file}**: ${result.type || 'Component'}\n`;
        }
        output += `\n`;
      }

      output += `## Summary\n\n`;
      output += `This explanation combines semantic documentation search with code structure analysis.\n`;
      
      return { content: [{ type: 'text', text: output }] };
    } catch (error) {
      return {
        content: [{ type: 'text', text: `Error explaining with context: ${error.message}` }],
        isError: true
      };
    }
  }

  async getKnowledgeBaseStatus(args) {
    await this.ensureInitialized();
    const { include_graph = true, include_vector = true } = args;

    try {
      const stats = await this.dataAccess.getStatistics();
      
      let output = `# Knowledge Base Status\n\n`;
      
      if (include_vector && stats.vector) {
        output += `## Vector Database (ChromaDB)\n\n`;
        
        // Handle collections object properly
        const totalCollections = stats.vector.totalCollections || 0;
        const collections = stats.vector.collections || {};
        const totalDocs = Object.values(collections).reduce((sum, count) => sum + count, 0);
        
        output += `- **Collections:** ${totalCollections}\n`;
        if (totalCollections > 0) {
          output += `- **Collections Detail:**\n`;
          for (const [name, count] of Object.entries(collections)) {
            output += `  - ${name}: ${count} documents\n`;
          }
        }
        output += `- **Total Documents:** ${totalDocs}\n`;
        
        // Determine health based on actual data
        const isHealthy = totalCollections > 0 && totalDocs > 0;
        output += `- **Status:** ${isHealthy ? '[OK] Healthy' : '[ERROR] Unhealthy'}\n\n`;
      }

      if (include_graph && stats.graph) {
        output += `## Graph Database (Neo4j)\n\n`;
        output += `- **Files:** ${stats.graph.fileCount || 0}\n`;
        output += `- **Functions:** ${stats.graph.functionCount || 0}\n`;
        output += `- **Classes:** ${stats.graph.classCount || 0}\n`;
        
        // Handle relationships - they come as array of {relationshipType, count} objects
        let totalRelationships = 0;
        const relationshipMap = {};
        
        if (Array.isArray(stats.graph.relationships)) {
          for (const rel of stats.graph.relationships) {
            const type = rel.relationshipType;
            const count = parseInt(rel.count) || 0;
            relationshipMap[type] = count;
            totalRelationships += count;
          }
        }
        
        output += `- **Total Relationships:** ${totalRelationships}\n`;
        
        if (Object.keys(relationshipMap).length > 0) {
          output += `- **Relationship Types:**\n`;
          const sortedRels = Object.entries(relationshipMap)
            .sort(([,a], [,b]) => b - a)
            .slice(0, 10);
          for (const [type, count] of sortedRels) {
            output += `  - ${type}: ${count}\n`;
          }
        }
        
        // Determine health based on actual data
        const isHealthy = (stats.graph.fileCount || 0) > 0 && totalRelationships > 0;
        output += `- **Status:** ${isHealthy ? '[OK] Healthy' : '[ERROR] Unhealthy'}\n\n`;
      }

      return { content: [{ type: 'text', text: output }] };
    } catch (error) {
      return {
        content: [{ type: 'text', text: `Error getting status: ${error.message}` }],
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

export default SemanticSearchTools;
