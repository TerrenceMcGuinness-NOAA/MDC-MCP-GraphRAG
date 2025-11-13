#!/usr/bin/env node

/**
 * RAG-Enhanced MCP Server for Global Workflow
 * Extends the basic MCP server with Retrieval-Augmented Generation capabilities
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ErrorCode,
  ListToolsRequestSchema,
  McpError,
} from "@modelcontextprotocol/sdk/types.js";

// Removed unused imports for cleaner diagnostics

// Import RAG components
import { ChromaClient } from 'chromadb';
import { pipeline } from '@xenova/transformers';

class RAGEnhancedMCPServer {
  constructor() {
    this.server = new Server({
      name: "global-workflow-rag-mcp",
      version: "1.0.0",
    }, {
      capabilities: {
        tools: {},
      },
    });

    // Initialize vector database connection (in-memory for testing)
    this.chromaClient = new ChromaClient();
    this.collection = null;
    this.embedModel = null;

    // Initialize components
    this.initializeRAG();

    this.setupTools();
    this.setupHandlers();
  }

  async initializeRAG() {
    // Initialize RAG components asynchronously without blocking server startup
    console.error('🔄 Initializing RAG components in background...');
    
    // Use setTimeout to ensure server starts immediately
    setTimeout(async () => {
      try {
        // Initialize embedding model with timeout protection
        console.error('🧠 Loading embedding model...');
        const modelPromise = pipeline('feature-extraction', 'Xenova/all-MiniLM-L6-v2');
        const timeoutPromise = new Promise((_, reject) => 
          setTimeout(() => reject(new Error('Model loading timeout')), 30000)
        );
        
        this.embedModel = await Promise.race([modelPromise, timeoutPromise]);
        console.error('✓ Embedding model initialized successfully');

        // Try to initialize ChromaDB collection (graceful fallback if not available)
        try {
          const collectionPromise = this.chromaClient.getOrCreateCollection({
            name: 'global-workflow-docs'
          });
          const dbTimeoutPromise = new Promise((_, reject) => 
            setTimeout(() => reject(new Error('ChromaDB timeout')), 5000)
          );
          
          this.collection = await Promise.race([collectionPromise, dbTimeoutPromise]);
          console.error('✓ ChromaDB collection initialized successfully');
        } catch (chromaError) {
          console.error('⚠ Vector database not available, running in local mode:', chromaError.message);
          this.collection = null;
        }

        console.error('✓ RAG components initialized successfully');
      } catch (error) {
        console.error('⚠ RAG initialization failed, server continues with basic functionality:', error.message);
        this.embedModel = null;
        this.collection = null;
      }
    }, 100); // Minimal delay to allow server to start
  }

  async generateEmbedding(text) {
    if (!this.embedModel) {
      // Return null instead of throwing - graceful degradation
      console.error('⚠ Embedding model not available, skipping semantic search');
      return null;
    }

    try {
      // Add timeout for embedding generation
      const embeddingPromise = this.embedModel(text);
      const timeoutPromise = new Promise((_, reject) => 
        setTimeout(() => reject(new Error('Embedding generation timeout')), 10000)
      );
      
      const result = await Promise.race([embeddingPromise, timeoutPromise]);
      return Array.from(result.data);
    } catch (error) {
      console.error('⚠ Failed to generate embedding, continuing without semantic search:', error.message);
      return null; // Graceful degradation
    }
  }

  // Local vector search using pre-computed embeddings
  async localVectorSearch(queryEmbedding, docType = "all", maxResults = 5) {
    const fs = await import('fs/promises');
    const path = await import('path');
    const { fileURLToPath } = await import('url');
    
    try {
      // Get the directory where this script is located
      const __filename = fileURLToPath(import.meta.url);
      const __dirname = path.dirname(__filename);
      
      // Load pre-computed embeddings from the correct path
      const chunksPath = path.join(__dirname, 'knowledge-base', 'chunks_with_embeddings.json');
      const chunksData = await fs.readFile(chunksPath, 'utf8');
      const chunks = JSON.parse(chunksData);
      
      // Calculate similarity scores
      const similarities = chunks.map(chunk => {
        if (!chunk.embedding || chunk.embedding.length === 0) {
          return { chunk, similarity: 0 };
        }
        
        // Filter by document type if specified
        if (docType !== "all" && chunk.metadata?.type !== docType) {
          return { chunk, similarity: 0 };
        }
        
        const similarity = this.cosineSimilarity(queryEmbedding, chunk.embedding);
        return { chunk, similarity };
      });
      
      // Sort by similarity and take top results
      const topResults = similarities
        .filter(item => item.similarity > 0.1) // Minimum relevance threshold
        .sort((a, b) => b.similarity - a.similarity)
        .slice(0, maxResults);
      
      // Format results to match ChromaDB format
      const documents = [topResults.map(item => item.chunk.content)];
      const distances = [topResults.map(item => 1 - item.similarity)];
      const metadatas = [topResults.map(item => ({
        file_path: item.chunk.metadata?.source || 'unknown',
        chunk_type: item.chunk.metadata?.type || 'unknown',
        language: item.chunk.metadata?.extension || 'unknown'
      }))];
      
      return { documents, distances, metadatas };
      
    } catch (error) {
      console.error('Local vector search failed:', error.message);
      return { documents: [[]], distances: [[]], metadatas: [[]] };
    }
  }
  
  // Cosine similarity calculation
  cosineSimilarity(vecA, vecB) {
    if (vecA.length !== vecB.length) return 0;
    
    let dotProduct = 0;
    let normA = 0;
    let normB = 0;
    
    for (let i = 0; i < vecA.length; i++) {
      dotProduct += vecA[i] * vecB[i];
      normA += vecA[i] * vecA[i];
      normB += vecB[i] * vecB[i];
    }
    
    normA = Math.sqrt(normA);
    normB = Math.sqrt(normB);
    
    if (normA === 0 || normB === 0) return 0;
    return dotProduct / (normA * normB);
  }
  
  // Fallback keyword search when embeddings unavailable
  async fallbackKeywordSearch(query, docType = "all", maxResults = 5) {
    const fs = await import('fs/promises');
    const path = await import('path');
    const { fileURLToPath } = await import('url');
    
    try {
      // Get the directory where this script is located
      const __filename = fileURLToPath(import.meta.url);
      const __dirname = path.dirname(__filename);
      
      const chunksPath = path.join(__dirname, 'knowledge-base', 'chunks.json');
      const chunksData = await fs.readFile(chunksPath, 'utf8');
      const chunks = JSON.parse(chunksData);
      
      const queryTerms = query.toLowerCase().split(/\s+/);
      
      const matches = chunks
        .map(chunk => {
          if (docType !== "all" && chunk.metadata?.type !== docType) {
            return { chunk, score: 0 };
          }
          
          const content = chunk.content.toLowerCase();
          const score = queryTerms.reduce((acc, term) => {
            const matches = (content.match(new RegExp(term, 'g')) || []).length;
            return acc + matches;
          }, 0);
          
          return { chunk, score };
        })
        .filter(item => item.score > 0)
        .sort((a, b) => b.score - a.score)
        .slice(0, maxResults);
      
      let responseText = `# Documentation Search Results (Keyword Search)\n\n`;
      responseText += `**Query:** "${query}"\n`;
      responseText += `**Document Type:** ${docType}\n`;
      responseText += `**Results Found:** ${matches.length}\n\n`;
      
      matches.forEach((match, index) => {
        responseText += `## Result ${index + 1} (${match.score} keyword matches)\n`;
        responseText += `**Source:** ${match.chunk.metadata?.source || 'unknown'}\n`;
        responseText += `**Type:** ${match.chunk.metadata?.type || 'unknown'}\n\n`;
        responseText += `**Content:**\n\`\`\`\n${match.chunk.content}\n\`\`\`\n\n`;
      });
      
      return {
        content: [{ type: "text", text: responseText }],
      };
      
    } catch (error) {
      return {
        content: [
          {
            type: "text",
            text: `Error in fallback search: ${error.message}`,
          },
        ],
      };
    }
  }

  setupTools() {
    // Original tools from basic MCP server
    const originalTools = [
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
          properties: {}
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
      }
    ];

    // New RAG-enhanced tools
    const ragTools = [
      {
        name: "search_documentation",
        description: "Semantic search across workflow documentation using RAG",
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
        description: "Provide detailed explanations using RAG-enhanced context",
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
      {
        name: "find_similar_code",
        description: "Find similar code patterns and implementations using vector similarity",
        inputSchema: {
          type: "object",
          properties: {
            code_snippet: {
              type: "string",
              description: "Code snippet to find similarities for"
            },
            language: {
              type: "string",
              enum: ["bash", "python", "cmake", "any"],
              description: "Programming language filter"
            },
            similarity_threshold: {
              type: "number",
              default: 0.7,
              description: "Minimum similarity score (0.0-1.0)"
            }
          },
          required: ["code_snippet"]
        }
      },
      {
        name: "get_operational_guidance",
        description: "Get operational procedures and best practices from knowledge base",
        inputSchema: {
          type: "object",
          properties: {
            task: {
              type: "string",
              description: "Operational task or procedure"
            },
            system: {
              type: "string",
              enum: ["hera", "orion", "hercules", "wcoss2", "gaeac5", "gaeac6"],
              description: "Target HPC system"
            },
            urgency: {
              type: "string",
              enum: ["routine", "urgent", "emergency"],
              description: "Urgency level for guidance"
            }
          },
          required: ["task"]
        }
      },
      {
        name: "analyze_dependencies",
        description: "Analyze and explain workflow job dependencies using graph knowledge",
        inputSchema: {
          type: "object",
          properties: {
            job_name: {
              type: "string",
              description: "Job name to analyze dependencies for"
            },
            direction: {
              type: "string",
              enum: ["upstream", "downstream", "both"],
              description: "Direction of dependency analysis"
            },
            depth: {
              type: "number",
              default: 2,
              description: "Depth of dependency traversal"
            }
          },
          required: ["job_name"]
        }
      }
    ];

    this.tools = [...originalTools, ...ragTools];
  }

  setupHandlers() {
    this.server.setRequestHandler(ListToolsRequestSchema, async () => ({
      tools: this.tools,
    }));

    this.server.setRequestHandler(CallToolRequestSchema, async (request) => {
      const { name, arguments: args } = request.params;

      try {
        switch (name) {
          // Original tool implementations (from basic MCP server)
          case "get_workflow_structure":
            return await this.getWorkflowStructure(args.component);
          case "list_job_scripts":
            return await this.listJobScripts();
          case "get_system_configs":
            return await this.getSystemConfigs(args.system);
          case "explain_component":
            return await this.explainWorkflowComponent(args.component);

          // New RAG-enhanced tool implementations
          case "search_documentation":
            return await this.searchDocumentation(args.query, args.doc_type, args.max_results);
          case "explain_with_context":
            return await this.explainWithContext(args.component, args.context_level, args.include_examples);
          case "find_similar_code":
            return await this.findSimilarCode(args.code_snippet, args.language, args.similarity_threshold);
          case "get_operational_guidance":
            return await this.getOperationalGuidance(args.task, args.system, args.urgency);
          case "analyze_dependencies":
            return await this.analyzeWorkflowDependencies(args.job_name, args.direction, args.depth);

          default:
            throw new McpError(ErrorCode.MethodNotFound, `Unknown tool: ${name}`);
        }
      } catch (error) {
        throw new McpError(ErrorCode.InternalError, `Error executing tool ${name}: ${error.message}`);
      }
    });
  }

  // RAG-enhanced tool implementations
  async searchDocumentation(query, docType = "all", maxResults = 5) {
    try {
      // Generate embedding for query
      const queryEmbedding = await this.generateEmbedding(query);
      
      if (!queryEmbedding) {
        return this.fallbackKeywordSearch(query, docType, maxResults);
      }

      let results;
      
      // Try ChromaDB server first, fall back to local search
      if (this.collection) {
        // Build metadata filter if docType is specified
        let whereClause = {};
        if (docType !== "all") {
          whereClause = { type: docType };
        }

        // Search vector database
        results = await this.collection.query({
          queryEmbeddings: [queryEmbedding],
          nResults: maxResults,
          where: Object.keys(whereClause).length > 0 ? whereClause : undefined
        });
      } else {
        // Local mode: search pre-computed embeddings
        results = await this.localVectorSearch(queryEmbedding, docType, maxResults);
      }

      // Format results
      let responseText = `# Documentation Search Results\n\n`;
      responseText += `**Query:** "${query}"\n`;
      responseText += `**Document Type:** ${docType}\n`;
      responseText += `**Results Found:** ${results.documents[0].length}\n\n`;

      if (results.documents[0].length === 0) {
        responseText += `No matching documents found. Try:\n`;
        responseText += `- Using different keywords\n`;
        responseText += `- Broadening your search terms\n`;
        responseText += `- Checking if documentation has been ingested\n`;
      } else {
        results.documents[0].forEach((doc, index) => {
          const metadata = results.metadatas[0][index];
          const distance = results.distances[0][index];
          const similarity = (1 - distance) * 100;

          responseText += `## Result ${index + 1} (${similarity.toFixed(1)}% match)\n`;
          responseText += `**Source:** ${metadata.file_path}\n`;
          responseText += `**Type:** ${metadata.chunk_type}\n`;
          responseText += `**Language:** ${metadata.language}\n\n`;
          responseText += `**Content:**\n\`\`\`\n${doc}\n\`\`\`\n\n`;
        });
      }

      return {
        content: [{ type: "text", text: responseText }],
      };
    } catch (error) {
      return {
        content: [
          {
            type: "text",
            text: `Error searching documentation: ${error.message}\n\n` +
                  `Please ensure:\n` +
                  `- Vector database is running\n` +
                  `- Documents have been ingested\n` +
                  `- Network connectivity is available`
          }
        ],
      };
    }
  }

  async explainWithContext(component, contextLevel = "intermediate", includeExamples = true) {
    try {
      if (!this.collection) {
        throw new Error('Vector database not initialized');
      }

      // Search for relevant context about the component
      const contextQueries = [
        `${component} documentation`,
        `${component} configuration`,
        `${component} usage examples`,
        `how to use ${component}`,
        `${component} workflow`
      ];

      let allResults = [];

      // Gather context from multiple queries
      for (const query of contextQueries) {
        try {
          const queryEmbedding = await this.generateEmbedding(query);
          const results = await this.collection.query({
            queryEmbeddings: [queryEmbedding],
            nResults: 3
          });

          if (results.documents[0].length > 0) {
            allResults.push(...results.documents[0].map((doc, index) => ({
              content: doc,
              metadata: results.metadatas[0][index],
              distance: results.distances[0][index]
            })));
          }
        } catch (error) {
          console.error(`Error querying for ${query}:`, error.message);
        }
      }

      // Remove duplicates and sort by relevance
      const uniqueResults = allResults
        .filter((result, index, self) =>
          index === self.findIndex(r => r.content === result.content)
        )
        .sort((a, b) => a.distance - b.distance)
        .slice(0, 8);

      // Generate comprehensive explanation
      let explanation = `# ${component} - Comprehensive Explanation\n\n`;
      explanation += `**Context Level:** ${contextLevel}\n`;
      explanation += `**Include Examples:** ${includeExamples ? 'Yes' : 'No'}\n\n`;

      if (uniqueResults.length === 0) {
        explanation += `## No Context Found\n\n`;
        explanation += `No documentation or examples found for "${component}". This could mean:\n\n`;
        explanation += `- The component name may be misspelled\n`;
        explanation += `- Documentation hasn't been ingested yet\n`;
        explanation += `- The component might be referenced by a different name\n\n`;
        explanation += `Try searching for related terms or check the available components.`;
      } else {
        explanation += `## Overview\n\n`;
        explanation += `Based on the available documentation, here's what we know about ${component}:\n\n`;

        // Group results by type
        const byType = {};
        uniqueResults.forEach(result => {
          const type = result.metadata.chunk_type || 'general';
          if (!byType[type]) byType[type] = [];
          byType[type].push(result);
        });

        // Present organized explanation
        Object.keys(byType).forEach(type => {
          explanation += `### ${type.charAt(0).toUpperCase() + type.slice(1)} Information\n\n`;

          byType[type].forEach((result) => {
            const similarity = ((1 - result.distance) * 100).toFixed(1);
            explanation += `**Source:** ${result.metadata.file_path} (${similarity}% relevance)\n\n`;

            if (includeExamples || contextLevel === 'advanced') {
              explanation += `\`\`\`${result.metadata.language || 'text'}\n`;
              explanation += `${result.content.substring(0, 500)}${result.content.length > 500 ? '...' : ''}\n`;
              explanation += `\`\`\`\n\n`;
            } else {
              explanation += `${result.content.substring(0, 200)}${result.content.length > 200 ? '...' : ''}\n\n`;
            }
          });
        });

        // Add usage recommendations
        explanation += `## Usage Recommendations\n\n`;
        if (contextLevel === 'basic') {
          explanation += `For basic usage of ${component}, refer to the documentation above. `;
          explanation += `Start with the configuration examples and follow the provided patterns.\n\n`;
        } else if (contextLevel === 'advanced') {
          explanation += `For advanced usage, consider:\n`;
          explanation += `- Reviewing all configuration options in the source files\n`;
          explanation += `- Understanding dependencies and workflow integration\n`;
          explanation += `- Checking system-specific implementations\n`;
          explanation += `- Following best practices from operational procedures\n\n`;
        }
      }

      return {
        content: [{ type: "text", text: explanation }],
      };
    } catch (error) {
      return {
        content: [
          {
            type: "text",
            text: `Error generating explanation: ${error.message}\n\n` +
                  `Please ensure the RAG system is properly initialized and try again.`
          }
        ],
      };
    }
  }

  async findSimilarCode(codeSnippet, language = "any", similarityThreshold = 0.7) {
    // TODO: Implement code similarity search
    // 1. Generate embedding for code snippet
    // 2. Search code vector database
    // 3. Filter by language and similarity threshold
    // 4. Return similar code patterns with explanations

    return {
      content: [
        {
          type: "text",
          text: `Code Similarity Search Results\n\n` +
                `Query: ${codeSnippet.substring(0, 100)}...\n` +
                `Language Filter: ${language}\n` +
                `Similarity Threshold: ${similarityThreshold}\n\n` +
                `[This would return similar code patterns with:\n` +
                `- Similarity scores\n` +
                `- Source file locations\n` +
                `- Usage context\n` +
                `- Functional explanations]`
        }
      ],
    };
  }

  async getOperationalGuidance(task, system, urgency = "routine") {
    // TODO: Implement operational guidance retrieval
    // 1. Search operational procedures database
    // 2. Filter by system and urgency
    // 3. Provide step-by-step guidance
    // 4. Include troubleshooting information

    return {
      content: [
        {
          type: "text",
          text: `Operational Guidance for: ${task}\n\n` +
                `Target System: ${system || "All systems"}\n` +
                `Urgency Level: ${urgency}\n\n` +
                `[This would provide operational guidance with:\n` +
                `- Step-by-step procedures\n` +
                `- System-specific instructions\n` +
                `- Troubleshooting steps\n` +
                `- Contact information for escalation]`
        }
      ],
    };
  }

  async analyzeWorkflowDependencies(jobName, direction = "both", depth = 2) {
    // TODO: Implement dependency analysis
    // 1. Parse workflow configurations
    // 2. Build dependency graph
    // 3. Traverse dependencies in specified direction
    // 4. Provide analysis and visualization

    return {
      content: [
        {
          type: "text",
          text: `Workflow Dependency Analysis for: ${jobName}\n\n` +
                `Analysis Direction: ${direction}\n` +
                `Traversal Depth: ${depth}\n\n` +
                `[This would provide dependency analysis with:\n` +
                `- Dependency graph visualization\n` +
                `- Critical path analysis\n` +
                `- Potential bottlenecks\n` +
                `- Impact assessment]`
        }
      ],
    };
  }

  // Original tool implementations (simplified versions)
  async getWorkflowStructure(component) {
    // Implement original functionality...
    return {
      content: [
        {
          type: "text",
          text: `Workflow structure for component: ${component || "overview"}`
        }
      ],
    };
  }

  async listJobScripts() {
    // Implement original functionality...
    return {
      content: [
        {
          type: "text",
          text: "Job scripts listing..."
        }
      ],
    };
  }

  async getSystemConfigs(system) {
    // Implement original functionality...
    return {
      content: [
        {
          type: "text",
          text: `System configuration for: ${system || "all systems"}`
        }
      ],
    };
  }

  async explainWorkflowComponent(component) {
    // Implement original functionality...
    return {
      content: [
        {
          type: "text",
          text: `Explanation of workflow component: ${component}`
        }
      ],
    };
  }

  async run() {
    const transport = new StdioServerTransport();
    await this.server.connect(transport);
    console.error("RAG-Enhanced Global Workflow MCP Server running on stdio");
  }
}

// Initialize and run the server with proper error handling
const server = new RAGEnhancedMCPServer();

// Add process-level error handlers for stability
process.on('uncaughtException', (error) => {
  console.error('⚠ Uncaught Exception:', error.message);
  // Don't exit - try to continue serving
});

process.on('unhandledRejection', (reason, promise) => {
  console.error('⚠ Unhandled Rejection at:', promise, 'reason:', reason);
  // Don't exit - try to continue serving
});

// Start server with retry mechanism
async function startServerWithRetry() {
  let retries = 0;
  const maxRetries = 3;
  
  while (retries < maxRetries) {
    try {
      await server.run();
      break; // Success
    } catch (error) {
      retries++;
      console.error(`⚠ Server start attempt ${retries} failed:`, error.message);
      
      if (retries >= maxRetries) {
        console.error('❌ Max retries reached. Server cannot start.');
        process.exit(1);
      }
      
      // Wait before retry
      await new Promise(resolve => setTimeout(resolve, 1000 * retries));
    }
  }
}

startServerWithRetry();
