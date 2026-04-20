/**
 * Unit Tests for OperationalTools
 * Week 3 Phase 4: Test Suite Development
 * 
 * Tests 3 tools:
 * 1. get_operational_guidance
 * 2. list_job_scripts
 * 3. explain_workflow_component
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import OperationalTools from '../tools/OperationalTools.js';

describe('OperationalTools', () => {
  let tools;
  let mockDataAccess;

  beforeEach(() => {
    mockDataAccess = {
      vectorDb: {
        query: vi.fn()
      },
      graphDb: {
        query: vi.fn()
      },
      hybridQuery: vi.fn()
    };

    tools = new OperationalTools(mockDataAccess);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe('get_operational_guidance', () => {
    it('should return platform-specific operational guidance', async () => {
      mockDataAccess.hybridQuery.mockResolvedValue({
        vectorResults: {
          documents: [['HERA operational procedures: module load...']],
          metadatas: [[{ source: 'operational-guide', platform: 'hera' }]],
          distances: [[0.78]]
        },
        graphContext: {
          relatedComponents: ['SLURM', 'modules', 'rocoto']
        }
      });

      const result = await tools.getOperationalGuidance({
        operation: 'restart failed workflow',
        platform: 'hera',
        urgency: 'urgent'
      });

      expect(mockDataAccess.hybridQuery).toHaveBeenCalledWith(
        expect.stringContaining('restart'),
        expect.objectContaining({ platform: 'hera' })
      );
      expect(result.content[0].text).toContain('HERA');
      expect(result.content[0].text).toContain('module load');
    });

    it('should provide generic guidance when platform not specified', async () => {
      mockDataAccess.hybridQuery.mockResolvedValue({
        vectorResults: {
          documents: [['Generic workflow restart procedure...']],
          metadatas: [[{ source: 'user-guide' }]],
          distances: [[0.82]]
        }
      });

      const result = await tools.getOperationalGuidance({
        operation: 'check workflow status'
      });

      expect(result.content[0].text).toContain('workflow');
    });

    it('should handle emergency urgency level', async () => {
      mockDataAccess.hybridQuery.mockResolvedValue({
        vectorResults: {
          documents: [['EMERGENCY: Kill all processes immediately']],
          metadatas: [[{ urgency: 'emergency' }]],
          distances: [[0.65]]
        }
      });

      const result = await tools.getOperationalGuidance({
        operation: 'emergency shutdown',
        urgency: 'emergency'
      });

      expect(result.content[0].text).toMatch(/EMERGENCY|urgent|immediate/i);
    });
  });

  describe('list_job_scripts', () => {
    it('should list all job scripts by default', async () => {
      mockDataAccess.graphDb.query.mockResolvedValue([
        { name: 'JGLOBAL_FORECAST', path: 'jobs/JGLOBAL_FORECAST', category: 'forecast' },
        { name: 'JGDAS_ANALYSIS', path: 'jobs/JGDAS_ANALYSIS', category: 'analysis' },
        { name: 'JGLOBAL_ARCHIVE', path: 'jobs/JGLOBAL_ARCHIVE', category: 'archive' }
      ]);

      const result = await tools.listJobScripts({
        category: 'all',
        format: 'summary'
      });

      expect(result.content[0].text).toContain('JGLOBAL_FORECAST');
      expect(result.content[0].text).toContain('JGDAS_ANALYSIS');
      expect(result.content[0].text).toContain('JGLOBAL_ARCHIVE');
    });

    it('should filter by category', async () => {
      mockDataAccess.graphDb.query.mockResolvedValue([
        { name: 'JGLOBAL_FORECAST', path: 'jobs/JGLOBAL_FORECAST', category: 'forecast' },
        { name: 'JGFS_FORECAST', path: 'jobs/JGFS_FORECAST', category: 'forecast' }
      ]);

      const result = await tools.listJobScripts({
        category: 'forecast',
        format: 'detailed'
      });

      expect(result.content[0].text).toContain('forecast');
      expect(result.content[0].text).not.toContain('analysis');
    });

    it('should provide detailed format with dependencies', async () => {
      mockDataAccess.graphDb.query.mockResolvedValue([
        {
          name: 'JGLOBAL_FORECAST',
          path: 'jobs/JGLOBAL_FORECAST',
          category: 'forecast',
          dependencies: ['JGDAS_ANALYSIS', 'JGLOBAL_PREP'],
          description: 'Run GFS forecast model'
        }
      ]);

      const result = await tools.listJobScripts({
        category: 'forecast',
        format: 'detailed'
      });

      expect(result.content[0].text).toContain('dependencies');
      expect(result.content[0].text).toContain('JGDAS_ANALYSIS');
    });
  });

  describe('explain_workflow_component', () => {
    it('should explain component with hybrid vector+graph context', async () => {
      mockDataAccess.hybridQuery.mockResolvedValue({
        vectorResults: {
          documents: [['JGLOBAL_FORECAST runs the GFS model...']],
          metadatas: [[{ source: 'job-docs', type: 'job' }]],
          distances: [[0.72]]
        },
        graphContext: {
          file: { path: 'jobs/JGLOBAL_FORECAST', language: 'bash' },
          calls: ['exglobal_forecast.py', 'setup_environment.sh'],
          dependencies: ['JGDAS_ANALYSIS']
        }
      });

      const result = await tools.explainWorkflowComponent({
        component: 'JGLOBAL_FORECAST',
        detailLevel: 'detailed'
      });

      expect(mockDataAccess.hybridQuery).toHaveBeenCalledWith(
        expect.stringContaining('JGLOBAL_FORECAST'),
        expect.any(Object)
      );
      expect(result.content[0].text).toContain('JGLOBAL_FORECAST');
      expect(result.content[0].text).toContain('exglobal_forecast.py');
    });

    it('should provide basic explanation for simple request', async () => {
      mockDataAccess.hybridQuery.mockResolvedValue({
        vectorResults: {
          documents: [['Configuration file for forecast parameters']],
          metadatas: [[{ source: 'config', type: 'yaml' }]],
          distances: [[0.88]]
        }
      });

      const result = await tools.explainWorkflowComponent({
        component: 'config/forecast.yaml',
        detailLevel: 'basic'
      });

      expect(result.content[0].text).toContain('config');
    });

    it('should provide expert-level detail with code examples', async () => {
      mockDataAccess.hybridQuery.mockResolvedValue({
        vectorResults: {
          documents: [['Advanced GSI configuration...', 'Code example: set GSI_MODE=regional']],
          metadatas: [[{ source: 'gsi-guide', level: 'expert' }]],
          distances: [[0.65]]
        },
        graphContext: {
          codeSnippets: ['export GSI_MODE=regional', 'export GSI_FIX=${HOMEgsi}/fix']
        }
      });

      const result = await tools.explainWorkflowComponent({
        component: 'GSI',
        detailLevel: 'expert'
      });

      expect(result.content[0].text).toContain('GSI');
      expect(result.content[0].text).toContain('export');
    });
  });

  describe('Error Handling', () => {
    it('should handle database connection errors', async () => {
      mockDataAccess.hybridQuery.mockRejectedValue(new Error('ChromaDB connection failed'));

      const result = await tools.getOperationalGuidance({
        operation: 'test'
      });

      expect(result.content[0].text).toContain('error');
    });

    it('should handle missing components gracefully', async () => {
      mockDataAccess.hybridQuery.mockResolvedValue({
        vectorResults: { documents: [[]], metadatas: [[]], distances: [[]] },
        graphContext: null
      });

      const result = await tools.explainWorkflowComponent({
        component: 'NONEXISTENT_COMPONENT'
      });

      expect(result.content[0].text).toMatch(/not found|no information|missing|no documentation/i);
    });
  });

  describe('explainWorkflowComponent (Phase 51 — J-job + flat-array contract)', () => {
    beforeEach(() => {
      // Phase 51 contract: multiSourceSearch returns a FLAT array of vector
      // results; graph hits come from a direct graphDb.query call.
      mockDataAccess.multiSourceSearch = vi.fn();
      mockDataAccess.graphDb.findFileImports = vi.fn().mockResolvedValue([]);
    });

    it('should populate Documentation + Code Structure for a J-job lookup', async () => {
      mockDataAccess.multiSourceSearch.mockResolvedValue([
        { document: 'JGLOBAL_FORECAST runs the GFS forecast model.', metadata: { source: 'jjobs' } }
      ]);
      mockDataAccess.graphDb.query.mockResolvedValue([
        { name: 'JGLOBAL_FORECAST', type: 'JJob', path: 'jobs/JGLOBAL_FORECAST', language: 'shell' }
      ]);

      const result = await tools.explainWorkflowComponent({ component: 'JGLOBAL_FORECAST' });
      const text = result.content[0].text;

      expect(mockDataAccess.multiSourceSearch).toHaveBeenCalledWith(
        'JGLOBAL_FORECAST',
        expect.objectContaining({ enrichWithGraph: true })
      );
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

    it('should emit hint guidance instead of just the heading when both arms are empty', async () => {
      mockDataAccess.multiSourceSearch.mockResolvedValue([]);
      mockDataAccess.graphDb.query.mockResolvedValue([]);

      const result = await tools.explainWorkflowComponent({ component: 'JTOTALLY_FAKE' });
      const text = result.content[0].text;

      expect(text).toMatch(/No documentation or graph nodes matched/);
      expect(text).toMatch(/JGLOBAL_FORECAST/);
    });
  });
});
