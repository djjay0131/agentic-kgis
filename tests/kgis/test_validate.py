"""Validation is two-tiered because the contract's `ValidationDecision` is
keyed on a candidate_id that does not exist yet when a record is rejected.
These tests pin both tiers and the guarantee each one buys."""

import pytest
from pydantic import ValidationError

from kg_contracts.candidates import (
    CandidateScores,
    RelationCandidate,
    SourceCoordinates,
)
from kg_contracts.curation import FailureKind
from kg_contracts.identity import EntityRef
from kg_contracts.testing.factories import (
    make_attribute_candidate,
    make_coords,
    make_entity_candidate,
)
from kgis.normalize import FieldSpec, SchemaNormalizer
from kgis.ontology import Ontology
from kgis.records import NormalizedRecord, RecordIssue, SourceRecord
from kgis.validate import (
    CandidateValidator,
    CompositeRecordValidator,
    IssueValidator,
    OntologyCandidateValidator,
    RecordValidation,
    RecordValidator,
    RequiredValuesValidator,
)

COORDS = SourceCoordinates(source_type="csv", locator="p.csv", fragment="row=2")


def normalized(
    values: dict[str, object], *, issues: tuple[RecordIssue, ...] = ()
) -> NormalizedRecord:
    return NormalizedRecord(index=0, coordinates=COORDS, values=values, issues=issues)


def relation_candidate(relation_type: str = "PLAYS_FOR") -> RelationCandidate:
    return RelationCandidate(
        graph_id="g1",
        producer="test",
        producer_run_id="run-1",
        ontology_version="1",
        source_coordinates=make_coords(),
        semantic_key=f"player/1/{relation_type}/team/2",
        scores=CandidateScores(extraction_confidence=1.0, source_reliability=0.8),
        relation_type=relation_type,
        subject=EntityRef(entity_type="Player", namespace="test", key="1"),
        object=EntityRef(entity_type="Team", namespace="test", key="2"),
    )


class TestRecordValidationModel:
    def test_invalid_requires_a_failure_kind(self) -> None:
        """Mirrors the contract's ValidationDecision biconditional exactly."""
        with pytest.raises(ValidationError, match="requires failure_kind"):
            RecordValidation(index=0, coordinates=COORDS, valid=False)

    def test_valid_forbids_a_failure_kind(self) -> None:
        with pytest.raises(ValidationError, match="forbids failure_kind"):
            RecordValidation(
                index=0, coordinates=COORDS, valid=True, failure_kind=FailureKind.BAD_DATA
            )

    def test_a_valid_record_may_still_carry_warnings(self) -> None:
        """Accepted-and-worth-mentioning is a real state; reasons cannot express it."""
        decision = RecordValidation(
            index=0, coordinates=COORDS, valid=True, warnings=("assumed_utc: ...",)
        )
        assert decision.valid is True
        assert decision.warnings


class TestIssueValidator:
    def test_rejects_a_record_normalization_could_not_read(self) -> None:
        normalizer = SchemaNormalizer([FieldSpec(name="age", type="int")])
        record = normalizer.normalize(
            SourceRecord(index=3, coordinates=COORDS, data={"age": "abc"})
        )
        decision = IssueValidator().validate(record)
        assert decision.valid is False
        assert decision.failure_kind is FailureKind.BAD_DATA
        assert decision.index == 3
        assert "coercion_failed" in decision.reasons[0]

    def test_accepts_a_clean_record(self) -> None:
        assert IssueValidator().validate(normalized({"id": "1"})).valid is True

    def test_warnings_do_not_reject(self) -> None:
        record = normalized(
            {"id": "1"},
            issues=(RecordIssue(code="assumed_utc", message="no tz", severity="warning"),),
        )
        decision = IssueValidator().validate(record)
        assert decision.valid is True
        assert decision.warnings == ("assumed_utc: no tz",)

    def test_reports_every_reason_not_just_the_first(self) -> None:
        record = normalized(
            {},
            issues=(
                RecordIssue(code="a", message="m1"),
                RecordIssue(code="b", message="m2"),
            ),
        )
        assert len(IssueValidator().validate(record).reasons) == 2

    def test_policy_version_is_carried(self) -> None:
        assert IssueValidator(policy_version="7").validate(normalized({})).policy_version == "7"

    def test_satisfies_the_protocol(self) -> None:
        assert isinstance(IssueValidator(), RecordValidator)


class TestRequiredValuesValidator:
    def test_rejects_a_null_required_value(self) -> None:
        decision = RequiredValuesValidator(["id"]).validate(normalized({"id": None}))
        assert decision.valid is False
        assert decision.failure_kind is FailureKind.BAD_DATA
        assert "'id' is null" in decision.reasons[0]

    def test_accepts_when_present(self) -> None:
        assert RequiredValuesValidator(["id"]).validate(normalized({"id": "1"})).valid is True

    def test_names_every_missing_field(self) -> None:
        decision = RequiredValuesValidator(["a", "b"]).validate(normalized({"a": None, "b": None}))
        assert len(decision.reasons) == 2


class TestCompositeRecordValidator:
    def test_collects_reasons_from_every_validator_not_just_the_first(self) -> None:
        """An operator fixing a bad file wants every reason at once."""
        record = normalized(
            {"id": None}, issues=(RecordIssue(code="coercion_failed", message="bad age"),)
        )
        composite = CompositeRecordValidator([IssueValidator(), RequiredValuesValidator(["id"])])
        decision = composite.validate(record)
        assert decision.valid is False
        assert len(decision.reasons) == 2

    def test_is_valid_only_when_every_validator_agrees(self) -> None:
        composite = CompositeRecordValidator([IssueValidator(), RequiredValuesValidator(["id"])])
        assert composite.validate(normalized({"id": "1"})).valid is True

    def test_deduplicates_the_same_reason_from_two_validators(self) -> None:
        composite = CompositeRecordValidator(
            [RequiredValuesValidator(["id"]), RequiredValuesValidator(["id"])]
        )
        assert composite.validate(normalized({"id": None})).reasons == (
            "required_value: 'id' is null",
        )

    def test_merges_policy_versions(self) -> None:
        composite = CompositeRecordValidator(
            [IssueValidator(policy_version="a"), IssueValidator(policy_version="b")]
        )
        assert composite.policy_version == "a+b"

    def test_empty_composite_accepts_everything(self) -> None:
        assert CompositeRecordValidator([]).validate(normalized({})).valid is True


class TestOntologyCandidateValidator:
    def test_accepts_a_declared_entity_type(self) -> None:
        ontology = Ontology(version="1", entity_types=frozenset({"TestEntity"}))
        decision = OntologyCandidateValidator(ontology).validate(make_entity_candidate())
        assert decision.valid is True
        assert decision.failure_kind is None

    def test_rejects_an_undeclared_entity_type_as_unsupported_ontology(self) -> None:
        """Not BAD_DATA: the row may be perfect and the ontology simply behind (spec §7.2)."""
        ontology = Ontology(version="1", entity_types=frozenset({"Player"}))
        decision = OntologyCandidateValidator(ontology).validate(make_entity_candidate())
        assert decision.valid is False
        assert decision.failure_kind is FailureKind.UNSUPPORTED_ONTOLOGY
        assert "TestEntity" in decision.reasons[0]

    def test_rejects_an_undeclared_relation_type(self) -> None:
        ontology = Ontology(version="1", relation_types=frozenset({"COACHES"}))
        decision = OntologyCandidateValidator(ontology).validate(relation_candidate("PLAYS_FOR"))
        assert decision.failure_kind is FailureKind.UNSUPPORTED_ONTOLOGY

    def test_rejects_an_undeclared_attribute(self) -> None:
        ontology = Ontology(version="1", attributes=frozenset({"weight_kg"}))
        decision = OntologyCandidateValidator(ontology).validate(make_attribute_candidate())
        assert decision.failure_kind is FailureKind.UNSUPPORTED_ONTOLOGY
        assert "height_cm" in decision.reasons[0]

    def test_permissive_mode_admits_but_still_names_the_unknown_term(self) -> None:
        """Spec §6: unknown types reported, never hidden — in either mode."""
        ontology = Ontology(version="1", entity_types=frozenset({"Player"}))
        validator = OntologyCandidateValidator(ontology, strict=False)
        decision = validator.validate(make_entity_candidate())
        assert decision.valid is True
        assert "TestEntity" in decision.reasons[0]

    def test_no_ontology_constrains_nothing(self) -> None:
        assert OntologyCandidateValidator(None).validate(make_entity_candidate()).valid is True

    def test_an_empty_term_set_is_unconstrained_not_forbidden(self) -> None:
        ontology = Ontology(version="1")
        assert OntologyCandidateValidator(ontology).validate(make_entity_candidate()).valid is True

    def test_decision_carries_the_candidates_ids(self) -> None:
        """The trace must survive into the audit stream (spec §5.9)."""
        candidate = make_entity_candidate()
        decision = OntologyCandidateValidator(None).validate(candidate)
        assert decision.candidate_id == candidate.candidate_id
        assert decision.trace_id == candidate.trace_id

    def test_satisfies_the_protocol(self) -> None:
        assert isinstance(OntologyCandidateValidator(None), CandidateValidator)
