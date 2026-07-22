import sqlite3
import threading
from typing import Any

import pytest

from kg_contracts.stores import CandidateSink, SubmissionStatus
from kg_contracts.testing.contract import CandidateSinkContract
from kg_contracts.testing.factories import make_entity_candidate

from kgis.ledger.row import LedgerRow
from kgis.ledger.store import SqliteCandidateLedger


class TestSqliteLedgerSink(CandidateSinkContract):
    def make_sink(self) -> CandidateSink:
        return SqliteCandidateLedger(":memory:")


def test_duplicate_semantic_key_writes_no_second_row():
    ledger = SqliteCandidateLedger(":memory:")
    c1 = make_entity_candidate(key="team/42")
    c2 = make_entity_candidate(key="team/42")  # same semantic key, new candidate_id
    assert ledger.submit([c1]).outcomes[0].status is SubmissionStatus.RECEIVED
    r2 = ledger.submit([c2])
    assert r2.outcomes[0].status is SubmissionStatus.DUPLICATE
    count = ledger._conn.execute("SELECT COUNT(*) c FROM ledger_entries").fetchone()["c"]
    assert count == 1


def test_boundary_distinct_candidates_are_not_falsely_deduped():
    """Regression test: (graph_id="ab", semantic_key="cd") and
    (graph_id="abc", semantic_key="d") are distinct candidates, but without a
    delimiter between graph_id and semantic_key their dedup_keys would both
    concatenate to "abcd", causing the second to be falsely flagged
    DUPLICATE and silently dropped. Both must be RECEIVED, and both rows
    must exist in the ledger.
    """
    ledger = SqliteCandidateLedger(":memory:")
    c1 = make_entity_candidate(graph_id="ab", key="k1", semantic_key="cd")
    c2 = make_entity_candidate(graph_id="abc", key="k2", semantic_key="d")
    r1 = ledger.submit([c1])
    r2 = ledger.submit([c2])
    assert r1.outcomes[0].status is SubmissionStatus.RECEIVED
    assert r2.outcomes[0].status is SubmissionStatus.RECEIVED
    count = ledger._conn.execute("SELECT COUNT(*) c FROM ledger_entries").fetchone()["c"]
    assert count == 2


class _SyncedConnection:
    """Wraps a real `sqlite3.Connection`, rendezvousing at a `barrier` right
    after the dedup-key SELECT fires (before the following INSERT).

    Used to force two independent connections' idempotency checks to
    interleave deterministically: both must observe "not present yet"
    before either proceeds to insert, reproducing the concurrent-writer
    race `submit()` has to survive without raising.
    """

    def __init__(self, conn: sqlite3.Connection, barrier: threading.Barrier) -> None:
        self._real = conn
        self._barrier = barrier

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        cur = self._real.execute(sql, params)
        if sql.lstrip().startswith("SELECT 1 FROM ledger_entries WHERE dedup_key"):
            self._barrier.wait(timeout=10)
        return cur

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


def test_concurrent_writers_race_on_dedup_check_yields_one_duplicate(tmp_path):
    """Two connections to the same on-disk db both miss the dedup SELECT
    (forced via `_SyncedConnection`'s barrier), so both attempt the INSERT.
    The loser must get a DUPLICATE outcome, not an uncaught IntegrityError,
    and exactly one row must land in the table.
    """
    db_path = tmp_path / "ledger.db"
    SqliteCandidateLedger(str(db_path)).close()  # pre-create schema once

    barrier = threading.Barrier(2)
    candidate_a = make_entity_candidate(key="race")
    candidate_b = make_entity_candidate(key="race")  # same semantic key/dedup_key

    results: dict[str, SubmissionStatus] = {}
    errors: dict[str, BaseException] = {}

    def run(name: str, candidate) -> None:
        try:
            sink = SqliteCandidateLedger(str(db_path))
            sink._conn = _SyncedConnection(sink._conn, barrier)  # type: ignore[assignment]
            result = sink.submit([candidate])
            results[name] = result.outcomes[0].status
            sink.close()
        except BaseException as exc:
            errors[name] = exc

    t_a = threading.Thread(target=run, args=("a", candidate_a))
    t_b = threading.Thread(target=run, args=("b", candidate_b))
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    assert not errors, errors
    assert set(results.values()) == {SubmissionStatus.RECEIVED, SubmissionStatus.DUPLICATE}

    verify_conn = sqlite3.connect(str(db_path))
    count = verify_conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0]
    verify_conn.close()
    assert count == 1


def test_mid_batch_failure_rolls_back_and_leaves_no_stranded_rows(tmp_path, monkeypatch):
    """An unexpected failure on the 2nd of 3 candidates must not strand the
    1st candidate's uncommitted insert on the connection: the whole batch
    rolls back, and a later, unrelated submit() is unaffected.
    """
    db_path = tmp_path / "ledger.db"
    ledger = SqliteCandidateLedger(str(db_path))
    candidates = [
        make_entity_candidate(key="one"),
        make_entity_candidate(key="two"),
        make_entity_candidate(key="three"),
    ]

    original_for_candidate = LedgerRow.for_candidate.__func__
    calls = {"n": 0}

    def flaky_for_candidate(cls, candidate, *, recorded_at):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated mid-batch failure")
        return original_for_candidate(cls, candidate, recorded_at=recorded_at)

    monkeypatch.setattr(LedgerRow, "for_candidate", classmethod(flaky_for_candidate))

    with pytest.raises(RuntimeError, match="simulated mid-batch failure"):
        ledger.submit(candidates)

    stranded = ledger._conn.execute("SELECT COUNT(*) c FROM ledger_entries").fetchone()["c"]
    assert stranded == 0

    monkeypatch.undo()  # restore the real LedgerRow.for_candidate before retrying

    result = ledger.submit(candidates)
    assert [o.status for o in result.outcomes] == [SubmissionStatus.RECEIVED] * 3
    count = ledger._conn.execute("SELECT COUNT(*) c FROM ledger_entries").fetchone()["c"]
    assert count == 3
