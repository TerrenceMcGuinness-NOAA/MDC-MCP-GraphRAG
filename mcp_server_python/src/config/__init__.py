"""Environment configuration (Requirement 1.8, 3.7)."""

from .aws_config import (
    DEFAULT_AWS_REGION,
    DEFAULT_HOST,
    DEFAULT_PORT,
    PRODUCTION_INDICES,
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
    "PRODUCTION_INDICES",
    "ServerConfig",
    "load_config",
    "resolve_index",
]
