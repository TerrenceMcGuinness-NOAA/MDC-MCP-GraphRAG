/**
 * create-opensearch-indices.test.js
 *
 * Spec: .kiro/specs/v17-knn-vector-reindex/
 *
 * Unit + preservation tests for the `--prefix` flag added to
 * create-opensearch-indices.js.
 *
 * Property 2 (Preservation): without `--prefix`, generated index names and
 * the knn_vector mapping body are byte-identical to the pre-fix behaviour.
 * Property 3 (Mapping): every created index uses the knn_vector mapping
 * regardless of prefix.
 *
 * No live OpenSearch — `ensureIndices` takes an injected mock client.
 */

import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import {
  parseModel,
  parsePrefix,
  resolveModels,
  buildIndexName,
  indexBody,
  ensureIndices,
  BASE_INDICES,
  MODEL_PROFILES,
} from '../scripts/create-opensearch-indices.js';

// ── mock client ──────────────────────────────────────────────────────────────

function mockClient({ existing = new Set() } = {}) {
  const created = [];
  return {
    created,
    indices: {
      exists: async ({ index }) => ({ body: existing.has(index) }),
      create: async ({ index, body }) => {
        created.push({ index, body });
        return { body: { acknowledged: true } };
      },
    },
  };
}

// ── parsePrefix / parseModel ──────────────────────────────────────────────────

describe('parsePrefix', () => {
  it('returns empty string when --prefix is absent', () => {
    expect(parsePrefix(['--model', 'titan1024'])).toBe('');
  });
  it('returns the value when --prefix is present', () => {
    expect(parsePrefix(['--prefix', 'gw_v17_', '--model', 'titan1024'])).toBe('gw_v17_');
  });
  it('returns empty string when --prefix has no following value', () => {
    expect(parsePrefix(['--model', 'titan1024', '--prefix'])).toBe('');
  });
});

describe('parseModel', () => {
  it('defaults to mpnet768', () => {
    expect(parseModel([])).toBe('mpnet768');
  });
  it('reads the provided model', () => {
    expect(parseModel(['--model', 'titan1024'])).toBe('titan1024');
  });
});

// ── buildIndexName ──────────────────────────────────────────────────────────

describe('buildIndexName', () => {
  it('produces unprefixed names when prefix is empty (backward compat)', () => {
    expect(buildIndexName('', 'mdc-code-context', 'titan1024'))
      .toBe('mdc-code-context-titan1024');
  });
  it('prepends the prefix when provided', () => {
    expect(buildIndexName('gw_v17_', 'mdc-code-context', 'titan1024'))
      .toBe('gw_v17_mdc-code-context-titan1024');
  });

  it('PBT: name is always `${prefix}${base}-${model}`', () => {
    const prefixArb = fc.stringMatching(/^[A-Za-z0-9_]{0,20}$/);
    fc.assert(
      fc.property(
        prefixArb,
        fc.constantFrom(...BASE_INDICES),
        fc.constantFrom(...Object.keys(MODEL_PROFILES)),
        (prefix, base, model) => {
          expect(buildIndexName(prefix, base, model)).toBe(`${prefix}${base}-${model}`);
        },
      ),
    );
  });
});

// ── indexBody: always knn_vector regardless of prefix ─────────────────────────

describe('indexBody', () => {
  it('always maps embedding as knn_vector with HNSW/nmslib/cosinesimil', () => {
    for (const { dimensions } of Object.values(MODEL_PROFILES)) {
      const emb = indexBody(dimensions).mappings.properties.embedding;
      expect(emb.type).toBe('knn_vector');
      expect(emb.dimension).toBe(dimensions);
      expect(emb.method.name).toBe('hnsw');
      expect(emb.method.engine).toBe('nmslib');
      expect(emb.method.space_type).toBe('cosinesimil');
    }
  });

  it('PBT: body is independent of any prefix value (prefix never reaches mapping)', () => {
    const ref = JSON.stringify(indexBody(1024));
    fc.assert(
      fc.property(fc.stringMatching(/^[A-Za-z0-9_]{0,20}$/), () => {
        // indexBody takes only dimensions — prefix cannot alter the mapping.
        expect(JSON.stringify(indexBody(1024))).toBe(ref);
      }),
    );
  });
});

// ── ensureIndices: prefix wiring + idempotency + knn_vector ───────────────────

describe('ensureIndices', () => {
  it('creates prefixed index names when prefix is provided', async () => {
    const client = mockClient();
    const res = await ensureIndices(client, { models: ['titan1024'], prefix: 'gw_v17_' });

    expect(res).toEqual({ created: BASE_INDICES.length, skipped: 0, errors: 0 });
    const names = client.created.map(c => c.index);
    expect(names).toContain('gw_v17_mdc-code-context-titan1024');
    expect(names).toContain('gw_v17_mdc-workflow-docs-titan1024');
    expect(names).toContain('gw_v17_mdc-jjobs-titan1024');
    // Every created index carries the knn_vector mapping (Property 3).
    for (const { body } of client.created) {
      expect(body.mappings.properties.embedding.type).toBe('knn_vector');
      expect(body.mappings.properties.embedding.dimension).toBe(1024);
    }
  });

  it('PRESERVATION: produces unprefixed names when no prefix is given', async () => {
    const client = mockClient();
    const res = await ensureIndices(client, { models: ['titan1024'], prefix: '' });

    expect(res.created).toBe(BASE_INDICES.length);
    const names = client.created.map(c => c.index).sort();
    expect(names).toEqual(
      BASE_INDICES.map(b => `${b}-titan1024`).sort(),
    );
    // No name carries a tenant prefix.
    expect(names.every(n => n.startsWith('mdc-'))).toBe(true);
  });

  it('PRESERVATION: defaults prefix to empty when omitted entirely', async () => {
    const client = mockClient();
    await ensureIndices(client, { models: ['titan1024'] });
    expect(client.created.map(c => c.index)).toContain('mdc-code-context-titan1024');
  });

  it('is idempotent — skips indices that already exist, creates none', async () => {
    const existing = new Set(
      BASE_INDICES.map(b => `gw_v17_${b}-titan1024`),
    );
    const client = mockClient({ existing });
    const res = await ensureIndices(client, { models: ['titan1024'], prefix: 'gw_v17_' });
    expect(res).toEqual({ created: 0, skipped: BASE_INDICES.length, errors: 0 });
    expect(client.created).toHaveLength(0);
  });
});

// ── resolveModels sanity (unchanged behaviour) ────────────────────────────────

describe('resolveModels', () => {
  it("expands 'all' to every profile", () => {
    expect(resolveModels('all').sort()).toEqual(Object.keys(MODEL_PROFILES).sort());
  });
  it('returns a single-element list for a known model', () => {
    expect(resolveModels('titan1024')).toEqual(['titan1024']);
  });
});
