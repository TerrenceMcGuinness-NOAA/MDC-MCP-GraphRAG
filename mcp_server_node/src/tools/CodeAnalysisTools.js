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

export class CodeAnalysisTools {
  constructor(dataAccess = null) {
    this.dataAccess = dataAccess;  // Accept injected dependency for testing
    this.isInitialized = !!dataAccess;  // Already initialized if dataAccess provided
  }

  /**
   * Initialize data access layer
   */
  async initialize() {
    if (this.isInitialized) return;

    console.error('[INIT] Initializing Code Analysis Tools...');
    
    this.dataAccess = new UnifiedDataAccess();
    await this.dataAccess.connect();  // Fixed: connect() not initialize()
    
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
          }
        },
        required: ['function_name']
      },
      this.findCallersCallees.bind(this)
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

    const { file_path, include_dependencies = true, depth = 2 } = args;

    try {
      // Use UnifiedDataAccess to get file information with graph context
      const fileInfo = await this.dataAccess.graphDB.findFileFunctions(file_path);
      
      if (!fileInfo || fileInfo.length === 0) {
        return {
          content: [{
            type: 'text',
            text: `File not found: ${file_path}\n\nTip: Use semantic search to find similar files:\n\`\`\`\nsearch_documentation query:"${file_path.split('/').pop()}"\n\`\`\``
          }]
        };
      }

      // Build analysis result
      let analysis = `# Code Structure Analysis: ${file_path}\n\n`;
      
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

    const { target, direction = 'both', max_depth = 3 } = args;

    try {
      let result = `# Dependency Analysis: ${target}\n\n`;

      if (direction === 'upstream' || direction === 'both') {
        result += `## Upstream Dependencies (What ${target} imports)\n\n`;
        const imports = await this.dataAccess.graphDB.findFileImports(target);
        
        if (imports.length > 0) {
          result += `Found ${imports.length} direct imports:\n\n`;
          for (const imp of imports) {
            result += `- \`${imp.target || imp}\`\n`;
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
            result += `- \`${imp.source || imp}\`\n`;
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

    const { function_name, file_path, max_depth = 3, include_callers = false } = args;

    try {
      let graphType = 'function'; // 'function', 'fortran', 'shell', or 'cross-language'
      
      // Find the entity - try Python function first
      let functions = file_path
        ? await this.dataAccess.graphDB.findFileFunctions(file_path)
        : await this.dataAccess.graphDB.query(
            'MATCH (f:FUNCTION {name: $name}) RETURN f LIMIT 5',
            { name: function_name }
          );
      
      // If no Python function, try Fortran (Phase 10 M5)
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
          `MATCH (s:ShellScript) WHERE toLower(s.name) CONTAINS toLower($name)
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
            text: `Entity "${function_name}" not found in function, Fortran, or shell script graphs.\n\nTry using \`analyze_code_structure\` first to find available entities.`
          }]
        };
      }
      
      // Set up labels based on graph type
      const typeLabels = {
        function: { entity: 'Function', calls: 'function calls' },
        fortran: { entity: 'Fortran', calls: 'Fortran calls' },
        shell: { entity: 'Shell Script', calls: 'script invocations' }
      };
      const labels = typeLabels[graphType] || typeLabels.function;
      
      let result = `# Execution Path Trace: ${function_name}\n\n`;
      result += `*Entity type: ${labels.entity}*\n\n`;

      // Trace call chain based on graph type
      result += `## Call Chain (What ${function_name} calls)\n\n`;
      
      let callChain;
      if (graphType === 'fortran') {
        callChain = await this.dataAccess.graphDB.traceFortranCallChain(function_name, max_depth);
      } else if (graphType === 'shell') {
        callChain = await this.dataAccess.graphDB.traceScriptChain(function_name, max_depth);
        
        // For shell scripts, also check for cross-language paths to Fortran
        const crossLangPath = await this.dataAccess.graphDB.traceCrossLanguagePath(function_name, max_depth);
        if (crossLangPath && crossLangPath.length > 0) {
          // Filter to only show entries with actual Fortran programs
          const validPaths = crossLangPath.filter(p => p.fortranProgram);
          if (validPaths.length > 0) {
            result += `### Cross-Language Path (Shell → Fortran)\n`;
            result += `*Shell script executes Fortran code via EXECUTES relationship*\n\n`;
            
            for (const step of validPaths.slice(0, 15)) {
              const script = step.executingScript || step.sourceScript;
              result += `- \`${script}\` —[EXECUTES]→ \`${step.fortranProgram}\``;
              if (step.fortranSubroutine) {
                result += ` —[CALLS]→ \`${step.fortranSubroutine}\``;
                if (step.subroutineType) result += ` [${step.subroutineType}]`;
              }
              result += `\n`;
            }
            if (validPaths.length > 15) {
              result += `*... and ${validPaths.length - 15} more paths*\n`;
            }
            result += `\n`;
          }
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
        if (graphType === 'fortran') {
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

    const { function_name, file_path, include_source = false } = args;

    try {
      // First try function graph (Python)
      let callers = await this.dataAccess.graphDB.findCallers(function_name);
      let callChain = await this.dataAccess.graphDB.traceCallChain(function_name, 1);
      
      // Track which graph type we're using
      let graphType = 'function';
      
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
          const name = caller.name || caller.callerName || caller;
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
   * Tool Implementation: Find Environment Variable Dependencies
   * Queries Neo4j graph for scripts that depend on or export a variable
   */
  async findEnvDependencies(args) {
    await this.ensureInitialized();

    const { variable_name, show_exports = true, limit = 50 } = args;
    const limitVal = Math.min(Math.max(parseInt(limit, 10) || 50, 1), 500);  // Clamp 1-500

    try {
      let result = `# Environment Variable Analysis: ${variable_name}\n\n`;
      
      // Query scripts that depend on this variable
      // Note: LIMIT embedded in query string (not parameter) to avoid Neo4j float conversion
      const dependsQuery = `
        MATCH (s:ShellScript)-[:DEPENDS_ON_ENV]->(e:EnvironmentVariable {name: $varName})
        RETURN s.name as script, s.path as path, s.type as type, s.category as category
        ORDER BY s.type, s.name
        LIMIT ${limitVal}
      `;
      
      const dependents = await this.dataAccess.graphDB.query(dependsQuery, { 
        varName: variable_name
      });
      
      result += `## Scripts Depending on \`${variable_name}\` (${dependents.length})\n\n`;
      
      if (dependents.length > 0) {
        // Group by type
        const byType = {};
        for (const dep of dependents) {
          const type = dep.type || 'unknown';
          if (!byType[type]) byType[type] = [];
          byType[type].push(dep);
        }
        
        for (const [type, scripts] of Object.entries(byType)) {
          result += `### ${type} (${scripts.length})\n`;
          for (const script of scripts.slice(0, 20)) {
            result += `- **\`${script.script}\`**`;
            if (script.path) result += ` - \`${script.path}\``;
            if (script.category) result += ` [${script.category}]`;
            result += `\n`;
          }
          if (scripts.length > 20) {
            result += `*... and ${scripts.length - 20} more*\n`;
          }
          result += `\n`;
        }
      } else {
        result += `*No scripts found depending on this variable*\n\n`;
      }
      
      // Query scripts that export this variable
      if (show_exports) {
        const exportsQuery = `
          MATCH (s:ShellScript)-[r:EXPORTS]->(e:EnvironmentVariable {name: $varName})
          RETURN s.name as script, s.path as path, s.type as type, r.line as line, e.default_value as value
          ORDER BY s.type, s.name
          LIMIT ${limitVal}
        `;
        
        const exporters = await this.dataAccess.graphDB.query(exportsQuery, { 
          varName: variable_name
        });
        
        result += `## Scripts Exporting \`${variable_name}\` (${exporters.length})\n\n`;
        
        if (exporters.length > 0) {
          for (const exp of exporters.slice(0, 20)) {
            result += `- **\`${exp.script}\`**`;
            if (exp.path) result += ` - \`${exp.path}\``;
            if (exp.line) result += ` (line ${exp.line})`;
            if (exp.value && exp.value.length < 50) result += ` = \`${exp.value}\``;
            result += `\n`;
          }
          if (exporters.length > 20) {
            result += `*... and ${exporters.length - 20} more*\n`;
          }
        } else {
          result += `*No scripts found exporting this variable*\n`;
        }
      }
      
      // Summary
      result += `\n## Summary\n\n`;
      result += `- **Total dependencies:** ${dependents.length} scripts\n`;
      result += `- **Impact level:** ${dependents.length > 50 ? 'HIGH' : dependents.length > 20 ? 'MEDIUM' : 'LOW'}\n`;
      
      if (dependents.length > 50) {
        result += `\n[WARN] This variable is widely used - changes will have broad impact\n`;
      }

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
