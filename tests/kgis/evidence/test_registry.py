from datetime import UTC, datetime

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


def test_put_is_idempotent_by_id():
    reg = SqliteEvidenceRegistry(":memory:")
    ev = present_evidence(evidence_id="src:k@1", source_type="api", source_locator="k",
                          observed_at=NOW, content="x", provenance=PROV)
    reg.put(ev)
    reg.put(ev)
    count = reg._conn.execute("SELECT COUNT(*) c FROM evidence").fetchone()["c"]
    assert count == 1
