#!/usr/bin/env node

/**
 * SubmoduleGraphIngester - Git Submodule Structure to Neo4j Graph
 *
 * Parses .gitmodules files recursively and creates a component dependency graph:
 * - Discovers all submodules in the repository tree
 * - Creates Component nodes for each repository/submodule
 * - Creates CONTAINS relationships for submodule hierarchy
 * - Extracts metadata (language, LOC, description)
 *
 * This implements Phase 0 of the Graph RAG architecture
 *
 * @version 1.0.0
 * @author NOAA EMC Global Workflow Team
 */

import fs from 'fs/promises';
import path from 'path';
import { execSync } from 'child_process';
import { NODE_TYPES, RELATIONSHIP_TYPES, generateNodeId } from './GraphSchema.js';

export class SubmoduleGraphIngester {
  constructor(neo4jClient, options = {}) {
    this.client = neo4jClient;
    this.options = {
      rootPath: options.rootPath || process.env.GIT_REPO || '/mcp_rag_eib/global-workflow_MCP_node.js-RAG',
      maxDepth: options.maxDepth || 10,
      extractLanguageInfo: options.extractLanguageInfo !== false,
      extractLOC: options.extractLOC !== false,
      verbose: options.verbose || false,
      ...options
    };

    this.stats = {
      componentsDiscovered: 0,
      componentsCreated: 0,
      relationshipsCreated: 0,
      gitmodulesFilesProcessed: 0,
      errors: [],
      processingTime: 0
    };

    this.discoveredComponents = new Map(); // path -> component data
    this.componentRelationships = []; // parent-child relationships
  }

  /**
   * Main ingestion entry point
   */
  async ingest() {
    const startTime = Date.now();
    console.error('\n[LOAD] Starting Submodule Graph Ingestion...\n');
    console.error(`📂 Root Path: ${this.options.rootPath}\n`);

    try {
      // Step 1: Discover all components
      console.error('[SEARCH] Step 1: Discovering components...');
      await this.discoverComponents(this.options.rootPath, null, 0);
      console.error(`[OK] Discovered ${this.stats.componentsDiscovered} components\n`);

      // Step 2: Create Component nodes in Neo4j
      console.error('[BUILD]  Step 2: Creating Component nodes...');
      await this.createComponentNodes();
      console.error(`[OK] Created ${this.stats.componentsCreated} nodes\n`);

      // Step 3: Create CONTAINS relationships
      console.error('🔗 Step 3: Creating CONTAINS relationships...');
      await this.createRelationships();
      console.error(`[OK] Created ${this.stats.relationshipsCreated} relationships\n`);

      // Step 4: Summary
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
   * Recursively discover all components (root + submodules)
   */
  async discoverComponents(currentPath, parentPath, depth) {
    if (depth > this.options.maxDepth) {
      console.warn(`[WARN]  Max depth ${this.options.maxDepth} reached at ${currentPath}`);
      return;
    }

    try {
      // Get component name from path
      const componentName = path.basename(currentPath);

      // Create component data with unique ID based on full path
      // Note: Using path for ID allows duplicate names at different locations
      const componentData = {
        id: generateNodeId('Component', currentPath),
        name: componentName,
        path: currentPath,
        relativePath: currentPath.replace(this.options.rootPath, '').replace(/^\//, ''),
        parentPath: parentPath,
        depth: depth,
        url: await this.getRepositoryUrl(currentPath),
        description: await this.getDescription(currentPath),
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString()
      };

      // Extract language information
      if (this.options.extractLanguageInfo) {
        componentData.language = await this.detectPrimaryLanguage(currentPath);
      }

      // Extract lines of code
      if (this.options.extractLOC) {
        componentData.loc = await this.countLinesOfCode(currentPath);
      }

      // Store discovered component
      this.discoveredComponents.set(currentPath, componentData);
      this.stats.componentsDiscovered++;

      if (this.options.verbose) {
        console.error(`  ${'  '.repeat(depth)}└─ ${componentName}`);
      }

      // Look for .gitmodules file
      const gitmodulesPath = path.join(currentPath, '.gitmodules');
      const hasGitmodules = await this.fileExists(gitmodulesPath);

      if (hasGitmodules) {
        this.stats.gitmodulesFilesProcessed++;

        // Parse .gitmodules
        const submodules = await this.parseGitmodulesFile(gitmodulesPath);

        if (this.options.verbose && submodules.length > 0) {
          console.error(`  ${'  '.repeat(depth)}   [${submodules.length} submodules]`);
        }

        // Recursively process each submodule
        for (const submodule of submodules) {
          const submodulePath = path.join(currentPath, submodule.path);

          // Check if submodule directory exists
          if (await this.directoryExists(submodulePath)) {
            // Record relationship
            this.componentRelationships.push({
              from: currentPath,
              to: submodulePath,
              type: 'CONTAINS'
            });

            // Recurse into submodule
            await this.discoverComponents(submodulePath, currentPath, depth + 1);
          } else {
            if (this.options.verbose) {
              console.warn(`  ${'  '.repeat(depth + 1)}[WARN]  Submodule not found: ${submodule.path}`);
            }
          }
        }
      }

    } catch (error) {
      console.error(`[WARN]  Error processing ${currentPath}: ${error.message}`);
      this.stats.errors.push({ path: currentPath, error: error.message });
    }
  }

  /**
   * Parse .gitmodules file
   */
  async parseGitmodulesFile(gitmodulesPath) {
    const content = await fs.readFile(gitmodulesPath, 'utf-8');
    const submodules = [];

    // Parse .gitmodules format
    // [submodule "path/to/submodule"]
    //   path = path/to/submodule
    //   url = https://github.com/org/repo.git

    const lines = content.split('\n');
    let currentSubmodule = null;

    for (const line of lines) {
      const trimmed = line.trim();

      // Match [submodule "name"]
      const submoduleMatch = trimmed.match(/^\[submodule\s+"([^"]+)"\]$/);
      if (submoduleMatch) {
        if (currentSubmodule && currentSubmodule.path) {
          submodules.push(currentSubmodule);
        }
        currentSubmodule = {
          name: submoduleMatch[1],
          path: null,
          url: null
        };
        continue;
      }

      if (currentSubmodule) {
        // Match path = ...
        const pathMatch = trimmed.match(/^path\s*=\s*(.+)$/);
        if (pathMatch) {
          currentSubmodule.path = pathMatch[1].trim();
        }

        // Match url = ...
        const urlMatch = trimmed.match(/^url\s*=\s*(.+)$/);
        if (urlMatch) {
          currentSubmodule.url = urlMatch[1].trim();
        }
      }
    }

    // Add last submodule
    if (currentSubmodule && currentSubmodule.path) {
      submodules.push(currentSubmodule);
    }

    return submodules;
  }

  /**
   * Create Component nodes in Neo4j (batch operation)
   */
  async createComponentNodes() {
    const components = Array.from(this.discoveredComponents.values());

    if (components.length === 0) {
      console.warn('[WARN]  No components to create');
      return;
    }

    const result = await this.client.batchCreateNodes(
      'Component',
      components,
      { mergeKey: 'path', batchSize: 100 }
    );

    this.stats.componentsCreated = result.created;
  }

  /**
   * Create CONTAINS relationships in Neo4j (batch operation)
   */
  async createRelationships() {
    if (this.componentRelationships.length === 0) {
      console.warn('[WARN]  No relationships to create');
      return;
    }

    // Transform relationships for batch creation
    const relationshipData = this.componentRelationships.map(rel => ({
      from: this.discoveredComponents.get(rel.from).id,
      to: this.discoveredComponents.get(rel.to).id,
      properties: {}
    }));

    const result = await this.client.batchCreateRelationships(
      'CONTAINS',
      relationshipData,
      {
        fromLabel: 'Component',
        toLabel: 'Component',
        fromKey: 'id',
        toKey: 'id',
        batchSize: 100
      }
    );

    this.stats.relationshipsCreated = result.created;
  }

  /**
   * Helper: Check if file exists
   */
  async fileExists(filePath) {
    try {
      await fs.access(filePath);
      return true;
    } catch {
      return false;
    }
  }

  /**
   * Helper: Check if directory exists
   */
  async directoryExists(dirPath) {
    try {
      const stats = await fs.stat(dirPath);
      return stats.isDirectory();
    } catch {
      return false;
    }
  }

  /**
   * Get repository URL from git config
   */
  async getRepositoryUrl(repoPath) {
    try {
      const url = execSync('git config --get remote.origin.url', {
        cwd: repoPath,
        encoding: 'utf-8',
        stdio: ['pipe', 'pipe', 'ignore']
      }).trim();
      return url;
    } catch {
      return null;
    }
  }

  /**
   * Get description from README.md
   */
  async getDescription(repoPath) {
    try {
      const readmePath = path.join(repoPath, 'README.md');
      if (await this.fileExists(readmePath)) {
        const content = await fs.readFile(readmePath, 'utf-8');
        // Extract first paragraph or first line starting with #
        const lines = content.split('\n');
        for (const line of lines) {
          const trimmed = line.trim();
          if (trimmed.startsWith('#')) {
            return trimmed.replace(/^#+\s*/, '').substring(0, 200);
          }
          if (trimmed.length > 20 && !trimmed.startsWith('!') && !trimmed.startsWith('[')) {
            return trimmed.substring(0, 200);
          }
        }
      }
      return null;
    } catch {
      return null;
    }
  }

  /**
   * Detect primary programming language
   */
  async detectPrimaryLanguage(repoPath) {
    try {
      // Count file extensions
      const extensions = {
        '.f90': 'Fortran',
        '.F90': 'Fortran',
        '.f': 'Fortran',
        '.F': 'Fortran',
        '.py': 'Python',
        '.c': 'C',
        '.cpp': 'C++',
        '.cc': 'C++',
        '.cxx': 'C++',
        '.sh': 'Shell',
        '.js': 'JavaScript',
        '.cmake': 'CMake'
      };

      const counts = {};
      const files = await this.getFilesRecursive(repoPath, 2); // Only go 2 levels deep for speed

      for (const file of files) {
        const ext = path.extname(file);
        if (extensions[ext]) {
          const lang = extensions[ext];
          counts[lang] = (counts[lang] || 0) + 1;
        }
      }

      // Return most common language
      let maxCount = 0;
      let primaryLang = 'Unknown';
      for (const [lang, count] of Object.entries(counts)) {
        if (count > maxCount) {
          maxCount = count;
          primaryLang = lang;
        }
      }

      return primaryLang;
    } catch {
      return 'Unknown';
    }
  }

  /**
   * Count lines of code (approximate)
   */
  async countLinesOfCode(repoPath) {
    try {
      // Use cloc if available, otherwise rough estimate
      try {
        const output = execSync('cloc --json --quiet .', {
          cwd: repoPath,
          encoding: 'utf-8',
          stdio: ['pipe', 'pipe', 'ignore'],
          timeout: 5000
        });
        const data = JSON.parse(output);
        return data.SUM?.code || 0;
      } catch {
        // Fallback: count lines in source files
        const files = await this.getFilesRecursive(repoPath, 3);
        let totalLines = 0;
        for (const file of files.slice(0, 100)) { // Sample first 100 files
          const ext = path.extname(file);
          if (['.f90', '.F90', '.py', '.c', '.cpp', '.sh'].includes(ext)) {
            const content = await fs.readFile(file, 'utf-8');
            totalLines += content.split('\n').length;
          }
        }
        return totalLines;
      }
    } catch {
      return 0;
    }
  }

  /**
   * Get files recursively (with depth limit)
   */
  async getFilesRecursive(dir, maxDepth, depth = 0) {
    if (depth > maxDepth) return [];

    try {
      const entries = await fs.readdir(dir, { withFileTypes: true });
      const files = [];

      for (const entry of entries) {
        const fullPath = path.join(dir, entry.name);

        // Skip hidden, build, and node_modules directories
        if (entry.name.startsWith('.') || entry.name === 'node_modules' || entry.name === 'build') {
          continue;
        }

        if (entry.isDirectory()) {
          const subFiles = await this.getFilesRecursive(fullPath, maxDepth, depth + 1);
          files.push(...subFiles);
        } else {
          files.push(fullPath);
        }
      }

      return files;
    } catch {
      return [];
    }
  }

  /**
   * Print ingestion summary
   */
  printSummary() {
    console.error('\n' + '═'.repeat(70));
    console.error('[STATS] SUBMODULE GRAPH INGESTION COMPLETE');
    console.error('═'.repeat(70));
    console.error(`[TIME]  Processing Time: ${(this.stats.processingTime / 1000).toFixed(1)}s`);
    console.error(`[LOAD] Components Discovered: ${this.stats.componentsDiscovered}`);
    console.error(`[BUILD]  Nodes Created: ${this.stats.componentsCreated}`);
    console.error(`🔗 Relationships Created: ${this.stats.relationshipsCreated}`);
    console.error(`📄 .gitmodules Files Processed: ${this.stats.gitmodulesFilesProcessed}`);

    if (this.stats.errors.length > 0) {
      console.error(`\n[ERROR] Errors: ${this.stats.errors.length}`);
      this.stats.errors.slice(0, 5).forEach(err => {
        console.error(`   ${err.path || err.stage}: ${err.error}`);
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
