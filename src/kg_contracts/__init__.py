"""kg_contracts: the shared ports/contracts layer for the KGIS/KGCS spec
(docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md, v2), version
`CONTRACT_VERSION`.

This module is the stable public import surface. It re-exports the typed
contracts, protocols, and helpers built across Tasks 3-18: security
context and deletion semantics; evidence; immutable identity; derivation
provenance; contract/component versioning; the nine-variant candidate
union; bitemporal assertions and canonical entities; the confidence
policy; the two-level (candidate sink / graph mutation) store protocols;
curation-plane contracts; ingestion protocols; and the graph registry.

Adapter-internal writer protocols (`GraphWriter`, `TransactionalGraphWriter`,
`BulkGraphWriter`) are deliberately not re-exported here — they remain
importable from `kg_contracts.stores` for adapter authors only; no
consumer-facing protocol in this module exposes raw graph writes.
"""

from kg_contracts.assertions import (
    Assertion,
    CanonicalEntity,
    ConflictRecord,
    ConflictStatus,
    CurationStatus,
)
from kg_contracts.candidates import (
    CANDIDATE_KINDS,
    IMPLEMENTED_KINDS,
    ArtifactCandidate,
    AttributeAssertionCandidate,
    Candidate,
    CandidateEnvelope,
    CandidateScores,
    DerivedAssertionCandidate,
    EntityCandidate,
    IdentityLinkCandidate,
    ObservationCandidate,
    OntologyCandidate,
    PlanCandidate,
    RelationCandidate,
    Representation,
    SourceCoordinates,
    candidate_adapter,
)
from kg_contracts.curation import (
    AuditRecord,
    CurationOperation,
    CurationOperationType,
    CurationPlan,
    FailureKind,
    Precondition,
    ProcessingState,
    ResolutionDecision,
    ReviewAction,
    ReviewDecision,
    ReviewItem,
    ReviewQueue,
    ValidationDecision,
)
from kg_contracts.derivation import Derivation, DerivationInput
from kg_contracts.evidence import (
    AbsenceReason,
    Evidence,
    EvidenceAvailability,
    EvidenceRef,
    EvidenceRelationship,
    Provenance,
    ValidPeriod,
)
from kg_contracts.identity import (
    EntityRef,
    IdentityError,
    IdentityLink,
    IdentityLinkKind,
    is_identity_id,
    new_identity_id,
    parse_identity_id,
)
from kg_contracts.ingestion import (
    CompletionClient,
    Extractor,
    IngestJob,
    IngestReport,
    Source,
)
from kg_contracts.policy import AdjudicationRoute, ConfidencePolicy
from kg_contracts.registry import (
    SCORED_FACTORS_V1,
    Backend,
    GraphDescriptor,
    Recommendation,
    RegistryStore,
)
from kg_contracts.security import DeletionBehavior, PolicyContext, new_trace_id
from kg_contracts.stores import (
    AdapterCapabilities,
    CandidateSink,
    CommitResult,
    GraphMutationBatch,
    GraphMutationStore,
    GraphReader,
    GraphReadOptions,
    SubmissionOutcome,
    SubmissionResult,
    SubmissionStatus,
    TemporalGraphReader,
    UnsupportedCapabilityError,
)
from kg_contracts.versioning import (
    CONTRACT_VERSION,
    CompatibilityClass,
    VersionChange,
    VersionedComponentKind,
)

__all__ = [
    # security (T3)
    "DeletionBehavior",
    "PolicyContext",
    "new_trace_id",
    # evidence (T4)
    "AbsenceReason",
    "Evidence",
    "EvidenceAvailability",
    "EvidenceRef",
    "EvidenceRelationship",
    "Provenance",
    "ValidPeriod",
    # identity (T5)
    "EntityRef",
    "IdentityError",
    "IdentityLink",
    "IdentityLinkKind",
    "is_identity_id",
    "new_identity_id",
    "parse_identity_id",
    # derivation (T6)
    "Derivation",
    "DerivationInput",
    # versioning (T7)
    "CONTRACT_VERSION",
    "CompatibilityClass",
    "VersionChange",
    "VersionedComponentKind",
    # candidates (T8-T10)
    "CANDIDATE_KINDS",
    "IMPLEMENTED_KINDS",
    "ArtifactCandidate",
    "AttributeAssertionCandidate",
    "Candidate",
    "CandidateEnvelope",
    "CandidateScores",
    "DerivedAssertionCandidate",
    "EntityCandidate",
    "IdentityLinkCandidate",
    "ObservationCandidate",
    "OntologyCandidate",
    "PlanCandidate",
    "RelationCandidate",
    "Representation",
    "SourceCoordinates",
    "candidate_adapter",
    # assertions (T11)
    "Assertion",
    "CanonicalEntity",
    "ConflictRecord",
    "ConflictStatus",
    "CurationStatus",
    # policy (T12)
    "AdjudicationRoute",
    "ConfidencePolicy",
    # stores (T13, T15)
    "AdapterCapabilities",
    "CandidateSink",
    "CommitResult",
    "GraphMutationBatch",
    "GraphMutationStore",
    "GraphReader",
    "GraphReadOptions",
    "SubmissionOutcome",
    "SubmissionResult",
    "SubmissionStatus",
    "TemporalGraphReader",
    "UnsupportedCapabilityError",
    # curation (T14)
    "AuditRecord",
    "CurationOperation",
    "CurationOperationType",
    "CurationPlan",
    "FailureKind",
    "Precondition",
    "ProcessingState",
    "ResolutionDecision",
    "ReviewAction",
    "ReviewDecision",
    "ReviewItem",
    "ReviewQueue",
    "ValidationDecision",
    # ingestion (T16)
    "CompletionClient",
    "Extractor",
    "IngestJob",
    "IngestReport",
    "Source",
    # registry (T17)
    "Backend",
    "GraphDescriptor",
    "Recommendation",
    "RegistryStore",
    "SCORED_FACTORS_V1",
]
