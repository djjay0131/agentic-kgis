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


def test_contract_version_is_the_additive_minor_bump():
    # ADR-0022/ADR-0023 add optional fields only; ADR candidate 0011 adds the
    # optional `Evidence.span` (and the new `TextSpan`); ADR-0028 adds the
    # optional `Assertion.source_candidate_ids` / `superseded_by`. The version
    # policy makes each a backward-compatible minor bump.
    assert CONTRACT_VERSION == "2.3.0"


def test_source_version_is_optional_and_defaults_none():
    assert COORDS.source_version is None
    assert SourceCoordinates(
        source_type="sqlite", locator="sqlite://players", fragment="id=1",
        source_version="snap_42",
    ).source_version == "snap_42"


def test_source_coordinates_round_trip_including_source_version():
    coords = SourceCoordinates(
        source_type="sqlite", locator="sqlite://players@snapshot=snap_42",
        fragment="id=1", source_version="snap_42",
    )
    restored = SourceCoordinates.model_validate_json(coords.model_dump_json())
    assert restored == coords
    assert restored.source_version == "snap_42"


def test_model_and_extractor_version_fields_default_none_and_round_trip():
    e = _envelope()
    assert e.model_id is None
    assert e.model_version is None
    assert e.extractor_version is None
    assert e.prompt_version is None

    filled = _envelope(
        model_id="claude-fake",
        model_version="2026-08",
        extractor_version="7",
        prompt_version="p3",
    )
    restored = CandidateEnvelope.model_validate_json(filled.model_dump_json())
    assert restored.model_id == "claude-fake"
    assert restored.model_version == "2026-08"
    assert restored.extractor_version == "7"
    assert restored.prompt_version == "p3"


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


def test_representations_frozen_at_rest_including_omitted_default():
    e = _envelope(representations={
        "raw_statement": Representation(kind="text", text="Player X bats left"),
    })
    with pytest.raises(TypeError):
        e.representations["raw_statement"] = Representation(  # type: ignore[index]
            kind="text", text="tampered")

    # representations omitted entirely -> default_factory=dict; must still be
    # frozen (validate_default=True), not a silently mutable plain dict.
    e2 = _envelope()
    with pytest.raises(TypeError):
        e2.representations["x"] = Representation(  # type: ignore[index]
            kind="text", text="z")
