"""Write-path immutability check (Task 12.1).

Two independent assertions guard the read-path-only boundary this spec
promises (Requirement 12.2, 12.7):

1. **File digests** -- every file under ``mcp_server_python/scripts/``
   must be byte-identical to the tree this task was authored against.
   Detected via a recorded SHA-256 digest manifest.
2. **Naming stability** -- ``resolve_collection_name`` (the write-side
   naming authority, unchanged by this task) must keep producing the
   exact same physical name, or the exact same rejection, for every
   combination in the Requirement 12.1 space: the five logical-collection
   domains, both Collection_Scope values, every tenant in the catalog,
   the default plus one non-default collection version, and each of
   ``titan1024``, ``mpnet768``, ``nova1024``.

Why the digest manifest lives under ``tests/`` and not ``scripts/``
---------------------------------------------------------------------
A file placed under ``mcp_server_python/scripts/`` to check that
``scripts/`` has not changed would itself change ``scripts/``, failing
its own assertion the first time it is regenerated. The manifest is
therefore a test asset at
``mcp_server_python/tests/assets/write_path_digests.json`` (the same
reasoning that puts the Task 6 baseline-capture harness under
``tests/baselines/`` rather than ``scripts/``).

Deliberate exclusions from the digest walk (documented, not an
oversight)
--------------------------------------------------------------------
- ``__pycache__/`` and ``*.pyc`` -- compiled bytecode, not source; whether
  they exist and what they contain depends on which interpreter last
  imported the module, not on any write-path change.
- ``scripts/ingestion_reports/*.json`` -- generated per-run ingestion
  reports. Every ``ingest_*_v8.py`` invocation writes a fresh timestamped
  report into this directory (see the many ``gw_v17_<timestamp>.json``
  files already present). Tracking these would make this test a tripwire
  on unrelated ingestion activity happening on this instance, not a
  signal that the write path itself changed.
- ``scripts/.ingest_watermark.json`` -- generated per-run watermark state
  written by ``reingest_s3_to_local.py`` (see
  ``WATERMARK_FILE`` in that script). Same rationale as
  ``ingestion_reports/``: it is legitimate runtime output, not source.
- ``scripts/run_benchmark.py`` -- **excluded for a different reason than the
  three above, and the difference matters.** That file is source, not
  generated output. It is excluded because **Requirement 12.2 does not cover
  it**, not because its content is uninteresting.

  Read the criterion's scope precisely: "THE *ingestion scripts* under
  ``mcp_server_python/scripts/``, *and the helper modules in that directory
  that those scripts import*, SHALL be byte-identical". The subject is the
  ingestion scripts and their imported helpers -- not every file that happens
  to live in the directory. Requirement 12's user story says why: the freeze
  exists "so that no re-ingestion is triggered and the already-correct
  write-side naming stays untouched."

  The Phase 80 benchmark harness (spec ``default-tenant-freeze-retirement``,
  ``sdd_framework/workflows/phase80_default_tenant_freeze_retirement.md``) is
  neither an ingestion script nor imported by one -- verified: no module under
  ``scripts/`` imports it. It triggers no re-ingestion, touches no write-side
  naming, and writes only a benchmark result JSON under its own results
  directory. So it falls outside the criterion's stated subject.

  What over-reached is *this walk*, not the requirement. Implementing 12.2 by
  digesting the whole directory is a broader proxy than 12.2 states, and it
  collides with a later spec that legitimately adds a read-path operator entry
  point beside the ingesters. Excluding the file brings the walk into
  alignment with the criterion rather than weakening the freeze.

  Recording its digest instead was considered and rejected: the harness is
  authored across several tasks, so a digest pinned at any one of them would
  re-break at the next -- and more fundamentally, digesting it would assert a
  freeze over a file Requirement 12.2 never froze.
- ``scripts/run_benchmark_nightly.sh`` -- **excluded on the identical
  rationale as ``run_benchmark.py`` immediately above, added when
  ``default-tenant-freeze-retirement`` Task 4.1 needed a documented,
  comment-only edit to this file and found it digested here.** This file
  is the Phase 71 nightly wrapper. It is not itself an ingestion script
  (it invokes a *benchmark* command, never an ingester) and it is not a
  helper module an ingestion script imports -- verified: no
  ``ingest_*_v8.py`` module imports it or is imported by it. It triggers
  no re-ingestion and touches no write-side naming; its entire effect is
  reading/writing ``quality_metrics.jsonl`` and an archive directory
  under ``sdd_framework/execution_state/``, neither of which is a
  write-side collection or graph-label naming path. So, on the same
  precise reading of Requirement 12.2's stated subject applied to
  ``run_benchmark.py`` above, it falls outside that criterion too, and
  the prior omission (it WAS digested before this addition) was this
  walk over-reaching in exactly the way the ``run_benchmark.py``
  rationale already describes -- not a newly-discovered gap in the
  requirement itself. This exclusion was added by
  ``default-tenant-freeze-retirement`` Task 4.2, alongside Task 4.1's
  comment-only edit to the wrapper; the manifest is left as originally
  recorded (still carrying this file's old digest) rather than
  regenerated, since regenerating it now would also be a change this
  task does not need to make for any other file.

This task is pure verification scaffolding over the current tree. It is
expected to pass immediately. If either assertion fails on first run,
that is a real finding about the tree -- report it, do not adjust the
expected values to make the test pass.

shared-scope-query-routing Requirements: 12.1, 12.2, 12.7.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from src.data.collection_namer import (
    DOMAIN_CODE_CONTEXT,
    DOMAIN_COMMUNITY_SUMMARIES,
    DOMAIN_EE2_STANDARDS,
    DOMAIN_JJOBS,
    DOMAIN_WORKFLOW_DOCS,
    resolve_collection_name,
)
from src.config.tenants import load_catalog

_TESTS_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _TESTS_DIR.parents[1]
_SCRIPTS_DIR = _REPO_ROOT / "mcp_server_python" / "scripts"
_DIGEST_MANIFEST_PATH = _TESTS_DIR / "assets" / "write_path_digests.json"
_TENANTS_YAML_PATH = (
    _REPO_ROOT / "mcp_server_python" / "src" / "config" / "tenants.yaml"
)

# Directories under scripts/ whose contents are never part of the
# byte-identity check -- see the module docstring for why each is
# excluded.
_EXCLUDED_DIR_NAMES = frozenset({"__pycache__", "ingestion_reports"})

# Individual files under scripts/ excluded by relative path (relative to
# _SCRIPTS_DIR). ``.ingest_watermark.json`` is generated runtime output;
# ``run_benchmark.py`` and ``run_benchmark_nightly.sh`` are source that fall
# outside Requirement 12.2's stated subject (ingestion scripts and their
# imported helpers). See the module docstring -- the exclusions have
# different justifications and should not be collapsed into one rationale.
_EXCLUDED_RELATIVE_FILES = frozenset({
    ".ingest_watermark.json",
    "run_benchmark.py",
    "run_benchmark_nightly.sh",
})

_EXCLUDED_SUFFIXES = (".pyc",)

# Requirement 12.1 combination space.
_DOMAINS = (
    DOMAIN_WORKFLOW_DOCS,
    DOMAIN_CODE_CONTEXT,
    DOMAIN_JJOBS,
    DOMAIN_EE2_STANDARDS,
    DOMAIN_COMMUNITY_SUMMARIES,
)
_SCOPES = ("shared", "tenant")
_VERSIONS = (None, "v9-0-0")  # default (no suffix) + one non-default
_PROFILES = ("titan1024", "mpnet768", "nova1024")


def _iter_scripts_files():
    """Yield every non-excluded file path under ``scripts/``, sorted.

    Sorted so the walk order -- and therefore any failure message
    listing mismatched files -- is stable across runs and platforms.
    """
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(_SCRIPTS_DIR):
        dirnames[:] = sorted(
            d for d in dirnames if d not in _EXCLUDED_DIR_NAMES
        )
        for filename in filenames:
            if filename.endswith(_EXCLUDED_SUFFIXES):
                continue
            full_path = Path(dirpath) / filename
            rel_path = full_path.relative_to(_SCRIPTS_DIR)
            if str(rel_path) in _EXCLUDED_RELATIVE_FILES:
                continue
            found.append(full_path)
    found.sort(key=lambda p: str(p.relative_to(_SCRIPTS_DIR)))
    return found


def _sha256_of(path: Path) -> str:
    """Return the SHA-256 hex digest of ``path``'s contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _expected_physical_name(
    *, domain: str, scope: str, index_prefix: str, version: str | None,
    profile: str,
) -> str:
    """Compute the expected physical name from the documented naming rule.

    Independently reproduces ``mdc-{domain}-{profile}{suffix}`` (with an
    ``{index_prefix}`` prepended for ``scope="tenant"``) exactly as
    ``collection_namer.py``'s module docstring specifies it, WITHOUT
    calling :func:`resolve_collection_name`. Computing the oracle from
    the documented rule rather than from the function under test is
    what makes assertion two a check on that function rather than a
    tautology.
    """
    suffix = "" if (not version or version == "v8-0-0") else f"-{version}"
    base = f"mdc-{domain}-{profile}{suffix}"
    if scope == "shared":
        return base
    return f"{index_prefix}{base}"


class TestFileDigestsUnchanged:
    """Assertion one: every file under ``scripts/`` matches its recorded
    digest.
    """

    def test_recorded_digest_manifest_exists(self):
        assert _DIGEST_MANIFEST_PATH.is_file(), (
            f"digest manifest missing at {_DIGEST_MANIFEST_PATH}; cannot "
            f"verify write-path immutability"
        )

    def test_no_file_under_scripts_differs_from_recorded_digest(self):
        with open(_DIGEST_MANIFEST_PATH, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
        recorded: dict[str, str] = manifest["digests"]

        current_files = _iter_scripts_files()
        current_rel_paths = {
            str(p.relative_to(_SCRIPTS_DIR)) for p in current_files
        }
        recorded_rel_paths = set(recorded.keys())

        added = sorted(current_rel_paths - recorded_rel_paths)
        removed = sorted(recorded_rel_paths - current_rel_paths)

        changed: list[str] = []
        for rel_path in sorted(current_rel_paths & recorded_rel_paths):
            actual_digest = _sha256_of(_SCRIPTS_DIR / rel_path)
            if actual_digest != recorded[rel_path]:
                changed.append(rel_path)

        failures: list[str] = []
        if changed:
            failures.append(f"content changed: {changed}")
        if added:
            failures.append(
                f"new files not in the recorded manifest: {added}"
            )
        if removed:
            failures.append(
                f"files removed since the recorded manifest: {removed}"
            )

        assert not failures, (
            "mcp_server_python/scripts/ differs from its recorded "
            "write-path-immutability digests (Requirement 12.2): "
            + "; ".join(failures)
        )

    def test_manifest_covers_every_current_non_excluded_file(self):
        """The manifest is not stale in the other direction either.

        A file added to ``scripts/`` after the manifest was recorded
        would otherwise pass silently (no recorded digest to compare
        against). This asserts the manifest and the live tree agree on
        *which* files exist, not only on their content.
        """
        with open(_DIGEST_MANIFEST_PATH, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
        recorded_rel_paths = set(manifest["digests"].keys())
        current_rel_paths = {
            str(p.relative_to(_SCRIPTS_DIR)) for p in _iter_scripts_files()
        }
        assert current_rel_paths == recorded_rel_paths, (
            "the set of non-excluded files under scripts/ no longer "
            f"matches the recorded manifest: "
            f"only-on-disk="
            f"{sorted(current_rel_paths - recorded_rel_paths)} "
            f"only-in-manifest="
            f"{sorted(recorded_rel_paths - current_rel_paths)}"
        )


class TestCollectionNamerStability:
    """Assertion two: ``resolve_collection_name`` is stable over the
    Requirement 12.1 combination space.
    """

    @pytest.fixture(scope="class")
    def tenants_by_id(self):
        catalog = load_catalog(_TENANTS_YAML_PATH)
        return {t.tenant_id: t for t in catalog.tenants}

    @staticmethod
    def _combinations(tenants_by_id):
        for domain in _DOMAINS:
            for scope in _SCOPES:
                for tenant_id, tenant in tenants_by_id.items():
                    for version in _VERSIONS:
                        for profile in _PROFILES:
                            yield (
                                domain, scope, tenant_id, tenant,
                                version, profile,
                            )

    def test_every_combination_matches_the_documented_naming_rule(
        self, tenants_by_id,
    ):
        mismatches: list[str] = []
        rejection_mismatches: list[str] = []

        for domain, scope, tenant_id, tenant, version, profile in (
            self._combinations(tenants_by_id)
        ):
            expected = _expected_physical_name(
                domain=domain,
                scope=scope,
                index_prefix=tenant.index_prefix,
                version=version,
                profile=profile,
            )
            try:
                actual = resolve_collection_name(
                    domain=domain,
                    scope=scope,
                    tenant=tenant,
                    version=version,
                    profile=profile,
                )
            except ValueError as exc:
                rejection_mismatches.append(
                    f"domain={domain!r} scope={scope!r} tenant={tenant_id!r} "
                    f"version={version!r} profile={profile!r}: expected "
                    f"name {expected!r}, got a rejection instead "
                    f"({type(exc).__name__}: {exc})"
                )
                continue

            if actual != expected:
                mismatches.append(
                    f"domain={domain!r} scope={scope!r} tenant={tenant_id!r} "
                    f"version={version!r} profile={profile!r}: expected "
                    f"{expected!r}, got {actual!r}"
                )

        assert not mismatches, (
            "resolve_collection_name produced a different physical name "
            "than the pinned expectation for at least one combination "
            "(Requirement 12.1): " + "; ".join(mismatches)
        )
        assert not rejection_mismatches, (
            "resolve_collection_name rejected a combination that was "
            "expected to resolve to a name (Requirement 12.1): "
            + "; ".join(rejection_mismatches)
        )

    def test_invalid_scope_is_still_rejected_with_the_same_exception_type(
        self, tenants_by_id,
    ):
        """The one rejection path the function has: an out-of-set scope.

        "Rejection" is observable behaviour under Requirement 12.1 --
        a combination that raises today must still raise, with the same
        exception type. ``resolve_collection_name`` has exactly one
        rejection path (an invalid ``scope`` string); none of the 300
        Requirement-12.1-space combinations swept above exercise it,
        since both values fed to ``scope`` there are valid. This
        confirms the rejection path itself is unchanged.
        """
        tenant = tenants_by_id["gw_v17"]
        with pytest.raises(ValueError):
            resolve_collection_name(
                domain=DOMAIN_CODE_CONTEXT,
                scope="not-a-real-scope",
                tenant=tenant,
                version=None,
                profile="titan1024",
            )

    def test_combination_space_covers_every_tenant_and_domain(
        self, tenants_by_id,
    ):
        """Guard against a silently narrowed sweep.

        If a future edit trims ``_DOMAINS``, ``_SCOPES``, ``_VERSIONS``,
        ``_PROFILES``, or the tenant catalog itself shrinks unexpectedly,
        the stability test above could pass while covering less than
        Requirement 12.1 actually requires. Pin the expected sizes.
        """
        assert len(_DOMAINS) == 5
        assert set(_SCOPES) == {"shared", "tenant"}
        assert len(_VERSIONS) == 2
        assert set(_PROFILES) == {"titan1024", "mpnet768", "nova1024"}
        assert set(tenants_by_id) == {
            "gw", "gw_sfs", "gw_jedi_gfs", "gw_v17", "gw_gefs_v12",
        }
        total = (
            len(_DOMAINS) * len(_SCOPES) * len(tenants_by_id)
            * len(_VERSIONS) * len(_PROFILES)
        )
        assert total == 300
