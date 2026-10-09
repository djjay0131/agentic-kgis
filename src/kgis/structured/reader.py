"""`StructuredRecordReader`: a `RowProvider` seen as a `RecordReader`.

This is the whole point of structured sync being "one more source, not one
more pipeline". A `RowProvider` pins a snapshot; this reader wraps it so the
existing `IngestPipeline` cannot tell a database snapshot from a CSV file —
normalize, validate, build, and `CandidateSink` run exactly as they do for
every other source.

Three properties are deliberate:

- **The snapshot is opened once and cached.** `read()` must be repeatable
  (`kgis.sources.base`): a dry run pages the snapshot, then an execution pages
  it again, and both must see identical rows. Caching the `Snapshot` on first
  use guarantees that even against a source mutating underneath — the reader
  reads *its* pinned snapshot, not the live table.

- **Coordinates are stable per row.** The fragment is built from the
  provider's `key_fields`, so the same source row maps to the same
  `SourceCoordinates` across runs regardless of query order (spec §5.8). This
  is the anchor idempotency rides on; it is not the row's stream position,
  which a re-query could reshuffle.

- **The snapshot version is first-class on the coordinates.** Every candidate's
  `source_coordinates.source_version` carries the pinned snapshot's version
  (ADR-0022), the dedicated home for *which* read of the source produced the
  fact. The locator is still stamped `@snapshot=<version>` by default so
  existing consumers and locator-based idempotency are unchanged; set
  `include_snapshot_in_locator=False` to keep the locator snapshot-independent
  while `source_version` still records the read. Either way two runs over a
  stable snapshot agree; a re-sync that read changed data gets a new version,
  honestly.
"""

from __future__ import annotations

from collections.abc import Iterator

from kg_contracts.candidates import SourceCoordinates
from kgis.records import SourceRecord
from kgis.structured.port import RowProvider, Snapshot

DEFAULT_BATCH_SIZE = 500


class StructuredRecordReader:
    """Adapts a `RowProvider` to the pipeline's `RecordReader` port."""

    def __init__(
        self,
        provider: RowProvider,
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
        include_snapshot_in_locator: bool = True,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        self._provider = provider
        self._batch_size = batch_size
        self._include_snapshot = include_snapshot_in_locator
        self._snapshot: Snapshot | None = None

    def _snap(self) -> Snapshot:
        """Open the snapshot once, then reuse it — this is what makes `read()`
        repeatable against a source that could otherwise change between a
        dry run and its execution."""
        if self._snapshot is None:
            self._snapshot = self._provider.open_snapshot()
        return self._snapshot

    @property
    def source_type(self) -> str:
        return self._provider.source_type

    @property
    def snapshot_version(self) -> str:
        """The pinned snapshot's deterministic version token."""
        return self._snap().version

    @property
    def locator(self) -> str:
        base = self._provider.locator
        if self._include_snapshot:
            return f"{base}@snapshot={self._snap().version}"
        return base

    def read(self) -> Iterator[SourceRecord]:
        snapshot = self._snap()
        locator = self.locator
        source_type = self._provider.source_type
        key_fields = self._provider.key_fields
        for index, row in enumerate(snapshot.rows(batch_size=self._batch_size)):
            data = dict(row)
            yield SourceRecord(
                index=index,
                coordinates=SourceCoordinates(
                    source_type=source_type,
                    locator=locator,
                    fragment=_fragment(data, key_fields, index),
                    source_version=snapshot.version,
                ),
                data=data,
            )


def _fragment(data: dict[str, object], key_fields: tuple[str, ...], index: int) -> str:
    """The stable per-row coordinate: the key columns' values.

    Falls back to the stream index only when the provider declares no key
    fields — a source without a stable key cannot promise stable coordinates,
    and saying so with `row=<n>` beats a fragment that looks stable but is not.
    """
    if not key_fields:
        return f"row={index}"
    return "&".join(f"{field}={data.get(field)}" for field in key_fields)
