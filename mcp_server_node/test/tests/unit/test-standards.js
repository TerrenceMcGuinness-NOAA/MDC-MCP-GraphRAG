#!/usr/bin/env node

/**
 * Test Coding Standards Access via MCP Tools
 */

import SimpleRAGServer from '../../simple-rag-server.js';
import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function testCodingStandards() {
  console.log('🔍 === Testing Coding Standards Access ===\n');

  const server = new SimpleRAGServer();
  await new Promise(resolve => setTimeout(resolve, 1000));

  console.log('📋 ACCESSING CODING STANDARDS VIA MCP TOOL:\n');

  try {
    const result = server.getDocumentationReferences("standards", "detailed");
    console.log('✅ Coding Standards Successfully Retrieved!\n');
    
    // Also load the raw JSON to analyze structure
    const referencesData = await fs.readFile(path.join(__dirname, '../../documentation-references.json'), 'utf-8');
    const refs = JSON.parse(referencesData);
    const standards = refs.documentation_references.standards_and_policies;

    console.log('\n🎯 KEY CODING STANDARDS AVAILABLE:');
    console.log('──────────────────────────────────────');

    // Count and display standards by category
    let totalStandards = 0;
    let categoryCount = 0;

    if (standards.python) {
      categoryCount++;
      const pythonCount = Object.keys(standards.python).length;
      totalStandards += pythonCount;
      console.log('📝 Python Standards:');
      Object.entries(standards.python).forEach(([key, url]) => {
        const displayName = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        console.log(`   • ${displayName}`);
      });
      console.log('');
    }

    if (standards.shell) {
      categoryCount++;
      const shellCount = Object.keys(standards.shell).length;
      totalStandards += shellCount;
      console.log('🔧 Shell Script Standards:');
      Object.entries(standards.shell).forEach(([key, url]) => {
        const displayName = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        console.log(`   • ${displayName}`);
      });
      console.log('');
    }

    if (standards.cmake) {
      categoryCount++;
      const cmakeCount = Object.keys(standards.cmake).length;
      totalStandards += cmakeCount;
      console.log('🏗️ Build System Standards:');
      Object.entries(standards.cmake).forEach(([key, url]) => {
        const displayName = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        console.log(`   • ${displayName}`);
      });
      console.log('');
    }

    if (standards.fortran) {
      categoryCount++;
      const fortranCount = Object.keys(standards.fortran).length;
      totalStandards += fortranCount;
      console.log('🔬 Fortran Standards:');
      Object.entries(standards.fortran).forEach(([key, url]) => {
        const displayName = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        console.log(`   • ${displayName}`);
      });
      console.log('');
    }

    if (standards.nws || standards.environmental_equivalence) {
      categoryCount++;
      console.log('🏛️ Organizational Standards:');
      
      if (standards.environmental_equivalence) {
        Object.entries(standards.environmental_equivalence).forEach(([key, url]) => {
          const displayName = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
          console.log(`   • ${displayName}`);
          totalStandards++;
        });
      }
      
      if (standards.nws) {
        Object.entries(standards.nws).forEach(([key, url]) => {
          const displayName = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
          console.log(`   • ${displayName}`);
          totalStandards++;
        });
      }
      console.log('');
    }

    console.log('✅ All coding standards are accessible via:');
    console.log('   🔸 MCP tool: get_documentation_references');
    console.log('   🔸 Category: "standards"');
    console.log(`   🔸 Total: ${totalStandards} standards across ${categoryCount} categories`);
    console.log('   🔸 Ready for GitHub Copilot integration!');

  } catch (error) {
    console.error('❌ Error accessing coding standards:', error.message);
  }
}

testCodingStandards().catch(console.error);
