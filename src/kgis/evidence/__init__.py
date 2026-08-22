"""Persistent evidence registry (spec §5.3)."""

from kgis.evidence.contract import EvidenceRegistryContract
from kgis.evidence.schema import open_evidence_db
from kgis.evidence.store import EvidenceNotFoundError, SqliteEvidenceRegistry

__all__ = [
    "EvidenceNotFoundError",
    "EvidenceRegistryContract",
    "SqliteEvidenceRegistry",
    "open_evidence_db",
]
