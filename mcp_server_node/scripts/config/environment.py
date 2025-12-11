"""
Environment Configuration for MCP RAG Server
============================================

Single Point of Truth (SPOT) for environment-aware database connections.

Usage:
    from config.environment import get_chromadb_client, MCP_ENV
    
    client = get_chromadb_client()
    collection = client.get_collection("global-workflow-docs")

Environment Variables:
    MCP_ENV: development (default), devops, staging, production

Data Isolation Strategy:
    - development: Direct SQLite access (PersistentClient)
    - devops: Containerized HTTP access (Docker Compose)
    - staging: Remote containerized (read validation)
    - production: CI/CD only, no manual access
"""

import os
import sys
from typing import Optional, Dict, Any

# Environment detection
MCP_ENV = os.environ.get('MCP_ENV', 'development')

# ============================================================================
# Environment Configurations
# ============================================================================

ENVIRONMENT_CONFIGS: Dict[str, Dict[str, Any]] = {
    'development': {
        'client_type': 'PersistentClient',
        'path': os.environ.get('CHROMA_DATA_PATH', '/mcp_rag_eib/data/chromadb'),
        'allow_writes': True,
        'description': 'Direct SQLite access for local development',
    },
    'devops': {
        'client_type': 'HttpClient',
        'host': os.environ.get('CHROMA_HOST', 'localhost'),
        'port': int(os.environ.get('CHROMA_PORT', '8080')),
        'allow_writes': True,
        'description': 'Containerized database for CI/CD validation',
    },
    'staging': {
        'client_type': 'HttpClient',
        'host': os.environ.get('STAGING_CHROMADB_HOST', 'staging-chromadb'),
        'port': int(os.environ.get('STAGING_CHROMADB_PORT', '8000')),
        'allow_writes': False,
        'description': 'Read-only staging environment',
    },
    'production': {
        'client_type': 'HttpClient',
        'host': os.environ.get('PROD_CHROMADB_HOST', ''),
        'port': int(os.environ.get('PROD_CHROMADB_PORT', '8000')),
        'allow_writes': False,
        'require_pipeline_auth': True,
        'description': 'Production - CI/CD access only',
    },
}

# ============================================================================
# ChromaDB Client Factory
# ============================================================================

def get_chromadb_client():
    """
    Get a ChromaDB client configured for the current environment.
    
    Returns:
        chromadb.ClientAPI: Configured ChromaDB client
        
    Raises:
        ValueError: If MCP_ENV is invalid
        RuntimeError: If production access is attempted outside CI/CD
    """
    import chromadb
    
    if MCP_ENV not in ENVIRONMENT_CONFIGS:
        raise ValueError(f"Invalid MCP_ENV: {MCP_ENV}. Valid values: {list(ENVIRONMENT_CONFIGS.keys())}")
    
    config = ENVIRONMENT_CONFIGS[MCP_ENV]
    
    # Production safety check
    if MCP_ENV == 'production':
        if not os.environ.get('CI_PIPELINE_ID'):
            raise RuntimeError(
                "Production database access is restricted to CI/CD pipelines. "
                "Set MCP_ENV=development or MCP_ENV=devops for local work."
            )
    
    print(f"[INFO] MCP_ENV={MCP_ENV}: {config['description']}")
    
    if config['client_type'] == 'PersistentClient':
        print(f"[INFO] Using PersistentClient at {config['path']}")
        return chromadb.PersistentClient(path=config['path'])
    else:
        url = f"http://{config['host']}:{config['port']}"
        print(f"[INFO] Using HttpClient at {url}")
        return chromadb.HttpClient(host=config['host'], port=config['port'])


def get_config() -> Dict[str, Any]:
    """Get the current environment configuration."""
    if MCP_ENV not in ENVIRONMENT_CONFIGS:
        raise ValueError(f"Invalid MCP_ENV: {MCP_ENV}")
    return ENVIRONMENT_CONFIGS[MCP_ENV]


def is_write_allowed() -> bool:
    """Check if writes are allowed in the current environment."""
    return get_config().get('allow_writes', False)


def validate_environment():
    """Validate the current environment configuration."""
    print(f"=" * 60)
    print(f"MCP Environment Configuration")
    print(f"=" * 60)
    print(f"MCP_ENV: {MCP_ENV}")
    
    config = get_config()
    for key, value in config.items():
        print(f"  {key}: {value}")
    
    print(f"=" * 60)
    
    # Test connection
    try:
        client = get_chromadb_client()
        heartbeat = client.heartbeat()
        print(f"[OK] ChromaDB connection successful (heartbeat: {heartbeat})")
        
        collections = client.list_collections()
        print(f"[OK] Found {len(collections)} collections")
        
        return True
    except Exception as e:
        print(f"[ERROR] ChromaDB connection failed: {e}")
        return False


# ============================================================================
# Neo4j Configuration (for future use)
# ============================================================================

NEO4J_CONFIGS: Dict[str, Dict[str, Any]] = {
    'development': {
        'uri': os.environ.get('NEO4J_URI', 'bolt://localhost:7687'),
        'auth': ('neo4j', os.environ.get('NEO4J_PASSWORD', 'password')),
    },
    'devops': {
        'uri': os.environ.get('NEO4J_URI', 'bolt://localhost:7687'),
        'auth': ('neo4j', os.environ.get('NEO4J_PASSWORD', 'devops_password')),
    },
    'staging': {
        'uri': os.environ.get('STAGING_NEO4J_URI', 'bolt://staging-neo4j:7687'),
        'auth': ('neo4j', os.environ.get('NEO4J_STAGING_PASSWORD', '')),
    },
    'production': {
        'uri': os.environ.get('PROD_NEO4J_URI', 'bolt://prod-neo4j:7687'),
        'auth': ('neo4j', os.environ.get('NEO4J_PRODUCTION_PASSWORD', '')),
    },
}


def get_neo4j_config() -> Dict[str, Any]:
    """Get Neo4j configuration for current environment."""
    if MCP_ENV not in NEO4J_CONFIGS:
        raise ValueError(f"Invalid MCP_ENV: {MCP_ENV}")
    return NEO4J_CONFIGS[MCP_ENV]


# ============================================================================
# CLI Entry Point
# ============================================================================

if __name__ == '__main__':
    """Run environment validation when executed directly."""
    print(f"\nValidating MCP environment configuration...\n")
    success = validate_environment()
    sys.exit(0 if success else 1)
