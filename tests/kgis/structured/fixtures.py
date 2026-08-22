"""SQLite fixtures for the structured-sync tests.

A real, in-memory `sqlite3` database — not a mock. `make_players_db` seeds a
`players` table so the reference `SqliteRowProvider` reads a genuine DB-API
source.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

PLAYER_ROWS: tuple[dict[str, object], ...] = (
    {"id": "1", "name": "Ada", "team": "10", "height_cm": 170},
    {"id": "2", "name": "Grace", "team": "10", "height_cm": 175},
    {"id": "3", "name": "Alan", "team": "20", "height_cm": 180},
)


def make_players_db(rows: Sequence[dict[str, object]] = PLAYER_ROWS) -> sqlite3.Connection:
    """An in-memory SQLite connection seeded with a `players` table."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE players (id TEXT PRIMARY KEY, name TEXT, team TEXT, height_cm INTEGER)"
    )
    conn.executemany(
        "INSERT INTO players (id, name, team, height_cm) VALUES (:id, :name, :team, :height_cm)",
        list(rows),
    )
    conn.commit()
    return conn
