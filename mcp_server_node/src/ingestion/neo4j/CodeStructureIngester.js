/**
 * Code Structure Graph Ingester
 * 
 * Parses source code files (Python, Shell, Fortran) and ingests code structure into Neo4j:
 * - Functions, classes, modules
 * - Import/use relationships
 * - Function call graphs
 * - Links to Component nodes from Phase 0
 * 
 * Architecture:
 * - Uses language-specific parsers (Python AST, regex for Shell/Fortran)
 * - Batch processing for large codebases (3000+ files)
 * - Links code entities to File nodes, which link to Component nodes
 * - Creates call graphs for runtime analysis
 */

import { spawn } from 'child_process';
import path from 'path';
import { fileURLToPath } from 'url';
import fs from 'fs/promises';
import { generateNodeId } from './GraphSchema.js';

export class CodeStructureIngester {
  /**
   * @param {Neo4jClient} neo4jClient - Initialized Neo4j client
   * @param {string} rootDir - Repository root directory (absolute path)
   */
  constructor(neo4jClient, rootDir) {
    this.client = neo4jClient;
    this.rootDir = rootDir;
    this.stats = {
      filesProcessed: 0,
      filesFailed: 0,
      functionsCreated: 0,
      classesCreated: 0,
      importsCreated: 0,
      callsCreated: 0,
      definesCreated: 0,
      // v8: J-Job specific stats
      jjobsProcessed: 0,
      execScriptsLinked: 0
    };
  }

  /**
   * Main entry point: Ingest code structure for specified language
   * @param {string} language - Language to parse ('python', 'shell', 'fortran')
   * @param {string[]} targetPaths - Optional specific paths to parse (relative to rootDir)
   * @param {Object} options - Processing options
   */
  async ingestCodeStructure(language, targetPaths = null, options = {}) {
    const { verbose = false, batchSize = 50 } = options;
    
    console.log(`\n=== Code Structure Ingestion: ${language.toUpperCase()} ===`);
    console.log(`Root directory: ${this.rootDir}`);
    
    const startTime = Date.now();
    
    try {
      // Discover source files
      const files = await this.discoverSourceFiles(language, targetPaths);
      console.log(`Discovered ${files.length} ${language} files`);
      
      if (files.length === 0) {
        console.log('No files to process');
        return this.stats;
      }
      
      // Process files in batches
      for (let i = 0; i < files.length; i += batchSize) {
        const batch = files.slice(i, Math.min(i + batchSize, files.length));
        console.log(`\nProcessing batch ${Math.floor(i / batchSize) + 1}/${Math.ceil(files.length / batchSize)} (${batch.length} files)...`);
        
        await this.processBatch(language, batch, verbose);
      }
      
      const elapsed = ((Date.now() - startTime) / 1000).toFixed(2);
      console.log(`\n=== Ingestion Complete ===`);
      console.log(`Files processed: ${this.stats.filesProcessed}`);
      console.log(`Files failed: ${this.stats.filesFailed}`);
      console.log(`Functions created: ${this.stats.functionsCreated}`);
      console.log(`Classes created: ${this.stats.classesCreated}`);
      console.log(`Import relationships: ${this.stats.importsCreated}`);
      console.log(`Call relationships: ${this.stats.callsCreated}`);
      console.log(`Defines relationships: ${this.stats.definesCreated}`);
      // v8: J-Job stats
      if (this.stats.jjobsProcessed > 0) {
        console.log(`J-Jobs processed: ${this.stats.jjobsProcessed}`);
        console.log(`Ex-script links: ${this.stats.execScriptsLinked}`);
      }
      console.log(`Processing time: ${elapsed}s`);
      
      return this.stats;
      
    } catch (error) {
      console.error('Ingestion failed:', error.message);
      throw error;
    }
  }

  /**
   * Discover source files for given language
   * @param {string} language - Language to search for
   * @param {string[]} targetPaths - Optional specific paths (relative)
   * @returns {Promise<string[]>} - Array of absolute file paths
   */
  async discoverSourceFiles(language, targetPaths = null) {
    const extensions = {
      python: ['.py'],
      shell: ['.sh'],
      fortran: ['.f90', '.F90', '.f', '.F']
    };
    
    const searchPaths = targetPaths || this.getDefaultSearchPaths(language);
    const targetExtensions = extensions[language];
    
    const files = [];
    
    for (const searchPath of searchPaths) {
      const absolutePath = path.isAbsolute(searchPath) 
        ? searchPath 
        : path.join(this.rootDir, searchPath);
      
      try {
        // v8: Special handling for dev/jobs which contains extensionless J-Jobs
        const isJJobDir = searchPath.includes('dev/jobs');
        const discovered = await this.findFilesRecursive(absolutePath, targetExtensions, { 
          includeJJobs: isJJobDir && language === 'shell' 
        });
        files.push(...discovered);
      } catch (error) {
        console.warn(`Warning: Could not search ${absolutePath}: ${error.message}`);
      }
    }
    
    return files;
  }

  /**
   * Get default search paths for each language
   * @param {string} language - Language identifier
   * @returns {string[]} - Array of relative paths to search
   */
  getDefaultSearchPaths(language) {
    switch (language) {
      case 'python':
        return ['scripts', 'ush/python'];
      case 'shell':
        // v8: Include dev/ directory structure (post-refactoring)
        return [
          'dev/jobs',       // J-Jobs (JGDAS_*, JGFS_*, JGLOBAL_*)
          'dev/scripts',    // ex-scripts (exgdas_*, exgfs_*)
          'scripts',        // Legacy location
          'ush'             // Utility shell scripts
        ];
      case 'fortran':
        return ['sorc/gdas.cd', 'sorc/ufs_model.fd'];
      default:
        return [];
    }
  }

  /**
   * Recursively find files with target extensions
   * @param {string} dir - Directory to search (absolute)
   * @param {string[]} extensions - File extensions to match
   * @param {Object} options - Search options
   * @param {boolean} options.includeJJobs - Include J-Job files (no extension, starts with J)
   * @returns {Promise<string[]>} - Array of matching file paths
   */
  async findFilesRecursive(dir, extensions, options = {}) {
    const { includeJJobs = false } = options;
    const files = [];
    
    try {
      const entries = await fs.readdir(dir, { withFileTypes: true });
      
      for (const entry of entries) {
        const fullPath = path.join(dir, entry.name);
        
        if (entry.isDirectory()) {
          // Skip hidden directories and common excludes
          if (!entry.name.startsWith('.') && entry.name !== 'node_modules') {
            const subFiles = await this.findFilesRecursive(fullPath, extensions, options);
            files.push(...subFiles);
          }
        } else if (entry.isFile()) {
          const ext = path.extname(entry.name);
          
          // Match by extension
          if (extensions.includes(ext)) {
            files.push(fullPath);
          }
          // v8: Also match J-Job files (start with J, no extension, executable shell scripts)
          else if (includeJJobs && ext === '' && entry.name.match(/^J[A-Z]+/)) {
            files.push(fullPath);
          }
        }
      }
    } catch (error) {
      // Directory doesn't exist or no permission - skip silently
    }
    
    return files;
  }

  /**
   * Process a batch of files
   * @param {string} language - Language being processed
   * @param {string[]} files - Batch of file paths (absolute)
   * @param {boolean} verbose - Verbose logging
   */
  async processBatch(language, files, verbose) {
    const parsers = {
      python: this.parsePythonFiles.bind(this),
      shell: this.parseShellFiles.bind(this),
      fortran: this.parseFortranFiles.bind(this)
    };
    
    const parser = parsers[language];
    if (!parser) {
      throw new Error(`Unsupported language: ${language}`);
    }
    
    // Parse files
    const parseResults = await parser(files);
    
    // Ingest into Neo4j
    for (const result of parseResults) {
      try {
        if (result.success) {
          await this.ingestFileStructure(result, language, verbose);
          this.stats.filesProcessed++;
        } else {
          if (verbose) {
            console.log(`  ✗ ${path.relative(this.rootDir, result.file_path)}: ${result.error_message}`);
          }
          this.stats.filesFailed++;
        }
      } catch (error) {
        console.error(`Error ingesting ${result.file_path}: ${error.message}`);
        this.stats.filesFailed++;
      }
    }
  }

  /**
   * Parse Python files using AST parser
   * @param {string[]} files - Array of file paths (absolute)
   * @returns {Promise<Object[]>} - Parse results
   */
  async parsePythonFiles(files) {
    // Script location: check environment variable first, then use path relative to this module
    const __filename = fileURLToPath(import.meta.url);
    const __dirname = path.dirname(__filename);
    const scriptPath = process.env.PYTHON_AST_SCRIPT || 
      path.resolve(__dirname, '../../../scripts/parse-python-ast.py');
    
    return new Promise((resolve, reject) => {
      const args = files;
      const process = spawn('python3', [scriptPath, ...args]);
      
      let stdout = '';
      let stderr = '';
      
      process.stdout.on('data', (data) => {
        stdout += data.toString();
      });
      
      process.stderr.on('data', (data) => {
        stderr += data.toString();
      });
      
      process.on('close', (code) => {
        if (code !== 0) {
          reject(new Error(`Python parser failed: ${stderr}`));
        } else {
          try {
            const results = JSON.parse(stdout);
            resolve(results);
          } catch (error) {
            reject(new Error(`Failed to parse JSON output: ${error.message}`));
          }
        }
      });
    });
  }

  /**
   * Parse Shell files using regex patterns
   * @param {string[]} files - Array of file paths (absolute)
   * @returns {Promise<Object[]>} - Parse results
   */
  async parseShellFiles(files) {
    const results = [];
    
    for (const filePath of files) {
      try {
        const content = await fs.readFile(filePath, 'utf-8');
        const parseResult = this.parseShellContent(filePath, content);
        results.push(parseResult);
      } catch (error) {
        results.push({
          file_path: filePath,
          success: false,
          error: 'read_error',
          error_message: error.message
        });
      }
    }
    
    return results;
  }

  /**
   * Parse shell script content using regex
   * @param {string} filePath - File path
   * @param {string} content - File content
   * @returns {Object} - Parse result
   */
  parseShellContent(filePath, content) {
    const functions = [];
    const sources = [];
    const calls = [];
    const execScripts = [];  // v8: Track ex-script executions
    const metadata = {};     // v8: J-Job metadata
    
    // Split into lines for line number tracking
    const lines = content.split('\n');
    const fileName = path.basename(filePath);
    
    // v8: Detect if this is a J-Job (starts with J, no extension)
    const isJJob = /^J[A-Z]+/.test(fileName) && !path.extname(filePath);
    
    // Regex patterns
    const functionPattern1 = /^function\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(\s*\)\s*\{?/; // function name() {
    const functionPattern2 = /^([a-zA-Z_][a-zA-Z0-9_]*)\s*\(\s*\)\s*\{/; // name() {
    const sourcePattern = /^\s*(?:source|\.)\s+["']?([^"'\s]+)["']?/; // source file or . file
    
    // v8: J-Job specific patterns
    const jjobHeaderPattern = /source.*jjob_header\.sh.*-e\s*["']?([^"'\s]+)["']?.*-c\s*["']?([^"']+)["']?/;
    const exScriptPattern = /\$\{SCRIPT[S]?[a-zA-Z_]*\}\/([a-zA-Z_][a-zA-Z0-9_]*\.sh)/;
    const exScriptPattern2 = /\$\{SCR[a-zA-Z_]*\}\/([a-zA-Z_][a-zA-Z0-9_]*\.sh)/;
    const exScriptDirectPattern = /["']?\$\{[A-Z_]+\}\/?(ex[a-z0-9_]+\.sh)["']?/;
    
    // Track current function context
    let currentFunction = null;
    let braceDepth = 0;
    
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const lineNumber = i + 1;
      
      // Skip comments and empty lines
      if (line.trim().startsWith('#') || line.trim() === '') {
        continue;
      }
      
      // v8: Check for jjob_header.sh sourcing (captures task and config names)
      if (isJJob) {
        const jjobMatch = line.match(jjobHeaderPattern);
        if (jjobMatch) {
          metadata.task = jjobMatch[1];
          metadata.configs = jjobMatch[2].split(/\s+/);
          sources.push({
            file: 'jjob_header.sh',
            line_number: lineNumber,
            type: 'jjob_header',
            task: jjobMatch[1],
            configs: jjobMatch[2]
          });
          continue;
        }
        
        // v8: Check for ex-script executions
        const exMatch = line.match(exScriptPattern) || 
                        line.match(exScriptPattern2) || 
                        line.match(exScriptDirectPattern);
        if (exMatch) {
          const exScript = exMatch[1];
          execScripts.push({
            script: exScript,
            line_number: lineNumber,
            caller_function: currentFunction?.name || null
          });
          // Also add as a call for relationship tracking
          calls.push({
            callee: exScript.replace('.sh', ''),
            line_number: lineNumber,
            caller_function: currentFunction?.name || '_main_',
            call_type: 'ex_script'
          });
        }
      }
      
      // Check for function definitions
      let match = line.match(functionPattern1) || line.match(functionPattern2);
      if (match) {
        const funcName = match[1];
        const funcInfo = {
          name: funcName,
          line_number: lineNumber,
          end_line: null, // Will be updated when function ends
          type: 'shell_function'
        };
        functions.push(funcInfo);
        currentFunction = funcInfo;
        braceDepth = line.includes('{') ? 1 : 0;
        continue;
      }
      
      // Track brace depth for function end detection
      if (currentFunction) {
        const openBraces = (line.match(/\{/g) || []).length;
        const closeBraces = (line.match(/\}/g) || []).length;
        braceDepth += openBraces - closeBraces;
        
        if (braceDepth === 0 && closeBraces > 0) {
          currentFunction.end_line = lineNumber;
          currentFunction = null;
        }
      }
      
      // Check for source/. commands (skip if already captured as jjob_header)
      if (!line.includes('jjob_header')) {
        match = line.match(sourcePattern);
        if (match) {
          const sourcedFile = match[1];
          sources.push({
            file: sourcedFile,
            line_number: lineNumber,
            type: line.trim().startsWith('.') ? 'dot' : 'source',
            caller_function: currentFunction?.name || null
          });
        }
      }
      
      // Check for function calls (simplified - matches word followed by arguments)
      // This will have false positives but captures most calls
      if (currentFunction) {
        const callPattern = /\b([a-zA-Z_][a-zA-Z0-9_]*)\s+/g;
        let callMatch;
        while ((callMatch = callPattern.exec(line)) !== null) {
          const calleeName = callMatch[1];
          
          // Filter out common shell keywords
          const shellKeywords = [
            'if', 'then', 'else', 'elif', 'fi', 'case', 'esac', 'for', 'while', 
            'do', 'done', 'function', 'local', 'export', 'source', 'echo', 'printf',
            'cd', 'mkdir', 'rm', 'cp', 'mv', 'ln', 'chmod', 'chown', 'grep', 'sed',
            'awk', 'cut', 'sort', 'uniq', 'head', 'tail', 'cat', 'ls', 'find',
            'set', 'unset', 'return', 'exit', 'test', 'true', 'false'
          ];
          
          if (!shellKeywords.includes(calleeName)) {
            calls.push({
              callee: calleeName,
              line_number: lineNumber,
              caller_function: currentFunction.name
            });
          }
        }
      }
    }
    
    // Set end_line for functions that didn't close (end of file)
    for (const func of functions) {
      if (func.end_line === null) {
        func.end_line = lines.length;
      }
    }
    
    return {
      file_path: filePath,
      success: true,
      functions: functions,
      classes: [], // Shell has no classes
      imports: sources, // Treat source commands as imports
      calls: calls,
      // v8: J-Job specific fields
      is_jjob: isJJob,
      exec_scripts: execScripts,
      metadata: metadata,
      stats: {
        num_functions: functions.length,
        num_classes: 0,
        num_imports: sources.length,
        num_calls: calls.length,
        num_exec_scripts: execScripts.length
      }
    };
  }

  /**
   * Parse Fortran files (placeholder - to be implemented)
   * @param {string[]} files - Array of file paths (absolute)
   * @returns {Promise<Object[]>} - Parse results
   */
  async parseFortranFiles(files) {
    // TODO: Implement Fortran parser
    console.log('Fortran parsing not yet implemented');
    return [];
  }

  /**
   * Ingest parsed file structure into Neo4j
   * @param {Object} parseResult - Parser output for single file
   * @param {string} language - Language identifier
   * @param {boolean} verbose - Verbose logging
   */
  async ingestFileStructure(parseResult, language, verbose) {
    const { file_path, functions, classes, imports, calls, is_jjob, exec_scripts, metadata } = parseResult;
    const relativePath = path.relative(this.rootDir, file_path);
    
    if (verbose) {
      const jjobLabel = is_jjob ? ' [J-JOB]' : '';
      console.log(`  ✓ ${relativePath}${jjobLabel} (${functions?.length || 0} functions, ${exec_scripts?.length || 0} ex-scripts)`);
    }
    
    // Create or match File node
    const fileId = generateNodeId('File', file_path);
    await this.ensureFileNode(fileId, file_path, relativePath, language, { is_jjob, metadata });
    
    // v8: Track J-Job count
    if (is_jjob) {
      this.stats.jjobsProcessed++;
    }
    
    // Create Function nodes
    if (functions && functions.length > 0) {
      await this.createFunctionNodes(fileId, functions, language);
      this.stats.functionsCreated += functions.length;
      this.stats.definesCreated += functions.length;
    }
    
    // Create Class nodes
    if (classes && classes.length > 0) {
      await this.createClassNodes(fileId, classes, language);
      this.stats.classesCreated += classes.length;
      this.stats.definesCreated += classes.length;
    }
    
    // Create Import relationships (includes source commands for shell)
    if (imports && imports.length > 0) {
      await this.createImportRelationships(fileId, imports);
      this.stats.importsCreated += imports.length;
    }
    
    // Create Call relationships
    if (calls && calls.length > 0) {
      await this.createCallRelationships(fileId, calls, functions, classes);
      this.stats.callsCreated += calls.length;
    }
    
    // v8: Create ex-script execution relationships for J-Jobs
    if (is_jjob && exec_scripts && exec_scripts.length > 0) {
      await this.createExScriptRelationships(fileId, exec_scripts);
      this.stats.execScriptsLinked += exec_scripts.length;
    }
  }

  /**
   * Ensure File node exists in Neo4j
   * @param {string} fileId - Node ID
   * @param {string} absolutePath - Absolute file path
   * @param {string} relativePath - Path relative to rootDir
   * @param {string} language - Programming language
   * @param {Object} options - Additional options for J-Jobs
   */
  async ensureFileNode(fileId, absolutePath, relativePath, language, options = {}) {
    const { is_jjob = false, metadata = {} } = options;
    
    // v8: J-Jobs get additional labels and properties
    if (is_jjob) {
      const query = `
        MERGE (f:File:JJob {id: $fileId})
        SET f.path = $relativePath,
            f.absolutePath = $absolutePath,
            f.language = $language,
            f.isJJob = true,
            f.task = $task,
            f.configs = $configs,
            f.lastUpdated = datetime()
        RETURN f
      `;
      
      await this.client.runWriteQuery(query, {
        fileId,
        relativePath,
        absolutePath,
        language,
        task: metadata.task || null,
        configs: metadata.configs || []
      });
    } else {
      const query = `
        MERGE (f:File {id: $fileId})
        SET f.path = $relativePath,
            f.absolutePath = $absolutePath,
            f.language = $language,
            f.lastUpdated = datetime()
        RETURN f
      `;
      
      await this.client.runWriteQuery(query, {
        fileId,
        relativePath,
        absolutePath,
        language
      });
    }
  }

  /**
   * v8: Create EXECUTES relationships from J-Job to ex-scripts
   * @param {string} fileId - J-Job file node ID
   * @param {Object[]} execScripts - Array of ex-script executions
   */
  async createExScriptRelationships(fileId, execScripts) {
    const query = `
      MATCH (jjob:File {id: $fileId})
      UNWIND $execScripts AS exec
      MERGE (exScript:File {path: exec.script})
      ON CREATE SET exScript.id = 'file_' + exec.script,
                   exScript.language = 'shell',
                   exScript.lastUpdated = datetime()
      MERGE (jjob)-[r:EXECUTES]->(exScript)
      SET r.lineNumber = exec.line_number,
          r.callerFunction = exec.caller_function
    `;
    
    try {
      await this.client.runWriteQuery(query, {
        fileId,
        execScripts
      });
    } catch (error) {
      console.warn(`Warning: Could not create ex-script relationships: ${error.message}`);
    }
  }

  /**
   * Create Function nodes and DEFINES relationships
   * @param {string} fileId - Parent file node ID
   * @param {Object[]} functions - Function definitions
   * @param {string} language - Programming language
   */
  async createFunctionNodes(fileId, functions, language) {
    if (language === 'shell') {
      // Shell functions have simpler structure
      const query = `
        MATCH (f:File {id: $fileId})
        UNWIND $functions AS func
        CREATE (fn:Function {
          id: $fileId + '_func_' + func.name + '_' + toString(func.line_number),
          name: func.name,
          language: $language,
          lineNumber: func.line_number,
          endLine: func.end_line,
          type: func.type
        })
        CREATE (f)-[:DEFINES]->(fn)
      `;
      
      await this.client.runWriteQuery(query, {
        fileId,
        functions,
        language
      });
    } else {
      // Python functions with full metadata
      const query = `
        MATCH (f:File {id: $fileId})
        UNWIND $functions AS func
        CREATE (fn:Function {
          id: $fileId + '_func_' + func.name + '_' + toString(func.line_number),
          name: func.name,
          language: $language,
          lineNumber: func.line_number,
          endLine: func.end_line,
          parameters: func.parameters,
          isAsync: func.is_async,
          isMethod: func.is_method,
          className: func.class_name,
          decorators: func.decorators,
          docstring: func.docstring,
          returnType: func.return_type
        })
        CREATE (f)-[:DEFINES]->(fn)
      `;
      
      await this.client.runWriteQuery(query, {
        fileId,
        functions,
        language
      });
    }
  }

  /**
   * Create Class nodes and DEFINES relationships
   * @param {string} fileId - Parent file node ID
   * @param {Object[]} classes - Class definitions
   * @param {string} language - Programming language
   */
  async createClassNodes(fileId, classes, language) {
    const query = `
      MATCH (f:File {id: $fileId})
      UNWIND $classes AS cls
      CREATE (c:Class {
        id: $fileId + '_class_' + cls.name + '_' + toString(cls.line_number),
        name: cls.name,
        language: $language,
        lineNumber: cls.line_number,
        endLine: cls.end_line,
        baseClasses: cls.base_classes,
        decorators: cls.decorators,
        docstring: cls.docstring
      })
      CREATE (f)-[:DEFINES]->(c)
    `;
    
    await this.client.runWriteQuery(query, {
      fileId,
      classes,
      language
    });
  }

  /**
   * Create IMPORTS relationships
   * @param {string} fileId - Importing file node ID
   * @param {Object[]} imports - Import statements
   */
  async createImportRelationships(fileId, imports) {
    if (imports.length === 0) return;
    
    // Check if this is shell source commands or Python imports
    const isShellSource = imports[0].type === 'source' || imports[0].type === 'dot';
    
    if (isShellSource) {
      // Shell source commands - link to other files
      const query = `
        MATCH (f:File {id: $fileId})
        UNWIND $imports AS imp
        MERGE (target:File {path: imp.file})
        CREATE (f)-[:SOURCES {
          type: imp.type,
          lineNumber: imp.line_number,
          callerFunction: imp.caller_function
        }]->(target)
      `;
      
      await this.client.runWriteQuery(query, {
        fileId,
        imports
      });
    } else {
      // Python imports - link to modules
      const query = `
        MATCH (f:File {id: $fileId})
        UNWIND $imports AS imp
        MERGE (m:Module {name: imp.module})
        CREATE (f)-[:IMPORTS {
          type: imp.type,
          alias: imp.alias,
          itemName: imp.name,
          lineNumber: imp.line_number,
          level: imp.level
        }]->(m)
      `;
      
      await this.client.runWriteQuery(query, {
        fileId,
        imports
      });
    }
  }

  /**
   * Create CALLS relationships between functions
   * @param {string} fileId - File node ID
   * @param {Object[]} calls - Function call information
   * @param {Object[]} functions - Function definitions (for context)
   * @param {Object[]} classes - Class definitions (for context)
   */
  async createCallRelationships(fileId, calls, functions = [], classes = []) {
    // Build lookup for functions in this file
    const functionLookup = new Map();
    for (const func of functions) {
      const key = func.class_name 
        ? `${func.class_name}.${func.name}`
        : func.name;
      functionLookup.set(key, {
        id: `${fileId}_func_${func.name}_${func.line_number}`,
        name: func.name
      });
    }
    
    // Create calls with known caller context
    const validCalls = calls.filter(call => {
      if (call.caller_function) {
        const key = call.caller_class
          ? `${call.caller_class}.${call.caller_function}`
          : call.caller_function;
        return functionLookup.has(key);
      }
      return false;
    });
    
    if (validCalls.length === 0) return;
    
    const query = `
      UNWIND $calls AS call
      MATCH (caller:Function {id: call.caller_id})
      MERGE (callee:Function {name: call.callee})
      ON CREATE SET callee.isExternal = true
      CREATE (caller)-[:CALLS {
        lineNumber: call.line_number,
        numArgs: call.num_args,
        numKwargs: call.num_kwargs
      }]->(callee)
    `;
    
    const enrichedCalls = validCalls.map(call => {
      const key = call.caller_class
        ? `${call.caller_class}.${call.caller_function}`
        : call.caller_function;
      const caller = functionLookup.get(key);
      
      return {
        caller_id: caller.id,
        callee: call.callee,
        line_number: call.line_number,
        num_args: call.num_args,
        num_kwargs: call.num_kwargs
      };
    });
    
    await this.client.runWriteQuery(query, {
      calls: enrichedCalls
    });
  }

  /**
   * Clear all code structure data from Neo4j
   * Removes: Function, Class, File, Module nodes and their relationships
   * Preserves: Component nodes from Phase 0
   */
  async clearCodeStructureData() {
    console.log('Clearing existing code structure data...');
    
    const queries = [
      'MATCH (f:Function) DETACH DELETE f',
      'MATCH (c:Class) DETACH DELETE c',
      'MATCH (m:Module) DETACH DELETE m',
      'MATCH (f:File) DETACH DELETE f'
    ];
    
    for (const query of queries) {
      await this.client.runWriteQuery(query, {});
    }
    
    console.log('Code structure data cleared');
  }
}
