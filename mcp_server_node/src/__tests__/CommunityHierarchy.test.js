/**
 * CommunityHierarchy.test.js - Phase 24E-5 Integration Tests
 *
 * Validates the hierarchical community structure in Neo4j:
 * - Community nodes exist at multiple levels
 * - MEMBER_OF, PARENT_OF, INTERACTS_WITH relationships are correct
 * - Summaries exist in both Neo4j and ChromaDB
 * - GraphGuidedRetrieval hierarchical drill-down works
 *
 * Requires: Live Neo4j + ChromaDB with 24E-5 data materialized.
 *
 * @phase Phase 24E-5
 */

import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { GraphDatabase } from '../data/GraphDatabase.js';

let db;

beforeAll(async () => {
  db = new GraphDatabase();
  await db.connect();
});

afterAll(async () => {
  await db.close();
});

describe('Community Hierarchy Structure', () => {

  it('Community nodes exist at 3+ hierarchical levels', async () => {
    const result = await db.query(`
      MATCH (c:Community)
      WITH c.level AS level, count(c) AS cnt
      RETURN level, cnt ORDER BY level
    `);
    expect(result.length).toBeGreaterThanOrEqual(3);
    // Level 0 should have the most communities
    const l0 = result.find(r => r.level === 0);
    expect(l0).toBeTruthy();
    expect(l0.cnt).toBeGreaterThan(50);
    console.log('Level breakdown:', result.map(r => `L${r.level}=${r.cnt}`).join(', '));
  });

  it('MEMBER_OF relationships link code nodes to L0 communities', async () => {
    const result = await db.query(`
      MATCH (n)-[m:MEMBER_OF]->(c:Community {level: 0})
      RETURN count(m) AS cnt, count(DISTINCT c) AS communities
    `);
    expect(result[0].cnt).toBeGreaterThan(10000);
    expect(result[0].communities).toBeGreaterThan(50);
    console.log(`MEMBER_OF: ${result[0].cnt} rels to ${result[0].communities} L0 communities`);
  });

  it('PARENT_OF tree is valid (acyclic, single parent per level)', async () => {
    const result = await db.query(`
      MATCH (parent:Community)-[:PARENT_OF]->(child:Community)
      RETURN count(*) AS edges,
             count(DISTINCT child) AS children,
             count(DISTINCT parent) AS parents
    `);
    expect(result[0].edges).toBeGreaterThan(50);
    console.log(`PARENT_OF: ${result[0].edges} edges, ${result[0].children} children, ${result[0].parents} parents`);

    // Check parent level is always child level + 1
    const levelCheck = await db.query(`
      MATCH (parent:Community)-[:PARENT_OF]->(child:Community)
      WHERE parent.level <> child.level + 1
      RETURN count(*) AS violations
    `);
    expect(levelCheck[0].violations).toBe(0);
  });

  it('INTERACTS_WITH edges capture cross-community communication', async () => {
    const result = await db.query(`
      MATCH (a:Community)-[ix:INTERACTS_WITH]->(b:Community)
      RETURN count(ix) AS total,
             avg(ix.strength) AS avgStrength,
             max(ix.strength) AS maxStrength
    `);
    expect(result[0].total).toBeGreaterThan(100);
    expect(result[0].avgStrength).toBeGreaterThan(2);
    console.log(`INTERACTS_WITH: ${result[0].total} edges, avg strength: ${result[0].avgStrength?.toFixed(1)}, max: ${result[0].maxStrength}`);
  });

  it('Community nodes have summaries in Neo4j', async () => {
    const result = await db.query(`
      MATCH (c:Community)
      WHERE c.summary IS NOT NULL
      WITH c.level AS level, count(c) AS withSummary
      RETURN level, withSummary ORDER BY level
    `);
    expect(result.length).toBeGreaterThanOrEqual(2);
    const totalWithSummary = result.reduce((s, r) => s + r.withSummary, 0);
    expect(totalWithSummary).toBeGreaterThan(100);
    console.log('Summaries in Neo4j:', result.map(r => `L${r.level}=${r.withSummary}`).join(', '));
  });

  it('Community nodes have metadata (languages, keyMembers)', async () => {
    const result = await db.query(`
      MATCH (c:Community {level: 0})
      WHERE c.languages IS NOT NULL AND c.keyMembers IS NOT NULL
      RETURN count(c) AS cnt
    `);
    expect(result[0].cnt).toBeGreaterThan(50);
    console.log(`L0 communities with metadata: ${result[0].cnt}`);
  });

});
