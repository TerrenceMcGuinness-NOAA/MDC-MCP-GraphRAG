# Test Health Check Workflow

**Purpose**: Simple test workflow to validate SDD automation with health checks

## Phase 1: System Health Validation

### Step 1: Check Vector Database
**Type**: health_check
**Component**: chromadb
**Required**: Yes

Verify ChromaDB is operational and accessible.

### Step 2: Check Graph Database
**Type**: health_check
**Component**: neo4j
**Required**: Yes

Verify Neo4j graph database connectivity and health.

### Step 3: Query Documentation
**Type**: data_query
**Query**: "What is Rocoto workflow manager"
**Required**: No

Test semantic search functionality with a simple query.

## Phase 2: Validation

### Step 4: Validate Results
**Type**: validation
**Target**: search_results
**Required**: Yes

Ensure search results were returned successfully.

## Success Criteria
- All health checks pass
- Documentation query returns results
- No errors during execution
