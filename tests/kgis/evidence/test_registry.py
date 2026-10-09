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


def test_provenance_model_version_round_trips_through_the_registry():
    """ADR-0023's `Provenance.model_version` survives `put`/`get` via
    `evidence_json` (no new column required)."""
    reg = SqliteEvidenceRegistry(":memory:")
    prov = Provenance(
        source="s3://reports/doc-1.txt", actor="player", model="claude-fake",
        model_version="2026-08", prompt_version="p3",
    )
    reg.put(present_evidence(
        evidence_id="src:k@mv", source_type="document", source_locator="doc-1",
        observed_at=NOW, content="x", provenance=prov,
    ))
    got = reg.get("src:k@mv")
    assert got is not None
    assert got.provenance.model_version == "2026-08"
    assert got.provenance.model == "claude-fake"
    assert got.provenance.prompt_version == "p3"


def test_put_is_idempotent_by_id():
    reg = SqliteEvidenceRegistry(":memory:")
    ev = present_evidence(evidence_id="src:k@1", source_type="api", source_locator="k",
                          observed_at=NOW, content="x", provenance=PROV)
    reg.put(ev)
    reg.put(ev)
    count = reg._conn.execute("SELECT COUNT(*) c FROM evidence").fetchone()["c"]
    assert count == 1
