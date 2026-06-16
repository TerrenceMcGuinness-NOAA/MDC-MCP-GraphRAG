"""Neptune source reader (Task 6).

Streams the property graph per tenant via openCypher: nodes (label +
properties) and relationships (type + endpoints + properties). The reader
operates on an injected client modelled on
:class:`src.data.neptune_adapter.NeptuneAdapter` -- a synchronous ``query``
callable ``query(cypher, params) -> list[dict]`` (SigV4-signed HTTPS in
production). Unit tests inject a fake that records every Cypher string so the
read-only invariant (Property 5) can be asserted: only ``MATCH`` / ``RETURN``
/ label-introspection queries are issued -- never ``CREATE`` / ``MERGE`` /
``SET`` / ``DELETE`` / ``REMOVE``.

Tenant scoping uses the label prefix (R7.2, R7.3): the default ``gw`` tenant
owns labels without any known foreign prefix; a non-default tenant owns labels
beginning with its ``label_prefix`` (e.g. ``GW_V17_``). Large label sets are
chunked with ``SKIP`` / ``LIMIT`` pagination.

Requirements: 1.2, 1.5, 7.1, 7.2, 7.3.
"""

from __future__ import annotations

import re
from typing import Any, Iterator, Optional

from portable_export.adapters import NodeRow, RelRow

#: Cypher verbs that mutate the graph -- never emitted by this reader.
_MUTATING_RE = re.compile(
    r"\b(CREATE|MERGE|SET|DELETE|REMOVE|DROP|DETACH)\b", re.IGNORECASE
)

#: Node-page size for SKIP/LIMIT pagination.
DEFAULT_PAGE: int = 1000


def is_read_only(cypher: str) -> bool:
    """Return ``True`` when ``cypher`` contains no mutating verb."""
    return _MUTATING_RE.search(cypher) is None


class NeptuneReader:
    """Read-only openCypher streaming reader.

    Parameters
    ----------
    query_fn
        Callable ``query(cypher, params=None) -> list[dict]``. In production
        this wraps the SigV4 Neptune adapter; tests inject a fake.
    label_prefixes
        Mapping ``tenant_id -> label_prefix`` for every tenant.
    page_size
        SKIP/LIMIT page size for node/relationship streaming.
    """

    def __init__(
        self,
        query_fn: Any,
        *,
        label_prefixes: dict[str, str],
        page_size: int = DEFAULT_PAGE,
    ) -> None:
        self._query = query_fn
        self._label_prefixes = dict(label_prefixes)
        self._page = page_size

    def _run(self, cypher: str, params: Optional[dict] = None) -> list[dict]:
        # Defensive: refuse to issue a mutating query from the read path.
        if not is_read_only(cypher):
            raise RuntimeError(
                f"NeptuneReader refused a non-read-only query: {cypher!r}"
            )
        return list(self._query(cypher, params or {}))

    # ── label families ────────────────────────────────────────────────

    def all_labels(self) -> list[str]:
        """Return every distinct node label in the graph."""
        rows = self._run("MATCH (n) RETURN DISTINCT labels(n) AS labels")
        labels: set[str] = set()
        for r in rows:
            for lbl in r.get("labels", []) or []:
                labels.add(lbl)
        return sorted(labels)

    def _non_default_prefixes(self) -> list[str]:
        return [p for p in self._label_prefixes.values() if p]

    def label_families_for_tenant(self, tenant_id: str) -> list[str]:
        """Return the label family owned by ``tenant_id`` (R7.2, R7.3)."""
        prefix = self._label_prefixes.get(tenant_id, "")
        labels = self.all_labels()
        if prefix:
            return sorted(l for l in labels if l.startswith(prefix))
        foreign = self._non_default_prefixes()
        return sorted(
            l for l in labels
            if not any(l.startswith(fp) for fp in foreign)
        )

    def list_graph_label_families(self, tenants: list[str]) -> list[str]:
        seen: list[str] = []
        for t in tenants:
            for lbl in self.label_families_for_tenant(t):
                if lbl not in seen:
                    seen.append(lbl)
        return seen

    # ── counts (preflight) ────────────────────────────────────────────

    def count_nodes(self, tenant_id: str) -> int:
        total = 0
        for label in self.label_families_for_tenant(tenant_id):
            rows = self._run(f"MATCH (n:`{label}`) RETURN count(n) AS c")
            total += int(rows[0].get("c", 0)) if rows else 0
        return total

    def count_relationships(self, tenant_id: str) -> int:
        labels = set(self.label_families_for_tenant(tenant_id))
        if not labels:
            return 0
        # Count relationships whose start node is owned by the tenant.
        rows = self._run(
            "MATCH (a)-[r]->(b) RETURN labels(a) AS la, count(r) AS c"
        )
        total = 0
        for r in rows:
            if any(l in labels for l in (r.get("la") or [])):
                total += int(r.get("c", 0))
        return total

    # ── streaming ──────────────────────────────────────────────────────

    def stream_nodes(self, tenant: str) -> Iterator[NodeRow]:
        """Yield every :class:`NodeRow` owned by ``tenant`` (paginated)."""
        for label in self.label_families_for_tenant(tenant):
            skip = 0
            while True:
                rows = self._run(
                    f"MATCH (n:`{label}`) RETURN id(n) AS id, "
                    f"properties(n) AS props ORDER BY id(n) "
                    f"SKIP {skip} LIMIT {self._page}"
                )
                if not rows:
                    break
                for r in rows:
                    yield NodeRow(
                        id=str(r.get("id")),
                        label=label,
                        properties=dict(r.get("props") or {}),
                    )
                if len(rows) < self._page:
                    break
                skip += self._page

    def stream_relationships(self, tenant: str) -> Iterator[RelRow]:
        """Yield every :class:`RelRow` whose start node is owned by ``tenant``.

        Scoped per-label to avoid full-graph scans that exceed Neptune's
        statement timeout on large graphs.
        """
        labels = list(self.label_families_for_tenant(tenant))
        if not labels:
            return
        for label in labels:
            skip = 0
            while True:
                rows = self._run(
                    f"MATCH (a:`{label}`)-[r]->(b) RETURN id(r) AS id, type(r) AS type, "
                    f"id(a) AS start, id(b) AS end, "
                    f"properties(r) AS props ORDER BY id(r) "
                    f"SKIP {skip} LIMIT {self._page}"
                )
                if not rows:
                    break
                for r in rows:
                    yield RelRow(
                        id=str(r.get("id")),
                        type=r.get("type"),
                        start=str(r.get("start")),
                        end=str(r.get("end")),
                        properties=dict(r.get("props") or {}),
                    )
                if len(rows) < self._page:
                    break
                skip += self._page

    # vector-half stubs so a NeptuneReader satisfies SourceReader structurally
    def list_index_families(self, tenants: list[str]) -> list[str]:  # pragma: no cover
        return []

    def scroll_records(self, index: str, batch: int = 0):  # pragma: no cover
        return iter(())

    def read_dedupe_registry(self):  # pragma: no cover
        return iter(())


__all__ = ["NeptuneReader", "is_read_only", "DEFAULT_PAGE"]
