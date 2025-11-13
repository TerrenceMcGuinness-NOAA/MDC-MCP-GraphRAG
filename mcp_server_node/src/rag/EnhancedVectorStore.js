#!/usr/bin/env node

/**
 * EnhancedVectorStore - Multi-source vector database with intelligent routing
 *
 * Extends the existing EE2VectorStore to handle multiple knowledge sources:
 * - Local repository documentation and code
 * - External documentation from 60+ sources
 * - EE2 compliance standards and policies
 * - GitHub ecosystem knowledge
 *
 * Features:
 * - Intelligent source routing based on query type
 * - Source attribution and provenance tracking
 * - Multi-modal search (semantic + keyword + category)
 * - Quality-based result ranking
 * - Automatic source refresh and validation
 *
 * @version 1.0.0
 * @author NOAA EMC Global Workflow Team
 */

import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';
import { EE2VectorStore } from './EE2VectorStore.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export class EnhancedVectorStore extends EE2VectorStore {
  constructor(options = {}) {
    super(options);

    this.options = {
      ...this.options,
      // Multi-source configuration
      enableExternalSources: options.enableExternalSources !== false,
      externalChunksPath: options.externalChunksPath ||
        path.join(this.options.knowledgeBasePath, 'external_documentation_chunks.json'),

      // Source weighting for search results
      sourceWeights: {
        local: 1.0,
        external: 0.9,
        ee2: 1.1,
        github: 0.8,
        standards: 1.0
      },

      // Query routing configuration
      enableIntelligentRouting: options.enableIntelligentRouting !== false,
      maxResultsPerSource: options.maxResultsPerSource || 10,

      ...options
    };

    // Extended data structures for multi-source support
    this.externalChunks = [];
    this.sourceIndex = new Map(); // source -> chunks
    this.categoryIndex = new Map(); // category -> chunks
    this.qualityIndex = new Map(); // quality_range -> chunks

    this.stats = {
      ...this.stats,
      externalChunks: 0,
      totalSources: 0,
      lastExternalUpdate: null
    };
  }

  /**
   * Initialize the enhanced vector store with all knowledge sources
   */
  async initialize() {
    console.error('[INIT] Initializing Enhanced Vector Store...');

    // Initialize base EE2VectorStore
    await super.initialize();

    // Load external documentation if enabled
    if (this.options.enableExternalSources) {
      await this.loadExternalDocumentation();
    }

    // Build enhanced indexes
    await this.buildEnhancedIndexes();

    this.stats.totalSources = this.sourceIndex.size;

    console.error(`[OK] Enhanced Vector Store initialized`);
    console.error(`[STATS] Total knowledge sources: ${this.stats.totalSources}`);
    console.error(`📄 Total chunks: ${this.getTotalChunkCount().toLocaleString()}`);
  }

  /**
   * Load external documentation chunks
   */
  async loadExternalDocumentation() {
    try {
      const externalPath = this.options.externalChunksPath;
      const content = await fs.readFile(externalPath, 'utf-8');
      const data = JSON.parse(content);

      this.externalChunks = data.chunks || [];
      this.stats.externalChunks = this.externalChunks.length;
      this.stats.lastExternalUpdate = data.metadata?.generatedAt || null;

      console.error(`[OK] Loaded ${this.stats.externalChunks.toLocaleString()} external documentation chunks`);

    } catch (error) {
      console.warn(`[WARN] Could not load external documentation: ${error.message}`);
      this.externalChunks = [];
      this.stats.externalChunks = 0;
    }
  }

  /**
   * Build enhanced indexes for multi-source search
   */
  async buildEnhancedIndexes() {
    console.error('[SEARCH] Building enhanced search indexes...');

    // Clear existing indexes
    this.sourceIndex.clear();
    this.categoryIndex.clear();
    this.qualityIndex.clear();

    // Index all chunks from all sources
    const allChunks = [
      ...this.chunks.map(chunk => ({ ...chunk, source_type: 'local' })),
      ...this.externalChunks.map(chunk => ({ ...chunk, source_type: 'external' }))
    ];

    allChunks.forEach((chunk, index) => {
      // Source index
      const sourceType = chunk.source_type || 'unknown';
      if (!this.sourceIndex.has(sourceType)) {
        this.sourceIndex.set(sourceType, []);
      }
      this.sourceIndex.get(sourceType).push({ ...chunk, globalIndex: index });

      // Category index
      const category = chunk.metadata?.category || 'uncategorized';
      if (!this.categoryIndex.has(category)) {
        this.categoryIndex.set(category, []);
      }
      this.categoryIndex.get(category).push({ ...chunk, globalIndex: index });

      // Quality index
      const qualityScore = chunk.qualityScore || chunk.metadata?.qualityScore || 0.5;
      const qualityRange = this.getQualityRange(qualityScore);
      if (!this.qualityIndex.has(qualityRange)) {
        this.qualityIndex.set(qualityRange, []);
      }
      this.qualityIndex.get(qualityRange).push({ ...chunk, globalIndex: index });
    });

    console.error(`[OK] Enhanced indexes built:`);
    console.error(`  📁 Sources: ${this.sourceIndex.size}`);
    console.error(`  [TAG] Categories: ${this.categoryIndex.size}`);
    console.error(`  ⭐ Quality ranges: ${this.qualityIndex.size}`);
  }

  /**
   * Enhanced semantic search across all sources
   */
  async searchDocumentation(query, options = {}) {
    const {
      maxResults = 10,
      sources = ['all'],
      categories = [],
      minQualityScore = 0.3,
      enableRouting = this.options.enableIntelligentRouting,
      includeMetadata = true
    } = options;

    // Intelligent query routing
    const routingInfo = enableRouting ? this.analyzeQuery(query) : { sources: ['all'] };
    const targetSources = sources.includes('all') ? routingInfo.sources : sources;

    const results = [];

    // Search each target source
    for (const sourceType of targetSources) {
      const sourceResults = await this.searchSource(
        sourceType,
        query,
        {
          maxResults: this.options.maxResultsPerSource,
          categories,
          minQualityScore,
          includeMetadata
        }
      );

      // Apply source weighting
      const weight = this.options.sourceWeights[sourceType] || 1.0;
      sourceResults.forEach(result => {
        result.relevance_score = (result.relevance_score || 0.5) * weight;
        result.source_type = sourceType;
      });

      results.push(...sourceResults);
    }

    // Sort by relevance score and limit results
    results.sort((a, b) => (b.relevance_score || 0) - (a.relevance_score || 0));

    const finalResults = results.slice(0, maxResults);

    // Add search metadata
    if (includeMetadata) {
      finalResults.forEach(result => {
        result.search_metadata = {
          query,
          routing: routingInfo,
          searched_sources: targetSources,
          total_candidates: results.length
        };
      });
    }

    return finalResults;
  }

  /**
   * Search within a specific source
   */
  async searchSource(sourceType, query, options = {}) {
    const {
      maxResults = 10,
      categories = [],
      minQualityScore = 0.3,
      includeMetadata = true
    } = options;

    let candidates = [];

    // Get candidates from source
    if (sourceType === 'local' && this.sourceIndex.has('local')) {
      candidates = this.sourceIndex.get('local');
    } else if (sourceType === 'external' && this.sourceIndex.has('external')) {
      candidates = this.sourceIndex.get('external');
    } else if (sourceType === 'ee2') {
      // Use existing EE2 search functionality
      return await this.searchEE2Compliance(query, {
        maxResults,
        category: categories[0],
        includeCode: true
      });
    } else if (sourceType === 'all') {
      candidates = [
        ...(this.sourceIndex.get('local') || []),
        ...(this.sourceIndex.get('external') || [])
      ];
    } else {
      console.warn(`[WARN] Unknown source type: ${sourceType}`);
      return [];
    }

    // Filter by categories if specified
    if (categories.length > 0) {
      candidates = candidates.filter(chunk =>
        categories.includes(chunk.metadata?.category) ||
        categories.includes(chunk.metadata?.subcategory)
      );
    }

    // Filter by quality score
    candidates = candidates.filter(chunk => {
      const score = chunk.qualityScore || chunk.metadata?.qualityScore || 0.5;
      return score >= minQualityScore;
    });

    // Perform similarity search
    const results = this.performSimilaritySearch(query, candidates, maxResults);

    return results;
  }

  /**
   * Perform similarity search on candidates
   */
  performSimilaritySearch(query, candidates, maxResults) {
    const queryLower = query.toLowerCase();
    const queryWords = new Set(queryLower.split(/\s+/));

    return candidates
      .map(chunk => {
        const content = chunk.content.toLowerCase();
        const title = (chunk.metadata?.title || '').toLowerCase();

        // Calculate similarity scores
        const contentScore = this.calculateTextSimilarity(content, queryLower);
        const titleScore = this.calculateTextSimilarity(title, queryLower);
        const keywordScore = this.calculateKeywordScore(content, queryWords);

        // Weighted combination
        const relevance_score = (contentScore * 0.6) + (titleScore * 0.3) + (keywordScore * 0.1);

        return {
          content: chunk.content,
          relevance_score,
          metadata: chunk.metadata || {},
          source_type: chunk.source_type,
          qualityScore: chunk.qualityScore || chunk.metadata?.qualityScore || 0.5
        };
      })
      .filter(result => result.relevance_score > 0.1) // Filter out very low relevance
      .sort((a, b) => b.relevance_score - a.relevance_score)
      .slice(0, maxResults);
  }

  /**
   * Analyze query to determine optimal sources
   */
  analyzeQuery(query) {
    const queryLower = query.toLowerCase();
    const analysis = {
      sources: ['all'],
      confidence: 0.5,
      reasoning: []
    };

    // EE2 compliance indicators
    if (/\b(ee2|compliance|standard|environment|error.?handling|file.?naming)\b/i.test(query)) {
      analysis.sources = ['ee2', 'standards'];
      analysis.confidence += 0.3;
      analysis.reasoning.push('EE2 compliance keywords detected');
    }

    // External documentation indicators
    if (/\b(ufs|rocoto|gsi|hpc|installation|setup|configuration)\b/i.test(query)) {
      analysis.sources = ['external', 'local'];
      analysis.confidence += 0.2;
      analysis.reasoning.push('External tool/system keywords detected');
    }

    // Local code/workflow indicators
    if (/\b(job|script|workflow|global.workflow|python|bash|cmake)\b/i.test(query)) {
      analysis.sources = ['local', 'external'];
      analysis.confidence += 0.2;
      analysis.reasoning.push('Local workflow keywords detected');
    }

    // Operational guidance indicators
    if (/\b(how.to|procedure|guide|tutorial|operational|deploy)\b/i.test(query)) {
      analysis.sources = ['external', 'local'];
      analysis.confidence += 0.2;
      analysis.reasoning.push('Operational guidance keywords detected');
    }

    // If no specific indicators, search all sources
    if (analysis.confidence < 0.7) {
      analysis.sources = ['local', 'external', 'ee2'];
      analysis.reasoning.push('General query - searching all sources');
    }

    return analysis;
  }

  /**
   * Calculate keyword matching score
   */
  calculateKeywordScore(content, queryWords) {
    const contentWords = new Set(content.split(/\s+/));
    const intersection = new Set([...queryWords].filter(word => contentWords.has(word)));
    return intersection.size / queryWords.size;
  }

  /**
   * Calculate text similarity using word overlap
   */
  calculateTextSimilarity(text1, text2) {
    const words1 = new Set(text1.toLowerCase().split(/\s+/));
    const words2 = new Set(text2.toLowerCase().split(/\s+/));
    const intersection = new Set([...words1].filter(x => words2.has(x)));
    const union = new Set([...words1, ...words2]);

    return intersection.size / union.size;
  }

  /**
   * Get quality range for indexing
   */
  getQualityRange(score) {
    if (score >= 0.8) return 'high';
    if (score >= 0.6) return 'medium';
    if (score >= 0.4) return 'low';
    return 'very_low';
  }

  /**
   * Get total chunk count across all sources
   */
  getTotalChunkCount() {
    return this.chunks.length + this.externalChunks.length;
  }

  /**
   * Get comprehensive statistics
   */
  getStats() {
    const baseStats = super.getStats();

    return {
      ...baseStats,
      ...this.stats,
      sources: Object.fromEntries(
        Array.from(this.sourceIndex.entries()).map(([source, chunks]) => [
          source,
          {
            chunkCount: chunks.length,
            avgQualityScore: this.calculateAvgQuality(chunks)
          }
        ])
      ),
      categories: Object.fromEntries(
        Array.from(this.categoryIndex.entries()).map(([category, chunks]) => [
          category,
          chunks.length
        ])
      )
    };
  }

  /**
   * Calculate average quality score for chunks
   */
  calculateAvgQuality(chunks) {
    if (chunks.length === 0) return 0;
    const total = chunks.reduce((sum, chunk) => {
      return sum + (chunk.qualityScore || chunk.metadata?.qualityScore || 0.5);
    }, 0);
    return Math.round((total / chunks.length) * 100) / 100;
  }

  /**
   * Refresh external documentation
   */
  async refreshExternalDocumentation() {
    console.error('[INIT] Refreshing external documentation...');

    try {
      await this.loadExternalDocumentation();
      await this.buildEnhancedIndexes();

      console.error('[OK] External documentation refreshed');
      return true;
    } catch (error) {
      console.error(`[ERROR] Failed to refresh external documentation: ${error.message}`);
      return false;
    }
  }

  /**
   * Search with source attribution
   */
  async searchWithAttribution(query, options = {}) {
    const results = await this.searchDocumentation(query, options);

    // Add detailed source attribution
    results.forEach(result => {
      const source = result.metadata?.source || 'Unknown';
      const category = result.metadata?.category || 'uncategorized';

      result.attribution = {
        source_url: source,
        source_type: result.source_type,
        category: category,
        last_updated: result.metadata?.lastModified ||
                     result.metadata?.fetchedAt ||
                     result.metadata?.ingestedAt,
        quality_score: result.qualityScore,
        confidence: result.relevance_score
      };
    });

    return results;
  }

  /**
   * Get source health status
   */
  getSourceHealth() {
    const health = {
      timestamp: new Date().toISOString(),
      sources: {}
    };

    this.sourceIndex.forEach((chunks, sourceType) => {
      const totalChunks = chunks.length;
      const avgQuality = this.calculateAvgQuality(chunks);
      const recentChunks = chunks.filter(chunk => {
        const updated = chunk.metadata?.ingestedAt || chunk.metadata?.fetchedAt;
        if (!updated) return false;
        const age = (Date.now() - new Date(updated).getTime()) / (1000 * 60 * 60 * 24); // days
        return age <= 7; // Recent if updated within 7 days
      }).length;

      health.sources[sourceType] = {
        status: totalChunks > 0 ? 'healthy' : 'empty',
        totalChunks,
        avgQuality,
        recentChunks,
        staleness: recentChunks / totalChunks // Ratio of recent updates
      };
    });

    return health;
  }

  /**
   * Export enhanced knowledge base
   */
  async exportKnowledgeBase(outputPath) {
    const export_data = {
      metadata: {
        exportedAt: new Date().toISOString(),
        version: '1.0.0',
        sources: Array.from(this.sourceIndex.keys()),
        totalChunks: this.getTotalChunkCount(),
        stats: this.getStats()
      },
      localChunks: this.chunks,
      externalChunks: this.externalChunks,
      indexes: {
        sourceIndex: Object.fromEntries(this.sourceIndex),
        categoryIndex: Object.fromEntries(this.categoryIndex)
      }
    };

    await fs.writeFile(outputPath, JSON.stringify(export_data, null, 2));
    console.error(`[LOAD] Enhanced knowledge base exported to ${outputPath}`);
  }
}