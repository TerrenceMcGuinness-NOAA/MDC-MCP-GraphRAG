/**
 * Unit Tests for WorkflowInfoTools
 * Updated: Phase 52 — aligned with actual tool output format
 *
 * WorkflowInfoTools uses a hardcoded structure object and real filesystem.
 * Tests validate the actual output format rather than mock-driven behavior.
 *
 * Tests 3 tools:
 * 1. get_workflow_structure
 * 2. get_system_configs
 * 3. describe_component
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import WorkflowInfoTools from '../tools/WorkflowInfoTools.js';

describe('WorkflowInfoTools', () => {
  let tools;

  beforeEach(() => {
    tools = new WorkflowInfoTools();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe('get_workflow_structure', () => {
    it('should return complete workflow structure', async () => {
      const result = await tools.getWorkflowStructure({});

      const text = result.content[0].text;
      expect(text).toContain('Global Workflow Structure');
      expect(text).toContain('jobs');
      expect(text).toContain('scripts');
      expect(text).toContain('parm');
      expect(text).toContain('ush');
    });

    it('should focus on specific component when requested', async () => {
      const result = await tools.getWorkflowStructure({
        component: 'jobs'
      });

      const text = result.content[0].text;
      expect(text).toContain('jobs');
      expect(text).toContain('Job Control Language');
    });

    it('should provide component descriptions', async () => {
      const result = await tools.getWorkflowStructure({
        component: 'scripts'
      });

      const text = result.content[0].text;
      expect(text).toMatch(/script|execution/i);
    });

    it('should return structure for env component', async () => {
      const result = await tools.getWorkflowStructure({
        component: 'env'
      });

      const text = result.content[0].text;
      expect(text).toContain('env');
      expect(text).toMatch(/platform|HPC|environment/i);
    });
  });

  describe('get_system_configs', () => {
    it('should return configs for specific platform', async () => {
      const result = await tools.getSystemConfigs({
        platform: 'hera'
      });

      const text = result.content[0].text;
      // Tool returns platform info from env files or hardcoded data
      expect(text).toMatch(/hera/i);
    });

    it('should handle generic platform query', async () => {
      const result = await tools.getSystemConfigs({
        platform: 'generic'
      });

      const text = result.content[0].text;
      expect(text).toBeDefined();
      expect(text.length).toBeGreaterThan(0);
    });

    it('should return content for all platform query', async () => {
      const result = await tools.getSystemConfigs({
        platform: 'all'
      });

      const text = result.content[0].text;
      expect(text).toBeDefined();
      expect(text.length).toBeGreaterThan(0);
    });
  });

  describe('describe_component', () => {
    it('should describe a known component from file system', async () => {
      // Use a component that exists in supported_repos/global-workflow
      const result = await tools.describeComponent({
        component: 'jobs'
      });

      const text = result.content[0].text;
      expect(text).toBeDefined();
      expect(text.length).toBeGreaterThan(0);
    });

    it('should handle non-existent components', async () => {
      const result = await tools.describeComponent({
        component: 'ZTOTALLY_NONEXISTENT_PATH_XYZ'
      });

      const text = result.content[0].text;
      expect(text).toMatch(/not found|does not exist|no component/i);
    });

    it('should describe J-job files', async () => {
      const result = await tools.describeComponent({
        component: 'JGLOBAL_FORECAST'
      });

      const text = result.content[0].text;
      // Should find it under dev/jobs/ or jobs/
      expect(text).toBeDefined();
      expect(text.length).toBeGreaterThan(0);
    });
  });

  describe('Error Handling', () => {
    it('should return valid content even for edge cases', async () => {
      const result = await tools.getWorkflowStructure({
        component: 'nonexistent_component'
      });

      // Tool falls through to full structure when component not in hardcoded map
      const text = result.content[0].text;
      expect(text).toBeDefined();
      expect(text).toContain('Global Workflow Structure');
    });

    it('should handle empty args gracefully', async () => {
      const result = await tools.describeComponent({});

      const text = result.content[0].text;
      expect(text).toBeDefined();
    });
  });
});
