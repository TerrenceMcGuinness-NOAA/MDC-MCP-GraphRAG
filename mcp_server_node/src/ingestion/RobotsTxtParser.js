#!/usr/bin/env node

/**
 * RobotsTxtParser - Parse and respect robots.txt directives
 *
 * Implements robots.txt protocol (RFC 9309) for respectful web crawling:
 * - User-agent matching and rule application
 * - Allow/Disallow path directives
 * - Crawl-delay enforcement
 * - Sitemap URL extraction
 * - URL pattern matching with wildcards
 *
 * @version 1.0.0
 * @author NOAA EMC Global Workflow Team
 */

export class RobotsTxtParser {
  constructor(robotsTxt, userAgent = 'NOAA-Global-Workflow-RAG') {
    this.userAgent = userAgent.toLowerCase();
    this.rules = {
      allow: [],
      disallow: [],
      crawlDelay: null,
      sitemaps: [],
      requestRate: null
    };

    if (robotsTxt) {
      this.parse(robotsTxt);
    }
  }

  /**
   * Parse robots.txt content
   */
  parse(robotsTxt) {
    const lines = robotsTxt.split(/\r?\n/);
    let currentUserAgent = null;
    let applicableToUs = false;

    for (let line of lines) {
      // Remove comments
      const commentIndex = line.indexOf('#');
      if (commentIndex !== -1) {
        line = line.substring(0, commentIndex);
      }

      line = line.trim();
      if (!line) continue;

      const colonIndex = line.indexOf(':');
      if (colonIndex === -1) continue;

      const directive = line.substring(0, colonIndex).trim().toLowerCase();
      const value = line.substring(colonIndex + 1).trim();

      switch (directive) {
        case 'user-agent':
          currentUserAgent = value.toLowerCase();
          // Check if this section applies to us
          applicableToUs = this._matchesUserAgent(currentUserAgent);
          break;

        case 'disallow':
          if (applicableToUs && value) {
            this.rules.disallow.push(this._normalizePattern(value));
          }
          break;

        case 'allow':
          if (applicableToUs && value) {
            this.rules.allow.push(this._normalizePattern(value));
          }
          break;

        case 'crawl-delay':
          if (applicableToUs) {
            const delay = parseFloat(value);
            if (!isNaN(delay) && delay > 0) {
              this.rules.crawlDelay = delay * 1000; // Convert to milliseconds
            }
          }
          break;

        case 'request-rate':
          if (applicableToUs) {
            // Format: "request-rate: requests/seconds"
            const match = value.match(/(\d+)\s*\/\s*(\d+)/);
            if (match) {
              const requests = parseInt(match[1]);
              const seconds = parseInt(match[2]);
              if (requests > 0 && seconds > 0) {
                this.rules.requestRate = { requests, seconds };
              }
            }
          }
          break;

        case 'sitemap':
          // Sitemaps apply globally, not per user-agent
          if (value) {
            this.rules.sitemaps.push(value);
          }
          break;
      }
    }

    // If no disallow rules, allow everything
    if (this.rules.disallow.length === 0 && this.rules.allow.length === 0) {
      this.rules.allow.push('/');
    }
  }

  /**
   * Check if a URL is allowed to be crawled
   */
  isAllowed(url) {
    try {
      const urlObj = new URL(url);
      const path = urlObj.pathname + urlObj.search;

      // Check allow rules first (they take precedence)
      for (const pattern of this.rules.allow) {
        if (this._matchesPattern(path, pattern)) {
          return true;
        }
      }

      // Check disallow rules
      for (const pattern of this.rules.disallow) {
        if (this._matchesPattern(path, pattern)) {
          return false;
        }
      }

      // If no rules matched and there are disallow rules, default to allowed
      // If only allow rules exist and none matched, default to disallowed
      return this.rules.disallow.length > 0 || this.rules.allow.length === 0;

    } catch (error) {
      // Invalid URL, disallow to be safe
      return false;
    }
  }

  /**
   * Get crawl delay in milliseconds
   */
  getCrawlDelay() {
    return this.rules.crawlDelay;
  }

  /**
   * Get request rate limit
   */
  getRequestRate() {
    return this.rules.requestRate;
  }

  /**
   * Get sitemap URLs
   */
  getSitemaps() {
    return this.rules.sitemaps;
  }

  /**
   * Check if user agent matches
   */
  _matchesUserAgent(ruleAgent) {
    // Wildcard matches all
    if (ruleAgent === '*') {
      return true;
    }

    // Exact match or prefix match
    return this.userAgent === ruleAgent || this.userAgent.startsWith(ruleAgent);
  }

  /**
   * Normalize path pattern
   */
  _normalizePattern(pattern) {
    // Remove leading/trailing whitespace
    pattern = pattern.trim();

    // Empty pattern matches nothing
    if (!pattern) {
      return null;
    }

    return pattern;
  }

  /**
   * Check if path matches pattern (with wildcards)
   */
  _matchesPattern(path, pattern) {
    if (!pattern) return false;

    // Convert robots.txt pattern to regex
    // * matches any sequence of characters
    // $ matches end of URL
    let regexPattern = pattern
      .replace(/[.+?^${}()|[\]\\]/g, '\\$&') // Escape special regex chars
      .replace(/\*/g, '.*'); // Convert * to .*

    // Handle end-of-URL marker ($)
    if (regexPattern.endsWith('$')) {
      regexPattern = '^' + regexPattern;
    } else {
      regexPattern = '^' + regexPattern;
    }

    try {
      const regex = new RegExp(regexPattern);
      return regex.test(path);
    } catch (error) {
      // Invalid regex, treat as literal string match
      return path.startsWith(pattern);
    }
  }

  /**
   * Get summary of parsed rules
   */
  getSummary() {
    return {
      userAgent: this.userAgent,
      allowedPatterns: this.rules.allow,
      disallowedPatterns: this.rules.disallow,
      crawlDelay: this.rules.crawlDelay,
      requestRate: this.rules.requestRate,
      sitemaps: this.rules.sitemaps
    };
  }

  /**
   * Static method to fetch and parse robots.txt from a domain
   */
  static async fetchAndParse(baseUrl, userAgent = 'NOAA-Global-Workflow-RAG') {
    try {
      const urlObj = new URL(baseUrl);
      const robotsUrl = `${urlObj.protocol}//${urlObj.host}/robots.txt`;

      const response = await fetch(robotsUrl, {
        headers: {
          'User-Agent': userAgent
        },
        signal: AbortSignal.timeout(5000) // 5 second timeout
      });

      if (!response.ok) {
        // No robots.txt or error fetching - allow all by default
        return new RobotsTxtParser('', userAgent);
      }

      const robotsTxt = await response.text();
      return new RobotsTxtParser(robotsTxt, userAgent);

    } catch (error) {
      // Network error or timeout - allow all by default
      console.warn(`[WARN] Could not fetch robots.txt from ${baseUrl}: ${error.message}`);
      return new RobotsTxtParser('', userAgent);
    }
  }
}
