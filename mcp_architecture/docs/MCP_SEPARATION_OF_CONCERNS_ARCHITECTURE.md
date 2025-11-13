#!/usr/bin/env node

/**
 * MCP Architecture Documentation: Separation of Concerns
 * 
 * CLEAR BOUNDARIES - NO MORE CONFUSION!
 * 
 * This document establishes the authoritative separation of concerns
 * for the MCP-RAG system to prevent future architectural confusion.
 * 
 * @version 1.0.0
 * @author Claude Sonnet 4.5
 * @supervisor Terry McGuinness
 * @date 2025-11-13
 */

# MCP Architecture: Separation of Concerns

## ❌ **PREVIOUS ISSUE: Mixed Responsibilities**

The `health_check` confusion revealed a fundamental architectural problem:
- Server-level utilities were mixed with tool-specific functionality
- Developers couldn't tell where functions belonged
- Duplicate responsibilities across classes
- Unclear ownership of system management vs domain logic

## ✅ **NEW ARCHITECTURE: Clear Boundaries**

### **Layer 1: Server Management** (`ServerUtilities.js`)
**Responsibility**: System lifecycle, health, status, configuration
```javascript
// ONLY server-level concerns
class ServerUtilities {
  healthCheck()        // System health across ALL components
  getServerInfo()      // Server configuration and capabilities
  getSystemStatistics() // Cross-component statistics
  registerServerUtilities() // Register server tools with MCP
}
```

**Tools Registered**:
- `get_server_info` - Server configuration and tool inventory
- `health_check` - System-wide health monitoring

### **Layer 2: Domain Tool Modules** (`tools/`)
**Responsibility**: Domain-specific functionality ONLY
```javascript
// ONLY domain logic - NO server management
class WorkflowInfoTools {
  getWorkflowStructure() // Domain: workflow structure
  getSystemConfigs()     // Domain: platform configs
  describeComponent()    // Domain: component descriptions
}

class OperationalTools {
  getOperationalGuidance()   // Domain: HPC procedures  
  explainWorkflowComponent() // Domain: component explanations
  listJobScripts()          // Domain: job inventory
}

// etc.
```

**What Tool Classes DO NOT Have**:
- ❌ `health_check()` methods
- ❌ `getStatus()` methods  
- ❌ Server configuration logic
- ❌ Cross-component health monitoring
- ❌ System statistics collection

### **Layer 3: Data Access** (`data/UnifiedDataAccess.js`)
**Responsibility**: Database connections and data retrieval
```javascript
class UnifiedDataAccess {
  connect()          // Database connections
  hybridQuery()      // Vector + graph search
  getVectorStats()   // Database statistics
  getGraphStats()    // Graph statistics
}
```

### **Layer 4: Base Infrastructure** (`core/BaseServer.js`)
**Responsibility**: MCP protocol handling
```javascript
class BaseServer {
  registerTool()     // MCP tool registration
  start()           // MCP protocol startup
  getStats()        // Basic server stats
}
```

## 🏗️ **Architecture Benefits**

### **Clear Ownership**
- **Server utilities**: `ServerUtilities` class
- **Domain tools**: Individual tool classes
- **Data access**: `UnifiedDataAccess` class
- **Protocol**: `BaseServer` class

### **No More Confusion**
- Developers know exactly where to find functionality
- No duplicate responsibilities
- Clear testing boundaries
- Predictable error handling

### **Easy Debugging**
```bash
# Tool not working? Check the right layer:
- Tool logic issue → Check tool class (e.g., OperationalTools.js)
- Server health issue → Check ServerUtilities.js  
- Database issue → Check UnifiedDataAccess.js
- MCP protocol issue → Check BaseServer.js
```

## 🔧 **Development Guidelines**

### **When Adding New Functionality**

**❓ Ask: "What layer does this belong to?"**

- **System health/status/info** → `ServerUtilities.js`
- **Workflow/operational domain logic** → Appropriate tool class
- **Database queries** → `UnifiedDataAccess.js`
- **MCP protocol handling** → `BaseServer.js`

### **Red Flags (Don't Do This)**
```javascript
// ❌ DON'T: Health check in tool class
class OperationalTools {
  healthCheck() { /* NO! This belongs in ServerUtilities */ }
}

// ❌ DON'T: Server info in tool class  
class SemanticSearchTools {
  getServerStatus() { /* NO! This belongs in ServerUtilities */ }
}

// ❌ DON'T: Database logic in server utilities
class ServerUtilities {
  queryVectorDB() { /* NO! This belongs in UnifiedDataAccess */ }
}
```

### **Green Lights (Do This)**
```javascript
// ✅ DO: Server utilities in dedicated class
class ServerUtilities {
  healthCheck() { /* YES! Check ALL components */ }
}

// ✅ DO: Domain logic in tool classes
class OperationalTools {
  getOperationalGuidance() { /* YES! Pure domain logic */ }
}

// ✅ DO: Database logic in data access layer
class UnifiedDataAccess {
  hybridQuery() { /* YES! Database operations */ }
}
```

## 📋 **Testing Strategy**

### **Unit Testing by Layer**
- **ServerUtilities**: Mock tool modules, test health aggregation
- **Tool Classes**: Mock UnifiedDataAccess, test domain logic
- **UnifiedDataAccess**: Mock databases, test query logic
- **BaseServer**: Mock MCP SDK, test protocol handling

### **Integration Testing**
- Test layer interactions through well-defined interfaces
- No cross-layer dependencies except through approved channels

## 🎯 **Success Metrics**

### **Architecture Quality**
- ✅ No duplicate functionality across layers
- ✅ Clear error attribution to specific layer
- ✅ Predictable developer experience
- ✅ Easy to add new functionality

### **Developer Experience**  
- ✅ "Where do I find X?" has clear answer
- ✅ "Where do I add Y?" has clear answer
- ✅ Debugging follows layer boundaries
- ✅ Testing follows layer boundaries

This separation of concerns eliminates the confusion that led to the `health_check` tool mystery and establishes clear patterns for future development.