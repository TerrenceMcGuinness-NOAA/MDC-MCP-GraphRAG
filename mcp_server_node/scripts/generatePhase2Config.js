#!/usr/bin/env node

/**
 * Generate Phase 2 Anti-Pattern Configuration from Knowledge Base
 * 
 * This script queries the ee2-standards-v6-0-0-corrected ChromaDB collection
 * to extract Phase 2 SME corrections (anti-patterns and correct patterns)
 * and generates a JSON configuration file for use by the scan tool.
 * 
 * Architecture: Single Source of Truth
 *   EE2 Standards (.rst) 
 *     → Phase 2 Annotations (mcp: directives)
 *     → ChromaDB Embeddings
 *     → Generated Config (this script)
 *     → Scan Tool Validation
 * 
 * Usage:
 *   node scripts/generatePhase2Config.js
 * 
 * Output:
 *   mcp_server_node/phase2_anti_patterns.json
 */

import { ChromaClient } from 'chromadb';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Configuration
const CHROMADB_HOST = process.env.CHROMADB_HOST || 'localhost';
const CHROMADB_PORT = process.env.CHROMADB_PORT || '8080';
const COLLECTION_NAME = 'ee2-standards-v6-0-0-corrected';
const OUTPUT_FILE = path.join(__dirname, '..', 'phase2_anti_patterns.json');

console.error('[INIT] Phase 2 Configuration Generator');
console.error(`[INIT] ChromaDB: http://${CHROMADB_HOST}:${CHROMADB_PORT}`);
console.error(`[INIT] Collection: ${COLLECTION_NAME}`);
console.error(`[INIT] Output: ${OUTPUT_FILE}`);

async function generateConfig() {
  try {
    // Connect to ChromaDB
    console.error('[CONNECT] Connecting to ChromaDB...');
    const client = new ChromaClient({
      path: `http://${CHROMADB_HOST}:${CHROMADB_PORT}`
    });

    // Get collection
    console.error(`[QUERY] Fetching collection: ${COLLECTION_NAME}`);
    const collection = await client.getCollection({ name: COLLECTION_NAME });
    
    // Get collection stats
    const count = await collection.count();
    console.error(`[OK] Collection found: ${count} documents`);

    // Get all documents (avoid query() which needs embeddings)
    console.error('[FETCH] Fetching all documents from collection...');
    const allDocs = await collection.get({
      limit: count
    });

    console.error(`[OK] Fetched ${allDocs.documents.length} documents`);

    // Separate by directive type
    const antiPatternResults = { metadatas: [[]], documents: [[]] };
    const correctPatternResults = { metadatas: [[]], documents: [[]] };
    const guidanceResults = { metadatas: [[]], documents: [[]] };

    for (let i = 0; i < allDocs.documents.length; i++) {
      const doc = allDocs.documents[i];
      const metadata = allDocs.metadatas[i];
      
      if (metadata.rst_directive === 'mcp:anti_pattern' || metadata.rst_directive === 'mcp:sme_correction') {
        antiPatternResults.documents[0].push(doc);
        antiPatternResults.metadatas[0].push(metadata);
      } else if (metadata.rst_directive === 'mcp:correct_pattern') {
        correctPatternResults.documents[0].push(doc);
        correctPatternResults.metadatas[0].push(metadata);
      } else if (metadata.rst_directive === 'mcp:ai_guidance_rule') {
        guidanceResults.documents[0].push(doc);
        guidanceResults.metadatas[0].push(metadata);
      }
    }

    console.error(`[OK] Found ${antiPatternResults.documents[0].length} anti-patterns`);
    console.error(`[OK] Found ${correctPatternResults.documents[0].length} correct patterns`);
    console.error(`[OK] Found ${guidanceResults.documents[0].length} AI guidance rules`);

    // Process anti-patterns
    const antiPatterns = {
      error_handling: [],
      environment_variables: [],
      file_naming: [],
      workflow_structure: []
    };

    if (antiPatternResults.metadatas && antiPatternResults.metadatas[0]) {
      for (let i = 0; i < antiPatternResults.metadatas[0].length; i++) {
        const metadata = antiPatternResults.metadatas[0][i];
        const document = antiPatternResults.documents[0][i];
        
        // Extract pattern information
        const pattern = {
          name: metadata.directive_name || 'unknown',
          directive: metadata.rst_directive,
          severity: metadata.severity || 'must_not',
          context: metadata.context || 'operational_scripts',
          false_positive_rate: metadata.false_positive_rate || null,
          sme_justification: metadata.sme_justification || '',
          evidence: [],
          description: document.substring(0, 200) + '...'
        };

        // Extract evidence from document text
        const evidenceMatches = document.match(/standards\.rst[: ]+(line[s]? )?(\d+-\d+|\d+)/gi);
        if (evidenceMatches) {
          pattern.evidence = evidenceMatches.map(m => m.replace(/line[s]?\s*/i, ''));
        }

        // Categorize by category
        const category = metadata.category || 'error_handling';
        if (antiPatterns[category]) {
          antiPatterns[category].push(pattern);
        } else {
          antiPatterns.error_handling.push(pattern);
        }
      }
    }

    // Process correct patterns
    const correctPatterns = {
      error_handling: [],
      environment_variables: [],
      file_naming: [],
      workflow_structure: []
    };

    if (correctPatternResults.metadatas && correctPatternResults.metadatas[0]) {
      for (let i = 0; i < correctPatternResults.metadatas[0].length; i++) {
        const metadata = correctPatternResults.metadatas[0][i];
        const document = correctPatternResults.documents[0][i];
        
        const pattern = {
          name: metadata.directive_name || 'unknown',
          directive: metadata.rst_directive,
          severity: metadata.severity || 'must',
          context: metadata.context || 'operational_scripts',
          ee2_section: metadata.ee2_section || '',
          description: document.substring(0, 200) + '...'
        };

        // Extract code examples if present
        const codeBlockMatch = document.match(/```[\w]*\n([\s\S]*?)```/);
        if (codeBlockMatch) {
          pattern.example_code = codeBlockMatch[1].trim();
        }

        const category = metadata.category || 'error_handling';
        if (correctPatterns[category]) {
          correctPatterns[category].push(pattern);
        } else {
          correctPatterns.error_handling.push(pattern);
        }
      }
    }

    // Process AI guidance rules
    const aiGuidanceRules = [];
    
    if (guidanceResults.metadatas && guidanceResults.metadatas[0]) {
      for (let i = 0; i < guidanceResults.metadatas[0].length; i++) {
        const metadata = guidanceResults.metadatas[0][i];
        const document = guidanceResults.documents[0][i];
        
        const rule = {
          name: metadata.directive_name || 'unknown',
          priority: metadata.priority || 'high',
          enforcement: metadata.enforcement || 'strict',
          description: document.substring(0, 200) + '...'
        };

        aiGuidanceRules.push(rule);
      }
    }

    // Build configuration object
    const config = {
      version: '6.0.0',
      phase: 2,
      generated: new Date().toISOString(),
      source_collection: COLLECTION_NAME,
      total_documents: count,
      anti_patterns: antiPatterns,
      correct_patterns: correctPatterns,
      ai_guidance_rules: aiGuidanceRules,
      metadata: {
        purpose: 'Phase 2 SME corrections for EE2 compliance scanning',
        architecture: 'Hybrid: Generated from semantic embeddings for runtime performance',
        update_procedure: 'Re-run scripts/generatePhase2Config.js when Phase 2 annotations change',
        traceability: 'All rules traceable to sdd_framework/phase2_annotations/*.rst files'
      }
    };

    // Write configuration file
    console.error(`[WRITE] Writing configuration to: ${OUTPUT_FILE}`);
    fs.writeFileSync(OUTPUT_FILE, JSON.stringify(config, null, 2), 'utf-8');
    
    // Summary
    console.error('[OK] Configuration generated successfully!');
    console.error('');
    console.error('Summary:');
    console.error(`  Anti-patterns extracted:`);
    for (const [category, patterns] of Object.entries(antiPatterns)) {
      if (patterns.length > 0) {
        console.error(`    ${category}: ${patterns.length}`);
      }
    }
    console.error(`  Correct patterns extracted:`);
    for (const [category, patterns] of Object.entries(correctPatterns)) {
      if (patterns.length > 0) {
        console.error(`    ${category}: ${patterns.length}`);
      }
    }
    console.error(`  AI guidance rules: ${aiGuidanceRules.length}`);
    console.error('');
    console.error(`[OK] Config file: ${OUTPUT_FILE}`);
    console.error('[OK] Ready to integrate with scan tool');

    return config;

  } catch (error) {
    console.error(`[ERROR] Failed to generate configuration: ${error.message}`);
    console.error(error.stack);
    process.exit(1);
  }
}

// Run generator
generateConfig().then(() => {
  console.error('[COMPLETE] Phase 2 configuration generation complete');
  process.exit(0);
}).catch(error => {
  console.error(`[FATAL] ${error.message}`);
  process.exit(1);
});
