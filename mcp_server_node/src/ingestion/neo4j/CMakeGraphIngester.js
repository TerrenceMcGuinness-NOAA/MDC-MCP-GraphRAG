/**
 * @file CMakeGraphIngester.js
 * @description Ingests CMake build system metadata into Neo4j graph database
 * 
 * ARCHITECTURE CONTEXT:
 * Global Workflow uses a CUSTOM build orchestration system, NOT unified CMake:
 * 
 * 1. sorc/build_all.sh - Custom parallel build orchestrator
 *    - Defines system_builds mappings (e.g., "gfs" -> "ufs_gfs gfs_utils ufs_utils upp ww3_gfs")
 *    - Executes component-specific build scripts (build_ufs.sh, build_gdas.sh, etc.)
 *    - Manages parallel job execution with resource limits
 * 
 * 2. Individual Components - Each has own CMake system
 *    - sorc/ufs_model.fd/CMakeLists.txt (UFS Weather Model)
 *    - sorc/gdas.cd/CMakeLists.txt (Data Assimilation)
 *    - sorc/gsi_enkf.fd/CMakeLists.txt (GSI Ensemble Kalman Filter)
 *    - etc. - each component builds independently
 * 
 * INGESTION STRATEGY:
 * - Parse build_all.sh to extract build orchestration relationships
 * - Recursively discover CMakeLists.txt in each component directory
 * - Parse CMake files for target definitions and dependencies
 * - Create BUILD_ORCHESTRATES relationships from build_all.sh metadata
 * - Create DEPENDS_ON relationships from CMake target_link_libraries()
 * 
 * GRAPH STRUCTURE:
 * - BuildOrchestrator node (represents build_all.sh)
 *   - BUILD_ORCHESTRATES -> Component nodes (from system_builds mapping)
 * - Library/Executable nodes (from CMake add_library/add_executable)
 *   - DEPENDS_ON -> Other Library/Executable nodes (from target_link_libraries)
 *   - BUILT_BY -> Component node (links CMake target to owning component)
 * 
 * @author Claude Code CLI + GitHub Copilot
 * @version 1.1.0 (Phase 34B: ExternalLibrary + find_package + namespace targets)
 * @since 2025-01-15
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { generateNodeId } from './GraphSchema.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

/**
 * CMakeGraphIngester - Parse CMake build system and create graph relationships
 */
export class CMakeGraphIngester {
  /**
   * @param {import('./Neo4jClient.js').Neo4jClient} neo4jClient - Neo4j client instance
   * @param {Object} options - Ingestion options
   * @param {string} options.rootDir - Root directory of global-workflow repository
   * @param {boolean} options.verbose - Enable verbose logging
   */
  constructor(neo4jClient, options = {}) {
    this.neo4jClient = neo4jClient;
    this.rootDir = options.rootDir || process.env.MCP_WORKFLOW_ROOT || '/mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow';
    this.verbose = options.verbose || false;
    
    // Known NCEPLIBS packages (Phase 34B)
    this.NCEPLIBS_PACKAGES = new Set([
      'bufr', 'ip', 'w3emc', 'w3nco', 'g2', 'g2tmpl', 'bacio',
      'nemsio', 'sfcio', 'sigio', 'landsfcutil', 'ncio', 'sp'
    ]);
    
    // Statistics tracking
    this.stats = {
      buildOrchestratorNodes: 0,
      libraryNodes: 0,
      executableNodes: 0,
      externalLibraryNodes: 0,
      cmakeFiles: 0,
      buildOrchestrationRelationships: 0,
      dependencyRelationships: 0,
      builtByRelationships: 0,
      externalDependencyRelationships: 0,
      errors: [],
      processingTime: 0
    };
  }

  /**
   * Main ingestion entry point
   */
  async ingest() {
    const startTime = Date.now();
    
    try {
      this.log('Starting CMake graph ingestion...');
      
      // Step 1: Parse build_all.sh for build orchestration metadata
      this.log('Step 1: Parsing build_all.sh for orchestration metadata...');
      const orchestrationData = await this.parseBuildOrchestrator();
      
      // Step 2: Create BuildOrchestrator node
      this.log('Step 2: Creating BuildOrchestrator node...');
      await this.createBuildOrchestratorNode(orchestrationData);
      
      // Step 3: Create BUILD_ORCHESTRATES relationships
      this.log('Step 3: Creating BUILD_ORCHESTRATES relationships...');
      await this.createOrchestrationRelationships(orchestrationData);
      
      // Step 4: Discover and parse CMakeLists.txt files
      this.log('Step 4: Discovering CMakeLists.txt files...');
      const cmakeFiles = await this.discoverCMakeFiles();
      
      // Step 5: Parse each CMakeLists.txt for targets and dependencies
      this.log(`Step 5: Parsing ${cmakeFiles.length} CMakeLists.txt files...`);
      for (const cmakeFile of cmakeFiles) {
        await this.parseCMakeFile(cmakeFile);
      }
      
      this.stats.processingTime = ((Date.now() - startTime) / 1000).toFixed(2);
      
      this.log('\nCMake ingestion complete!');
      this.printStats();
      
      return this.stats;
      
    } catch (error) {
      this.stats.errors.push(`Fatal error: ${error.message}`);
      throw error;
    }
  }

  /**
   * Parse build_all.sh to extract build orchestration metadata
   * @returns {Object} Build orchestration data structure
   */
  async parseBuildOrchestrator() {
    const buildAllPath = path.join(this.rootDir, 'sorc', 'build_all.sh');
    
    if (!fs.existsSync(buildAllPath)) {
      throw new Error(`build_all.sh not found at ${buildAllPath}`);
    }
    
    const content = fs.readFileSync(buildAllPath, 'utf-8');
    
    // Extract system_builds mapping using regex
    // Pattern: ["system_name"]="component1 component2 ..."
    const systemBuildsRegex = /\["(\w+)"\]="([^"]+)"/g;
    const systemBuilds = {};
    
    let match;
    while ((match = systemBuildsRegex.exec(content)) !== null) {
      const [, systemName, components] = match;
      systemBuilds[systemName] = components.trim().split(/\s+/);
    }
    
    // Extract build_scripts mapping
    const buildScriptsSection = content.match(/build_scripts=\(([\s\S]*?)\)/);
    const buildScripts = {};
    
    if (buildScriptsSection) {
      const scriptLines = buildScriptsSection[1].match(/\["(\w+)"\]="([^"]+)"/g) || [];
      for (const line of scriptLines) {
        const scriptMatch = line.match(/\["(\w+)"\]="([^"]+)"/);
        if (scriptMatch) {
          buildScripts[scriptMatch[1]] = scriptMatch[2];
        }
      }
    }
    
    // Extract build_opts mapping
    const buildOptsSection = content.match(/build_opts=\(([\s\S]*?)\)/);
    const buildOpts = {};
    
    if (buildOptsSection) {
      const optsLines = buildOptsSection[1].match(/\["(\w+)"\]="[^"]*"/g) || [];
      for (const line of optsLines) {
        const optsMatch = line.match(/\["(\w+)"\]="([^"]*)"/);
        if (optsMatch) {
          buildOpts[optsMatch[1]] = optsMatch[2];
        }
      }
    }
    
    // Extract build_jobs mapping
    const buildJobsSection = content.match(/build_jobs=\(([\s\S]*?)\)/);
    const buildJobs = {};
    
    if (buildJobsSection) {
      const jobsLines = buildJobsSection[1].match(/\["(\w+)"\]=\d+/g) || [];
      for (const line of jobsLines) {
        const jobsMatch = line.match(/\["(\w+)"\]=(\d+)/);
        if (jobsMatch) {
          buildJobs[jobsMatch[1]] = parseInt(jobsMatch[2], 10);
        }
      }
    }
    
    this.log(`Parsed build orchestration: ${Object.keys(systemBuilds).length} systems, ${Object.keys(buildScripts).length} components`);
    
    return {
      systemBuilds,
      buildScripts,
      buildOpts,
      buildJobs,
      scriptPath: buildAllPath
    };
  }

  /**
   * Create BuildOrchestrator node representing build_all.sh
   */
  async createBuildOrchestratorNode(orchestrationData) {
    const nodeId = 'build_orchestrator:build_all.sh';
    
    const query = `
      MERGE (bo:BuildOrchestrator {id: $id})
      SET bo.name = $name,
          bo.path = $path,
          bo.type = $type,
          bo.systemsManaged = $systemsManaged,
          bo.componentsManaged = $componentsManaged,
          bo.lastUpdated = datetime()
      RETURN bo
    `;
    
    const params = {
      id: nodeId,
      name: 'build_all.sh',
      path: orchestrationData.scriptPath,
      type: 'parallel_orchestrator',
      systemsManaged: Object.keys(orchestrationData.systemBuilds),
      componentsManaged: Object.keys(orchestrationData.buildScripts)
    };
    
    await this.neo4jClient.runWriteQuery(query, params);
    this.stats.buildOrchestratorNodes++;
    
    this.log(`Created BuildOrchestrator node: ${nodeId}`);
  }

  /**
   * Create BUILD_ORCHESTRATES relationships from BuildOrchestrator to Components
   */
  async createOrchestrationRelationships(orchestrationData) {
    const relationships = [];
    
    // For each system build mapping, create relationships to components
    for (const [systemName, components] of Object.entries(orchestrationData.systemBuilds)) {
      for (const componentName of components) {
        // Map component names to actual component IDs from submodule ingestion
        // Component IDs follow pattern: component:sorc/<component_dir>
        const componentId = this.mapComponentNameToId(componentName);
        
        relationships.push({
          buildOrchestratorId: 'build_orchestrator:build_all.sh',
          componentId,
          systemName,
          buildScript: orchestrationData.buildScripts[componentName] || 'unknown',
          buildOptions: orchestrationData.buildOpts[componentName] || '',
          parallelJobs: orchestrationData.buildJobs[componentName] || 1
        });
      }
    }
    
    // Batch create relationships
    const query = `
      UNWIND $relationships AS rel
      MATCH (bo:BuildOrchestrator {id: rel.buildOrchestratorId})
      MATCH (c:Component {id: rel.componentId})
      MERGE (bo)-[r:BUILD_ORCHESTRATES]->(c)
      SET r.systemName = rel.systemName,
          r.buildScript = rel.buildScript,
          r.buildOptions = rel.buildOptions,
          r.parallelJobs = rel.parallelJobs,
          r.lastUpdated = datetime()
      RETURN count(r) as relCount
    `;
    
    const result = await this.neo4jClient.runWriteQuery(query, { relationships });
    const relCount = result.records[0]?.get('relCount')?.toNumber() || 0;
    this.stats.buildOrchestrationRelationships += relCount;
    
    this.log(`Created ${relCount} BUILD_ORCHESTRATES relationships`);
  }

  /**
   * Map component name from build_all.sh to Component node ID
   * @param {string} componentName - Component name from build_all.sh (e.g., "ufs_gfs", "gdas")
   * @returns {string} Component ID for graph node
   */
  mapComponentNameToId(componentName) {
    // Mapping from build_all.sh component names to actual directory names
    const nameMapping = {
      'ufs_gfs': 'sorc/ufs_model.fd',
      'ufs_gefs': 'sorc/ufs_model.fd',
      'ufs_sfs': 'sorc/ufs_model.fd',
      'ufs_gcafs': 'sorc/ufs_model.fd',
      'gdas': 'sorc/gdas.cd',
      'gsi_enkf': 'sorc/gsi_enkf.fd',
      'gsi_utils': 'sorc/gsi_utils.fd',
      'gsi_monitor': 'sorc/gsi_monitor.fd',
      'gfs_utils': 'sorc/gfs_utils.fd',
      'ufs_utils': 'sorc/ufs_utils.fd',
      'upp': 'sorc/upp.fd',
      'ww3_gfs': 'sorc/ww3.fd',
      'ww3_gefs': 'sorc/ww3.fd'
    };
    
    const relativePath = nameMapping[componentName] || `sorc/${componentName}.fd`;
    const absolutePath = path.join(this.rootDir, relativePath);
    return generateNodeId('Component', absolutePath);
  }

  /**
   * Recursively discover all CMakeLists.txt files in sorc/ directory
   * @returns {Array<Object>} Array of {path, componentId} objects
   */
  async discoverCMakeFiles() {
    const cmakeFiles = [];
    const sourcDir = path.join(this.rootDir, 'sorc');
    
    const walkDir = (dir, componentPath = '') => {
      if (!fs.existsSync(dir)) return;
      
      const entries = fs.readdirSync(dir, { withFileTypes: true });
      
      for (const entry of entries) {
        const fullPath = path.join(dir, entry.name);
        
        if (entry.isDirectory()) {
          // Recursively walk subdirectories
          walkDir(fullPath, componentPath ? `${componentPath}/${entry.name}` : entry.name);
        } else if (entry.name === 'CMakeLists.txt') {
          // Found a CMakeLists.txt file
          const relativePath = path.relative(this.rootDir, fullPath);
          const componentId = this.deriveComponentIdFromPath(relativePath);
          
          cmakeFiles.push({
            path: fullPath,
            relativePath,
            componentId
          });
        }
      }
    };
    
    walkDir(sourcDir);
    
    this.stats.cmakeFiles = cmakeFiles.length;
    this.log(`Discovered ${cmakeFiles.length} CMakeLists.txt files`);
    
    return cmakeFiles;
  }

  /**
   * Derive Component ID from CMakeLists.txt file path
   * @param {string} relativePath - Relative path to CMakeLists.txt
   * @returns {string} Component ID
   */
  deriveComponentIdFromPath(relativePath) {
    // Extract component directory from path (e.g., sorc/ufs_model.fd/CMakeLists.txt -> sorc/ufs_model.fd)
    const pathParts = relativePath.split('/');
    
    // Find the component directory (ends with .fd or .cd)
    let componentPath = '';
    for (let i = 0; i < pathParts.length; i++) {
      if (pathParts[i].endsWith('.fd') || pathParts[i].endsWith('.cd')) {
        componentPath = pathParts.slice(0, i + 1).join('/');
        break;
      }
    }
    
    // If no .fd/.cd directory, use first two parts (sorc/<component>)
    if (!componentPath) {
      componentPath = pathParts.slice(0, 2).join('/');
    }
    
    const absolutePath = path.join(this.rootDir, componentPath);
    return generateNodeId('Component', absolutePath);
  }

  /**
   * Parse a single CMakeLists.txt file for targets and dependencies
   * @param {Object} cmakeFile - {path, relativePath, componentId}
   */
  async parseCMakeFile(cmakeFile) {
    try {
      const content = fs.readFileSync(cmakeFile.path, 'utf-8');
      
      // Parse add_library() directives
      const libraries = this.parseCMakeLibraries(content, cmakeFile);
      
      // Parse add_executable() directives
      const executables = this.parseCMakeExecutables(content, cmakeFile);
      
      // Parse target_link_libraries() for dependencies
      const dependencies = this.parseCMakeDependencies(content, cmakeFile);
      
      // Parse find_package() for external library dependencies (Phase 34B)
      const externalPackages = this.parseCMakeExternalPackages(content, cmakeFile);
      
      // Create Library nodes
      if (libraries.length > 0) {
        await this.createLibraryNodes(libraries, cmakeFile.componentId);
      }
      
      // Create Executable nodes
      if (executables.length > 0) {
        await this.createExecutableNodes(executables, cmakeFile.componentId);
      }
      
      // Create ExternalLibrary nodes from find_package() (Phase 34B)
      if (externalPackages.length > 0) {
        await this.createExternalLibraryNodes(externalPackages);
      }
      
      // Create DEPENDS_ON relationships (includes namespace target resolution)
      if (dependencies.length > 0) {
        await this.createDependencyRelationships(dependencies, cmakeFile.componentId);
      }
      
    } catch (error) {
      this.stats.errors.push(`Error parsing ${cmakeFile.relativePath}: ${error.message}`);
      this.log(`ERROR: Failed to parse ${cmakeFile.relativePath}: ${error.message}`);
    }
  }

  /**
   * Parse add_library() directives from CMakeLists.txt
   * @param {string} content - CMakeLists.txt content
   * @param {Object} cmakeFile - File metadata
   * @returns {Array<Object>} Array of library objects
   */
  parseCMakeLibraries(content, cmakeFile) {
    const libraries = [];
    
    // Regex pattern: add_library(target_name ...)
    // Handles multi-line declarations
    const libraryRegex = /add_library\s*\(\s*([A-Za-z0-9_:-]+)(?:\s+[A-Z]+)?\s+([^)]*)\)/g;
    
    let match;
    while ((match = libraryRegex.exec(content)) !== null) {
      const [, targetName, sources] = match;
      
      libraries.push({
        name: targetName,
        sources: sources.trim().split(/\s+/).filter(s => s.length > 0),
        cmakeFile: cmakeFile.relativePath
      });
    }
    
    return libraries;
  }

  /**
   * Parse add_executable() directives from CMakeLists.txt
   * @param {string} content - CMakeLists.txt content
   * @param {Object} cmakeFile - File metadata
   * @returns {Array<Object>} Array of executable objects
   */
  parseCMakeExecutables(content, cmakeFile) {
    const executables = [];
    
    // Regex pattern: add_executable(target_name ...)
    const executableRegex = /add_executable\s*\(\s*([A-Za-z0-9_:-]+)\s+([^)]*)\)/g;
    
    let match;
    while ((match = executableRegex.exec(content)) !== null) {
      const [, targetName, sources] = match;
      
      executables.push({
        name: targetName,
        sources: sources.trim().split(/\s+/).filter(s => s.length > 0),
        cmakeFile: cmakeFile.relativePath
      });
    }
    
    return executables;
  }

  /**
   * Parse target_link_libraries() for dependency relationships
   * @param {string} content - CMakeLists.txt content
   * @param {Object} cmakeFile - File metadata
   * @returns {Array<Object>} Array of dependency objects
   */
  parseCMakeDependencies(content, cmakeFile) {
    const dependencies = [];
    
    // Regex pattern: target_link_libraries(target_name lib1 lib2 ...)
    // Handles PUBLIC, PRIVATE, INTERFACE keywords
    const linkRegex = /target_link_libraries\s*\(\s*([A-Za-z0-9_:-]+)\s+([^)]+)\)/g;
    
    let match;
    while ((match = linkRegex.exec(content)) !== null) {
      const [, targetName, libs] = match;
      
      // Parse libraries (filter out keywords PUBLIC, PRIVATE, INTERFACE)
      const libList = libs.trim().split(/\s+/).filter(lib => 
        lib.length > 0 && 
        !['PUBLIC', 'PRIVATE', 'INTERFACE'].includes(lib)
      );
      
      for (const lib of libList) {
        dependencies.push({
          target: targetName,
          dependency: lib,
          cmakeFile: cmakeFile.relativePath
        });
      }
    }
    
    return dependencies;
  }

  /**
   * Parse find_package() directives for external library detection (Phase 34B)
   * @param {string} content - CMakeLists.txt content
   * @param {Object} cmakeFile - File metadata
   * @returns {Array<Object>} Array of external package objects
   */
  parseCMakeExternalPackages(content, cmakeFile) {
    const packages = [];
    
    // Pattern: find_package(name [version] [REQUIRED] [QUIET] [CONFIG] [MODULE] [COMPONENTS ...])
    const findPkgRegex = /find_package\s*\(\s*([A-Za-z0-9_]+)(?:\s+([0-9][0-9.]*))?([^)]*)\)/g;
    
    let match;
    while ((match = findPkgRegex.exec(content)) !== null) {
      const [, packageName, version, rest] = match;
      const isRequired = rest ? rest.includes('REQUIRED') : false;
      const isNCEPLIBS = this.NCEPLIBS_PACKAGES.has(packageName.toLowerCase());
      
      packages.push({
        name: packageName.toLowerCase(),
        version: version || null,
        required: isRequired,
        family: isNCEPLIBS ? 'NCEPLIBS' : null,
        repo_url: isNCEPLIBS ? `https://github.com/NOAA-EMC/NCEPLIBS-${packageName.toLowerCase()}` : null,
        cmakeFile: cmakeFile.relativePath
      });
    }
    
    return packages;
  }

  /**
   * Create Library nodes in Neo4j
   */
  async createLibraryNodes(libraries, componentId) {
    const nodes = libraries.map(lib => ({
      id: generateNodeId('Library', `${componentId}_${lib.name}`),
      name: lib.name,
      type: 'static_or_shared',
      sourceFiles: lib.sources,
      cmakeFile: lib.cmakeFile,
      componentId
    }));
    
    const query = `
      UNWIND $nodes AS node
      MERGE (l:Library {id: node.id})
      SET l.name = node.name,
          l.type = node.type,
          l.sourceFiles = node.sourceFiles,
          l.cmakeFile = node.cmakeFile,
          l.lastUpdated = datetime()
      WITH l, node
      MATCH (c:Component {id: node.componentId})
      MERGE (l)-[r:BUILT_BY]->(c)
      SET r.lastUpdated = datetime()
      RETURN count(l) as nodeCount
    `;
    
    const result = await this.neo4jClient.runWriteQuery(query, { nodes });
    const nodeCount = result.records[0]?.get('nodeCount')?.toNumber() || 0;
    
    this.stats.libraryNodes += nodeCount;
    this.stats.builtByRelationships += nodeCount;
    
    this.log(`Created ${nodeCount} Library nodes`);
  }

  /**
   * Create Executable nodes in Neo4j
   */
  async createExecutableNodes(executables, componentId) {
    const nodes = executables.map(exe => ({
      id: generateNodeId('Executable', `${componentId}_${exe.name}`),
      name: exe.name,
      type: 'binary',
      sourceFiles: exe.sources,
      cmakeFile: exe.cmakeFile,
      componentId
    }));
    
    const query = `
      UNWIND $nodes AS node
      MERGE (e:Executable {id: node.id})
      SET e.name = node.name,
          e.type = node.type,
          e.sourceFiles = node.sourceFiles,
          e.cmakeFile = node.cmakeFile,
          e.lastUpdated = datetime()
      WITH e, node
      MATCH (c:Component {id: node.componentId})
      MERGE (e)-[r:BUILT_BY]->(c)
      SET r.lastUpdated = datetime()
      RETURN count(e) as nodeCount
    `;
    
    const result = await this.neo4jClient.runWriteQuery(query, { nodes });
    const nodeCount = result.records[0]?.get('nodeCount')?.toNumber() || 0;
    
    this.stats.executableNodes += nodeCount;
    this.stats.builtByRelationships += nodeCount;
    
    this.log(`Created ${nodeCount} Executable nodes`);
  }

  /**
   * Create ExternalLibrary nodes from find_package() results (Phase 34B)
   */
  async createExternalLibraryNodes(packages) {
    const nodes = packages.map(pkg => ({
      name: pkg.name,
      version: pkg.version,
      family: pkg.family,
      repo_url: pkg.repo_url,
      required: pkg.required,
      cmakeFile: pkg.cmakeFile
    }));
    
    const query = `
      UNWIND $nodes AS node
      MERGE (el:ExternalLibrary {name: node.name})
      SET el.version = CASE WHEN node.version IS NOT NULL THEN node.version ELSE el.version END,
          el.family = CASE WHEN node.family IS NOT NULL THEN node.family ELSE el.family END,
          el.repo_url = CASE WHEN node.repo_url IS NOT NULL THEN node.repo_url ELSE el.repo_url END,
          el.required = node.required,
          el.cmake_target = node.name,
          el.lastUpdated = datetime()
      RETURN count(el) as nodeCount
    `;
    
    const result = await this.neo4jClient.runWriteQuery(query, { nodes });
    const nodeCount = result.records[0]?.get('nodeCount')?.toNumber() || 0;
    
    this.stats.externalLibraryNodes += nodeCount;
    
    this.log(`Created ${nodeCount} ExternalLibrary nodes`);
  }

  /**
   * Create DEPENDS_ON relationships between targets
   * Enhanced in Phase 34B: resolves namespace targets (e.g., bufr::bufr_4 → ExternalLibrary bufr)
   */
  async createDependencyRelationships(dependencies, componentId) {
    if (dependencies.length === 0) {
      return;
    }
    
    // Separate internal dependencies from namespace (external) dependencies
    const internalDeps = [];
    const externalDeps = [];
    
    for (const dep of dependencies) {
      if (dep.dependency.includes('::')) {
        // Namespace target: bufr::bufr_4 → library "bufr", variant "bufr_4"
        const [namespace] = dep.dependency.split('::');
        externalDeps.push({
          target: dep.target,
          externalLib: namespace.toLowerCase(),
          fullTarget: dep.dependency,
          cmakeFile: dep.cmakeFile
        });
      } else {
        internalDeps.push(dep);
      }
    }
    
    // Create internal DEPENDS_ON relationships (existing behavior)
    if (internalDeps.length > 0) {
      const query = `
        UNWIND $dependencies AS dep
        MATCH (target) WHERE (target:Library OR target:Executable) AND target.name = dep.target
        MATCH (dependency) WHERE (dependency:Library OR dependency:Executable) AND dependency.name = dep.dependency
        MERGE (target)-[r:DEPENDS_ON]->(dependency)
        SET r.linkType = 'cmake_target_link',
            r.cmakeFile = dep.cmakeFile,
            r.lastUpdated = datetime()
        RETURN count(r) as relCount
      `;
      
      const result = await this.neo4jClient.runWriteQuery(query, { dependencies: internalDeps });
      const relCount = result.records[0]?.get('relCount')?.toNumber() || 0;
      this.stats.dependencyRelationships += relCount;
      
      if (relCount > 0) {
        this.log(`Created ${relCount} internal DEPENDS_ON relationships`);
      }
    }
    
    // Create external DEPENDS_ON relationships to ExternalLibrary nodes (Phase 34B)
    if (externalDeps.length > 0) {
      const query = `
        UNWIND $dependencies AS dep
        MATCH (target) WHERE (target:Library OR target:Executable) AND target.name = dep.target
        MERGE (el:ExternalLibrary {name: dep.externalLib})
        MERGE (target)-[r:DEPENDS_ON]->(el)
        SET r.linkType = 'cmake_namespace_target',
            r.fullTarget = dep.fullTarget,
            r.cmakeFile = dep.cmakeFile,
            r.lastUpdated = datetime()
        RETURN count(r) as relCount
      `;
      
      const result = await this.neo4jClient.runWriteQuery(query, { dependencies: externalDeps });
      const relCount = result.records[0]?.get('relCount')?.toNumber() || 0;
      this.stats.externalDependencyRelationships += relCount;
      
      if (relCount > 0) {
        this.log(`Created ${relCount} external DEPENDS_ON relationships (namespace targets)`);
      }
    }
  }

  /**
   * Print ingestion statistics
   */
  printStats() {
    console.log('\n=== CMake Ingestion Statistics ===');
    console.log(`BuildOrchestrator nodes: ${this.stats.buildOrchestratorNodes}`);
    console.log(`Library nodes: ${this.stats.libraryNodes}`);
    console.log(`Executable nodes: ${this.stats.executableNodes}`);
    console.log(`ExternalLibrary nodes: ${this.stats.externalLibraryNodes}`);
    console.log(`CMakeLists.txt files processed: ${this.stats.cmakeFiles}`);
    console.log(`BUILD_ORCHESTRATES relationships: ${this.stats.buildOrchestrationRelationships}`);
    console.log(`DEPENDS_ON relationships (internal): ${this.stats.dependencyRelationships}`);
    console.log(`DEPENDS_ON relationships (external): ${this.stats.externalDependencyRelationships}`);
    console.log(`BUILT_BY relationships: ${this.stats.builtByRelationships}`);
    console.log(`Processing time: ${this.stats.processingTime}s`);
    
    if (this.stats.errors.length > 0) {
      console.log(`\nErrors encountered: ${this.stats.errors.length}`);
      this.stats.errors.forEach((err, i) => console.log(`  ${i + 1}. ${err}`));
    }
  }

  /**
   * Logging helper
   */
  log(message) {
    if (this.verbose) {
      console.log(message);
    }
  }
}

export default CMakeGraphIngester;
