# Deep Crawl Test Script Documentation

## Overview
`test-deep-crawl.js` validates the integration of deep web crawling with semantic chunking for documentation ingestion.

## What It Tests

### 1. Web Crawling Infrastructure
- **WebCrawler**: Recursive link following with robots.txt compliance
- **RobotsTxtParser**: RFC 9309 compliant robots.txt parsing and enforcement
- **SitemapParser**: XML sitemap discovery and parsing
- **URL Management**: Deduplication, domain filtering, depth tracking

### 2. Semantic Chunking (Context7 Methodology)
- **Code Preservation**: Entire code blocks kept intact
- **Example Preservation**: Explanations + code kept together
- **Context Windows**: Parent headers included in chunks
- **Header Boundaries**: Sections split at natural boundaries
- **List Integrity**: Complete lists as single chunks

### 3. Integration Pipeline
- **DocumentationIngester.crawlAndIngest()**: Orchestration and batch processing
- **ContentExtractor.createChunks()**: Semantic vs fallback chunking
- **Quality Filtering**: Chunks scored and filtered by quality

## Usage

### Basic Test (Default Settings)
```bash
node scripts/test-deep-crawl.js
```

**Defaults:**
- URL: https://noaa-emc.github.io/global-workflow/
- Max Depth: 2 levels
- Max Pages: 50 pages

### Custom Depth
```bash
node scripts/test-deep-crawl.js --depth 3
```
Crawls up to 3 levels deep from seed URL.

### Custom Page Limit
```bash
node scripts/test-deep-crawl.js --pages 100
```
Crawls up to 100 pages (prevents runaway crawls on large sites).

### Custom URL
```bash
node scripts/test-deep-crawl.js --url https://noaa-emc.github.io/ufs-weather-model/
```
Crawls specified documentation site.

### Combined Options
```bash
node scripts/test-deep-crawl.js --url https://example.com/docs/ --depth 4 --pages 200
```

## Output Format

### 1. Crawl Results
```
📊 CRAWL RESULTS
==================================================
Crawl Statistics:
  Pages Discovered: 73
  Pages Crawled: 50
  Pages Skipped: 20
  Errors: 3
  Duration: 45.23s
  Speed: 1.11 pages/sec

Ingestion Statistics:
  Total Processed: 50
  Successful: 47
  Failed: 3
```

### 2. Content Analysis
```
🔍 CONTENT ANALYSIS
==================================================
Total Chunks: 342
Average Chunk Size: 1487 chars
Average Quality Score: 0.723
Average Section Depth: 2.34

Chunk Types:
  section: 185 (54.1%)
  subsection: 98 (28.7%)
  code_example: 42 (12.3%)
  example: 12 (3.5%)
  list: 5 (1.5%)

Content Features:
  Chunks with Code: 54
  Chunks with Tables: 12
  Chunks with Lists: 23
  Example Chunks: 12
```

### 3. Semantic Validation
```
✅ SEMANTIC CHUNKING VALIDATION
==================================================
Context7 Features:
  Code Preservation: ✓
  Example Preservation: ✓
  Context Windows: ✓
  Header Boundaries: ✓
  List Integrity: ✓
```

### 4. Sample Chunks
```
📄 SAMPLE CHUNKS
==================================================
Chunk Type: code_example
Section Path: Installation > Quick Start > Environment Setup
Quality Score: 0.842
Content Preview (1234 chars):
Setting up the environment requires loading the appropriate modules...
```

### 5. Results File
Detailed JSON results saved to `test-results/crawl-test-[timestamp].json`:
```json
{
  "processed": 50,
  "successful": 47,
  "failed": 3,
  "crawlStats": {
    "discovered": 73,
    "crawled": 50,
    "skipped": 20,
    "errors": 3
  },
  "results": [
    {
      "success": true,
      "url": "https://example.com/doc1",
      "chunks": [
        {
          "content": "...",
          "metadata": {
            "chunkType": "section",
            "sectionPath": "...",
            "hasCode": true,
            ...
          },
          "qualityScore": 0.842
        }
      ]
    }
  ]
}
```

## Validation Criteria

### ✅ Pass Conditions
1. **Crawl Success**: Discovered pages > 0, Crawled pages > 0
2. **Chunking Success**: Total chunks > 0, Average quality > 0.5
3. **Semantic Features**: At least 3 of 5 Context7 features detected
4. **Content Diversity**: Multiple chunk types present
5. **No Fatal Errors**: Script completes with exit code 0

### ⚠️ Warning Conditions
- Some semantic features not detected (may need more content)
- High skip rate (>50% pages skipped)
- Low quality scores (<0.5 average)
- High error rate (>10% failed)

### ❌ Fail Conditions
- No pages crawled
- No chunks generated
- Script crashes or throws uncaught errors
- Exit code 1

## Interpreting Results

### Chunk Types
- **section**: Top-level section (H1-H2 headers)
- **subsection**: Nested section (H3-H6 headers)
- **code_example**: Pure code block with syntax highlighting
- **example**: Explanation + code block together
- **list**: List structure (ordered/unordered)
- **table**: Table structure
- **paragraph**: Plain text paragraph

### Quality Scores
- **0.8-1.0**: Excellent (well-structured, rich content)
- **0.6-0.8**: Good (decent structure, useful content)
- **0.4-0.6**: Fair (minimal structure, basic content)
- **0.0-0.4**: Poor (low structure, questionable content)

### Section Depth
- **1-2**: Flat documentation (few nested sections)
- **2-4**: Typical documentation (moderate hierarchy)
- **4+**: Deep documentation (highly nested structure)

## Troubleshooting

### "No pages crawled"
- Check robots.txt compliance: Site may disallow crawling
- Check URL accessibility: Site may be down or require authentication
- Check network connectivity: Firewall or proxy issues

### "No chunks generated"
- Check content type: Script expects HTML documentation
- Check minContentLength: Content may be too short
- Check quality score threshold: May be filtering out all chunks

### "Semantic features not detected"
- Normal for simple documentation: Not all docs have code/examples
- Try different URL: Choose docs with code examples and structure
- Check content: Ensure HTML has proper structure (headers, code blocks)

### High error rate
- Check crawl speed: May be hitting rate limits
- Check robots.txt: May be accessing disallowed paths
- Check URL patterns: excludePatterns may be too aggressive

## Performance Guidelines

### Small Sites (< 50 pages)
```bash
node scripts/test-deep-crawl.js --depth 5 --pages 100
```
- Fast crawl, comprehensive coverage
- Good for initial testing

### Medium Sites (50-200 pages)
```bash
node scripts/test-deep-crawl.js --depth 3 --pages 100
```
- Balanced speed and coverage
- Recommended for most testing

### Large Sites (> 200 pages)
```bash
node scripts/test-deep-crawl.js --depth 2 --pages 50
```
- Quick validation, sample coverage
- Use for development testing

### Production Ingestion
```javascript
// Use in production code with full settings
const ingester = new DocumentationIngester({
  enableDeepCrawl: true,
  crawlMaxDepth: 5,
  crawlMaxPages: 1000,
  enableSemanticChunking: true,
  crawlDelay: 1000,
  respectRobotsTxt: true
});
```

## Next Steps After Testing

1. **Validation**: Verify all semantic features detected
2. **Quality Check**: Review sample chunks for structure preservation
3. **Performance Tuning**: Adjust depth, pages, concurrency for optimal speed
4. **Production Config**: Update documentation-references.json with validated URLs
5. **Full Ingestion**: Run production ingestion with validated configuration
6. **Retrieval Testing**: Query the ingested content to validate retrieval quality

## Related Documentation
- `DOCUMENTATION_INGESTION_ENHANCEMENT.md` - Complete architecture and design
- `changelog.md` - Integration history and changes
- `documentation-references.json` - URL configuration and priorities
- `src/ingestion/WebCrawler.js` - Crawling implementation
- `src/ingestion/SemanticChunker.js` - Semantic chunking implementation
