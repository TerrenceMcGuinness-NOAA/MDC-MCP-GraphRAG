/**
 * Unit Tests for CodeAnalysisTools
 * Week 3 Phase 4: Test Suite Development
 * 
 * Tests 4 tools:
 * 1. analyze_code_structure
 * 2. find_dependencies
 * 3. trace_execution_path
 * 4. find_callers_callees
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import CodeAnalysisTools from '../tools/CodeAnalysisTools.js';

describe('CodeAnalysisTools', () => {
  let tools;
  let mockDataAccess;

  beforeEach(() => {
    mockDataAccess = {
      graphDb: {
        query: vi.fn(),
        healthCheck: vi.fn()
      }
    };

    tools = new CodeAnalysisTools(mockDataAccess);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe('analyze_code_structure', () => {
    it('should analyze file structure and dependencies', async () => {
      mockDataAccess.graphDb.query.mockResolvedValue([
        {
          file: { path: 'scripts/exglobal_forecast.py', language: 'python' },
          functions: [
            { name: 'main', lines: 50 },
            { name: 'run_forecast', lines: 120 }
          ],
          imports: ['os', 'sys', 'pygfs.utils'],
          complexity: 15
        }
      ]);

      const result = await tools.analyzeCodeStructure({
        filePath: 'scripts/exglobal_forecast.py',
        depth: 2
      });

      expect(mockDataAccess.graphDb.query).toHaveBeenCalled();
      expect(result.content[0].text).toContain('exglobal_forecast.py');
      expect(result.content[0].text).toContain('main');
      expect(result.content[0].text).toContain('run_forecast');
    });

    it('should include dependency analysis when requested', async () => {
      mockDataAccess.graphDb.query.mockResolvedValueOnce([
        {
          file: { path: 'ush/utils.py' },
          functions: [{ name: 'process_data' }]
        }
      ]).mockResolvedValueOnce([
        {
          upstream: ['typing', 'dataclasses'],
          downstream: ['exglobal_forecast', 'exgdas_analysis']
        }
      ]);

      const result = await tools.analyzeCodeStructure({
        filePath: 'ush/utils.py',
        includeDependencies: true
      });

      expect(result.content[0].text).toContain('typing');
      expect(result.content[0].text).toContain('exglobal_forecast');
    });
  });

  describe('find_dependencies', () => {
    it('should find upstream dependencies (imports)', async () => {
      mockDataAccess.graphDb.query.mockResolvedValue([
        {
          module: 'exglobal_forecast',
          imports: [
            { name: 'os', type: 'stdlib' },
            { name: 'pygfs.utils', type: 'internal' },
            { name: 'numpy', type: 'external' }
          ]
        }
      ]);

      const result = await tools.findDependencies({
        target: 'scripts/exglobal_forecast.py',
        direction: 'upstream'
      });

      expect(result.content[0].text).toContain('os');
      expect(result.content[0].text).toContain('pygfs.utils');
      expect(result.content[0].text).toContain('numpy');
    });

    it('should find downstream dependencies (importers)', async () => {
      mockDataAccess.graphDb.query.mockResolvedValue([
        {
          module: 'pygfs.utils',
          importedBy: [
            'exglobal_forecast',
            'exgdas_analysis',
            'exgfs_wave_post'
          ]
        }
      ]);

      const result = await tools.findDependencies({
        target: 'ush/pygfs/utils.py',
        direction: 'downstream'
      });

      expect(result.content[0].text).toContain('exglobal_forecast');
      expect(result.content[0].text).toContain('exgdas_analysis');
    });

    it('should handle circular dependencies', async () => {
      mockDataAccess.graphDb.query.mockResolvedValue([
        {
          circular: [
            { from: 'module_a', to: 'module_b' },
            { from: 'module_b', to: 'module_a' }
          ]
        }
      ]);

      const result = await tools.findDependencies({
        target: 'module_a',
        direction: 'both',
        maxDepth: 5
      });

      expect(result.content[0].text).toMatch(/circular|cycle/i);
    });
  });

  describe('trace_execution_path', () => {
    it('should trace function call chains', async () => {
      mockDataAccess.graphDb.query.mockResolvedValue([
        {
          path: [
            { function: 'main', file: 'exglobal_forecast.py' },
            { function: 'run_forecast', file: 'exglobal_forecast.py' },
            { function: 'setup_environment', file: 'pygfs/utils.py' },
            { function: 'load_config', file: 'pygfs/config.py' }
          ]
        }
      ]);

      const result = await tools.traceExecutionPath({
        functionName: 'main',
        filePath: 'scripts/exglobal_forecast.py',
        maxDepth: 3
      });

      expect(result.content[0].text).toContain('main');
      expect(result.content[0].text).toContain('run_forecast');
      expect(result.content[0].text).toContain('setup_environment');
      expect(result.content[0].text).toContain('→'); // Path indicator
    });

    it('should detect recursive calls', async () => {
      mockDataAccess.graphDb.query.mockResolvedValue([
        {
          path: [
            { function: 'factorial', file: 'utils.py' },
            { function: 'factorial', file: 'utils.py' } // Recursive
          ],
          recursive: true
        }
      ]);

      const result = await tools.traceExecutionPath({
        functionName: 'factorial',
        maxDepth: 10
      });

      expect(result.content[0].text).toMatch(/recursive|recursion/i);
    });
  });

  describe('find_callers_callees', () => {
    it('should find functions that call target function', async () => {
      mockDataAccess.graphDb.query.mockResolvedValue([
        {
          function: 'process_data',
          callers: [
            { name: 'main', file: 'exglobal_forecast.py', line: 45 },
            { name: 'batch_process', file: 'batch_runner.py', line: 78 }
          ]
        }
      ]);

      const result = await tools.findCallersCallees({
        functionName: 'process_data',
        filePath: 'ush/utils.py'
      });

      expect(result.content[0].text).toContain('main');
      expect(result.content[0].text).toContain('batch_process');
      expect(result.content[0].text).toContain('line 45');
    });

    it('should find functions called by target function', async () => {
      mockDataAccess.graphDb.query.mockResolvedValue([
        {
          function: 'main',
          callees: [
            { name: 'setup', file: 'utils.py' },
            { name: 'run_forecast', file: 'forecast.py' },
            { name: 'cleanup', file: 'utils.py' }
          ]
        }
      ]);

      const result = await tools.findCallersCallees({
        functionName: 'main',
        includeSource: true
      });

      expect(result.content[0].text).toContain('setup');
      expect(result.content[0].text).toContain('run_forecast');
      expect(result.content[0].text).toContain('cleanup');
    });

    it('should handle functions with no callers or callees', async () => {
      mockDataAccess.graphDb.query.mockResolvedValue([
        {
          function: 'unused_function',
          callers: [],
          callees: []
        }
      ]);

      const result = await tools.findCallersCallees({
        functionName: 'unused_function'
      });

      expect(result.content[0].text).toMatch(/no callers|unused|isolated/i);
    });
  });

  describe('Error Handling', () => {
    it('should handle graph database errors', async () => {
      mockDataAccess.graphDb.query.mockRejectedValue(new Error('Neo4j unavailable'));

      const result = await tools.analyzeCodeStructure({
        filePath: 'test.py'
      });

      expect(result.content[0].text).toContain('error');
      expect(result.content[0].text).toContain('Neo4j');
    });

    it('should handle missing files gracefully', async () => {
      mockDataAccess.graphDb.query.mockResolvedValue([]);

      const result = await tools.analyzeCodeStructure({
        filePath: 'nonexistent.py'
      });

      expect(result.content[0].text).toMatch(/not found|no data|missing/i);
    });
  });
});
