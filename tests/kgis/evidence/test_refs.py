import sqlite3
from datetime import UTC, datetime

import pytest

from kg_contracts.evidence import (
    EvidenceRef,
    EvidenceRelationship,
    Provenance,
    present_evidence,
)

from kgis.evidence.contract import EvidenceRegistryContract
from kgis.evidence.schema import SCHEMA_SQL
from kgis.evidence.store import EvidenceNotFoundError, SqliteEvidenceRegistry

NOW = datetime(2026, 7, 21, tzinfo=UTC)
PROV = Provenance(source="test", actor="tester")


class TestSqliteEvidenceRegistry(EvidenceRegistryContract):
    def make_registry(self) -> SqliteEvidenceRegistry:
        return SqliteEvidenceRegistry(":memory:")


def test_resolve_by_relationship():
    reg = SqliteEvidenceRegistry(":memory:")
    reg.put(present_evidence(evidence_id="e1", source_type="api", source_locator="k",
                             observed_at=NOW, content="x", provenance=PROV))
    reg.add_refs("cand_1", [
        EvidenceRef(evidence_id="e1", relationship=EvidenceRelationship.SUPPORTS),
    ])
    resolved = reg.resolve("cand_1", EvidenceRelationship.SUPPORTS)
    assert [e.evidence_id for e in resolved] == ["e1"]
    assert reg.resolve("cand_1", EvidenceRelationship.CONTRADICTS) == []


def test_dangling_ref_is_not_silently_dropped():
    reg = SqliteEvidenceRegistry(":memory:")
    reg.add_refs("cand_1", [
        EvidenceRef(evidence_id="missing", relationship=EvidenceRelationship.SUPPORTS),
    ])
    with pytest.raises(EvidenceNotFoundError, match="missing"):
        reg.resolve("cand_1")


def test_resolve_contextualizes_round_trips():
    reg = SqliteEvidenceRegistry(":memory:")
    reg.put(present_evidence(evidence_id="e1", source_type="api", source_locator="k",
                             observed_at=NOW, content="x", provenance=PROV))
    reg.add_refs("cand_1", [
        EvidenceRef(evidence_id="e1", relationship=EvidenceRelationship.CONTEXTUALIZES),
    ])
    refs = reg.refs_for("cand_1", EvidenceRelationship.CONTEXTUALIZES)
    assert [r.evidence_id for r in refs] == ["e1"]
    resolved = reg.resolve("cand_1", EvidenceRelationship.CONTEXTUALIZES)
    assert [e.evidence_id for e in resolved] == ["e1"]


class _FlakyExecutemanyConnection(sqlite3.Connection):
    """A sqlite3.Connection whose executemany() can be armed to fail partway
    through a batch, simulating a real mid-batch write failure (e.g. a
    constraint violation on a later row).

    sqlite3.Connection is an immutable C-extension type: neither instance
    nor class attribute assignment works (`monkeypatch.setattr` hits the same
    "attribute is read-only" / "immutable type" error a plain `setattr`
    would), so the ledger suite's `monkeypatch.setattr(obj, "method", boom)`
    style can't be applied directly to it. This subclass is the equivalent
    seam: `SqliteEvidenceRegistry.__init__` already accepts a pre-built
    `sqlite3.Connection`, so passing an instance of this subclass lets the
    test inject the failure at the exact call `add_refs` makes, after some
    rows have actually been written to the (uncommitted) transaction.
    """

    fail_after: int | None = None

    def executemany(self, sql, seq):  # type: ignore[override]
        rows = list(seq)
        if self.fail_after is not None and len(rows) > self.fail_after:
            super().executemany(sql, rows[: self.fail_after])
            raise RuntimeError("simulated mid-batch failure")
        return super().executemany(sql, rows)


def _make_flaky_registry() -> tuple[SqliteEvidenceRegistry, _FlakyExecutemanyConnection]:
    conn = sqlite3.connect(":memory:", factory=_FlakyExecutemanyConnection)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return SqliteEvidenceRegistry(conn), conn


def test_add_refs_write_failure_rolls_back_and_leaves_registry_usable():
    reg, conn = _make_flaky_registry()
    reg.put(present_evidence(evidence_id="e1", source_type="api", source_locator="k",
                             observed_at=NOW, content="x", provenance=PROV))
    reg.put(present_evidence(evidence_id="e2", source_type="api", source_locator="k",
                             observed_at=NOW, content="x", provenance=PROV))
    reg.put(present_evidence(evidence_id="e3", source_type="api", source_locator="k",
                             observed_at=NOW, content="x", provenance=PROV))

    # A ref that already exists before the failing call, to prove it survives
    # the rollback untouched.
    reg.add_refs("cand_1", [
        EvidenceRef(evidence_id="e1", relationship=EvidenceRelationship.SUPPORTS),
    ])
    before = conn.execute(
        "SELECT COUNT(*) c FROM evidence_refs"
    ).fetchone()["c"]
    assert before == 1

    conn.fail_after = 1  # write the 1st row of the batch, then blow up on the 2nd
    with pytest.raises(RuntimeError, match="simulated mid-batch failure"):
        reg.add_refs("cand_1", [
            EvidenceRef(evidence_id="e2", relationship=EvidenceRelationship.SUPPORTS),
            EvidenceRef(evidence_id="e3", relationship=EvidenceRelationship.SUPPORTS),
        ])
    conn.fail_after = None

    # No partial refs from the failed batch: row count unchanged from before.
    after = conn.execute("SELECT COUNT(*) c FROM evidence_refs").fetchone()["c"]
    assert after == before
    assert reg.resolve("cand_1", EvidenceRelationship.SUPPORTS)[0].evidence_id == "e1"

    # Registry is still usable: a subsequent add_refs succeeds and commits.
    reg.add_refs("cand_1", [
        EvidenceRef(evidence_id="e2", relationship=EvidenceRelationship.SUPPORTS),
    ])
    resolved_ids = {e.evidence_id for e in reg.resolve("cand_1", EvidenceRelationship.SUPPORTS)}
    assert resolved_ids == {"e1", "e2"}
