"""The structured-sync source port: `RowProvider` + `Snapshot` (Plan 4, Wave 2).

Structured sync is **not** a second ingestion architecture. It is one more
way to feed the *existing* pipeline: a `RowProvider` is turned into a
`RecordReader` (`kgis.structured.reader`) and everything downstream —
normalize, validate, build, `CandidateSink` — is the Sprint 1 spine
unchanged. This module defines only the read edge.

Two ideas carry the whole design:

- **A snapshot, not a live cursor.** `RowProvider.open_snapshot()` pins a
  *repeatable read*: a `Snapshot` that yields the same rows every time it is
  paged, and a `version` token that is stable while the underlying data is
  stable. That is what makes `plan()` and `run()` honest — a dry run over a
  snapshot and an execution over the *same* snapshot see byte-identical rows,
  so the plan an operator approves is the plan that runs (spec §5.8, ADR-0009).
  A production provider backs this with a database's own MVCC/REPEATABLE-READ
  transaction or a watermark column; the reference SQLite provider
  materializes the ordered rows once (see `providers.py`).

- **Stable source coordinates come from the row's own key.** The provider
  declares `key_fields`; the reader builds each record's coordinate fragment
  from those fields' values, not from the row's position in the stream. The
  same source row therefore maps to the same `SourceCoordinates` across runs
  even if the query's row order changes — the property idempotency rides on
  (spec §5.8).

No driver dependency lives here. `RowProvider` is a `Protocol`; a caller
injects a connection into a concrete provider (the reference one wraps an
injected `sqlite3.Connection`). `kgis` never imports Postgres/Spanner/Neo4j.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Protocol, runtime_checkable


@runtime_checkable
class Snapshot(Protocol):
    """A pinned, repeatable-read view of a source's rows.

    `version` is a deterministic token for the data this snapshot exposes:
    equal versions promise equal row sets, so two pipelines that open a
    snapshot over unchanged data agree. `rows()` may be paged in batches, but
    batching is transport only — a batch of one and a batch of 500 yield the
    same rows in the same order (the pipeline's batch-of-one constraint).
    """

    @property
    def version(self) -> str: ...

    def rows(self, *, batch_size: int) -> Iterator[Mapping[str, object]]:
        """Yield every row in the snapshot, in a stable order, repeatably."""
        ...


@runtime_checkable
class RowProvider(Protocol):
    """Reads rows from an injected connection/provider (the structured port).

    A `RowProvider` is the structured analogue of a file handle: it knows how
    to open a `Snapshot` over some tabular source it was handed, and it names
    the source (`source_type`, `locator`) and the columns that identify a row
    (`key_fields`). It builds no candidates and knows nothing about the graph
    — that keeps it reusable across every mapping layered on top of it.
    """

    @property
    def source_type(self) -> str:
        """Short slug for the physical source — `"sqlite"`, `"dbapi"`, ... ."""
        ...

    @property
    def locator(self) -> str:
        """Stable logical address of the source as a whole (a table/query name)."""
        ...

    @property
    def key_fields(self) -> tuple[str, ...]:
        """Columns whose values identify a row — the stable-coordinate anchor.

        Non-empty for a source that wants stable per-row coordinates across
        runs (the point of structured sync). The reader composes the coordinate
        fragment from these fields' values (spec §5.8).
        """
        ...

    def open_snapshot(self) -> Snapshot:
        """Pin a repeatable-read snapshot. Paging it twice yields equal rows."""
        ...
