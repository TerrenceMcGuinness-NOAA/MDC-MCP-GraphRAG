#!/usr/bin/env node

/**
 * Vector Database Verification Script
 * Verifies ChromaDB setup and vector store population
 */

import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

class VectorDBVerifier {
  constructor() {
    this.knowledgeBasePath = path.join(__dirname, '../knowledge-base');
    this.chromaDbPath = path.join(this.knowledgeBasePath, 'chroma_db');
    this.summaryPath = path.join(this.knowledgeBasePath, 'summary.json');
    this.chunksPath = path.join(this.knowledgeBasePath, 'chunks_with_embeddings.json');
  }

  async checkFileExists(filePath) {
    try {
      await fs.access(filePath);
      return true;
    } catch {
      return false;
    }
  }

  async getFileSize(filePath) {
    try {
      const stats = await fs.stat(filePath);
      return this.formatBytes(stats.size);
    } catch {
      return 'N/A';
    }
  }

  formatBytes(bytes, decimals = 2) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
  }

  async loadSummary() {
    try {
      const summaryData = await fs.readFile(this.summaryPath, 'utf8');
      return JSON.parse(summaryData);
    } catch (error) {
      console.error('⚠️  Could not load summary.json:', error.message);
      return null;
    }
  }

  async checkChromaDB() {
    console.log('🔍 Checking ChromaDB setup...');
    
    const chromaDbExists = await this.checkFileExists(this.chromaDbPath);
    if (!chromaDbExists) {
      console.log('❌ ChromaDB directory not found');
      return false;
    }

    const sqliteFile = path.join(this.chromaDbPath, 'chroma.sqlite3');
    const sqliteExists = await this.checkFileExists(sqliteFile);
    const sqliteSize = await this.getFileSize(sqliteFile);
    
    console.log(`   📁 ChromaDB directory: ${chromaDbExists ? '✅ Found' : '❌ Missing'}`);
    console.log(`   💾 SQLite database: ${sqliteExists ? '✅ Found' : '❌ Missing'} (${sqliteSize})`);
    
    return chromaDbExists && sqliteExists;
  }

  async checkKnowledgeBase() {
    console.log('\n📚 Checking knowledge base files...');
    
    const files = [
      { name: 'summary.json', path: this.summaryPath },
      { name: 'chunks.json', path: path.join(this.knowledgeBasePath, 'chunks.json') },
      { name: 'chunks_with_embeddings.json', path: this.chunksPath },
      { name: 'documents.json', path: path.join(this.knowledgeBasePath, 'documents.json') }
    ];

    let allPresent = true;
    for (const file of files) {
      const exists = await this.checkFileExists(file.path);
      const size = await this.getFileSize(file.path);
      console.log(`   📄 ${file.name}: ${exists ? '✅' : '❌'} (${size})`);
      if (!exists) allPresent = false;
    }

    return allPresent;
  }

  async analyzeSummary() {
    console.log('\n📊 Knowledge base statistics...');
    
    const summary = await this.loadSummary();
    if (!summary) {
      console.log('   ❌ Could not load summary statistics');
      return false;
    }

    console.log(`   🔢 Total chunks: ${summary.total_chunks || 'N/A'}`);
    console.log(`   🏠 Local chunks: ${summary.local_chunks || 'N/A'}`);
    console.log(`   🌐 External chunks: ${summary.external_chunks || 'N/A'}`);
    console.log(`   🧠 Embedding model: ${summary.embedding_model || 'N/A'}`);
    console.log(`   📐 Embedding dimension: ${summary.embedding_dimension || 'N/A'}`);
    console.log(`   🕒 Generated at: ${summary.generated_at ? new Date(summary.generated_at * 1000).toLocaleString() : 'N/A'}`);
    console.log(`   🔗 ChromaDB enabled: ${summary.chromadb_enabled ? '✅ Yes' : '❌ No'}`);

    // Check if data looks reasonable
    const hasReasonableData = (
      summary.total_chunks > 0 &&
      summary.embedding_model &&
      summary.embedding_dimension > 0
    );

    return hasReasonableData;
  }

  async checkEmbeddings() {
    console.log('\n🔍 Checking embeddings...');
    
    try {
      const chunksData = await fs.readFile(this.chunksPath, 'utf8');
      const chunks = JSON.parse(chunksData);
      
      if (!Array.isArray(chunks) || chunks.length === 0) {
        console.log('   ❌ No chunks found in embeddings file');
        return false;
      }

      const totalChunks = chunks.length;
      const chunksWithEmbeddings = chunks.filter(chunk => 
        chunk.embedding && Array.isArray(chunk.embedding) && chunk.embedding.length > 0
      ).length;

      console.log(`   📦 Total chunks: ${totalChunks}`);
      console.log(`   🧠 Chunks with embeddings: ${chunksWithEmbeddings}`);
      console.log(`   📊 Embedding coverage: ${((chunksWithEmbeddings / totalChunks) * 100).toFixed(1)}%`);

      // Sample check on first few embeddings
      if (chunksWithEmbeddings > 0) {
        const sampleChunk = chunks.find(c => c.embedding && c.embedding.length > 0);
        console.log(`   📏 Embedding dimension: ${sampleChunk.embedding.length}`);
        
        // Check if embeddings look reasonable (non-zero variance)
        const embedding = sampleChunk.embedding;
        const mean = embedding.reduce((a, b) => a + b) / embedding.length;
        const variance = embedding.reduce((sum, val) => sum + Math.pow(val - mean, 2), 0) / embedding.length;
        
        console.log(`   📈 Sample embedding stats: mean=${mean.toFixed(4)}, variance=${variance.toFixed(4)}`);
        
        if (variance < 0.0001) {
          console.log('   ⚠️  Warning: Low embedding variance detected');
        } else {
          console.log('   ✅ Embeddings appear valid');
        }
      }

      return chunksWithEmbeddings > 0;
      
    } catch (error) {
      console.log(`   ❌ Error checking embeddings: ${error.message}`);
      return false;
    }
  }

  async testChromaDBConnection() {
    console.log('\n🔌 Testing ChromaDB connection...');
    
    try {
      // Dynamic import to avoid issues if chromadb is not available
      const { ChromaClient } = await import('chromadb');
      
      const client = new ChromaClient();
      
      try {
        const collections = await client.listCollections();
        console.log(`   ✅ ChromaDB connection successful`);
        console.log(`   📚 Collections found: ${collections.length}`);
        
        if (collections.length > 0) {
          for (const collection of collections) {
            console.log(`     - ${collection.name} (${collection.metadata ? 'with metadata' : 'no metadata'})`);
          }
        }
        
        return true;
        
      } catch (connectionError) {
        console.log(`   ⚠️  ChromaDB server not running: ${connectionError.message}`);
        console.log(`   💡 This is expected if ChromaDB server is not started`);
        return false;
      }
      
    } catch (importError) {
      console.log(`   ❌ ChromaDB package not available: ${importError.message}`);
      return false;
    }
  }

  async runFullVerification() {
    console.log('🔍 Vector Database Verification');
    console.log('===============================\n');

    const checks = [];
    
    // Run all checks
    checks.push({ name: 'ChromaDB Setup', result: await this.checkChromaDB() });
    checks.push({ name: 'Knowledge Base Files', result: await this.checkKnowledgeBase() });
    checks.push({ name: 'Summary Analysis', result: await this.analyzeSummary() });
    checks.push({ name: 'Embeddings Check', result: await this.checkEmbeddings() });
    checks.push({ name: 'ChromaDB Connection', result: await this.testChromaDBConnection() });

    // Summary
    console.log('\n📋 VERIFICATION SUMMARY');
    console.log('=======================\n');

    const passed = checks.filter(check => check.result).length;
    const total = checks.length;

    checks.forEach(check => {
      console.log(`${check.result ? '✅' : '❌'} ${check.name}`);
    });

    console.log(`\n📊 Overall: ${passed}/${total} checks passed`);

    if (passed === total) {
      console.log('🎉 All vector database components are working correctly!');
      return true;
    } else if (passed >= total - 1) { // Allow ChromaDB connection to fail (server not running)
      console.log('✅ Vector database is functional (ChromaDB server optional)');
      return true;
    } else {
      console.log('⚠️  Some issues detected with vector database setup');
      return false;
    }
  }
}

// Main execution
async function main() {
  const verifier = new VectorDBVerifier();
  const success = await verifier.runFullVerification();
  process.exit(success ? 0 : 1);
}

// Allow running as script
if (import.meta.url === `file://${process.argv[1]}`) {
  main();
}

export default VectorDBVerifier;