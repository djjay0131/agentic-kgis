"""SQLite-backed `RegistryStore` + human-gated decision corpus (spec §8).

A deliberately boring store (spec §8): stdlib `sqlite3`, parameterized SQL,
explicit transactions with commit/rollback, and schema versioning via
``PRAGMA user_version``. It implements the frozen
`kg_contracts.registry.RegistryStore` protocol (`register` / `get` / `all`)
and extends it — behind that protocol — with the three things Plan 7 needs
that the I/O-free contract cannot carry itself:

- **Descriptor versioning.** Each `register` of an existing name writes a new
  version row; `get` / `all` return the latest. The frozen `GraphDescriptor`
  has no version field, so version is registry-managed metadata.
- **Extension attributes.** A per-version key/value sidecar carrying the
  attribute vocabulary (candidate 0004) and the open backend identifier
  (candidate 0005) that the frozen contract cannot yet declare. This is the
  least-invasive resolution of both gaps: no contract edit, and a clean
  promotion path if the owner accepts either candidate.
- **A decision + outcome corpus.** Every human adjudication of a
  `Recommendation` is recorded with its later real-world outcome, so the
  thresholds in `AdvisorConfig` can be recalibrated on real data (ADR-0005).

Nothing here auto-creates or auto-extends a graph. `record_decision` persists
a human's choice; `register` provisions a graph. They are separate calls on
purpose — the advisor advises, a human decides, and only then does anyone
register. There is no method that takes a `Recommendation` and mutates the
registry.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from kg_contracts.registry import GraphDescriptor, RegistryStore
from kgis.clock import Clock, SystemClock
from kgis.errors import KgisError
from kgis.ids import stable_suffix
from kgis.registry.models import (
    ATTR_BACKEND_OPEN_ID,
    AdvisorRecommendation,
    Outcome,
    RegisteredGraph,
)

_SCHEMA_VERSION = 1


class DecisionConflictError(KgisError):
    """A different decision is already recorded under the same `decision_id`.

    `record_decision` is idempotent for an *identical* re-submission (a
    double-submit, or any caller on a `FixedClock` deriving the same
    deterministic id), but a same-id/different-content collision is a real
    ambiguity — surfaced as this domain error rather than a bare
    `sqlite3.IntegrityError`.
    """


class DecisionRecord(BaseModel):
    """A human's adjudication of a `Recommendation`, plus its later outcome.

    `decided_*` is filled when the human decides; `outcome_*` is filled later
    when the real-world consequence is known. Together they are the corpus
    that calibrates the advisor's thresholds (spec §8, ADR-0005).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: str
    graph_name: str | None
    recommendation: AdvisorRecommendation
    chosen_outcome: Outcome
    decided_by: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    decided_at: datetime
    outcome_label: str | None = None
    outcome_note: str | None = None
    outcome_recorded_at: datetime | None = None


class SqliteRegistryStore:
    """A persistent `RegistryStore` (spec §8). Conforms to the contract
    protocol; the extra methods are additive and keyword-defaulted so the
    conformant `register(descriptor)` call still type-checks."""

    def __init__(self, connection: sqlite3.Connection, *, clock: Clock | None = None) -> None:
        self._conn = connection
        self._conn.row_factory = sqlite3.Row
        self._clock = clock or SystemClock()
        self._init_schema()

    # --- lifecycle -----------------------------------------------------------

    def _init_schema(self) -> None:
        version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        if version == _SCHEMA_VERSION:
            return
        if version not in (0, _SCHEMA_VERSION):
            raise RuntimeError(
                f"registry db schema version {version} is not understood by this build "
                f"(expected {_SCHEMA_VERSION})"
            )
        with self._transaction() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS graph_versions (
                    name TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    descriptor_json TEXT NOT NULL,
                    attributes_json TEXT NOT NULL,
                    registered_at TEXT NOT NULL,
                    PRIMARY KEY (name, version)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS decisions (
                    decision_id TEXT PRIMARY KEY,
                    graph_name TEXT,
                    recommendation_json TEXT NOT NULL,
                    chosen_outcome TEXT NOT NULL,
                    decided_by TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    decided_at TEXT NOT NULL,
                    outcome_label TEXT,
                    outcome_note TEXT,
                    outcome_recorded_at TEXT
                )
                """
            )
            cursor.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Cursor]:
        """One unit of work: explicit BEGIN, COMMIT on success, ROLLBACK on
        any exception. Mirrors the ledger's transaction discipline."""
        cursor = self._conn.cursor()
        cursor.execute("BEGIN")
        try:
            yield cursor
        except BaseException:
            self._conn.rollback()
            raise
        else:
            self._conn.commit()
        finally:
            cursor.close()

    def close(self) -> None:
        self._conn.close()

    # --- RegistryStore protocol ----------------------------------------------

    def register(
        self,
        descriptor: GraphDescriptor,
        *,
        attributes: Mapping[str, str] | None = None,
        backend_ref: str | None = None,
    ) -> None:
        """Register (or version-bump) a graph.

        `attributes` and `backend_ref` are the registry extension surface:
        `backend_ref` is the open backend identifier (candidate 0005), stored
        as the `backend.open_id` attribute so a Postgres/AGE-class backend the
        frozen `Backend` enum cannot name is still recorded losslessly.
        """
        merged: dict[str, str] = dict(attributes or {})
        if backend_ref is not None:
            merged[ATTR_BACKEND_OPEN_ID] = backend_ref
        registered_at = self._clock.now().isoformat()
        with self._transaction() as cursor:
            row = cursor.execute(
                "SELECT MAX(version) FROM graph_versions WHERE name = ?", (descriptor.name,)
            ).fetchone()
            next_version = (row[0] or 0) + 1
            cursor.execute(
                "INSERT INTO graph_versions "
                "(name, version, descriptor_json, attributes_json, registered_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    descriptor.name,
                    next_version,
                    descriptor.model_dump_json(),
                    _dump_attributes(merged),
                    registered_at,
                ),
            )

    def get(self, name: str) -> GraphDescriptor | None:
        row = self._conn.execute(
            "SELECT descriptor_json FROM graph_versions WHERE name = ? "
            "ORDER BY version DESC LIMIT 1",
            (name,),
        ).fetchone()
        if row is None:
            return None
        return GraphDescriptor.model_validate_json(row["descriptor_json"])

    def all(self) -> list[GraphDescriptor]:
        return [g.descriptor for g in self.snapshot()]

    # --- versioning + extension attributes -----------------------------------

    def latest_version(self, name: str) -> int | None:
        row = self._conn.execute(
            "SELECT MAX(version) AS v FROM graph_versions WHERE name = ?", (name,)
        ).fetchone()
        return None if row["v"] is None else int(row["v"])

    def versions(self, name: str) -> list[int]:
        rows = self._conn.execute(
            "SELECT version FROM graph_versions WHERE name = ? ORDER BY version",
            (name,),
        ).fetchall()
        return [int(r["version"]) for r in rows]

    def get_version(self, name: str, version: int) -> GraphDescriptor | None:
        row = self._conn.execute(
            "SELECT descriptor_json FROM graph_versions WHERE name = ? AND version = ?",
            (name, version),
        ).fetchone()
        if row is None:
            return None
        return GraphDescriptor.model_validate_json(row["descriptor_json"])

    def attributes_for(self, name: str, version: int | None = None) -> dict[str, str]:
        if version is None:
            row = self._conn.execute(
                "SELECT attributes_json FROM graph_versions WHERE name = ? "
                "ORDER BY version DESC LIMIT 1",
                (name,),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT attributes_json FROM graph_versions WHERE name = ? AND version = ?",
                (name, version),
            ).fetchone()
        if row is None:
            return {}
        return _load_attributes(row["attributes_json"])

    def snapshot(self) -> list[RegisteredGraph]:
        """The latest version of every registered graph, with attributes.

        This is the deterministic input the advisor scores against — sorted by
        name so a fixed registry state always produces a fixed snapshot order.
        """
        rows = self._conn.execute(
            """
            SELECT gv.name, gv.version, gv.descriptor_json, gv.attributes_json
            FROM graph_versions gv
            JOIN (
                SELECT name, MAX(version) AS mv FROM graph_versions GROUP BY name
            ) latest ON gv.name = latest.name AND gv.version = latest.mv
            ORDER BY gv.name
            """
        ).fetchall()
        return [
            RegisteredGraph(
                descriptor=GraphDescriptor.model_validate_json(r["descriptor_json"]),
                version=int(r["version"]),
                attributes=_load_attributes(r["attributes_json"]),
            )
            for r in rows
        ]

    # --- decision + outcome corpus (human-gated) -----------------------------

    def record_decision(
        self,
        recommendation: AdvisorRecommendation,
        *,
        chosen_outcome: Outcome,
        decided_by: str,
        rationale: str,
        graph_name: str | None = None,
        decision_id: str | None = None,
    ) -> DecisionRecord:
        """Record a human's adjudication of `recommendation`.

        This does not act on the decision — it only records that a human made
        it. Provisioning (a `register` call) is a separate, explicit step.
        """
        decided_at = self._clock.now()
        target = graph_name if graph_name is not None else recommendation.target_graph
        did = decision_id or "dec_" + stable_suffix(
            decided_by, str(chosen_outcome), target or "", decided_at.isoformat()
        )
        record = DecisionRecord(
            decision_id=did,
            graph_name=target,
            recommendation=recommendation,
            chosen_outcome=chosen_outcome,
            decided_by=decided_by,
            rationale=rationale,
            decided_at=decided_at,
        )
        new_row = (
            record.decision_id,
            record.graph_name,
            recommendation.model_dump_json(),
            str(chosen_outcome),
            decided_by,
            rationale,
            decided_at.isoformat(),
        )
        with self._transaction() as cursor:
            # Idempotent by decision_id: a re-submit of the *same* row is a
            # no-op; the read-back below then decides no-op vs. conflict.
            cursor.execute(
                "INSERT INTO decisions "
                "(decision_id, graph_name, recommendation_json, chosen_outcome, "
                " decided_by, rationale, decided_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(decision_id) DO NOTHING",
                new_row,
            )
            stored = cursor.execute(
                "SELECT decision_id, graph_name, recommendation_json, chosen_outcome, "
                "decided_by, rationale, decided_at FROM decisions WHERE decision_id = ?",
                (record.decision_id,),
            ).fetchone()
        if tuple(stored) != new_row:
            raise DecisionConflictError(
                f"a different decision is already recorded under decision_id "
                f"{record.decision_id!r}"
            )
        return record

    def record_outcome(self, decision_id: str, *, label: str, note: str | None = None) -> None:
        """Attach the real-world outcome of an earlier decision to the corpus."""
        recorded_at = self._clock.now().isoformat()
        with self._transaction() as cursor:
            updated = cursor.execute(
                "UPDATE decisions SET outcome_label = ?, outcome_note = ?, "
                "outcome_recorded_at = ? WHERE decision_id = ?",
                (label, note, recorded_at, decision_id),
            )
            if updated.rowcount == 0:
                raise KeyError(f"no decision with decision_id {decision_id!r}")

    def decision(self, decision_id: str) -> DecisionRecord | None:
        row = self._conn.execute(
            "SELECT * FROM decisions WHERE decision_id = ?", (decision_id,)
        ).fetchone()
        return None if row is None else _row_to_decision(row)

    def decisions(self, graph_name: str | None = None) -> list[DecisionRecord]:
        if graph_name is None:
            rows = self._conn.execute(
                "SELECT * FROM decisions ORDER BY decided_at, decision_id"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM decisions WHERE graph_name = ? ORDER BY decided_at, decision_id",
                (graph_name,),
            ).fetchall()
        return [_row_to_decision(r) for r in rows]


def open_registry_db(path: str | Path, *, clock: Clock | None = None) -> SqliteRegistryStore:
    """Open (creating if needed) a persistent registry at `path`.

    Pass ``":memory:"`` for an ephemeral store. A real path persists across
    process restarts — reopen it and every registered graph and decision is
    still there.
    """
    connection = sqlite3.connect(str(path))
    return SqliteRegistryStore(connection, clock=clock)


def _assert_registry_store_conformance(store: SqliteRegistryStore) -> RegistryStore:
    """Static-only guard: `mypy --strict` fails here if `SqliteRegistryStore`
    ever drifts out of structural conformance with the frozen `RegistryStore`
    protocol (a changed `register`/`get`/`all` signature or return type). The
    runtime `isinstance` check only inspects method *names*; this checks types.
    Never called."""
    return store


# --- serialization helpers ---------------------------------------------------


def _dump_attributes(attributes: Mapping[str, str]) -> str:
    return json.dumps(dict(attributes), sort_keys=True)


def _load_attributes(raw: str) -> dict[str, str]:
    data = json.loads(raw)
    return {str(k): str(v) for k, v in data.items()}


def _row_to_decision(row: sqlite3.Row) -> DecisionRecord:
    return DecisionRecord(
        decision_id=row["decision_id"],
        graph_name=row["graph_name"],
        recommendation=AdvisorRecommendation.model_validate_json(row["recommendation_json"]),
        chosen_outcome=Outcome(row["chosen_outcome"]),
        decided_by=row["decided_by"],
        rationale=row["rationale"],
        decided_at=datetime.fromisoformat(row["decided_at"]),
        outcome_label=row["outcome_label"],
        outcome_note=row["outcome_note"],
        outcome_recorded_at=(
            datetime.fromisoformat(row["outcome_recorded_at"])
            if row["outcome_recorded_at"]
            else None
        ),
    )


__all__ = [
    "DecisionConflictError",
    "DecisionRecord",
    "SqliteRegistryStore",
    "open_registry_db",
]
