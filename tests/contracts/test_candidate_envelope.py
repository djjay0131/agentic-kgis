import pytest
from pydantic import ValidationError

from kg_contracts.candidates import (
    CandidateEnvelope,
    CandidateScores,
    Representation,
    SourceCoordinates,
)
from kg_contracts.versioning import CONTRACT_VERSION

SCORES = CandidateScores(extraction_confidence=0.9, source_reliability=0.8)
COORDS = SourceCoordinates(source_type="postgres", locator="intersections/101")


def _envelope(**overrides: object) -> CandidateEnvelope:
    base: dict[str, object] = dict(
        graph_id="traffic",
        candidate_kind="entity",
        producer="structured-sync",
        producer_run_id="run-1",
        ontology_version="1",
        source_coordinates=COORDS,
        semantic_key="traffic/intersection/101",
        scores=SCORES,
    )
    base.update(overrides)
    return CandidateEnvelope(**base)  # type: ignore[arg-type]


def test_envelope_defaults():
    e = _envelope()
    assert e.candidate_id.startswith("cand_")
    assert e.trace_id.startswith("trace_")
    assert e.contract_version == CONTRACT_VERSION
    assert e.created_at.tzinfo is not None


def test_single_confidence_is_banned():
    with pytest.raises(ValidationError):
        _envelope(confidence=0.9)  # extra="forbid" makes this a hard error
    with pytest.raises(ValidationError):
        CandidateScores(confidence=0.9)  # type: ignore[call-arg]


def test_scores_require_extraction_and_source_reliability():
    with pytest.raises(ValidationError):
        CandidateScores(extraction_confidence=0.9)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        CandidateScores(extraction_confidence=1.2, source_reliability=0.5)


def test_optional_scores_start_unknown():
    assert SCORES.identity_confidence is None
    assert SCORES.assertion_confidence is None
    assert SCORES.policy_risk == 0.0


def test_semantic_key_required_nonempty():
    with pytest.raises(ValidationError):
        _envelope(semantic_key="")


def test_representations_are_named_views():
    e = _envelope(representations={
        "raw_statement": Representation(kind="text", text="Player X bats left"),
        "statement_embedding": Representation(
            kind="vector", vector=(0.1, 0.2), model="embed-v3"),
    })
    assert set(e.representations) == {"raw_statement", "statement_embedding"}


def test_representation_exactly_one_payload():
    with pytest.raises(ValidationError, match="vector"):
        Representation(kind="vector", text="oops")
