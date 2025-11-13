# Neo4j Graph Database Integration

## Overview

Neo4j graph database has been integrated into the MCP RAG infrastructure to enable **graph-based relationship queries** that are impossible with vector embeddings alone. This is Phase 0 of the **Enhanced Ingestion Architecture** - a hybrid triple-store approach combining ChromaDB (vectors), Neo4j (graphs), and PostgreSQL (metadata).

**Status**: ✅ **Infrastructure Ready** - Docker service configured, persistent storage established, APOC + GDS plugins enabled

**Next Milestone**: Phase 0 POC (2-day weekend project)

---

## Quick Start

### 1. Start Neo4j Service
```bash
cd /mcp_rag_eib/SETUP
docker compose up -d neo4j
```

### 2. Verify Connection
```bash
./test-neo4j.sh
```

### 3. Access Neo4j Browser
Open browser: **http://localhost:7474**

**Credentials**:
- Username: `neo4j`
- Password: `gfsworkflow2025`

---

## Architecture

### Service Configuration
- **Version**: Neo4j 5.15.0 (latest stable with GDS support)
- **Ports**:
  - `7474` - HTTP (Neo4j Browser UI)
  - `7687` - Bolt protocol (driver connections)
- **Plugins**:
  - **APOC** - Procedures library for data import, export, graph algorithms
  - **GDS** - Graph Data Science algorithms (PageRank, community detection, etc.)

### Persistent Storage
All data persists at `/mcp_rag_eib/data/neo4j/`:
```
/mcp_rag_eib/data/neo4j/
├── data/       # Graph database files
├── logs/       # Neo4j server logs
├── import/     # CSV/JSON import staging
└── plugins/    # APOC + GDS .jar files
```

### Memory Configuration
Optimized for GFS graph analysis:
- **Heap**: 1GB initial, 4GB max
- **Pagecache**: 2GB
- **Total footprint**: ~5-7GB (estimated)

---

## Phase 0 POC - Weekend Project (2 Days)

### Objective
Prove Neo4j value by demonstrating **structural relationship queries** that ChromaDB vectors cannot answer.

### Tasks

#### Day 1: Data Ingestion (8 hours)
1. **Submodule Relationship Graph** (3 hours)
   - Parse `.gitmodules` from global-workflow
   - Create nodes: `Repository`, `Submodule`
   - Create relationships: `DEPENDS_ON`, `CONTAINS`
   
2. **CMakeLists.txt Dependency Graph** (3 hours)
   - Parse `CMakeLists.txt` from `sorc/` directories
   - Create nodes: `Library`, `Executable`, `Target`
   - Create relationships: `LINKS_TO`, `REQUIRES`

3. **Basic Ingestion Scripts** (2 hours)
   - `ingest_submodules.py` - Parse and load .gitmodules
   - `ingest_cmake.py` - Parse and load CMakeLists.txt

#### Day 2: Queries + Demo (8 hours)
4. **Demo Queries** (4 hours)
   - **Q1**: "Which submodules depend on wxflow?"
   - **Q2**: "What's the shortest dependency path from sorc/build_all.sh to ufs_model?"
   - **Q3**: "Show me all circular dependencies in the build system"
   
5. **Visualization** (2 hours)
   - Neo4j Browser graph visualizations
   - Export PNG screenshots for stakeholder presentation

6. **Documentation** (2 hours)
   - Phase 0 results document
   - Comparison: What ChromaDB vectors cannot do
   - Recommendation: Proceed to Phase 1 or abort

### Success Criteria
✅ Submodule graph ingested (50+ nodes, 100+ relationships)  
✅ CMake dependency graph ingested (100+ nodes, 200+ relationships)  
✅ 3 demo queries return actionable insights  
✅ Queries are impossible/impractical with ChromaDB vectors alone  
✅ Stakeholders approve Phase 1 continuation  

---

## Example Cypher Queries

### Show All Submodules
```cypher
MATCH (s:Submodule)
RETURN s.name, s.url, s.branch
ORDER BY s.name
```

### Find Dependencies of Specific Submodule
```cypher
MATCH (s:Submodule {name: 'wxflow'})<-[:DEPENDS_ON]-(dep)
RETURN dep.name AS dependent
ORDER BY dep.name
```

### Shortest Path Between Components
```cypher
MATCH path = shortestPath(
  (start:Library {name: 'build_all.sh'})-[*]-(end:Library {name: 'ufs_model'})
)
RETURN path
```

### Circular Dependency Detection
```cypher
MATCH (a)-[:DEPENDS_ON*]->(b)-[:DEPENDS_ON*]->(a)
WHERE a <> b
RETURN DISTINCT a.name AS node1, b.name AS node2
```

---

## Development Workflow

### Starting Services
```bash
cd /mcp_rag_eib/SETUP
docker compose up -d neo4j
docker compose logs neo4j -f  # Watch startup logs
```

### Testing Connection
```bash
./test-neo4j.sh
```

### Accessing Cypher Shell (Interactive)
```bash
docker compose exec neo4j cypher-shell -u neo4j -p gfsworkflow2025
```

### Running Cypher from Command Line
```bash
docker compose exec -T neo4j cypher-shell \
  -u neo4j -p gfsworkflow2025 \
  "MATCH (n) RETURN count(n)"
```

### Stopping Services
```bash
docker compose down  # Stops all services, preserves data
```

---

## Integration with ChromaDB

### Hybrid Query Pattern

**Use ChromaDB for:**
- Semantic similarity: "Find code similar to this implementation"
- Content search: "Show me documentation about data assimilation"
- Embedding-based retrieval: "What are the nearest neighbors?"

**Use Neo4j for:**
- Structural queries: "What depends on this module?"
- Path finding: "How do I get from A to B?"
- Relationship traversal: "Show me the entire dependency chain"
- Graph algorithms: "Which components are most central?"

**Combine Both:**
1. ChromaDB: Find semantically similar code snippet
2. Neo4j: Trace which other components depend on that code
3. Result: "This code is used by 12 downstream modules (here's the graph)"

---

## APOC + GDS Plugin Usage

### APOC - Import/Export
```cypher
// Import from JSON
CALL apoc.load.json("file:///import/submodules.json")
YIELD value
CREATE (s:Submodule {name: value.name, url: value.url})

// Export to CSV
CALL apoc.export.csv.all("export.csv", {})
```

### GDS - Graph Algorithms
```cypher
// PageRank (find most important nodes)
CALL gds.pageRank.stream('myGraph')
YIELD nodeId, score
RETURN gds.util.asNode(nodeId).name AS node, score
ORDER BY score DESC

// Community Detection (find clusters)
CALL gds.louvain.stream('myGraph')
YIELD nodeId, communityId
RETURN communityId, collect(gds.util.asNode(nodeId).name) AS members
```

---

## Troubleshooting

### Container Not Starting
```bash
# Check logs
docker compose logs neo4j

# Check if port is in use
netstat -tuln | grep 7474

# Restart with fresh logs
docker compose down
docker compose up -d neo4j
docker compose logs neo4j -f
```

### Health Check Failing
```bash
# Manually test cypher-shell
docker compose exec neo4j cypher-shell -u neo4j -p gfsworkflow2025 "RETURN 1"

# Check memory constraints
docker stats global-workflow-neo4j
```

### Plugins Not Loading
```bash
# Verify plugin JARs exist
docker compose exec neo4j ls -lh /plugins/

# Check Neo4j logs for plugin errors
docker compose logs neo4j | grep -i "plugin\|apoc\|gds"
```

### Connection Refused
```bash
# Verify container is running
docker compose ps neo4j

# Check if ports are mapped correctly
docker compose port neo4j 7474
docker compose port neo4j 7687

# Test HTTP endpoint
curl -v http://localhost:7474
```

---

## Next Steps After Phase 0 POC

### If POC Succeeds (Proceed to Phase 1):
1. **Schema Refinement** (Week 1-2)
   - Formalize node types and relationship types
   - Add constraints and indexes
   - Document graph schema

2. **Full Ingestion Pipeline** (Week 3-4)
   - Job scripts → graph
   - Workflow dependencies → graph
   - Source code structure → graph

3. **MCP Tool Integration** (Week 5-6)
   - `mcp_neo4j_query` tool
   - `mcp_graph_analysis` tool
   - `mcp_dependency_trace` tool

4. **Hybrid Queries** (Week 7-8)
   - ChromaDB + Neo4j combined queries
   - Performance optimization
   - Production deployment

### If POC Fails (Abort Neo4j):
- Document why graph queries didn't provide value
- Continue with ChromaDB-only approach
- Revisit graph database in future if use cases emerge

---

## Resources

### Documentation
- **Neo4j Cypher Manual**: https://neo4j.com/docs/cypher-manual/current/
- **APOC Documentation**: https://neo4j.com/docs/apoc/current/
- **GDS Documentation**: https://neo4j.com/docs/graph-data-science/current/

### Related Files
- `SETUP/docker-compose.yml` - Service configuration
- `SETUP/dockerfiles/Dockerfile.neo4j` - Custom image
- `SETUP/provision_mcp_rag_persistent.sh` - Provisioning script
- `ENHANCED_INGESTION_ARCHITECTURE.md` - Complete strategy document

### Support
- **Logs**: `docker compose logs neo4j -f`
- **Interactive Shell**: `docker compose exec neo4j cypher-shell`
- **Test Script**: `./test-neo4j.sh`

---

**Version**: 1.0.0  
**Last Updated**: 2025-01-15  
**Status**: Infrastructure Ready - Phase 0 POC Next  
**Owner**: NOAA EMC Global Workflow Team
