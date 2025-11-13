#!/usr/bin/env node

/**
 * SemanticChunker - Context7-inspired semantic document chunking
 *
 * Implements intelligent, structure-aware chunking that respects document semantics:
 * - Header-based boundaries (H1-H6) as primary chunk boundaries
 * - Code block preservation (entire code blocks as indivisible units)
 * - Example preservation (explanation + code kept together)
 * - List and table integrity (keep complete structures)
 * - Context window management (include parent headers)
 * - Smart overlap at semantic boundaries
 * - Cross-reference preservation
 *
 * Key Differences from Simple Chunking:
 * - Respects document structure instead of arbitrary character counts
 * - Preserves code examples with their explanations
 * - Maintains section hierarchy for better context
 * - Splits at semantic boundaries, not mid-sentence
 *
 * @version 1.0.0
 * @author NOAA EMC Global Workflow Team
 */

import * as cheerio from 'cheerio';

export class SemanticChunker {
  constructor(options = {}) {
    this.options = {
      // Target chunk size (soft limit, will be exceeded to respect boundaries)
      targetSize: options.targetSize || 1500,

      // Maximum chunk size (hard limit, will force split)
      maxSize: options.maxSize || 3000,

      // Minimum chunk size (merge small chunks)
      minSize: options.minSize || 200,

      // Overlap strategy
      overlapSize: options.overlapSize || 100,
      overlapAtBoundaries: options.overlapAtBoundaries !== false,

      // Structure preservation
      preserveCodeBlocks: options.preserveCodeBlocks !== false,
      preserveExamples: options.preserveExamples !== false,
      preserveLists: options.preserveLists !== false,
      preserveTables: options.preserveTables !== false,

      // Context enrichment
      includeHeaderContext: options.includeHeaderContext !== false,
      maxHeaderContextDepth: options.maxHeaderContextDepth || 2,

      // Chunk metadata
      extractKeywords: options.extractKeywords !== false,
      extractCrossReferences: options.extractCrossReferences !== false,

      ...options
    };

    this.stats = {
      totalChunks: 0,
      chunksByType: {},
      averageChunkSize: 0,
      boundaryRespected: 0
    };
  }

  /**
   * Create semantic chunks from HTML content
   */
  async chunkHtml(html, url, metadata = {}) {
    const $ = cheerio.load(html);

    // Extract document structure
    const structure = this._extractDocumentStructure($);

    // Create semantic elements
    const elements = this._createSemanticElements(structure, $);

    // Group elements into chunks
    const chunks = this._groupIntoChunks(elements, url, metadata);

    // Enrich chunks with metadata
    const enrichedChunks = this._enrichChunks(chunks, structure);

    return enrichedChunks;
  }

  /**
   * Create semantic chunks from markdown content
   */
  async chunkMarkdown(markdown, url, metadata = {}) {
    // Parse markdown structure
    const structure = this._parseMarkdownStructure(markdown);

    // Create semantic elements
    const elements = this._createMarkdownElements(structure);

    // Group into chunks
    const chunks = this._groupIntoChunks(elements, url, metadata);

    // Enrich with metadata
    const enrichedChunks = this._enrichChunks(chunks, structure);

    return enrichedChunks;
  }

  /**
   * Extract document structure from HTML
   */
  _extractDocumentStructure($) {
    const structure = {
      title: $('title').text().trim() || $('h1').first().text().trim(),
      sections: [],
      headerHierarchy: [],
      codeBlocks: [],
      lists: [],
      tables: [],
      links: []
    };

    const contentElement = this._findMainContent($);
    let currentSection = null;
    let headerStack = [];

    contentElement.find('*').each((i, elem) => {
      const $elem = $(elem);
      const tagName = elem.tagName.toLowerCase();

      // Headers
      if (/^h[1-6]$/.test(tagName)) {
        const level = parseInt(tagName.charAt(1));
        const headerText = $elem.text().trim();

        // Update header stack
        while (headerStack.length > 0 && headerStack[headerStack.length - 1].level >= level) {
          headerStack.pop();
        }

        const header = {
          level,
          text: headerText,
          id: $elem.attr('id') || this._slugify(headerText),
          path: [...headerStack.map(h => h.text), headerText],
          position: i
        };

        headerStack.push(header);
        structure.headerHierarchy.push(header);

        // Save previous section
        if (currentSection) {
          structure.sections.push(currentSection);
        }

        // Start new section
        currentSection = {
          type: 'section',
          header: header,
          elements: [{ type: 'header', content: headerText, level }],
          startPos: i
        };
      }
      // Code blocks
      else if ((tagName === 'pre' || tagName === 'code') && $elem.find('code').length > 0) {
        const codeContent = $elem.find('code').text() || $elem.text();
        const language = this._detectCodeLanguage($elem);

        const codeBlock = {
          type: 'code',
          content: codeContent,
          language,
          position: i,
          lines: codeContent.split('\n').length
        };

        structure.codeBlocks.push(codeBlock);

        if (currentSection) {
          currentSection.elements.push(codeBlock);
        }
      }
      // Lists
      else if (tagName === 'ul' || tagName === 'ol') {
        const listContent = $elem.text().trim();
        const items = $elem.find('li').map((j, li) => $(li).text().trim()).get();

        const list = {
          type: 'list',
          listType: tagName,
          content: listContent,
          items,
          position: i
        };

        structure.lists.push(list);

        if (currentSection) {
          currentSection.elements.push(list);
        }
      }
      // Tables
      else if (tagName === 'table') {
        const tableContent = $elem.text().trim();

        const table = {
          type: 'table',
          content: tableContent,
          rows: $elem.find('tr').length,
          position: i
        };

        structure.tables.push(table);

        if (currentSection) {
          currentSection.elements.push(table);
        }
      }
      // Paragraphs and other text
      else if (['p', 'div', 'span'].includes(tagName)) {
        const textContent = $elem.text().trim();

        if (textContent && currentSection) {
          // Check if this is an explanation before a code block
          const nextElem = $elem.next();
          const isExplanation = nextElem.is('pre, code') &&
            /\b(example|usage|following|below|shows|demonstrates)\b/i.test(textContent);

          currentSection.elements.push({
            type: isExplanation ? 'explanation' : 'text',
            content: textContent,
            position: i
          });
        }
      }
      // Links
      else if (tagName === 'a') {
        const href = $elem.attr('href');
        const text = $elem.text().trim();

        if (href && text) {
          structure.links.push({
            href,
            text,
            position: i
          });
        }
      }
    });

    // Add final section
    if (currentSection) {
      structure.sections.push(currentSection);
    }

    return structure;
  }

  /**
   * Find main content area in HTML
   */
  _findMainContent($) {
    const selectors = [
      'main', 'article', '.content', '.document', '.body',
      '#content', '#main', '#documentation', '.rst-content'
    ];

    for (const selector of selectors) {
      const element = $(selector);
      if (element.length > 0) {
        return element.first();
      }
    }

    return $('body');
  }

  /**
   * Parse markdown structure
   */
  _parseMarkdownStructure(markdown) {
    const lines = markdown.split('\n');
    const structure = {
      title: '',
      sections: [],
      headerHierarchy: [],
      codeBlocks: [],
      lists: [],
      links: []
    };

    let currentSection = null;
    let headerStack = [];
    let inCodeBlock = false;
    let codeBlockContent = [];
    let codeBlockLanguage = '';

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];

      // Code blocks (```)
      if (line.trim().startsWith('```')) {
        if (!inCodeBlock) {
          // Start code block
          inCodeBlock = true;
          codeBlockLanguage = line.trim().substring(3).trim();
          codeBlockContent = [];
        } else {
          // End code block
          const codeBlock = {
            type: 'code',
            content: codeBlockContent.join('\n'),
            language: codeBlockLanguage,
            position: i,
            lines: codeBlockContent.length
          };

          structure.codeBlocks.push(codeBlock);

          if (currentSection) {
            currentSection.elements.push(codeBlock);
          }

          inCodeBlock = false;
          codeBlockContent = [];
          codeBlockLanguage = '';
        }
        continue;
      }

      if (inCodeBlock) {
        codeBlockContent.push(line);
        continue;
      }

      // Headers
      const headerMatch = line.match(/^(#+)\s+(.+)$/);
      if (headerMatch) {
        const level = headerMatch[1].length;
        const headerText = headerMatch[2].trim();

        // Update header stack
        while (headerStack.length > 0 && headerStack[headerStack.length - 1].level >= level) {
          headerStack.pop();
        }

        const header = {
          level,
          text: headerText,
          id: this._slugify(headerText),
          path: [...headerStack.map(h => h.text), headerText],
          position: i
        };

        headerStack.push(header);
        structure.headerHierarchy.push(header);

        if (!structure.title && level === 1) {
          structure.title = headerText;
        }

        // Save previous section
        if (currentSection) {
          structure.sections.push(currentSection);
        }

        // Start new section
        currentSection = {
          type: 'section',
          header: header,
          elements: [{ type: 'header', content: headerText, level }],
          startPos: i
        };

        continue;
      }

      // Lists
      const listMatch = line.match(/^(\s*)([-*+]|\d+\.)\s+(.+)$/);
      if (listMatch && currentSection) {
        currentSection.elements.push({
          type: 'list_item',
          content: listMatch[3].trim(),
          position: i
        });
        continue;
      }

      // Regular text
      if (line.trim() && currentSection) {
        // Check if this is an explanation (mentions code/example)
        const isExplanation = /\b(example|usage|following|below|shows|demonstrates)\b/i.test(line);

        currentSection.elements.push({
          type: isExplanation ? 'explanation' : 'text',
          content: line.trim(),
          position: i
        });
      }
    }

    // Add final section
    if (currentSection) {
      structure.sections.push(currentSection);
    }

    return structure;
  }

  /**
   * Create semantic elements from HTML structure
   */
  _createSemanticElements(structure, $) {
    const elements = [];

    for (const section of structure.sections) {
      // Add header with context
      const headerContext = this._getHeaderContext(section.header, structure.headerHierarchy);

      elements.push({
        type: 'header',
        content: section.header.text,
        metadata: {
          level: section.header.level,
          id: section.header.id,
          path: section.header.path,
          context: headerContext
        },
        size: section.header.text.length,
        canSplit: false
      });

      // Process section elements
      for (let i = 0; i < section.elements.length; i++) {
        const elem = section.elements[i];

        if (elem.type === 'header') {
          continue; // Already added above
        }

        // Check if this is an explanation + code pair
        if (elem.type === 'explanation' || elem.type === 'text') {
          const nextElem = section.elements[i + 1];

          if (nextElem && nextElem.type === 'code' && this.options.preserveExamples) {
            // Keep explanation and code together
            elements.push({
              type: 'example',
              content: elem.content + '\n\n' + nextElem.content,
              metadata: {
                explanation: elem.content,
                code: nextElem.content,
                language: nextElem.language
              },
              size: elem.content.length + nextElem.content.length,
              canSplit: false
            });

            i++; // Skip next element (already processed)
            continue;
          }
        }

        // Add element as-is
        elements.push({
          ...elem,
          size: elem.content.length,
          canSplit: elem.type === 'text' // Only text paragraphs can be split
        });
      }
    }

    return elements;
  }

  /**
   * Create semantic elements from markdown structure
   */
  _createMarkdownElements(structure) {
    const elements = [];

    for (const section of structure.sections) {
      // Add header
      const headerContext = this._getHeaderContext(section.header, structure.headerHierarchy);

      elements.push({
        type: 'header',
        content: section.header.text,
        metadata: {
          level: section.header.level,
          id: section.header.id,
          path: section.header.path,
          context: headerContext
        },
        size: section.header.text.length,
        canSplit: false
      });

      // Add section elements
      for (const elem of section.elements) {
        if (elem.type === 'header') continue;

        elements.push({
          ...elem,
          size: elem.content.length,
          canSplit: elem.type === 'text'
        });
      }
    }

    return elements;
  }

  /**
   * Group elements into chunks
   */
  _groupIntoChunks(elements, url, metadata) {
    const chunks = [];
    let currentChunk = {
      elements: [],
      size: 0,
      headerContext: null
    };

    for (let i = 0; i < elements.length; i++) {
      const elem = elements[i];

      // Track current header context
      if (elem.type === 'header') {
        currentChunk.headerContext = elem.metadata;
      }

      // Check if adding this element would exceed target size
      if (currentChunk.size > 0 &&
          currentChunk.size + elem.size > this.options.targetSize) {

        // Check if we can split
        if (!elem.canSplit || currentChunk.size + elem.size > this.options.maxSize) {
          // Save current chunk and start new one
          if (currentChunk.elements.length > 0) {
            chunks.push(this._finalizeChunk(currentChunk, url, metadata, chunks.length));
          }

          // Start new chunk with header context
          currentChunk = {
            elements: [],
            size: 0,
            headerContext: currentChunk.headerContext
          };

          // Include header context in new chunk if needed
          if (this.options.includeHeaderContext && currentChunk.headerContext) {
            const contextText = this._formatHeaderContext(currentChunk.headerContext);
            currentChunk.elements.push({
              type: 'context',
              content: contextText,
              size: contextText.length
            });
            currentChunk.size += contextText.length;
          }
        }
      }

      // Add element to current chunk
      currentChunk.elements.push(elem);
      currentChunk.size += elem.size;
    }

    // Add final chunk
    if (currentChunk.elements.length > 0) {
      chunks.push(this._finalizeChunk(currentChunk, url, metadata, chunks.length));
    }

    // Merge small chunks
    return this._mergeSmallChunks(chunks);
  }

  /**
   * Finalize a chunk
   */
  _finalizeChunk(chunkData, url, metadata, chunkIndex) {
    const content = chunkData.elements
      .map(elem => elem.content)
      .join('\n\n')
      .trim();

    // Detect chunk type
    const chunkType = this._detectChunkType(chunkData.elements);

    // Extract keywords
    const keywords = this.options.extractKeywords
      ? this._extractKeywords(content, chunkData.headerContext)
      : [];

    return {
      content,
      metadata: {
        source: url,
        sourceType: 'external_documentation',
        chunkIndex,
        chunkType,
        contentLength: content.length,
        headerContext: chunkData.headerContext,
        sectionPath: chunkData.headerContext?.path?.join(' > '),
        keywords,
        hasCode: chunkData.elements.some(e => e.type === 'code' || e.type === 'example'),
        hasTable: chunkData.elements.some(e => e.type === 'table'),
        hasList: chunkData.elements.some(e => e.type === 'list'),
        ...metadata
      },
      qualityScore: this._calculateChunkQuality(chunkData, content)
    };
  }

  /**
   * Merge small chunks
   */
  _mergeSmallChunks(chunks) {
    const merged = [];
    let i = 0;

    while (i < chunks.length) {
      const chunk = chunks[i];

      if (chunk.content.length < this.options.minSize && i < chunks.length - 1) {
        // Merge with next chunk
        const nextChunk = chunks[i + 1];

        merged.push({
          content: chunk.content + '\n\n' + nextChunk.content,
          metadata: {
            ...chunk.metadata,
            chunkIndex: merged.length,
            merged: true,
            originalChunks: [chunk.metadata.chunkIndex, nextChunk.metadata.chunkIndex]
          },
          qualityScore: (chunk.qualityScore + nextChunk.qualityScore) / 2
        });

        i += 2; // Skip next chunk
      } else {
        merged.push({
          ...chunk,
          metadata: {
            ...chunk.metadata,
            chunkIndex: merged.length
          }
        });

        i++;
      }
    }

    return merged;
  }

  /**
   * Enrich chunks with additional metadata
   */
  _enrichChunks(chunks, structure) {
    return chunks.map(chunk => ({
      ...chunk,
      metadata: {
        ...chunk.metadata,
        totalChunks: chunks.length,
        documentTitle: structure.title,
        extractedAt: new Date().toISOString()
      }
    }));
  }

  /**
   * Get header context for a header
   */
  _getHeaderContext(header, hierarchy) {
    const parentHeaders = hierarchy
      .filter(h => h.level < header.level && h.position < header.position)
      .slice(-this.options.maxHeaderContextDepth);

    return {
      current: header.text,
      parents: parentHeaders.map(h => h.text),
      level: header.level,
      path: header.path
    };
  }

  /**
   * Format header context for inclusion in chunk
   */
  _formatHeaderContext(context) {
    if (!context) return '';

    const parents = Array.isArray(context.parents) ? context.parents : [];
    const parts = [...parents, context.current];
    return '# ' + parts.join(' > ');
  }

  /**
   * Detect chunk type
   */
  _detectChunkType(elements) {
    const types = elements.map(e => e.type);

    if (types.includes('example')) return 'code_example';
    if (types.includes('code')) return 'code';
    if (types.includes('table')) return 'table';
    if (types.includes('list')) return 'list';
    if (types.includes('header') && types.includes('text')) return 'section';

    return 'text';
  }

  /**
   * Extract keywords from content
   */
  _extractKeywords(content, headerContext) {
    const keywords = new Set();

    // Add header context keywords
    if (headerContext) {
      headerContext.path.forEach(header => {
        header.split(/\s+/).forEach(word => {
          if (word.length > 3) {
            keywords.add(word.toLowerCase());
          }
        });
      });
    }

    // Extract technical terms (capitalized words, acronyms)
    const technicalTerms = content.match(/\b[A-Z][A-Za-z0-9]{2,}\b/g) || [];
    technicalTerms.forEach(term => keywords.add(term));

    // Extract common documentation keywords
    const commonKeywords = [
      'install', 'setup', 'configure', 'usage', 'example', 'tutorial',
      'guide', 'reference', 'api', 'function', 'class', 'method'
    ];

    commonKeywords.forEach(keyword => {
      if (new RegExp(`\\b${keyword}\\b`, 'i').test(content)) {
        keywords.add(keyword);
      }
    });

    return Array.from(keywords).slice(0, 10); // Top 10 keywords
  }

  /**
   * Calculate chunk quality score
   */
  _calculateChunkQuality(chunkData, content) {
    let score = 0.6; // Base score (higher for documentation)

    // Size scoring - More lenient for documentation
    const sizeRatio = chunkData.size / this.options.targetSize;
    if (sizeRatio >= 0.5 && sizeRatio <= 2.0) {
      // Accept wider range (750-3000 chars)
      score += 0.15;
    }
    if (sizeRatio >= 0.8 && sizeRatio <= 1.5) {
      // Bonus for ideal range (1200-2250 chars)
      score += 0.05;
    }

    // Structure scoring - Essential for context preservation
    if (chunkData.headerContext) {
      score += 0.15; // Increased: Critical for retrieval
      // Bonus for deep context
      const depth = chunkData.headerContext.path?.length || 0;
      if (depth >= 2) score += 0.05; // Has meaningful hierarchy
    }

    // Content type bonuses (optional features, not requirements)
    if (chunkData.elements.some(e => e.type === 'code')) score += 0.08;
    if (chunkData.elements.some(e => e.type === 'example')) score += 0.08;
    if (chunkData.elements.some(e => e.type === 'list')) score += 0.05; // Lists = structured info
    if (chunkData.elements.some(e => e.type === 'table')) score += 0.05; // Tables = dense info

    // Content quality indicators
    const contentLower = content.toLowerCase();
    if (/\b(example|usage|tutorial|guide|how to)\b/i.test(content)) score += 0.05;
    if (/\b(note|warning|important|tip)\b/i.test(content)) score += 0.03; // Callouts
    if (/\b(must|should|required|recommended)\b/i.test(content)) score += 0.03; // Standards/requirements
    
    // Information density (reward substantive content)
    const wordCount = content.split(/\s+/).length;
    if (wordCount >= 100) score += 0.03; // Substantive content
    if (wordCount >= 200) score += 0.02; // Rich content

    return Math.max(0, Math.min(1, score));
  }

  /**
   * Detect code language from element
   */
  _detectCodeLanguage($elem) {
    const classAttr = $elem.attr('class') || '';

    const langMatch = classAttr.match(/language-([a-z0-9]+)/i);
    if (langMatch) {
      return langMatch[1];
    }

    return 'unknown';
  }

  /**
   * Slugify text
   */
  _slugify(text) {
    return text
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '');
  }

  /**
   * Get statistics
   */
  getStats() {
    return this.stats;
  }
}
