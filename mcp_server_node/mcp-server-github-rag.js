#!/usr/bin/env node

/**
 * Enhanced RAG MCP Server with GitHub Integration
 * 
 * This server combines:
 * - Local RAG capabilities with ChromaDB
 * - GitHub MCP tools for repository access
 * - Comprehensive workflow documentation search
 * - Cross-repository code pattern analysis
 * 
 * @version 2.0.0
 * @author NOAA EMC Global Workflow Team
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ErrorCode,
  ListToolsRequestSchema,
  McpError,
} from '@modelcontextprotocol/sdk/types.js';

// GitHub Integration
import { Octokit } from '@octokit/rest';
import fs from 'fs/promises';
import path from 'path';

class EnhancedGitHubRAGServer {
  constructor() {
    this.collection = null;
    this.isChromaDBConnected = false;
    this.embeddingModel = null;
    this.githubToken = process.env.GITHUB_TOKEN || null;
    this.octokit = null;
    this.setupEmbeddingModel();
    this.setupGitHubClient();
  }

  async setupGitHubClient() {
    try {
      this.octokit = new Octokit({
        auth: this.githubToken,
        userAgent: 'global-workflow-mcp-server/2.0.0'
      });
      
      if (this.githubToken) {
        console.error('✅ GitHub client initialized with authentication');
      } else {
        console.error('⚠ GitHub client initialized without authentication (rate limits apply)');
      }
    } catch (error) {
      console.error('⚠ Warning: Could not initialize GitHub client:', error.message);
    }
  }

  async setupEmbeddingModel() {
    try {
      const { pipeline } = await import('@xenova/transformers');
      this.embeddingModel = await pipeline('feature-extraction', 'Xenova/all-MiniLM-L6-v2');
      console.error('✅ Embedding model initialized');
    } catch (error) {
      console.error('⚠ Warning: Could not initialize embedding model:', error.message);
    }
  }

  async initializeChromaDB() {
    try {
      const chromadb = await import('chromadb');
      const client = new chromadb.ChromaClient({
        path: 'http://localhost:8000'
      });

      // Try to get existing collection
      try {
        this.collection = await client.getCollection({ name: 'global_workflow_docs' });
        this.isChromaDBConnected = true;
        console.error('✅ Connected to existing ChromaDB collection');
      } catch {
        // Try the other collection name
        try {
          this.collection = await client.getCollection({ name: 'global-workflow-docs' });
          this.isChromaDBConnected = true;
          console.error('✅ Connected to ChromaDB collection (global-workflow-docs)');
        } catch {
          console.error('⚠ Warning: ChromaDB collections not found, will use fallback search');
        }
      }
    } catch (error) {
      console.error('⚠ Warning: Could not connect to ChromaDB:', error.message);
    }
  }

  setupTools() {
    const tools = [
      // Core Global Workflow Tools
      {
        name: "get_workflow_structure",
        description: "Get the structure and overview of the global workflow system",
        inputSchema: {
          type: "object",
          properties: {
            component: {
              type: "string",
              description: "Specific component to focus on (jobs, scripts, configs, etc.)"
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
        description: "Get system-specific configuration information",
        inputSchema: {
          type: "object",
          properties: {
            system: {
              type: "string",
              description: "HPC system name (hera, orion, hercules, wcoss2, etc.)"
            }
          }
        }
      },
      {
        name: "explain_component",
        description: "Explain workflow components with enhanced context",
        inputSchema: {
          type: "object", 
          properties: {
            component: {
              type: "string",
              description: "Component or concept to explain"
            }
          },
          required: ["component"]
        }
      },

      // RAG-Enhanced Tools
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
        description: "Find similar code implementations using vector similarity",
        inputSchema: {
          type: "object",
          properties: {
            code_snippet: {
              type: "string",
              description: "Code snippet to find similarities for"
            },
            language: {
              type: "string",
              enum: ["bash", "python", "any"],
              description: "Programming language filter"
            }
          },
          required: ["code_snippet"]
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
            depth: {
              type: "number",
              default: 2,
              description: "Depth of dependency analysis"
            }
          }
        }
      },
      {
        name: "get_operational_guidance",
        description: "Get operational procedures and guidance for HPC systems",
        inputSchema: {
          type: "object",
          properties: {
            system: {
              type: "string",
              description: "HPC system name"
            },
            operation: {
              type: "string",
              description: "Specific operation or procedure"
            }
          }
        }
      },

      // GitHub Integration Tools
      {
        name: "github_search_repositories",
        description: "Search for GitHub repositories related to global workflow",
        inputSchema: {
          type: "object",
          properties: {
            query: {
              type: "string",
              description: "Search query for repositories"
            },
            org: {
              type: "string",
              default: "NOAA-EMC",
              description: "GitHub organization to search in"
            },
            include_forks: {
              type: "boolean",
              default: false,
              description: "Include forked repositories"
            }
          },
          required: ["query"]
        }
      },
      {
        name: "github_get_repository_content",
        description: "Get content from a specific GitHub repository",
        inputSchema: {
          type: "object",
          properties: {
            owner: {
              type: "string",
              description: "Repository owner"
            },
            repo: {
              type: "string", 
              description: "Repository name"
            },
            path: {
              type: "string",
              default: "",
              description: "Path within repository"
            },
            ref: {
              type: "string",
              default: "main",
              description: "Git reference (branch, tag, commit)"
            }
          },
          required: ["owner", "repo"]
        }
      },
      {
        name: "github_search_code",
        description: "Search for code patterns across GitHub repositories",
        inputSchema: {
          type: "object",
          properties: {
            query: {
              type: "string",
              description: "Code search query"
            },
            language: {
              type: "string",
              description: "Programming language filter"
            },
            org: {
              type: "string",
              default: "NOAA-EMC",
              description: "GitHub organization to search in"
            }
          },
          required: ["query"]
        }
      },
      {
        name: "github_get_issues",
        description: "Get issues from GitHub repositories for troubleshooting context",
        inputSchema: {
          type: "object",
          properties: {
            owner: {
              type: "string",
              description: "Repository owner"
            },
            repo: {
              type: "string",
              description: "Repository name"
            },
            state: {
              type: "string",
              enum: ["open", "closed", "all"],
              default: "all",
              description: "Issue state filter"
            },
            labels: {
              type: "string",
              description: "Comma-separated list of labels"
            }
          },
          required: ["owner", "repo"]
        }
      },
      {
        name: "github_cross_repo_analysis",
        description: "Analyze patterns and dependencies across multiple NOAA-EMC repositories",
        inputSchema: {
          type: "object",
          properties: {
            analysis_type: {
              type: "string",
              enum: ["dependencies", "patterns", "issues", "documentation"],
              description: "Type of cross-repository analysis"
            },
            repositories: {
              type: "array",
              items: { type: "string" },
              description: "List of repository names to analyze"
            },
            search_term: {
              type: "string",
              description: "Specific term or pattern to search for"
            }
          },
          required: ["analysis_type"]
        }
      }
    ];

    return tools;
  }

  // Tool implementations will go here...
  async handleToolCall(name, args) {
    try {
      switch (name) {
        case 'get_workflow_structure':
          return await this.getWorkflowStructure(args?.component);
        case 'list_job_scripts':
          return await this.listJobScripts();
        case 'get_system_configs':
          return await this.getSystemConfigs(args?.system);
        case 'explain_component':
          return await this.explainComponent(args?.component);
        case 'search_documentation':
          return await this.searchDocumentation(args?.query, args?.doc_type, args?.max_results);
        case 'explain_with_context':
          return await this.explainWithContext(args?.component, args?.context_level, args?.include_examples);
        case 'find_similar_code':
          return await this.findSimilarCode(args?.code_snippet, args?.language);
        case 'analyze_dependencies':
          return await this.analyzeDependencies(args?.job_name, args?.depth);
        case 'get_operational_guidance':
          return await this.getOperationalGuidance(args?.system, args?.operation);
        case 'github_search_repositories':
          return await this.githubSearchRepositories(args?.query, args?.org, args?.include_forks);
        case 'github_get_repository_content':
          return await this.githubGetRepositoryContent(args?.owner, args?.repo, args?.path, args?.ref);
        case 'github_search_code':
          return await this.githubSearchCode(args?.query, args?.language, args?.org);
        case 'github_get_issues':
          return await this.githubGetIssues(args?.owner, args?.repo, args?.state, args?.labels);
        case 'github_cross_repo_analysis':
          return await this.githubCrossRepoAnalysis(args?.analysis_type, args?.repositories, args?.search_term);
        default:
          throw new Error(`Unknown tool: ${name}`);
      }
    } catch (error) {
      return {
        content: [
          {
            type: 'text',
            text: `Error: ${error.message}`
          }
        ]
      };
    }
  }

  // Basic workflow tools (existing implementations)
  async getWorkflowStructure(component) {
    // Implementation from existing server
    const structure = {
      overview: `Global Workflow - NOAA's Operational Weather Prediction System...`,
      // ... rest of implementation
    };
    
    const content = component && structure[component] ? structure[component] : structure.overview;
    return { content: [{ type: 'text', text: content.trim() }] };
  }

  async listJobScripts() {
    // Implementation from existing server
    return { content: [{ type: 'text', text: 'Job scripts listing...' }] };
  }

  async getSystemConfigs(system) {
    // Implementation from existing server  
    return { content: [{ type: 'text', text: `System config for ${system}...` }] };
  }

  async explainComponent(component) {
    // Implementation from existing server
    return { content: [{ type: 'text', text: `Explanation of ${component}...` }] };
  }

  // GitHub integration methods (new)
  async githubSearchRepositories(query, org = "NOAA-EMC", includeForks = false) {
    try {
      if (!this.octokit) {
        throw new Error('GitHub client not initialized');
      }

      const searchQuery = `org:${org} ${query}${includeForks ? '' : ' -is:fork'}`;
      
      const { data } = await this.octokit.rest.search.repos({
        q: searchQuery,
        sort: 'updated',
        order: 'desc',
        per_page: 10
      });

      let responseText = `# GitHub Repository Search\n\n`;
      responseText += `**Query:** ${searchQuery}\n`;
      responseText += `**Total Found:** ${data.total_count}\n\n`;

      if (data.items.length === 0) {
        responseText += `No repositories found matching your criteria.\n`;
      } else {
        responseText += `**Top Repositories:**\n\n`;
        data.items.forEach((repo, index) => {
          responseText += `${index + 1}. **${repo.full_name}**\n`;
          responseText += `   - Description: ${repo.description || 'No description'}\n`;
          responseText += `   - Language: ${repo.language || 'Unknown'}\n`;
          responseText += `   - Stars: ${repo.stargazers_count}, Forks: ${repo.forks_count}\n`;
          responseText += `   - Updated: ${new Date(repo.updated_at).toLocaleDateString()}\n`;
          responseText += `   - URL: ${repo.html_url}\n\n`;
        });
      }
      
      return {
        content: [{
          type: 'text',
          text: responseText
        }]
      };
    } catch (error) {
      return {
        content: [{
          type: 'text',
          text: `Error searching GitHub repositories: ${error.message}`
        }]
      };
    }
  }

  async githubGetRepositoryContent(owner, repo, path = "", ref = "main") {
    try {
      if (!this.octokit) {
        throw new Error('GitHub client not initialized');
      }

      const { data } = await this.octokit.rest.repos.getContent({
        owner,
        repo,
        path,
        ref
      });

      let responseText = `# Repository Content: ${owner}/${repo}\n\n`;
      responseText += `**Path:** ${path || '/'}\n`;
      responseText += `**Reference:** ${ref}\n\n`;

      if (Array.isArray(data)) {
        // Directory listing
        responseText += `**Directory Contents:**\n\n`;
        data.forEach(item => {
          const icon = item.type === 'dir' ? '📁' : '📄';
          responseText += `${icon} ${item.name} (${item.type})\n`;
        });
      } else {
        // File content
        if (data.type === 'file') {
          responseText += `**File:** ${data.name}\n`;
          responseText += `**Size:** ${data.size} bytes\n`;
          responseText += `**Encoding:** ${data.encoding}\n\n`;
          
          if (data.content && data.encoding === 'base64') {
            try {
              const content = Buffer.from(data.content, 'base64').toString('utf-8');
              // Only show first 1000 characters for readability
              const preview = content.length > 1000 ? content.substring(0, 1000) + '\n...\n[Content truncated]' : content;
              responseText += `**Content:**\n\`\`\`\n${preview}\n\`\`\`\n`;
            } catch (e) {
              responseText += `**Content:** Binary file or encoding error\n`;
            }
          }
        }
      }
      
      return {
        content: [{
          type: 'text', 
          text: responseText
        }]
      };
    } catch (error) {
      return {
        content: [{
          type: 'text',
          text: `Error getting repository content: ${error.message}`
        }]
      };
    }
  }

  async githubSearchCode(query, language, org = "NOAA-EMC") {
    try {
      if (!this.octokit) {
        throw new Error('GitHub client not initialized');
      }

      let searchQuery = `${query} org:${org}`;
      if (language) {
        searchQuery += ` language:${language}`;
      }
      
      const { data } = await this.octokit.rest.search.code({
        q: searchQuery,
        sort: 'indexed',
        order: 'desc',
        per_page: 10
      });

      let responseText = `# GitHub Code Search\n\n`;
      responseText += `**Query:** ${searchQuery}\n`;
      responseText += `**Total Found:** ${data.total_count}\n\n`;

      if (data.items.length === 0) {
        responseText += `No code found matching your criteria.\n`;
      } else {
        responseText += `**Code Results:**\n\n`;
        data.items.forEach((item, index) => {
          responseText += `${index + 1}. **${item.name}** in ${item.repository.full_name}\n`;
          responseText += `   - Path: ${item.path}\n`;
          responseText += `   - URL: ${item.html_url}\n`;
          responseText += `   - Repository: ${item.repository.html_url}\n\n`;
        });
      }
      
      return {
        content: [{
          type: 'text',
          text: responseText
        }]
      };
    } catch (error) {
      return {
        content: [{
          type: 'text',
          text: `Error searching GitHub code: ${error.message}`
        }]
      };
    }
  }

  async githubGetIssues(owner, repo, state = "all", labels) {
    try {
      if (!this.octokit) {
        throw new Error('GitHub client not initialized');
      }

      const params = {
        owner,
        repo,
        state,
        per_page: 20,
        sort: 'updated',
        direction: 'desc'
      };

      if (labels) {
        params.labels = labels;
      }

      const { data } = await this.octokit.rest.issues.listForRepo(params);

      let responseText = `# GitHub Issues: ${owner}/${repo}\n\n`;
      responseText += `**State:** ${state}\n`;
      responseText += `**Labels:** ${labels || 'none'}\n`;
      responseText += `**Total Found:** ${data.length}\n\n`;

      if (data.length === 0) {
        responseText += `No issues found matching your criteria.\n`;
      } else {
        responseText += `**Issues:**\n\n`;
        data.forEach((issue, index) => {
          const labels = issue.labels.map(label => label.name).join(', ');
          responseText += `${index + 1}. **#${issue.number}** ${issue.title}\n`;
          responseText += `   - State: ${issue.state}\n`;
          responseText += `   - Author: ${issue.user.login}\n`;
          responseText += `   - Labels: ${labels || 'none'}\n`;
          responseText += `   - Created: ${new Date(issue.created_at).toLocaleDateString()}\n`;
          responseText += `   - Updated: ${new Date(issue.updated_at).toLocaleDateString()}\n`;
          responseText += `   - URL: ${issue.html_url}\n\n`;
        });
      }
      
      return {
        content: [{
          type: 'text',
          text: responseText
        }]
      };
    } catch (error) {
      return {
        content: [{
          type: 'text',
          text: `Error getting GitHub issues: ${error.message}`
        }]
      };
    }
  }

  async githubCrossRepoAnalysis(analysisType, repositories, searchTerm) {
    try {
      if (!this.octokit) {
        throw new Error('GitHub client not initialized');
      }

      const defaultRepos = [
        'global-workflow', 'GSI', 'UFS-weather-model', 'wxflow', 
        'UPP', 'GDASApp', 'GSI-Utils', 'GSI-Monitor'
      ];
      
      const reposToAnalyze = repositories && repositories.length > 0 ? repositories : defaultRepos;
      
      let responseText = `# Cross-Repository Analysis\n\n`;
      responseText += `**Type:** ${analysisType}\n`;
      responseText += `**Repositories:** ${reposToAnalyze.join(', ')}\n`;
      responseText += `**Search Term:** ${searchTerm || 'none'}\n\n`;

      switch (analysisType) {
        case 'dependencies':
          responseText += await this.analyzeDependenciesAcrossRepos(reposToAnalyze);
          break;
        case 'patterns':
          responseText += await this.analyzeCodePatternsAcrossRepos(reposToAnalyze, searchTerm);
          break;
        case 'issues':
          responseText += await this.analyzeIssuesAcrossRepos(reposToAnalyze, searchTerm);
          break;
        case 'documentation':
          responseText += await this.analyzeDocumentationAcrossRepos(reposToAnalyze, searchTerm);
          break;
        default:
          throw new Error(`Unknown analysis type: ${analysisType}`);
      }
      
      return {
        content: [{
          type: 'text',
          text: responseText
        }]
      };
    } catch (error) {
      return {
        content: [{
          type: 'text',
          text: `Error in cross-repository analysis: ${error.message}`
        }]
      };
    }
  }

  async analyzeDependenciesAcrossRepos(repositories) {
    let analysis = `**Dependency Analysis Results:**\n\n`;
    
    for (const repo of repositories.slice(0, 3)) { // Limit to first 3 for demo
      try {
        // Look for common dependency files
        const depFiles = ['requirements.txt', 'setup.py', 'CMakeLists.txt', 'Makefile'];
        
        for (const file of depFiles) {
          try {
            const { data } = await this.octokit.rest.repos.getContent({
              owner: 'NOAA-EMC',
              repo,
              path: file
            });
            
            analysis += `📄 **${repo}/${file}** found\n`;
          } catch (e) {
            // File doesn't exist, continue
          }
        }
      } catch (error) {
        analysis += `❌ **${repo}**: ${error.message}\n`;
      }
    }
    
    return analysis;
  }

  async analyzeCodePatternsAcrossRepos(repositories, searchTerm) {
    let analysis = `**Code Pattern Analysis Results:**\n\n`;
    
    if (searchTerm) {
      // Search for the pattern across repositories
      try {
        const { data } = await this.octokit.rest.search.code({
          q: `${searchTerm} org:NOAA-EMC`,
          per_page: 5
        });
        
        analysis += `Found ${data.total_count} matches for "${searchTerm}"\n\n`;
        data.items.forEach((item, index) => {
          analysis += `${index + 1}. ${item.repository.name}/${item.path}\n`;
        });
      } catch (error) {
        analysis += `Error searching patterns: ${error.message}\n`;
      }
    } else {
      analysis += `Please provide a search term for pattern analysis.\n`;
    }
    
    return analysis;
  }

  async analyzeIssuesAcrossRepos(repositories, searchTerm) {
    let analysis = `**Issues Analysis Results:**\n\n`;
    
    for (const repo of repositories.slice(0, 3)) { // Limit for demo
      try {
        const { data } = await this.octokit.rest.issues.listForRepo({
          owner: 'NOAA-EMC',
          repo,
          state: 'open',
          per_page: 5
        });
        
        analysis += `📋 **${repo}**: ${data.length} open issues\n`;
      } catch (error) {
        analysis += `❌ **${repo}**: ${error.message}\n`;
      }
    }
    
    return analysis;
  }

  async analyzeDocumentationAcrossRepos(repositories, searchTerm) {
    let analysis = `**Documentation Analysis Results:**\n\n`;
    
    for (const repo of repositories.slice(0, 3)) { // Limit for demo
      try {
        // Look for common documentation files
        const docFiles = ['README.md', 'docs/', 'doc/', 'INSTALL', 'CONTRIBUTING.md'];
        
        for (const file of docFiles) {
          try {
            const { data } = await this.octokit.rest.repos.getContent({
              owner: 'NOAA-EMC',
              repo,
              path: file
            });
            
            analysis += `📚 **${repo}/${file}** found\n`;
          } catch (e) {
            // File doesn't exist, continue
          }
        }
      } catch (error) {
        analysis += `❌ **${repo}**: ${error.message}\n`;
      }
    }
    
    return analysis;
  }

  // RAG methods (existing implementations)
  async searchDocumentation(query, docType = "all", maxResults = 5) {
    // Implementation from existing RAG server
    return { content: [{ type: 'text', text: `Documentation search for: ${query}` }] };
  }

  async explainWithContext(component, contextLevel = "intermediate", includeExamples = true) {
    // Implementation from existing RAG server
    return { content: [{ type: 'text', text: `Context explanation for: ${component}` }] };
  }

  async findSimilarCode(codeSnippet, language) {
    // Implementation from existing RAG server
    return { content: [{ type: 'text', text: `Similar code search for: ${language} code` }] };
  }

  async analyzeDependencies(jobName, depth = 2) {
    // New dependency analysis implementation
    return { content: [{ type: 'text', text: `Dependency analysis for: ${jobName}` }] };
  }

  async getOperationalGuidance(system, operation) {
    // New operational guidance implementation
    return { content: [{ type: 'text', text: `Operational guidance for: ${system} - ${operation}` }] };
  }
}

function createServer() {
  const server = new Server(
    {
      name: 'enhanced-github-rag-server',
      version: '2.0.0',
    },
    {
      capabilities: {
        tools: {},
      },
    }
  );

  const ragServer = new EnhancedGitHubRAGServer();
  
  // Initialize ChromaDB connection
  ragServer.initializeChromaDB();

  server.setRequestHandler(ListToolsRequestSchema, async () => {
    return {
      tools: ragServer.setupTools(),
    };
  });

  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params;
    return await ragServer.handleToolCall(name, args);
  });

  return server;
}

async function main() {
  const server = createServer();
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error('Enhanced GitHub RAG MCP Server running on stdio');
}

main().catch((error) => {
  console.error('Server error:', error);
  process.exit(1);
});
