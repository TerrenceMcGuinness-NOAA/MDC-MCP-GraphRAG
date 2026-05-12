"""Pytest configuration for the Python MCP server test suite.

Puts the ``mcp_server_python`` root on ``sys.path`` so tests can ``import
src.…`` without installing the package first. This matches the design's
``from src.data.unified_data_access import ...`` import pattern.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
