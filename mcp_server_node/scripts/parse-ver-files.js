#!/usr/bin/env node
/**
 * Phase 34B: Parse .ver files for PlatformVersion nodes
 * 
 * Reads versions/*.ver from global-workflow and creates:
 * - PlatformVersion nodes: {platform, library, version, ver_file}
 * - REQUIRES_VERSION edges: ExternalLibrary ← PlatformVersion
 * 
 * Usage:
 *   node scripts/parse-ver-files.js [--dry-run] [--verbose]
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const NEO4J_URI = process.env.NEO4J_URI || 'bolt://localhost:7687';
const NEO4J_USER = process.env.NEO4J_USER || 'neo4j';
const NEO4J_PASSWORD = process.env.NEO4J_PASSWORD || 'gfsworkflow2025';
const WORKFLOW_ROOT = process.env.MCP_WORKFLOW_ROOT || '/mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow_develop';

// NCEPLIBS library names to track versions for
const NCEPLIBS_NAMES = new Set([
  'bacio', 'bufr', 'g2', 'g2tmpl', 'ip', 'nemsio',
  'sfcio', 'sigio', 'w3emc', 'w3nco', 'sp', 'landsfcutil', 'ncio'
]);

const args = process.argv.slice(2);
const dryRun = args.includes('--dry-run');
const verbose = args.includes('--verbose');

function log(msg) {
  if (verbose) console.log(msg);
}

/**
 * Derive platform name from .ver filename
 * spack.ver → "spack", build.wcoss2.ver → "wcoss2", build.hera.ver → "hera"
 */
function derivePlatform(filename) {
  // build.wcoss2.ver → wcoss2
  // build.hera.ver → hera
  // spack.ver → spack (default)
  // build.ver → default
  const base = path.basename(filename, '.ver');
  const parts = base.split('.');
  if (parts.length >= 2 && parts[0] === 'build') {
    return parts[1]; // wcoss2, hera, orion, etc.
  }
  if (base === 'spack') return 'spack';
  if (base === 'build') return 'default';
  return base;
}

/**
 * Parse a .ver file for export NAME_ver=VERSION lines
 */
function parseVerFile(filepath) {
  const content = fs.readFileSync(filepath, 'utf-8');
  const versions = [];
  
  // Match: export name_ver=version
  const regex = /^export\s+(\w+)_ver=([^\s#]+)/gm;
  let match;
  while ((match = regex.exec(content)) !== null) {
    const [, libName, version] = match;
    if (NCEPLIBS_NAMES.has(libName)) {
      versions.push({ library: libName, version });
    }
  }
  
  return versions;
}

async function main() {
  const versionsDir = path.join(WORKFLOW_ROOT, 'versions');
  
  if (!fs.existsSync(versionsDir)) {
    console.log(`[ERROR] versions/ directory not found at ${versionsDir}`);
    process.exit(1);
  }
  
  // Find all build*.ver and spack.ver files
  const verFiles = fs.readdirSync(versionsDir)
    .filter(f => f.endsWith('.ver') && (f.startsWith('build') || f === 'spack.ver'))
    .map(f => path.join(versionsDir, f));
  
  console.log(`[INFO] Found ${verFiles.length} .ver files`);
  
  // Parse all versions
  const allVersions = [];
  for (const verFile of verFiles) {
    const platform = derivePlatform(verFile);
    const relPath = path.relative(WORKFLOW_ROOT, verFile);
    const versions = parseVerFile(verFile);
    
    log(`  ${relPath}: ${platform} → ${versions.length} NCEPLIBS versions`);
    
    for (const v of versions) {
      allVersions.push({
        platform,
        library: v.library,
        version: v.version,
        ver_file: relPath
      });
    }
  }
  
  console.log(`[INFO] Total NCEPLIBS version entries: ${allVersions.length}`);
  
  // Detect version divergences
  const byLibrary = {};
  for (const v of allVersions) {
    if (!byLibrary[v.library]) byLibrary[v.library] = {};
    byLibrary[v.library][v.platform] = v.version;
  }
  
  console.log('\n[INFO] Version divergences:');
  for (const [lib, platforms] of Object.entries(byLibrary)) {
    const versions = new Set(Object.values(platforms));
    if (versions.size > 1) {
      const entries = Object.entries(platforms).map(([p, v]) => `${p}=${v}`).join(', ');
      console.log(`  ${lib}: ${entries}`);
    }
  }
  
  if (dryRun) {
    console.log('\n[DRY-RUN] Would create PlatformVersion nodes and REQUIRES_VERSION edges');
    console.log(JSON.stringify(allVersions.slice(0, 5), null, 2));
    return;
  }
  
  // Write to Neo4j
  let neo4j;
  try {
    neo4j = await import('neo4j-driver');
  } catch {
    console.log('[ERROR] neo4j-driver not available. Install with: npm install neo4j-driver');
    process.exit(1);
  }
  
  const driver = neo4j.default.driver(NEO4J_URI, neo4j.default.auth.basic(NEO4J_USER, NEO4J_PASSWORD));
  
  try {
    const session = driver.session();
    
    // Create index
    await session.run('CREATE INDEX IF NOT EXISTS FOR (pv:PlatformVersion) ON (pv.platform, pv.library)');
    
    // Create PlatformVersion nodes and link to ExternalLibrary
    const result = await session.run(`
      UNWIND $versions AS v
      MERGE (pv:PlatformVersion {platform: v.platform, library: v.library})
      SET pv.version = v.version,
          pv.ver_file = v.ver_file,
          pv.lastUpdated = datetime()
      WITH pv, v
      MERGE (el:ExternalLibrary {name: v.library})
      MERGE (pv)-[r:REQUIRES_VERSION]->(el)
      SET r.version = v.version,
          r.platform = v.platform,
          r.lastUpdated = datetime()
      RETURN count(pv) as pvCount
    `, { versions: allVersions });
    
    const pvCount = result.records[0]?.get('pvCount')?.toNumber?.() || 0;
    console.log(`\n[OK] Created ${pvCount} PlatformVersion nodes with REQUIRES_VERSION edges`);
    
    await session.close();
  } finally {
    await driver.close();
  }
}

main().catch(err => {
  console.error('[ERROR]', err.message);
  process.exit(1);
});
