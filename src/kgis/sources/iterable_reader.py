"""`IterableRecordReader`: records from any Python iterable of mappings.

The simplest source, and the one every test uses. It exists so that "a list
of dicts" is a first-class source rather than a test-only shortcut — the
pipeline must not be able to tell it apart from a CSV file.

The input is **materialized at construction**. `read()` has to be
repeatable (see `sources/base.py`), and a generator handed to the
constructor would be exhausted after the first pass — a dry run would plan
N candidates and the following execution would submit zero. Copying costs
memory proportional to the input, which is the right trade for an in-memory
source; a genuinely large stream belongs in a file-backed reader that can
re-open its handle.
"""

from typing import Iterable, Iterator, Mapping

from kg_contracts.candidates import SourceCoordinates
from kgis.records import SourceRecord


class IterableRecordReader:
    """A `RecordReader` over an in-memory iterable of mappings."""

    def __init__(
        self,
        records: Iterable[Mapping[str, object]],
        *,
        source_type: str = "iterable",
        locator: str = "memory",
    ) -> None:
        # Copy each mapping too, not just the outer iterable: the caller's
        # dicts stay mutable, and a source that changes under the pipeline
        # would break replay determinism in a way that is very hard to see.
        self._records: tuple[dict[str, object], ...] = tuple(dict(record) for record in records)
        self._source_type = source_type
        self._locator = locator

    @property
    def source_type(self) -> str:
        return self._source_type

    @property
    def locator(self) -> str:
        return self._locator

    def read(self) -> Iterator[SourceRecord]:
        for index, data in enumerate(self._records):
            yield SourceRecord(
                index=index,
                coordinates=SourceCoordinates(
                    source_type=self._source_type,
                    locator=self._locator,
                    fragment=f"index={index}",
                ),
                data=dict(data),
            )
