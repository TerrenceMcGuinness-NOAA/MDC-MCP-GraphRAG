/**
 * Unit Tests for CodeAnalysisTools
 * Updated: Phase 52 — aligned with current graphDB API (capital B)
 *
 * Tests 4 tools:
 * 1. analyze_code_structure   (uses graphDB.findFileFunctions, findFileImports, findImporters)
 * 2. find_dependencies        (uses graphDB.findFileImports, findImporters, findCircularDependencies)
 * 3. trace_execution_path     (uses graphDB.query, tracePythonCallChain, traceCallChain)
 * 4. find_callers_callees     (uses graphDB.findCallers, findCallees)
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import CodeAnalysisTools from '../tools/CodeAnalysisTools.js';

describe('CodeAnalysisTools', () => {
  let tools;
  let mockDataAccess;

  beforeEach(() => {
    mockDataAccess = {
      graphDB: {
        query: vi.fn().mockResolvedValue([]),
        findFileFunctions: vi.fn().mockResolvedValue([]),
        findFileImports: vi.fn().mockResolvedValue([]),
        findImporters: vi.fn().mockResolvedValue([]),
        findCircularDependencies: vi.fn().mockResolvedValue([]),
        tracePythonCallChain: vi.fn().mockResolvedValue([]),
        traceFortranCallChain: vi.fn().mockResolvedValue([]),
        traceCallChain: vi.fn().mockResolvedValue([]),
        traceScriptChain: vi.fn().mockResolvedValue([]),
        traceCrossLanguageChain: vi.fn().mockResolvedValue([]),
        findCallers: vi.fn().mockResolvedValue([]),
        findCallees: vi.fn().mockResolvedValue([]),
        findPythonCallers: vi.fn().mockResolvedValue([]),
        findFortranCallers: vi.fn().mockResolvedValue([]),
        findScriptCallers: vi.fn().mockResolvedValue([]),
        findFortranModuleUses: vi.fn().mockResolvedValue([]),
        healthCheck: vi.fn().mockResolvedValue(true)
      },
      connect: vi.fn().mockResolvedValue()
    };

    tools = new CodeAnalysisTools(mockDataAccess);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe('analyze_code_structure', () => {
    it('should analyze file structure via findFileFunctions', async () => {
      mockDataAccess.graphDB.findFileFunctions.mockResolvedValue([
        { name: 'main', type: 'FUNCTION', lineNumber: 10 },
        { name: 'run_forecast', type: 'FUNCTION', lineNumber: 50 }
      ]);
      mockDataAccess.graphDB.findFileImports.mockResolvedValue([
        { target: 'os' }, { target: 'pygfs.utils' }
      ]);
      mockDataAccess.graphDB.findImporters.mockResolvedValue([
        { source: 'exglobal_forecast' }
      ]);

      const result = await tools.analyzeCodeStructure({
        file_path: 'scripts/exglobal_forecast.py',
        depth: 2
      });

      expect(mockDataAccess.graphDB.findFileFunctions).toHaveBeenCalledWith('scripts/exglobal_forecast.py');
      expect(result.content[0].text).toContain('exglobal_forecast.py');
      expect(result.content[0].text).toContain('main');
      expect(result.content[0].text).toContain('run_forecast');
    });

    it('should include dependency analysis when requested', async () => {
      mockDataAccess.graphDB.findFileFunctions.mockResolvedValue([
        { name: 'process_data', type: 'FUNCTION' }
      ]);
      mockDataAccess.graphDB.findFileImports.mockResolvedValue([
        { target: 'typing' }, { target: 'dataclasses' }
      ]);
      mockDataAccess.graphDB.findImporters.mockResolvedValue([
        { source: 'exglobal_forecast' }, { source: 'exgdas_analysis' }
      ]);

      const result = await tools.analyzeCodeStructure({
        file_path: 'ush/utils.py',
        include_dependencies: true
      });

      const text = result.content[0].text;
      expect(text).toContain('typing');
      expect(text).toContain('exglobal_forecast');
    });
  });

  describe('find_dependencies', () => {
    it('should find upstream dependencies (imports)', async () => {
      mockDataAccess.graphDB.findFileImports.mockResolvedValue([
        { target: 'os' },
        { target: 'pygfs.utils' },
        { target: 'numpy' }
      ]);

      const result = await tools.findDependencies({
        target: 'scripts/exglobal_forecast.py',
        direction: 'upstream'
      });

      const text = result.content[0].text;
      expect(text).toContain('os');
      expect(text).toContain('pygfs.utils');
      expect(text).toContain('numpy');
    });

    it('should find downstream dependencies (importers)', async () => {
      mockDataAccess.graphDB.findImporters.mockResolvedValue([
        { source: 'exglobal_forecast' },
        { source: 'exgdas_analysis' },
        { source: 'exgfs_wave_post' }
      ]);

      const result = await tools.findDependencies({
        target: 'ush/pygfs/utils.py',
        direction: 'downstream'
      });

      const text = result.content[0].text;
      expect(text).toContain('exglobal_forecast');
      expect(text).toContain('exgdas_analysis');
    });

    it('should handle both direction', async () => {
      mockDataAccess.graphDB.findFileImports.mockResolvedValue([{ target: 'os' }]);
      mockDataAccess.graphDB.findImporters.mockResolvedValue([{ source: 'caller_module' }]);

      const result = await tools.findDependencies({
        target: 'module_a',
        direction: 'both',
        max_depth: 5
      });

      const text = result.content[0].text;
      expect(text).toBeDefined();
      expect(text.length).toBeGreaterThan(0);
    });
  });

  describe('trace_execution_path', () => {
    it('should trace function call chains via graphDB', async () => {
      // Tool first queries for function language, then traces
      mockDataAccess.graphDB.query.mockResolvedValue([
        { name: 'main', language: 'python', filePath: 'scripts/exglobal_forecast.py' }
      ]);
      mockDataAccess.graphDB.tracePythonCallChain.mockResolvedValue([
        { callee: 'run_forecast', depth: 1 },
        { callee: 'setup_environment', depth: 2 }
      ]);

      const result = await tools.traceExecutionPath({
        function_name: 'main',
        file_path: 'scripts/exglobal_forecast.py',
        max_depth: 3
      });

      expect(result.content[0].text).toContain('main');
    });

    it('should handle function not found', async () => {
      mockDataAccess.graphDB.findFileFunctions.mockResolvedValue([]);
      mockDataAccess.graphDB.query.mockResolvedValue([]);

      const result = await tools.traceExecutionPath({
        function_name: 'nonexistent_func',
        max_depth: 10
      });

      expect(result.content[0].text).toMatch(/not found|no.*found|could not/i);
    });
  });

  describe('find_callers_callees', () => {
    it('should find functions that call target function', async () => {
      mockDataAccess.graphDB.findCallers.mockResolvedValue([
        { name: 'main', file: 'exglobal_forecast.py' },
        { name: 'batch_process', file: 'batch_runner.py' }
      ]);

      const result = await tools.findCallersCallees({
        function_name: 'process_data',
        file_path: 'ush/utils.py'
      });

      const text = result.content[0].text;
      expect(text).toContain('main');
      expect(text).toContain('batch_process');
    });

    it('should find functions called by target function via traceCallChain', async () => {
      mockDataAccess.graphDB.findCallers.mockResolvedValue([]);
      mockDataAccess.graphDB.traceCallChain.mockResolvedValue([
        { callee: 'setup', file: 'utils.py', depth: 1 },
        { callee: 'run_forecast', file: 'forecast.py', depth: 1 },
        { callee: 'cleanup', file: 'utils.py', depth: 1 }
      ]);

      const result = await tools.findCallersCallees({
        function_name: 'main'
      });

      const text = result.content[0].text;
      expect(text).toContain('setup');
      expect(text).toContain('run_forecast');
      expect(text).toContain('cleanup');
    });

    it('should handle functions with no callers or callees', async () => {
      mockDataAccess.graphDB.findCallers.mockResolvedValue([]);
      mockDataAccess.graphDB.findCallees.mockResolvedValue([]);

      const result = await tools.findCallersCallees({
        function_name: 'unused_function'
      });

      expect(result.content[0].text).toBeDefined();
      expect(result.content[0].text.length).toBeGreaterThan(0);
    });
  });

  describe('Error Handling', () => {
    it('should handle graph database errors', async () => {
      mockDataAccess.graphDB.findFileFunctions.mockRejectedValue(new Error('Neo4j unavailable'));

      const result = await tools.analyzeCodeStructure({
        file_path: 'test.py'
      });

      expect(result.content[0].text).toMatch(/error/i);
    });

    it('should handle missing files gracefully', async () => {
      mockDataAccess.graphDB.findFileFunctions.mockResolvedValue([]);

      const result = await tools.analyzeCodeStructure({
        file_path: 'nonexistent.py'
      });

      expect(result.content[0].text).toMatch(/not found|tip/i);
    });
  });
});
