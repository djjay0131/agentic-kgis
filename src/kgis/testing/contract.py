"""Reusable contract suite for `RecordReader` implementations (spec §10.2).

Subclass `RecordReaderContract`, implement `make_reader()` over the canonical
fixture below, and every reader — the three in this sprint, plus the SQL and
document readers that land later — is held to the same rules.

The rule worth the whole suite is `test_read_is_repeatable`. A reader built
around a generator passes every other test here and then quietly breaks the
pipeline: dry-run consumes the stream, execution re-reads an exhausted
iterator, and the operator sees a plan for 1,000 candidates followed by a
run that submits none. That bug is invisible in a single-pass test, so it
gets a test of its own.
"""

from kgis.records import SourceRecord
from kgis.sources.base import RecordReader

CANONICAL_RECORDS: tuple[dict[str, str], ...] = (
    {"id": "1", "name": "Ada"},
    {"id": "2", "name": "Grace"},
    {"id": "3", "name": "Alan"},
)
"""The dataset every `RecordReader` implementation is tested against.

All values are strings: CSV cannot express any other type, so a fixture with
real integers could not be represented identically across formats — and
cross-format equivalence is precisely what this suite exists to guarantee.
"""


class RecordReaderContract:
    """Subclass and implement `make_reader()` (spec §10.2)."""

    def make_reader(self) -> RecordReader:
        """Return a reader over exactly `CANONICAL_RECORDS`, in order."""
        raise NotImplementedError

    def test_reads_every_record_in_order(self) -> None:
        records = list(self.make_reader().read())
        assert [record.data["id"] for record in records] == ["1", "2", "3"]
        assert [record.data["name"] for record in records] == ["Ada", "Grace", "Alan"]

    def test_read_is_repeatable(self) -> None:
        """Dry-run then execute reads the same reader twice — it must not be one-shot."""
        reader = self.make_reader()
        first = list(reader.read())
        second = list(reader.read())
        assert first == second
        assert len(first) == len(CANONICAL_RECORDS)

    def test_indices_are_sequential_from_zero(self) -> None:
        records = list(self.make_reader().read())
        assert [record.index for record in records] == list(range(len(CANONICAL_RECORDS)))

    def test_coordinates_carry_the_readers_source_type_and_locator(self) -> None:
        reader = self.make_reader()
        for record in reader.read():
            assert record.coordinates.source_type == reader.source_type
            assert record.coordinates.locator == reader.locator

    def test_fragments_uniquely_locate_each_record(self) -> None:
        """`SourceCoordinates` is the idempotency anchor (spec §5.8) — it must
        actually distinguish one record from another."""
        records = list(self.make_reader().read())
        fragments = [record.coordinates.fragment for record in records]
        assert all(fragment is not None for fragment in fragments)
        assert len(set(fragments)) == len(records)

    def test_clean_records_carry_no_issues(self) -> None:
        for record in self.make_reader().read():
            assert record.issues == ()

    def test_records_are_source_records(self) -> None:
        for record in self.make_reader().read():
            assert isinstance(record, SourceRecord)
