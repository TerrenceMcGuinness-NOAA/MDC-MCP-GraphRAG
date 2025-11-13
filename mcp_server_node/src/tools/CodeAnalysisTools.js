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

    console.error('[OK] Registered 4 Code Analysis tools');
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
      let result = `# Execution Path Trace: ${function_name}\n\n`;

      // Find the function first
      const functions = file_path
        ? await this.dataAccess.graphDB.findFileFunctions(file_path)
        : await this.dataAccess.graphDB.query(
            'MATCH (f:FUNCTION {name: $name}) RETURN f LIMIT 5',
            { name: function_name }
          );

      if (!functions || functions.length === 0) {
        return {
          content: [{
            type: 'text',
            text: `Function "${function_name}" not found.\n\nTry using \`analyze_code_structure\` first to find available functions.`
          }]
        };
      }

      // Trace call chain from this function
      result += `## Call Chain (What ${function_name} calls)\n\n`;
      const callChain = await this.dataAccess.graphDB.traceCallChain(
        function_name,
        max_depth
      );

      if (callChain && callChain.length > 0) {
        result += `Traced ${callChain.length} function calls:\n\n`;
        for (const call of callChain.slice(0, 20)) {
          const indent = '  '.repeat((call.depth || 1) - 1);
          result += `${indent}${call.depth}. \`${call.callee || call.name}\``;
          if (call.file) {
            result += ` (in ${call.file})`;
          }
          result += `\n`;
        }
        if (callChain.length > 20) {
          result += `\n*... and ${callChain.length - 20} more calls*\n`;
        }
      } else {
        result += `*No function calls found or function is a leaf node*\n`;
      }

      // Optionally include callers
      if (include_callers) {
        result += `\n## Callers (What calls ${function_name})\n\n`;
        const callers = await this.dataAccess.graphDB.findCallers(function_name);

        if (callers && callers.length > 0) {
          result += `Found ${callers.length} callers:\n\n`;
          for (const caller of callers.slice(0, 10)) {
            result += `- \`${caller.name || caller}\``;
            if (caller.file) {
              result += ` (in ${caller.file})`;
            }
            result += `\n`;
          }
          if (callers.length > 10) {
            result += `*... and ${callers.length - 10} more callers*\n`;
          }
        } else {
          result += `*No callers found - this may be an entry point function*\n`;
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
      let result = `# Function Analysis: ${function_name}\n\n`;

      // Find callers (upstream - what calls this function)
      const callers = await this.dataAccess.graphDB.findCallers(function_name);
      result += `## Callers (${callers.length})\n`;
      result += `*Functions that call ${function_name}*\n\n`;

      if (callers.length > 0) {
        for (const caller of callers.slice(0, 15)) {
          result += `- **\`${caller.name || caller}\`**`;
          if (caller.file) {
            result += ` in \`${caller.file}\``;
          }
          if (caller.lineNumber) {
            result += ` (line ${caller.lineNumber})`;
          }
          result += `\n`;
        }
        if (callers.length > 15) {
          result += `\n*... and ${callers.length - 15} more callers*\n`;
        }
      } else {
        result += `*No callers found - this may be an entry point or unused function*\n`;
      }

      // Find callees (downstream - what this function calls)
      result += `\n## Callees\n`;
      result += `*Functions called by ${function_name}*\n\n`;

      const callChain = await this.dataAccess.graphDB.traceCallChain(function_name, 1);
      
      if (callChain && callChain.length > 0) {
        for (const call of callChain.slice(0, 15)) {
          result += `- **\`${call.callee || call.name}\`**`;
          if (call.file) {
            result += ` in \`${call.file}\``;
          }
          result += `\n`;
        }
        if (callChain.length > 15) {
          result += `\n*... and ${callChain.length - 15} more callees*\n`;
        }
      } else {
        result += `*No callees found - this is a leaf function*\n`;
      }

      // Complexity analysis
      result += `\n## Complexity Analysis\n\n`;
      result += `- **Fan-in:** ${callers.length} (functions calling this)\n`;
      result += `- **Fan-out:** ${callChain ? callChain.length : 0} (functions this calls)\n`;
      
      const complexity = (callers.length * (callChain ? callChain.length : 0));
      result += `- **Complexity Score:** ${complexity}\n`;
      
      if (complexity > 50) {
        result += `\n[WARN]  **High complexity** - Consider refactoring\n`;
      } else if (complexity > 20) {
        result += `\n[WARN]  **Moderate complexity** - Review for simplification\n`;
      } else {
        result += `\n[OK] **Low complexity** - Well-scoped function\n`;
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
