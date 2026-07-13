import pytest
from pydantic import ValidationError

from kg_contracts.candidates import (
    ArtifactCandidate,
    AttributeAssertionCandidate,
    CandidateScores,
    EntityCandidate,
    RelationCandidate,
    SourceCoordinates,
)
from kg_contracts.identity import EntityRef, new_identity_id

SCORES = CandidateScores(extraction_confidence=0.9, source_reliability=0.8)
COORDS = SourceCoordinates(source_type="document", locator="doc-1#p3")
ENV = dict(graph_id="baseball", producer="llm-extract", producer_run_id="r1",
           ontology_version="1", source_coordinates=COORDS, scores=SCORES)
PLAYER = EntityRef(entity_type="Player", namespace="usssa", key="12345")


def test_entity_candidate_valid():
    c = EntityCandidate(**ENV, semantic_key="baseball/player/usssa:12345",
                        entity_type="Player", aliases=(PLAYER,))
    assert c.candidate_kind == "entity"


def test_entity_candidate_requires_aliases():
    with pytest.raises(ValidationError, match="alias"):
        EntityCandidate(**ENV, semantic_key="k", entity_type="Player", aliases=())


def test_entity_candidate_alias_type_must_match():
    with pytest.raises(ValidationError, match="entity_type"):
        EntityCandidate(**ENV, semantic_key="k", entity_type="Coach",
                        aliases=(PLAYER,))


def test_relation_candidate_valid_with_ref_and_identity_subject():
    iid = new_identity_id("baseball")
    c = RelationCandidate(**ENV, semantic_key="k", relation_type="PLAYS_FOR",
                          subject=PLAYER, object=iid)
    assert c.candidate_kind == "relation"


def test_relation_candidate_rejects_bad_type_and_bad_subject():
    with pytest.raises(ValidationError, match="UPPER_SNAKE"):
        RelationCandidate(**ENV, semantic_key="k", relation_type="playsFor",
                          subject=PLAYER, object=PLAYER)
    with pytest.raises(ValidationError, match="identity"):
        RelationCandidate(**ENV, semantic_key="k", relation_type="PLAYS_FOR",
                          subject="Player:123", object=PLAYER)  # bare id string


def test_attribute_assertion_candidate():
    c = AttributeAssertionCandidate(**ENV, semantic_key="k", subject=PLAYER,
                                    attribute="batting_avg", value=0.312)
    assert c.candidate_kind == "attribute_assertion"
    with pytest.raises(ValidationError):
        AttributeAssertionCandidate(**ENV, semantic_key="k", subject=PLAYER,
                                    attribute="", value=1)


def test_artifact_candidate():
    c = ArtifactCandidate(**ENV, semantic_key="k", artifact_type="cut_list",
                          artifact_hash="sha256:abc", source_uri="s3://b/cuts.csv")
    assert c.candidate_kind == "artifact"
    with pytest.raises(ValidationError):
        ArtifactCandidate(**ENV, semantic_key="k", artifact_type="cut_list",
                          artifact_hash="", source_uri="s3://b/x")
