/**
 * Unit Tests for OperationalTools
 * Updated: Phase 52 — aligned with flat-array hybridQuery / multiSourceSearch API
 *
 * Tests 4 tools:
 * 1. get_operational_guidance (uses dataAccess.hybridQuery → flat array)
 * 2. list_job_scripts (filesystem-based, uses job_list param for unit test)
 * 3. explain_workflow_component (uses multiSourceSearch + graphDb.query)
 * 4. get_job_details (uses multiSourceSearch + graphDb.query)
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import OperationalTools from '../tools/OperationalTools.js';

describe('OperationalTools', () => {
  let tools;
  let mockDataAccess;

  beforeEach(() => {
    mockDataAccess = {
      vectorDB: {
        query: vi.fn().mockResolvedValue([])
      },
      graphDb: {
        query: vi.fn().mockResolvedValue([]),
        findFileImports: vi.fn().mockResolvedValue([])
      },
      graphDB: {
        query: vi.fn().mockResolvedValue([]),
        findFileImports: vi.fn().mockResolvedValue([])
      },
      hybridQuery: vi.fn().mockResolvedValue([]),
      multiSourceSearch: vi.fn().mockResolvedValue([]),
      getStatistics: vi.fn().mockResolvedValue({})
    };

    tools = new OperationalTools(mockDataAccess);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe('get_operational_guidance', () => {
    it('should return platform-specific operational guidance', async () => {
      // hybridQuery now returns a flat array of result objects
      mockDataAccess.hybridQuery.mockResolvedValue([
        {
          document: 'HERA operational procedures: module load intel...',
          metadata: { source: 'operational-guide', platform: 'hera' },
          distance: 0.78
        }
      ]);

      const result = await tools.getOperationalGuidance({
        operation: 'restart failed workflow',
        platform: 'hera',
        urgency: 'urgent'
      });

      expect(mockDataAccess.hybridQuery).toHaveBeenCalled();
      const text = result.content[0].text;
      expect(text).toContain('HERA');
      expect(text).toContain('module load');
    });

    it('should provide generic guidance when platform not specified', async () => {
      mockDataAccess.hybridQuery.mockResolvedValue([]);

      const result = await tools.getOperationalGuidance({
        operation: 'check workflow status'
      });

      const text = result.content[0].text;
      // Falls through to general guidance block
      expect(text).toContain('workflow');
      expect(text).toContain('General Guidance');
    });

    it('should handle emergency urgency level', async () => {
      mockDataAccess.hybridQuery.mockResolvedValue([]);

      const result = await tools.getOperationalGuidance({
        operation: 'emergency shutdown',
        urgency: 'emergency'
      });

      const text = result.content[0].text;
      expect(text).toContain('EMERGENCY');
    });

    it('should handle database connection errors', async () => {
      mockDataAccess.hybridQuery.mockRejectedValue(new Error('ChromaDB connection failed'));

      const result = await tools.getOperationalGuidance({
        operation: 'test'
      });

      expect(result.content[0].text).toMatch(/error/i);
      expect(result.content[0].text).toContain('ChromaDB connection failed');
    });
  });

  describe('list_job_scripts', () => {
    it('should list all job scripts from job_list parameter', async () => {
      const result = await tools.listJobScripts({
        job_list: ['JGLOBAL_FORECAST', 'JGDAS_ANALYSIS', 'JGLOBAL_ARCHIVE'],
        category: 'all',
        format: 'summary'
      });

      const text = result.content[0].text;
      expect(text).toContain('JGLOBAL_FORECAST');
      expect(text).toContain('JGDAS_ANALYSIS');
      expect(text).toContain('JGLOBAL_ARCHIVE');
    });

    it('should filter by category', async () => {
      const result = await tools.listJobScripts({
        job_list: ['JGLOBAL_FORECAST', 'JGFS_FORECAST', 'JGDAS_ANALYSIS'],
        category: 'forecast',
        format: 'summary'
      });

      const text = result.content[0].text;
      expect(text).toContain('forecast');
      expect(text).toContain('JGLOBAL_FORECAST');
    });

    it('should support json format', async () => {
      const result = await tools.listJobScripts({
        job_list: ['JGLOBAL_FORECAST'],
        format: 'json'
      });

      const parsed = JSON.parse(result.content[0].text);
      expect(parsed.jobs).toContain('JGLOBAL_FORECAST');
    });

    it('should filter by search term', async () => {
      const result = await tools.listJobScripts({
        job_list: ['JGLOBAL_FORECAST', 'JGDAS_ANALYSIS', 'JGLOBAL_ARCHIVE'],
        search: 'GLOBAL',
        format: 'summary'
      });

      const text = result.content[0].text;
      expect(text).toContain('JGLOBAL_FORECAST');
      expect(text).toContain('JGLOBAL_ARCHIVE');
      expect(text).not.toContain('JGDAS_ANALYSIS');
    });
  });

  describe('explain_workflow_component', () => {
    it('should explain component with multiSourceSearch + graph', async () => {
      mockDataAccess.multiSourceSearch.mockResolvedValue([
        { document: 'JGLOBAL_FORECAST runs the GFS forecast model.', metadata: { source: 'jjobs' } }
      ]);
      mockDataAccess.graphDb.query.mockResolvedValue([
        { name: 'JGLOBAL_FORECAST', type: 'JJob', path: 'jobs/JGLOBAL_FORECAST', language: 'shell' }
      ]);

      const result = await tools.explainWorkflowComponent({
        component: 'JGLOBAL_FORECAST'
      });

      expect(mockDataAccess.multiSourceSearch).toHaveBeenCalledWith(
        'JGLOBAL_FORECAST',
        expect.objectContaining({ enrichWithGraph: true })
      );
      const text = result.content[0].text;
      expect(text).toContain('## Documentation');
      expect(text).toContain('runs the GFS forecast model');
      expect(text).toContain('## Code Structure');
      expect(text).toContain('JGLOBAL_FORECAST');
      expect(text).toContain('jobs/JGLOBAL_FORECAST');
    });

    it('should include :JJob / :Script labels in graph cypher when name is J-job-like', async () => {
      mockDataAccess.multiSourceSearch.mockResolvedValue([]);
      mockDataAccess.graphDb.query.mockResolvedValue([]);

      await tools.explainWorkflowComponent({ component: 'JGDAS_ENKF_SELECT_OBS' });

      const cypherArg = mockDataAccess.graphDb.query.mock.calls[0][0];
      expect(cypherArg).toMatch(/n:JJob/);
      expect(cypherArg).toMatch(/n:Script/);
    });

    it('should emit hint guidance when both arms are empty', async () => {
      mockDataAccess.multiSourceSearch.mockResolvedValue([]);
      mockDataAccess.graphDb.query.mockResolvedValue([]);

      const result = await tools.explainWorkflowComponent({ component: 'JTOTALLY_FAKE' });
      const text = result.content[0].text;

      expect(text).toMatch(/No documentation or graph nodes matched/);
      expect(text).toMatch(/JGLOBAL_FORECAST/);
    });

    it('should provide expert-level detail', async () => {
      mockDataAccess.multiSourceSearch.mockResolvedValue([
        { document: 'GSI configuration docs', metadata: {} }
      ]);
      mockDataAccess.graphDb.query.mockResolvedValue([]);

      const result = await tools.explainWorkflowComponent({
        component: 'GSI',
        detail_level: 'expert'
      });

      const text = result.content[0].text;
      expect(text).toContain('Expert Notes');
      expect(text).toContain('GSI');
    });

    it('should handle errors gracefully', async () => {
      mockDataAccess.multiSourceSearch.mockRejectedValue(new Error('timeout'));

      const result = await tools.explainWorkflowComponent({
        component: 'test'
      });

      expect(result.content[0].text).toMatch(/error/i);
    });

    it('Phase 53 D8: renders Job Definition section when graph hits a JJob', async () => {
      // Graph arm returns a J-Job hit; vector arm returns nothing useful.
      mockDataAccess.multiSourceSearch.mockResolvedValue([]);
      mockDataAccess.graphDb.query.mockResolvedValue([
        { name: 'JGLOBAL_FORECAST', type: 'JJob', path: 'jobs/JGLOBAL_FORECAST', language: 'shell' }
      ]);
      mockDataAccess.graphDB.query.mockResolvedValue([
        { name: 'JGLOBAL_FORECAST', type: 'JJob', path: 'jobs/JGLOBAL_FORECAST', language: 'shell' }
      ]);
      // getJobDetails internally calls fs.readFile — short-circuit it via spy.
      const getJobDetailsSpy = vi.spyOn(tools, 'getJobDetails').mockResolvedValue({
        content: [{
          type: 'text',
          text: '## Sourced Scripts\n- exglobal_forecast.sh\n## Inputs\n- ICs\n## Outputs\n- forecast files\n'
        }]
      });

      const result = await tools.explainWorkflowComponent({ component: 'JGLOBAL_FORECAST' });
      const text = result.content[0].text;

      expect(getJobDetailsSpy).toHaveBeenCalled();
      expect(text).toContain('Job Definition');
      expect(text).toMatch(/Sourced Scripts|Inputs/);
    });
  });

  describe('Phase 53 D9: get_operational_guidance topic alias', () => {
    it('accepts `topic` as canonical parameter', async () => {
      mockDataAccess.hybridQuery.mockResolvedValue([
        { document: 'Restart procedure', metadata: { source: 'ops' }, distance: 0.5 }
      ]);

      const result = await tools.getOperationalGuidance({
        topic: 'restart failed workflow',
        platform: 'hera'
      });

      expect(result.isError).not.toBe(true);
      expect(result.content[0].text).toMatch(/restart|hera/i);
    });

    it('accepts `operation` as backward-compatible alias', async () => {
      mockDataAccess.hybridQuery.mockResolvedValue([
        { document: 'Restart procedure', metadata: { source: 'ops' }, distance: 0.5 }
      ]);

      const result = await tools.getOperationalGuidance({
        operation: 'restart failed workflow',
        platform: 'hera'
      });

      expect(result.isError).not.toBe(true);
      expect(result.content[0].text).toMatch(/restart|hera/i);
    });

    it('returns an error when neither parameter is supplied', async () => {
      const result = await tools.getOperationalGuidance({ platform: 'hera' });
      expect(result.isError).toBe(true);
      expect(result.content[0].text).toMatch(/topic|operation/);
    });
  });
});
