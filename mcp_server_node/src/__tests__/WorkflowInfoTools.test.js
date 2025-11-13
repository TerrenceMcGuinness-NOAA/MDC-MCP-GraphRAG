/**
 * Unit Tests for WorkflowInfoTools
 * Week 3 Phase 4: Test Suite Development
 * 
 * Tests 3 tools:
 * 1. get_workflow_structure
 * 2. get_system_configs
 * 3. describe_component
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import WorkflowInfoTools from '../tools/WorkflowInfoTools.js';
import fs from 'fs/promises';

vi.mock('fs/promises');

describe('WorkflowInfoTools', () => {
  let tools;

  beforeEach(() => {
    tools = new WorkflowInfoTools();
    
    // Mock file system reads
    fs.readdir.mockResolvedValue([]);
    fs.stat.mockResolvedValue({ isDirectory: () => false, isFile: () => true });
    fs.readFile.mockResolvedValue('');
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe('get_workflow_structure', () => {
    it('should return complete workflow structure', async () => {
      fs.readdir.mockResolvedValue([
        'jobs', 'scripts', 'parm', 'ush', 'sorc', 'docs', 'env'
      ]);

      const result = await tools.getWorkflowStructure({});

      expect(result.content[0].text).toContain('jobs');
      expect(result.content[0].text).toContain('scripts');
      expect(result.content[0].text).toContain('workflow structure');
    });

    it('should focus on specific component when requested', async () => {
      fs.readdir.mockResolvedValue([
        'JGLOBAL_FORECAST', 'JGDAS_ANALYSIS', 'JGLOBAL_ARCHIVE'
      ]);

      const result = await tools.getWorkflowStructure({
        component: 'jobs'
      });

      expect(result.content[0].text).toContain('jobs');
      expect(result.content[0].text).toContain('JGLOBAL_FORECAST');
    });

    it('should provide component descriptions', async () => {
      const result = await tools.getWorkflowStructure({
        component: 'scripts'
      });

      expect(result.content[0].text).toMatch(/script|execute|operational/i);
    });
  });

  describe('get_system_configs', () => {
    it('should return configs for specific platform', async () => {
      const result = await tools.getSystemConfigs({
        platform: 'hera',
        configType: 'all'
      });

      expect(result.content[0].text).toContain('hera');
      expect(result.content[0].text).toMatch(/module|resource|path/i);
    });

    it('should filter by config type', async () => {
      const result = await tools.getSystemConfigs({
        platform: 'wcoss2',
        configType: 'modules'
      });

      expect(result.content[0].text).toContain('module');
      expect(result.content[0].text).not.toContain('resources');
    });

    it('should return all platform configs when platform is "all"', async () => {
      const result = await tools.getSystemConfigs({
        platform: 'all',
        configType: 'resources'
      });

      expect(result.content[0].text).toMatch(/hera|hercules|orion|wcoss2|gaea/i);
    });

    it('should provide module information', async () => {
      const result = await tools.getSystemConfigs({
        platform: 'orion',
        configType: 'modules'
      });

      expect(result.content[0].text).toContain('module');
    });

    it('should provide resource information', async () => {
      const result = await tools.getSystemConfigs({
        platform: 'gaea',
        configType: 'resources'
      });

      expect(result.content[0].text).toMatch(/cpu|memory|partition|queue/i);
    });

    it('should provide path information', async () => {
      const result = await tools.getSystemConfigs({
        platform: 'hercules',
        configType: 'paths'
      });

      expect(result.content[0].text).toMatch(/path|directory|ROTDIR|DMPDIR/i);
    });
  });

  describe('describe_component', () => {
    it('should describe component from file system', async () => {
      fs.stat.mockResolvedValue({
        isDirectory: () => false,
        isFile: () => true,
        size: 1024,
        mtime: new Date()
      });
      fs.readFile.mockResolvedValue('#!/bin/bash\n# Job script for forecast\n');

      const result = await tools.describeComponent({
        component: 'jobs/JGLOBAL_FORECAST'
      });

      expect(result.content[0].text).toContain('JGLOBAL_FORECAST');
      expect(result.content[0].text).toMatch(/file|size|modified/i);
    });

    it('should show file content preview when requested', async () => {
      fs.readFile.mockResolvedValue('#!/bin/bash\nexport VAR=value\necho "Starting forecast"');

      const result = await tools.describeComponent({
        component: 'jobs/JGLOBAL_FORECAST',
        showContent: true
      });

      expect(result.content[0].text).toContain('#!/bin/bash');
      expect(result.content[0].text).toContain('export VAR=value');
    });

    it('should describe directories', async () => {
      fs.stat.mockResolvedValue({
        isDirectory: () => true,
        isFile: () => false
      });
      fs.readdir.mockResolvedValue(['file1.py', 'file2.sh', 'subdir']);

      const result = await tools.describeComponent({
        component: 'scripts'
      });

      expect(result.content[0].text).toContain('directory');
      expect(result.content[0].text).toContain('file1.py');
    });

    it('should handle non-existent components', async () => {
      fs.stat.mockRejectedValue(new Error('ENOENT: no such file'));

      const result = await tools.describeComponent({
        component: 'nonexistent/component'
      });

      expect(result.content[0].text).toMatch(/not found|does not exist/i);
    });
  });

  describe('Error Handling', () => {
    it('should handle file system errors gracefully', async () => {
      fs.readdir.mockRejectedValue(new Error('Permission denied'));

      const result = await tools.getWorkflowStructure({});

      expect(result.content[0].text).toContain('error');
    });

    it('should provide fallback info when files unavailable', async () => {
      fs.readFile.mockRejectedValue(new Error('Read error'));

      const result = await tools.describeComponent({
        component: 'test.sh',
        showContent: true
      });

      expect(result.content[0].text).toMatch(/error|unable to read/i);
    });
  });
});
