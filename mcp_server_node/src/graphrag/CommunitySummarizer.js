#!/usr/bin/env node

/**
 * CommunitySummarizer.js - Template-Based Community Summary Generation
 *
 * Generates structured natural language summaries for each Leiden community
 * using node metadata (names, types, relationships). Summaries are stored
 * in a ChromaDB collection for semantic retrieval by the query router.
 *
 * Architecture: The MCP server is passive (no direct LLM calls). These
 * template-based summaries provide rich semantic context that LLM clients
 * can search via ChromaDB. A future enhancement could use an LLM endpoint
 * to generate richer narrative summaries.
 *
 * @version 1.0.0
 * @phase Phase 24E-2
 * @author Terry McGuinness + AI Assistants
 * @date 2026-02-09
 */

const COLLECTION_NAME = 'community-summaries';
const MIN_COMMUNITY_SIZE = 3;

// Language detection from node labels
const LANGUAGE_MAP = {
  FortranSubroutine: 'Fortran',
  FortranFunction: 'Fortran',
  FortranModule: 'Fortran',
  FortranProgram: 'Fortran',
  PythonModule: 'Python',
  PythonFunction: 'Python',
  PythonClass: 'Python',
  File: 'Shell',
  CodeFile: 'Shell'
};

class CommunitySummarizer {

  /**
   * @param {object} opts
   * @param {object} opts.communityDetection - CommunityDetection instance
   * @param {object} opts.vectorDB - VectorDatabase instance
   */
  constructor({ communityDetection, vectorDB }) {
    this.cd = communityDetection;
    this.vectorDB = vectorDB;
  }

  /**
   * Generate a structured summary for a single community.
   * @param {number} communityId
   * @param {Array} members - [{name, label, communityId}]
   * @param {Array} [relationships] - [{source, rel, target}]
   * @returns {string} Natural language summary
   */
  generateSummary(communityId, members, relationships = []) {
    const typeBreakdown = {};
    const languages = new Set();
    const namesByType = {};

    for (const m of members) {
      const label = m.label || 'Unknown';
      typeBreakdown[label] = (typeBreakdown[label] || 0) + 1;
      languages.add(LANGUAGE_MAP[label] || 'Unknown');

      if (!namesByType[label]) namesByType[label] = [];
      if (namesByType[label].length < 15) {
        namesByType[label].push(m.name);
      }
    }

    const langList = [...languages].filter(l => l !== 'Unknown').join(', ') || 'Mixed';
    const size = members.length;

    // Build summary sections
    const parts = [];

    // Header
    parts.push(`Community ${communityId}: ${size} nodes (${langList})`);

    // Type breakdown
    const typeStr = Object.entries(typeBreakdown)
      .sort((a, b) => b[1] - a[1])
      .map(([t, c]) => `${c} ${t}`)
      .join(', ');
    parts.push(`Composition: ${typeStr}`);

    // Key members by type
    for (const [type, names] of Object.entries(namesByType)) {
      const displayNames = names.slice(0, 10).join(', ');
      const suffix = names.length >= 15 ? ` (and more)` : '';
      parts.push(`${type}: ${displayNames}${suffix}`);
    }

    // Infer purpose from member names
    const purpose = this._inferPurpose(members, relationships);
    if (purpose) {
      parts.push(`Likely purpose: ${purpose}`);
    }

    // Relationship patterns
    if (relationships.length > 0) {
      const relTypes = {};
      for (const r of relationships) {
        relTypes[r.rel] = (relTypes[r.rel] || 0) + 1;
      }
      const relStr = Object.entries(relTypes)
        .sort((a, b) => b[1] - a[1])
        .map(([t, c]) => `${c} ${t}`)
        .join(', ');
      parts.push(`Internal relationships: ${relStr}`);
    }

    return parts.join('. ');
  }

  /**
   * Generate and store summaries for all communities above minSize.
   * @param {object} opts
   * @param {number} [opts.minSize=3]
   * @param {number} [opts.maxCommunities=500]
   * @param {number} [opts.batchSize=50]
   * @returns {Promise<{generated: number, stored: number, elapsedMs: number}>}
   */
  async summarizeAll({ minSize = MIN_COMMUNITY_SIZE, maxCommunities = 500, batchSize = 50 } = {}) {
    const startTime = Date.now();
    console.log(`[INFO] Phase 24E-2: Generating community summaries (minSize=${minSize})...`);

    // Get all communities above threshold
    const communities = await this.cd.getLargestCommunities(minSize, maxCommunities);
    console.log(`[OK] Found ${communities.length} communities with ${minSize}+ members`);

    const documents = [];

    for (let i = 0; i < communities.length; i++) {
      const c = communities[i];

      // Get internal relationships for richer summaries
      let rels = [];
      try {
        rels = await this.cd.getCommunityRelationships(c.communityId, 50);
      } catch {
        // Non-fatal
      }

      const summary = this.generateSummary(c.communityId, c.members, rels);

      // Determine dominant language
      const langCounts = {};
      for (const m of c.members) {
        const lang = LANGUAGE_MAP[m.label] || 'Unknown';
        langCounts[lang] = (langCounts[lang] || 0) + 1;
      }
      const dominantLang = Object.entries(langCounts).sort((a, b) => b[1] - a[1])[0]?.[0] || 'Mixed';

      documents.push({
        id: `community-${c.communityId}`,
        text: summary,
        metadata: {
          communityId: c.communityId,
          size: c.size,
          language: dominantLang,
          nodeTypes: Object.keys(c.typeBreakdown).join(','),
          level: 'leaf',
          generatedAt: new Date().toISOString()
        }
      });

      if ((i + 1) % 100 === 0) {
        console.log(`[INFO] Processed ${i + 1}/${communities.length} communities...`);
      }
    }

    // Store in ChromaDB in batches
    console.log(`[INFO] Storing ${documents.length} summaries in ChromaDB collection '${COLLECTION_NAME}'...`);

    if (!this.vectorDB.connected) {
      await this.vectorDB.connect();
    }
    await this.vectorDB.getOrCreateCollection(COLLECTION_NAME, {
      description: 'Hierarchical community summaries from Leiden detection (Phase 24E)'
    });

    for (let i = 0; i < documents.length; i += batchSize) {
      const batch = documents.slice(i, i + batchSize);
      await this.vectorDB.addDocuments(COLLECTION_NAME, batch);
    }

    const elapsed = Date.now() - startTime;
    console.log(`[OK] Phase 24E-2 complete: ${documents.length} summaries stored in ${elapsed}ms`);

    return {
      generated: documents.length,
      stored: documents.length,
      elapsedMs: elapsed
    };
  }

  /**
   * Search community summaries for a query.
   * @param {string} queryText
   * @param {number} [nResults=5]
   * @returns {Promise<Array>}
   */
  async searchSummaries(queryText, nResults = 5) {
    const results = await this.vectorDB.query(COLLECTION_NAME, queryText, {
      nResults,
      include: ['documents', 'metadatas', 'distances']
    });
    return results;
  }

  /**
   * Infer the likely purpose of a community from member names.
   * Uses keyword pattern matching on subroutine/function names.
   */
  _inferPurpose(members, relationships) {
    const allNames = members.map(m => (m.name || '').toLowerCase()).join(' ');

    const patterns = [
      { keywords: ['gsi', 'radiance', 'satellite', 'obs', 'bias'], purpose: 'Data assimilation / observation processing' },
      { keywords: ['enkf', 'ensemble', 'kalman'], purpose: 'Ensemble Kalman filter analysis' },
      { keywords: ['forecast', 'fv3', 'dycore', 'dynamics', 'atmos'], purpose: 'Atmospheric forecast / dynamics' },
      { keywords: ['ocean', 'mom6', 'ice', 'cice', 'wave'], purpose: 'Ocean / sea ice / wave modeling' },
      { keywords: ['post', 'grib', 'product', 'upp', 'bufr'], purpose: 'Post-processing / product generation' },
      { keywords: ['io', 'read', 'write', 'netcdf', 'hdf5'], purpose: 'I/O / file operations' },
      { keywords: ['mpi', 'comm', 'parallel', 'scatter', 'gather'], purpose: 'MPI communication / parallelism' },
      { keywords: ['grid', 'interpolat', 'regrid', 'transform'], purpose: 'Grid operations / interpolation' },
      { keywords: ['physics', 'radiation', 'convect', 'turb', 'cloud', 'pbl'], purpose: 'Physical parameterization' },
      { keywords: ['land', 'soil', 'noah', 'surface', 'lsm'], purpose: 'Land surface model' },
      { keywords: ['chem', 'aerosol', 'ozone', 'tracer'], purpose: 'Chemistry / aerosol / tracer transport' },
      { keywords: ['test', 'check', 'verify', 'assert', 'valid'], purpose: 'Testing / validation' },
      { keywords: ['config', 'setup', 'init', 'param', 'namelist'], purpose: 'Configuration / initialization' },
      { keywords: ['diag', 'monitor', 'log', 'stat', 'metric'], purpose: 'Diagnostics / monitoring' },
      { keywords: ['workflow', 'task', 'job', 'rocoto', 'ecflow'], purpose: 'Workflow orchestration' },
      { keywords: ['python', 'pygfs', 'pygw', 'wxflow'], purpose: 'Python workflow automation' },
    ];

    const matches = [];
    for (const p of patterns) {
      const hits = p.keywords.filter(k => allNames.includes(k));
      if (hits.length >= 2) {
        matches.push({ purpose: p.purpose, confidence: hits.length });
      }
    }

    if (matches.length === 0) return null;
    matches.sort((a, b) => b.confidence - a.confidence);
    return matches[0].purpose;
  }
}

export default CommunitySummarizer;
