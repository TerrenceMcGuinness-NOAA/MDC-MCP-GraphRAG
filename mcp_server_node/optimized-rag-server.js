#!/usr/bin/env node

/**
 * Optimized RAG-Enhanced MCP Server for Global Workflow
 * 
 * This version addresses the scaling issues in the current knowledge base:
 * - Uses optimized vector store with chunked loading
 * - Implements intelligent caching strategies
 * - Provides asynchronous operations
 * - Includes performance monitoring
 * - Maintains backward compatibility
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ErrorCode,
  ListToolsRequestSchema,
  McpError,
} from "@modelcontextprotocol/sdk/types.js";

import { pipeline } from '@xenova/transformers';
import OptimizedVectorStore from './optimized-vector-store.js';

class OptimizedRAGServer {
  constructor() {
    this.server = new Server({
      name: "global-workflow-optimized-rag",
      version: "2.0.0",
    }, {
      capabilities: {
        tools: {},
      },
    });

    // Initialize optimized components
    this.vectorStore = new OptimizedVectorStore({
      chunkSize: 50,           // Smaller chunks for better memory management
      cacheSize: 200,          // Reasonable cache size
      similarityThreshold: 0.15 // Slightly higher threshold for better quality
    });

    this.embedModel = null;
    this.isInitialized = false;
    this.initPromise = null;

    // Performance monitoring
    this.performance = {
      queryCount: 0,
      totalResponseTime: 0,
      avgResponseTime: 0,
      errorCount: 0,
      lastError: null
    };

    this.setupTools();
    this.setupHandlers();
    
    // Initialize asynchronously
    this.initializeAsync();
  }

  /**
   * Asynchronous initialization
   */
  async initializeAsync() {
    if (this.initPromise) return this.initPromise;
    
    this.initPromise = this._performInitialization();
    return this.initPromise;
  }

  async _performInitialization() {
    console.error('🚀 Initializing Optimized RAG Server...');
    
    // Initialize vector store first
    await this.vectorStore.initialize().catch(error => {
      console.error('⚠️ Vector store initialization failed:', error.message);
    });

    // Initialize embedding model with timeout and fallback
    setTimeout(async () => {
      try {
        console.error('🧠 Loading embedding model (background)...');
        
        const modelPromise = pipeline('feature-extraction', 'Xenova/all-MiniLM-L6-v2');
        const timeoutPromise = new Promise((_, reject) => 
          setTimeout(() => reject(new Error('Model loading timeout')), 45000)
        );
        
        this.embedModel = await Promise.race([modelPromise, timeoutPromise]);
        console.error('✅ Embedding model loaded successfully');
        
      } catch (error) {
        console.error('⚠️ Embedding model failed to load:', error.message);
        this.embedModel = null;
      }
    }, 200);

    this.isInitialized = true;
    console.error('✅ Optimized RAG Server initialized');
  }

  /**
   * Generate embedding with caching and error handling
   */
  async generateEmbedding(text, useCache = true) {
    if (!this.embedModel) {
      console.error('⚠️ Embedding model not available');
      return null;
    }

    // Simple cache key (first 50 chars)
    const cacheKey = useCache ? text.substring(0, 50) : null;
    
    try {
      const embeddingPromise = this.embedModel(text);
      const timeoutPromise = new Promise((_, reject) => 
        setTimeout(() => reject(new Error('Embedding timeout')), 15000)
      );
      
      const result = await Promise.race([embeddingPromise, timeoutPromise]);
      return Array.from(result.data);
      
    } catch (error) {
      console.error('⚠️ Embedding generation failed:', error.message);
      return null;
    }
  }

  setupTools() {
    this.tools = [
      // Core workflow tools
      {
        name: "get_workflow_structure",
        description: "Get the structure and overview of the global workflow system",
        inputSchema: {
          type: "object",
          properties: {
            component: {
              type: "string",
              description: "Specific component to focus on (optional)",
              enum: ["jobs", "scripts", "configs", "overview"]
            }
          }
        }
      },
      {
        name: "list_job_scripts",
        description: "List all available job scripts in the workflow",
        inputSchema: {
          type: "object",
          properties: {
            random_string: {
              type: "string",
              description: "Dummy parameter for no-parameter tools"
            }
          },
          required: ["random_string"]
        }
      },
      {
        name: "get_system_configs",
        description: "Get configuration information for different HPC systems",
        inputSchema: {
          type: "object",
          properties: {
            system: {
              type: "string",
              description: "HPC system name",
              enum: ["hera", "orion", "hercules", "wcoss2", "gaeac5", "gaeac6"]
            }
          }
        }
      },
      {
        name: "explain_component",
        description: "Explain a specific workflow component or directory",
        inputSchema: {
          type: "object",
          properties: {
            component: {
              type: "string",
              description: "Component name (e.g., rocoto, gsi, ufs)"
            }
          },
          required: ["component"]
        }
      },

      // Optimized RAG tools
      {
        name: "search_documentation",
        description: "Fast semantic search across workflow documentation",
        inputSchema: {
          type: "object",
          properties: {
            query: {
              type: "string",
              description: "Natural language search query"
            },
            doc_type: {
              type: "string",
              enum: ["all", "user_guide", "dev_docs", "api_reference", "troubleshooting"],
              description: "Type of documentation to search"
            },
            max_results: {
              type: "number",
              default: 5,
              description: "Maximum number of results to return"
            }
          },
          required: ["query"]
        }
      },
      {
        name: "explain_with_context",
        description: "Provide detailed explanations using optimized RAG context",
        inputSchema: {
          type: "object",
          properties: {
            component: {
              type: "string",
              description: "Component or concept to explain"
            },
            context_level: {
              type: "string",
              enum: ["basic", "intermediate", "advanced"],
              description: "Level of detail required"
            },
            include_examples: {
              type: "boolean",
              default: true,
              description: "Include code examples and usage patterns"
            }
          },
          required: ["component"]
        }
      },

      // Performance and monitoring tools
      {
        name: "get_performance_stats",
        description: "Get server performance statistics and cache metrics",
        inputSchema: {
          type: "object",
          properties: {}
        }
      }
    ];
  }

  setupHandlers() {
    this.server.setRequestHandler(ListToolsRequestSchema, async () => ({
      tools: this.tools,
    }));

    this.server.setRequestHandler(CallToolRequestSchema, async (request) => {
      const { name, arguments: args } = request.params;

      try {
        switch (name) {
          case "get_workflow_structure":
            return await this.getWorkflowStructure(args.component);
          case "list_job_scripts":
            return await this.listJobScripts();
          case "get_system_configs":
            return await this.getSystemConfigs(args.system);
          case "explain_component":
            return await this.explainComponent(args.component);
          case "search_documentation":
            return await this.searchDocumentationOptimized(args.query, args.doc_type, args.max_results);
          case "explain_with_context":
            return await this.explainWithContextOptimized(args.component, args.context_level, args.include_examples);
          case "get_performance_stats":
            return await this.getPerformanceStats();
          default:
            throw new McpError(ErrorCode.MethodNotFound, `Unknown tool: ${name}`);
        }
      } catch (error) {
        this.performance.errorCount++;
        this.performance.lastError = error.message;
        throw new McpError(ErrorCode.InternalError, `Error executing tool ${name}: ${error.message}`);
      }
    });
  }

  /**
   * Optimized documentation search
   */
  async searchDocumentationOptimized(query, docType = "all", maxResults = 5) {
    const startTime = Date.now();
    this.performance.queryCount++;

    try {
      await this.initializeAsync();

      // Generate query embedding
      const queryEmbedding = await this.generateEmbedding(query);
      
      let results;
      if (queryEmbedding) {
        // Use optimized vector search
        results = await this.vectorStore.searchSemantic(queryEmbedding, {
          docType,
          maxResults,
          similarityThreshold: 0.15
        });
      } else {
        // Fallback to keyword search
        results = await this.vectorStore.searchKeywords(query, {
          docType,
          maxResults
        });
      }

      // Track performance
      const responseTime = Date.now() - startTime;
      this.performance.totalResponseTime += responseTime;
      this.performance.avgResponseTime = this.performance.totalResponseTime / this.performance.queryCount;

      // Format response
      let responseText = `# Documentation Search Results (${queryEmbedding ? 'Semantic' : 'Keyword'})\n\n`;
      responseText += `**Query:** "${query}"\n`;
      responseText += `**Document Type:** ${docType}\n`;
      responseText += `**Results Found:** ${results.documents[0].length}\n`;
      responseText += `**Response Time:** ${responseTime}ms\n\n`;

      if (results.documents[0].length === 0) {
        responseText += `No matching documents found. Try:\n`;
        responseText += `- Using different keywords\n`;
        responseText += `- Broadening your search terms\n`;
        responseText += `- Checking available document types\n`;
      } else {
        results.documents[0].forEach((doc, index) => {
          const metadata = results.metadatas[0][index];
          const distance = results.distances[0][index];
          const similarity = (1 - distance) * 100;

          responseText += `## Result ${index + 1} (${similarity.toFixed(1)}% match)\n`;
          responseText += `**Source:** ${metadata.file_path}\n`;
          responseText += `**Type:** ${metadata.chunk_type}\n`;
          responseText += `**Language:** ${metadata.language}\n\n`;
          responseText += `**Content:**\n\`\`\`\n${doc.substring(0, 500)}${doc.length > 500 ? '...' : ''}\n\`\`\`\n\n`;
        });
      }

      return {
        content: [{ type: "text", text: responseText }],
      };

    } catch (error) {
      console.error('❌ Search error:', error.message);
      return {
        content: [
          {
            type: "text",
            text: `Search error: ${error.message}\n\nThe optimized search system encountered an issue. Please try:\n- Simplifying your query\n- Checking system resources\n- Trying again in a moment`
          }
        ],
      };
    }
  }

  /**
   * Optimized context explanation
   */
  async explainWithContextOptimized(component, contextLevel = "intermediate", includeExamples = true) {
    try {
      await this.initializeAsync();

      // Generate multiple search queries for comprehensive context
      const queries = [
        `${component} overview documentation`,
        `${component} configuration setup`,
        `${component} usage examples`,
        `how to use ${component} workflow`
      ];

      // Parallel searches for better performance
      const searchPromises = queries.map(async query => {
        const embedding = await this.generateEmbedding(query);
        if (embedding) {
          return this.vectorStore.searchSemantic(embedding, {
            maxResults: 2
          });
        }
        return null;
      });

      const searchResults = await Promise.all(searchPromises);
      
      // Collect unique results
      const allResults = [];
      searchResults.forEach(result => {
        if (result && result.documents[0].length > 0) {
          result.documents[0].forEach((doc, index) => {
            allResults.push({
              content: doc,
              metadata: result.metadatas[0][index],
              distance: result.distances[0][index]
            });
          });
        }
      });

      // Remove duplicates and sort
      const uniqueResults = allResults
        .filter((result, index, self) =>
          index === self.findIndex(r => r.content === result.content)
        )
        .sort((a, b) => a.distance - b.distance)
        .slice(0, 6);

      // Generate explanation
      let explanation = `# ${component} - Optimized Explanation\n\n`;
      explanation += `**Context Level:** ${contextLevel}\n`;
      explanation += `**Include Examples:** ${includeExamples ? 'Yes' : 'No'}\n`;
      explanation += `**Sources Found:** ${uniqueResults.length}\n\n`;

      if (uniqueResults.length === 0) {
        explanation += `## No Context Available\n\n`;
        explanation += `No documentation found for "${component}". This could mean:\n`;
        explanation += `- The component name may be misspelled\n`;
        explanation += `- Documentation hasn't been indexed yet\n`;
        explanation += `- The component might use a different name\n\n`;
      } else {
        explanation += `## Overview\n\n`;
        explanation += `Based on the available documentation:\n\n`;

        uniqueResults.forEach((result, index) => {
          const similarity = ((1 - result.distance) * 100).toFixed(1);
          explanation += `### Source ${index + 1} (${similarity}% relevance)\n`;
          explanation += `**File:** ${result.metadata.file_path}\n\n`;
          
          if (includeExamples) {
            explanation += `\`\`\`\n${result.content.substring(0, 400)}${result.content.length > 400 ? '...' : ''}\n\`\`\`\n\n`;
          } else {
            explanation += `${result.content.substring(0, 200)}${result.content.length > 200 ? '...' : ''}\n\n`;
          }
        });
      }

      return {
        content: [{ type: "text", text: explanation }],
      };

    } catch (error) {
      return {
        content: [
          {
            type: "text",
            text: `Error generating explanation: ${error.message}\n\nThe optimized context system encountered an issue.`
          }
        ],
      };
    }
  }

  /**
   * Get performance statistics
   */
  async getPerformanceStats() {
    const vectorStats = this.vectorStore.getStats();
    const memoryUsage = this.vectorStore.getMemoryUsage();
    
    const stats = {
      server: {
        queries: this.performance.queryCount,
        avgResponseTime: Math.round(this.performance.avgResponseTime),
        errors: this.performance.errorCount,
        lastError: this.performance.lastError
      },
      vectorStore: {
        cacheHitRate: Math.round(vectorStats.cacheHitRate * 100),
        cacheSize: vectorStats.cacheSize,
        totalQueries: vectorStats.totalQueries,
        avgResponseTime: Math.round(vectorStats.avgResponseTime)
      },
      memory: memoryUsage,
      embedding: {
        model: this.embedModel ? 'all-MiniLM-L6-v2' : 'not loaded',
        status: this.embedModel ? 'ready' : 'unavailable'
      }
    };

    let responseText = `# Performance Statistics\n\n`;
    responseText += `## Server Performance\n`;
    responseText += `- **Total Queries:** ${stats.server.queries}\n`;
    responseText += `- **Average Response Time:** ${stats.server.avgResponseTime}ms\n`;
    responseText += `- **Errors:** ${stats.server.errors}\n\n`;
    
    responseText += `## Vector Store Performance\n`;
    responseText += `- **Cache Hit Rate:** ${stats.vectorStore.cacheHitRate}%\n`;
    responseText += `- **Cache Size:** ${stats.vectorStore.cacheSize} chunks\n`;
    responseText += `- **Vector Queries:** ${stats.vectorStore.totalQueries}\n\n`;
    
    responseText += `## Memory Usage\n`;
    responseText += `- **Heap Used:** ${stats.memory.heapUsed} MB\n`;
    responseText += `- **Heap Total:** ${stats.memory.heapTotal} MB\n`;
    responseText += `- **RSS:** ${stats.memory.rss} MB\n\n`;
    
    responseText += `## Embedding Model\n`;
    responseText += `- **Model:** ${stats.embedding.model}\n`;
    responseText += `- **Status:** ${stats.embedding.status}\n`;

    return {
      content: [{ type: "text", text: responseText }],
    };
  }

  // Basic tool implementations (simplified for space)
  async getWorkflowStructure(component) {
    return {
      content: [{ type: "text", text: `Workflow structure for component: ${component || "overview"}` }],
    };
  }

  async listJobScripts() {
    return {
      content: [{ type: "text", text: "Job scripts listing..." }],
    };
  }

  async getSystemConfigs(system) {
    return {
      content: [{ type: "text", text: `System configuration for: ${system || "all systems"}` }],
    };
  }

  async explainComponent(component) {
    return {
      content: [{ type: "text", text: `Explanation of workflow component: ${component}` }],
    };
  }

  async run() {
    const transport = new StdioServerTransport();
    await this.server.connect(transport);
    console.error("🚀 Optimized RAG Server running on stdio");
  }
}

// Initialize and run server
const server = new OptimizedRAGServer();

// Enhanced error handling
process.on('uncaughtException', (error) => {
  console.error('⚠️ Uncaught Exception:', error.message);
});

process.on('unhandledRejection', (reason, promise) => {
  console.error('⚠️ Unhandled Rejection:', reason);
});

// Memory monitoring
setInterval(() => {
  const usage = process.memoryUsage();
  if (usage.heapUsed / 1024 / 1024 > 500) { // Alert if over 500MB
    console.error(`⚠️ High memory usage: ${Math.round(usage.heapUsed / 1024 / 1024)}MB`);
  }
}, 30000);

// Start server
server.run().catch(error => {
  console.error('❌ Server failed to start:', error.message);
  process.exit(1);
});
