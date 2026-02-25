#!/usr/bin/env node

/**
 * export_community_contexts.js - Phase 24E-6 Step 1
 *
 * Exports community context from Neo4j into a JSON file suitable for
 * LLM summarization. For each non-singleton community at each level,
 * extracts: members, internal relationships, external relationships,
 * child summaries (for L1+), and metadata.
 *
 * Usage:
 *   node scripts/export_community_contexts.js
 *   node scripts/export_community_contexts.js --output data/community_contexts.json
 *
 * Output: data/community_contexts.json
 *
 * @phase Phase 24E-6
 * @author Terry McGuinness + AI Assistants
 * @date 2026-02-25
 */

import { GraphDatabase } from '../src/data/GraphDatabase.js';
import CommunityDetection from '../src/graphrag/CommunityDetection.js';
import { writeFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const DEFAULT_OUTPUT = resolve(__dirname, '..', 'data', 'community_contexts.json');

const outputPath = process.argv.includes('--output')
  ? resolve(process.argv[process.argv.indexOf('--output') + 1])
  : DEFAULT_OUTPUT;

async function main() {
  console.log('============================================================');
  console.log('Phase 24E-6 Step 1: Export Community Contexts');
  console.log('============================================================');

  const graphDB = new GraphDatabase();
  const startTime = Date.now();

  try {
    await graphDB.connect();
    console.log('[OK] Connected to Neo4j');

    const cd = new CommunityDetection(graphDB);
    const maxLevel = await cd.getMaxCommunityLevel();
    console.log(`[INFO] Max community level: ${maxLevel}`);

    const contexts = [];
    let totalExported = 0;

    for (let level = 0; level <= maxLevel; level++) {
      const minSize = level === 0 ? 3 : 1;
      const communities = await cd.getCommunitiesAtLevel(level, minSize);
      console.log(`[INFO] Level ${level}: ${communities.length} communities`);

      for (const c of communities) {
        const context = {
          communityId: c.communityId,
          level: c.level,
          memberCount: c.memberCount,
          name: c.name,
          languages: c.languages,
          keyMembers: c.keyMembers,
          members: [],
          internalRelationships: [],
          externalRelationships: [],
          childSummaries: [],
          childCommunityIds: []
        };

        // Get members (names, types, paths)
        try {
          const members = await cd.getCommunityMembers(c.communityId, 200);
          context.members = members.map(m => ({
            name: m.name,
            type: m.label
          }));
        } catch (e) {
          console.error(`[WARN] Members failed for L${level}-${c.communityId}: ${e.message}`);
        }

        // Get internal relationships
        try {
          const rels = await cd.getCommunityRelationships(c.communityId, 100);
          context.internalRelationships = rels.map(r => ({
            source: r.source,
            rel: r.rel,
            target: r.target
          }));
        } catch { /* non-fatal */ }

        // Get external relationships (cross-community edges)
        try {
          const extResult = await graphDB.query(`
            MATCH (a)-[r]->(b)
            WHERE a.communityId = $cid
              AND b.communityId IS NOT NULL
              AND b.communityId <> $cid
              AND NOT a:Community AND NOT b:Community
            RETURN coalesce(a.name, a.file_path, 'unnamed') AS source,
                   type(r) AS rel,
                   coalesce(b.name, b.file_path, 'unnamed') AS target,
                   b.communityId AS targetCommunity
            LIMIT 50
          `, { cid: c.communityId });
          context.externalRelationships = extResult.map(r => ({
            source: r.source,
            rel: r.rel,
            target: r.target,
            targetCommunity: r.targetCommunity
          }));
        } catch { /* non-fatal */ }

        // Get child communities (for L1+)
        if (level > 0) {
          try {
            const children = await cd.getChildCommunities(c.communityId, level);
            context.childSummaries = children
              .filter(ch => ch.summary)
              .map(ch => ({
                communityId: ch.communityId,
                name: ch.name,
                memberCount: ch.memberCount,
                summary: ch.summary
              }));
            context.childCommunityIds = children.map(ch => ch.communityId);
          } catch { /* non-fatal */ }
        }

        // Get interactions
        try {
          const interactions = await cd.getCommunityInteractions(c.communityId, level);
          context.interactions = interactions.map(i => ({
            communityId: i.communityId,
            name: i.name,
            strength: i.strength
          }));
        } catch { /* non-fatal */ }

        contexts.push(context);
        totalExported++;

        if (totalExported % 100 === 0) {
          console.log(`[INFO] Exported ${totalExported} communities...`);
        }
      }
    }

    // Write output
    writeFileSync(outputPath, JSON.stringify(contexts, null, 2));
    const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
    const sizeMB = (Buffer.byteLength(JSON.stringify(contexts)) / 1024 / 1024).toFixed(1);

    console.log('');
    console.log('============================================================');
    console.log(`Phase 24E-6 Step 1 Complete: Export`);
    console.log(`  Communities exported: ${totalExported}`);
    console.log(`  Output: ${outputPath}`);
    console.log(`  Size: ${sizeMB} MB`);
    console.log(`  Elapsed: ${elapsed}s`);
    console.log('============================================================');

  } catch (err) {
    console.error(`[ERROR] Export failed: ${err.message}`);
    process.exit(1);
  } finally {
    try { await graphDB.close(); } catch {}
  }
}

main();
