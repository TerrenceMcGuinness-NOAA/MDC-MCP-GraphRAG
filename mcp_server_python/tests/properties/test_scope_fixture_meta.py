"""Meta-test guarding the cross-adapter backend sweep (Task 2.5, optional).

shared-scope-query-routing Requirement 4.5. The ``adapters()`` fixture
(``tests/properties/conftest.py``) is parameterised over both backends so
every property that references a Vector_Adapter runs against
``ChromaDBAdapter`` and ``OpenSearchAdapter`` alike. This module is
defense-in-depth beyond R4.5 which the fixture itself satisfies: it fails
if a future change quietly drops one backend from the sweep, so the
two-backend guarantee cannot silently erode.

Kept in its own module (per the task) so it does not collide with the
property modules. Marked ``unit`` -- nothing here is Hypothesis-driven.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit


def test_adapters_fixture_yields_a_connected_backend(adapters):
    """A parameterised probe so this module's collection carries both ids.

    Runs once per ``adapters()`` param, giving the ``[chromadb]`` and
    ``[opensearch]`` node ids that :func:`test_both_backend_ids_collected`
    asserts on.
    """
    adapter, _double = adapters
    assert adapter._connected is True


def test_both_backend_ids_collected(pytestconfig):
    """Both ``chromadb`` and ``opensearch`` ids must appear in the sweep.

    Collects this module and asserts both parameter ids are present, so a
    change that drops a backend from the ``adapters()`` fixture fails
    here rather than silently halving the cross-backend coverage R4.5
    requires.
    """
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            f"{__file__}::test_adapters_fixture_yields_a_connected_backend",
            "--collect-only", "-q",
        ],
        capture_output=True,
        text=True,
        cwd=pytestconfig.rootpath,
    )
    assert "chromadb" in result.stdout, result.stdout
    assert "opensearch" in result.stdout, result.stdout
