#!/usr/bin/env node
/**
 * Clean Empty ChromaDB Collections
 * 
 * Identifies and removes collections with 0 documents (vestigial tables).
 */

import { VectorDatabase } from '../src/data/VectorDatabase.js';
import readline from 'readline';

const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout
});

function question(prompt) {
  return new Promise((resolve) => {
    rl.question(prompt, resolve);
  });
}

async function main() {
  console.log('='.repeat(70));
  console.log('ChromaDB Collection Cleanup');
  console.log('='.repeat(70));
  
  const autoDelete = process.argv.includes('--delete') || process.argv.includes('-d');
  
  const vdb = new VectorDatabase();
  
  try {
    // Connect to ChromaDB
    await vdb.connect();
    
    // List all collections
    const collectionNames = await vdb.listCollections();
    console.log(`\nFound ${collectionNames.length} collections:\n`);
    
    const emptyCollections = [];
    
    // Check each collection
    for (const name of collectionNames) {
      try {
        const count = await vdb.getCollectionCount(name);
        const status = count === 0 ? 'EMPTY ❌' : 'OK ✓';
        console.log(`${status.padEnd(12)} ${name.padEnd(45)} ${String(count).padStart(6)} documents`);
        
        if (count === 0) {
          emptyCollections.push(name);
        }
      } catch (error) {
        console.log(`ERROR ?    ${name.padEnd(45)} (${error.message})`);
      }
    }
    
    // Offer to delete empty collections
    if (emptyCollections.length > 0) {
      console.log(`\n\nFound ${emptyCollections.length} empty collection(s):`);
      for (const name of emptyCollections) {
        console.log(`  - ${name}`);
      }
      
      let shouldDelete = autoDelete;
      if (!autoDelete) {
        const response = await question('\nDelete empty collections? [y/N]: ');
        shouldDelete = response.toLowerCase() === 'y' || response.toLowerCase() === 'yes';
      } else {
        console.log('\nAuto-delete mode enabled (--delete flag)');
      }
      
      if (shouldDelete) {
        console.log('\nDeleting empty collections...');
        for (const name of emptyCollections) {
          try {
            await vdb.deleteCollection(name);
            console.log(`  ✓ Deleted: ${name}`);
          } catch (error) {
            console.log(`  ✗ Failed to delete: ${name} (${error.message})`);
          }
        }
        console.log('\nCleanup complete!');
      } else {
        console.log('\nNo collections deleted.');
      }
    } else {
      console.log('\n\nNo empty collections found. All collections contain data!');
    }
    
    console.log('\n' + '='.repeat(70));
    
  } catch (error) {
    console.error('\nError:', error.message);
    process.exit(1);
  } finally {
    rl.close();
    process.exit(0);
  }
}

main();
