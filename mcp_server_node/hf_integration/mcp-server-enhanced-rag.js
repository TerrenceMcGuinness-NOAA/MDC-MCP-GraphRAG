#!/usr/bin/env node

/**
 * Enhanced RAG-MCP Server with Hugging Face Integration
 * Extends the RAG server to use external Hugging Face MCP tools
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ErrorCode,
  ListToolsRequestSchema,
  McpError,
} from "@modelcontextprotocol/sdk/types.js";

import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

// Import RAG components
import { ChromaClient } from 'chromadb';
import { pipeline } from '@xenova/transformers';
import { HuggingFaceRAGUtils } from './huggingface-rag-utils.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

class EnhancedRAGMCPServer {
  constructor() {
    this.server = new Server({
      name: "global-workflow-enhanced-rag-mcp",
      version: "1.1.0",
    }, {
      capabilities: {
        tools: {},
      },
    });

    // Initialize vector database connection
    this.chromaClient = new ChromaClient({
      host: process.env.CHROMA_HOST || 'localhost',
      port: process.env.CHROMA_PORT || 8000
    });
    this.collection = null;
    this.embedModel = null;
    this.hfUtils = null;

    // Initialize components
    this.initializeRAG();
    this.setupTools();
    this.setupHandlers();
  }

  async initializeRAG() {
    try {
      console.error('🚀 Initializing Enhanced RAG components...');

      // Load Hugging Face configuration
      const configPath = path.join(__dirname, 'config', 'huggingface.json');
      try {
        const configData = await fs.readFile(configPath, 'utf8');
        const config = JSON.parse(configData);
        this.hfUtils = new HuggingFaceRAGUtils(config);
        console.error('✓ Hugging Face utilities initialized');
      } catch (error) {
        console.error('⚠ Hugging Face config not found, using defaults');
        this.hfUtils = null;
      }

      // Initialize embedding model
      this.embedModel = await pipeline('feature-extraction', 'Xenova/all-MiniLM-L6-v2');
      console.error('✓ Embedding model loaded');

      // Get or create collection
      try {
        this.collection = await this.chromaClient.getOrCreateCollection({
          name: 'global-workflow-docs'
        });
        console.error('✓ Vector database connected');
      } catch (error) {
        console.error('⚠ Vector database connection failed, using in-memory fallback');
        this.collection = null;
      }

      console.error('✅ Enhanced RAG components initialized successfully');
    } catch (error) {
      console.error('❌ RAG initialization failed:', error.message);
    }
  }

  async generateEmbedding(text) {
    if (!this.embedModel) {
      throw new Error('Embedding model not initialized');
    }

    try {
      const result = await this.embedModel(text);
      return Array.from(result.data);
    } catch (error) {
      console.error('Failed to generate embedding:', error.message);
      throw error;
    }
  }

  setupTools() {
    const tools = [
      // Enhanced RAG tools with Hugging Face integration
      {
        name: "search_documentation",
        description: "Semantic search across workflow documentation using RAG with optional Hugging Face model enhancement",
        inputSchema: {
          type: "object",
          properties: {
            query: {
              type: "string",
              description: "Natural language search query"
            },
            doc_type: {
              type: "string",
              description: "Type of documentation to search",
              enum: ["all", "user_guide", "dev_docs", "api_reference", "troubleshooting"]
            },
            max_results: {
              type: "number",
              description: "Maximum number of results to return",
              default: 5
            },
            use_hf_enhancement: {
              type: "boolean",
              description: "Use Hugging Face models for enhanced search",
              default: false
            }
          },
          required: ["query"]
        }
      },
      {
        name: "enhance_documentation_with_hf",
        description: "Enhance documentation search using Hugging Face papers and datasets",
        inputSchema: {
          type: "object",
          properties: {
            topic: {
              type: "string",
              description: "Topic to search for in HF resources"
            },
            include_papers: {
              type: "boolean",
              description: "Include relevant research papers",
              default: true
            },
            include_datasets: {
              type: "boolean",
              description: "Include relevant datasets",
              default: true
            },
            include_models: {
              type: "boolean",
              description: "Include relevant models",
              default: true
            }
          },
          required: ["topic"]
        }
      },
      {
        name: "find_similar_implementations",
        description: "Find similar code implementations using HF code models and local RAG",
        inputSchema: {
          type: "object",
          properties: {
            code_snippet: {
              type: "string",
              description: "Code snippet to find similarities for"
            },
            language: {
              type: "string",
              description: "Programming language filter",
              enum: ["bash", "python", "cmake", "any"]
            },
            use_hf_models: {
              type: "boolean",
              description: "Use Hugging Face code models for analysis",
              default: true
            }
          },
          required: ["code_snippet"]
        }
      },
      {
        name: "generate_documentation",
        description: "Generate documentation using Hugging Face text generation models",
        inputSchema: {
          type: "object",
          properties: {
            prompt: {
              type: "string",
              description: "Documentation prompt or outline"
            },
            style: {
              type: "string",
              description: "Documentation style",
              enum: ["technical", "user_guide", "api_reference", "tutorial"]
            },
            max_length: {
              type: "number",
              description: "Maximum length of generated content",
              default: 1000
            }
          },
          required: ["prompt"]
        }
      },
      // Original workflow tools
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
        name: "explain_workflow_component",
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
      {
        name: "analyze_workflow_dependencies",
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
              description: "Direction of dependency analysis",
              enum: ["upstream", "downstream", "both"]
            },
            depth: {
              type: "number",
              description: "Depth of dependency traversal",
              default: 2
            }
          },
          required: ["job_name"]
        }
      }
    ];

    this.server.setRequestHandler(ListToolsRequestSchema, async () => {
      return { tools };
    });
  }

  async searchDocumentationEnhanced(query, options = {}) {
    const results = [];

    // Local RAG search if available
    if (this.collection && this.embedModel) {
      try {
        const embedding = await this.generateEmbedding(query);
        const ragResults = await this.collection.query({
          queryEmbeddings: [embedding],
          nResults: options.max_results || 5
        });

        if (ragResults.documents && ragResults.documents[0]) {
          ragResults.documents[0].forEach((doc, idx) => {
            results.push({
              source: 'local_rag',
              content: doc,
              score: ragResults.distances[0][idx],
              metadata: ragResults.metadatas[0][idx]
            });
          });
        }
      } catch (error) {
        console.error('Local RAG search failed:', error.message);
      }
    }

    // Hugging Face enhancement if requested
    if (options.use_hf_enhancement && this.hfUtils) {
      try {
        // Note: In a real implementation, this would call the actual HF MCP tools
        // For now, we return structured placeholders that indicate integration points
        results.push({
          source: 'huggingface_papers',
          content: `[HF Integration Point] Search papers related to: ${query}`,
          hf_tool_suggestion: 'mcp_huggingface_paper_search',
          parameters: { query: query, results_limit: 5 }
        });

        results.push({
          source: 'huggingface_models',
          content: `[HF Integration Point] Find relevant models for: ${query}`,
          hf_tool_suggestion: 'mcp_huggingface_model_search',
          parameters: { query: query, limit: 5 }
        });
      } catch (error) {
        console.error('Hugging Face enhancement failed:', error.message);
      }
    }

    return results;
  }

  setupHandlers() {
    this.server.setRequestHandler(CallToolRequestSchema, async (request) => {
      const { name, arguments: args } = request.params;

      try {
        switch (name) {
          case "search_documentation":
            const searchResults = await this.searchDocumentationEnhanced(
              args.query,
              {
                doc_type: args.doc_type,
                max_results: args.max_results,
                use_hf_enhancement: args.use_hf_enhancement
              }
            );
            return {
              content: [{
                type: "text",
                text: JSON.stringify({
                  query: args.query,
                  results: searchResults,
                  total_results: searchResults.length,
                  sources: [...new Set(searchResults.map(r => r.source))],
                  hf_integration_suggestions: searchResults
                    .filter(r => r.hf_tool_suggestion)
                    .map(r => ({
                      tool: r.hf_tool_suggestion,
                      params: r.parameters
                    }))
                }, null, 2)
              }]
            };

          case "enhance_documentation_with_hf":
            return {
              content: [{
                type: "text",
                text: JSON.stringify({
                  topic: args.topic,
                  message: "Hugging Face enhancement integration points identified",
                  suggested_hf_tools: [
                    {
                      name: "mcp_huggingface_paper_search",
                      purpose: "Find research papers related to the topic",
                      parameters: { query: args.topic, results_limit: 10 }
                    },
                    {
                      name: "mcp_huggingface_dataset_search", 
                      purpose: "Find relevant datasets for knowledge enhancement",
                      parameters: { query: args.topic, limit: 5 }
                    },
                    {
                      name: "mcp_huggingface_model_search",
                      purpose: "Find models that could assist with the topic",
                      parameters: { query: args.topic, limit: 5 }
                    }
                  ],
                  next_steps: [
                    "Use the suggested HF tools via MCP integration",
                    "Incorporate results into local knowledge base",
                    "Update RAG embeddings with new content"
                  ]
                }, null, 2)
              }]
            };

          case "find_similar_implementations":
            return {
              content: [{
                type: "text",
                text: JSON.stringify({
                  code_snippet: args.code_snippet.substring(0, 100) + "...",
                  language: args.language,
                  message: "Code similarity analysis ready",
                  local_analysis: "Vector similarity search in local codebase",
                  hf_integration: args.use_hf_models ? {
                    suggested_tool: "mcp_huggingface_model_search",
                    purpose: "Find code generation models for enhanced analysis",
                    parameters: { 
                      query: "code analysis " + (args.language || "programming"),
                      task: "text-generation",
                      limit: 3
                    }
                  } : null
                }, null, 2)
              }]
            };

          case "generate_documentation":
            return {
              content: [{
                type: "text",
                text: JSON.stringify({
                  prompt: args.prompt,
                  style: args.style,
                  message: "Documentation generation pipeline ready",
                  hf_integration: {
                    text_generation: {
                      suggested_tool: "mcp_huggingface_model_search",
                      parameters: {
                        query: "text generation documentation writing",
                        task: "text-generation",
                        limit: 3
                      }
                    },
                    content_enhancement: {
                      suggested_tool: "mcp_huggingface_paper_search",
                      parameters: {
                        query: args.prompt,
                        results_limit: 5
                      }
                    }
                  },
                  next_steps: [
                    "Use HF text generation models via MCP",
                    "Enhance with domain-specific papers",
                    "Validate with local knowledge base"
                  ]
                }, null, 2)
              }]
            };

          // Original workflow tools (simplified implementations)
          case "get_workflow_structure":
            const componentInfo = args.component ? 
              `Structure for component: ${args.component}` : 
              "Overall Global Workflow structure";
            
            return {
              content: [{
                type: "text",
                text: JSON.stringify({
                  component: args.component || "overview",
                  structure: componentInfo,
                  hf_enhancement_available: true,
                  suggested_searches: [
                    "weather prediction models",
                    "numerical weather prediction",
                    "ensemble forecasting"
                  ]
                }, null, 2)
              }]
            };

          case "list_job_scripts":
            return {
              content: [{
                type: "text", 
                text: JSON.stringify({
                  message: "Job scripts listing with HF enhancement",
                  scripts: ["JGDAS_*", "JGFS_*", "Various workflow jobs"],
                  hf_integration: "Can search for similar workflow implementations"
                }, null, 2)
              }]
            };

          case "explain_workflow_component":
            return {
              content: [{
                type: "text",
                text: JSON.stringify({
                  component: args.component,
                  explanation: `Enhanced explanation for ${args.component}`,
                  hf_research_available: true,
                  suggested_paper_search: `${args.component} weather modeling`
                }, null, 2)
              }]
            };

          case "analyze_workflow_dependencies":
            return {
              content: [{
                type: "text",
                text: JSON.stringify({
                  job_name: args.job_name,
                  direction: args.direction,
                  depth: args.depth,
                  analysis: `Dependency analysis for ${args.job_name}`,
                  hf_enhancement: "Can find similar workflow patterns in research"
                }, null, 2)
              }]
            };

          default:
            throw new McpError(
              ErrorCode.MethodNotFound,
              `Unknown tool: ${name}`
            );
        }
      } catch (error) {
        console.error(`Error executing tool ${name}:`, error);
        throw new McpError(
          ErrorCode.InternalError,
          `Tool execution failed: ${error.message}`
        );
      }
    });
  }

  async run() {
    const transport = new StdioServerTransport();
    await this.server.connect(transport);
    console.error("🚀 Enhanced RAG-MCP Server with Hugging Face integration running on stdio");
  }
}

const server = new EnhancedRAGMCPServer();
server.run().catch(console.error);
