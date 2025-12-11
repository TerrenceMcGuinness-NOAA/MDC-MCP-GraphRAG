"""
Configuration package for MCP RAG Server scripts.

This package provides environment-aware configuration for database connections
and other runtime settings.
"""

from .environment import (
    MCP_ENV,
    get_chromadb_client,
    get_config,
    is_write_allowed,
    validate_environment,
    get_neo4j_config,
    ENVIRONMENT_CONFIGS,
    NEO4J_CONFIGS,
)

__all__ = [
    'MCP_ENV',
    'get_chromadb_client',
    'get_config',
    'is_write_allowed',
    'validate_environment',
    'get_neo4j_config',
    'ENVIRONMENT_CONFIGS',
    'NEO4J_CONFIGS',
]
