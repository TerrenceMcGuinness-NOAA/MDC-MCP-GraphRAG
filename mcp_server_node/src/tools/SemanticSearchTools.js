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
import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

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
          collection: { type: 'string', description: 'Target specific collection (default: search all). Options: global-workflow-docs-v8-0-0, jjobs-v8-0-0, ee2-standards-v5-0-0-enhanced' },
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

    // Tool 5: List Ingested URLs (migrated from Week 1 EnhancedRAGTools)
    server.registerTool(
      'list_ingested_urls',
      'List all URLs that have been ingested into the RAG knowledge base',
      {
        type: 'object',
        properties: {
          format: { 
            type: 'string', 
            enum: ['detailed', 'summary', 'urls_only'],
            default: 'detailed',
            description: 'Output format: detailed (full report), summary (stats only), urls_only (just URLs)'
          },
          source_filter: { 
            type: 'string', 
            description: 'Filter by source name (e.g., "global-workflow", "spack")'
          }
        }
      },
      this.listIngestedURLs.bind(this)
    );

    // Tool 6: Get Ingested URLs Array (migrated from Week 1 EnhancedRAGTools)
    server.registerTool(
      'get_ingested_urls_array',
      'Get a structured array of all ingested URLs for programmatic access',
      {
        type: 'object',
        properties: {
          include_failed: { 
            type: 'boolean', 
            default: false,
            description: 'Include failed/errored URLs in the response'
          }
        }
      },
      this.getIngestedURLsArray.bind(this)
    );

    console.error('[OK] Registered 6 Semantic Search tools');
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
    
    const { query, collection, max_results = 8, include_graph = true, similarity_threshold = 0.1 } = args;

    try {
      console.error(`[SEARCH] Starting search_documentation: "${query}" (max_results=${max_results}, collection=${collection || 'all'})`);
      const startTime = Date.now();

      let results;
      if (collection) {
        // Targeted single-collection search via hybridQuery
        results = await this.dataAccess.hybridQuery(query, {
          collection,
          maxResults: max_results,
          includeGraph: include_graph,
          graphDepth: 2,
          similarityThreshold: similarity_threshold
        });
      } else {
        // Multi-collection search across all sources
        results = await this.dataAccess.multiSourceSearch(query, {
          nResults: max_results,
          enrichWithGraph: include_graph
        });
      }
      
      const elapsed = Date.now() - startTime;
      console.error(`[OK] Search completed in ${elapsed}ms, found ${results?.length || 0} results`);

      if (!results || results.length === 0) {
        return {
          content: [{ type: 'text', text: `No results found for: "${query}"` }]
        };
      }

      let output = `# Search Results: ${query}\n\n`;
      output += `Found ${results.length} results (${collection ? `collection: ${collection}` : 'multi-collection search'})\n\n`;

      for (const result of results) {
        output += `## ${result.metadata?.title || result.document || 'Result'}\n`;
        output += `**Similarity:** ${(result.distance * 100).toFixed(1)}%\n`;
        output += `**Source:** ${result.metadata?.source || 'Unknown'}`;
        if (result.collection) {
          output += ` | **Collection:** ${result.collection}`;
        }
        output += `\n`;
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
    // Coerce string booleans from MCP clients (VS Code passes "true"/"false" as strings)
    const include_graph = args.include_graph === false || args.include_graph === 'false' ? false : true;
    const include_vector = args.include_vector === false || args.include_vector === 'false' ? false : true;

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
        
        // Try to get shell script stats (Phase 27B)
        try {
          if (this.dataAccess.graphDB && this.dataAccess.graphDB.getScriptGraphStats) {
            const scriptStats = await this.dataAccess.graphDB.getScriptGraphStats();
            if (scriptStats.totalScripts > 0) {
              output += `\n### Shell Script Graph (Phase 27B)\n`;
              output += `- **Total Scripts:** ${scriptStats.totalScripts}\n`;
              output += `  - J-Jobs: ${scriptStats.jJobs}\n`;
              output += `  - Ex-Scripts: ${scriptStats.exScripts}\n`;
              output += `  - USH Scripts: ${scriptStats.ushScripts}\n`;
              output += `- **Environment Variables:** ${scriptStats.envVars}\n`;
              output += `- **Script Relationships:**\n`;
              output += `  - SOURCES: ${scriptStats.sourcesRels}\n`;
              output += `  - INVOKES: ${scriptStats.invokesRels}\n`;
              output += `  - EXPORTS: ${scriptStats.exportsRels}\n`;
              output += `  - DEPENDS_ON_ENV: ${scriptStats.dependsRels}\n`;
            }
          }
        } catch (scriptError) {
          // Shell script stats not available, ignore
        }
        
        // Determine health based on actual data - include shell scripts as valid data
        const hasCodeGraph = (stats.graph.fileCount || 0) > 0;
        const hasScriptGraph = totalRelationships > 0;
        const isHealthy = hasCodeGraph || hasScriptGraph;
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

  /**
   * List all URLs that have been ingested as embeddings
   * Migrated from Week 1 EnhancedRAGTools.js
   * Enhanced to query ChromaDB directly for accurate ingestion status
   */
  async listIngestedURLs(args) {
    await this.ensureInitialized();
    const { format = 'detailed', source_filter = null } = args;

    try {
      // Get knowledge base path
      const knowledgeBasePath = process.env.MCP_KNOWLEDGE_BASE_PATH || 
        path.join(__dirname, '../../knowledge-base');

      // Query ChromaDB directly for actual ingestion data via dataAccess layer
      let chromaStats = null;
      
      try {
        // Use the already-initialized dataAccess to query ChromaDB
        if (this.dataAccess && this.dataAccess.vectorDB) {
          const stats = await this.dataAccess.getStatistics();
          
          if (stats.vector && stats.vector.collections) {
            // Get the v8 collection document count
            const v8Count = stats.vector.collections['global-workflow-docs-v8-0-0'] || 0;
            
            // Query the collection for source breakdown
            const chromaUrl = process.env.CHROMADB_URL || process.env.CHROMA_SERVER_URL || 'http://localhost:8080';
            const baseUrl = `${chromaUrl}/api/v2`;
            const tenant = 'default_tenant';
            const database = 'default_database';
            
            // Get collections to find v8 ID
            const collsResp = await fetch(`${baseUrl}/tenants/${tenant}/databases/${database}/collections`);
            if (collsResp.ok) {
              const collections = await collsResp.json();
              const v8Coll = collections.find(c => c.name === 'global-workflow-docs-v8-0-0');
              
              if (v8Coll) {
                // Sample documents to get source breakdown
                const sampleResp = await fetch(
                  `${baseUrl}/tenants/${tenant}/databases/${database}/collections/${v8Coll.id}/get`,
                  {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ limit: 4000, include: ['metadatas'] })
                  }
                );
                
                if (sampleResp.ok) {
                  const sampleData = await sampleResp.json();
                  const sourceCounter = {};
                  
                  for (const meta of sampleData.metadatas || []) {
                    if (meta) {
                      const source = meta.source || 'unknown';
                      sourceCounter[source] = (sourceCounter[source] || 0) + 1;
                    }
                  }
                  
                  chromaStats = {
                    collectionName: 'global-workflow-docs-v8-0-0',
                    totalDocuments: v8Count,
                    sampledDocuments: sampleData.metadatas?.length || 0,
                    sourceBreakdown: sourceCounter
                  };
                }
              }
            }
          }
        }
      } catch (err) {
        console.error('ChromaDB query error:', err.message);
      }

      // Also load the documentation sources config for reference (JSON format)
      const configPath = path.join(__dirname, '../../config/documentation_sources.json');
      let spotSources = [];
      
      try {
        const configContent = await fs.readFile(configPath, 'utf-8');
        const config = JSON.parse(configContent);
        spotSources = config.sources || [];
      } catch (err) {
        // Config may not be readable - continue without SPOT data
        console.error('[WARN] Could not read documentation_sources.json:', err.message);
      }

      let response = `# RAG Knowledge Base Ingested URLs\n\n`;
      response += `**Generated**: ${new Date().toISOString()}\n\n`;

      // Report actual ChromaDB ingestion status (PRIMARY SOURCE OF TRUTH)
      if (chromaStats) {
        response += `## Actual Ingestion Status (from ChromaDB)\n\n`;
        response += `**Collection**: ${chromaStats.collectionName}\n`;
        response += `**Total Documents**: ${chromaStats.totalDocuments.toLocaleString()}\n\n`;
        
        response += `### Sources by Document Count\n\n`;
        response += `| Source | Documents | % of Total |\n`;
        response += `|--------|-----------|------------|\n`;
        
        const sortedSources = Object.entries(chromaStats.sourceBreakdown)
          .sort(([,a], [,b]) => b - a);
        
        for (const [source, count] of sortedSources) {
          if (source_filter && !source.includes(source_filter)) continue;
          const pct = ((count / chromaStats.totalDocuments) * 100).toFixed(1);
          response += `| ${source} | ${count.toLocaleString()} | ${pct}% |\n`;
        }
        response += `\n`;
        
        // Cross-reference with SPOT config
        const ingestedSources = new Set(Object.keys(chromaStats.sourceBreakdown));
        const spotSourceNames = new Set(spotSources.map(s => s.name));
        
        response += `### SPOT Compliance\n\n`;
        let allPresent = true;
        for (const spot of spotSources.filter(s => s.enabled)) {
          const isIngested = ingestedSources.has(spot.name);
          const status = isIngested ? '✅' : '❌';
          const count = chromaStats.sourceBreakdown[spot.name] || 0;
          if (!isIngested) allPresent = false;
          response += `- ${status} **${spot.name}**: ${count} docs\n`;
        }
        response += `\n**All SPOT sources ingested**: ${allPresent ? '✅ Yes' : '❌ No'}\n\n`;
      }

      // Report on SPOT configuration sources
      if (spotSources.length > 0) {
        response += `## Configured Documentation Sources (SPOT v7.0.0)\n\n`;
        response += `| Source | URL | Status |\n`;
        response += `|--------|-----|--------|\n`;
        
        for (const source of spotSources) {
          if (source_filter && !source.name.includes(source_filter)) continue;
          const status = source.enabled ? '✅ Enabled' : '❌ Disabled';
          response += `| ${source.name} | ${source.url} | ${status} |\n`;
        }
        response += `\n`;
        
        const enabledCount = spotSources.filter(s => s.enabled).length;
        response += `**Total Sources**: ${spotSources.length} (${enabledCount} enabled)\n\n`;
      }

      if (format === 'urls_only') {
        const urls = spotSources
          .filter(s => s.enabled && (!source_filter || s.name.includes(source_filter)))
          .map(s => s.url);
        response = urls.join('\n');
      }

      return { content: [{ type: 'text', text: response }] };

    } catch (error) {
      return {
        content: [{ type: 'text', text: `Error listing ingested URLs: ${error.message}` }],
        isError: true
      };
    }
  }

  /**
   * Get a simple array of all ingested URLs for programmatic access
   * Migrated from Week 1 EnhancedRAGTools.js
   * Updated: Uses JSON config baked into container (security: no external file access)
   */
  async getIngestedURLsArray(args) {
    await this.ensureInitialized();
    const { include_failed = false } = args;

    try {
      // Load documentation sources from baked-in JSON config
      const configPath = path.join(__dirname, '../../config/documentation_sources.json');
      const configContent = await fs.readFile(configPath, 'utf-8');
      const config = JSON.parse(configContent);
      
      const sources = config.sources || [];
      const version = config.version || '7.0.0';

      const enabledSources = sources.filter(s => s.enabled);
      const disabledSources = sources.filter(s => !s.enabled);

      const result = {
        version: '7.0.0',
        generatedAt: new Date().toISOString(),
        totalSources: sources.length,
        enabledCount: enabledSources.length,
        disabledCount: disabledSources.length,
        enabledUrls: enabledSources.map(s => s.url),
        sources: enabledSources.map(s => ({ name: s.name, url: s.url }))
      };

      if (include_failed) {
        result.disabledUrls = disabledSources.map(s => s.url);
        result.disabledSources = disabledSources.map(s => ({ name: s.name, url: s.url }));
      }

      // Format as markdown for MCP response
      let output = `# Ingested URLs Array\n\n`;
      output += `**Version**: ${result.version}\n`;
      output += `**Generated**: ${result.generatedAt}\n`;
      output += `**Total Sources**: ${result.totalSources}\n`;
      output += `**Enabled**: ${result.enabledCount}\n`;
      output += `**Disabled**: ${result.disabledCount}\n\n`;
      
      output += `## Enabled URLs (${result.enabledUrls.length})\n\n`;
      output += `\`\`\`json\n${JSON.stringify(result.enabledUrls, null, 2)}\n\`\`\`\n\n`;
      
      output += `## Source Details\n\n`;
      output += `\`\`\`json\n${JSON.stringify(result.sources, null, 2)}\n\`\`\`\n`;

      if (include_failed && result.disabledUrls?.length > 0) {
        output += `\n## Disabled URLs (${result.disabledUrls.length})\n\n`;
        output += `\`\`\`json\n${JSON.stringify(result.disabledUrls, null, 2)}\n\`\`\`\n`;
      }

      return { content: [{ type: 'text', text: output }] };

    } catch (error) {
      return {
        content: [{ type: 'text', text: `Error getting URLs array: ${error.message}` }],
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
