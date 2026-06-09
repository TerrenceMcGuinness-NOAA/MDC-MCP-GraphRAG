"""Shared loader for the hyphenated ``provision-agentcore-creds.py`` tool.

The production script lives at the repository-root ``tools/`` directory and has
a hyphenated filename, so it cannot be imported by name. This helper loads it
once via :mod:`importlib` and exposes the module object as ``prov`` for every
provisioning test (unit and property).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _find_tool() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "tools" / "provision-agentcore-creds.py"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("tools/provision-agentcore-creds.py not found")


def load_module():
    path = _find_tool()
    spec = importlib.util.spec_from_file_location("provision_agentcore_creds", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


#: The loaded production module, shared across test files.
prov = load_module()
