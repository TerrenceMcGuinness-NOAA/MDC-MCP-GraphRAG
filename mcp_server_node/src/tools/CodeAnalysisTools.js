#!/usr/bin/env node

/**
 * Code Analysis Tools Module
 * 
 * Provides code structure analysis and dependency tracing capabilities
 * using Neo4j graph database via the UnifiedDataAccess layer (Week 1).
 * 
 * These tools demonstrate the power of combining semantic search (ChromaDB)
 * with graph traversal (Neo4j) for intelligent code comprehension.
 * 
 * @version 2.0.0
 * @author Claude Sonnet 4.5
 * @supervisor Terry McGuinness
 * @date 2025-10-16
 */

import { UnifiedDataAccess } from '../data/UnifiedDataAccess.js';
import { GGSRTraversalPrototypes } from '../graphrag/GGSRTraversalPrototypes.js';
import { GraphGuidedRetrieval } from '../graphrag/GraphGuidedRetrieval.js';

export class CodeAnalysisTools {
  constructor(dataAccess = null) {
    this.dataAccess = dataAccess;  // Accept injected dependency for testing
    this.isInitialized = !!dataAccess;  // Already initialized if dataAccess provided
    this.ggsr = null;      // Phase 28A: GGSR traversal prototypes
    this.retrieval = null;  // Phase 24D: GraphGuidedRetrieval fusion engine
  }

  /**
   * Initialize data access layer
   */
  async initialize() {
    if (this.isInitialized) return;

    console.error('[INIT] Initializing Code Analysis Tools...');
    
    this.dataAccess = new UnifiedDataAccess();
    await this.dataAccess.connect();
    
    // Phase 28A: Initialize GGSR traversal prototypes
    if (this.dataAccess.graphDB) {
      this.ggsr = new GGSRTraversalPrototypes(this.dataAccess.graphDB);
      // Phase 24D+24E: Initialize GraphGuidedRetrieval fusion engine
      this.retrieval = new GraphGuidedRetrieval({
        dataAccess: this.dataAccess,
        ggsr: this.ggsr,
        vectorDB: this.dataAccess.vectorDB || null
      });
    }
    
    this.isInitialized = true;
    console.error('[OK] Code Analysis Tools initialized');
  }

  /**
   * Register code analysis tools with server
   */
  registerWith(server) {
    // Tool 1: Analyze Code Structure
    server.registerTool(
      'analyze_code_structure',
      'Analyze code structure, relationships, and dependencies for a specific file',
      {
        type: 'object',
        properties: {
          file_path: {
            type: 'string',
            description: 'Path to the file to analyze (e.g., "scripts/exglobal_forecast.py")'
          },
          include_dependencies: {
            type: 'boolean',
            description: 'Include dependency analysis',
            default: true
          },
          depth: {
            type: 'number',
            description: 'Depth of dependency tree to explore (1-3)',
            default: 2,
            minimum: 1,
            maximum: 3
          },
          token_budget: {
            type: 'number',
            description: 'Max tokens for GGSR weighted context (Phase 24C). Lower = more precise, higher = more coverage.',
            default: 4000
          }
        },
        required: ['file_path']
      },
      this.analyzeCodeStructure.bind(this)
    );

    // Tool 2: Find Dependencies
    server.registerTool(
      'find_dependencies',
      'Find all dependencies (imports) and dependents (importers) for a file or module',
      {
        type: 'object',
        properties: {
          target: {
            type: 'string',
            description: 'File path or module name to analyze'
          },
          direction: {
            type: 'string',
            enum: ['upstream', 'downstream', 'both'],
            description: 'upstream=what it imports, downstream=what imports it, both=complete graph',
            default: 'both'
          },
          max_depth: {
            type: 'number',
            description: 'Maximum traversal depth',
            default: 3,
            minimum: 1,
            maximum: 5
          },
          token_budget: {
            type: 'number',
            description: 'Max tokens for GGSR weighted context (Phase 24C)',
            default: 4000
          }
        },
        required: ['target']
      },
      this.findDependencies.bind(this)
    );

    // Tool 3: Trace Execution Path
    server.registerTool(
      'trace_execution_path',
      'Trace the execution path from a starting function through call chains',
      {
        type: 'object',
        properties: {
          function_name: {
            type: 'string',
            description: 'Name of the function to trace from'
          },
          file_path: {
            type: 'string',
            description: 'Optional: File path to narrow search (faster)'
          },
          max_depth: {
            type: 'number',
            description: 'Maximum call chain depth to trace',
            default: 3,
            minimum: 1,
            maximum: 5
          },
          include_callers: {
            type: 'boolean',
            description: 'Include functions that call this function',
            default: false
          },
          include_weights: {
            type: 'boolean',
            description: 'Include GGSR relationship weights and hop decay scores (Phase 28B)',
            default: true
          },
          token_budget: {
            type: 'number',
            description: 'Max tokens for GGSR weighted context (Phase 24C)',
            default: 4000
          }
        },
        required: ['function_name']
      },
      this.traceExecutionPath.bind(this)
    );

    // Tool 4: Find Callers and Callees
    server.registerTool(
      'find_callers_callees',
      'Find all functions that call a target function (callers) and functions it calls (callees)',
      {
        type: 'object',
        properties: {
          function_name: {
            type: 'string',
            description: 'Name of the function to analyze'
          },
          file_path: {
            type: 'string',
            description: 'Optional: File path containing the function'
          },
          include_source: {
            type: 'boolean',
            description: 'Include source code snippets',
            default: false
          },
          token_budget: {
            type: 'number',
            description: 'Max tokens for GGSR weighted context (Phase 24C)',
            default: 4000
          },
          cross_language: {
            type: 'boolean',
            description: 'When true, follow EXECUTES/INVOKES edges across language boundaries (Shell↔Fortran, Shell↔Python). Default: false for backward compatibility.',
            default: false
          }
        },
        required: ['function_name']
      },
      this.findCallersCallees.bind(this)
    );

    // Tool 6: Trace Full Execution Chain (Phase 24F Step 5)
    server.registerTool(
      'trace_full_execution_chain',
      'Trace complete execution chain across Shell, Python, and Fortran language boundaries. Starting from any node (J-Job, script, Fortran program, Python task), follows SOURCES, INVOKES, EXECUTES, CALLS, USES, and DEFINES edges to build the full execution tree.',
      {
        type: 'object',
        properties: {
          start: {
            type: 'string',
            description: 'Starting point: J-Job name (JGLOBAL_FORECAST), script name (exglobal_forecast.sh), Fortran program (gsi), or Python module (pygfs.task.gfs_forecast)'
          },
          direction: {
            type: 'string',
            enum: ['forward', 'reverse', 'both'],
            description: 'forward: trace what this node executes. reverse: trace what triggers this node. both: full bidirectional context. Default: forward',
            default: 'forward'
          },
          max_depth: {
            type: 'number',
            description: 'Maximum hops per language segment (default: 5)',
            default: 5,
            minimum: 1,
            maximum: 10
          },
          languages: {
            type: 'array',
            items: { type: 'string', enum: ['shell', 'fortran', 'python'] },
            description: 'Limit to specific languages. Default: all'
          }
        },
        required: ['start']
      },
      this.traceFullExecutionChain.bind(this)
    );

    // Tool 5: Find Environment Variable Dependencies
    server.registerTool(
      'find_env_dependencies',
      'Find all scripts that depend on or export a specific environment variable (uses Neo4j graph)',
      {
        type: 'object',
        properties: {
          variable_name: {
            type: 'string',
            description: 'Name of the environment variable (e.g., HOMEgfs, DATAROOT, RUN)'
          },
          show_exports: {
            type: 'boolean',
            description: 'Include scripts that export this variable',
            default: true
          },
          limit: {
            type: 'number',
            description: 'Maximum number of results to return',
            default: 50
          },
          token_budget: {
            type: 'number',
            description: 'Max tokens for GGSR weighted context (Phase 24C)',
            default: 4000
          }
        },
        required: ['variable_name']
      },
      this.findEnvDependencies.bind(this)
    );

    console.error('[OK] Registered 5 Code Analysis tools');
  }

  /**
   * Tool Implementation: Analyze Code Structure
   */
  async analyzeCodeStructure(args) {
    await this.ensureInitialized();

    const { file_path, include_dependencies = true, depth = 2, token_budget = 4000 } = args;

    try {
      // Phase 53 D4: three-tier path resolver.
      // Other tools find the same node by basename; analyze_code_structure
      // used exact-match on :File.path and returned "File not found" for
      // partial paths (e.g., scripts/exglobal_forecast.sh vs the absolute
      // supported_repos/...).
      let resolvedPath = file_path;
      let fileInfo = await this.dataAccess.graphDB.findFileFunctions(file_path);

      if (!fileInfo || fileInfo.length === 0) {
        try {
          // Tier 2 + 3: ENDS WITH suffix or basename match, ranked by shortest path.
          const basename = file_path.split('/').pop();
          const candidates = await this.dataAccess.graphDB.query(
            `MATCH (f:File)
             WHERE f.path = $exact
                OR f.path ENDS WITH $suffix
                OR f.path ENDS WITH $basenameSuffix
             RETURN f.path AS path
             ORDER BY size(f.path) ASC
             LIMIT 5`,
            {
              exact: file_path,
              suffix: file_path.startsWith('/') ? file_path : '/' + file_path,
              basenameSuffix: '/' + basename
            }
          );
          if (candidates && candidates.length > 0) {
            resolvedPath = candidates[0].path;
            fileInfo = await this.dataAccess.graphDB.findFileFunctions(resolvedPath);
          }
        } catch (_) {
          // Resolver is best-effort; fall through to the original "not found" path.
        }
      }

      if (!fileInfo || fileInfo.length === 0) {
        return {
          content: [{
            type: 'text',
            text: `File not found: ${file_path}\n\nTip: Use semantic search to find similar files:\n\`\`\`\nsearch_documentation query:"${file_path.split('/').pop()}"\n\`\`\``
          }]
        };
      }

      // Build analysis result
      let analysis = `# Code Structure Analysis: ${resolvedPath}\n\n`;
      if (resolvedPath !== file_path) {
        analysis += `*Resolved \`${file_path}\` → \`${resolvedPath}\`*\n\n`;
      }
      
      // File overview
      const functions = fileInfo.filter(item => item.type === 'FUNCTION');
      const classes = fileInfo.filter(item => item.type === 'CLASS');
      
      analysis += `## Overview\n`;
      analysis += `- **Functions:** ${functions.length}\n`;
      analysis += `- **Classes:** ${classes.length}\n`;
      analysis += `- **Total Symbols:** ${fileInfo.length}\n\n`;

      // Functions detail
      if (functions.length > 0) {
        analysis += `## Functions\n\n`;
        for (const func of functions.slice(0, 10)) {
          analysis += `### \`${func.name}\`\n`;
          if (func.docstring) {
            analysis += `${func.docstring.split('\n')[0]}\n`;
          }
          if (func.lineNumber) {
            analysis += `*Line ${func.lineNumber}*\n`;
          }
          analysis += `\n`;
        }
        if (functions.length > 10) {
          analysis += `*... and ${functions.length - 10} more functions*\n\n`;
        }
      }

      // Classes detail
      if (classes.length > 0) {
        analysis += `## Classes\n\n`;
        for (const cls of classes.slice(0, 5)) {
          analysis += `### \`${cls.name}\`\n`;
          if (cls.docstring) {
            analysis += `${cls.docstring.split('\n')[0]}\n`;
          }
          analysis += `\n`;
        }
        if (classes.length > 5) {
          analysis += `*... and ${classes.length - 5} more classes*\n\n`;
        }
      }

      // Dependency analysis
      if (include_dependencies) {
        const imports = await this.dataAccess.graphDB.findFileImports(file_path);
        const importers = await this.dataAccess.graphDB.findImporters(file_path);

        analysis += `## Dependencies\n\n`;
        analysis += `### Imports (${imports.length})\n`;
        if (imports.length > 0) {
          for (const imp of imports.slice(0, 10)) {
            // Fix [object Object] by properly extracting string values
            const importName = typeof imp === 'string' ? imp : 
                              (imp.target || imp.moduleName || imp.name || JSON.stringify(imp));
            analysis += `- \`${importName}\`\n`;
          }
          if (imports.length > 10) {
            analysis += `- *... and ${imports.length - 10} more imports*\n`;
          }
        } else {
          analysis += `*No imports found*\n`;
        }

        analysis += `\n### Imported By (${importers.length})\n`;
        if (importers.length > 0) {
          for (const imp of importers.slice(0, 10)) {
            // Fix [object Object] by properly extracting string values
            const importerName = typeof imp === 'string' ? imp : 
                                (imp.source || imp.filePath || imp.name || JSON.stringify(imp));
            analysis += `- \`${importerName}\`\n`;
          }
          if (importers.length > 10) {
            analysis += `- *... and ${importers.length - 10} more importers*\n`;
          }
        } else {
          analysis += `*Not imported by other files*\n`;
        }
      }

      // Suggest related queries
      analysis += `\n## Related Queries\n\n`;
      analysis += `- \`find_dependencies\` - Full dependency graph\n`;
      analysis += `- \`trace_execution_path\` - Trace function call chains\n`;
      if (functions.length > 0) {
        analysis += `- \`find_callers_callees function_name:"${functions[0].name}"\` - Analyze function relationships\n`;
      }

      // Phase 24D: Unified GGSR + semantic retrieval
      if (this.retrieval) {
        const entityName = file_path.split('/').pop();
        const semanticKeys = functions.slice(0, 5).map(f => f.name).filter(Boolean);
        const ctx = await this.retrieval.retrieve(entityName, semanticKeys, {
          tokenBudget: token_budget, maxResults: 15, hops: 1,
          semanticLabel: 'key functions'
        });
        analysis += ctx.ggsrSection + ctx.semanticSection + (ctx.communitySection || "");
      }

      return {
        content: [{
          type: 'text',
          text: analysis
        }]
      };

    } catch (error) {
      console.error('Error analyzing code structure:', error);
      return {
        content: [{
          type: 'text',
          text: `Error analyzing code structure: ${error.message}\n\nGraph database may not be fully populated. Run ingestion scripts to populate Neo4j.`
        }],
        isError: true
      };
    }
  }

  /**
   * Tool Implementation: Find Dependencies
   */
  async findDependencies(args) {
    await this.ensureInitialized();

    // Phase 29: accept file_path as alias for target
    const effectiveArgs = { ...args, target: args.target || args.file_path };
    const { target, direction = 'both', max_depth = 3, token_budget = 4000 } = effectiveArgs;

    try {
      let result = `# Dependency Analysis: ${target}\n\n`;

      if (direction === 'upstream' || direction === 'both') {
        result += `## Upstream Dependencies (What ${target} imports)\n\n`;
        const imports = await this.dataAccess.graphDB.findFileImports(target);
        
        if (imports.length > 0) {
          result += `Found ${imports.length} direct imports:\n\n`;
          for (const imp of imports) {
            // Phase 53 D1: GraphDatabase.findFileImports returns
            // { moduleName, importType, importedItem, alias, lineNumber }.
            // Old code used imp.target (always undefined) → fell through to
            // the object itself → rendered as "[object Object]".
            const label = typeof imp === 'string'
              ? imp
              : (imp.moduleName ?? imp.target ?? imp.name ?? imp.path ?? JSON.stringify(imp));
            result += `- \`${label}\`\n`;
          }
        } else {
          result += `*No imports found*\n`;
        }
        result += `\n`;
      }

      if (direction === 'downstream' || direction === 'both') {
        result += `## Downstream Dependencies (What imports ${target})\n\n`;
        const importers = await this.dataAccess.graphDB.findImporters(target);
        
        if (importers.length > 0) {
          result += `Found ${importers.length} files that import this:\n\n`;
          for (const imp of importers) {
            // Phase 53 D1: GraphDatabase.findImporters returns
            // { file, importType, importedItem, lineNumber }.
            // Old code used imp.source (always undefined) → fell through to
            // the object itself → rendered as "[object Object]".
            const label = typeof imp === 'string'
              ? imp
              : (imp.file ?? imp.source ?? imp.path ?? imp.name ?? JSON.stringify(imp));
            result += `- \`${label}\`\n`;
          }
        } else {
          result += `*No importers found*\n`;
        }
      }

      // Check for circular dependencies if max_depth > 1
      if (max_depth > 1) {
        result += `\n## Circular Dependency Check\n\n`;
        const circular = await this.dataAccess.graphDB.findCircularDependencies();
        
        if (circular.length > 0) {
          const relevant = circular.filter(cycle => 
            cycle.path && cycle.path.includes(target)
          );
          
          if (relevant.length > 0) {
            result += `[WARN]  **Warning:** Found ${relevant.length} circular dependency chains involving this file:\n\n`;
            for (const cycle of relevant.slice(0, 5)) {
              result += `- ${cycle.path.join(' → ')}\n`;
            }
          } else {
            result += `[OK] No circular dependencies detected for this file\n`;
          }
        } else {
          result += `[OK] No circular dependencies in entire codebase\n`;
        }
      }

      // Phase 24D: Unified GGSR + semantic retrieval (2-hop for dependencies)
      if (this.retrieval) {
        const ctx = await this.retrieval.retrieveDependency(target, [target], {
          tokenBudget: token_budget
        });
        result += ctx.ggsrSection + ctx.semanticSection + (ctx.communitySection || "");
      }

      return {
        content: [{
          type: 'text',
          text: result
        }]
      };

    } catch (error) {
      console.error('Error finding dependencies:', error);
      return {
        content: [{
          type: 'text',
          text: `Error finding dependencies: ${error.message}`
        }],
        isError: true
      };
    }
  }

  /**
   * Tool Implementation: Trace Execution Path
   */
  async traceExecutionPath(args) {
    await this.ensureInitialized();

    const { function_name, file_path, max_depth = 3, include_callers = false, include_weights = true, token_budget = 4000 } = args;

    try {
      let graphType = 'function'; // 'function', 'fortran', 'shell', 'python', or 'cross-language'
      
      // Find the entity - try Python function first (Phase 24I)
      let functions = file_path
        ? await this.dataAccess.graphDB.findFileFunctions(file_path)
        : await this.dataAccess.graphDB.query(
            'MATCH (f) WHERE (f:Function OR f:PythonFunction) AND f.name = $name RETURN f LIMIT 5',
            { name: function_name }
          );
      
      // Check if result is from Python graph
      if (functions && functions.length > 0 && !file_path) {
        const pyCheck = await this.dataAccess.graphDB.query(
          'MATCH (f:PythonFunction {name: $name}) RETURN f LIMIT 1',
          { name: function_name }
        );
        if (pyCheck && pyCheck.length > 0) {
          graphType = 'python';
        }
      }

      // Check if result is from Fortran graph (may have both Function and Fortran labels)
      if (functions && functions.length > 0 && graphType === 'function' && !file_path) {
        const fortranCheck = await this.dataAccess.graphDB.query(
          `MATCH (f) WHERE (f:FortranSubroutine OR f:FortranFunction OR f:FortranModule OR f:FortranProgram)
           AND f.name = $name RETURN f LIMIT 1`,
          { name: function_name }
        );
        if (fortranCheck && fortranCheck.length > 0) {
          graphType = 'fortran';
        }
      }
      
      // If no function found, try Fortran (Phase 10 M5)
      if (!functions || functions.length === 0) {
        const fortranEntity = await this.dataAccess.graphDB.query(
          `MATCH (f) WHERE (f:FortranSubroutine OR f:FortranFunction OR f:FortranModule OR f:FortranProgram)
           AND toLower(f.name) CONTAINS toLower($name)
           RETURN f, labels(f)[0] as entityType LIMIT 5`,
          { name: function_name }
        );
        if (fortranEntity && fortranEntity.length > 0) {
          graphType = 'fortran';
          functions = fortranEntity;
        }
      }
      
      // If still nothing, try shell script
      if (!functions || functions.length === 0) {
        const shellScript = await this.dataAccess.graphDB.query(
          `MATCH (s:CodeFile) WHERE s.language = 'shell' AND toLower(s.name) CONTAINS toLower($name)
           RETURN s LIMIT 5`,
          { name: function_name }
        );
        if (shellScript && shellScript.length > 0) {
          graphType = 'shell';
          functions = shellScript;
        }
      }

      if (!functions || functions.length === 0) {
        return {
          content: [{
            type: 'text',
            text: `Entity "${function_name}" not found in function, Python, Fortran, or shell script graphs.\n\nTry using \`analyze_code_structure\` first to find available entities.`
          }]
        };
      }
      
      // Set up labels based on graph type
      const typeLabels = {
        function: { entity: 'Function', calls: 'function calls' },
        python: { entity: 'Python Function', calls: 'Python calls' },
        fortran: { entity: 'Fortran', calls: 'Fortran calls' },
        shell: { entity: 'Shell Script', calls: 'script invocations' }
      };
      const labels = typeLabels[graphType] || typeLabels.function;
      
      let result = `# Execution Path Trace: ${function_name}\n\n`;
      result += `*Entity type: ${labels.entity}*\n\n`;

      // Trace call chain based on graph type
      result += `## Call Chain (What ${function_name} calls)\n\n`;
      
      let callChain;
      if (graphType === 'python') {
        callChain = await this.dataAccess.graphDB.tracePythonCallChain(function_name, max_depth);
      } else if (graphType === 'fortran') {
        callChain = await this.dataAccess.graphDB.traceFortranCallChain(function_name, max_depth);
      } else if (graphType === 'shell') {
        callChain = await this.dataAccess.graphDB.traceScriptChain(function_name, max_depth);
        
        // Phase 24F Step 4: Integrated cross-language output using traceCrossLanguageChain
        try {
          const xLang = await this.dataAccess.graphDB.traceCrossLanguageChain(function_name, max_depth, 'forward');
          if (xLang.bridges.length > 0) {
            result += `### Integrated Execution Path\n\n`;
            let hopNum = 0;
            for (const entry of xLang.chain) {
              if (entry.direction !== 'forward') continue;
              hopNum++;
              const tag = entry.language === 'shell' ? 'Shell' :
                          entry.relType === 'EXECUTES' ? 'Bridge' :
                          entry.language === 'fortran' ? 'Fortran' :
                          entry.language === 'python' ? 'Python' : entry.language;
              const relInfo = entry.relType === 'EXECUTES' ? ' ═══ EXECUTES ═══>' :
                              entry.relType ? ` (${entry.relType})` : '';
              result += `${hopNum}. [${tag}] ${entry.hop === 0 ? '' : '→ '}\`${entry.name}\`${relInfo}${entry.label && entry.label !== 'ShellScript' ? ` [${entry.label}]` : ''}\n`;
            }
            result += `\n*Languages: ${xLang.stats.languages.join(', ')} | Bridges: ${xLang.stats.bridgeCrossings} | Nodes: ${xLang.stats.totalNodes}*\n\n`;
          }
        } catch (xLangErr) {
          console.error('[WARN] Cross-language integrated trace failed:', xLangErr.message);
        }
      } else {
        callChain = await this.dataAccess.graphDB.traceCallChain(function_name, max_depth);
      }

      if (callChain && callChain.length > 0) {
        result += `Traced ${callChain.length} ${labels.calls}:\n\n`;
        for (const call of callChain.slice(0, 20)) {
          const indent = '  '.repeat((call.depth || 1) - 1);
          const name = call.callee || call.name;
          const type = call.calleeType || call.type;
          result += `${indent}${call.depth || 1}. \`${name}\``;
          if (type && graphType === 'fortran') result += ` [${type}]`;
          if (call.file) result += ` (in ${call.file})`;
          result += `\n`;
        }
        if (callChain.length > 20) {
          result += `\n*... and ${callChain.length - 20} more calls*\n`;
        }
      } else {
        result += `*No ${labels.calls} found or this is a leaf node*\n`;
      }
      
      // Add Fortran module dependencies if applicable
      if (graphType === 'fortran') {
        const moduleUses = await this.dataAccess.graphDB.findFortranModuleUses(function_name);
        if (moduleUses && moduleUses.length > 0) {
          result += `\n## Module Dependencies (USES)\n\n`;
          for (const mod of moduleUses.slice(0, 10)) {
            result += `- \`${mod.moduleName}\``;
            if (mod.moduleFile) result += ` in \`${mod.moduleFile}\``;
            result += `\n`;
          }
          if (moduleUses.length > 10) {
            result += `*... and ${moduleUses.length - 10} more modules*\n`;
          }
        }
      }

      // Optionally include callers
      if (include_callers) {
        result += `\n## Callers (What calls ${function_name})\n\n`;
        
        let callers;
        if (graphType === 'python') {
          callers = await this.dataAccess.graphDB.findPythonCallers(function_name);
        } else if (graphType === 'fortran') {
          callers = await this.dataAccess.graphDB.findFortranCallers(function_name);
        } else if (graphType === 'shell') {
          callers = await this.dataAccess.graphDB.findScriptCallers(function_name);
        } else {
          callers = await this.dataAccess.graphDB.findCallers(function_name);
        }

        if (callers && callers.length > 0) {
          result += `Found ${callers.length} callers:\n\n`;
          for (const caller of callers.slice(0, 10)) {
            const name = caller.name || caller.callerName || caller;
            const type = caller.callerType || caller.type;
            result += `- \`${name}\``;
            if (type && graphType === 'fortran') result += ` [${type}]`;
            if (caller.file || caller.callerFile) result += ` (in ${caller.file || caller.callerFile})`;
            result += `\n`;
          }
          if (callers.length > 10) {
            result += `*... and ${callers.length - 10} more callers*\n`;
          }
        } else {
          result += `*No callers found - this may be an entry point*\n`;
        }
      }

      // Phase 28B: Weighted traversal for GGSR (all entity types)
      if (include_weights && this.ggsr) {
        try {
          if (graphType === 'fortran') {
            const weighted = await this.ggsr.fortranWeightedTraversal(function_name, max_depth);
            result += `\n## GGSR Weighted Traversal\n`;
            result += `*Latency: ${weighted.latencyMs}ms (target <100ms: ${weighted.meetsTarget ? 'PASS' : 'MISS'})*\n\n`;
            
            if (weighted.combined.length > 0) {
              result += `| Target | Type | Rel | Weight | Score | Depth |\n`;
              result += `|--------|------|-----|--------|-------|-------|\n`;
              for (const entry of weighted.combined.slice(0, 20)) {
                result += `| \`${entry.target}\` | ${entry.targetType} | ${entry.relType} | ${entry.weight} | ${entry.score.toFixed(3)} | ${entry.depth} |\n`;
              }
              if (weighted.combined.length > 20) {
                result += `\n*... and ${weighted.combined.length - 20} more weighted results*\n`;
              }
              result += `\n**CALLS:** ${weighted.callCount} | **USES:** ${weighted.usesCount}\n`;
            }
          } else if (this.retrieval) {
            // Phase 24D: Non-Fortran uses unified retrieval (1-hop)
            const semanticKeys = callChain ? callChain.slice(0, 5).map(c => c.callee || c.name).filter(Boolean) : [];
            const ctx = await this.retrieval.retrieve(function_name, semanticKeys, {
              tokenBudget: token_budget, maxResults: 15, hops: 1,
              semanticLabel: 'key entities'
            });
            result += ctx.ggsrSection + ctx.semanticSection + (ctx.communitySection || "");
          }
        } catch (ggsrError) {
          console.error('[WARN] GGSR weighted traversal failed:', ggsrError.message);
        }
      }

      // Fortran path: semantic enrichment only (GGSR handled by fortranWeightedTraversal above)
      if (include_weights && graphType === 'fortran' && this.retrieval) {
        const semanticKeys = callChain ? callChain.slice(0, 5).map(c => c.callee || c.name).filter(Boolean) : [];
        if (semanticKeys.length > 0) {
          const ctx = await this.retrieval.retrieve(null, semanticKeys, {
            tokenBudget: token_budget, semanticLabel: 'key entities'
          });
          result += ctx.semanticSection + (ctx.communitySection || '');
        }
      }

      // Phase 24F-3: Cross-language trace (Shell→Fortran, Shell→Python bridges)
      if (this.ggsr) {
        try {
          const xLang = await this.ggsr.crossLanguageTrace(function_name, { maxDepth: max_depth });
          if (xLang.traceCount > 0) {
            result += `\n## Cross-Language Traces\n`;
            result += `*${xLang.fortranTraces} Fortran | ${xLang.pythonTraces} Python | ${xLang.latencyMs}ms*\n\n`;
            for (const t of xLang.traces) {
              if (t.type === 'shell-to-fortran') {
                result += `### Shell → Fortran: \`${t.shell}\` → \`${t.target}\`\n`;
                if (t.chain.length > 0) {
                  result += `CALLS chain: ${t.chain.slice(0, 10).map(c => `\`${c}\``).join(' → ')}`;
                  if (t.chain.length > 10) result += ` ... (+${t.chain.length - 10} more)`;
                  result += `\n`;
                }
              } else if (t.type === 'shell-to-python') {
                result += `### Shell → Python: \`${t.shell}\` → \`${t.target}\`\n`;
                if (t.functions.length > 0) {
                  result += `Functions: ${t.functions.slice(0, 10).map(f => `\`${f}()\``).join(', ')}\n`;
                }
              }
              result += `\n`;
            }
          }
        } catch (xLangError) {
          console.error('[WARN] Cross-language trace failed:', xLangError.message);
        }
      }

      return {
        content: [{
          type: 'text',
          text: result
        }]
      };

    } catch (error) {
      console.error('Error tracing execution path:', error);
      return {
        content: [{
          type: 'text',
          text: `Error tracing execution path: ${error.message}`
        }],
        isError: true
      };
    }
  }

  /**
   * Tool Implementation: Find Callers and Callees
   */
  async findCallersCallees(args) {
    await this.ensureInitialized();

    const { function_name, file_path, include_source = false, token_budget = 4000, cross_language = false } = args;

    try {
      // First try unified function graph (includes both Function and PythonFunction via Phase 24I)
      let callers = await this.dataAccess.graphDB.findCallers(function_name);
      let callChain = await this.dataAccess.graphDB.traceCallChain(function_name, 1);
      
      // Track which graph type we're using
      let graphType = 'function';
      
      // Detect if results came from Python graph
      if (callers.length > 0 || (callChain && callChain.length > 0)) {
        const pyCheck = await this.dataAccess.graphDB.query(
          'MATCH (f:PythonFunction {name: $name}) RETURN f LIMIT 1',
          { name: function_name }
        );
        if (pyCheck && pyCheck.length > 0) {
          graphType = 'python';
        } else {
          // Check if it's a Fortran entity (may share generic CALLS edges)
          const fortranCheck = await this.dataAccess.graphDB.query(
            `MATCH (f) WHERE (f:FortranSubroutine OR f:FortranFunction OR f:FortranModule OR f:FortranProgram)
             AND f.name = $name RETURN f LIMIT 1`,
            { name: function_name }
          );
          if (fortranCheck && fortranCheck.length > 0) {
            graphType = 'fortran';
          }
        }
      }
      
      // If no function results, try Fortran graph (Phase 10 M5)
      if (callers.length === 0 && (!callChain || callChain.length === 0)) {
        const fortranCallers = await this.dataAccess.graphDB.findFortranCallers(function_name);
        const fortranChain = await this.dataAccess.graphDB.traceFortranCallChain(function_name, 2);
        
        if (fortranCallers.length > 0 || (fortranChain && fortranChain.length > 0)) {
          graphType = 'fortran';
          callers = fortranCallers;
          callChain = fortranChain;
        }
      }
      
      // If still no results, try shell script graph
      if (callers.length === 0 && (!callChain || callChain.length === 0)) {
        const scriptCallers = await this.dataAccess.graphDB.findScriptCallers(function_name);
        const scriptChain = await this.dataAccess.graphDB.traceScriptChain(function_name, 2);
        
        if (scriptCallers.length > 0 || (scriptChain && scriptChain.length > 0)) {
          graphType = 'shell';
          callers = scriptCallers;
          callChain = scriptChain;
        }
      }
      
      // Set entity type label based on graph type
      const entityLabels = {
        function: { name: 'Function', caller: 'Functions that call', callee: 'Functions called by' },
        python: { name: 'Python Function', caller: 'Python functions that call', callee: 'Python functions called by' },
        fortran: { name: 'Fortran Subroutine/Function', caller: 'Fortran code that calls', callee: 'Fortran code called by' },
        shell: { name: 'Shell Script', caller: 'Scripts that source/invoke', callee: 'Scripts sourced/invoked by' }
      };
      const labels = entityLabels[graphType];
      
      let result = `# ${labels.name} Analysis: ${function_name}\n\n`;
      
      if (graphType === 'fortran') {
        result += `*Showing Fortran call graph (CALLS/USES relationships)*\n\n`;
        
        // Add module usage for Fortran
        const moduleUses = await this.dataAccess.graphDB.findFortranModuleUses(function_name);
        if (moduleUses && moduleUses.length > 0) {
          result += `## Module Dependencies (${moduleUses.length})\n`;
          result += `*Modules used by ${function_name}*\n\n`;
          for (const mod of moduleUses.slice(0, 10)) {
            result += `- **\`${mod.moduleName}\`**`;
            if (mod.moduleFile) result += ` in \`${mod.moduleFile}\``;
            result += `\n`;
          }
          if (moduleUses.length > 10) {
            result += `*... and ${moduleUses.length - 10} more modules*\n`;
          }
          result += `\n`;
        }
      } else if (graphType === 'shell') {
        result += `*Showing shell script call tree (J-Jobs, ex-scripts, ush)*\n\n`;
      }

      // Find callers (upstream)
      result += `## Callers (${callers.length})\n`;
      result += `*${labels.caller} ${function_name}*\n\n`;

      if (callers.length > 0) {
        for (const caller of callers.slice(0, 15)) {
          const name = caller.caller || caller.name || caller.callerName || (typeof caller === 'string' ? caller : JSON.stringify(caller));
          const file = caller.file || caller.callerFile;
          const type = caller.callerType || caller.type;
          result += `- **\`${name}\`**`;
          if (type && graphType === 'fortran') result += ` [${type}]`;
          if (file) result += ` in \`${file}\``;
          if (caller.relationship) result += ` [${caller.relationship}]`;
          if (caller.lineNumber) result += ` (line ${caller.lineNumber})`;
          result += `\n`;
        }
        if (callers.length > 15) {
          result += `\n*... and ${callers.length - 15} more callers*\n`;
        }
      } else {
        result += `*No callers found - this may be an entry point*\n`;
      }

      // Find callees (downstream)
      result += `\n## Callees\n`;
      result += `*${labels.callee} ${function_name}*\n\n`;
      
      if (callChain && callChain.length > 0) {
        for (const call of callChain.slice(0, 15)) {
          const name = call.callee || call.name;
          const type = call.calleeType || call.type;
          result += `- **\`${name}\`**`;
          if (type && graphType === 'fortran') result += ` [${type}]`;
          if (call.file) result += ` in \`${call.file}\``;
          if (call.depth) result += ` (depth: ${call.depth})`;
          result += `\n`;
        }
        if (callChain.length > 15) {
          result += `\n*... and ${callChain.length - 15} more callees*\n`;
        }
      } else {
        result += `*No callees found - this is a leaf ${labels.name.toLowerCase()}*\n`;
      }
      
      // Environment dependencies for shell scripts
      if (graphType === 'shell') {
        try {
          const envDeps = await this.dataAccess.graphDB.findScriptEnvDeps(function_name);
          if (envDeps && envDeps.length > 0) {
            result += `\n## Environment Variables\n`;
            result += `*Variables this script exports or depends on*\n\n`;
            
            const exports = envDeps.filter(e => e.relationship === 'EXPORTS');
            const depends = envDeps.filter(e => e.relationship === 'DEPENDS_ON_ENV');
            
            if (exports.length > 0) {
              result += `**Exports:** `;
              result += exports.slice(0, 10).map(e => `\`${e.envVar}\``).join(', ');
              if (exports.length > 10) result += ` (+${exports.length - 10} more)`;
              result += `\n`;
            }
            if (depends.length > 0) {
              result += `**Depends on:** `;
              result += depends.slice(0, 10).map(e => `\`${e.envVar}\``).join(', ');
              if (depends.length > 10) result += ` (+${depends.length - 10} more)`;
              result += `\n`;
            }
          }
        } catch (envError) {
          // Ignore env lookup errors
        }
      }

      // Phase 24F: Cross-language traversal when cross_language=true
      if (cross_language) {
        try {
          const direction = (graphType === 'fortran') ? 'reverse' : 'forward';
          const xLang = await this.dataAccess.graphDB.traceCrossLanguageChain(function_name, 5, direction);
          if (xLang.chain.length > 0) {
            result += `\n## Cross-Language Callees\n\n`;
            const shellNodes = xLang.chain.filter(n => n.language === 'shell' && n.hop > 0);
            const fortranNodes = xLang.chain.filter(n => n.language === 'fortran');
            const pythonNodes = xLang.chain.filter(n => n.language === 'python');

            if (shellNodes.length > 0) {
              result += `### Shell Layer\n`;
              for (const node of shellNodes.slice(0, 10)) {
                result += `- ${function_name} → \`${node.name}\` (${node.relType || 'SOURCES/INVOKES'})\n`;
              }
              result += `\n`;
            }
            if (xLang.bridges.length > 0) {
              result += `### Language Bridge (${xLang.bridges[0].fromLang} → ${xLang.bridges[0].toLang})\n`;
              for (const bridge of xLang.bridges.slice(0, 10)) {
                result += `- \`${bridge.from}\` ═══${bridge.type}═══> \`${bridge.to}\`\n`;
              }
              result += `\n`;
            }
            if (fortranNodes.length > 0) {
              result += `### Fortran Layer\n`;
              for (const node of fortranNodes.slice(0, 15)) {
                result += `- \`${node.name}\` [${node.label}] (${node.relType || 'CALLS'}, depth: ${node.hop})\n`;
              }
              result += `\n`;
            }
            if (pythonNodes.length > 0) {
              result += `### Python Layer\n`;
              for (const node of pythonNodes.slice(0, 15)) {
                result += `- \`${node.name}\` [${node.label}] (${node.relType || 'DEFINES'}, depth: ${node.hop})\n`;
              }
              result += `\n`;
            }
            result += `*Languages traversed: ${xLang.stats.languages.join(', ')} | Bridge crossings: ${xLang.stats.bridgeCrossings}*\n`;
          }
        } catch (xLangError) {
          console.error('[WARN] Cross-language traversal failed:', xLangError.message);
        }
      }

      // Complexity analysis
      result += `\n## Complexity Analysis\n\n`;
      result += `- **Fan-in:** ${callers.length} (${labels.caller.toLowerCase()} this)\n`;
      result += `- **Fan-out:** ${callChain ? callChain.length : 0} (${labels.callee.toLowerCase()} this)\n`;
      
      const complexity = (callers.length * (callChain ? callChain.length : 0));
      result += `- **Complexity Score:** ${complexity}\n`;
      
      if (complexity > 50) {
        result += `\n[WARN]  **High complexity** - Consider refactoring\n`;
      } else if (complexity > 20) {
        result += `\n[WARN]  **Moderate complexity** - Review for simplification\n`;
      } else {
        result += `\n[OK] **Low complexity** - Well-scoped ${labels.name.toLowerCase()}\n`;
      }

      // Phase 24D: GGSR scoring for callers/callees + semantic enrichment
      if (this.retrieval) {
        const rawResults = [];
        for (const c of callers.slice(0, 15)) {
          rawResults.push({
            name: c.name || c.callerName || c,
            relType: c.relationship || (graphType === 'fortran' ? 'CALLS' : graphType === 'shell' ? 'SOURCES' : 'CALLS'),
            depth: 1
          });
        }
        if (callChain) {
          for (const c of callChain.slice(0, 15)) {
            rawResults.push({
              name: c.callee || c.name,
              relType: graphType === 'fortran' ? 'CALLS' : graphType === 'shell' ? 'INVOKES' : 'CALLS',
              depth: c.depth || 1
            });
          }
        }
        const semanticKeys = [
          ...callers.slice(0, 3).map(c => c.name || c.callerName || c).filter(s => typeof s === 'string'),
          ...(callChain ? callChain.slice(0, 3).map(c => c.callee || c.name).filter(Boolean) : [])
        ];
        const ctx = await this.retrieval.retrieveFortranScored(
          function_name, rawResults, semanticKeys,
          { fileType: graphType, semanticLabel: 'key entities' }
        );
        result += ctx.ggsrSection + ctx.semanticSection + (ctx.communitySection || "");
      }

      return {
        content: [{
          type: 'text',
          text: result
        }]
      };

    } catch (error) {
      console.error('Error finding callers/callees:', error);
      return {
        content: [{
          type: 'text',
          text: `Error finding callers/callees: ${error.message}`
        }],
        isError: true
      };
    }
  }

  /**
   * Tool Implementation: Trace Full Execution Chain (Phase 24F Step 5)
   * Flagship cross-language tool — end-to-end Shell→Fortran→Python chains
   */
  async traceFullExecutionChain(args) {
    await this.ensureInitialized();

    // Phase 29: accept function_name as alias for start
    const start = args.start || args.function_name;
    const { direction = 'forward', max_depth = 5, languages } = args;
    const startTime = Date.now();

    try {
      const xLang = await this.dataAccess.graphDB.traceCrossLanguageChain(start, max_depth, direction);
      const elapsed = Date.now() - startTime;

      // Filter by requested languages if specified
      let chain = xLang.chain;
      if (languages && languages.length > 0) {
        const langSet = new Set(languages);
        chain = chain.filter(n => langSet.has(n.language));
      }

      let result = `# Full Execution Chain: ${start}\n\n`;

      if (chain.length === 0) {
        result += `*No execution chain found for "${start}". Try a J-Job name (e.g., JGLOBAL_FORECAST), script name (e.g., exglobal_forecast.sh), or Fortran program (e.g., gsi).*\n`;
        return { content: [{ type: 'text', text: result }] };
      }

      // Group by direction
      const forwardNodes = chain.filter(n => n.direction === 'forward');
      const reverseNodes = chain.filter(n => n.direction === 'reverse');

      if (forwardNodes.length > 0) {
        result += `### Forward Direction\n\n`;
        result += this._formatChainTree(forwardNodes, xLang.bridges.filter(b => true));
        result += `\n`;
      }
      if (reverseNodes.length > 0) {
        result += `### Reverse Direction\n\n`;
        result += this._formatChainTree(reverseNodes, xLang.bridges);
        result += `\n`;
      }

      result += `### Statistics\n`;
      result += `- Languages traversed: ${xLang.stats.languages.join(', ')}\n`;
      result += `- Total nodes: ${xLang.stats.totalNodes}\n`;
      result += `- Bridge crossings: ${xLang.stats.bridgeCrossings}\n`;
      result += `- Max depth: ${max_depth} hops\n`;
      result += `- Query time: ${elapsed}ms\n`;

      return { content: [{ type: 'text', text: result }] };
    } catch (error) {
      console.error('Error tracing full execution chain:', error);
      return {
        content: [{ type: 'text', text: `Error tracing execution chain: ${error.message}` }],
        isError: true
      };
    }
  }

  /** Format chain nodes as an indented tree. */
  _formatChainTree(nodes, bridges) {
    let result = '';
    const bridgeTargets = new Set(bridges.map(b => b.to));
    for (const node of nodes) {
      const indent = '  '.repeat(node.hop);
      const prefix = node.hop === 0 ? '' : '├── ';
      const langTag = node.language ? `[${node.language.charAt(0).toUpperCase() + node.language.slice(1)}]` : '';
      const isBridge = bridgeTargets.has(node.name);
      const bridgeMarker = isBridge ? ' ═══' : '';
      const relInfo = node.relType ? ` (${node.relType})` : '';
      result += `${indent}${prefix}${langTag} \`${node.name}\`${bridgeMarker}${relInfo}\n`;
    }
    return result;
  }

  /**
   * Tool Implementation: Find Environment Variable Dependencies
   * Queries Neo4j graph for scripts that depend on or export a variable
   */
  async findEnvDependencies(args) {
    await this.ensureInitialized();

    const { variable_name, show_exports = true, limit = 50, token_budget = 4000 } = args;
    const limitVal = Math.min(Math.max(parseInt(limit, 10) || 50, 1), 500);  // Clamp 1-500

    try {
      // Phase 53 D5: Build sections into local strings, run GGSR first, then
      // emit the header with a single-source count derived from total rows
      // shown (table + GGSR) so the header never disagrees with the body.

      // Query scripts that depend on this variable
      // Note: LIMIT embedded in query string (not parameter) to avoid Neo4j float conversion
      const dependsQuery = `
        MATCH (s:CodeFile)-[:DEPENDS_ON_ENV]->(e:EnvironmentVariable {name: $varName})
        RETURN s.name as script, s.path as path, s.script_type as type, s.language as language
        ORDER BY s.script_type, s.name
        LIMIT ${limitVal}
      `;

      const dependents = await this.dataAccess.graphDB.query(dependsQuery, {
        varName: variable_name
      });

      // Build the dependents body separately
      let dependentsBody = '';
      if (dependents.length > 0) {
        // Group by type
        const byType = {};
        for (const dep of dependents) {
          const type = dep.type || 'unknown';
          if (!byType[type]) byType[type] = [];
          byType[type].push(dep);
        }

        for (const [type, scripts] of Object.entries(byType)) {
          dependentsBody += `### ${type} (${scripts.length})\n`;
          for (const script of scripts.slice(0, 20)) {
            dependentsBody += `- **\`${script.script}\`**`;
            if (script.path) dependentsBody += ` - \`${script.path}\``;
            if (script.category) dependentsBody += ` [${script.category}]`;
            dependentsBody += `\n`;
          }
          if (scripts.length > 20) {
            dependentsBody += `*... and ${scripts.length - 20} more*\n`;
          }
          dependentsBody += `\n`;
        }
      } else {
        dependentsBody += `*No scripts found depending on this variable*\n\n`;
      }
      
      // Query scripts that export this variable
      let exportersBody = '';
      let exportersCount = 0;
      let exportersHeader = '';
      if (show_exports) {
        const exportsQuery = `
          MATCH (s:CodeFile)-[r:EXPORTS]->(e:EnvironmentVariable {name: $varName})
          RETURN s.name as script, s.path as path, s.script_type as type, r.line as line, r.value as value
          ORDER BY s.script_type, s.name
          LIMIT ${limitVal}
        `;

        const exporters = await this.dataAccess.graphDB.query(exportsQuery, {
          varName: variable_name
        });
        exportersCount = exporters.length;
        exportersHeader = `## Scripts Exporting \`${variable_name}\` (${exportersCount})\n\n`;

        if (exporters.length > 0) {
          for (const exp of exporters.slice(0, 20)) {
            exportersBody += `- **\`${exp.script}\`**`;
            if (exp.path) exportersBody += ` - \`${exp.path}\``;
            if (exp.line) exportersBody += ` (line ${exp.line})`;
            if (exp.value && exp.value.length < 50) exportersBody += ` = \`${exp.value}\``;
            exportersBody += `\n`;
          }
          if (exporters.length > 20) {
            exportersBody += `*... and ${exporters.length - 20} more*\n`;
          }
        } else {
          exportersBody += `*No scripts found exporting this variable*\n`;
        }
      }

      // Summary with EE2 metadata
      const metaQuery = `
        MATCH (e:EnvironmentVariable {name: $varName})
        RETURN e.is_ee2_standard as isEE2, e.is_home_model as isHome, e.first_seen_in as firstSeen
      `;
      const meta = await this.dataAccess.graphDB.query(metaQuery, { varName: variable_name });

      // Phase 24D: Unified GGSR + semantic retrieval for env variables
      // Wrapped in isolated try-catch so core graph results always return
      let ggsrBody = '';
      let ggsrCount = 0;
      if (this.retrieval) {
        try {
          const semanticKeys = dependents.slice(0, 5).map(d => d.script);
          const timeout = new Promise((_, reject) =>
            setTimeout(() => reject(new Error('GGSR retrieval timeout')), 15000)
          );
          const ctx = await Promise.race([
            this.retrieval.retrieve(variable_name, semanticKeys, {
              tokenBudget: token_budget, maxResults: 15, hops: 1,
              fileType: 'env-variable',
              semanticLabel: 'key scripts'
            }),
            timeout
          ]);
          ggsrBody = (ctx.ggsrSection || '') + (ctx.semanticSection || '') + (ctx.communitySection || '');
          ggsrCount = ctx.metadata?.ggsrCount || 0;
        } catch (ggsrErr) {
          console.error('[WARN] GGSR enrichment failed for env var:', ggsrErr.message);
          ggsrBody = `\n*[GGSR enrichment skipped: ${ggsrErr.message}]*\n`;
        }
      }

      // Phase 53 D5: Header count is single source of truth — total of
      // dependents + GGSR-enriched scripts. Avoids the report claiming
      // "(0)" while the body shows rows.
      const totalScripts = dependents.length + ggsrCount;

      let result = `# Environment Variable Analysis: ${variable_name}\n\n`;
      result += `## Scripts Depending on \`${variable_name}\` (${totalScripts})\n\n`;
      result += dependentsBody;

      if (show_exports) {
        result += exportersHeader + exportersBody;
      }

      result += `\n## Summary\n\n`;
      if (meta && meta.length > 0) {
        const m = meta[0];
        const tags = [];
        if (m.isEE2) tags.push('EE2 Standard');
        if (m.isHome) tags.push('HOMEmodel');
        if (tags.length > 0) result += `- **Classification:** ${tags.join(', ')}\n`;
        if (m.firstSeen) result += `- **First seen in:** \`${m.firstSeen}\`\n`;
      }
      result += `- **Total dependencies:** ${totalScripts} scripts\n`;
      result += `- **Impact level:** ${totalScripts > 50 ? 'HIGH' : totalScripts > 20 ? 'MEDIUM' : 'LOW'}\n`;

      if (totalScripts > 50) {
        result += `\n[WARN] This variable is widely used - changes will have broad impact\n`;
      }

      result += ggsrBody;

      return {
        content: [{
          type: 'text',
          text: result
        }]
      };

    } catch (error) {
      console.error('Error finding env dependencies:', error);
      return {
        content: [{
          type: 'text',
          text: `Error finding env dependencies: ${error.message}`
        }],
        isError: true
      };
    }
  }

  /**
   * Ensure data access is initialized
   */
  async ensureInitialized() {
    if (!this.isInitialized) {
      await this.initialize();
    }
  }

  /**
   * Cleanup resources
   */
  async cleanup() {
    if (this.dataAccess) {
      await this.dataAccess.close();
      this.dataAccess = null;
    }
    this.isInitialized = false;
  }
}

export default CodeAnalysisTools;
