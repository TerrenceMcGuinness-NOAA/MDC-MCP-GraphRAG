"""Export_Bundle pack / unpack (Task 12).

Packages a complete Portable_Export (manifest + every Vector_Export part +
every Graph_Export part + the Dedupe_Registry_Export) into a single
``<prefix>.tar.gz`` for offline transfer to a disconnected COTS host (R12.1,
R12.2). The internal layout is preserved verbatim so a COTS_Restore from a
bundle restores the same data as the equivalent S3-native layout (R12.4): the
keys inside the tarball are exactly the S3 keys (relative to the prefix).

The pack/unpack operate on an in-memory object map ``{relative_key: bytes}`` so
they are testable without S3 or a filesystem, and a thin
:func:`unpack_to_dir` / :func:`pack_from_dir` pair handles on-disk hosts.

Requirements: 12.1, 12.2, 12.3, 12.4, 13.1.
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path
from typing import Mapping


class BundleLayoutError(Exception):
    """A bundle is missing the expected internal layout (manifest.json)."""


def pack_objects(objects: Mapping[str, bytes]) -> bytes:
    """Pack ``{relative_key: bytes}`` into a deterministic gzipped tarball.

    The relative keys become the tar member names. ``manifest.json`` MUST be
    present (it anchors the restore).
    """
    if not any(k == "manifest.json" or k.endswith("/manifest.json") for k in objects):
        raise BundleLayoutError("bundle must contain manifest.json")
    raw = io.BytesIO()
    # mtime=0 + sorted names -> deterministic, byte-stable tarball.
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for name in sorted(objects):
            data = objects[name]
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mtime = 0
            tar.addfile(info, io.BytesIO(data))
    gz = io.BytesIO()
    import gzip
    with gzip.GzipFile(fileobj=gz, mode="wb", mtime=0) as g:
        g.write(raw.getvalue())
    return gz.getvalue()


def unpack_objects(bundle: bytes) -> dict[str, bytes]:
    """Unpack a gzipped tarball back to ``{relative_key: bytes}``.

    Raises :class:`BundleLayoutError` when ``manifest.json`` is absent (R12.4
    guard ``Bundle_Layout_Invalid``).
    """
    import gzip
    raw = gzip.decompress(bundle)
    objects: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            f = tar.extractfile(member)
            if f is not None:
                objects[member.name] = f.read()
    if not any(k == "manifest.json" or k.endswith("/manifest.json") for k in objects):
        raise BundleLayoutError("bundle missing manifest.json")
    return objects


def pack_from_dir(directory: str | Path) -> bytes:
    """Pack every file under ``directory`` into a bundle (keys are relative)."""
    root = Path(directory)
    objects: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            objects[str(path.relative_to(root))] = path.read_bytes()
    return pack_objects(objects)


def unpack_to_dir(bundle: bytes, directory: str | Path) -> list[str]:
    """Unpack a bundle to ``directory``; return the list of written keys."""
    root = Path(directory)
    objects = unpack_objects(bundle)
    for key, data in objects.items():
        dest = root / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    return sorted(objects)


__all__ = [
    "pack_objects",
    "unpack_objects",
    "pack_from_dir",
    "unpack_to_dir",
    "BundleLayoutError",
]
