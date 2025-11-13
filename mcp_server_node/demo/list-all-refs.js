#!/usr/bin/env node

/**
 * List All Documentation References
 * Comprehensive display of all stored reference URLs
 */

import SimpleRAGServer from './simple-rag-server.js';

async function listAllReferences() {
  console.log('=== Complete Documentation References Inventory ===\n');

  const server = new SimpleRAGServer();
  await new Promise(resolve => setTimeout(resolve, 1000));

  const categories = [
    'internal',
    'ufs',
    'rocoto',
    'gsi',
    'hpc_systems',
    'noaa_tools',
    'standards'
  ];

  for (const category of categories) {
    console.log(`\n📚 === ${category.toUpperCase()} ===`);

    try {
      const result = server.getDocumentationReferences(category, 'detailed');
      const response = result.content[0].text;

      // Extract just the URLs section for cleaner display
      const lines = response.split('\n');
      let inUrlSection = false;

      for (const line of lines) {
        if (line.startsWith('##') || line.startsWith('###')) {
          console.log(`\n${line}`);
          inUrlSection = true;
        } else if (line.startsWith('- **') && inUrlSection) {
          console.log(line);
        } else if (line.startsWith('---')) {
          break; // Stop at metadata section
        }
      }

    } catch (error) {
      console.log(`❌ Error loading ${category}: ${error.message}`);
    }
  }

  // Get count of all URLs
  console.log('\n📊 === SUMMARY STATISTICS ===');
  try {
    const allRefs = server.getDocumentationReferences('all', 'urls_only');
    const urlCount = (allRefs.content[0].text.match(/- https:/g) || []).length;
    console.log(`\n✅ Total Reference URLs: ${urlCount}`);

    // Count by category
    for (const category of categories) {
      const catRefs = server.getDocumentationReferences(category, 'urls_only');
      const catCount = (catRefs.content[0].text.match(/- https:/g) || []).length;
      console.log(`   ${category}: ${catCount} URLs`);
    }

  } catch (error) {
    console.log(`❌ Error getting statistics: ${error.message}`);
  }

  console.log('\n🎯 === CODING STANDARDS HIGHLIGHTS ===');
  try {
    const standards = server.getDocumentationReferences('standards', 'detailed');
    console.log('\nKey Coding Standards Available:');
    console.log('• Python: PEP8, NumPy docstrings, Pylint');
    console.log('• Shell: Google style guide, ShellCheck');
    console.log('• CMake: Modern CMake best practices');
    console.log('• Fortran: Modern Fortran standards');
    console.log('• NOAA: Official coding and development standards');
    console.log('• EMC: Workflow-specific development guidelines');

  } catch (error) {
    console.log(`❌ Error loading standards: ${error.message}`);
  }

  console.log('\n=== Reference Inventory Complete ===');
}

listAllReferences().catch(console.error);
