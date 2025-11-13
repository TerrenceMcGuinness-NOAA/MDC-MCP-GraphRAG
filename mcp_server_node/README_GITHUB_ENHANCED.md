# Enhanced GitHub RAG MCP Server

## 🚀 Revolutionary MCP Integration

This enhanced MCP server combines the power of:
- **Local RAG Capabilities**: ChromaDB vector search across workflow documentation
- **GitHub API Integration**: Real-time access to NOAA-EMC repositories and submodules  
- **Cross-Repository Analysis**: Intelligent analysis across the entire global-workflow ecosystem
- **Comprehensive Documentation Access**: Live access to README files, issues, and code patterns

## 🎯 Key Capabilities

### **Core Global Workflow Tools**
- `get_workflow_structure` - System architecture overview
- `list_job_scripts` - Inventory of workflow job scripts  
- `get_system_configs` - HPC platform configurations
- `explain_component` - Component explanations with context

### **RAG-Enhanced Intelligence**
- `search_documentation` - Semantic search across workflow docs
- `explain_with_context` - RAG-enhanced explanations with examples
- `find_similar_code` - Vector-based code pattern matching
- `analyze_dependencies` - Workflow dependency analysis
- `get_operational_guidance` - HPC operational procedures

### **GitHub Integration Tools** ⭐ NEW
- `github_search_repositories` - Search NOAA-EMC repositories
- `github_get_repository_content` - Access files from any repository
- `github_search_code` - Cross-repository code pattern search
- `github_get_issues` - Repository issue analysis for troubleshooting
- `github_cross_repo_analysis` - Multi-repository dependency/pattern analysis

## 🌟 GitHub Integration Benefits

### **Live Submodule Access**
- **UFS Weather Model**: Real-time documentation and code access
- **GSI Data Assimilation**: Live access to GSI repository content
- **wxflow**: Direct access to workflow utility documentation
- **All NOAA-EMC Repos**: Comprehensive ecosystem coverage

### **Cross-Repository Intelligence**
```javascript
// Example: Find all repositories using a specific pattern
github_search_code({
  query: "rocoto xml", 
  language: "python", 
  org: "NOAA-EMC"
})

// Analyze dependencies across multiple repositories
github_cross_repo_analysis({
  analysis_type: "dependencies",
  repositories: ["global-workflow", "GSI", "UFS-weather-model"]
})
```

### **Issue-Driven Troubleshooting**
- Access live GitHub issues for troubleshooting context
- Cross-reference problems across related repositories
- Find solutions in issue discussions and comments

## 🔧 Usage Examples

### **1. Search for Workflow-Related Repositories**
```json
{
  "method": "tools/call",
  "params": {
    "name": "github_search_repositories",
    "arguments": {
      "query": "workflow",
      "org": "NOAA-EMC",
      "include_forks": false
    }
  }
}
```

### **2. Get Documentation from Submodules**
```json
{
  "method": "tools/call", 
  "params": {
    "name": "github_get_repository_content",
    "arguments": {
      "owner": "NOAA-EMC",
      "repo": "wxflow",
      "path": "README.md",
      "ref": "develop"
    }
  }
}
```

### **3. Cross-Repository Analysis**
```json
{
  "method": "tools/call",
  "params": {
    "name": "github_cross_repo_analysis", 
    "arguments": {
      "analysis_type": "documentation",
      "repositories": ["global-workflow", "GSI", "UFS-weather-model"],
      "search_term": "installation"
    }
  }
}
```

## 🚀 Quick Start

### **Basic Usage**
```bash
# Start the enhanced server
npm run start:github

# Or with development mode
npm run dev:github
```

### **With GitHub Authentication** (Recommended)
```bash
# Set your GitHub token for higher rate limits
export GITHUB_TOKEN="your_github_token"
npm run start:github
```

### **Available Scripts**
- `npm run start` - Basic MCP server
- `npm run start:rag` - RAG-enhanced server with ChromaDB
- `npm run start:github` - Full GitHub + RAG server ⭐
- `npm run dev:github` - Development mode with hot reload

## 🏗️ Architecture

```
Enhanced GitHub RAG Server
├── Core Workflow Tools
│   ├── Local filesystem access
│   ├── Job script enumeration  
│   └── System configuration
├── RAG Capabilities
│   ├── ChromaDB vector search
│   ├── Semantic document retrieval
│   └── Context-enhanced responses  
└── GitHub Integration ⭐ NEW
    ├── Repository search & access
    ├── Cross-repo code analysis
    ├── Issue tracking integration
    └── Live documentation access
```

## 🎯 Integration Impact

### **Before GitHub Integration**
- ❌ Limited to local filesystem content
- ❌ Static documentation snapshots  
- ❌ No access to submodule documentation
- ❌ No cross-repository pattern analysis

### **After GitHub Integration** ✅
- ✅ **Live Repository Access**: Real-time content from all NOAA-EMC repos
- ✅ **Submodule Documentation**: Direct access to UFS, GSI, wxflow docs
- ✅ **Cross-Repository Intelligence**: Pattern analysis across ecosystem
- ✅ **Issue-Driven Context**: GitHub issues for troubleshooting
- ✅ **Comprehensive Coverage**: 30+ NOAA-EMC repositories accessible

## 🔐 Security & Rate Limits

### **Authentication Options**
- **Unauthenticated**: 60 requests/hour (GitHub's public rate limit)
- **Authenticated**: 5,000 requests/hour with `GITHUB_TOKEN`

### **Token Setup**
```bash
# Create a GitHub Personal Access Token with 'public_repo' scope
export GITHUB_TOKEN="ghp_your_token_here"
```

## 📈 Performance Features

- **Intelligent Caching**: Reduces redundant GitHub API calls
- **Rate Limit Handling**: Graceful degradation when limits reached  
- **Parallel Processing**: Concurrent requests for cross-repo analysis
- **Error Recovery**: Fallback mechanisms for network issues

## 🔮 Future Enhancements

- **GitHub Actions Integration**: Access to workflow run logs and status
- **Pull Request Analysis**: Code change impact analysis across repositories
- **Advanced Caching**: Persistent cache for frequently accessed content
- **Webhook Integration**: Real-time updates when repositories change

---

**This enhanced server represents a quantum leap in global-workflow development assistance, providing unprecedented access to the entire NOAA-EMC ecosystem through intelligent GitHub integration.**
