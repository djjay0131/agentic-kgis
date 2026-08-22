import pytest
from pydantic import ValidationError

from kg_contracts.candidates import (
    CANDIDATE_KINDS,
    IMPLEMENTED_KINDS,
    CandidateScores,
    ObservationCandidate,
    SourceCoordinates,
    candidate_adapter,
)

SCORES = CandidateScores(extraction_confidence=0.9, source_reliability=0.8)
COORDS = SourceCoordinates(source_type="sensor", locator="loop-7")
ENV = dict(graph_id="traffic", producer="p", producer_run_id="r1",
           ontology_version="1", source_coordinates=COORDS,
           semantic_key="k", scores=SCORES)


def test_all_nine_kinds_defined():
    assert CANDIDATE_KINDS == {
        "entity", "relation", "attribute_assertion", "observation",
        "derived_assertion", "artifact", "plan", "ontology", "identity_link",
    }
    assert IMPLEMENTED_KINDS == {"entity", "relation", "attribute_assertion",
                                 "artifact"}


def test_union_discriminates_on_candidate_kind():
    raw = dict(**ENV, candidate_kind="observation", metric="speed_avg")
    parsed = candidate_adapter.validate_python(raw)
    assert isinstance(parsed, ObservationCandidate)


def test_union_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        candidate_adapter.validate_python(dict(**ENV, candidate_kind="vibe"))


def test_spec_level_variants_are_marked():
    from kg_contracts import candidates

    for cls_name in ("ObservationCandidate", "DerivedAssertionCandidate",
                     "PlanCandidate", "OntologyCandidate",
                     "IdentityLinkCandidate"):
        assert "SPEC-LEVEL" in getattr(candidates, cls_name).__doc__


def test_roundtrip_serialization():
    c = ObservationCandidate(**ENV, metric="speed_avg", value=42.1)
    again = candidate_adapter.validate_json(c.model_dump_json())
    assert again == c


def test_observation_parameters_frozen_including_omitted_default():
    # parameters omitted entirely -> default_factory=dict; must still be
    # frozen (validate_default=True), not a silently mutable plain dict.
    c = ObservationCandidate(**ENV, metric="speed_avg", value=42.1)
    with pytest.raises(TypeError):
        c.parameters["x"] = 1  # type: ignore[index]


def test_derived_assertion_conclusion_frozen():
    from kg_contracts.candidates import DerivedAssertionCandidate
    from kg_contracts.derivation import Derivation, DerivationInput

    d = Derivation(
        method="m", deterministic=True,
        inputs=(DerivationInput(kind="assertion", ref="a1"),),
        implementation_version="v1",
    )
    c = DerivedAssertionCandidate(**ENV, derivation=d, conclusion={"value": 1})
    with pytest.raises(TypeError):
        c.conclusion["value"] = 2  # type: ignore[index]
