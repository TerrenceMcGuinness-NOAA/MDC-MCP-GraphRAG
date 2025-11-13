# Tests Directory

This directory contains all test scripts for the MCP Server Node.js RAG system.

## Structure

### `/integration/`
Integration tests that validate end-to-end functionality and external system compatibility:
- `test-vscode-integration.js` - VS Code extension integration tests
- `test-copilot-integration.py` - GitHub Copilot integration tests

### `/unit/`
Unit tests for individual components and modules:
- `test-rag.js` - RAG functionality tests
- `test-ee2.js` - EE2 embedding tests
- `test-system-integrity.js` - System integrity checks
- `test-docs-refs.js` - Documentation reference tests
- `test-standards.js` - Code standards compliance tests

## Running Tests

### JavaScript Tests
```bash
# Run all tests
npm test

# Run specific test
node tests/unit/test-rag.js
node tests/integration/test-vscode-integration.js
```

### Python Tests
```bash
# Run Python integration tests
python3 tests/integration/test-copilot-integration.py
```

## Test Categories

- **Unit Tests**: Test individual functions and modules in isolation
- **Integration Tests**: Test component interactions and external dependencies
- **System Tests**: End-to-end validation of complete workflows

## Contributing

When adding new tests:
1. Place unit tests in `/unit/` directory
2. Place integration tests in `/integration/` directory
3. Follow existing naming convention: `test-[component].js` or `test-[component].py`
4. Include comprehensive docstrings and comments
5. Update this README when adding new test categories
