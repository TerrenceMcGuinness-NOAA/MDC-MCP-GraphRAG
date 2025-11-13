#!/usr/bin/env node

/**
 * Simple RAG-Enhanced MCP Server for Global Workflow
 * Uses basic text search without vector embeddings for demonstration
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

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

class SimpleRAGMCPServer {
  constructor() {
    this.server = new Server({
      name: "global-workflow-simple-rag-mcp",
      version: "1.0.0",
    }, {
      capabilities: {
        tools: {},
      },
    });

    this.knowledgeBase = null;
    this.chunks = [];
    this.documents = [];

    this.setupTools();
    this.setupHandlers();
    this.loadKnowledgeBase();
  }

  async loadKnowledgeBase() {
    try {
      const knowledgeDir = path.join(__dirname, 'simple-knowledge-base');

      const chunksData = await fs.readFile(path.join(knowledgeDir, 'chunks.json'), 'utf-8');
      this.chunks = JSON.parse(chunksData);

      const docsData = await fs.readFile(path.join(knowledgeDir, 'documents.json'), 'utf-8');
      this.documents = JSON.parse(docsData);

      const summaryData = await fs.readFile(path.join(knowledgeDir, 'summary.json'), 'utf-8');
      this.knowledgeBase = JSON.parse(summaryData);

      // Load documentation references
      try {
        const referencesData = await fs.readFile(path.join(__dirname, 'documentation-references.json'), 'utf-8');
        this.documentationReferences = JSON.parse(referencesData);
      } catch (error) {
        console.error('⚠ Documentation references not found:', error.message);
        this.documentationReferences = null;
      }

      console.error(`✓ Knowledge base loaded: ${this.chunks.length} chunks from ${this.documents.length} documents`);
    } catch (error) {
      console.error('⚠ Knowledge base not found, some features may not work:', error.message);
    }
  }

  setupTools() {
    this.tools = [
      {
        name: "search_documentation",
        description: "Search through Global Workflow documentation and code",
        inputSchema: {
          type: "object",
          properties: {
            query: {
              type: "string",
              description: "Search query (keywords to find in documentation)"
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
        name: "explain_component",
        description: "Get detailed explanation of a workflow component with examples",
        inputSchema: {
          type: "object",
          properties: {
            component: {
              type: "string",
              description: "Component name or concept to explain"
            },
            include_examples: {
              type: "boolean",
              default: true,
              description: "Include code examples in explanation"
            }
          },
          required: ["component"]
        }
      },
      {
        name: "list_workflow_jobs",
        description: "List available workflow jobs and scripts",
        inputSchema: {
          type: "object",
          properties: {
            filter_type: {
              type: "string",
              enum: ["all", "jobs", "scripts", "configs"],
              default: "all",
              description: "Type of workflow components to list"
            }
          }
        }
      },
      {
        name: "get_knowledge_stats",
        description: "Get statistics about the knowledge base",
        inputSchema: {
          type: "object",
          properties: {}
        }
      },
      {
        name: "get_documentation_references",
        description: "Get reference URLs for external documentation and resources",
        inputSchema: {
          type: "object",
          properties: {
            category: {
              type: "string",
              enum: ["all", "internal", "external", "ufs", "rocoto", "gsi", "hpc_systems", "noaa_tools", "standards"],
              default: "all",
              description: "Category of documentation references to retrieve"
            },
            format: {
              type: "string",
              enum: ["detailed", "urls_only", "structured"],
              default: "detailed",
              description: "Format of the response"
            }
          }
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
          case "search_documentation":
            return await this.searchDocumentation(args.query, args.max_results);
          case "explain_component":
            return await this.explainComponent(args.component, args.include_examples);
          case "list_workflow_jobs":
            return await this.listWorkflowJobs(args.filter_type);
          case "get_knowledge_stats":
            return await this.getKnowledgeStats();
          case "get_documentation_references":
            return await this.getDocumentationReferences(args.category, args.format);
          default:
            throw new McpError(ErrorCode.MethodNotFound, `Unknown tool: ${name}`);
        }
      } catch (error) {
        throw new McpError(ErrorCode.InternalError, `Error executing tool ${name}: ${error.message}`);
      }
    });
  }

  searchDocumentation(query, maxResults = 5) {
    if (!this.chunks || this.chunks.length === 0) {
      return {
        content: [{
          type: "text",
          text: "Knowledge base not loaded. Please ensure the simple-processor has been run to create the knowledge base."
        }]
      };
    }

    const queryLower = query.toLowerCase();
    const results = [];

    for (const chunk of this.chunks) {
      const contentLower = chunk.content.toLowerCase();
      let score = 0;

      // Simple keyword matching with better scoring
      const queryWords = queryLower.split(/\\s+/).filter(word => word.length > 2);
      for (const word of queryWords) {
        const matches = (contentLower.match(new RegExp(word, 'g')) || []).length;
        score += matches;

        // Bonus for title/header matches
        if (chunk.metadata.source.toLowerCase().includes(word)) {
          score += 2;
        }
      }

      if (score > 0) {
        results.push({
          ...chunk,
          score
        });
      }
    }

    const sortedResults = results
      .sort((a, b) => b.score - a.score)
      .slice(0, maxResults);

    let responseText = `# Documentation Search Results\\n\\n`;
    responseText += `**Query:** "${query}"\\n`;
    responseText += `**Results Found:** ${sortedResults.length}\\n\\n`;

    if (sortedResults.length === 0) {
      responseText += `No matching content found. Try:\\n`;
      responseText += `- Using different keywords\\n`;
      responseText += `- Searching for specific component names\\n`;
      responseText += `- Looking for configuration terms\\n`;
    } else {
      sortedResults.forEach((result, index) => {
        responseText += `## Result ${index + 1} (Score: ${result.score})\\n`;
        responseText += `**Source:** ${result.metadata.source}\\n`;
        responseText += `**Type:** ${result.metadata.type}\\n\\n`;
        responseText += `**Content:**\\n\`\`\`\\n${result.content.substring(0, 500)}${result.content.length > 500 ? '...' : ''}\\n\`\`\`\\n\\n`;
      });
    }

    return {
      content: [{ type: "text", text: responseText }]
    };
  }

  explainComponent(component, includeExamples = true) {
    if (!this.chunks || this.chunks.length === 0) {
      return {
        content: [{
          type: "text",
          text: "Knowledge base not loaded. Please run the simple-processor first."
        }]
      };
    }

    // Search for component-related content
    const componentResults = this.searchForComponent(component);

    let explanation = `# ${component} - Component Explanation\\n\\n`;

    if (componentResults.length === 0) {
      explanation += `No specific information found for "${component}".\\n\\n`;
      explanation += `This could mean:\\n`;
      explanation += `- The component name might be spelled differently\\n`;
      explanation += `- It might be part of a larger system\\n`;
      explanation += `- Documentation might use different terminology\\n\\n`;
      explanation += `Try searching for related terms or check the workflow job listings.`;
    } else {
      explanation += `Based on the available documentation:\\n\\n`;

      // Group by type
      const byType = {};
      componentResults.forEach(result => {
        const type = result.metadata.type;
        if (!byType[type]) byType[type] = [];
        byType[type].push(result);
      });

      Object.keys(byType).forEach(type => {
        explanation += `### ${type.charAt(0).toUpperCase() + type.slice(1)} Information\\n\\n`;

        byType[type].slice(0, 2).forEach(result => {
          explanation += `**From:** ${result.metadata.source}\\n\\n`;
          if (includeExamples) {
            explanation += `\`\`\`\\n${result.content.substring(0, 300)}${result.content.length > 300 ? '...' : ''}\\n\`\`\`\\n\\n`;
          } else {
            explanation += `${result.content.substring(0, 150)}${result.content.length > 150 ? '...' : ''}\\n\\n`;
          }
        });
      });
    }

    return {
      content: [{ type: "text", text: explanation }]
    };
  }

  searchForComponent(component) {
    const componentLower = component.toLowerCase();
    const results = [];

    for (const chunk of this.chunks) {
      let score = 0;
      const contentLower = chunk.content.toLowerCase();
      const sourceLower = chunk.metadata.source.toLowerCase();

      // Exact component name match
      if (contentLower.includes(componentLower) || sourceLower.includes(componentLower)) {
        score += 3;
      }

      // Partial matches
      const componentWords = componentLower.split(/[-_\\s]/);
      for (const word of componentWords) {
        if (word.length > 2) {
          if (contentLower.includes(word)) score += 1;
          if (sourceLower.includes(word)) score += 1;
        }
      }

      if (score > 0) {
        results.push({ ...chunk, score });
      }
    }

    return results.sort((a, b) => b.score - a.score).slice(0, 10);
  }

  listWorkflowJobs(filterType = "all") {
    if (!this.documents || this.documents.length === 0) {
      return {
        content: [{
          type: "text",
          text: "Knowledge base not loaded. Please run the simple-processor first."
        }]
      };
    }

    const filtered = this.documents.filter(doc => {
      if (filterType === "all") return true;
      if (filterType === "jobs") return doc.type === "workflow" || doc.relativePath.includes("jobs");
      if (filterType === "scripts") return doc.type === "shell_script" || doc.type === "python_script";
      if (filterType === "configs") return doc.type === "configuration" || doc.type === "yaml_config";
      return false;
    });

    let response = `# Workflow Components (${filterType})\\n\\n`;
    response += `Found ${filtered.length} components:\\n\\n`;

    // Group by type
    const byType = {};
    filtered.forEach(doc => {
      const type = doc.type;
      if (!byType[type]) byType[type] = [];
      byType[type].push(doc);
    });

    Object.keys(byType).forEach(type => {
      response += `## ${type.charAt(0).toUpperCase() + type.slice(1)} (${byType[type].length})\\n\\n`;
      byType[type].slice(0, 20).forEach(doc => {
        response += `- **${doc.name}** - \`${doc.relativePath}\`\\n`;
      });
      if (byType[type].length > 20) {
        response += `  ... and ${byType[type].length - 20} more\\n`;
      }
      response += `\\n`;
    });

    return {
      content: [{ type: "text", text: response }]
    };
  }

  getKnowledgeStats() {
    if (!this.knowledgeBase) {
      return {
        content: [{
          type: "text",
          text: "Knowledge base not loaded."
        }]
      };
    }

    const typeStats = {};
    this.documents.forEach(doc => {
      typeStats[doc.type] = (typeStats[doc.type] || 0) + 1;
    });

    let stats = `# Knowledge Base Statistics\\n\\n`;
    stats += `**Created:** ${this.knowledgeBase.createdAt}\\n`;
    stats += `**Total Documents:** ${this.knowledgeBase.totalDocuments}\\n`;
    stats += `**Total Chunks:** ${this.knowledgeBase.totalChunks}\\n\\n`;

    stats += `## Document Types\\n\\n`;
    Object.keys(typeStats).forEach(type => {
      stats += `- **${type}:** ${typeStats[type]}\\n`;
    });

    stats += `\\n## Configuration\\n\\n`;
    stats += `- **Chunk Size:** ${this.knowledgeBase.config.chunkSize}\\n`;
    stats += `- **Max Files Processed:** ${this.knowledgeBase.config.maxFiles}\\n`;
    stats += `- **Supported Extensions:** ${this.knowledgeBase.config.supportedExtensions.join(', ')}\\n`;

    return {
      content: [{ type: "text", text: stats }]
    };
  }

  getDocumentationReferences(category = "all", format = "detailed") {
    if (!this.documentationReferences) {
      return {
        content: [{
          type: "text",
          text: "Documentation references not loaded. Please ensure documentation-references.json exists."
        }]
      };
    }

    const refs = this.documentationReferences.documentation_references;
    let filteredRefs = {};

    // Filter by category
    switch (category) {
      case "all":
        filteredRefs = refs;
        break;
      case "internal":
        filteredRefs = { internal: refs.internal };
        break;
      case "external":
        filteredRefs = { external: refs.external };
        break;
      case "ufs":
        filteredRefs = { ufs: refs.external?.ufs };
        break;
      case "rocoto":
        filteredRefs = { rocoto: refs.external?.rocoto };
        break;
      case "gsi":
        filteredRefs = { gsi: refs.external?.gsi };
        break;
      case "hpc_systems":
        filteredRefs = { hpc_systems: refs.external?.hpc_systems };
        break;
      case "noaa_tools":
        filteredRefs = { noaa_tools: refs.external?.noaa_tools };
        break;
      case "standards":
        filteredRefs = { standards_and_policies: refs.standards_and_policies };
        break;
      default:
        filteredRefs = refs;
    }

    // Format response
    let response = `# Documentation References (${category})\\n\\n`;

    if (format === "urls_only") {
      response += this.formatUrlsOnly(filteredRefs);
    } else if (format === "structured") {
      response += this.formatStructured(filteredRefs);
    } else {
      response += this.formatDetailed(filteredRefs);
    }

    // Add metadata
    const metadata = this.documentationReferences.reference_metadata;
    response += `\\n---\\n`;
    response += `**Last Updated:** ${metadata.last_updated}\\n`;
    response += `**Version:** ${metadata.version}\\n`;
    response += `**Update Frequency:** ${metadata.update_frequency}\\n`;

    return {
      content: [{ type: "text", text: response }]
    };
  }

  formatDetailed(refs) {
    let output = "";

    Object.keys(refs).forEach(section => {
      output += `## ${section.charAt(0).toUpperCase() + section.slice(1).replace(/_/g, ' ')}\\n\\n`;

      if (typeof refs[section] === 'object') {
        Object.keys(refs[section]).forEach(subsection => {
          output += `### ${subsection.charAt(0).toUpperCase() + subsection.slice(1).replace(/_/g, ' ')}\\n\\n`;

          const item = refs[section][subsection];
          if (typeof item === 'object') {
            Object.keys(item).forEach(key => {
              if (typeof item[key] === 'string' && item[key].startsWith('http')) {
                output += `- **${key.replace(/_/g, ' ')}:** [${item[key]}](${item[key]})\\n`;
              }
            });
          }
          output += `\\n`;
        });
      }
    });

    return output;
  }

  formatUrlsOnly(refs) {
    let output = "";
    const urls = this.extractAllUrls(refs);

    urls.forEach(url => {
      output += `- ${url}\\n`;
    });

    return output;
  }

  formatStructured(refs) {
    return `\`\`\`json\\n${JSON.stringify(refs, null, 2)}\\n\`\`\`\\n`;
  }

  extractAllUrls(obj, urls = []) {
    Object.values(obj).forEach(value => {
      if (typeof value === 'string' && value.startsWith('http')) {
        urls.push(value);
      } else if (typeof value === 'object' && value !== null) {
        this.extractAllUrls(value, urls);
      }
    });
    return urls;
  }

  async run() {
    const transport = new StdioServerTransport();
    await this.server.connect(transport);
    console.error("Simple RAG-Enhanced Global Workflow MCP Server running on stdio");
  }
}

// Initialize and run the server
const server = new SimpleRAGMCPServer();

// Export for testing
export default SimpleRAGMCPServer;

// Run server if called directly
if (import.meta.url === `file://${process.argv[1]}`) {
  server.run().catch(console.error);
}
