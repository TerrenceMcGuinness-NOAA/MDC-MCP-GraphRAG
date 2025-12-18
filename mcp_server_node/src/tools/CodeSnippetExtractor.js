/**
 * CodeSnippetExtractor - Extract code patterns for LLM analysis
 * 
 * Extracts relevant code snippets from shell/Python files for
 * EE2 compliance analysis. Returns structured data suitable for
 * LLM reasoning in passthrough mode.
 * 
 * @version 1.0.0
 * @phase 4C
 * @author AI Assistant + Terry McGuinness
 * @created 2025-12-05
 */

import fs from 'fs';
import path from 'path';

// Regex patterns for extraction - based on EE2 standards
// Updated to match global-workflow conventions (COMOUT_*, COMIN_*, etc.)
const PATTERNS = {
  // Output file patterns - COM* assignments and file operations
  output: [
    // Modern suffixed COM variables: ${COMOUT_ATMOS_GRIB_0p25}/...
    /\$\{COM(?:OUT|IN)_[A-Z0-9_]+\}[^\n]*/g,
    // Legacy $COMOUT and $COMIN usage
    /\$COM(?:OUT|IN)\s*[=\/][^\n]*/g,
    // COM variable assignments
    /COM(?:OUT|IN)[A-Z_]*=\$\{[^}]+\}[^\n]*/g,
    // File copy/move to COM directories
    /cp\s+[^\n]*\$\{?COM[^\n]*/g,
    /mv\s+[^\n]*\$\{?COM[^\n]*/g,
    // Redirect to COM directories
    />\s*["']?\$\{?COM[^\n]*/g,
    // cpreq utility
    /cpreq\s+[^\n]*\$\{?COM[^\n]*/g,
    // COMIN_* usage patterns
    /\$\{COMIN_[A-Z0-9_]+\}[^\n]*/g
  ],
  
  // Error handling patterns
  error_handling: [
    /set\s+-[xueo]+/g,
    /err_chk[^\n]*/g,
    /err_exit[^\n]*/g,
    /exit\s+[01][^\n]*/g,
    /\$\?\s*-ne\s*0[^\n]*/g,
    /if\s*\[\s*\$\?\s*[^\]]+\][^\n]*/g
  ],
  
  // Environment variable patterns
  env_vars: [
    /\$\{[A-Z_]+:\?[^}]*\}/g,
    /\$\{[A-Z_]+:-[^}]*\}/g,
    /export\s+[A-Z_]+=\$\{[^}]+\}/g
  ],
  
  // Shebang and header patterns (as array for extractPatterns compatibility)
  shebang: [
    /^#!(?:\/usr\/bin\/env\s+|\/bin\/)(bash|sh|ksh|python[23]?)[^\n]*/gm,
    /^\s*set\s+-[xeuo]+[^\n]*/gm,
    /^\s*export\s+PS4=[^\n]*/gm
  ]
};

/**
 * CodeSnippetExtractor class
 * 
 * Extracts code patterns from shell and Python files for
 * EE2 compliance analysis in passthrough mode.
 */
export class CodeSnippetExtractor {
  /**
   * Create a CodeSnippetExtractor
   * @param {Object} options - Configuration options
   * @param {number} options.maxLines - Max lines for shebang block (default: 20)
   * @param {number} options.contextLines - Context lines around matches (default: 3)
   */
  constructor(options = {}) {
    this.maxLines = options.maxLines || 20;
    this.contextLines = options.contextLines || 3;
  }

  /**
   * Extract all relevant patterns from a file
   * @param {string} filePath - Path to file
   * @param {string[]} categories - Categories to extract
   * @returns {Object} Extracted snippets with line numbers
   */
  async extractFromFile(filePath, categories = ['output', 'error_handling']) {
    const content = fs.readFileSync(filePath, 'utf-8');
    const lines = content.split('\n');
    const filename = path.basename(filePath);
    
    const result = {
      file: filePath,
      filename,
      fileType: this.detectFileType(filename),
      lineCount: lines.length,
      snippets: {}
    };

    // Extract shebang block (first N lines)
    result.shebangBlock = this.extractShebangBlock(lines);

    // Extract patterns by category
    for (const category of categories) {
      if (PATTERNS[category]) {
        result.snippets[category] = this.extractPatterns(
          content, 
          lines, 
          PATTERNS[category],
          category
        );
      }
    }

    return result;
  }

  /**
   * Extract patterns from content string (Phase 19: Content Abstraction)
   * Same logic as extractFromFile but works with direct content
   * @param {string} content - Code content string
   * @param {string} contentType - Content type (bash, python, auto)
   * @param {string[]} categories - Categories to extract
   * @returns {Object} Extracted snippets with line numbers
   */
  extractFromContent(content, contentType = 'auto', categories = ['output', 'error_handling']) {
    const lines = content.split('\n');
    
    // Detect file type from content if auto
    let fileType = contentType;
    if (contentType === 'auto') {
      if (content.startsWith('#!/bin/bash') || content.startsWith('#!/usr/bin/env bash')) {
        fileType = 'bash';
      } else if (content.startsWith('#!/usr/bin/env python') || content.startsWith('#!/usr/bin/python')) {
        fileType = 'python';
      } else if (/^\s*import\s+/.test(content) || /^\s*def\s+/.test(content)) {
        fileType = 'python';
      } else if (/^\s*set\s+-/.test(content) || /^\s*export\s+/.test(content)) {
        fileType = 'bash';
      }
    }
    
    const result = {
      filename: 'direct_content',
      fileType: fileType === 'bash' ? 'shell' : fileType,
      lineCount: lines.length,
      snippets: {},
      source: 'direct'
    };

    // Extract shebang block (first N lines)
    result.shebangBlock = this.extractShebangBlock(lines);

    // Extract patterns by category
    for (const category of categories) {
      if (PATTERNS[category]) {
        result.snippets[category] = this.extractPatterns(
          content, 
          lines, 
          PATTERNS[category],
          category
        );
      }
    }

    return result;
  }

  /**
   * Extract shebang and header block
   * @param {string[]} lines - File lines
   * @returns {Object} Shebang block analysis
   */
  extractShebangBlock(lines) {
    const block = lines.slice(0, this.maxLines);
    const shebangLine = block[0] || '';
    const hasShebang = /^#!/.test(shebangLine);
    const hasSetX = block.some(l => /^\s*set\s+-x/.test(l));
    
    return {
      lines: block,
      shebang: hasShebang ? shebangLine : null,
      shebangType: this.parseShebang(shebangLine),
      hasSetX,
      setXLine: block.findIndex(l => /^\s*set\s+-x/.test(l)) + 1 || null
    };
  }

  /**
   * Parse shebang to identify shell type
   * @param {string} line - Shebang line
   * @returns {string} Shell type
   */
  parseShebang(line) {
    // Handle env-based shebangs: #!/usr/bin/env bash
    if (/^#!\/usr\/bin\/env\s+bash/.test(line)) return 'bash';
    if (/^#!\/usr\/bin\/env\s+sh/.test(line)) return 'sh';
    if (/^#!\/usr\/bin\/env\s+ksh/.test(line)) return 'ksh';
    if (/^#!\/usr\/bin\/env\s+python/.test(line)) return 'python';
    // Handle direct shebangs: #!/bin/bash
    if (/^#!\/bin\/bash/.test(line)) return 'bash';
    if (/^#!\/bin\/sh/.test(line)) return 'sh';
    if (/^#!\/bin\/ksh/.test(line)) return 'ksh';
    if (/^#!.*python/.test(line)) return 'python';
    return 'unknown';
  }

  /**
   * Detect file type from name
   * @param {string} filename - File name
   * @returns {string} File type classification
   */
  detectFileType(filename) {
    if (/^J[A-Z_]+$/.test(filename)) return 'j-job';
    if (/^ex[a-z_]+\.sh$/.test(filename)) return 'ex-script';
    if (/\.sh$/.test(filename)) return 'shell';
    if (/\.py$/.test(filename)) return 'python';
    return 'unknown';
  }

  /**
   * Extract patterns with context
   * @param {string} content - File content
   * @param {string[]} lines - File lines
   * @param {RegExp[]} patterns - Patterns to match
   * @param {string} category - Category name
   * @returns {Object[]} Array of matches with context
   */
  extractPatterns(content, lines, patterns, category) {
    const matches = [];
    
    for (const pattern of patterns) {
      let match;
      const regex = new RegExp(pattern.source, pattern.flags);
      
      while ((match = regex.exec(content)) !== null) {
        const lineNum = content.substring(0, match.index).split('\n').length;
        const contextStart = Math.max(0, lineNum - this.contextLines - 1);
        const contextEnd = Math.min(lines.length, lineNum + this.contextLines);
        
        matches.push({
          line: lineNum,
          match: match[0].trim(),
          pattern: pattern.source,
          context: lines.slice(contextStart, contextEnd).join('\n')
        });
      }
    }

    // Deduplicate by line number
    const seen = new Set();
    return matches.filter(m => {
      if (seen.has(m.line)) return false;
      seen.add(m.line);
      return true;
    }).sort((a, b) => a.line - b.line);
  }

  /**
   * Extract from multiple files in a directory
   * @param {string} dirPath - Directory path
   * @param {Object} options - Filter options
   * @returns {Object} Extraction results
   */
  async extractFromDirectory(dirPath, options = {}) {
    const {
      pattern = /\.(sh|py)$/,
      categories = ['output', 'error_handling'],
      maxFiles = 100,
      recursive = true
    } = options;

    const files = this.findFiles(dirPath, pattern, recursive, maxFiles);
    const results = [];

    for (const file of files) {
      try {
        const extracted = await this.extractFromFile(file, categories);
        // Only include files with matches
        const hasMatches = Object.values(extracted.snippets)
          .some(arr => arr.length > 0);
        if (hasMatches || extracted.shebangBlock.shebang) {
          results.push(extracted);
        }
      } catch (error) {
        results.push({
          file,
          error: error.message
        });
      }
    }

    return {
      directory: dirPath,
      filesScanned: files.length,
      filesWithMatches: results.filter(r => !r.error).length,
      results
    };
  }

  /**
   * Find files matching pattern
   * @param {string} dirPath - Directory to scan
   * @param {RegExp} pattern - File name pattern
   * @param {boolean} recursive - Recurse into subdirectories
   * @param {number} maxFiles - Maximum files to return
   * @returns {string[]} Array of file paths
   */
  findFiles(dirPath, pattern, recursive, maxFiles) {
    const files = [];
    
    const scan = (dir) => {
      if (files.length >= maxFiles) return;
      
      try {
        const entries = fs.readdirSync(dir, { withFileTypes: true });
        
        for (const entry of entries) {
          if (files.length >= maxFiles) break;
          
          const fullPath = path.join(dir, entry.name);
          
          if (entry.isDirectory() && recursive) {
            // Skip common non-source directories
            if (!['node_modules', '.git', '__pycache__', 'build', 'venv'].includes(entry.name)) {
              scan(fullPath);
            }
          } else if (entry.isFile() && pattern.test(entry.name)) {
            files.push(fullPath);
          }
        }
      } catch (err) {
        // Skip directories we can't read
        console.error(`[WARN] Cannot read directory: ${dir}`);
      }
    };

    scan(dirPath);
    return files;
  }
}

export default CodeSnippetExtractor;
