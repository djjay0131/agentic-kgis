from datetime import UTC, datetime

import pytest

from kg_contracts.evidence import (
    EvidenceRef,
    EvidenceRelationship,
    Provenance,
    present_evidence,
)

from kgis.evidence.contract import EvidenceRegistryContract
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
