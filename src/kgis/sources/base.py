"""`RecordReader`: the pipeline's only I/O stage.

A reader turns *some physical format* into `SourceRecord`s. That is all it
does. It does not interpret values, judge them, or know what a `Candidate`
is — a CSV reader that knows about entity types is a CSV reader you cannot
reuse. Every source in the sprint (in-memory iterable, CSV, JSON) is
uniform behind this one protocol, which is what lets the pipeline treat
"rows from a file" and "dicts from a test" as the same thing.

**`read()` must be repeatable.** Calling it twice must yield equal records
both times. This is not a stylistic preference: the pipeline may be dry-run
and then executed against the same reader, and a one-shot generator would
make the second pass silently see an empty source — a dry run that plans
1,000 candidates followed by an execution that submits 0. Readers therefore
hold a re-openable *handle* (a path, a string, a materialized tuple), never
a half-consumed iterator. `SourceContract` enforces this.
"""

from typing import Iterator, Protocol, runtime_checkable

from kgis.records import SourceRecord


@runtime_checkable
class RecordReader(Protocol):
    """Reads raw records from one source (spec §6, `sources/base.py`)."""

    @property
    def source_type(self) -> str:
        """Short slug naming the physical format — `"csv"`, `"json"`, ... .

        Stamped into `SourceCoordinates.source_type` on every record, and
        reported in the ingest report's source manifest.
        """
        ...

    @property
    def locator(self) -> str:
        """Stable locator for the source as a whole (spec §5.8).

        The file name, URI, or logical name of the stream — *not* the row.
        Per-record position goes in `SourceCoordinates.fragment`.
        """
        ...

    def read(self) -> Iterator[SourceRecord]:
        """Yield every record, in source order. Repeatable (see module docs).

        Raises `SourceReadError` for I/O and parse faults. Malformed
        *records* are not faults: those are emitted carrying a
        `RecordIssue` (see `SourceRecord.issues`).
        """
        ...
