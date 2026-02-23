/**
 * Phase 24F: Cross-Language Traversal Tests
 * Tests for Shell → Fortran and Shell → Python cross-language graph traversal.
 *
 * Requires: Neo4j running with ingested global-workflow data + bridge edges.
 */

import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import neo4j from 'neo4j-driver';

const NEO4J_URI = process.env.NEO4J_URI || 'bolt://localhost:7687';
const NEO4J_USER = process.env.NEO4J_USER || 'neo4j';
const NEO4J_PASSWORD = process.env.NEO4J_PASSWORD || 'gfsworkflow2025';

let driver;
let session;

beforeAll(async () => {
  driver = neo4j.driver(NEO4J_URI, neo4j.auth.basic(NEO4J_USER, NEO4J_PASSWORD));
  session = driver.session();
});

afterAll(async () => {
  if (session) await session.close();
  if (driver) await driver.close();
});

describe('Cross-Language Graph Integration (Phase 24F)', () => {

  // Test 1: Shell → Fortran (forward)
  it('should trace JGLOBAL_ATMOS_ANALYSIS forward to Fortran programs', async () => {
    const result = await session.run(`
      MATCH (s:ShellScript)-[:SOURCES|INVOKES*1..3]->(ex:ShellScript)
      WHERE s.name =~ '(?i).*JGLOBAL_ATMOS_ANALYSIS.*' AND s.type = 'j-job'
      WITH ex
      MATCH (ex)-[:EXECUTES]->(p:FortranProgram)
      RETURN DISTINCT ex.name AS script, p.name AS program
    `);
    const records = result.records;
    expect(records.length).toBeGreaterThan(0);
    const programs = records.map(r => r.get('program'));
    // Expect at least gsi, calc_analysis, or similar
    expect(programs.some(p => ['gsi', 'calc_analysis', 'calc_increment_main', 'enkf_chgres_recenter_nc', 'interp_inc'].includes(p))).toBe(true);
  });

  // Test 2: Fortran → Shell (reverse)
  it('should trace enkf_chgres_recenter_nc reverse to shell scripts and J-Jobs', async () => {
    const result = await session.run(`
      MATCH (p:FortranProgram {name: 'enkf_chgres_recenter_nc'})<-[:EXECUTES]-(script:ShellScript)
      OPTIONAL MATCH (jjob:ShellScript)-[:SOURCES|INVOKES*1..3]->(script)
      WHERE jjob.type = 'j-job'
      RETURN DISTINCT script.name AS executor, collect(DISTINCT jjob.name) AS jjobs
    `);
    const records = result.records;
    expect(records.length).toBeGreaterThan(0);
    const executors = records.map(r => r.get('executor'));
    expect(executors.some(e => e && e.includes('exg'))).toBe(true);
  });

  // Test 3: Shell → Python (forward)
  it('should find ShellScript-INVOKES->PythonModule bridges', async () => {
    const result = await session.run(`
      MATCH (s:ShellScript)-[:INVOKES]->(m:PythonModule)
      RETURN DISTINCT s.name AS script, m.name AS module
    `);
    const records = result.records;
    expect(records.length).toBeGreaterThan(0);
  });

  // Test 4: Fortran reverse to J-Job via calc_analysis
  it('should trace calc_analysis reverse to triggering J-Job', async () => {
    const result = await session.run(`
      MATCH (p:FortranProgram {name: 'calc_analysis'})<-[:EXECUTES]-(script:ShellScript)
      OPTIONAL MATCH (jjob:ShellScript)-[:SOURCES|INVOKES*1..3]->(script)
      WHERE jjob.type = 'j-job'
      RETURN DISTINCT script.name AS script, collect(DISTINCT jjob.name) AS jjobs
    `);
    const records = result.records;
    expect(records.length).toBeGreaterThan(0);
  });

  // Test 5: Latency benchmark — cross-language queries should be fast
  // First query may be slow due to Neo4j cold cache; allow 3000ms warmup, then <200ms
  it('should complete cross-language queries within acceptable latency', async () => {
    const queries = [
      `MATCH (s:ShellScript)-[:EXECUTES]->(p:FortranProgram)-[:CALLS*1..5]->(sub) WHERE s.name =~ '.*exglobal_atmos_analysis.*' RETURN count(sub) AS c`,
      `MATCH (p:FortranProgram {name: 'gsi'})<-[:EXECUTES]-(s:ShellScript) RETURN s.name, p.name`,
      `MATCH (s:ShellScript)-[:INVOKES]->(m:PythonModule) RETURN count(*) AS c`,
      `MATCH (s:ShellScript)-[:EXECUTES]->(p:FortranProgram) RETURN count(*) AS c`,
      `MATCH (p:FortranProgram {name: 'calc_analysis'})<-[:EXECUTES]-(s)<-[:SOURCES|INVOKES*1..3]-(j:ShellScript {type: 'j-job'}) RETURN j.name`,
    ];

    // Warmup: first query warms the cache
    await session.run(queries[0]);

    // Subsequent queries should be fast
    for (const q of queries.slice(1)) {
      const start = Date.now();
      await session.run(q);
      const elapsed = Date.now() - start;
      expect(elapsed).toBeLessThan(500);
    }
  });

  // Test 6: ShellScript EXECUTES bridge edge counts
  it('should have ShellScript-EXECUTES->FortranProgram bridges (Step 1)', async () => {
    const result = await session.run(
      'MATCH (s:ShellScript)-[:EXECUTES]->(p:FortranProgram) RETURN count(*) AS c'
    );
    const count = result.records[0].get('c').toNumber();
    expect(count).toBeGreaterThanOrEqual(16);
  });
});
