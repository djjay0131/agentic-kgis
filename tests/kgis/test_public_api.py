"""Public import-surface contract for `kgis.ledger` and `kgis.evidence` (Task 15)."""


def test_ledger_public_surface() -> None:
    from kgis.ledger import (  # noqa: F401
        BASEBALL_AI_PROFILE,
        ConsumerProfile,
        IdentityMode,
        IdentityResolver,
        IllegalTransitionError,
        LedgerRow,
        PersistentLedgerContract,
        SqliteAuditStream,
        SqliteCandidateLedger,
        open_ledger_db,
    )


def test_evidence_public_surface() -> None:
    from kgis.evidence import (  # noqa: F401
        EvidenceNotFoundError,
        EvidenceRegistryContract,
        SqliteEvidenceRegistry,
        open_evidence_db,
    )
