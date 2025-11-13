#!/usr/bin/env node

/**
 * Test script for Environmental Equivalence (EE2) standards access
 * Tests the MCP get_documentation_references tool for EE2 standards
 */

import fs from 'fs';
import path from 'path';

const __dirname = path.dirname(new URL(import.meta.url).pathname);

// Load documentation references - go up to the parent directory
const referencesFile = path.join(__dirname, '../../documentation-references.json');
const references = JSON.parse(fs.readFileSync(referencesFile, 'utf8'));

console.log('🔍 === Environmental Equivalence (EE2) Standards Test ===\n');

// Test 1: Check if environmental_equivalence section exists
if (references.documentation_references?.standards_and_policies?.environmental_equivalence) {
    console.log('✅ Environmental Equivalence section found in standards_and_policies');

    const ee2Section = references.documentation_references.standards_and_policies.environmental_equivalence;
    console.log('📋 EE2 Standards:');
    Object.entries(ee2Section).forEach(([key, url]) => {
        console.log(`   ${key}: ${url}`);
    });
} else {
    console.log('❌ Environmental Equivalence section not found');
    process.exit(1);
}

// Test 2: Simulate MCP tool call for EE2 standards
console.log('\n🔧 === Simulating MCP Tool Call for EE2 ===');

function get_documentation_references(category = null, format = 'detailed') {
    if (category === 'environmental_equivalence') {
        const ee2Data = references.documentation_references.standards_and_policies.environmental_equivalence;

        if (format === 'detailed') {
            return {
                category: 'Environmental Equivalence (EE2) Standards',
                description: 'High-priority standards for Environmental Equivalence verification and testing',
                references: Object.entries(ee2Data).map(([key, url]) => ({
                    name: key,
                    url: url,
                    priority: 'HIGH',
                    usage: 'Vector embedding generation and PR review process'
                }))
            };
        } else if (format === 'urls') {
            return Object.values(ee2Data);
        }
    }

    return references;
}

// Test the tool
const ee2Result = get_documentation_references('environmental_equivalence', 'detailed');
console.log('🎯 EE2 Tool Response:');
console.log(JSON.stringify(ee2Result, null, 2));

// Test URL format
console.log('\n📎 === EE2 URLs Only ===');
const ee2Urls = get_documentation_references('environmental_equivalence', 'urls');
ee2Urls.forEach((url, index) => {
    console.log(`${index + 1}. ${url}`);
});

console.log('\n✅ === Environmental Equivalence Testing Complete ===');
console.log('🚀 Ready for vector embedding generation and PR review integration');
