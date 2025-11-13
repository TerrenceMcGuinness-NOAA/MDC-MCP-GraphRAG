#!/usr/bin/env node

/**
 * GitHub Integration Tools Module
 * 
 * Provides GitHub repository access and analysis capabilities
 * for cross-repository code pattern analysis and issue tracking.
 * 
 * @version 2.0.0
 * @author NOAA EMC Global Workflow Team
 */

// Lazy load Octokit to avoid startup issues
let Octokit = null;

export class GitHubTools {
  constructor(githubToken = null) {
    this.githubToken = githubToken || process.env.GITHUB_TOKEN;
    this.octokit = null;
    this.initializeClient();
  }

  /**
   * Initialize GitHub client
   */
  async initializeClient() {
    try {
      if (!Octokit) {
        const octokitModule = await import('@octokit/rest');
        Octokit = octokitModule.Octokit;
      }
      
      this.octokit = new Octokit({
        auth: this.githubToken,
        userAgent: 'global-workflow-mcp-server/2.0.0'
      });
      
      if (this.githubToken) {
        console.error('[OK] GitHub client initialized with authentication');
      } else {
        console.error('[WARN] GitHub client initialized without token (limited API access)');
      }
    } catch (error) {
      console.error(`[ERROR] GitHub client initialization failed: ${error.message}`);
      this.octokit = null;
    }
  }

  /**
   * Register GitHub tools with server
   */
  registerWith(server) {
    server.registerTool(
      'analyze_workflow_dependencies',
      'Analyze dependencies and relationships between workflow components',
      {
        type: 'object',
        properties: {
          component: {
            type: 'string',
            description: 'Component name to analyze dependencies for'
          },
          analysis_type: {
            type: 'string',
            description: 'Type of dependency analysis',
            enum: ['upstream', 'downstream', 'circular', 'all'],
            default: 'all'
          },
          include_external: {
            type: 'boolean',
            description: 'Include external repository dependencies',
            default: false
          }
        },
        required: ['component']
      },
      this.analyzeWorkflowDependencies.bind(this)
    );

    server.registerTool(
      'search_issues',
      'Search GitHub issues across workflow repositories',
      {
        type: 'object',
        properties: {
          query: {
            type: 'string',
            description: 'Search query for issues'
          },
          repository: {
            type: 'string',
            description: 'Repository to search (default: global-workflow)',
            default: 'global-workflow'
          },
          state: {
            type: 'string',
            description: 'Issue state to search',
            enum: ['open', 'closed', 'all'],
            default: 'open'
          },
          labels: {
            type: 'array',
            items: { type: 'string' },
            description: 'Filter by labels'
          }
        },
        required: ['query']
      },
      this.searchIssues.bind(this)
    );

    server.registerTool(
      'get_pull_requests',
      'Get pull request information and changes',
      {
        type: 'object',
        properties: {
          repository: {
            type: 'string',
            description: 'Repository name',
            default: 'global-workflow'
          },
          state: {
            type: 'string',
            description: 'PR state',
            enum: ['open', 'closed', 'all'],
            default: 'open'
          },
          limit: {
            type: 'number',
            description: 'Maximum PRs to return',
            default: 10,
            maximum: 50
          }
        }
      },
      this.getPullRequests.bind(this)
    );

    server.registerTool(
      'analyze_repository_structure',
      'Analyze structure and components across multiple repositories',
      {
        type: 'object',
        properties: {
          repositories: {
            type: 'array',
            items: { type: 'string' },
            description: 'List of repositories to analyze',
            default: ['global-workflow', 'GSI', 'UFS_UTILS']
          },
          analysis_depth: {
            type: 'string',
            description: 'Depth of analysis',
            enum: ['shallow', 'deep'],
            default: 'shallow'
          }
        }
      },
      this.analyzeRepositoryStructure.bind(this)
    );
  }

  /**
   * Analyze workflow dependencies
   */
  async analyzeWorkflowDependencies(args) {
    const { component, analysis_type = 'all', include_external = false } = args;
    
    if (!this.octokit) {
      return 'GitHub integration not available - no API access';
    }

    try {
      let analysis = `# Dependency Analysis: ${component}\n\n`;
      
      // Search for component references in the repository
      const searchResults = await this.searchCodeReferences(component);
      
      if (analysis_type === 'upstream' || analysis_type === 'all') {
        analysis += await this.analyzeUpstreamDependencies(component, searchResults);
      }
      
      if (analysis_type === 'downstream' || analysis_type === 'all') {
        analysis += await this.analyzeDownstreamDependencies(component, searchResults);
      }
      
      if (analysis_type === 'circular' || analysis_type === 'all') {
        analysis += await this.detectCircularDependencies(component, searchResults);
      }

      if (include_external) {
        analysis += await this.analyzeExternalDependencies(component);
      }

      return analysis;
      
    } catch (error) {
      return `Dependency analysis error: ${error.message}`;
    }
  }

  /**
   * Search GitHub issues
   */
  async searchIssues(args) {
    const { query, repository = 'global-workflow', state = 'open', labels = [] } = args;
    
    if (!this.octokit) {
      return 'GitHub integration not available - no API access';
    }

    try {
      const owner = 'NOAA-EMC';
      let searchQuery = `repo:${owner}/${repository} ${query}`;
      
      if (state !== 'all') {
        searchQuery += ` state:${state}`;
      }
      
      if (labels.length > 0) {
        searchQuery += ` ${labels.map(label => `label:"${label}"`).join(' ')}`;
      }

      const response = await this.octokit.search.issuesAndPullRequests({
        q: searchQuery,
        sort: 'updated',
        order: 'desc',
        per_page: 20
      });

      if (response.data.total_count === 0) {
        return `No issues found for query: "${query}"`;
      }

      return this.formatIssueResults(response.data.items, query);
      
    } catch (error) {
      return `Issue search error: ${error.message}`;
    }
  }

  /**
   * Get pull request information
   */
  async getPullRequests(args) {
    const { repository = 'global-workflow', state = 'open', limit = 10 } = args;
    
    if (!this.octokit) {
      return 'GitHub integration not available - no API access';
    }

    try {
      const owner = 'NOAA-EMC';
      
      const response = await this.octokit.pulls.list({
        owner,
        repo: repository,
        state,
        sort: 'updated',
        direction: 'desc',
        per_page: Math.min(limit, 50)
      });

      if (response.data.length === 0) {
        return `No ${state} pull requests found in ${repository}`;
      }

      return this.formatPRResults(response.data, repository);
      
    } catch (error) {
      return `Pull request error: ${error.message}`;
    }
  }

  /**
   * Analyze repository structure across multiple repos
   */
  async analyzeRepositoryStructure(args) {
    const { repositories = ['global-workflow', 'GSI', 'UFS_UTILS'], analysis_depth = 'shallow' } = args;
    
    if (!this.octokit) {
      return 'GitHub integration not available - no API access';
    }

    try {
      let analysis = `# Multi-Repository Structure Analysis\n\n`;
      const owner = 'NOAA-EMC';

      for (const repo of repositories) {
        analysis += `## ${repo}\n\n`;
        
        try {
          // Get repository information
          const repoInfo = await this.octokit.repos.get({ owner, repo });
          analysis += `**Description**: ${repoInfo.data.description || 'No description'}\n`;
          analysis += `**Language**: ${repoInfo.data.language || 'Mixed'}\n`;
          analysis += `**Size**: ${repoInfo.data.size} KB\n`;
          analysis += `**Last Updated**: ${new Date(repoInfo.data.updated_at).toLocaleDateString()}\n\n`;

          // Get top-level structure
          const contents = await this.octokit.repos.getContent({ owner, repo, path: '' });
          const directories = contents.data.filter(item => item.type === 'dir');
          
          analysis += `**Top-level directories**: ${directories.map(d => d.name).join(', ')}\n\n`;

          if (analysis_depth === 'deep') {
            // Get more detailed structure for key directories
            const keyDirs = ['jobs', 'scripts', 'parm', 'src', 'sorc'];
            for (const dir of keyDirs) {
              const dirExists = directories.find(d => d.name === dir);
              if (dirExists) {
                try {
                  const dirContents = await this.octokit.repos.getContent({ 
                    owner, repo, path: dir 
                  });
                  analysis += `- **${dir}**: ${dirContents.data.length} items\n`;
                } catch (err) {
                  analysis += `- **${dir}**: Could not analyze\n`;
                }
              }
            }
            analysis += '\n';
          }

        } catch (error) {
          analysis += `Error analyzing ${repo}: ${error.message}\n\n`;
        }
      }

      return analysis;
      
    } catch (error) {
      return `Repository analysis error: ${error.message}`;
    }
  }

  /**
   * Helper methods
   */
  async searchCodeReferences(component) {
    try {
      const owner = 'NOAA-EMC';
      const repo = 'global-workflow';
      
      const response = await this.octokit.search.code({
        q: `${component} repo:${owner}/${repo}`,
        sort: 'indexed',
        per_page: 30
      });

      return response.data.items;
    } catch (error) {
      console.error('Code search error:', error.message);
      return [];
    }
  }

  async analyzeUpstreamDependencies(component, searchResults) {
    let analysis = `## Upstream Dependencies\n\n`;
    analysis += `Components that ${component} depends on:\n\n`;

    // Analyze search results to find what this component imports/uses
    const dependencies = new Set();
    
    searchResults.forEach(result => {
      // Look for import statements, source commands, etc.
      const content = result.text_matches?.[0]?.fragment || '';
      const imports = this.extractDependencies(content, 'upstream');
      imports.forEach(dep => dependencies.add(dep));
    });

    if (dependencies.size > 0) {
      dependencies.forEach(dep => {
        analysis += `- ${dep}\n`;
      });
    } else {
      analysis += `No clear upstream dependencies found in search results.\n`;
    }

    analysis += '\n';
    return analysis;
  }

  async analyzeDownstreamDependencies(component, searchResults) {
    let analysis = `## Downstream Dependencies\n\n`;
    analysis += `Components that depend on ${component}:\n\n`;

    // Group results by file to show where component is used
    const usageFiles = new Map();
    
    searchResults.forEach(result => {
      const file = result.path;
      if (!usageFiles.has(file)) {
        usageFiles.set(file, []);
      }
      usageFiles.get(file).push(result);
    });

    if (usageFiles.size > 0) {
      usageFiles.forEach((results, file) => {
        analysis += `- **${file}**: ${results.length} reference(s)\n`;
      });
    } else {
      analysis += `No downstream dependencies found in search results.\n`;
    }

    analysis += '\n';
    return analysis;
  }

  async detectCircularDependencies(component, searchResults) {
    let analysis = `## Circular Dependency Check\n\n`;
    
    // This is a simplified check - in practice would need deeper analysis
    analysis += `Circular dependency detection requires deeper code analysis.\n`;
    analysis += `Manual review recommended for critical components.\n\n`;
    
    return analysis;
  }

  async analyzeExternalDependencies(component) {
    let analysis = `## External Dependencies\n\n`;
    
    try {
      // Search across multiple NOAA-EMC repositories
      const repos = ['GSI', 'UFS_UTILS', 'GDASApp', 'wxflow'];
      const owner = 'NOAA-EMC';
      
      for (const repo of repos) {
        try {
          const response = await this.octokit.search.code({
            q: `${component} repo:${owner}/${repo}`,
            per_page: 5
          });
          
          if (response.data.total_count > 0) {
            analysis += `- **${repo}**: ${response.data.total_count} references\n`;
          }
        } catch (error) {
          // Repository might not exist or be accessible
          continue;
        }
      }
    } catch (error) {
      analysis += `External dependency search error: ${error.message}\n`;
    }

    analysis += '\n';
    return analysis;
  }

  extractDependencies(content, type) {
    const dependencies = [];
    
    if (type === 'upstream') {
      // Look for common dependency patterns
      const patterns = [
        /import\s+(\w+)/g,
        /from\s+(\w+)\s+import/g,
        /source\s+([^\s]+)/g,
        /\$\{(\w+)\}/g
      ];
      
      patterns.forEach(pattern => {
        let match;
        while ((match = pattern.exec(content)) !== null) {
          dependencies.push(match[1]);
        }
      });
    }
    
    return dependencies;
  }

  formatIssueResults(issues, query) {
    let output = `# GitHub Issues for: "${query}"\n\n`;
    output += `Found ${issues.length} issues:\n\n`;
    
    issues.forEach((issue, index) => {
      const isPR = issue.pull_request ? ' (PR)' : '';
      output += `## ${index + 1}. ${issue.title}${isPR}\n\n`;
      output += `**Number**: #${issue.number}\n`;
      output += `**State**: ${issue.state}\n`;
      output += `**Author**: ${issue.user.login}\n`;
      output += `**Updated**: ${new Date(issue.updated_at).toLocaleDateString()}\n`;
      
      if (issue.labels.length > 0) {
        output += `**Labels**: ${issue.labels.map(l => l.name).join(', ')}\n`;
      }
      
      output += `**URL**: ${issue.html_url}\n\n`;
      
      if (issue.body && issue.body.length > 0) {
        const preview = issue.body.substring(0, 200);
        output += `**Description**: ${preview}${issue.body.length > 200 ? '...' : ''}\n`;
      }
      
      output += '\n---\n\n';
    });

    return output;
  }

  formatPRResults(prs, repository) {
    let output = `# Pull Requests for ${repository}\n\n`;
    output += `Found ${prs.length} pull requests:\n\n`;
    
    prs.forEach((pr, index) => {
      output += `## ${index + 1}. ${pr.title}\n\n`;
      output += `**Number**: #${pr.number}\n`;
      output += `**State**: ${pr.state}\n`;
      output += `**Author**: ${pr.user.login}\n`;
      output += `**Branch**: ${pr.head.ref} → ${pr.base.ref}\n`;
      output += `**Updated**: ${new Date(pr.updated_at).toLocaleDateString()}\n`;
      
      if (pr.labels.length > 0) {
        output += `**Labels**: ${pr.labels.map(l => l.name).join(', ')}\n`;
      }
      
      output += `**URL**: ${pr.html_url}\n\n`;
      
      if (pr.body && pr.body.length > 0) {
        const preview = pr.body.substring(0, 150);
        output += `**Description**: ${preview}${pr.body.length > 150 ? '...' : ''}\n`;
      }
      
      output += '\n---\n\n';
    });

    return output;
  }
}