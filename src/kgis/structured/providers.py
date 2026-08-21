"""Concrete `RowProvider`s: the reference SQLite one and a generic DB-API one.

`SqliteRowProvider` is the reference implementation the tests exercise — a
real, injected `sqlite3.Connection`, no network, stdlib only. `DbapiRowProvider`
proves the port is not SQLite-specific: it reads from any PEP-249 connection
through a minimal structural `Protocol`, so a Postgres/Spanner connection works
without `kgis` ever importing its driver.

Both share `_MaterializedSnapshot`: `open_snapshot()` runs the ordered query
once, pages the cursor with `fetchmany`, and holds the rows. Materializing is
the honest repeatable-read for a reference provider — the in-memory copy cannot
change under a concurrent writer, so paging it twice is byte-identical. A
production provider backed by a true MVCC transaction would stream instead and
take its `version` from the database's snapshot id; the `Snapshot` port permits
both (`rows()` is an iterator, `version` is just a token).

The snapshot `version` defaults to a deterministic digest of the ordered rows:
unchanged data → same version → `plan()` and `run()` agree; changed data → a
new version, which is the honest signal that a re-sync read something different.
Pass an explicit `snapshot_version` (e.g. a DB transaction id or a watermark)
to pin it instead of deriving it.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from typing import Protocol


def _digest_version(rows: Sequence[Mapping[str, object]]) -> str:
    """A deterministic snapshot token: same ordered rows → same version.

    blake2b (not a hash-randomized `hash()`) so the token is stable across
    processes — a dry run in one process and an execution in another must
    derive the same version for the same data.
    """
    encoded = json.dumps(
        [dict(sorted(row.items())) for row in rows], sort_keys=True, default=str
    ).encode("utf-8")
    return "snap_" + hashlib.blake2b(encoded, digest_size=12).hexdigest()


class _MaterializedSnapshot:
    """A `Snapshot` over rows already read into memory (reference semantics)."""

    def __init__(self, rows: Sequence[Mapping[str, object]], version: str) -> None:
        self._rows: tuple[dict[str, object], ...] = tuple(dict(row) for row in rows)
        self._version = version

    @property
    def version(self) -> str:
        return self._version

    def rows(self, *, batch_size: int) -> Iterator[Mapping[str, object]]:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        # Chunk the materialized rows in `batch_size` pages so the iterator
        # behaves like a real paged cursor; the row *sequence* is identical
        # for any batch size (batch-of-one constraint).
        for start in range(0, len(self._rows), batch_size):
            for row in self._rows[start : start + batch_size]:
                yield dict(row)


def _quote_ident(name: str) -> str:
    """Quote a SQL identifier, doubling embedded quotes. Standard SQL; works
    across SQLite and Postgres. Guards against a stray column name breaking
    (or injecting into) the generated SELECT."""
    return '"' + name.replace('"', '""') + '"'


class DbapiRowProvider:
    """A `RowProvider` over any injected PEP-249 (DB-API 2.0) connection.

    The connection is *injected*, never opened here — `kgis` adds no database
    driver to its dependencies. The provider builds a deterministic
    `SELECT ... ORDER BY <key_fields>` so rows arrive in a stable order, then
    materializes one snapshot per `open_snapshot()`.
    """

    def __init__(
        self,
        connection: _DbapiConnection,
        *,
        table: str,
        key_fields: Sequence[str],
        columns: Sequence[str] | None = None,
        where: str | None = None,
        params: Sequence[object] = (),
        source_type: str = "dbapi",
        locator: str | None = None,
        snapshot_version: str | None = None,
        fetch_size: int = 500,
    ) -> None:
        if not key_fields:
            raise ValueError("DbapiRowProvider requires key_fields for stable coordinates")
        if fetch_size < 1:
            raise ValueError("fetch_size must be >= 1")
        self._conn = connection
        self._table = table
        self._key_fields = tuple(key_fields)
        self._columns = tuple(columns) if columns is not None else None
        self._where = where
        self._params = tuple(params)
        self._source_type = source_type
        self._locator = locator if locator is not None else f"{source_type}://{table}"
        self._pinned_version = snapshot_version
        self._fetch_size = fetch_size

    @property
    def source_type(self) -> str:
        return self._source_type

    @property
    def locator(self) -> str:
        return self._locator

    @property
    def key_fields(self) -> tuple[str, ...]:
        return self._key_fields

    def _select_sql(self) -> str:
        cols = (
            ", ".join(_quote_ident(c) for c in self._columns)
            if self._columns is not None
            else "*"
        )
        order = ", ".join(_quote_ident(k) for k in self._key_fields)
        where = f" WHERE {self._where}" if self._where else ""
        return f"SELECT {cols} FROM {_quote_ident(self._table)}{where} ORDER BY {order}"

    def open_snapshot(self) -> _MaterializedSnapshot:
        cursor = self._conn.cursor()
        try:
            cursor.execute(self._select_sql(), self._params)
            description = cursor.description
            if description is None:
                columns: tuple[str, ...] = ()
            else:
                columns = tuple(str(col[0]) for col in description)
            rows: list[dict[str, object]] = []
            while True:
                page = cursor.fetchmany(self._fetch_size)
                if not page:
                    break
                for raw in page:
                    rows.append({col: raw[i] for i, col in enumerate(columns)})
        finally:
            cursor.close()
        version = self._pinned_version if self._pinned_version is not None else _digest_version(rows)
        return _MaterializedSnapshot(rows, version)


class SqliteRowProvider(DbapiRowProvider):
    """The reference `RowProvider`: an injected stdlib `sqlite3.Connection`.

    A thin `DbapiRowProvider` specialization fixing `source_type="sqlite"`.
    Exists so the tests (and any downstream) get a real, dependency-free
    structured source — an in-memory or temp-file SQLite database is a genuine
    DB-API source, not a mock.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        table: str,
        key_fields: Sequence[str],
        columns: Sequence[str] | None = None,
        where: str | None = None,
        params: Sequence[object] = (),
        locator: str | None = None,
        snapshot_version: str | None = None,
        fetch_size: int = 500,
    ) -> None:
        super().__init__(
            connection,
            table=table,
            key_fields=key_fields,
            columns=columns,
            where=where,
            params=params,
            source_type="sqlite",
            locator=locator,
            snapshot_version=snapshot_version,
            fetch_size=fetch_size,
        )


class _DbapiCursor(Protocol):
    """The slice of a PEP-249 cursor the provider uses (positional-only so any
    driver's parameter names match structurally)."""

    @property
    def description(self) -> Sequence[Sequence[object]] | None: ...

    def execute(self, sql: str, parameters: Sequence[object], /) -> object: ...

    def fetchmany(self, size: int, /) -> Sequence[Sequence[object]]: ...

    def close(self) -> None: ...


class _DbapiConnection(Protocol):
    """The slice of a PEP-249 connection the provider uses."""

    def cursor(self) -> _DbapiCursor: ...
