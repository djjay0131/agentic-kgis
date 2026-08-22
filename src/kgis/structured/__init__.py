"""Deterministic structured synchronization (Plan 4, Wave 2 Stream B1).

A database-shaped source, fed through the *existing* Sprint 1 pipeline — not a
second ingestion architecture. A `RowProvider` (the injected DB-API/row-provider
port) is pinned to a repeatable-read `Snapshot`, adapted to a `RecordReader` by
`StructuredRecordReader`, and from there normalize → validate → build →
`CandidateSink` is unchanged. No graph-write surface exists here, as everywhere
in `kgis`.

Public surface:

- `RowProvider`, `Snapshot` — the source port (Protocols).
- `SqliteRowProvider` — the reference provider over an injected
  `sqlite3.Connection`; `DbapiRowProvider` — the same over any PEP-249 connection.
- `StructuredRecordReader` — the `RowProvider` → `RecordReader` adapter.
- `StructuredSyncConfig` — source + mapping (`Normalizer` + `CandidateBuilder`)
  → a wired `IngestPipeline`.
- `StructuredEvidenceRecorder` / `source_evidence_id` — per-row Evidence,
  produced and linked idempotently through the evidence registry.
- `RowProviderContract` — the reusable §10.2 contract suite for providers.

This subpackage owns its own exports; it does not edit `kgis.__init__`.
"""

from kgis.structured.config import StructuredSyncConfig
from kgis.structured.evidence import StructuredEvidenceRecorder, source_evidence_id
from kgis.structured.port import RowProvider, Snapshot
from kgis.structured.providers import DbapiRowProvider, SqliteRowProvider
from kgis.structured.reader import DEFAULT_BATCH_SIZE, StructuredRecordReader
from kgis.structured.testing import CANONICAL_ROWS, RowProviderContract

__all__ = [
    "CANONICAL_ROWS",
    "DEFAULT_BATCH_SIZE",
    "DbapiRowProvider",
    "RowProvider",
    "RowProviderContract",
    "Snapshot",
    "SqliteRowProvider",
    "StructuredEvidenceRecorder",
    "StructuredRecordReader",
    "StructuredSyncConfig",
    "source_evidence_id",
]
