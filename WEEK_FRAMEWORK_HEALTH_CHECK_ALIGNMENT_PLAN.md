# WEEK Framework Consolidation & Health Check Alignment Plan
**Date**: November 13, 2025  
**Purpose**: Reconcile WEEK 1-3 evolution with current health check mechanisms for unified operations  
**Status**: Implementation Roadmap for Production Alignment

---

## 🎯 **Consolidation Analysis Results**

### **WEEK Framework Evolution Status**

#### **✅ WEEK 1: Data Access Layer (COMPLETE & HEALTHY)**
- **Deliverable**: UnifiedDataAccess with Neo4j + ChromaDB integration
- **Health Status**: Production validated with 8,709+ graph relationships
- **Alignment**: Fully integrated with health monitoring capabilities
- **Action Required**: **NONE** - Framework complete and operational

#### **✅ WEEK 2: Tool Consolidation (COMPLETE & OPERATIONAL)**  
- **Deliverable**: 22→21 tools across 5 focused modules, 36% duplicate reduction
- **Health Status**: All 21 tools operational with performance metrics
- **Alignment**: Health monitoring pattern established but not fully integrated
- **Action Required**: **ENHANCE** - Complete health metric integration per tool

#### **⚠️ WEEK 3: Quality & Testing (PARTIAL - DIVERGED FROM PLAN)**
- **Original Plan**: ChromaDB cleanup, 11-source ingestion, Neo4j docs, test suite
- **Actual Achievement**: Embedding upgrade (768-dim), enhanced collections, EE2 tools
- **Health Status**: Test infrastructure created but method alignment needed  
- **Action Required**: **COMPLETE** - Finish Week 3 per original specification

---

## 🔧 **Health Check Integration Gaps Identified**

### **Current Health Mechanisms**
1. **Infrastructure Health** (`SETUP/check-mcp-status.sh`) ✅ COMPLETE
   - ChromaDB API v1/v2 monitoring
   - Neo4j Docker service status  
   - MCP REST API availability
   - LangFlow workflow engine health

2. **MCP Client Health** (`mcp_server_node/test/health-check-mcp.sh`) ✅ COMPLETE
   - Node.js environment validation
   - MCP configuration integrity
   - Dependency resolution checks
   - Server startup testing

3. **Application Health Monitoring** ⚠️ PARTIAL
   - Per-tool performance metrics **MISSING**
   - Error tracking and categorization **INCOMPLETE**
   - Recovery mechanism automation **NOT IMPLEMENTED**
   - Health dashboard visualization **MISSING**

---

## 📋 **Consolidated Implementation Plan**

### **Phase 1: Complete WEEK 3 Original Specification (2-3 Days)**

#### **Task 1.1: Fix Test Suite Method Alignment (4 hours)**
**Issue**: Test mocks use `hybridSearch`, actual code uses `hybridQuery`  
**Files Affected**: 
- `SemanticSearchTools.test.js` (287 lines)
- `OperationalTools.test.js` (185 lines)

**Implementation**:
```bash
# Fix method name alignment across test suite
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node
# Update test mocks to use correct method names
sed -i 's/hybridSearch/hybridQuery/g' src/__tests__/*.test.js
```

#### **Task 1.2: ChromaDB Collection Cleanup (2 hours)**
**Issue**: Duplicate collections `global-workflow-docs` vs `global_workflow_docs`  
**Implementation**:
```javascript
// Consolidate to single authoritative collection
const collections = await chromaClient.listCollections();
const duplicates = collections.filter(name => name.includes('global_workflow_docs'));
for (const duplicate of duplicates) {
    await chromaClient.deleteCollection(duplicate);
}
```

#### **Task 1.3: Complete 11-Source Documentation Ingestion (6 hours)**
**Missing Sources** (per Week 3 original plan):
- UFS Weather Model documentation
- Rocoto workflow documentation  
- GSI data assimilation system
- Additional HPC platform guides

### **Phase 2: Integrate Health Monitoring Per Tool (1-2 Days)**

#### **Task 2.1: Implement HealthMonitor Class**
```javascript
// Add to each tool module
class HealthMonitor {
    constructor(componentName) {
        this.componentName = componentName;
        this.metrics = {
            totalQueries: 0,
            successCount: 0,
            failureCount: 0,
            averageResponseTime: 0,
            errorCategories: {},
            lastHealthy: Date.now()
        };
    }
    
    recordSuccess(responseTime) {
        this.metrics.totalQueries++;
        this.metrics.successCount++;
        this.updateAverageResponseTime(responseTime);
        this.metrics.lastHealthy = Date.now();
    }
    
    recordFailure(error, responseTime = 0) {
        this.metrics.totalQueries++;
        this.metrics.failureCount++;
        this.categorizeError(error);
        this.updateAverageResponseTime(responseTime);
    }
    
    getHealthStatus() {
        const successRate = this.metrics.successCount / this.metrics.totalQueries;
        const isHealthy = successRate > 0.95 && Date.now() - this.metrics.lastHealthy < 300000; // 5 min
        
        return {
            status: isHealthy ? 'healthy' : 'degraded',
            successRate,
            averageResponseTime: this.metrics.averageResponseTime,
            errorCategories: this.metrics.errorCategories,
            uptime: Date.now() - this.metrics.lastHealthy
        };
    }
}
```

#### **Task 2.2: Update All 21 Tools with Health Integration**
**Pattern for each tool**:
```javascript
// Example: SemanticSearchTools with health monitoring
class SemanticSearchTools {
    constructor(dataAccess = null) {
        this.dataAccess = dataAccess || new UnifiedDataAccess();
        this.healthMonitor = new HealthMonitor('semantic-search-tools');
    }
    
    async search_documentation(params) {
        const startTime = Date.now();
        try {
            const result = await this.dataAccess.hybridQuery(params.query, params.options);
            this.healthMonitor.recordSuccess(Date.now() - startTime);
            return result;
        } catch (error) {
            this.healthMonitor.recordFailure(error, Date.now() - startTime);
            throw error;
        }
    }
    
    async getHealthStatus() {
        return this.healthMonitor.getHealthStatus();
    }
}
```

### **Phase 3: Health Dashboard & Automation (2-3 Days)**

#### **Task 3.1: Create Health Dashboard Endpoint**
```javascript
// Add to mcp-server-rag.js
class MCPServerWithHealth extends MCPServer {
    constructor() {
        super();
        this.healthAggregator = new HealthAggregator();
        this.setupHealthEndpoint();
    }
    
    setupHealthEndpoint() {
        // REST endpoint for health dashboard
        this.app.get('/health', async (req, res) => {
            const systemHealth = await this.healthAggregator.getSystemHealth();
            res.json(systemHealth);
        });
        
        this.app.get('/health/:component', async (req, res) => {
            const componentHealth = await this.healthAggregator.getComponentHealth(req.params.component);
            res.json(componentHealth);
        });
    }
}
```

#### **Task 3.2: Automated Recovery Mechanisms**
```javascript
class HealthAggregator {
    async monitorAndRecover() {
        const systemHealth = await this.getSystemHealth();
        
        for (const [component, health] of Object.entries(systemHealth.components)) {
            if (health.status === 'degraded') {
                await this.attemptRecovery(component, health);
            }
        }
    }
    
    async attemptRecovery(component, healthStatus) {
        switch (component) {
            case 'chromadb':
                await this.restartChromaDBConnection();
                break;
            case 'neo4j':
                await this.reconnectNeo4j();
                break;
            case 'semantic-search-tools':
                await this.clearToolCache(component);
                break;
        }
    }
}
```

### **Phase 4: Integration with Existing Health Checks (1 Day)**

#### **Task 4.1: Enhance check-mcp-status.sh**
Add application-level health monitoring:
```bash
# Add to SETUP/check-mcp-status.sh
echo "🔍 Application Health (MCP Tools):"
HEALTH_RESPONSE=$(curl -s "http://localhost:3000/health" 2>/dev/null)
if [ $? -eq 0 ]; then
    echo "   ✅ MCP server responsive"
    
    # Parse component health
    HEALTHY_COMPONENTS=$(echo "$HEALTH_RESPONSE" | jq -r '.components | to_entries[] | select(.value.status == "healthy") | .key' 2>/dev/null | wc -l)
    TOTAL_COMPONENTS=$(echo "$HEALTH_RESPONSE" | jq -r '.components | keys | length' 2>/dev/null)
    
    echo "   📊 Healthy Components: ${HEALTHY_COMPONENTS}/${TOTAL_COMPONENTS}"
else
    echo "   ❌ MCP server not responding"
fi
```

#### **Task 4.2: Integrate with health-check-mcp.sh**  
Add tool-level validation:
```bash
# Add to mcp_server_node/test/health-check-mcp.sh
test_tool_health() {
    log_info "Testing MCP tool health..."
    
    # Start server temporarily for health check
    local server_pid
    start_test_server server_pid
    
    if [ -n "$server_pid" ]; then
        sleep 3  # Allow startup
        
        local health_status
        health_status=$(curl -s "http://localhost:3000/health" 2>/dev/null)
        
        if [ $? -eq 0 ]; then
            log_success "All MCP tools responding to health checks"
            
            # Check individual tool health
            for tool in semantic-search code-analysis operational workflow github; do
                local tool_health
                tool_health=$(curl -s "http://localhost:3000/health/${tool}" 2>/dev/null)
                
                if [ $? -eq 0 ]; then
                    log_success "Tool '${tool}' is healthy"
                else
                    log_warning "Tool '${tool}' health check failed"
                fi
            done
        else
            log_error "MCP health endpoint not responding"
            return 1
        fi
        
        kill "$server_pid" 2>/dev/null
    else
        log_error "Could not start MCP server for health testing"
        return 1
    fi
}
```

---

## 🎯 **Validation & Success Criteria**

### **Phase 1 Success Criteria**
- ✅ All 50+ tests pass with correct method names
- ✅ Single ChromaDB collection with no duplicates
- ✅ 11 documentation sources successfully ingested
- ✅ Week 3 completion document created

### **Phase 2 Success Criteria**  
- ✅ All 21 tools have integrated health monitoring
- ✅ Health metrics accurately track success/failure rates
- ✅ Error categorization provides actionable insights
- ✅ Performance metrics within acceptable bounds

### **Phase 3 Success Criteria**
- ✅ Health dashboard accessible via REST API
- ✅ Automated recovery mechanisms functional
- ✅ Real-time health status visualization
- ✅ Proactive alerting for degraded components

### **Phase 4 Success Criteria**
- ✅ Infrastructure + application health unified
- ✅ Single command provides complete system health
- ✅ Health checks integrated into CI/CD pipeline
- ✅ Documentation updated with health procedures

---

## 📊 **Implementation Timeline**

### **Week 1: Complete WEEK 3 & Basic Health Integration**
- Days 1-2: Fix test suite, complete ingestion
- Days 3-4: Implement HealthMonitor class
- Day 5: Integrate health monitoring into all tools

### **Week 2: Advanced Health Features & Dashboard**
- Days 1-2: Build health dashboard and REST endpoints
- Days 3-4: Implement automated recovery mechanisms  
- Day 5: Integration with existing health check scripts

### **Week 3: Production Deployment & Validation**
- Days 1-2: Deploy to production environment
- Days 3-4: Validate all health monitoring in real-world usage
- Day 5: Documentation and training materials

---

**This plan ensures complete alignment between the WEEK framework evolution and comprehensive health monitoring, creating a unified, production-ready system with proactive operational excellence.**