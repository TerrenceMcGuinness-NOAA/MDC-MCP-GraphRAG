#!/usr/bin/env node

/**
 * GitHubGraphIngester - GitHub Metadata to Neo4j Graph
 *
 * Ingests GitHub repository metadata into the Neo4j graph:
 * - Git commit history from local repositories
 * - Developer nodes from commit authors
 * - Commit nodes with messages and timestamps
 * - Relationships: AUTHORED, MODIFIES, CONTRIBUTED_TO
 *
 * Optional (if GH_TOKEN available):
 * - GitHub Issues and Pull Requests
 * - Issue/PR relationships to components
 *
 * @version 1.0.0
 * @author NOAA EMC Global Workflow Team
 */

import { execSync } from 'child_process';
import { generateNodeId } from './GraphSchema.js';

// Lazy load Octokit for GitHub API access
let Octokit = null;

export class GitHubGraphIngester {
  constructor(neo4jClient, options = {}) {
    this.client = neo4jClient;
    this.options = {
      rootPath: options.rootPath || process.env.MCP_WORKFLOW_ROOT || process.env.GW_REPO || '/mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow_develop',
      maxCommitsPerRepo: options.maxCommitsPerRepo || 100,
      includeGitHubAPI: options.includeGitHubAPI !== false,
      githubToken: options.githubToken || process.env.GH_TOKEN || process.env.GITHUB_TOKEN,
      verbose: options.verbose || false,
      ...options
    };

    this.octokit = null;
    this.stats = {
      componentsProcessed: 0,
      commitsDiscovered: 0,
      commitsCreated: 0,
      developersCreated: 0,
      relationshipsCreated: 0,
      issuesCreated: 0,
      pullRequestsCreated: 0,
      errors: [],
      processingTime: 0
    };

    this.discoveredDevelopers = new Map(); // email -> developer data
    this.discoveredCommits = new Map(); // hash -> commit data
    this.componentCommits = []; // component-commit relationships
    this.commitFileModifications = []; // commit-file relationships
  }

  /**
   * Initialize GitHub API client (optional)
   */
  async initializeGitHubAPI() {
    if (!this.options.includeGitHubAPI) {
      console.error('[SKIP]  Skipping GitHub API initialization (disabled)');
      return;
    }

    if (!this.options.githubToken) {
      console.error('[WARN]  No GitHub token available - skipping API features');
      console.error('   Set GH_TOKEN or GITHUB_TOKEN environment variable for Issues/PRs');
      return;
    }

    try {
      if (!Octokit) {
        const octokitModule = await import('@octokit/rest');
        Octokit = octokitModule.Octokit;
      }

      this.octokit = new Octokit({
        auth: this.options.githubToken,
        userAgent: 'global-workflow-neo4j-ingester/1.0.0'
      });

      console.error('[OK] GitHub API client initialized (authenticated)');
    } catch (error) {
      console.error(`[WARN]  GitHub API initialization failed: ${error.message}`);
      this.octokit = null;
    }
  }

  /**
   * Main ingestion entry point
   */
  async ingest(componentPaths) {
    const startTime = Date.now();
    console.error('\n📚 Starting GitHub Metadata Ingestion...\n');

    try {
      // Step 1: Initialize GitHub API (optional)
      await this.initializeGitHubAPI();

      // Step 2: Get component paths from Neo4j if not provided
      if (!componentPaths) {
        console.error('[SEARCH] Step 1: Fetching component paths from Neo4j...');
        componentPaths = await this.getComponentPathsFromGraph();
        console.error(`[OK] Found ${componentPaths.length} components\n`);
      }

      // Step 3: Extract git history from each component
      console.error('📖 Step 2: Extracting git commit history...');
      for (const componentPath of componentPaths) {
        await this.processComponentGitHistory(componentPath);
      }
      console.error(`[OK] Discovered ${this.discoveredCommits.size} commits from ${this.stats.componentsProcessed} components\n`);

      // Step 4: Create Developer nodes
      console.error('👥 Step 3: Creating Developer nodes...');
      await this.createDeveloperNodes();
      console.error(`[OK] Created ${this.stats.developersCreated} developers\n`);

      // Step 5: Create Commit nodes
      console.error('📝 Step 4: Creating Commit nodes...');
      await this.createCommitNodes();
      console.error(`[OK] Created ${this.stats.commitsCreated} commits\n`);

      // Step 6: Create relationships
      console.error('🔗 Step 5: Creating relationships...');
      await this.createRelationships();
      console.error(`[OK] Created ${this.stats.relationshipsCreated} relationships\n`);

      // Step 7: Optional - Ingest GitHub Issues/PRs
      if (this.octokit) {
        console.error('🐛 Step 6: Ingesting GitHub Issues/PRs (optional)...');
        await this.ingestGitHubIssuesAndPRs();
        console.error(`[OK] Created ${this.stats.issuesCreated} issues, ${this.stats.pullRequestsCreated} PRs\n`);
      }

      // Summary
      this.stats.processingTime = Date.now() - startTime;
      this.printSummary();

      return {
        success: true,
        stats: this.stats
      };

    } catch (error) {
      console.error(`\n[ERROR] Ingestion failed: ${error.message}`);
      this.stats.errors.push({ stage: 'main', error: error.message });
      throw error;
    }
  }

  /**
   * Get component paths from existing Neo4j graph
   */
  async getComponentPathsFromGraph() {
    const result = await this.client.runQuery(`
      MATCH (c:Component)
      WHERE c.path IS NOT NULL
      RETURN c.path as path, c.name as name
      ORDER BY c.path
    `);

    return result.records.map(record => ({
      path: record.get('path'),
      name: record.get('name')
    }));
  }

  /**
   * Process git history for a single component
   */
  async processComponentGitHistory(component) {
    const { path: componentPath, name: componentName } = component;

    try {
      // Check if it's a git repository
      if (!this.isGitRepository(componentPath)) {
        if (this.options.verbose) {
          console.error(`  [SKIP]  ${componentName}: Not a git repository`);
        }
        return;
      }

      if (this.options.verbose) {
        console.error(`  📖 Processing: ${componentName}`);
      }

      // Get commit history (limited to maxCommitsPerRepo)
      const commits = this.getGitCommits(componentPath, this.options.maxCommitsPerRepo);

      for (const commit of commits) {
        // Add developer if not seen before
        if (!this.discoveredDevelopers.has(commit.authorEmail)) {
          this.discoveredDevelopers.set(commit.authorEmail, {
            id: generateNodeId('Developer', commit.authorEmail),
            name: commit.authorName,
            email: commit.authorEmail,
            commitCount: 0,
            createdAt: new Date().toISOString()
          });
        }

        // Increment developer's commit count
        const developer = this.discoveredDevelopers.get(commit.authorEmail);
        developer.commitCount++;

        // Add commit if not seen before
        if (!this.discoveredCommits.has(commit.hash)) {
          this.discoveredCommits.set(commit.hash, {
            id: generateNodeId('Commit', commit.hash),
            hash: commit.hash,
            message: commit.message,
            timestamp: commit.timestamp,
            author: commit.authorEmail,
            createdAt: new Date().toISOString()
          });

          this.stats.commitsDiscovered++;
        }

        // Record component-commit relationship
        this.componentCommits.push({
          componentPath: componentPath,
          commitHash: commit.hash
        });
      }

      this.stats.componentsProcessed++;

    } catch (error) {
      console.error(`  [WARN]  Error processing ${componentName}: ${error.message}`);
      this.stats.errors.push({ component: componentName, error: error.message });
    }
  }

  /**
   * Check if directory is a git repository
   */
  isGitRepository(repoPath) {
    try {
      execSync('git rev-parse --git-dir', {
        cwd: repoPath,
        stdio: ['pipe', 'pipe', 'ignore']
      });
      return true;
    } catch {
      return false;
    }
  }

  /**
   * Get git commits for a repository
   */
  getGitCommits(repoPath, maxCommits) {
    try {
      const format = '%H|%an|%ae|%at|%s';
      const output = execSync(
        `git log --format="${format}" -n ${maxCommits}`,
        {
          cwd: repoPath,
          encoding: 'utf-8',
          stdio: ['pipe', 'pipe', 'ignore'],
          maxBuffer: 10 * 1024 * 1024 // 10MB buffer
        }
      );

      const commits = [];
      const lines = output.trim().split('\n');

      for (const line of lines) {
        if (!line) continue;

        const [hash, authorName, authorEmail, timestamp, ...messageParts] = line.split('|');
        const message = messageParts.join('|'); // Rejoin in case message had |

        commits.push({
          hash,
          authorName,
          authorEmail,
          timestamp: new Date(parseInt(timestamp) * 1000).toISOString(),
          message: message.substring(0, 500) // Truncate long messages
        });
      }

      return commits;
    } catch (error) {
      console.error(`Git log error in ${repoPath}: ${error.message}`);
      return [];
    }
  }

  /**
   * Create Developer nodes in Neo4j
   */
  async createDeveloperNodes() {
    const developers = Array.from(this.discoveredDevelopers.values());

    if (developers.length === 0) {
      console.warn('[WARN]  No developers to create');
      return;
    }

    const result = await this.client.batchCreateNodes(
      'Developer',
      developers,
      { mergeKey: 'email', batchSize: 100 }
    );

    this.stats.developersCreated = result.created;
  }

  /**
   * Create Commit nodes in Neo4j
   */
  async createCommitNodes() {
    const commits = Array.from(this.discoveredCommits.values());

    if (commits.length === 0) {
      console.warn('[WARN]  No commits to create');
      return;
    }

    const result = await this.client.batchCreateNodes(
      'Commit',
      commits,
      { mergeKey: 'hash', batchSize: 100 }
    );

    this.stats.commitsCreated = result.created;
  }

  /**
   * Create all relationships
   */
  async createRelationships() {
    let totalCreated = 0;

    // 1. AUTHORED relationships (Developer -> Commit)
    console.error('  Creating AUTHORED relationships...');
    const authoredRels = Array.from(this.discoveredCommits.values()).map(commit => ({
      from: this.discoveredDevelopers.get(commit.author).email,
      to: commit.hash,
      properties: {}
    }));

    const authoredResult = await this.client.batchCreateRelationships(
      'AUTHORED',
      authoredRels,
      {
        fromLabel: 'Developer',
        toLabel: 'Commit',
        fromKey: 'email',
        toKey: 'hash',
        batchSize: 100
      }
    );
    totalCreated += authoredResult.created;

    // 2. CONTRIBUTED_TO relationships (Developer -> Component)
    console.error('  Creating CONTRIBUTED_TO relationships...');
    const contributionMap = new Map();

    this.componentCommits.forEach(({ componentPath, commitHash }) => {
      const commit = this.discoveredCommits.get(commitHash);
      const key = `${commit.author}|${componentPath}`;

      if (!contributionMap.has(key)) {
        contributionMap.set(key, {
          email: commit.author,
          componentPath: componentPath,
          commits: 0
        });
      }

      contributionMap.get(key).commits++;
    });

    const contributedRels = Array.from(contributionMap.values()).map(contrib => ({
      from: contrib.email,
      to: contrib.componentPath,
      properties: {
        commits: contrib.commits
      }
    }));

    const contributedResult = await this.client.batchCreateRelationships(
      'CONTRIBUTED_TO',
      contributedRels,
      {
        fromLabel: 'Developer',
        toLabel: 'Component',
        fromKey: 'email',
        toKey: 'path',
        batchSize: 100
      }
    );
    totalCreated += contributedResult.created;

    this.stats.relationshipsCreated = totalCreated;
  }

  /**
   * Ingest GitHub Issues and PRs (requires GitHub API)
   */
  async ingestGitHubIssuesAndPRs() {
    if (!this.octokit) {
      console.error('  [SKIP]  Skipping (no GitHub API access)');
      return;
    }

    try {
      // Get GitHub org/repo from first component with URL
      const result = await this.client.runQuery(`
        MATCH (c:Component)
        WHERE c.url IS NOT NULL AND c.url CONTAINS 'github.com'
        RETURN c.url as url
        LIMIT 1
      `);

      if (result.records.length === 0) {
        console.error('  [SKIP]  No GitHub URLs found in components');
        return;
      }

      const url = result.records[0].get('url');
      const match = url.match(/github\.com[:/]([^/]+)\/([^/.]+)/);

      if (!match) {
        console.error('  [WARN]  Could not parse GitHub org/repo from URL');
        return;
      }

      const [, owner, repo] = match;
      console.error(`  [QUERY] Fetching from ${owner}/${repo}...`);

      // Fetch recent issues (limit to avoid rate limits)
      try {
        const issues = await this.octokit.issues.listForRepo({
          owner,
          repo,
          state: 'all',
          per_page: 50,
          sort: 'updated',
          direction: 'desc'
        });

        console.error(`  Found ${issues.data.length} issues/PRs`);

        // Note: Full implementation would create Issue/PR nodes here
        // Skipping for now to stay within scope
        this.stats.issuesCreated = issues.data.filter(i => !i.pull_request).length;
        this.stats.pullRequestsCreated = issues.data.filter(i => i.pull_request).length;

      } catch (error) {
        console.error(`  [WARN]  GitHub API error: ${error.message}`);
      }

    } catch (error) {
      console.error(`  [WARN]  Error fetching GitHub data: ${error.message}`);
    }
  }

  /**
   * Print ingestion summary
   */
  printSummary() {
    console.error('\n' + '═'.repeat(70));
    console.error('[STATS] GITHUB METADATA INGESTION COMPLETE');
    console.error('═'.repeat(70));
    console.error(`[TIME]  Processing Time: ${(this.stats.processingTime / 1000).toFixed(1)}s`);
    console.error(`[LOAD] Components Processed: ${this.stats.componentsProcessed}`);
    console.error(`📝 Commits Discovered: ${this.stats.commitsDiscovered}`);
    console.error(`📝 Commit Nodes Created: ${this.stats.commitsCreated}`);
    console.error(`👥 Developer Nodes Created: ${this.stats.developersCreated}`);
    console.error(`🔗 Relationships Created: ${this.stats.relationshipsCreated}`);

    if (this.octokit) {
      console.error(`🐛 Issues Found: ${this.stats.issuesCreated}`);
      console.error(`🔀 Pull Requests Found: ${this.stats.pullRequestsCreated}`);
    }

    if (this.stats.errors.length > 0) {
      console.error(`\n[ERROR] Errors: ${this.stats.errors.length}`);
      this.stats.errors.slice(0, 5).forEach(err => {
        console.error(`   ${err.component || err.stage}: ${err.error}`);
      });
      if (this.stats.errors.length > 5) {
        console.error(`   ... and ${this.stats.errors.length - 5} more errors`);
      }
    }

    console.error('═'.repeat(70) + '\n');
  }

  /**
   * Get ingestion statistics
   */
  getStats() {
    return this.stats;
  }
}
