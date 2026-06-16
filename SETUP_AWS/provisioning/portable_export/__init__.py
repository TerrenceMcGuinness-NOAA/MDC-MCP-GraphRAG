"""Cross_Platform_Data_Persistence_System (``portable_export``) package.

The outbound mirror of the inbound ``migrate-to-aws.js`` pipeline. Produces
an engine-neutral ``Portable_Export`` of the entire Knowledge_Base in S3,
which can be restored into the COTS stack (ChromaDB + Neo4j) or re-imported
back into AWS (OpenSearch + Neptune) -- the round trip the funding-resilience
case rests on.

Three transfer directions are supported, each operator-invokable:

* ``AWS_Export``  -- read OpenSearch + Neptune, write Vector_Export +
  Graph_Export to S3.
* ``COTS_Restore`` -- read Portable_Export from S3, load into ChromaDB +
  Neo4j.
* ``AWS_Reimport`` -- read Portable_Export from S3, load into OpenSearch +
  Neptune.

The S3 Portable_Export is the contract: every direction writes or reads the
same artifacts under the same layout, validated against the same schema,
verified by the same Count_Parity_Check. The pipeline is read-only on every
source and applies operator gating before any destructive write.

ASCII-only console output (``[OK]`` / ``[ERROR]`` / ``[WARN]`` / ``[INFO]`` /
``[SKIP]``) per the repository convention; emoji break MCP stdio.

See ``.kiro/specs/cross-platform-data-persistence/`` for the spec.
"""

from __future__ import annotations

#: Tool version recorded in every Export_Manifest (R11.1).
__version__ = "1.0.0"

#: Export_Manifest / Portable_Export schema version (semantic). The restore
#: tools refuse a manifest whose MAJOR component exceeds this (R11.3).
SCHEMA_VERSION = "1.0.0"

__all__ = ["__version__", "SCHEMA_VERSION"]
