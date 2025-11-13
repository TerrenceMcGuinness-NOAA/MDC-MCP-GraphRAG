#!/usr/bin/env node

/**
 * Display All Documentation URLs
 * Clean listing of all reference URLs by category
 */

import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function displayAllUrls() {
  console.log('🔗 === ALL DOCUMENTATION REFERENCE URLs ===\n');

  try {
    const referencesData = await fs.readFile(path.join(__dirname, 'documentation-references.json'), 'utf-8');
    const refs = JSON.parse(referencesData);
    const docRefs = refs.documentation_references;

    let totalUrls = 0;

    // INTERNAL REFERENCES
    console.log('📂 INTERNAL DOCUMENTATION');
    console.log('─'.repeat(50));
    if (docRefs.internal) {
      Object.keys(docRefs.internal).forEach(system => {
        console.log(`\n🔸 ${system.toUpperCase()}`);
        Object.keys(docRefs.internal[system]).forEach(key => {
          const url = docRefs.internal[system][key];
          console.log(`   • ${key.replace(/_/g, ' ')}: ${url}`);
          totalUrls++;
        });
      });
    }

    // EXTERNAL REFERENCES
    console.log('\n\n📂 EXTERNAL DOCUMENTATION');
    console.log('─'.repeat(50));
    if (docRefs.external) {
      Object.keys(docRefs.external).forEach(system => {
        console.log(`\n🔸 ${system.toUpperCase()}`);

        if (typeof docRefs.external[system] === 'object') {
          Object.keys(docRefs.external[system]).forEach(subsystem => {
            const item = docRefs.external[system][subsystem];

            if (typeof item === 'object') {
              console.log(`   📋 ${subsystem}`);
              Object.keys(item).forEach(key => {
                if (typeof item[key] === 'string' && item[key].startsWith('http')) {
                  console.log(`      • ${key.replace(/_/g, ' ')}: ${item[key]}`);
                  totalUrls++;
                }
              });
            } else if (typeof item === 'string' && item.startsWith('http')) {
              console.log(`   • ${subsystem.replace(/_/g, ' ')}: ${item}`);
              totalUrls++;
            }
          });
        }
      });
    }

    // STANDARDS AND POLICIES
    console.log('\n\n📂 CODING STANDARDS & POLICIES');
    console.log('─'.repeat(50));
    if (docRefs.standards_and_policies) {
      Object.keys(docRefs.standards_and_policies).forEach(org => {
        console.log(`\n🔸 ${org.toUpperCase()}`);
        Object.keys(docRefs.standards_and_policies[org]).forEach(key => {
          const url = docRefs.standards_and_policies[org][key];
          console.log(`   • ${key.replace(/_/g, ' ')}: ${url}`);
          totalUrls++;
        });
      });
    }

    // SUMMARY
    console.log('\n\n📊 SUMMARY');
    console.log('─'.repeat(50));
    console.log(`✅ Total Documentation URLs: ${totalUrls}`);
    console.log(`📅 Last Updated: ${refs.reference_metadata.last_updated}`);
    console.log(`🔄 Update Frequency: ${refs.reference_metadata.update_frequency}`);

    // CODING STANDARDS BREAKDOWN
    console.log('\n📝 CODING STANDARDS BREAKDOWN:');
    const standards = docRefs.standards_and_policies;
    Object.keys(standards).forEach(org => {
      const count = Object.keys(standards[org]).length;
      console.log(`   • ${org.toUpperCase()}: ${count} standards`);
    });

  } catch (error) {
    console.error('❌ Error reading documentation references:', error.message);
  }
}

displayAllUrls().catch(console.error);
