from datetime import UTC, datetime

import pytest

from kg_contracts.evidence import (
    AbsenceReason,
    EvidenceAvailability,
    Provenance,
    absent_evidence,
    error_evidence,
    present_evidence,
)

from kgis.evidence.store import SqliteEvidenceRegistry

NOW = datetime(2026, 7, 21, tzinfo=UTC)
PROV = Provenance(source="test", actor="tester")


def test_all_three_availabilities_persist_and_resolve():
    reg = SqliteEvidenceRegistry(":memory:")
    present = present_evidence(evidence_id="src:k@1", source_type="api",
                              source_locator="k", observed_at=NOW, content="x", provenance=PROV)
    absent = absent_evidence(evidence_id="src:k@2", source_type="api",
                             source_locator="k", observed_at=NOW,
                             reason=AbsenceReason.SOURCE_OMITTED, provenance=PROV)
    err = error_evidence(evidence_id="src:k@3", source_type="api",
                         source_locator="k", observed_at=NOW, error="timeout", provenance=PROV)
    reg.put_many([present, absent, err])
    assert reg.get("src:k@1").availability is EvidenceAvailability.PRESENT
    assert reg.get("src:k@2").absence_reason is AbsenceReason.SOURCE_OMITTED
    assert reg.get("src:k@3").error == "timeout"
    assert reg.get("missing") is None


def test_put_many_is_atomic_on_mid_batch_failure(monkeypatch):
    """A failure partway through `put_many` rolls the whole batch back: the
    first item's insert must not be left stranded (Issue #14, single-txn)."""
    reg = SqliteEvidenceRegistry(":memory:")
    items = [
        present_evidence(evidence_id=f"src:k@{i}", source_type="api", source_locator="k",
                         observed_at=NOW, content="x", provenance=PROV)
        for i in range(1, 4)
    ]
    real = reg._put_stmt
    calls = {"n": 0}

    def flaky(ev):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated mid-batch failure")
        real(ev)

    monkeypatch.setattr(reg, "_put_stmt", flaky)
    with pytest.raises(RuntimeError, match="simulated mid-batch failure"):
        reg.put_many(items)

    count = reg._conn.execute("SELECT COUNT(*) c FROM evidence").fetchone()["c"]
    assert count == 0  # first insert rolled back, nothing committed


def test_put_is_idempotent_by_id():
    reg = SqliteEvidenceRegistry(":memory:")
    ev = present_evidence(evidence_id="src:k@1", source_type="api", source_locator="k",
                          observed_at=NOW, content="x", provenance=PROV)
    reg.put(ev)
    reg.put(ev)
    count = reg._conn.execute("SELECT COUNT(*) c FROM evidence").fetchone()["c"]
    assert count == 1
