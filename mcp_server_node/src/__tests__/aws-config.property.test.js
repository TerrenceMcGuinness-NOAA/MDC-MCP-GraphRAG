/**
 * Property Tests for aws-config.js
 * P11: Secret Non-Exposure
 * P12: Configuration Caching
 */

import { describe, test, expect, beforeEach, vi } from 'vitest';
import fc from 'fast-check';

// We test the module in isolation by mocking AWS SDK clients
vi.mock('@aws-sdk/client-secrets-manager', () => ({
  SecretsManagerClient: vi.fn(),
  GetSecretValueCommand: vi.fn((input) => input),
}));
vi.mock('@aws-sdk/client-ssm', () => ({
  SSMClient: vi.fn(),
  GetParametersCommand: vi.fn((input) => input),
}));

import { SecretsManagerClient } from '@aws-sdk/client-secrets-manager';
import { SSMClient } from '@aws-sdk/client-ssm';

// Helper: load a fresh module instance per test
async function loadFreshModule() {
  // Bust the module cache so _cache resets between tests
  const mod = await import(`../src/config/aws-config.js?t=${Date.now()}`);
  return mod;
}

// ---------------------------------------------------------------------------
// P12: Configuration Caching
// ---------------------------------------------------------------------------
describe('P12: Configuration Caching', () => {
  test('resolveConfig() calls Secrets Manager exactly once for any number of invocations', async () => {
    let smCallCount = 0;
    let ssmCallCount = 0;

    SecretsManagerClient.mockImplementation(() => ({
      send: async () => {
        smCallCount++;
        return { SecretString: JSON.stringify({ username: 'u', password: 'p' }) };
      },
    }));
    SSMClient.mockImplementation(() => ({
      send: async () => {
        ssmCallCount++;
        return {
          Parameters: [
            { Name: '/mdc-mcp-rag/neptune/endpoint', Value: 'neptune.example.com' },
            { Name: '/mdc-mcp-rag/opensearch/endpoint', Value: 'opensearch.example.com' },
            { Name: '/mdc-mcp-rag/db-backend', Value: 'aws' },
          ],
        };
      },
    }));

    await fc.assert(
      fc.asyncProperty(fc.integer({ min: 1, max: 20 }), async (callCount) => {
        const { resolveConfig, _clearCache } = await loadFreshModule();
        _clearCache();
        smCallCount = 0;
        ssmCallCount = 0;

        // Call resolveConfig() callCount times
        for (let i = 0; i < callCount; i++) {
          await resolveConfig();
        }

        // Regardless of callCount, AWS APIs called exactly once each
        expect(smCallCount).toBe(1);
        expect(ssmCallCount).toBe(1);
      }),
      { numRuns: 10 }
    );
  });

  test('cached result is reference-equal across calls', async () => {
    SecretsManagerClient.mockImplementation(() => ({
      send: async () => ({ SecretString: '{"username":"u","password":"p"}' }),
    }));
    SSMClient.mockImplementation(() => ({
      send: async () => ({
        Parameters: [
          { Name: '/mdc-mcp-rag/neptune/endpoint', Value: 'ep' },
          { Name: '/mdc-mcp-rag/opensearch/endpoint', Value: 'ep2' },
          { Name: '/mdc-mcp-rag/db-backend', Value: 'legacy' },
        ],
      }),
    }));

    const { resolveConfig, _clearCache } = await loadFreshModule();
    _clearCache();
    const first = await resolveConfig();
    const second = await resolveConfig();
    expect(first).toBe(second);  // same object reference
  });
});

// ---------------------------------------------------------------------------
// P11: Secret Non-Exposure
// ---------------------------------------------------------------------------
describe('P11: Secret Non-Exposure', () => {
  test('no secret value appears in console.error output', async () => {
    const sensitivePassword = 'SuperSecret_P@ssw0rd_12345';
    const sensitiveToken = 'ghp_ABCDEF1234567890abcdef';

    SecretsManagerClient.mockImplementation(() => ({
      send: async (cmd) => {
        if (cmd.SecretId?.includes('neptune')) {
          return { SecretString: JSON.stringify({ username: 'neptune', password: sensitivePassword }) };
        }
        return { SecretString: sensitiveToken };
      },
    }));
    SSMClient.mockImplementation(() => ({
      send: async () => ({
        Parameters: [
          { Name: '/mdc-mcp-rag/neptune/endpoint', Value: 'neptune.example.com' },
          { Name: '/mdc-mcp-rag/opensearch/endpoint', Value: 'os.example.com' },
          { Name: '/mdc-mcp-rag/db-backend', Value: 'aws' },
        ],
      }),
    }));

    const loggedMessages = [];
    const origError = console.error;
    console.error = (...args) => loggedMessages.push(args.join(' '));

    try {
      const { resolveConfig, _clearCache } = await loadFreshModule();
      _clearCache();
      await resolveConfig();
    } finally {
      console.error = origError;
    }

    for (const msg of loggedMessages) {
      expect(msg).not.toContain(sensitivePassword);
      expect(msg).not.toContain(sensitiveToken);
    }
  });

  test('property: for any secret string, it never appears in log output', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.string({ minLength: 8, maxLength: 32 }),
        async (secretValue) => {
          SecretsManagerClient.mockImplementation(() => ({
            send: async () => ({ SecretString: JSON.stringify({ username: 'u', password: secretValue }) }),
          }));
          SSMClient.mockImplementation(() => ({
            send: async () => ({
              Parameters: [
                { Name: '/mdc-mcp-rag/neptune/endpoint', Value: 'ep' },
                { Name: '/mdc-mcp-rag/opensearch/endpoint', Value: 'ep2' },
                { Name: '/mdc-mcp-rag/db-backend', Value: 'legacy' },
              ],
            }),
          }));

          const logged = [];
          const orig = console.error;
          console.error = (...a) => logged.push(a.join(' '));

          try {
            const { resolveConfig, _clearCache } = await loadFreshModule();
            _clearCache();
            await resolveConfig();
          } finally {
            console.error = orig;
          }

          for (const msg of logged) {
            expect(msg).not.toContain(secretValue);
          }
        }
      ),
      { numRuns: 20 }
    );
  });

  test('env var fallback path also does not log secret values', async () => {
    const sensitiveEnvPassword = 'EnvFallback_Secret_XYZ';
    process.env.NEPTUNE_PASSWORD = sensitiveEnvPassword;

    SecretsManagerClient.mockImplementation(() => ({
      send: async () => { throw Object.assign(new Error('throttled'), { name: 'ThrottlingException' }); },
    }));
    SSMClient.mockImplementation(() => ({
      send: async () => { throw new Error('SSM unavailable'); },
    }));

    const logged = [];
    const orig = console.error;
    console.error = (...a) => logged.push(a.join(' '));

    try {
      const { resolveConfig, _clearCache } = await loadFreshModule();
      _clearCache();
      await resolveConfig();
    } finally {
      console.error = orig;
      delete process.env.NEPTUNE_PASSWORD;
    }

    for (const msg of logged) {
      expect(msg).not.toContain(sensitiveEnvPassword);
    }
  });
});
