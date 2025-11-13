#!/usr/bin/env node

/**
 * Simple Document Processor for Global Workflow
 * Creates a basic knowledge base without vector embeddings for testing
 */

import fs from 'fs/promises';
import path from 'path';
import crypto from 'crypto';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

class SimpleDocumentProcessor {
  constructor(baseDir = '.') {
    this.baseDir = baseDir;
    this.documents = [];
    this.chunks = [];

    this.config = {
      supportedExtensions: ['.md', '.txt', '.py', '.sh', '.yml', '.yaml', '.json', '.xml', '.cmake', '.rst'],
      excludePatterns: [
        'node_modules', '.git', '__pycache__', '.vscode', 'build', 'dist',
        '.pytest_cache', '.coverage', 'venv', '.venv', 'env', 'fix', 'exec'
      ],
      chunkSize: 1000,
      maxFiles: 50 // Limit for testing
    };
  }

  async processRepository(repoPath) {
    console.log(`Processing repository: ${repoPath}`);

    try {
      await this.discoverDocuments(repoPath);
      console.log(`Found ${this.documents.length} documents`);

      // Limit to first few files for testing
      const limitedDocs = this.documents.slice(0, this.config.maxFiles);
      console.log(`Processing first ${limitedDocs.length} documents`);

      await this.processDocuments(limitedDocs);
      console.log(`Generated ${this.chunks.length} chunks`);

      await this.saveKnowledgeBase();

      return {
        documents: this.documents.length,
        chunks: this.chunks.length
      };

    } catch (error) {
      console.error('Processing failed:', error.message);
      throw error;
    }
  }

  async discoverDocuments(dirPath, relativePath = '', depth = 0) {
    if (depth > 3) return; // Limit recursion depth

    try {
      const entries = await fs.readdir(dirPath, { withFileTypes: true });

      for (const entry of entries) {
        const fullPath = path.join(dirPath, entry.name);
        const relPath = path.join(relativePath, entry.name);

        if (this.shouldExclude(relPath)) {
          continue;
        }

        if (entry.isDirectory()) {
          await this.discoverDocuments(fullPath, relPath, depth + 1);
        } else if (entry.isFile()) {
          const ext = path.extname(entry.name).toLowerCase();
          if (this.config.supportedExtensions.includes(ext)) {
            this.documents.push({
              path: fullPath,
              relativePath: relPath,
              extension: ext,
              name: entry.name,
              type: this.classifyDocument(relPath, ext)
            });
          }
        }
      }
    } catch (error) {
      console.warn(`Skipping directory ${dirPath}: ${error.message}`);
    }
  }

  shouldExclude(relativePath) {
    return this.config.excludePatterns.some(pattern =>
      relativePath.includes(pattern)
    );
  }

  classifyDocument(relativePath, extension) {
    const pathLower = relativePath.toLowerCase();

    if (pathLower.includes('readme') || pathLower.includes('doc')) return 'documentation';
    if (pathLower.includes('job') || pathLower.includes('script')) return 'workflow';
    if (pathLower.includes('config') || pathLower.includes('parm')) return 'configuration';
    if (extension === '.py') return 'python_script';
    if (extension === '.sh') return 'shell_script';
    if (extension === '.yml' || extension === '.yaml') return 'yaml_config';

    return 'general';
  }

  async processDocuments(documents) {
    for (const doc of documents) {
      try {
        const content = await fs.readFile(doc.path, 'utf-8');
        if (content.trim()) {
          const chunks = this.chunkDocument(content, doc);
          this.chunks.push(...chunks);
        }
      } catch (error) {
        console.warn(`Error processing ${doc.path}: ${error.message}`);
      }
    }
  }

  chunkDocument(content, doc) {
    const chunks = [];
    const lines = content.split('\\n');
    let currentChunk = '';
    let chunkIndex = 0;

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      currentChunk += line + '\\n';

      if (currentChunk.length >= this.config.chunkSize || i === lines.length - 1) {
        if (currentChunk.trim()) {
          chunks.push({
            id: this.generateChunkId(doc, chunkIndex),
            content: currentChunk.trim(),
            document: doc,
            chunkIndex,
            metadata: {
              source: doc.relativePath,
              type: doc.type,
              extension: doc.extension,
              size: currentChunk.length
            }
          });
          chunkIndex++;
        }
        currentChunk = '';
      }
    }

    return chunks;
  }

  generateChunkId(doc, chunkIndex) {
    const hash = crypto.createHash('md5')
      .update(doc.relativePath + chunkIndex)
      .digest('hex')
      .substring(0, 8);
    return `chunk_${hash}_${chunkIndex}`;
  }

  async saveKnowledgeBase() {
    const outputDir = './simple-knowledge-base';
    await fs.mkdir(outputDir, { recursive: true });

    const summary = {
      createdAt: new Date().toISOString(),
      totalDocuments: this.documents.length,
      totalChunks: this.chunks.length,
      config: this.config
    };

    await fs.writeFile(
      path.join(outputDir, 'chunks.json'),
      JSON.stringify(this.chunks, null, 2)
    );

    await fs.writeFile(
      path.join(outputDir, 'documents.json'),
      JSON.stringify(this.documents, null, 2)
    );

    await fs.writeFile(
      path.join(outputDir, 'summary.json'),
      JSON.stringify(summary, null, 2)
    );

    console.log(`Knowledge base saved to: ${outputDir}`);
  }

  // Simple search without embeddings
  searchChunks(query, maxResults = 5) {
    const queryLower = query.toLowerCase();
    const results = [];

    for (const chunk of this.chunks) {
      const contentLower = chunk.content.toLowerCase();
      let score = 0;

      // Simple keyword matching
      const queryWords = queryLower.split(/\\s+/);
      for (const word of queryWords) {
        if (contentLower.includes(word)) {
          score += 1;
        }
      }

      if (score > 0) {
        results.push({
          ...chunk,
          score
        });
      }
    }

    return results
      .sort((a, b) => b.score - a.score)
      .slice(0, maxResults);
  }
}

// Simple test function
async function main() {
  const processor = new SimpleDocumentProcessor();
  const repoPath = path.join(__dirname, '../../../../../..');

  try {
    const result = await processor.processRepository(repoPath);
    console.log('\\n✓ Processing completed:');
    console.log(`  - Documents: ${result.documents}`);
    console.log(`  - Chunks: ${result.chunks}`);

    // Test simple search
    console.log('\\n=== Testing Simple Search ===');
    const searchResults = processor.searchChunks('workflow job script');
    console.log(`Found ${searchResults.length} matching chunks`);

    searchResults.slice(0, 3).forEach((result, index) => {
      console.log(`\\n${index + 1}. ${result.metadata.source} (score: ${result.score})`);
      console.log(`   ${result.content.substring(0, 100)}...`);
    });

  } catch (error) {
    console.error('Test failed:', error.message);
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main();
}

export default SimpleDocumentProcessor;
