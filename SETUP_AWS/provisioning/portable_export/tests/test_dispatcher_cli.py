"""Dispatcher + CLI tests (Task 13.1) + Property 7 (confirmation gate).

Every direction resolves to the expected adapter pair; selective scope honored;
--dry-run mutates nothing; status does not lock. Property 7: no destination
write call across any restore / reimport path until confirmation phrase or
--yes is captured.

Requirements: 9.4, 14.1, 14.2, 14.3, 14.4, 14.5, 15.1, 15.2.
"""

from __future__ import annotations

import io

import pytest

from portable_export.adapters import NodeRow, RelRow
from portable_export.direction_dispatcher import (
    AWS_EXPORT,
    AWS_REIMPORT,
    COTS_RESTORE,
    DispatchError,
    build_scope,
    confirmation_satisfied,
    execute_restore,
    needs_confirmation,
    resolve_direction,
)
from portable_export.kms_writer import compute_sha256
from portable_export.manifest import ExportManifest
from portable_export.phases.export_vectors import export_collection
from portable_export import portable_export_cli as cli


# ── Direction resolution ──────────────────────────────────────────────────────


def test_resolve_directions():
    assert resolve_direction(AWS_EXPORT).source_adapters == (
        "opensearch_reader", "neptune_reader")
    assert resolve_direction(AWS_EXPORT).target_adapters == ()
    assert resolve_direction(COTS_RESTORE).target_adapters == (
        "chromadb_writer", "neo4j_writer")
    assert resolve_direction(COTS_RESTORE).target_kind == "cots"
    assert resolve_direction(AWS_REIMPORT).target_adapters == (
        "opensearch_writer", "neptune_loader")
    assert resolve_direction(AWS_REIMPORT).target_kind == "aws"


def test_unknown_direction_refused():
    with pytest.raises(DispatchError):
        resolve_direction("Sideways_Teleport")


# ── Scope ─────────────────────────────────────────────────────────────────────


def test_scope_full_default():
    s = build_scope()
    assert s.vectors and s.graph and s.dedupe


def test_scope_vectors_only():
    s = build_scope(vectors_only=True)
    assert s.vectors is True and s.graph is False


def test_scope_graph_only():
    s = build_scope(graph_only=True)
    assert s.graph is True and s.vectors is False


def test_scope_mutually_exclusive():
    with pytest.raises(DispatchError):
        build_scope(vectors_only=True, graph_only=True)


def test_scope_collection_selection_drops_dedupe():
    s = build_scope(collections=["mdc-code-context-titan1024"])
    assert s.collections == ("mdc-code-context-titan1024",)
    assert s.dedupe is False


# ── Confirmation helpers ──────────────────────────────────────────────────────


def test_needs_confirmation():
    assert needs_confirmation({"c": 5}) is True
    assert needs_confirmation({}) is False


def test_confirmation_satisfied():
    assert confirmation_satisfied(yes=True, provided_phrase=None, expected_phrase="x")
    assert confirmation_satisfied(yes=False, provided_phrase="x", expected_phrase="x")
    assert not confirmation_satisfied(yes=False, provided_phrase="y", expected_phrase="x")
    assert not confirmation_satisfied(yes=False, provided_phrase=None, expected_phrase="x")


# ── Property 7: no write before confirmation ─────────────────────────────────


class ExplodingVectorTarget:
    """Any write attempt fails the test (proves Property 7)."""

    def ensure_collection_or_index(self, name, model_profile):
        raise AssertionError("ensure_collection_or_index called before confirmation")

    def bulk_insert_vectors(self, collection, records):
        raise AssertionError("bulk_insert_vectors called before confirmation")


class RecordingAudit:
    def __init__(self):
        self.events = []

    def emit(self, event_type, **kw):
        self.events.append(event_type)
        return {"event_type": event_type}


def _manifest_with_vectors(sample_vector_records):
    kms_objs = {}

    class _Kms:
        def put(self, key, body, content_type="application/octet-stream"):
            kms_objs[key] = body
            return compute_sha256(body)

    class _Reader:
        def scroll_records(self, index, batch):
            yield sample_vector_records

    m = ExportManifest.new(manifest_id="m", tenants=["gw"])
    entry = export_collection(_Reader(), _Kms(), None, prefix="pfx/", tenant="gw",
                              collection="mdc-code-context-titan1024",
                              model_profile="titan1024")
    m.add_vector_export(entry)
    return m, (lambda k: kms_objs[k])


def test_property7_no_write_when_unconfirmed_nonempty_target(sample_vector_records):
    m, fetch = _manifest_with_vectors(sample_vector_records)
    audit = RecordingAudit()
    outcome = execute_restore(
        COTS_RESTORE, manifest=m, fetch=fetch,
        vector_target=ExplodingVectorTarget(), graph_target=None,
        probe_result={"mdc-code-context-titan1024": 10},  # non-empty target
        confirmed=False, audit=audit,
    )
    assert outcome.performed is False
    assert "Confirmation_Declined" in audit.events
    # ExplodingVectorTarget asserts if any write was attempted -> reaching here
    # proves no write occurred.


def test_property7_write_proceeds_when_confirmed(sample_vector_records):
    m, fetch = _manifest_with_vectors(sample_vector_records)

    class FakeColl:
        def __init__(self): self.ids = []
        def add(self, *, ids, documents, embeddings, metadatas): self.ids += list(ids)
        def count(self): return len(self.ids)

    class FakeChroma:
        def __init__(self): self.collections = {}
        def get_or_create_collection(self, name):
            return self.collections.setdefault(name, FakeColl())
        def list_collections(self): return list(self.collections)

    from portable_export.adapters.chromadb_writer import ChromaDBWriter
    target = ChromaDBWriter(FakeChroma(), version="0.5.0")
    audit = RecordingAudit()
    outcome = execute_restore(
        COTS_RESTORE, manifest=m, fetch=fetch, vector_target=target,
        probe_result={"x": 1}, confirmed=True, audit=audit,
    )
    assert outcome.performed is True
    assert outcome.vector_report.total_loaded == 2
    assert "COTS_Restore_Completed" in audit.events


def test_property7_empty_target_needs_no_confirmation(sample_vector_records):
    m, fetch = _manifest_with_vectors(sample_vector_records)

    class FakeColl:
        def __init__(self): self.ids = []
        def add(self, *, ids, documents, embeddings, metadatas): self.ids += list(ids)
        def count(self): return len(self.ids)

    class FakeChroma:
        def __init__(self): self.collections = {}
        def get_or_create_collection(self, name):
            return self.collections.setdefault(name, FakeColl())
        def list_collections(self): return list(self.collections)

    from portable_export.adapters.chromadb_writer import ChromaDBWriter
    target = ChromaDBWriter(FakeChroma(), version="0.5.0")
    # empty probe -> no confirmation needed, proceeds even unconfirmed
    outcome = execute_restore(COTS_RESTORE, manifest=m, fetch=fetch,
                              vector_target=target, probe_result={}, confirmed=False)
    assert outcome.performed is True


def test_reimport_query_compat_aws_all_compatible(sample_vector_records):
    m, fetch = _manifest_with_vectors(sample_vector_records)

    class FakeOSClient:
        def __init__(self): self.docs = {}
        def index_exists(self, *, index): return False
        def get_mapping(self, *, index): return {index: {"mappings": {"properties": {}}}}
        def create_index(self, *, index, body): self.docs.setdefault(index, [])
        def bulk(self, *, body):
            for i in range(0, len(body), 2):
                self.docs.setdefault(body[i]["index"]["_index"], []).append(body[i+1])
        def count(self, *, index): return {"count": len(self.docs.get(index, []))}

    from portable_export.adapters.opensearch_writer import OpenSearchWriter
    target = OpenSearchWriter(FakeOSClient())
    outcome = execute_restore(AWS_REIMPORT, manifest=m, fetch=fetch,
                              vector_target=target, probe_result={}, confirmed=True)
    assert outcome.performed is True
    assert outcome.query_compatibility.all_compatible is True
    # dedupe rebuilt deterministically on reimport
    assert outcome.dedupe_rows is not None


# ── CLI ───────────────────────────────────────────────────────────────────────


def test_cli_parser_subcommands():
    p = cli.build_parser()
    args = p.parse_args(["export", "--env", "dev", "--dry-run"])
    assert args.command == "export"
    args = p.parse_args(["restore", "--artefact", "s3://x", "--dry-run"])
    assert args.command == "restore"


def test_cli_vectors_and_graph_only_mutually_exclusive():
    p = cli.build_parser()
    with pytest.raises(SystemExit):
        p.parse_args(["export", "--env", "dev", "--vectors-only", "--graph-only"])


def test_cli_export_dry_run_mutates_nothing():
    out = io.StringIO()
    rc = cli.main(["export", "--env", "dev", "--tenants", "gw,gw_v17", "--dry-run"],
                  out=out)
    assert rc == 0
    text = out.getvalue()
    assert "DRY-RUN" in text
    assert "AWS_Export" in text
    # ASCII only
    text.encode("ascii")


def test_cli_restore_dry_run_plan():
    out = io.StringIO()
    rc = cli.main(["restore", "--artefact", "s3://b/pfx/", "--dry-run"], out=out)
    assert rc == 0
    assert "COTS_Restore" in out.getvalue()
    assert "confirmation phrase or --yes" in out.getvalue()


def test_cli_reimport_dry_run_plan():
    out = io.StringIO()
    rc = cli.main(["reimport", "--artefact", "s3://b/pfx/", "--env", "dev",
                   "--dry-run"], out=out)
    assert rc == 0
    text = out.getvalue()
    assert "AWS_Reimport" in text
    assert "env=dev" in text


def test_cli_status_does_not_lock():
    out = io.StringIO()
    rc = cli.main(["status", "--artefact", "s3://b/pfx/"], out=out)
    # status is gated for live read but must declare it never locks
    assert "no lock acquired" in out.getvalue()


def test_expected_confirmation_phrase():
    assert cli.expected_confirmation_phrase(AWS_REIMPORT, env="dev-reimport") == "dev-reimport"
    assert cli.expected_confirmation_phrase(COTS_RESTORE) == "restore-cots"
