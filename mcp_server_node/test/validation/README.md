# Validation Directory

This directory contains all validation and verification scripts for the MCP Server Node.js RAG system.

## Scripts

### URL Validation
- `validate-urls.js` - Validates accessibility and responsiveness of documentation URLs
- `check-url-relevance.py` - Analyzes URL content relevance to the Global Workflow ecosystem

### Data Quality
- `check-redundancies.py` - Identifies duplicate URLs and overlapping content in documentation references

## Result Files

### Analysis Reports
- `redundancy-analysis.json` - Detailed redundancy analysis results
- `url-validation-results.json` - URL accessibility validation results
- `url-relevance-check.json` - URL content relevance analysis
- `submodule-documentation-analysis.json` - Submodule documentation analysis

## Usage

### URL Validation
```bash
# Validate all URLs in documentation-references.json
node validation/validate-urls.js

# Verbose output
node validation/validate-urls.js --verbose
```

### Redundancy Check
```bash
# Check for duplicate and redundant URLs
python3 validation/check-redundancies.py
```

### Relevance Analysis
```bash
# Analyze URL content relevance
python3 validation/check-url-relevance.py
```

## Quality Assurance Workflow

1. **URL Validation**: Ensure all documentation URLs are accessible
2. **Redundancy Check**: Remove duplicate entries to optimize collection
3. **Relevance Analysis**: Verify content alignment with Global Workflow ecosystem
4. **Documentation Update**: Reflect changes in documentation-references.json

## Validation Standards

- **URL Accessibility**: All URLs must return HTTP 200 status
- **Content Relevance**: URLs must contain Global Workflow related content
- **No Duplicates**: Eliminate exact duplicate URLs and overlapping content
- **Performance**: Validation should complete within reasonable time limits

## Contributing

When adding validation scripts:
1. Follow naming convention: `validate-[component].js` or `check-[component].py`
2. Generate JSON reports for programmatic analysis
3. Include both summary and detailed output options
4. Document usage and expected results
5. Update this README with new validation procedures
