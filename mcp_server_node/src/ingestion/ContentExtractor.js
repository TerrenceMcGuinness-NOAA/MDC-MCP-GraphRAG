#!/usr/bin/env node

/**
 * ContentExtractor - Multi-format content extraction and cleaning
 *
 * Extracts clean, structured content from various sources:
 * - HTML documentation (ReadTheDocs, GitHub Pages, etc.)
 * - PDF documents
 * - Markdown files
 * - JSON/XML structured data
 * - Plain text documents
 *
 * Features:
 * - Intelligent content cleaning and noise removal
 * - Structure preservation (headers, code blocks, lists)
 * - Metadata extraction (titles, authors, dates)
 * - Content quality scoring
 *
 * @version 1.0.0
 * @author NOAA EMC Global Workflow Team
 */

import * as cheerio from 'cheerio';
import { RecursiveCharacterTextSplitter } from 'langchain/text_splitter';
import { SemanticChunker } from './SemanticChunker.js';
import path from 'path';

export class ContentExtractor {
  constructor(options = {}) {
    this.options = {
      // Content processing options
      chunkSize: options.chunkSize || 1000,
      chunkOverlap: options.chunkOverlap || 200,

      // Semantic chunking options
      enableSemanticChunking: options.enableSemanticChunking !== false,
      semanticChunkMaxSize: options.semanticChunkMaxSize || 3000,

      // Quality filtering
      minContentLength: options.minContentLength || 100,
      maxContentLength: options.maxContentLength || 50000,

      // HTML extraction options
      removeSelectors: options.removeSelectors || [
        'script', 'style', 'nav', 'header', 'footer',
        '.navigation', '.sidebar', '.toc', '.breadcrumbs',
        '#navigation', '#sidebar', '#toc', '#breadcrumbs',
        '.edit-on-github', '.view-source', '.headerlink'
      ],
      keepSelectors: options.keepSelectors || [
        'main', 'article', '.content', '.document', '.body',
        '#content', '#main', '#documentation', '.rst-content'
      ],

      // Content structure preservation
      preserveHeaders: options.preserveHeaders !== false,
      preserveCodeBlocks: options.preserveCodeBlocks !== false,
      preserveLists: options.preserveLists !== false,

      ...options
    };

    // Initialize RecursiveCharacterTextSplitter (fallback for non-semantic formats)
    this.textSplitter = new RecursiveCharacterTextSplitter({
      chunkSize: this.options.chunkSize,
      chunkOverlap: this.options.chunkOverlap,
      separators: ['\n\n', '\n', '. ', ' ', '']
    });

    // Initialize SemanticChunker for HTML/Markdown
    if (this.options.enableSemanticChunking) {
      this.semanticChunker = new SemanticChunker({
        targetSize: this.options.chunkSize,
        maxSize: this.options.semanticChunkMaxSize,
        minSize: this.options.minContentLength,
        overlapSize: this.options.chunkOverlap,
        enableCodePreservation: this.options.preserveCodeBlocks,
        enableExamplePreservation: true,
        enableContextWindow: true,
        includeMetadata: true
      });
    }

    this.stats = {
      processed: 0,
      htmlPages: 0,
      pdfDocuments: 0,
      markdownFiles: 0,
      jsonFiles: 0,
      totalChunks: 0,
      averageQualityScore: 0
    };
  }

  /**
   * Extract content from fetched response
   */
  async extractContent(fetchResponse) {
    const { url, content, metadata } = fetchResponse;
    const contentType = metadata.contentType.toLowerCase();

    this.stats.processed++;

    try {
      let extractedData;

      if (contentType.includes('text/html')) {
        extractedData = await this.extractFromHtml(content, url, metadata);
        this.stats.htmlPages++;
      } else if (contentType.includes('application/pdf')) {
        extractedData = await this.extractFromPdf(content, url, metadata);
        this.stats.pdfDocuments++;
      } else if (contentType.includes('text/markdown') || url.endsWith('.md')) {
        extractedData = await this.extractFromMarkdown(content, url, metadata);
        this.stats.markdownFiles++;
      } else if (contentType.includes('application/json')) {
        extractedData = await this.extractFromJson(content, url, metadata);
        this.stats.jsonFiles++;
      } else if (contentType.includes('text/xml') || contentType.includes('application/xml')) {
        extractedData = await this.extractFromXml(content, url, metadata);
      } else {
        // Plain text or unknown format
        extractedData = await this.extractFromPlainText(content, url, metadata);
      }

      // Create chunks from extracted content
      const chunks = await this.createChunks(extractedData, url, metadata);
      this.stats.totalChunks += chunks.length;

      // Update quality score average
      const totalQuality = chunks.reduce((sum, chunk) => sum + chunk.qualityScore, 0);
      const avgQuality = chunks.length > 0 ? totalQuality / chunks.length : 0;
      this.stats.averageQualityScore =
        (this.stats.averageQualityScore * (this.stats.processed - 1) + avgQuality) / this.stats.processed;

      return {
        url,
        sourceMetadata: metadata,
        extractedData,
        chunks,
        stats: {
          chunkCount: chunks.length,
          averageQualityScore: avgQuality,
          totalLength: extractedData.cleanText.length
        }
      };

    } catch (error) {
      console.error(`[ERROR] Content extraction failed for ${url}:`, error.message);
      return {
        url,
        sourceMetadata: metadata,
        error: error.message,
        chunks: []
      };
    }
  }

  /**
   * Extract content from HTML documents
   */
  async extractFromHtml(html, url, metadata) {
    const $ = cheerio.load(html);

    // Remove unwanted elements
    this.options.removeSelectors.forEach(selector => {
      $(selector).remove();
    });

    // Try to find main content area
    let contentElement = null;
    for (const selector of this.options.keepSelectors) {
      const element = $(selector);
      if (element.length > 0) {
        contentElement = element.first();
        break;
      }
    }

    // If no specific content area found, use body
    if (!contentElement) {
      contentElement = $('body');
    }

    // Extract structured content
    const structuredContent = this._extractStructuredContent(contentElement, $);

    // Extract metadata
    const extractedMetadata = {
      title: $('title').text().trim() ||
             $('h1').first().text().trim() ||
             this._getFilenameFromUrl(url),
      description: $('meta[name="description"]').attr('content') ||
                  $('meta[property="og:description"]').attr('content') ||
                  '',
      author: $('meta[name="author"]').attr('content') || '',
      keywords: $('meta[name="keywords"]').attr('content') || '',
      lastModified: metadata.lastModified || '',
      language: $('html').attr('lang') || 'en'
    };

    // Clean and join text content
    const cleanText = structuredContent.sections
      .map(section => section.content)
      .join('\n\n')
      .replace(/\s+/g, ' ')
      .trim();

    return {
      title: extractedMetadata.title,
      cleanText,
      structuredContent,
      metadata: extractedMetadata,
      qualityScore: this._calculateQualityScore(cleanText, structuredContent),
      rawHtml: html  // Preserve original HTML for semantic chunking
    };
  }

  /**
   * Extract content from PDF documents
   */
  async extractFromPdf(pdfBuffer, url, metadata) {
    try {
      // Dynamic import of pdf-parse to avoid startup issues
      const pdfParse = (await import('pdf-parse')).default;

      const pdfData = await pdfParse(pdfBuffer);

      const cleanText = pdfData.text
        .replace(/\r\n/g, '\n')
        .replace(/\r/g, '\n')
        .replace(/\s+/g, ' ')
        .trim();

      const extractedMetadata = {
        title: pdfData.info?.Title || this._getFilenameFromUrl(url),
        author: pdfData.info?.Author || '',
        subject: pdfData.info?.Subject || '',
        creator: pdfData.info?.Creator || '',
        producer: pdfData.info?.Producer || '',
        creationDate: pdfData.info?.CreationDate || '',
        modificationDate: pdfData.info?.ModDate || metadata.lastModified || '',
        pages: pdfData.numpages
      };

      // Create basic structure for PDF content
      const structuredContent = {
        sections: [{
          type: 'document',
          title: extractedMetadata.title,
          content: cleanText,
          level: 1
        }]
      };

      return {
        title: extractedMetadata.title,
        cleanText,
        structuredContent,
        metadata: extractedMetadata,
        qualityScore: this._calculateQualityScore(cleanText, structuredContent)
      };

    } catch (error) {
      throw new Error(`PDF extraction failed: ${error.message}`);
    }
  }

  /**
   * Extract content from Markdown files
   */
  async extractFromMarkdown(markdown, url, metadata) {
    // Basic markdown parsing - extract headers and content
    const lines = markdown.split('\n');
    const sections = [];
    let currentSection = null;
    let currentContent = [];

    const extractedMetadata = {
      title: this._extractMarkdownTitle(markdown) || this._getFilenameFromUrl(url),
      lastModified: metadata.lastModified || ''
    };

    for (const line of lines) {
      const headerMatch = line.match(/^(#+)\s+(.+)$/);

      if (headerMatch) {
        // Save previous section
        if (currentSection) {
          sections.push({
            ...currentSection,
            content: currentContent.join('\n').trim()
          });
        }

        // Start new section
        currentSection = {
          type: 'header',
          level: headerMatch[1].length,
          title: headerMatch[2].trim()
        };
        currentContent = [line];
      } else {
        currentContent.push(line);
      }
    }

    // Add final section
    if (currentSection) {
      sections.push({
        ...currentSection,
        content: currentContent.join('\n').trim()
      });
    }

    const structuredContent = { sections };
    const cleanText = sections.map(s => s.content).join('\n\n').trim();

    return {
      title: extractedMetadata.title,
      cleanText,
      structuredContent,
      metadata: extractedMetadata,
      qualityScore: this._calculateQualityScore(cleanText, structuredContent)
    };
  }

  /**
   * Extract content from JSON documents
   */
  async extractFromJson(jsonString, url, metadata) {
    try {
      const jsonData = JSON.parse(jsonString);

      // Convert JSON to readable text representation
      const cleanText = this._jsonToReadableText(jsonData);

      const extractedMetadata = {
        title: jsonData.title || jsonData.name || this._getFilenameFromUrl(url),
        description: jsonData.description || '',
        version: jsonData.version || '',
        lastModified: metadata.lastModified || ''
      };

      const structuredContent = {
        sections: [{
          type: 'json',
          title: extractedMetadata.title,
          content: cleanText,
          level: 1,
          data: jsonData
        }]
      };

      return {
        title: extractedMetadata.title,
        cleanText,
        structuredContent,
        metadata: extractedMetadata,
        qualityScore: this._calculateQualityScore(cleanText, structuredContent)
      };

    } catch (error) {
      throw new Error(`JSON parsing failed: ${error.message}`);
    }
  }

  /**
   * Extract content from XML documents
   */
  async extractFromXml(xml, url, metadata) {
    const $ = cheerio.load(xml, { xmlMode: true });

    // Extract text content from XML
    const cleanText = $('*').contents()
      .filter(function() { return this.type === 'text'; })
      .text()
      .replace(/\s+/g, ' ')
      .trim();

    const extractedMetadata = {
      title: $('title').text() || this._getFilenameFromUrl(url),
      lastModified: metadata.lastModified || ''
    };

    const structuredContent = {
      sections: [{
        type: 'xml',
        title: extractedMetadata.title,
        content: cleanText,
        level: 1
      }]
    };

    return {
      title: extractedMetadata.title,
      cleanText,
      structuredContent,
      metadata: extractedMetadata,
      qualityScore: this._calculateQualityScore(cleanText, structuredContent)
    };
  }

  /**
   * Extract content from plain text
   */
  async extractFromPlainText(text, url, metadata) {
    const cleanText = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();

    const extractedMetadata = {
      title: this._getFilenameFromUrl(url),
      lastModified: metadata.lastModified || ''
    };

    const structuredContent = {
      sections: [{
        type: 'text',
        title: extractedMetadata.title,
        content: cleanText,
        level: 1
      }]
    };

    return {
      title: extractedMetadata.title,
      cleanText,
      structuredContent,
      metadata: extractedMetadata,
      qualityScore: this._calculateQualityScore(cleanText, structuredContent)
    };
  }

  /**
   * Create chunks from extracted content
   */
  async createChunks(extractedData, url, metadata) {
    const { cleanText, structuredContent, title, rawHtml } = extractedData;
    const contentType = metadata.contentType?.toLowerCase() || '';

    // Filter content by length
    if (cleanText.length < this.options.minContentLength) {
      console.warn(`[WARN] Content too short (${cleanText.length} chars): ${url}`);
      return [];
    }

    if (cleanText.length > this.options.maxContentLength) {
      console.warn(`[WARN] Content very long (${cleanText.length} chars), chunking: ${url}`);
    }

    let chunks = [];

    // Use semantic chunking for HTML/Markdown if enabled and available
    if (this.options.enableSemanticChunking && this.semanticChunker) {
      if (contentType.includes('text/html') && rawHtml) {
        // Semantic chunking for HTML using original HTML
        console.log(`🧠 Using semantic HTML chunking for: ${url}`);
        chunks = await this.semanticChunker.chunkHtml(rawHtml, url, {
          ...metadata,
          title,
          extractedAt: new Date().toISOString()
        });
      } else if (contentType.includes('text/markdown') || contentType.includes('markdown')) {
        // Semantic chunking for Markdown
        console.log(`🧠 Using semantic Markdown chunking for: ${url}`);
        chunks = await this.semanticChunker.chunkMarkdown(cleanText, url, {
          ...metadata,
          title,
          extractedAt: new Date().toISOString()
        });
      }
    }

    // Fallback to RecursiveCharacterTextSplitter for other formats or if semantic chunking disabled
    if (chunks.length === 0) {
      console.log(`📄 Using fallback text splitting for: ${url}`);
      const textChunks = await this.textSplitter.splitText(cleanText);

      chunks = textChunks.map((chunk, index) => ({
        content: chunk,
        metadata: {
          source: url,
          sourceType: 'external_documentation',
          title: title,
          chunkIndex: index,
          totalChunks: textChunks.length,
          contentLength: chunk.length,
          extractedAt: new Date().toISOString(),
          originalMetadata: metadata,
          ...extractedData.metadata
        },
        qualityScore: this._calculateChunkQualityScore(chunk, structuredContent, index, textChunks.length)
      }));
    } else {
      // Semantic chunks already have metadata, just add legacy fields for compatibility
      chunks = chunks.map((chunk, index) => ({
        ...chunk,
        metadata: {
          ...chunk.metadata,
          sourceType: 'external_documentation',
          originalMetadata: metadata,
          ...extractedData.metadata
        }
      }));
    }

    return chunks;
  }

  /**
   * Extract structured content from HTML element
   */
  _extractStructuredContent(element, $) {
    const sections = [];
    let currentSection = null;

    element.find('*').each((i, elem) => {
      const $elem = $(elem);
      const tagName = elem.tagName.toLowerCase();

      if (['h1', 'h2', 'h3', 'h4', 'h5', 'h6'].includes(tagName)) {
        // Save previous section
        if (currentSection) {
          sections.push(currentSection);
        }

        // Start new section
        currentSection = {
          type: 'header',
          level: parseInt(tagName.charAt(1)),
          title: $elem.text().trim(),
          content: ''
        };
      } else if (currentSection && ['p', 'div', 'span'].includes(tagName)) {
        const text = $elem.text().trim();
        if (text) {
          currentSection.content += (currentSection.content ? '\n' : '') + text;
        }
      }
    });

    // Add final section
    if (currentSection) {
      sections.push(currentSection);
    }

    return { sections };
  }

  /**
   * Calculate content quality score (0-1)
   */
  _calculateQualityScore(text, structuredContent) {
    let score = 0.5; // Base score

    // Length scoring
    if (text.length > 500) score += 0.2;
    if (text.length > 2000) score += 0.1;

    // Structure scoring
    const sections = structuredContent.sections || [];
    if (sections.length > 1) score += 0.1;
    if (sections.some(s => s.type === 'header')) score += 0.1;

    // Content quality indicators
    if (text.includes('http')) score -= 0.05; // URLs often indicate noise
    if (/\b(error|404|not found)\b/i.test(text)) score -= 0.2;
    if (/\b(documentation|guide|tutorial|howto)\b/i.test(text)) score += 0.1;
    if (/\b(example|usage|install|setup)\b/i.test(text)) score += 0.05;

    return Math.max(0, Math.min(1, score));
  }

  /**
   * Calculate chunk-specific quality score
   */
  _calculateChunkQualityScore(chunk, structuredContent, index, totalChunks) {
    let score = this._calculateQualityScore(chunk, structuredContent);

    // Position scoring - earlier chunks often more important
    if (index === 0) score += 0.1; // First chunk bonus
    if (index < totalChunks * 0.3) score += 0.05; // Early chunks bonus

    return Math.max(0, Math.min(1, score));
  }

  /**
   * Extract title from markdown
   */
  _extractMarkdownTitle(markdown) {
    const lines = markdown.split('\n');
    for (const line of lines.slice(0, 10)) { // Check first 10 lines
      const match = line.match(/^#\s+(.+)$/);
      if (match) {
        return match[1].trim();
      }
    }
    return null;
  }

  /**
   * Convert JSON to readable text
   */
  _jsonToReadableText(obj, depth = 0) {
    if (depth > 3) return '[Object]'; // Prevent deep recursion

    if (typeof obj === 'string') return obj;
    if (typeof obj === 'number' || typeof obj === 'boolean') return obj.toString();
    if (obj === null) return 'null';

    if (Array.isArray(obj)) {
      return obj.map(item => this._jsonToReadableText(item, depth + 1)).join(', ');
    }

    if (typeof obj === 'object') {
      return Object.entries(obj)
        .map(([key, value]) => `${key}: ${this._jsonToReadableText(value, depth + 1)}`)
        .join('\n');
    }

    return obj.toString();
  }

  /**
   * Get filename from URL
   */
  _getFilenameFromUrl(url) {
    try {
      const urlObj = new URL(url);
      const pathname = urlObj.pathname;
      return path.basename(pathname) || urlObj.hostname;
    } catch (error) {
      return 'Unknown Document';
    }
  }

  /**
   * Get extraction statistics
   */
  getStats() {
    return {
      ...this.stats,
      averageChunksPerDocument: this.stats.processed > 0
        ? Math.round(this.stats.totalChunks / this.stats.processed * 10) / 10
        : 0,
      averageQualityScore: Math.round(this.stats.averageQualityScore * 100) / 100
    };
  }

  /**
   * Reset statistics
   */
  resetStats() {
    this.stats = {
      processed: 0,
      htmlPages: 0,
      pdfDocuments: 0,
      markdownFiles: 0,
      jsonFiles: 0,
      totalChunks: 0,
      averageQualityScore: 0
    };
  }
}