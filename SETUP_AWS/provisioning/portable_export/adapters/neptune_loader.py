"""Neptune bulk-loader target adapter (Task 7).

Re-imports a Graph_Export into Neptune using the Neptune bulk-loader REST API:
POST ``/loader`` with the S3 source prefix + the bulk-loader IAM role, then
poll ``GET /loader/<loadId>`` until the overall status reaches
``LOAD_COMPLETED`` (or a terminal failure). The loader expects S3-resident
CSV files in Neptune-loader format -- the Graph_Export parts written by
``export_graph`` are already in that layout (R3.2).

The adapter operates on an injected ``loader_fn`` so unit tests drive the poll
loop without HTTP. In production ``loader_fn`` wraps the SigV4-signed HTTPS
calls (same transport as :mod:`src.data.aws_backend`).

Requirements: 3.2.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

#: Terminal loader statuses.
STATUS_COMPLETE = "LOAD_COMPLETED"
_TERMINAL_FAILURES = frozenset(
    {
        "LOAD_FAILED",
        "LOAD_CANCELLED_BY_USER",
        "LOAD_CANCELLED_DUE_TO_ERRORS",
        "LOAD_UNEXPECTED_ERROR",
        "LOAD_DATA_DEADLOCK",
        "LOAD_DATA_FAILED_DUE_TO_FEED_MODIFIED_OR_DELETED",
        "LOAD_FAILED_BECAUSE_DEPENDENCY_NOT_SATISFIED",
        "LOAD_FAILED_INVALID_REQUEST",
    }
)


class NeptuneLoaderError(Exception):
    """A Neptune bulk-loader job ended in a terminal failure state."""

    def __init__(self, message: str, *, load_id: Optional[str] = None,
                 status: Optional[str] = None) -> None:
        super().__init__(message)
        self.load_id = load_id
        self.status = status


class NeptuneLoader:
    """Starts and polls a Neptune bulk-loader job.

    Parameters
    ----------
    loader_fn
        Callable ``loader_fn(action, payload) -> dict`` where ``action`` is
        ``"start"`` or ``"status"``. ``start`` returns ``{"loadId": ...}``;
        ``status`` returns the loader status payload
        ``{"payload": {"overallStatus": {"status": ...}}}``.
    s3_loader_role_arn
        IAM role ARN the loader assumes to read the S3 source.
    region
        AWS region (recorded in the start request).
    poll_interval
        Seconds between status polls.
    sleep_fn
        Injectable sleep (tests pass a no-op).
    """

    def __init__(
        self,
        loader_fn: Callable[[str, dict], dict],
        *,
        s3_loader_role_arn: str,
        region: str = "us-east-1",
        poll_interval: float = 5.0,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self._loader = loader_fn
        self._role = s3_loader_role_arn
        self._region = region
        self._poll = poll_interval
        self._sleep = sleep_fn

    def start(self, s3_source_uri: str, *, fmt: str = "csv") -> str:
        """Start a loader job for ``s3_source_uri``; return the load id."""
        resp = self._loader(
            "start",
            {
                "source": s3_source_uri,
                "format": fmt,
                "iamRoleArn": self._role,
                "region": self._region,
                "failOnError": "TRUE",
                "parallelism": "MEDIUM",
            },
        )
        load_id = resp.get("payload", {}).get("loadId") or resp.get("loadId")
        if not load_id:
            raise NeptuneLoaderError(
                f"loader start returned no loadId: {resp!r}"
            )
        return load_id

    def status(self, load_id: str) -> str:
        """Return the current ``overallStatus.status`` for ``load_id``."""
        resp = self._loader("status", {"loadId": load_id})
        return (
            resp.get("payload", {})
            .get("overallStatus", {})
            .get("status", "")
        )

    def wait(self, load_id: str, *, max_polls: int = 1000) -> str:
        """Poll until the job completes; raise on terminal failure.

        Returns ``LOAD_COMPLETED`` on success.
        """
        for _ in range(max_polls):
            status = self.status(load_id)
            if status == STATUS_COMPLETE:
                return status
            if status in _TERMINAL_FAILURES:
                raise NeptuneLoaderError(
                    f"Neptune bulk load {load_id} failed: {status}",
                    load_id=load_id,
                    status=status,
                )
            self._sleep(self._poll)
        raise NeptuneLoaderError(
            f"Neptune bulk load {load_id} did not complete within "
            f"{max_polls} polls",
            load_id=load_id,
            status="TIMEOUT",
        )

    def load_graph_bundle(self, tenant: str, nodes_uris, rels_uris) -> str:
        """Start + wait a loader job for a tenant's graph prefix.

        ``nodes_uris`` / ``rels_uris`` here is the common S3 prefix string
        (the loader recurses into ``nodes/`` and ``rels/``); accepted as a
        single source URI for protocol symmetry.
        """
        source = nodes_uris if isinstance(nodes_uris, str) else rels_uris
        load_id = self.start(source)
        return self.wait(load_id)


__all__ = ["NeptuneLoader", "NeptuneLoaderError", "STATUS_COMPLETE"]
