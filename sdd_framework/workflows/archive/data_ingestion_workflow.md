# Documentation Ingestion Guide

Complete guide for ingesting external documentation into the RAG vector store.

## Table of Contents
1. [Quick Start](#quick-start)
2. [URL Extraction](#url-extraction)
3. [URL List Ingestion](#url-list-ingestion)
4. [Testing Integration](#testing-integration)
5. [Troubleshooting](#troubleshooting)

---

## Quick Start

**3-Step Ingestion Process:**

```bash
cd dev/ci/scripts/utils/Copilot/mcp_server_node

# 1. Extract URLs from sitemap
node scripts/extract-sitemap-urls.js https://example.com/docs/ \
  -o extracted-urls/example-urls.txt \
  --show-metadata

# 2. Ingest URLs into vector store
node scripts/ingest-from-url-list.js extracted-urls/example-urls.txt \
  --mode direct \
  --collection example-docs

# 3. Verify stored chunks
cat src/knowledge-base/external_documentation_chunks.json | jq 'length'
```

---

## URL Extraction

### Basic Usage

Extract all URLs from a documentation site:

```bash
node scripts/extract-sitemap-urls.js <base-url> [options]
```

### Examples

**Extract with metadata:**
```bash
node scripts/extract-sitemap-urls.js https://spack.readthedocs.io/en/latest/ \
  -o extracted-urls/spack-all-urls.txt \
  --show-metadata
```

**Filter by pattern:**
```bash
node scripts/extract-sitemap-urls.js https://python.org/docs/ \
  -o extracted-urls/python-tutorial.txt \
  --filter "tutorial" \
  --exclude "archives,download"
```

**JSON output:**
```bash
node scripts/extract-sitemap-urls.js https://docs.example.com \
  -o extracted-urls/example.json \
  --format json
```

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `-o, --output <file>` | Output file path | `extracted-urls.txt` |
| `--filter <pattern>` | Include only URLs matching pattern | none |
| `--exclude <patterns>` | Comma-separated exclusion patterns | none |
| `--show-metadata` | Include priority, lastmod, changefreq | false |
| `--format <txt\|json>` | Output format | `txt` |

### Output Format

**Text with metadata:**
```
https://spack.readthedocs.io/en/latest/
# priority: 1
# lastmod: 2025-10-15T00:20:41.107933+00:00
# changefreq: weekly

https://spack.readthedocs.io/en/v1.0.2/
# priority: 0.8
# changefreq: monthly
```

**JSON:**
```json
[
  {
    "url": "https://spack.readthedocs.io/en/latest/",
    "priority": 1,
    "lastmod": "2025-10-15T00:20:41.107933+00:00",
    "changefreq": "weekly"
  }
]
```

---

## URL List Ingestion

### Processing Modes

**Direct Mode** (recommended):
- Processes only the listed URLs
- Fast and predictable
- Best for curated URL lists

**Crawl Mode**:
- Uses URLs as crawl seeds
- Discovers related pages
- More comprehensive but slower

### Basic Usage

```bash
node scripts/ingest-from-url-list.js <url-file> [options]
```

### Examples

**Direct ingestion (recommended):**
```bash
node scripts/ingest-from-url-list.js extracted-urls/spack-all-urls.txt \
  --mode direct \
  --collection spack-docs
```

**Crawl mode with discovery:**
```bash
node scripts/ingest-from-url-list.js extracted-urls/seeds.txt \
  --mode crawl \
  --crawl-depth 2 \
  --crawl-max-pages 100
```

**Dry run (test without storing):**
```bash
node scripts/ingest-from-url-list.js extracted-urls/test.txt \
  --mode direct \
  --dry-run
```

**Custom quality and batch size:**
```bash
node scripts/ingest-from-url-list.js extracted-urls/docs.txt \
  --mode direct \
  --quality 0.6 \
  --batch-size 5
```

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `--mode <direct\|crawl>` | Processing mode | `direct` |
| `--collection <name>` | Collection name | `external-docs` |
| `--batch-size <n>` | URLs per batch | `10` |
| `--quality <n>` | Quality threshold (0-1) | `0.4` |
| `--crawl-depth <n>` | Max crawl depth (crawl mode) | `3` |
| `--crawl-max-pages <n>` | Max pages (crawl mode) | `1000` |
| `--crawl-strategy <bfs\|dfs>` | Crawl strategy | `bfs` |
| `--dry-run` | Test without storing | `false` |

### Output

**Progress indicators:**
```
📚 Starting documentation ingestion...
📦 Processing batch 1/1 (3 URLs)
🧠 Using semantic HTML chunking for: https://spack.readthedocs.io/en/latest/
```

**Summary statistics:**
```
📚 DOCUMENTATION INGESTION COMPLETE
════════════════════════════════════
⏱️  Total Time: 1.3s
📊 URLs Processed: 3
✅ Successful: 3 (100.0%)
❌ Failed: 0
📄 Total Chunks: 47
📏 Total Content: 0.1 MB
⭐ Avg Quality Score: 73.6%
📈 Processing Rate: 2.38 URLs/s
```

---

## Testing Integration

### Test Script

Use `test-deep-crawl.js` to validate the complete pipeline:

```bash
node scripts/test-deep-crawl.js --url <base-url> --depth <n> --pages <n>
```

**Example:**
```bash
node scripts/test-deep-crawl.js \
  --url https://spack.readthedocs.io/en/latest/ \
  --depth 1 \
  --pages 3
```

### Validation

**Analyze stored chunks:**
```bash
# Count total chunks
cat src/knowledge-base/external_documentation_chunks.json | jq 'length'

# Group by source
cat src/knowledge-base/external_documentation_chunks.json | \
  jq 'group_by(.metadata.source) | map({source: .[0].metadata.source, count: length})'

# Calculate average quality
cat src/knowledge-base/external_documentation_chunks.json | \
  jq '[.[].qualityScore] | add / length'

# Find chunk types
cat src/knowledge-base/external_documentation_chunks.json | \
  jq '[.[].metadata.chunkType] | group_by(.) | map({type: .[0], count: length})'
```

---

## Troubleshooting

### Common Issues

**Problem: "Cache write failed"**
```
Cache write failed for https://example.com: ENOENT: no such file or directory
```

**Solution:** Create cache directory:
```bash
mkdir -p knowledge-base/cache
```

---

**Problem: "Could not load existing knowledge base"**
```
⚠️ Could not load existing knowledge base: ENOENT
```

**Solution:** This is normal on first run. The file will be created during ingestion.

---

**Problem: "Total chunks in store: 0"**

**Solution:** Check that:
1. URLs are accessible and return HTML
2. Quality threshold isn't too high (`--quality 0.4` or lower)
3. URLs aren't being filtered by robots.txt

---

**Problem: Low quality scores**

**Solution:**
- Lower quality threshold: `--quality 0.3`
- Check if pages have proper semantic structure
- Try different URLs from the documentation

---

### Debug Tips

**Enable verbose output:**
```bash
DEBUG=* node scripts/ingest-from-url-list.js urls.txt --mode direct
```

**Check individual URLs:**
```bash
# Test single URL
echo "https://example.com/docs/" > test.txt
node scripts/ingest-from-url-list.js test.txt --mode direct --dry-run
```

**Validate URL list:**
```bash
# Check file contents
cat extracted-urls/my-urls.txt

# Count URLs (excluding comments)
grep -v '^#' extracted-urls/my-urls.txt | wc -l
```

---

## File Locations

**Scripts:**
- `scripts/extract-sitemap-urls.js` - URL extraction
- `scripts/ingest-from-url-list.js` - Ingestion pipeline
- `scripts/test-deep-crawl.js` - Integration testing

**Data:**
- `extracted-urls/` - URL lists (create if needed)
- `src/knowledge-base/external_documentation_chunks.json` - Stored chunks
- `knowledge-base/cache/` - URL fetch cache

**Configuration:**
- Quality threshold: 0.4 (40% minimum)
- Batch size: 10 URLs per batch
- Target chunk size: 1500 characters
- Max chunk size: 3000 characters

---

## Production Workflow

**Recommended workflow for adding new documentation:**

```bash
# 1. Extract URLs
node scripts/extract-sitemap-urls.js https://docs.example.com \
  -o extracted-urls/example-urls.txt \
  --show-metadata

# 2. Review URLs
cat extracted-urls/example-urls.txt

# 3. Test with dry-run
node scripts/ingest-from-url-list.js extracted-urls/example-urls.txt \
  --mode direct \
  --dry-run

# 4. Ingest for real
node scripts/ingest-from-url-list.js extracted-urls/example-urls.txt \
  --mode direct \
  --collection example-docs

# 5. Verify results
cat src/knowledge-base/external_documentation_chunks.json | \
  jq '[.[] | select(.metadata.source | startswith("https://docs.example.com"))] | length'
```

---

## Performance Characteristics

**Tested Performance (3 URLs, Spack docs):**
- Processing: 2.38 URLs/sec
- Total time: 1.3s
- Chunks generated: 47
- Average quality: 73.6%
- Average chunk size: 1744 chars
- Success rate: 100%

**Expected Performance:**
- Small sites (< 10 pages): < 5 seconds
- Medium sites (10-100 pages): 5-60 seconds
- Large sites (100-1000 pages): 1-10 minutes

**Optimization Tips:**
- Use direct mode for known URL lists
- Increase batch size for faster processing: `--batch-size 20`
- Lower quality threshold for more chunks: `--quality 0.3`
- Enable caching by ensuring `knowledge-base/cache/` exists

---

## Next Steps

After ingesting documentation:

1. **Test Retrieval**: Query the vector store to verify chunks are accessible
2. **Generate Embeddings**: Ensure semantic search is enabled
3. **Validate Quality**: Review sample chunks for accuracy
4. **Update Index**: Rebuild search indexes if needed
5. **Monitor Usage**: Track retrieval quality and user feedback
