"""Direction-agnostic transfer phases for the Portable_Export pipeline.

Each phase calls the injected Source/Target adapters and the shared primitives
(manifest, watermarks, KMS writer) and never branches on which engine is on
either side. Export phases write the S3 Portable_Export; restore phases read
it and load a target.
"""

from __future__ import annotations

__all__: list[str] = []
