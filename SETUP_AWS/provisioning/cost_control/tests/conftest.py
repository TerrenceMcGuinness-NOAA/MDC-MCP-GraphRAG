"""Pytest configuration for the cost_control test suite.

Ensures ``SETUP_AWS/provisioning`` (the parent of the ``cost_control``
package) is importable as a top-level package root regardless of the
operator's working directory, matching the documented invocation
``cd SETUP_AWS/provisioning && python3.12 -m pytest cost_control/tests/ -q``.
"""

from __future__ import annotations

import sys
from pathlib import Path

# tests/ -> cost_control/ -> provisioning/
_PROVISIONING_ROOT = Path(__file__).resolve().parents[2]
if str(_PROVISIONING_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROVISIONING_ROOT))
