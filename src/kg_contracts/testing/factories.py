"""Test-data builders shared by the reusable contract suites (`contract.py`)
and every downstream repo/adopter that tests against `kg_contracts` ports.

Each factory takes explicit, individually typed keyword parameters with
sensible defaults (never a `**overrides` dict-splat into a model
constructor) so callers only spell out what actually matters for their
test, while mypy --strict still checks every argument against the real
field type. These are the only place in `kg_contracts` where sample data
is assembled — the reusable suites themselves, and any adopter's own
tests, build fixtures through here rather than hand-rolling model
construction.
"""

from datetime import UTC, datetime

from kg_contracts.assertions import Assertion, CanonicalEntity, CurationStatus
from kg_contracts.candidates import (
    AttributeAssertionCandidate,
    CandidateScores,
    EntityCandidate,
    SourceCoordinates,
    SubjectRef,
)
from kg_contracts.derivation import Derivation
from kg_contracts.evidence import EvidenceRef, Provenance, ValidPeriod
from kg_contracts.identity import EntityRef, new_identity_id
from kg_contracts.security import new_trace_id

NOW: datetime = datetime(2026, 7, 12, tzinfo=UTC)
"""Fixed instant used as the default timestamp everywhere in this module,
so factory output is reproducible across calls unless a test overrides it."""


def make_scores(
    *,
    extraction_confidence: float = 0.92,
    source_reliability: float = 0.9,
    identity_confidence: float | None = None,
    assertion_confidence: float | None = None,
    corroboration_score: float | None = None,
    policy_risk: float = 0.0,
) -> CandidateScores:
    """Build a `CandidateScores` with both required scores set."""
    return CandidateScores(
        extraction_confidence=extraction_confidence,
        source_reliability=source_reliability,
        identity_confidence=identity_confidence,
        assertion_confidence=assertion_confidence,
        corroboration_score=corroboration_score,
        policy_risk=policy_risk,
    )


def make_coords(
    *,
    source_type: str = "test",
    locator: str = "row-1",
    fragment: str | None = None,
) -> SourceCoordinates:
    """Build a `SourceCoordinates` pointing at a fake test row."""
    return SourceCoordinates(source_type=source_type, locator=locator, fragment=fragment)


def make_entity_candidate(
    *,
    graph_id: str = "g1",
    key: str = "e1",
    entity_type: str = "TestEntity",
    aliases: tuple[EntityRef, ...] | None = None,
    semantic_key: str | None = None,
    scores: CandidateScores | None = None,
    source_coordinates: SourceCoordinates | None = None,
    display_name: str | None = None,
    properties: dict[str, object] | None = None,
) -> EntityCandidate:
    """Build a valid `EntityCandidate` for graph `graph_id` keyed by `key`."""
    return EntityCandidate(
        graph_id=graph_id,
        producer="test-producer",
        producer_run_id="run-1",
        ontology_version="1",
        source_coordinates=source_coordinates if source_coordinates is not None else make_coords(),
        semantic_key=semantic_key if semantic_key is not None else f"testentity/{key}",
        scores=scores if scores is not None else make_scores(),
        entity_type=entity_type,
        aliases=aliases
        if aliases is not None
        else (EntityRef(entity_type=entity_type, namespace="test", key=key),),
        display_name=display_name,
        properties=properties if properties is not None else {},
    )


def make_attribute_candidate(
    *,
    graph_id: str = "g1",
    key: str = "e1",
    subject: SubjectRef | None = None,
    attribute: str = "height_cm",
    value: object = 200,
    scores: CandidateScores | None = None,
    source_coordinates: SourceCoordinates | None = None,
    valid_period: ValidPeriod | None = None,
) -> AttributeAssertionCandidate:
    """Build a valid `AttributeAssertionCandidate` about identity `key`."""
    return AttributeAssertionCandidate(
        graph_id=graph_id,
        producer="test-producer",
        producer_run_id="run-1",
        ontology_version="1",
        source_coordinates=source_coordinates if source_coordinates is not None else make_coords(),
        semantic_key=f"testentity/{key}/{attribute}",
        scores=scores if scores is not None else make_scores(),
        subject=subject if subject is not None else new_identity_id(graph_id),
        attribute=attribute,
        value=value,
        valid_period=valid_period,
    )


def make_entity(
    *,
    graph_id: str = "g1",
    key: str = "e1",
    entity_type: str = "TestEntity",
    identity_id: str | None = None,
    aliases: tuple[EntityRef, ...] | None = None,
    status: CurationStatus = CurationStatus.ACTIVE,
    display_name: str | None = None,
    created_at: datetime = NOW,
    curation_epoch: int = 0,
) -> CanonicalEntity:
    """Build a valid `CanonicalEntity` in the canonical graph `graph_id`."""
    return CanonicalEntity(
        identity_id=identity_id if identity_id is not None else new_identity_id(graph_id),
        entity_type=entity_type,
        aliases=aliases
        if aliases is not None
        else (EntityRef(entity_type=entity_type, namespace="test", key=key),),
        status=status,
        display_name=display_name,
        created_at=created_at,
        curation_epoch=curation_epoch,
    )


def make_assertion(
    *,
    graph_id: str = "g1",
    subject_identity: str | None = None,
    predicate: str = "height_cm",
    object_value: object = 200,
    object_identity: str | None = None,
    status: CurationStatus = CurationStatus.ACTIVE,
    valid_period: ValidPeriod | None = None,
    recorded_at: datetime = NOW,
    superseded_at: datetime | None = None,
    scores: CandidateScores | None = None,
    evidence_refs: tuple[EvidenceRef, ...] = (),
    authority: str = "test-authority",
    provenance: Provenance | None = None,
    derivation: Derivation | None = None,
    curation_epoch: int = 0,
    trace_id: str | None = None,
) -> Assertion:
    """Build a valid `Assertion`; defaults to a fresh identity as subject."""
    return Assertion(
        subject_identity=subject_identity
        if subject_identity is not None
        else new_identity_id(graph_id),
        predicate=predicate,
        object_value=object_value,
        object_identity=object_identity,
        status=status,
        valid_period=valid_period if valid_period is not None else ValidPeriod(),
        recorded_at=recorded_at,
        superseded_at=superseded_at,
        scores=scores if scores is not None else make_scores(),
        evidence_refs=evidence_refs,
        authority=authority,
        provenance=provenance
        if provenance is not None
        else Provenance(source="test", actor="tester"),
        derivation=derivation,
        curation_epoch=curation_epoch,
        trace_id=trace_id if trace_id is not None else new_trace_id(),
    )
