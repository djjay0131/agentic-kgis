"""`RowProvider` reference-implementation tests + the reusable contract suite."""

from __future__ import annotations

import sqlite3

from fixtures import make_players_db  # type: ignore[import-not-found]

from kgis.structured import DbapiRowProvider, RowProviderContract, SqliteRowProvider


def _canonical_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE people (id TEXT PRIMARY KEY, name TEXT)")
    conn.executemany(
        "INSERT INTO people (id, name) VALUES (?, ?)",
        [("1", "Ada"), ("2", "Grace"), ("3", "Alan")],
    )
    conn.commit()
    return conn


class TestSqliteRowProviderContract(RowProviderContract):
    def make_provider(self) -> SqliteRowProvider:
        return SqliteRowProvider(_canonical_db(), table="people", key_fields=("id",))


class TestDbapiRowProviderContract(RowProviderContract):
    """The generic PEP-249 provider must satisfy the same port contract —
    proof the port is not SQLite-specific (no driver imported by kgis)."""

    def make_provider(self) -> DbapiRowProvider:
        return DbapiRowProvider(_canonical_db(), table="people", key_fields=("id",))


def test_snapshot_version_changes_when_data_changes() -> None:
    conn = make_players_db()
    provider = SqliteRowProvider(conn, table="players", key_fields=("id",))
    before = provider.open_snapshot().version

    conn.execute("UPDATE players SET height_cm = 999 WHERE id = '1'")
    conn.commit()
    after = provider.open_snapshot().version

    assert before != after  # honest: a changed read gets a new version token


def test_pinned_snapshot_version_is_used_verbatim() -> None:
    conn = make_players_db()
    provider = SqliteRowProvider(
        conn, table="players", key_fields=("id",), snapshot_version="pinned-42"
    )
    assert provider.open_snapshot().version == "pinned-42"


def test_columns_projection_limits_selected_fields() -> None:
    conn = make_players_db()
    provider = SqliteRowProvider(
        conn, table="players", key_fields=("id",), columns=("id", "name")
    )
    rows = list(provider.open_snapshot().rows(batch_size=500))
    assert set(rows[0].keys()) == {"id", "name"}


def test_where_clause_filters_rows() -> None:
    conn = make_players_db()
    provider = SqliteRowProvider(
        conn, table="players", key_fields=("id",), where="team = ?", params=("10",)
    )
    rows = list(provider.open_snapshot().rows(batch_size=500))
    assert [row["id"] for row in rows] == ["1", "2"]


def test_locator_defaults_to_source_scheme_and_table() -> None:
    conn = make_players_db()
    assert SqliteRowProvider(conn, table="players", key_fields=("id",)).locator == (
        "sqlite://players"
    )


def test_empty_key_fields_is_rejected() -> None:
    conn = make_players_db()
    try:
        SqliteRowProvider(conn, table="players", key_fields=())
    except ValueError:
        return
    raise AssertionError("empty key_fields must raise ValueError")
