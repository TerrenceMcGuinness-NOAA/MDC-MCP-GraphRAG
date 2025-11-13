#!/usr/bin/env node

/**
 * Document Ingester for Global Workflow Knowledge Base
 * Processes repository files to create structured knowledge chunks with vector embeddings
 */

import fs from 'fs/promises';
import path from 'path';
import crypto from 'crypto';
import { ChromaClient } from 'chromadb';
import { pipeline } from '@xenova/transformers';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

class DocumentIngester {
  constructor(baseDir, outputFile = './knowledge-base.json') {
    this.baseDir = baseDir;
    this.outputFile = outputFile;
    this.knowledgeBase = {
      metadata: {
        createdAt: new Date().toISOString(),
        baseDirectory: baseDir,
        totalChunks: 0,
        version: '2.0.0'
      },
      chunks: []
    };

    // Initialize arrays
    this.documents = [];
    this.chunks = [];

    // Configuration
    this.config = {
      supportedExtensions: ['.md', '.txt', '.py', '.sh', '.yml', '.yaml', '.json', '.xml', '.cmake', '.rst'],
      excludePatterns: [
        'node_modules', '.git', '__pycache__', '.vscode', 'build', 'dist',
        '.pytest_cache', '.coverage', 'venv', '.venv', 'env'
      ],
      chunkSize: 1500,
      chunkOverlap: 200,
      outputDir: './knowledge-base'
    };

    // Vector database setup
    this.chromaClient = null;
    this.collection = null;
    this.embedModel = null;

    // Initialize embedding model
    this.initializeEmbedding();
  }

  async initializeEmbedding() {
    try {
      // Initialize ChromaDB client
      this.chromaClient = new ChromaClient({
        host: process.env.CHROMA_HOST || 'localhost',
        port: process.env.CHROMA_PORT || 8000
      });

      // Initialize embedding model (using sentence-transformers)
      this.embedModel = await pipeline('feature-extraction', 'Xenova/all-MiniLM-L6-v2');

      console.log('✓ Vector database and embedding model initialized');
    } catch (error) {
      console.warn('⚠ Vector database not available, running in local mode:', error.message);
    }
  }

  async setupVectorDatabase(collectionName = 'global-workflow-docs') {
    if (!this.chromaClient) {
      console.log('Vector database not available, skipping setup');
      return;
    }

    try {
      // Create or get collection
      this.collection = await this.chromaClient.getOrCreateCollection({
        name: collectionName,
        metadata: {
          description: 'Global Workflow documentation and code chunks',
          version: '2.0.0',
          created: new Date().toISOString()
        }
      });

      console.log(`✓ Vector collection '${collectionName}' ready`);
    } catch (error) {
      console.error('Failed to setup vector database:', error.message);
    }
  }

  async generateEmbedding(text) {
    if (!this.embedModel) {
      return null;
    }

    try {
      const result = await this.embedModel(text);
      // Convert tensor to array and get the mean pooling
      const embedding = result.data;
      return Array.from(embedding);
    } catch (error) {
      console.warn('Failed to generate embedding:', error.message);
      return null;
    }
  }

  async storeInVectorDB(chunk) {
    if (!this.collection || !chunk.embedding) {
      return;
    }

    try {
      await this.collection.add({
        ids: [chunk.id],
        embeddings: [chunk.embedding],
        metadatas: [{
          file_path: chunk.file_path,
          chunk_type: chunk.chunk_type,
          language: chunk.language,
          size: chunk.size,
          hash: chunk.hash,
          created_at: chunk.created_at
        }],
        documents: [chunk.content]
      });
    } catch (error) {
      console.warn('Failed to store in vector DB:', error.message);
    }
  }

  /**
   * Main ingestion pipeline
   */
  async ingestRepository(repoPath) {
    console.log(`Starting document ingestion for: ${repoPath}`);

    try {
      // Step 0: Setup vector database
      await this.setupVectorDatabase();

      // Step 1: Discover and process documents
      await this.discoverDocuments(repoPath);
      console.log(`Discovered ${this.documents.length} documents`);

      // Step 2: Process documents into chunks
      await this.processDocuments();
      console.log(`Generated ${this.chunks.length} text chunks`);

      // Step 3: Extract metadata
      await this.extractMetadata();

      // Step 4: Save knowledge base
      await this.saveKnowledgeBase();

      console.log('Document ingestion completed successfully');
      return this.chunks;

    } catch (error) {
      console.error('Error during document ingestion:', error);
      throw error;
    }
  }

  /**
   * Recursively discover documents in repository
   */
  async discoverDocuments(dirPath, relativePath = '') {
    const entries = await fs.readdir(dirPath, { withFileTypes: true });

    for (const entry of entries) {
      const fullPath = path.join(dirPath, entry.name);
      const relPath = path.join(relativePath, entry.name);

      // Skip excluded patterns
      if (this.shouldExclude(relPath)) {
        continue;
      }

      if (entry.isDirectory()) {
        await this.discoverDocuments(fullPath, relPath);
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
  }

  /**
   * Check if path should be excluded
   */
  shouldExclude(relativePath) {
    return this.config.excludePatterns.some(pattern =>
      relativePath.includes(pattern)
    );
  }

  /**
   * Classify document type based on path and extension
   */
  classifyDocument(relativePath, extension) {
    const pathLower = relativePath.toLowerCase();

    if (pathLower.includes('/docs/') || pathLower.includes('/documentation/')) {
      return 'documentation';
    } else if (pathLower.includes('/jobs/')) {
      return 'job_script';
    } else if (pathLower.includes('/scripts/') || pathLower.includes('/ush/')) {
      return 'utility_script';
    } else if (pathLower.includes('/parm/') || pathLower.includes('/config/')) {
      return 'configuration';
    } else if (pathLower.includes('/env/')) {
      return 'environment';
    } else if (extension === '.md' || extension === '.rst') {
      return 'documentation';
    } else if (extension === '.sh' || extension === '.py') {
      return 'script';
    } else if (extension === '.yml' || extension === '.yaml' || extension === '.json') {
      return 'configuration';
    } else {
      return 'other';
    }
  }

  /**
   * Process documents into chunks
   */
  async processDocuments() {
    for (const doc of this.documents) {
      try {
        const content = await fs.readFile(doc.path, 'utf-8');
        const chunks = await this.chunkDocument(content, doc);
        this.chunks.push(...chunks);
      } catch (error) {
        console.error(`Error processing document ${doc.path}:`, error);
      }
    }
  }

  /**
   * Split document into overlapping chunks
   */
  async chunkDocument(content, doc) {
    const chunks = [];
    const lines = content.split('\n');
    let currentChunk = '';
    let lineCount = 0;
    let chunkIndex = 0;

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];

      // Add line to current chunk
      currentChunk += line + '\n';
      lineCount++;

      // Check if chunk is large enough
      if (currentChunk.length >= this.config.chunkSize || i === lines.length - 1) {
        if (currentChunk.trim()) {
          const chunk = {
            id: this.generateChunkId(doc, chunkIndex),
            content: currentChunk.trim(),
            document: doc,
            chunkIndex: chunkIndex,
            startLine: i - lineCount + 1,
            endLine: i,
            metadata: {
              source: doc.relativePath,
              type: doc.type,
              extension: doc.extension,
              chunk_size: currentChunk.length,
              line_count: lineCount
            }
          };

          // Generate embedding for the chunk
          const embedding = await this.generateEmbedding(chunk.content);
          if (embedding) {
            chunk.embedding = embedding;
          }

          // Store in vector database
          await this.storeInVectorDB(chunk);

          chunks.push(chunk);
          chunkIndex++;
        }

        // Create overlap for next chunk
        const overlapLines = Math.min(
          Math.floor(this.config.chunkOverlap / (currentChunk.length / lineCount)),
          lineCount
        );

        if (overlapLines > 0 && i < lines.length - 1) {
          const overlapContent = lines.slice(i - overlapLines + 1, i + 1).join('\n') + '\n';
          currentChunk = overlapContent;
          lineCount = overlapLines;
        } else {
          currentChunk = '';
          lineCount = 0;
        }
      }
    }

    return chunks;
  }

  /**
   * Generate unique chunk ID
   */
  generateChunkId(doc, chunkIndex) {
    const hash = crypto.createHash('md5')
      .update(doc.relativePath + chunkIndex)
      .digest('hex')
      .substring(0, 8);
    return `chunk_${hash}_${chunkIndex}`;
  }

  /**
   * Extract additional metadata from chunks
   */
  async extractMetadata() {
    for (const chunk of this.chunks) {
      // Extract component information
      chunk.metadata.component = this.extractComponent(chunk.document.relativePath);

      // Extract workflow phase
      chunk.metadata.workflow_phase = this.extractWorkflowPhase(chunk.content, chunk.document.relativePath);

      // Extract system references
      chunk.metadata.systems = this.extractSystemReferences(chunk.content);

      // Extract dependencies
      chunk.metadata.dependencies = this.extractDependencies(chunk.content, chunk.document.type);

      // Add timestamp
      chunk.metadata.ingested_at = new Date().toISOString();
    }
  }

  /**
   * Extract workflow component from path
   */
  extractComponent(relativePath) {
    const components = ['gdas', 'gfs', 'wave', 'aero', 'ocean', 'ice', 'ufs', 'rocoto'];
    const pathLower = relativePath.toLowerCase();

    for (const component of components) {
      if (pathLower.includes(component)) {
        return component;
      }
    }

    return 'general';
  }

  /**
   * Extract workflow phase (analysis, forecast, post-processing, etc.)
   */
  extractWorkflowPhase(content, relativePath) {
    const phases = {
      'analysis': ['analysis', 'anal', 'gsi', 'observer'],
      'forecast': ['forecast', 'fcst', 'model', 'integration'],
      'post': ['post', 'output', 'product', 'grib'],
      'prep': ['prep', 'preparation', 'initial', 'setup'],
      'archive': ['archive', 'backup', 'storage']
    };

    const contentLower = content.toLowerCase();
    const pathLower = relativePath.toLowerCase();

    for (const [phase, keywords] of Object.entries(phases)) {
      if (keywords.some(keyword =>
        contentLower.includes(keyword) || pathLower.includes(keyword)
      )) {
        return phase;
      }
    }

    return 'general';
  }

  /**
   * Extract HPC system references
   */
  extractSystemReferences(content) {
    const systems = ['hera', 'orion', 'hercules', 'wcoss2', 'gaeac5', 'gaeac6'];
    const found = [];

    const contentLower = content.toLowerCase();
    for (const system of systems) {
      if (contentLower.includes(system)) {
        found.push(system);
      }
    }

    return found;
  }

  /**
   * Extract dependencies from content
   */
  extractDependencies(content, docType) {
    const dependencies = [];

    if (docType === 'job_script') {
      // Extract job dependencies from Rocoto XML or job scripts
      const jobMatches = content.match(/JGDAS_\w+|JGFS_\w+/g);
      if (jobMatches) {
        dependencies.push(...jobMatches);
      }
    }

    if (docType === 'script') {
      // Extract script dependencies
      const scriptMatches = content.match(/source\s+[\w\/\.\-]+|\.[\w\/\.\-]+/g);
      if (scriptMatches) {
        dependencies.push(...scriptMatches);
      }
    }

    return [...new Set(dependencies)]; // Remove duplicates
  }

  /**
   * Save knowledge base to files
   */
  async saveKnowledgeBase() {
    // Create output directory
    await fs.mkdir(this.config.outputDir, { recursive: true });

    // Save chunks
    const chunksFile = path.join(this.config.outputDir, 'chunks.json');
    await fs.writeFile(chunksFile, JSON.stringify(this.chunks, null, 2));

    // Save document index
    const docsFile = path.join(this.config.outputDir, 'documents.json');
    await fs.writeFile(docsFile, JSON.stringify(this.documents, null, 2));

    // Save metadata summary
    const summary = this.generateSummary();
    const summaryFile = path.join(this.config.outputDir, 'summary.json');
    await fs.writeFile(summaryFile, JSON.stringify(summary, null, 2));

    console.log(`Knowledge base saved to: ${this.config.outputDir}`);
  }

  /**
   * Generate ingestion summary
   */
  generateSummary() {
    const typeCount = {};
    const componentCount = {};
    const systemCount = {};

    for (const chunk of this.chunks) {
      // Count by type
      typeCount[chunk.metadata.type] = (typeCount[chunk.metadata.type] || 0) + 1;

      // Count by component
      componentCount[chunk.metadata.component] = (componentCount[chunk.metadata.component] || 0) + 1;

      // Count by system
      for (const system of chunk.metadata.systems) {
        systemCount[system] = (systemCount[system] || 0) + 1;
      }
    }

    return {
      ingestion_date: new Date().toISOString(),
      total_documents: this.documents.length,
      total_chunks: this.chunks.length,
      type_distribution: typeCount,
      component_distribution: componentCount,
      system_distribution: systemCount,
      config: this.config
    };
  }
}

// Command line interface
async function main() {
  const args = process.argv.slice(2);
  const repoPath = args[0] || process.cwd();

  console.log('Global Workflow Document Ingestion Pipeline');
  console.log('==========================================');

  const ingester = new DocumentIngester();

  try {
    await ingester.ingestRepository(repoPath);
    console.log('\nIngestion completed successfully!');
    console.log(`Knowledge base created in: ${ingester.config.outputDir}`);
  } catch (error) {
    console.error('\nIngestion failed:', error);
    process.exit(1);
  }
}

// Run if called directly
if (import.meta.url === `file://${process.argv[1]}`) {
  main();
}

export default DocumentIngester;
