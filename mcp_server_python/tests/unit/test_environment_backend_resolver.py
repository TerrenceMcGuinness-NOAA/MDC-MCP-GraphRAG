"""Unit tests for the ``DB_BACKEND=legacy`` → ``cots`` deprecation shim.

Phase 63a: renames the on-prem backend selector value from ``legacy`` to
``cots`` (Commercial Off-The-Shelf: ChromaDB + Neo4j). The historical
value ``legacy`` continues to work but emits a one-time WARN.

Acceptance criteria covered:

* AC 1 — ``DB_BACKEND=cots`` accepted without warnings.
* AC 3 — ``DB_BACKEND=legacy`` maps to ``cots`` and emits the expected WARN.
* AC 4 — Repeated ``load_config`` calls emit the WARN at most once per process.
* AC 5 — Unknown values fail fast with :class:`ConfigError` naming the
  canonical values (``aws``, ``cots``).
"""

from __future__ import annotations

import logging

import pytest

from src.config import ConfigError, load_config
from src.config.environment import _reset_legacy_backend_warn


@pytest.fixture(autouse=True)
def _reset_warn_guard():
    """Reset the module-level shim warn guard between tests."""
    _reset_legacy_backend_warn()
    yield
    _reset_legacy_backend_warn()


# ── AC 1 — cots is the canonical value ──────────────────────────────────────


def test_cots_accepted_without_warning(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.WARNING, logger="src.config.environment")
    cfg = load_config(env={"DB_BACKEND": "cots"})
    assert cfg.db_backend == "cots"
    assert cfg.is_cots() is True
    assert cfg.is_aws() is False
    assert not any(
        "DB_BACKEND=legacy" in rec.message for rec in caplog.records
    ), "cots must not trigger the legacy-alias WARN"


# ── AC 3 — legacy is shimmed with WARN ──────────────────────────────────────


def test_legacy_shim_maps_to_cots_and_warns(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.WARNING, logger="src.config.environment")
    cfg = load_config(env={"DB_BACKEND": "legacy"})

    assert cfg.db_backend == "cots"
    assert cfg.is_cots() is True

    warns = [
        rec.message for rec in caplog.records
        if "DB_BACKEND=legacy" in rec.message
    ]
    assert warns == [
        "[WARN] DB_BACKEND=legacy is deprecated; "
        "use DB_BACKEND=cots (auto-mapped)"
    ], f"Expected exactly one deprecation WARN, got: {warns!r}"


def test_legacy_shim_case_insensitive(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.WARNING, logger="src.config.environment")
    cfg = load_config(env={"DB_BACKEND": " LEGACY "})
    assert cfg.db_backend == "cots"
    assert any(
        "DB_BACKEND=legacy" in rec.message for rec in caplog.records
    ), "uppercase / whitespace-padded 'LEGACY' must still trigger the shim"


# ── AC 4 — WARN emitted at most once per process ────────────────────────────


def test_legacy_shim_warns_only_once(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.WARNING, logger="src.config.environment")
    load_config(env={"DB_BACKEND": "legacy"})
    load_config(env={"DB_BACKEND": "legacy"})
    load_config(env={"DB_BACKEND": "legacy"})

    warns = [
        rec for rec in caplog.records
        if "DB_BACKEND=legacy" in rec.message
    ]
    assert len(warns) == 1, (
        f"Expected exactly one deprecation WARN across 3 load_config calls, "
        f"got {len(warns)}"
    )


# ── AC 5 — unknown values fail fast ─────────────────────────────────────────


def test_unknown_backend_lists_canonical_values():
    with pytest.raises(ConfigError, match=r"DB_BACKEND must be one of") as exc:
        load_config(env={"DB_BACKEND": "bogus"})

    msg = str(exc.value)
    assert "'aws'" in msg or "\"aws\"" in msg or "aws" in msg
    assert "'cots'" in msg or "\"cots\"" in msg or "cots" in msg
    # The raw user input surfaces in the error to aid debugging.
    assert "bogus" in msg


def test_unset_defaults_to_aws(caplog: pytest.LogCaptureFixture):
    """DB_BACKEND unset falls through to the Python server's canonical
    default (``aws``), unchanged by the rename."""
    caplog.set_level(logging.WARNING, logger="src.config.environment")
    cfg = load_config(env={})
    assert cfg.db_backend == "aws"
    assert cfg.is_aws() is True
    assert not any(
        "DB_BACKEND=legacy" in rec.message for rec in caplog.records
    )
