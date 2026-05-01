/**
 * Phase 53 D6 regression test for EE2ComplianceTools.scanRepositoryCompliance
 *
 * Defect: callers passing `files=[{name, content}]` got a "Repository not
 * found: undefined" error because the old code dereferenced `repository_path`
 * before checking the in-memory `files` argument.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import EE2ComplianceTools from '../tools/EE2ComplianceTools.js';

describe('EE2ComplianceTools.scanRepositoryCompliance (Phase 53 D6)', () => {
  let tools;

  beforeEach(() => {
    const mockDataAccess = {
      vectorDB: { query: vi.fn().mockResolvedValue([]) },
      graphDB: { query: vi.fn().mockResolvedValue([]) }
    };
    tools = new EE2ComplianceTools(mockDataAccess);
    tools.ensureInitialized = vi.fn().mockResolvedValue();
  });

  it('accepts files=[] without a repository_path and returns scan results', async () => {
    const files = [
      {
        name: 'exglobal_forecast.sh',
        path: 'scripts/exglobal_forecast.sh',
        content: '#!/bin/bash\nset -x\necho "FATAL ERROR: missing input"\nerr_exit 1\n'
      },
      {
        name: 'badscript.sh',
        path: 'ush/badscript.sh',
        content: '\n#!/bin/bash\necho "error happened"\nexit 1\n'  // shebang on line 2 — violation
      }
    ];

    const result = await tools.scanRepositoryCompliance({
      files,
      categories: ['error_handling', 'file_naming']
    });

    expect(result.isError).not.toBe(true);
    const text = result.content[0].text;
    // Must not be the old "Repository not found" failure mode
    expect(text).not.toMatch(/Repository not found/);
    // Must reference the in-memory mode marker we added
    expect(text).toContain('(in-memory files)');
  });

  it('still surfaces "Repository not found" when path mode is used with a bad path', async () => {
    const result = await tools.scanRepositoryCompliance({
      repository_path: '/no/such/path/at/all/xyz',
      categories: ['error_handling']
    });
    expect(result.isError).toBe(true);
    expect(result.content[0].text).toMatch(/Repository not found/);
  });
});
