"""Environment configuration (Requirement 1.8, 3.7).

Phase C-2c (Bedrock-native embedding swap, Requirement 8) replaces the
single-profile ``PRODUCTION_INDICES`` constant with the profile-keyed
:data:`PRODUCTION_INDICES_BY_PROFILE` plus :func:`get_production_indices`
for callers that need the inner map. ``PRODUCTION_INDICES`` is no
longer exported.
"""

from .aws_config import (
    DEFAULT_AWS_REGION,
    DEFAULT_HOST,
    DEFAULT_PORT,
    PRODUCTION_INDICES_BY_PROFILE,
    get_production_indices,
    resolve_index,
)
from .environment import (
    KNOWN_MODULES,
    VALID_BACKENDS,
    ConfigError,
    ServerConfig,
    load_config,
)

__all__ = [
    "DEFAULT_AWS_REGION",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "KNOWN_MODULES",
    "VALID_BACKENDS",
    "ConfigError",
    "PRODUCTION_INDICES_BY_PROFILE",
    "ServerConfig",
    "get_production_indices",
    "load_config",
    "resolve_index",
]
