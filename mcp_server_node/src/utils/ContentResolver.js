/**
 * ContentResolver.js - Universal Content Access Layer
 * 
 * Resolves content from multiple sources with a consistent interface.
 * Enables MCP tools to work with content regardless of origin:
 * - Direct content (passed via parameter)
 * - File arrays (batch processing)
 * - Local filesystem paths (fallback for local mode)
 * 
 * This abstraction layer solves the topology problem where:
 * - Remote MCP Gateway cannot access local HPC filesystems
 * - VS Code can read local files and pass content to remote MCP
 * - Tools work identically in local and remote deployments
 * 
 * @version 1.0.0
 * @author NOAA EMC Global Workflow Team
 * @see sdd_framework/workflows/phase19_content_abstraction_layer.md
 */

import fs from 'fs/promises';
import path from 'path';

/**
 * Resolved content structure returned by ContentResolver
 * @typedef {Object} ResolvedContent
 * @property {'single'|'multi'} type - Content type (single file or multiple)
 * @property {string} [content] - Content string (for single type)
 * @property {Array<ResolvedFile>} [files] - Array of files (for multi type)
 * @property {string} contentType - Detected or specified content type
 * @property {string} source - Content origin identifier
 * @property {Object} metadata - Additional metadata about the content
 */

/**
 * Individual file in multi-file resolution
 * @typedef {Object} ResolvedFile
 * @property {string} name - Filename
 * @property {string} [path] - Relative path (for context)
 * @property {string} content - File content
 * @property {string} contentType - Detected content type
 */

/**
 * ContentResolver - Universal content access layer for MCP tools
 * 
 * Priority order for resolution:
 * 1. content (direct string) - highest priority, works everywhere
 * 2. files (array of {name, path, content}) - batch mode
 * 3. path/file_path/repository_path - filesystem fallback (local only)
 */
export class ContentResolver {
  constructor(options = {}) {
    this.options = {
      // Default content type if not detected
      defaultContentType: options.defaultContentType || 'auto',
      // Whether to throw on path access failure or return error in metadata
      throwOnPathError: options.throwOnPathError !== false,
      // Maximum file size to read (prevent memory issues)
      maxFileSize: options.maxFileSize || 10 * 1024 * 1024, // 10MB
      // Allowed file extensions (security)
      allowedExtensions: options.allowedExtensions || null, // null = allow all
      ...options
    };
  }

  /**
   * Resolve content from tool parameters
   * 
   * @param {Object} params - Tool parameters
   * @param {string} [params.content] - Direct content string
   * @param {Array} [params.files] - Array of {name, path, content} objects
   * @param {string} [params.path] - Single file path
   * @param {string} [params.file_path] - Alternative path parameter name
   * @param {string} [params.repository_path] - Repository path for scanning
   * @param {string} [params.target] - Generic target (path or content)
   * @param {string} [params.content_type] - Content type hint
   * @param {string} [params.source_hint] - Source origin hint
   * @returns {Promise<ResolvedContent>}
   */
  async resolve(params) {
    // Priority 1: Direct content
    if (params.content && typeof params.content === 'string') {
      return this.fromDirect(params.content, params);
    }

    // Priority 2: Files array
    if (params.files && Array.isArray(params.files) && params.files.length > 0) {
      return this.fromFiles(params.files, params);
    }

    // Priority 3: Path-based resolution (various parameter names)
    const pathParam = params.path || params.file_path || params.repository_path || params.target;
    if (pathParam && typeof pathParam === 'string') {
      // Check if 'target' looks like content rather than a path
      if (params.target && this.looksLikeContent(params.target)) {
        return this.fromDirect(params.target, params);
      }
      return this.fromPath(pathParam, params);
    }

    // No valid input found
    throw new ContentResolverError(
      'MISSING_INPUT',
      "Either 'content', 'files', or 'path' parameter required. " +
      "For remote MCP access, use 'content' parameter with file contents."
    );
  }

  /**
   * Check if a string looks like content rather than a path
   * @param {string} value - String to check
   * @returns {boolean}
   */
  looksLikeContent(value) {
    // Multi-line strings are likely content
    if (value.includes('\n')) return true;
    // Shebang indicates script content
    if (value.startsWith('#!')) return true;
    // Very long strings are likely content
    if (value.length > 500) return true;
    // Contains code-like patterns
    if (/^(import |from |def |class |function |const |let |var |export )/.test(value)) return true;
    return false;
  }

  /**
   * Resolve from direct content string
   * @param {string} content - Content string
   * @param {Object} params - Original parameters
   * @returns {Promise<ResolvedContent>}
   */
  async fromDirect(content, params) {
    const contentType = params.content_type || this.detectType(content);
    
    return {
      type: 'single',
      content: content,
      contentType: contentType,
      source: params.source_hint || 'direct',
      metadata: {
        providedDirectly: true,
        contentLength: content.length,
        lineCount: content.split('\n').length
      }
    };
  }

  /**
   * Resolve from files array
   * @param {Array} files - Array of file objects
   * @param {Object} params - Original parameters
   * @returns {Promise<ResolvedContent>}
   */
  async fromFiles(files, params) {
    const resolvedFiles = files.map(f => ({
      name: f.name || 'unnamed',
      path: f.path || f.name || 'unknown',
      content: f.content || '',
      contentType: params.content_type || this.detectType(f.content || '', f.name || '')
    }));

    return {
      type: 'multi',
      files: resolvedFiles,
      contentType: params.content_type || 'mixed',
      source: params.source_hint || 'batch',
      metadata: {
        fileCount: resolvedFiles.length,
        totalSize: resolvedFiles.reduce((sum, f) => sum + f.content.length, 0),
        fileTypes: [...new Set(resolvedFiles.map(f => f.contentType))]
      }
    };
  }

  /**
   * Resolve from filesystem path
   * @param {string} targetPath - File or directory path
   * @param {Object} params - Original parameters
   * @returns {Promise<ResolvedContent>}
   */
  async fromPath(targetPath, params) {
    try {
      const stat = await fs.stat(targetPath);
      
      if (stat.isDirectory()) {
        return this.fromDirectory(targetPath, params);
      } else {
        return this.fromFile(targetPath, params);
      }
    } catch (err) {
      const error = new ContentResolverError(
        'PATH_ACCESS_FAILED',
        `Cannot access path '${targetPath}': ${err.message}. ` +
        `For remote MCP access, use 'content' parameter instead of 'path'.`,
        { originalError: err.message, path: targetPath }
      );

      if (this.options.throwOnPathError) {
        throw error;
      }

      // Return error in metadata for graceful handling
      return {
        type: 'error',
        content: null,
        contentType: 'error',
        source: 'path_failed',
        metadata: {
          error: error.message,
          errorCode: error.code,
          requestedPath: targetPath,
          suggestion: "Use 'content' parameter for remote access"
        }
      };
    }
  }

  /**
   * Read a single file
   * @param {string} filePath - File path
   * @param {Object} params - Original parameters
   * @returns {Promise<ResolvedContent>}
   */
  async fromFile(filePath, params) {
    // Security check: file extension
    if (this.options.allowedExtensions) {
      const ext = path.extname(filePath).toLowerCase();
      if (!this.options.allowedExtensions.includes(ext)) {
        throw new ContentResolverError(
          'DISALLOWED_EXTENSION',
          `File extension '${ext}' is not allowed`,
          { path: filePath, extension: ext }
        );
      }
    }

    // Size check
    const stat = await fs.stat(filePath);
    if (stat.size > this.options.maxFileSize) {
      throw new ContentResolverError(
        'FILE_TOO_LARGE',
        `File size ${stat.size} exceeds maximum ${this.options.maxFileSize}`,
        { path: filePath, size: stat.size, maxSize: this.options.maxFileSize }
      );
    }

    const content = await fs.readFile(filePath, 'utf8');
    const contentType = params.content_type || this.detectType(content, filePath);

    return {
      type: 'single',
      content: content,
      contentType: contentType,
      source: 'local_fs',
      metadata: {
        originalPath: filePath,
        absolutePath: path.resolve(filePath),
        filename: path.basename(filePath),
        extension: path.extname(filePath),
        size: stat.size,
        lineCount: content.split('\n').length
      }
    };
  }

  /**
   * Scan a directory for files
   * @param {string} dirPath - Directory path
   * @param {Object} params - Original parameters
   * @returns {Promise<ResolvedContent>}
   */
  async fromDirectory(dirPath, params) {
    const files = await this.scanDirectory(dirPath, params);
    
    if (files.length === 0) {
      return {
        type: 'multi',
        files: [],
        contentType: 'empty',
        source: 'local_fs',
        metadata: {
          originalPath: dirPath,
          fileCount: 0,
          message: 'No matching files found in directory'
        }
      };
    }

    return {
      type: 'multi',
      files: files,
      contentType: params.content_type || 'mixed',
      source: 'local_fs',
      metadata: {
        originalPath: dirPath,
        fileCount: files.length,
        totalSize: files.reduce((sum, f) => sum + f.content.length, 0),
        fileTypes: [...new Set(files.map(f => f.contentType))]
      }
    };
  }

  /**
   * Recursively scan directory for code files
   * @param {string} dirPath - Directory path
   * @param {Object} params - Parameters with optional filters
   * @returns {Promise<Array<ResolvedFile>>}
   */
  async scanDirectory(dirPath, params) {
    const results = [];
    const maxFiles = params.max_files || 100;
    const extensions = params.extensions || ['.sh', '.py', '.js', '.yaml', '.yml', '.json', '.f90', '.F90'];
    const excludeDirs = params.exclude_dirs || ['node_modules', '.git', '__pycache__', 'build', 'dist'];

    const scan = async (currentPath, relativePath = '') => {
      if (results.length >= maxFiles) return;

      const entries = await fs.readdir(currentPath, { withFileTypes: true });

      for (const entry of entries) {
        if (results.length >= maxFiles) break;

        const fullPath = path.join(currentPath, entry.name);
        const relPath = path.join(relativePath, entry.name);

        if (entry.isDirectory()) {
          if (!excludeDirs.includes(entry.name)) {
            await scan(fullPath, relPath);
          }
        } else if (entry.isFile()) {
          const ext = path.extname(entry.name).toLowerCase();
          if (extensions.includes(ext)) {
            try {
              const stat = await fs.stat(fullPath);
              if (stat.size <= this.options.maxFileSize) {
                const content = await fs.readFile(fullPath, 'utf8');
                results.push({
                  name: entry.name,
                  path: relPath,
                  content: content,
                  contentType: this.detectType(content, entry.name)
                });
              }
            } catch (err) {
              // Skip files that can't be read
              console.error(`[WARN] Skipping unreadable file: ${fullPath}`);
            }
          }
        }
      }
    };

    await scan(dirPath);
    return results;
  }

  /**
   * Detect content type from content and/or filename
   * @param {string} content - File content
   * @param {string} [filename] - Optional filename for extension detection
   * @returns {string} - Content type identifier
   */
  detectType(content, filename = '') {
    // Extension-based detection
    const ext = path.extname(filename).toLowerCase();
    const extMap = {
      '.sh': 'bash',
      '.bash': 'bash',
      '.py': 'python',
      '.js': 'javascript',
      '.mjs': 'javascript',
      '.ts': 'typescript',
      '.yaml': 'yaml',
      '.yml': 'yaml',
      '.json': 'json',
      '.f90': 'fortran',
      '.F90': 'fortran',
      '.f': 'fortran',
      '.F': 'fortran',
      '.md': 'markdown',
      '.xml': 'xml',
      '.toml': 'toml',
      '.cfg': 'config',
      '.ini': 'config',
      '.conf': 'config'
    };

    if (ext && extMap[ext]) {
      return extMap[ext];
    }

    // Content-based detection (shebang)
    if (content.startsWith('#!/bin/bash') || content.startsWith('#!/usr/bin/env bash')) {
      return 'bash';
    }
    if (content.startsWith('#!/usr/bin/env python') || content.startsWith('#!/usr/bin/python')) {
      return 'python';
    }
    if (content.startsWith('#!/usr/bin/env node') || content.startsWith('#!/usr/bin/node')) {
      return 'javascript';
    }

    // Pattern-based detection
    if (/^(import |from .+ import |def |class )/.test(content)) {
      return 'python';
    }
    if (/^(const |let |var |import |export |function )/.test(content)) {
      return 'javascript';
    }
    if (/^(program |subroutine |module |use )/i.test(content)) {
      return 'fortran';
    }
    if (content.trim().startsWith('{') || content.trim().startsWith('[')) {
      try {
        JSON.parse(content);
        return 'json';
      } catch {
        // Not valid JSON
      }
    }
    if (/^[a-zA-Z_]+:/.test(content.trim())) {
      return 'yaml';
    }

    return 'auto';
  }

  /**
   * Utility: Check if content was resolved successfully
   * @param {ResolvedContent} resolved - Resolution result
   * @returns {boolean}
   */
  static isResolved(resolved) {
    return resolved && resolved.type !== 'error' && (resolved.content || resolved.files);
  }

  /**
   * Utility: Get all content as a single string (for single or multi)
   * @param {ResolvedContent} resolved - Resolution result
   * @param {string} [separator] - Separator for multi-file content
   * @returns {string}
   */
  static getAllContent(resolved, separator = '\n\n---\n\n') {
    if (resolved.type === 'single') {
      return resolved.content;
    }
    if (resolved.type === 'multi') {
      return resolved.files
        .map(f => `# File: ${f.path || f.name}\n${f.content}`)
        .join(separator);
    }
    return '';
  }

  /**
   * Utility: Iterate over all files in resolved content
   * @param {ResolvedContent} resolved - Resolution result
   * @yields {ResolvedFile}
   */
  static *iterateFiles(resolved) {
    if (resolved.type === 'single') {
      yield {
        name: resolved.metadata?.filename || 'content',
        path: resolved.metadata?.originalPath || 'direct',
        content: resolved.content,
        contentType: resolved.contentType
      };
    } else if (resolved.type === 'multi') {
      for (const file of resolved.files) {
        yield file;
      }
    }
  }
}

/**
 * Custom error class for ContentResolver
 */
export class ContentResolverError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = 'ContentResolverError';
    this.code = code;
    this.details = details;
  }

  toJSON() {
    return {
      error: this.name,
      code: this.code,
      message: this.message,
      details: this.details
    };
  }
}

// Default export for convenience
export default ContentResolver;
