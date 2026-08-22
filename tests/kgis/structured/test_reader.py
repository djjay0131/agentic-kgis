"""`StructuredRecordReader` tests + the reusable `RecordReader` contract suite."""

from __future__ import annotations

import sqlite3

from fixtures import make_players_db  # type: ignore[import-not-found]

from kgis.sources.base import RecordReader
from kgis.structured import SqliteRowProvider, StructuredRecordReader
from kgis.testing import RecordReaderContract


def _people_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE people (id TEXT PRIMARY KEY, name TEXT)")
    conn.executemany(
        "INSERT INTO people (id, name) VALUES (?, ?)",
        [("1", "Ada"), ("2", "Grace"), ("3", "Alan")],
    )
    conn.commit()
    return conn


class TestStructuredReaderContract(RecordReaderContract):
    def make_reader(self) -> RecordReader:
        provider = SqliteRowProvider(_people_db(), table="people", key_fields=("id",))
        return StructuredRecordReader(provider)


def _reader(conn: sqlite3.Connection, **kwargs: object) -> StructuredRecordReader:
    provider = SqliteRowProvider(conn, table="players", key_fields=("id",))
    return StructuredRecordReader(provider, **kwargs)  # type: ignore[arg-type]


def test_coordinates_are_keyed_on_the_row_key_not_the_stream_index() -> None:
    reader = _reader(make_players_db())
    fragments = [record.coordinates.fragment for record in reader.read()]
    assert fragments == ["id=1", "id=2", "id=3"]


def test_locator_carries_the_snapshot_version_by_default() -> None:
    reader = _reader(make_players_db())
    assert reader.locator == f"sqlite://players@snapshot={reader.snapshot_version}"
    for record in reader.read():
        assert record.coordinates.locator == reader.locator


def test_snapshot_can_be_excluded_from_the_locator() -> None:
    reader = _reader(make_players_db(), include_snapshot_in_locator=False)
    assert reader.locator == "sqlite://players"


def test_read_is_repeatable_against_a_mutating_source() -> None:
    """The snapshot is pinned on first read: a source mutated afterwards does
    not change what a second read() sees (dry-run then execute honesty)."""
    conn = make_players_db()
    reader = _reader(conn)
    first = list(reader.read())

    conn.execute("UPDATE players SET height_cm = 999 WHERE id = '1'")
    conn.commit()
    second = list(reader.read())

    assert first == second


def test_batch_size_does_not_change_records() -> None:
    small = list(_reader(make_players_db(), batch_size=1).read())
    large = list(_reader(make_players_db(), batch_size=500).read())
    assert [r.data for r in small] == [r.data for r in large]
    assert [r.coordinates for r in small] == [r.coordinates for r in large]


def test_integer_columns_arrive_as_real_ints() -> None:
    """SQLite carries types CSV cannot; the reader preserves them for the
    normalizer rather than stringifying."""
    reader = _reader(make_players_db())
    first = next(iter(reader.read()))
    assert first.data["height_cm"] == 170
    assert isinstance(first.data["height_cm"], int)
