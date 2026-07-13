def test_top_level_exports() -> None:
    from kg_contracts import (  # noqa: F401
        # security (T3)
        DeletionBehavior, PolicyContext, new_trace_id,
        # evidence (T4)
        AbsenceReason, Evidence, EvidenceAvailability, EvidenceRef,
        EvidenceRelationship, Provenance, ValidPeriod,
        # identity (T5)
        EntityRef, IdentityError, IdentityLink, IdentityLinkKind,
        is_identity_id, new_identity_id, parse_identity_id,
        # derivation (T6)
        Derivation, DerivationInput,
        # versioning (T7)
        CONTRACT_VERSION, CompatibilityClass, VersionChange,
        VersionedComponentKind,
        # candidates (T8-T10)
        CANDIDATE_KINDS, IMPLEMENTED_KINDS, ArtifactCandidate,
        AttributeAssertionCandidate, Candidate, CandidateEnvelope,
        CandidateScores, DerivedAssertionCandidate, EntityCandidate,
        IdentityLinkCandidate, ObservationCandidate, OntologyCandidate,
        PlanCandidate, RelationCandidate, Representation, SourceCoordinates,
        candidate_adapter,
        # assertions (T11)
        Assertion, CanonicalEntity, ConflictRecord, ConflictStatus,
        CurationStatus,
        # policy (T12)
        AdjudicationRoute, ConfidencePolicy,
        # stores (T13, T15; ledger read surface ADR-0011)
        AdapterCapabilities, CandidateSink, CommitResult, GraphMutationBatch,
        GraphMutationStore, GraphReader, GraphReadOptions, LedgerEntry,
        LedgerReader, LedgerReadOptions, SubmissionOutcome,
        SubmissionResult, SubmissionStatus, TemporalGraphReader,
        UnsupportedCapabilityError,
        # curation (T14)
        AuditRecord, CurationOperation, CurationOperationType, CurationPlan,
        FailureKind, Precondition, ProcessingState, ResolutionDecision,
        ReviewAction, ReviewDecision, ReviewItem, ReviewQueue,
        ValidationDecision,
        # ingestion (T16)
        CompletionClient, Extractor, IngestJob, IngestReport, Source,
        # registry (T17)
        Backend, GraphDescriptor, Recommendation, RegistryStore,
        SCORED_FACTORS_V1,
    )
