"""Neo4j target writer (COTS restore, Task 8).

Loads a Graph_Export into Neo4j. Two paths:

* **bulk** -- shell out to ``neo4j-admin import`` over the
  locally-extracted Neptune-loader CSV files (preferred for > ~10K nodes);
  the same CSVs load unchanged because the Neptune-loader CSV format is a
  superset of ``neo4j-admin import``'s format.
* **transactional** -- ``UNWIND``-batched ``CREATE`` for small deltas.

Tenant-prefixed labels (``GW_V17_FortranSubroutine``) are preserved verbatim
(R2.3): Neo4j accepts arbitrary label strings, so the prefix becomes the
tenant scoper.

The adapter operates on injected callables so unit tests avoid a live Neo4j:
``runner`` runs a shell command (bulk path) and ``session_fn`` yields a
transaction-like object (transactional path).

Requirements: 2.2, 2.3, 2.5.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional, Sequence

from portable_export.adapters import NodeRow, RelRow

#: Supported Neo4j major versions.
SUPPORTED_NEO4J_MAJORS: frozenset[int] = frozenset({4, 5})

#: Transactional batch size.
DEFAULT_BATCH: int = 1000


class Neo4jVersionError(Exception):
    """The Neo4j server version is outside the supported range."""


@dataclass
class GraphLoadResult:
    """Outcome of a graph load for one tenant."""

    tenant: str
    nodes: int = 0
    relationships: int = 0
    method: str = "transactional"
    command: Optional[str] = None


def assert_supported_version(version: str) -> None:
    """Refuse a Neo4j version whose major is unsupported."""
    major = int(version.split(".", 1)[0]) if version and version[0].isdigit() else -1
    if major not in SUPPORTED_NEO4J_MAJORS:
        raise Neo4jVersionError(
            f"Neo4j version {version} unsupported; need major in "
            f"{sorted(SUPPORTED_NEO4J_MAJORS)}"
        )


def build_admin_import_command(
    *,
    database: str,
    node_csvs: Sequence[str],
    rel_csvs: Sequence[str],
    neo4j_admin: str = "neo4j-admin",
) -> str:
    """Build the ``neo4j-admin database import`` command string.

    The CSVs are Neptune-loader format (a superset of neo4j-admin's). Paths are
    shell-quoted to prevent injection from a hostile filename.
    """
    parts = [neo4j_admin, "database", "import", "full"]
    for csv in node_csvs:
        parts.append(f"--nodes={shlex.quote(csv)}")
    for csv in rel_csvs:
        parts.append(f"--relationships={shlex.quote(csv)}")
    parts.append(shlex.quote(database))
    return " ".join(parts)


class Neo4jWriter:
    """Neo4j COTS writer (bulk import + transactional paths).

    Parameters
    ----------
    runner
        Callable ``runner(cmd: str) -> Any`` that executes a shell command
        (bulk path). Injected for tests.
    session_fn
        Callable returning a context-manager session whose ``run(cypher,
        **params)`` executes a statement (transactional path). Injected.
    version
        Neo4j server version; validated unless ``validate_version=False``.
    database
        Target database name (bulk import).
    """

    def __init__(
        self,
        *,
        runner: Optional[Callable[[str], Any]] = None,
        session_fn: Optional[Callable[[], Any]] = None,
        version: str = "5.0.0",
        validate_version: bool = True,
        database: str = "neo4j",
    ) -> None:
        if validate_version:
            assert_supported_version(version)
        self._runner = runner
        self._session_fn = session_fn
        self._database = database

    # ── bulk path ──────────────────────────────────────────────────────

    def load_graph_bundle(
        self, tenant: str, nodes_uris: Sequence[str], rels_uris: Sequence[str]
    ) -> GraphLoadResult:
        """Bulk-import a tenant's extracted CSV files via neo4j-admin (R2.2)."""
        if self._runner is None:
            raise RuntimeError("bulk load requires a runner callable")
        cmd = build_admin_import_command(
            database=self._database,
            node_csvs=list(nodes_uris),
            rel_csvs=list(rels_uris),
        )
        self._runner(cmd)
        return GraphLoadResult(tenant=tenant, method="bulk", command=cmd)

    # ── transactional path ─────────────────────────────────────────────

    def write_nodes(
        self, nodes: Iterable[NodeRow], *, batch: int = DEFAULT_BATCH
    ) -> int:
        """Transactionally create nodes preserving labels (R2.3)."""
        if self._session_fn is None:
            raise RuntimeError("transactional write requires a session_fn")
        count = 0
        buf: list[NodeRow] = []
        with self._session_fn() as session:
            for n in nodes:
                buf.append(n)
                if len(buf) >= batch:
                    count += self._flush_nodes(session, buf)
                    buf = []
            if buf:
                count += self._flush_nodes(session, buf)
        return count

    @staticmethod
    def _flush_nodes(session: Any, nodes: list[NodeRow]) -> int:
        # group by label so each UNWIND uses a literal (safe) label.
        by_label: dict[str, list[dict]] = {}
        for n in nodes:
            by_label.setdefault(n.label, []).append(
                {"id": n.id, "props": n.properties}
            )
        for label, rows in by_label.items():
            # label is from a controlled catalog-prefixed set; backtick-quote.
            session.run(
                f"UNWIND $rows AS row CREATE (n:`{label}`) "
                f"SET n = row.props SET n.`_pe_id` = row.id",
                rows=rows,
            )
        return sum(len(v) for v in by_label.values())

    def write_relationships(
        self, rels: Iterable[RelRow], *, batch: int = DEFAULT_BATCH
    ) -> int:
        """Transactionally create relationships by ``_pe_id`` endpoints."""
        if self._session_fn is None:
            raise RuntimeError("transactional write requires a session_fn")
        count = 0
        buf: list[RelRow] = []
        with self._session_fn() as session:
            for r in rels:
                buf.append(r)
                if len(buf) >= batch:
                    count += self._flush_rels(session, buf)
                    buf = []
            if buf:
                count += self._flush_rels(session, buf)
        return count

    @staticmethod
    def _flush_rels(session: Any, rels: list[RelRow]) -> int:
        by_type: dict[str, list[dict]] = {}
        for r in rels:
            by_type.setdefault(r.type, []).append(
                {"start": r.start, "end": r.end, "props": r.properties}
            )
        for rtype, rows in by_type.items():
            session.run(
                "UNWIND $rows AS row "
                "MATCH (a {`_pe_id`: row.start}), (b {`_pe_id`: row.end}) "
                f"CREATE (a)-[rel:`{rtype}`]->(b) SET rel = row.props",
                rows=rows,
            )
        return sum(len(v) for v in by_type.values())

    def count_graph(self, tenant: str) -> tuple[int, int]:
        """Return ``(node_count, rel_count)`` -- transactional path only."""
        if self._session_fn is None:
            return (0, 0)
        with self._session_fn() as session:
            nrows = session.run("MATCH (n) RETURN count(n) AS c")
            rrows = session.run("MATCH ()-[r]->() RETURN count(r) AS c")
        return (_first_count(nrows), _first_count(rrows))


def _first_count(rows: Any) -> int:
    rows = list(rows)
    return int(rows[0].get("c", 0)) if rows else 0


__all__ = [
    "Neo4jWriter",
    "Neo4jVersionError",
    "GraphLoadResult",
    "assert_supported_version",
    "build_admin_import_command",
]
