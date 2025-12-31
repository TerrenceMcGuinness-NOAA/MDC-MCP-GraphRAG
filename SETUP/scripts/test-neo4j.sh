#!/bin/bash

################################################################################
# Neo4j Graph Database Test Suite
# Tests Neo4j Docker service connectivity and functionality
################################################################################

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

################################################################################
# Pre-Flight: Ensure Neo4j directories exist
################################################################################
echo -e "${CYAN}Pre-Flight Check: Neo4j Directory Structure${NC}"

NEO4J_BASE="/mcp_rag_eib/data/neo4j"
DIRS_NEEDED=("${NEO4J_BASE}/data" "${NEO4J_BASE}/logs" "${NEO4J_BASE}/import" "${NEO4J_BASE}/plugins")

for dir in "${DIRS_NEEDED[@]}"; do
    if [ ! -d "$dir" ]; then
        echo -e "${YELLOW}⚠️  Creating missing directory: $dir${NC}"
        sudo mkdir -p "$dir"
        sudo chown -R "${USER}:${USER}" "${NEO4J_BASE}"
    else
        echo -e "${GREEN}✅ Directory exists: $dir${NC}"
    fi
done

echo ""

# Logging functions
log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

log_section() {
    echo -e "\n${CYAN}═══════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════${NC}\n"
}

# Source environment
SCRIPT_DIR="$(dirname "${BASH_SOURCE[0]}")"
if [ -f "${SCRIPT_DIR}/mcp_env.sh" ]; then
    source "${SCRIPT_DIR}/mcp_env.sh" --quiet
fi

NEO4J_HOST="localhost"
NEO4J_HTTP_PORT="7474"
NEO4J_BOLT_PORT="7687"
NEO4J_USER="neo4j"
NEO4J_PASSWORD="gfsworkflow2025"

log_section "Neo4j Graph Database Connection Test"

################################################################################
# Test 1: Docker Container Status
################################################################################
log_info "Test 1: Checking Docker container status..."

if docker compose ps neo4j 2>/dev/null | grep -q "healthy"; then
    log_success "Neo4j container is running and healthy"
elif docker compose ps neo4j 2>/dev/null | grep -q "running"; then
    log_warning "Neo4j container is running but not yet healthy"
else
    log_error "Neo4j container is not running"
    log_info "Start with: docker compose up -d neo4j"
    exit 1
fi

################################################################################
# Test 2: HTTP Endpoint Test
################################################################################
log_info "Test 2: Testing HTTP endpoint (Browser UI)..."

if curl -s "http://${NEO4J_HOST}:${NEO4J_HTTP_PORT}" > /dev/null 2>&1; then
    log_success "Neo4j Browser UI accessible at http://${NEO4J_HOST}:${NEO4J_HTTP_PORT}"
else
    log_error "Neo4j Browser UI not accessible"
    exit 1
fi

################################################################################
# Test 3: Cypher Query Test (requires cypher-shell in container)
################################################################################
log_info "Test 3: Testing Cypher query execution..."

CYPHER_TEST=$(docker compose exec -T neo4j cypher-shell \
    -u "${NEO4J_USER}" \
    -p "${NEO4J_PASSWORD}" \
    "RETURN 'Neo4j is working!' AS message" 2>&1)

if echo "${CYPHER_TEST}" | grep -q "Neo4j is working"; then
    log_success "Cypher query executed successfully"
else
    log_error "Cypher query execution failed"
    echo "${CYPHER_TEST}"
    exit 1
fi

################################################################################
# Test 4: Database Information
################################################################################
log_info "Test 4: Retrieving database information..."

DB_INFO=$(docker compose exec -T neo4j cypher-shell \
    -u "${NEO4J_USER}" \
    -p "${NEO4J_PASSWORD}" \
    "CALL dbms.components() YIELD name, versions, edition RETURN name, versions[0] AS version, edition" 2>&1)

if [ $? -eq 0 ]; then
    log_success "Database information retrieved"
    echo "${DB_INFO}" | grep -v "^$"
else
    log_warning "Could not retrieve database information (may not be critical)"
fi

################################################################################
# Test 5: APOC Plugin Test
################################################################################
log_info "Test 5: Testing APOC plugin availability..."

APOC_TEST=$(docker compose exec -T neo4j cypher-shell \
    -u "${NEO4J_USER}" \
    -p "${NEO4J_PASSWORD}" \
    "CALL apoc.version() YIELD version RETURN version" 2>&1)

if echo "${APOC_TEST}" | grep -q "[0-9]\+\.[0-9]\+\.[0-9]\+"; then
    APOC_VERSION=$(echo "${APOC_TEST}" | grep -oP '\d+\.\d+\.\d+' | head -1)
    log_success "APOC plugin available (version: ${APOC_VERSION})"
else
    log_warning "APOC plugin not available or not loaded"
fi

################################################################################
# Test 6: Graph Data Science Plugin Test
################################################################################
log_info "Test 6: Testing Graph Data Science (GDS) plugin..."

GDS_TEST=$(docker compose exec -T neo4j cypher-shell \
    -u "${NEO4J_USER}" \
    -p "${NEO4J_PASSWORD}" \
    "CALL gds.version() YIELD version RETURN version" 2>&1)

if echo "${GDS_TEST}" | grep -q "[0-9]\+\.[0-9]\+\.[0-9]\+"; then
    GDS_VERSION=$(echo "${GDS_TEST}" | grep -oP '\d+\.\d+\.\d+' | head -1)
    log_success "GDS plugin available (version: ${GDS_VERSION})"
else
    log_warning "GDS plugin not available or not loaded"
fi

################################################################################
# Test 7: Create Sample Node (Phase 0 POC Preview)
################################################################################
log_info "Test 7: Creating sample test node..."

CREATE_TEST=$(docker compose exec -T neo4j cypher-shell \
    -u "${NEO4J_USER}" \
    -p "${NEO4J_PASSWORD}" \
    "CREATE (n:TestNode {name: 'Global Workflow Test', timestamp: datetime()}) RETURN n.name AS created" 2>&1)

if echo "${CREATE_TEST}" | grep -q "Global Workflow Test"; then
    log_success "Sample node created successfully"
    
    # Clean up test node
    docker compose exec -T neo4j cypher-shell \
        -u "${NEO4J_USER}" \
        -p "${NEO4J_PASSWORD}" \
        "MATCH (n:TestNode) DELETE n" > /dev/null 2>&1
    log_info "Test node cleaned up"
else
    log_warning "Could not create test node (permissions issue?)"
fi

################################################################################
# Summary
################################################################################
log_section "Test Summary"

echo -e "${GREEN}✅ All critical tests passed!${NC}\n"

echo -e "${CYAN}Connection Information:${NC}"
echo -e "  Browser UI:  http://${NEO4J_HOST}:${NEO4J_HTTP_PORT}"
echo -e "  Bolt:        bolt://${NEO4J_HOST}:${NEO4J_BOLT_PORT}"
echo -e "  Username:    ${NEO4J_USER}"
echo -e "  Password:    ${NEO4J_PASSWORD}"

echo -e "\n${CYAN}Next Steps for Phase 0 POC:${NC}"
echo -e "  1. ${YELLOW}Parse .gitmodules${NC} → Create submodule nodes + relationships"
echo -e "  2. ${YELLOW}Parse CMakeLists.txt${NC} → Create dependency graph"
echo -e "  3. ${YELLOW}Demo Queries${NC} → Show structural insights impossible with vector DB"
echo -e "  4. ${YELLOW}Stakeholder Demo${NC} → Present graph visualization + query results"

echo -e "\n${CYAN}Useful Cypher Commands:${NC}"
echo -e "  ${BLUE}List all nodes:${NC}          MATCH (n) RETURN n LIMIT 25"
echo -e "  ${BLUE}Count by label:${NC}          MATCH (n) RETURN labels(n) AS label, count(*) AS count"
echo -e "  ${BLUE}Show relationships:${NC}      MATCH (a)-[r]->(b) RETURN a, r, b LIMIT 10"
echo -e "  ${BLUE}Clear database:${NC}          MATCH (n) DETACH DELETE n"
echo -e "  ${BLUE}APOC procedures:${NC}         CALL apoc.help('apoc')"

log_success "Neo4j is ready for Phase 0 POC development! 🚀"
