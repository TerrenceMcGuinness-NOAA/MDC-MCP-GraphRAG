#!/usr/bin/env node

/**
 * Enhanced Vector Store for EE2 Compliance
 * 
 * Specialized vector store implementation optimized for EE2 compliance
 * documentation and regulatory knowledge retrieval.
 * 
 * Features:
 * - EE2-specific document processing
 * - Compliance-focused embedding strategies
 * - Regulatory knowledge indexing
 * - Expert-level code review capabilities
 * 
 * @version 3.0.0
 * @author NOAA EMC Global Workflow Team
 */

import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export class EE2VectorStore {
  constructor(options = {}) {
    this.options = {
      knowledgeBasePath: options.knowledgeBasePath || this.findKnowledgeBase(),
      embeddingModel: options.embeddingModel || 'all-mpnet-base-v2',  // 768-dim embeddings (upgraded from MiniLM 384-dim)
      chunkSize: options.chunkSize || 512,
      overlapSize: options.overlapSize || 64,
      ee2ComplianceWeight: options.ee2ComplianceWeight || 2.0,
      ...options
    };

    this.documents = new Map();
    this.chunks = [];
    this.embeddings = new Map();
    this.ee2Index = new Map();
    this.complianceCategories = new Map();
    
    // EE2 compliance categories for enhanced search
    this.initializeEE2Categories();
  }

  /**
   * Initialize EE2 compliance categories
   */
  initializeEE2Categories() {
    this.complianceCategories.set('environment_variables', {
      keywords: ['DATAROOT', 'DATA', 'HOMEmodel', 'USHmodel', 'EXECmodel', 'PARMmodel', 'FIXmodel', 'envir', 'job', 'jobid', 'NET', 'RUN', 'PDY', 'cyc', 'COMIN', 'COMOUT'],
      weight: 2.5,
      description: 'Environment Variables Standards'
    });

    this.complianceCategories.set('workflow_structure', {
      keywords: ['JAAAAA', 'exaaaaa', 'ecFlow', 'J-job', 'ex-script', 'ush'],
      weight: 2.0,
      description: 'Workflow Structure Standards'
    });

    this.complianceCategories.set('error_handling', {
      keywords: ['err_chk', 'err_exit', 'prep_step', 'startmsg', 'postmsg', 'FATAL', 'ERROR', 'WARNING'],
      weight: 2.5,
      description: 'Error Handling Standards'
    });

    this.complianceCategories.set('file_naming', {
      keywords: ['JAAAAA', 'exaaaaa.sh', 'f001', 'f006', 'GRIB2', 'forecast hours'],
      weight: 1.8,
      description: 'File Naming Standards'
    });

    this.complianceCategories.set('production_utilities', {
      keywords: ['prep_step', 'startmsg', 'postmsg', 'cpreq', 'module load', 'pgmout'],
      weight: 2.2,
      description: 'Production Utilities Standards'
    });

    this.complianceCategories.set('code_standards', {
      keywords: ['shebang', 'licensing', 'GNU LGPL', 'documentation', 'comments', 'headers'],
      weight: 1.5,
      description: 'Code Standards'
    });

    this.complianceCategories.set('directory_structure', {
      keywords: ['jobs/', 'scripts/', 'ush/', 'parm/', 'fix/', 'exec/', 'sorc/', 'modulefiles/'],
      weight: 1.8,
      description: 'Directory Structure Standards'
    });
  }

  /**
   * Find knowledge base directory
   */
  findKnowledgeBase() {
    let currentDir = __dirname;
    while (currentDir !== '/') {
      const knowledgeBase = path.join(currentDir, 'knowledge-base');
      try {
        if (require('fs').existsSync(knowledgeBase)) {
          return knowledgeBase;
        }
      } catch (error) {
        // Continue searching
      }
      currentDir = path.dirname(currentDir);
    }
    return path.join(__dirname, '../knowledge-base');
  }

  /**
   * Initialize the enhanced vector store
   */
  async initialize() {
    console.error('[INIT] Initializing Enhanced EE2 Vector Store...');
    
    await this.loadExistingKnowledgeBase();
    await this.processEE2Documentation();
    await this.buildComplianceIndex();
    await this.optimizeEmbeddings();
    
    console.error('[OK] Enhanced EE2 Vector Store initialized');
    return this.getStats();
  }

  /**
   * Load existing knowledge base
   */
  async loadExistingKnowledgeBase() {
    try {
      const chunksPath = path.join(this.options.knowledgeBasePath, 'chunks_with_embeddings.json');
      const content = await fs.readFile(chunksPath, 'utf-8');
      const data = JSON.parse(content);
      
      if (data.chunks) {
        this.chunks = data.chunks;
        console.error(`📚 Loaded ${this.chunks.length} existing chunks`);
      }
    } catch (error) {
      console.error(`[WARN] Could not load existing knowledge base: ${error.message}`);
      this.chunks = [];
    }
  }

  /**
   * Process EE2-specific documentation
   */
  async processEE2Documentation() {
    console.error('[INFO] Processing EE2 compliance documentation...');
    
    // Find EE2 documents
    const ee2Documents = await this.findEE2Documents();
    
    for (const docPath of ee2Documents) {
      await this.processEE2Document(docPath);
    }
    
    console.error(`[OK] Processed ${ee2Documents.length} EE2 documents`);
  }

  /**
   * Find EE2 compliance documents
   */
  async findEE2Documents() {
    const ee2Docs = [];
    const searchPaths = [
      process.env.MCP_WORKFLOW_ROOT || '/mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow',
      this.options.knowledgeBasePath
    ];

    for (const searchPath of searchPaths) {
      try {
        const files = await this.findFilesRecursive(searchPath, (filename) => {
          const lower = filename.toLowerCase();
          return lower.includes('ee2') || 
                 lower.includes('compliance') || 
                 lower.includes('standard') ||
                 lower.includes('executive_summary');
        });
        ee2Docs.push(...files);
      } catch (error) {
        console.error(`[WARN] Could not search path ${searchPath}: ${error.message}`);
      }
    }

    return [...new Set(ee2Docs)]; // Remove duplicates
  }

  /**
   * Find files recursively with filter
   */
  async findFilesRecursive(dir, filter) {
    const results = [];
    
    try {
      const entries = await fs.readdir(dir, { withFileTypes: true });
      
      for (const entry of entries) {
        const fullPath = path.join(dir, entry.name);
        
        if (entry.isDirectory() && !entry.name.startsWith('.')) {
          const subResults = await this.findFilesRecursive(fullPath, filter);
          results.push(...subResults);
        } else if (entry.isFile() && filter(entry.name)) {
          results.push(fullPath);
        }
      }
    } catch (error) {
      // Skip directories we can't read
    }
    
    return results;
  }

  /**
   * Process individual EE2 document
   */
  async processEE2Document(docPath) {
    try {
      const content = await fs.readFile(docPath, 'utf-8');
      const chunks = await this.createEE2Chunks(content, docPath);
      
      for (const chunk of chunks) {
        // Add EE2-specific metadata
        chunk.metadata = {
          ...chunk.metadata,
          source: docPath,
          type: 'ee2_compliance',
          compliance_categories: this.identifyComplianceCategories(chunk.content),
          importance_score: this.calculateEE2ImportanceScore(chunk.content)
        };
        
        this.chunks.push(chunk);
      }
      
      console.error(`📄 Processed EE2 document: ${path.basename(docPath)} (${chunks.length} chunks)`);
    } catch (error) {
      console.error(`[WARN] Could not process EE2 document ${docPath}: ${error.message}`);
    }
  }

  /**
   * Create EE2-optimized chunks
   */
  async createEE2Chunks(content, sourcePath) {
    const chunks = [];
    
    // Split by sections for better EE2 context preservation
    const sections = this.splitIntoEE2Sections(content);
    
    for (let i = 0; i < sections.length; i++) {
      const section = sections[i];
      
      if (section.trim().length < 50) continue; // Skip very short sections
      
      // Further split large sections if needed
      const sectionChunks = this.splitLargeSection(section);
      
      for (let j = 0; j < sectionChunks.length; j++) {
        const chunk = {
          id: `ee2_${path.basename(sourcePath)}_${i}_${j}`,
          content: sectionChunks[j].trim(),
          metadata: {
            source: sourcePath,
            section_index: i,
            chunk_index: j,
            total_chunks: sectionChunks.length
          }
        };
        
        chunks.push(chunk);
      }
    }
    
    return chunks;
  }

  /**
   * Split content into EE2-relevant sections
   */
  splitIntoEE2Sections(content) {
    // Split by headers and important markers
    const sectionMarkers = [
      /^#+ .+$/gm,           // Markdown headers
      /^## .+$/gm,          // Subheaders
      /^### .+$/gm,         // Sub-subheaders
      /^\*\*[^*]+\*\*$/gm,  // Bold section markers
      /^---+$/gm,           // Horizontal rules
      /^Assessment:/gm,     // Assessment sections
      /^Evidence:/gm,       // Evidence sections
      /^Key Findings:/gm,   // Key findings
      /^Compliance:/gm      // Compliance sections
    ];
    
    let sections = [content];
    
    for (const marker of sectionMarkers) {
      const newSections = [];
      for (const section of sections) {
        const parts = section.split(marker);
        newSections.push(...parts);
      }
      sections = newSections;
    }
    
    return sections.filter(section => section.trim().length > 0);
  }

  /**
   * Split large sections into smaller chunks
   */
  splitLargeSection(section) {
    if (section.length <= this.options.chunkSize) {
      return [section];
    }
    
    const chunks = [];
    const sentences = section.split(/[.!?]+\s+/);
    let currentChunk = '';
    
    for (const sentence of sentences) {
      if ((currentChunk + sentence).length > this.options.chunkSize) {
        if (currentChunk.length > 0) {
          chunks.push(currentChunk.trim());
          currentChunk = sentence;
        } else {
          // Single sentence is too long, split it by words
          const words = sentence.split(' ');
          let wordChunk = '';
          for (const word of words) {
            if ((wordChunk + ' ' + word).length > this.options.chunkSize) {
              if (wordChunk.length > 0) {
                chunks.push(wordChunk.trim());
                wordChunk = word;
              } else {
                chunks.push(word); // Single word that's too long
              }
            } else {
              wordChunk += (wordChunk ? ' ' : '') + word;
            }
          }
          if (wordChunk.length > 0) {
            chunks.push(wordChunk.trim());
          }
        }
      } else {
        currentChunk += (currentChunk ? '. ' : '') + sentence;
      }
    }
    
    if (currentChunk.length > 0) {
      chunks.push(currentChunk.trim());
    }
    
    return chunks;
  }

  /**
   * Identify compliance categories for a chunk
   */
  identifyComplianceCategories(content) {
    const categories = [];
    const contentLower = content.toLowerCase();
    
    for (const [categoryName, categoryData] of this.complianceCategories) {
      let matchCount = 0;
      for (const keyword of categoryData.keywords) {
        if (contentLower.includes(keyword.toLowerCase())) {
          matchCount++;
        }
      }
      
      if (matchCount > 0) {
        categories.push({
          name: categoryName,
          description: categoryData.description,
          matches: matchCount,
          weight: categoryData.weight
        });
      }
    }
    
    return categories;
  }

  /**
   * Calculate EE2 importance score for a chunk
   */
  calculateEE2ImportanceScore(content) {
    let score = 1.0;
    const contentLower = content.toLowerCase();
    
    // Boost score for compliance-related content
    const complianceTerms = [
      'compliant', 'compliance', 'standard', 'requirement', 'mandatory',
      'ee2', 'wcoss', 'operational', 'production', 'error handling',
      'environment variable', 'workflow structure', 'file naming'
    ];
    
    for (const term of complianceTerms) {
      if (contentLower.includes(term)) {
        score += 0.3;
      }
    }
    
    // Boost for assessment and evidence sections
    if (contentLower.includes('assessment:') || contentLower.includes('evidence:')) {
      score += 0.5;
    }
    
    // Boost for code examples
    if (content.includes('```') || content.includes('export ') || content.includes('source ')) {
      score += 0.4;
    }
    
    return Math.min(score, 3.0); // Cap at 3.0
  }

  /**
   * Build compliance-focused index
   */
  async buildComplianceIndex() {
    console.error('[SEARCH] Building EE2 compliance index...');
    
    for (const chunk of this.chunks) {
      // Index by compliance categories
      if (chunk.metadata.compliance_categories) {
        for (const category of chunk.metadata.compliance_categories) {
          if (!this.ee2Index.has(category.name)) {
            this.ee2Index.set(category.name, []);
          }
          this.ee2Index.get(category.name).push({
            chunk,
            relevance: category.matches * category.weight
          });
        }
      }
      
      // Index by importance score
      const score = chunk.metadata.importance_score || 1.0;
      if (score > 1.5) {
        if (!this.ee2Index.has('high_importance')) {
          this.ee2Index.set('high_importance', []);
        }
        this.ee2Index.get('high_importance').push({
          chunk,
          relevance: score
        });
      }
    }
    
    // Sort indices by relevance
    for (const [category, chunks] of this.ee2Index) {
      chunks.sort((a, b) => b.relevance - a.relevance);
    }
    
    console.error(`[OK] Built index for ${this.ee2Index.size} compliance categories`);
  }

  /**
   * Optimize embeddings for EE2 search
   */
  async optimizeEmbeddings() {
    console.error('[START] Optimizing embeddings for EE2 compliance search...');
    
    // Load or generate embeddings
    await this.loadEmbeddings();
    
    // Create specialized EE2 embeddings if needed
    const ee2Chunks = this.chunks.filter(chunk => 
      chunk.metadata?.type === 'ee2_compliance' || 
      chunk.metadata?.importance_score > 1.5
    );
    
    console.error(`[OK] Optimized embeddings for ${ee2Chunks.length} EE2-specific chunks`);
  }

  /**
   * Load embeddings from existing knowledge base
   */
  async loadEmbeddings() {
    try {
      const embeddingsPath = path.join(this.options.knowledgeBasePath, 'chunks_with_embeddings.json');
      const content = await fs.readFile(embeddingsPath, 'utf-8');
      const data = JSON.parse(content);
      
      if (data.chunks) {
        for (const chunk of data.chunks) {
          if (chunk.embedding) {
            this.embeddings.set(chunk.id, chunk.embedding);
          }
        }
      }
      
      console.error(`[STATS] Loaded ${this.embeddings.size} embeddings`);
    } catch (error) {
      console.error(`[WARN] Could not load embeddings: ${error.message}`);
    }
  }

  /**
   * Search for EE2 compliance information
   */
  async searchEE2Compliance(query, options = {}) {
    const {
      maxResults = 10,
      category = null,
      minImportance = 1.0,
      includeCode = true
    } = options;
    
    const results = [];
    
    // Search by category if specified
    if (category && this.ee2Index.has(category)) {
      const categoryResults = this.ee2Index.get(category)
        .slice(0, maxResults)
        .map(item => ({
          ...item.chunk,
          relevance_score: item.relevance,
          match_type: 'category'
        }));
      results.push(...categoryResults);
    }
    
    // Text-based search through all chunks
    const queryLower = query.toLowerCase();
    const textResults = this.chunks
      .filter(chunk => {
        const importance = chunk.metadata?.importance_score || 1.0;
        return importance >= minImportance;
      })
      .map(chunk => {
        const content = chunk.content.toLowerCase();
        let score = 0;
        
        // Simple relevance scoring
        const queryWords = queryLower.split(/\s+/);
        for (const word of queryWords) {
          if (content.includes(word)) {
            score += 1;
          }
        }
        
        // Boost for EE2-specific content
        const importance = chunk.metadata?.importance_score || 1.0;
        score *= importance;
        
        return {
          ...chunk,
          relevance_score: score,
          match_type: 'text'
        };
      })
      .filter(item => item.relevance_score > 0)
      .sort((a, b) => b.relevance_score - a.relevance_score)
      .slice(0, maxResults);
    
    results.push(...textResults);
    
    // Remove duplicates and sort by relevance
    const uniqueResults = new Map();
    for (const result of results) {
      const key = result.id || result.content.substring(0, 100);
      if (!uniqueResults.has(key) || uniqueResults.get(key).relevance_score < result.relevance_score) {
        uniqueResults.set(key, result);
      }
    }
    
    return Array.from(uniqueResults.values())
      .sort((a, b) => b.relevance_score - a.relevance_score)
      .slice(0, maxResults);
  }

  /**
   * Get vector store statistics
   */
  getStats() {
    const ee2Chunks = this.chunks.filter(chunk => chunk.metadata?.type === 'ee2_compliance');
    const highImportanceChunks = this.chunks.filter(chunk => 
      (chunk.metadata?.importance_score || 1.0) > 1.5
    );
    
    return {
      total_chunks: this.chunks.length,
      ee2_chunks: ee2Chunks.length,
      high_importance_chunks: highImportanceChunks.length,
      compliance_categories: this.ee2Index.size,
      embeddings_loaded: this.embeddings.size,
      knowledge_base_path: this.options.knowledgeBasePath
    };
  }

  /**
   * Save enhanced knowledge base
   */
  async save() {
    console.error('💾 Saving enhanced EE2 vector store...');
    
    const outputData = {
      metadata: {
        version: '3.0.0',
        created_at: new Date().toISOString(),
        embedding_model: this.options.embeddingModel,
        ee2_optimized: true,
        stats: this.getStats()
      },
      chunks: this.chunks,
      compliance_index: Object.fromEntries(this.ee2Index),
      compliance_categories: Object.fromEntries(this.complianceCategories)
    };
    
    const outputPath = path.join(this.options.knowledgeBasePath, 'ee2_enhanced_knowledge_base.json');
    await fs.writeFile(outputPath, JSON.stringify(outputData, null, 2));
    
    console.error(`[OK] Enhanced knowledge base saved to: ${outputPath}`);
    return outputPath;
  }
}