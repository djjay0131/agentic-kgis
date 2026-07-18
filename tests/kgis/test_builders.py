"""Builders produce proposals, never graph records. These tests pin the score
honesty required by ADR-0004, the null-value rule, and the composed semantic
keys that idempotency rides on."""

from datetime import UTC, datetime

import pytest

from kg_contracts.assertions import Assertion, CanonicalEntity
from kg_contracts.candidates import (
    IMPLEMENTED_KINDS,
    AttributeAssertionCandidate,
    CandidateEnvelope,
    EntityCandidate,
    RelationCandidate,
    SourceCoordinates,
    candidate_adapter,
)
from kg_contracts.identity import EntityRef
from kgis.builders import (
    AttributeCandidateBuilder,
    BuildContext,
    CandidateBuilder,
    CompositeCandidateBuilder,
    EntityCandidateBuilder,
    RelationCandidateBuilder,
    SourceScoring,
    entity_semantic_key,
)
from kgis.clock import FixedClock
from kgis.errors import ConfigurationError
from kgis.ids import DeterministicIdStrategy
from kgis.records import NormalizedRecord

NOW = datetime(2026, 7, 14, tzinfo=UTC)
COORDS = SourceCoordinates(source_type="csv", locator="players.csv", fragment="row=2")


def context(**overrides: object) -> BuildContext:
    defaults: dict[str, object] = {
        "graph_id": "baseball",
        "producer": "kgis.structured",
        "producer_run_id": "run-1",
        "ontology_version": "1",
        "scoring": SourceScoring(source_reliability=0.8),
        "clock": FixedClock(NOW),
        "ids": DeterministicIdStrategy(),
    }
    return BuildContext(**{**defaults, **overrides})  # type: ignore[arg-type]


def record(values: dict[str, object]) -> NormalizedRecord:
    return NormalizedRecord(index=0, coordinates=COORDS, values=values)


def player_builder(**overrides: object) -> EntityCandidateBuilder:
    defaults: dict[str, object] = {
        "entity_type": "Player",
        "namespace": "usssa",
        "key_field": "id",
    }
    return EntityCandidateBuilder(**{**defaults, **overrides})  # type: ignore[arg-type]


class TestSourceScoring:
    def test_source_reliability_has_no_default(self) -> None:
        """ADR-0004: a perfect read of an unreliable source is still just that.
        A default here would let the distinction quietly evaporate."""
        with pytest.raises(Exception, match="source_reliability"):
            SourceScoring()  # type: ignore[call-arg]

    def test_extraction_confidence_defaults_to_one_for_an_exact_read(self) -> None:
        assert SourceScoring(source_reliability=0.5).extraction_confidence == 1.0

    def test_unknown_axes_stay_none_rather_than_zero(self) -> None:
        """Honest nulls: curation fills these in. A zero would read as 'scored low'."""
        scores = SourceScoring(source_reliability=0.8).to_scores()
        assert scores.identity_confidence is None
        assert scores.assertion_confidence is None
        assert scores.corroboration_score is None

    def test_carries_both_required_axes(self) -> None:
        scores = SourceScoring(source_reliability=0.4, extraction_confidence=0.9).to_scores()
        assert scores.source_reliability == 0.4
        assert scores.extraction_confidence == 0.9


class TestEntityCandidateBuilder:
    def test_builds_an_entity_candidate(self) -> None:
        [candidate] = player_builder().build(record({"id": "42"}), context())
        assert isinstance(candidate, EntityCandidate)
        assert candidate.entity_type == "Player"
        assert candidate.aliases == (
            EntityRef(entity_type="Player", namespace="usssa", key="42"),
        )

    def test_semantic_key_is_composed_not_hashed(self) -> None:
        """Spec §5.8: hashes are a supplementary signal, never the anchor."""
        [candidate] = player_builder().build(record({"id": "42"}), context())
        assert candidate.semantic_key == "player/usssa/42"

    def test_carries_the_runs_provenance(self) -> None:
        [candidate] = player_builder().build(record({"id": "42"}), context())
        assert candidate.graph_id == "baseball"
        assert candidate.producer == "kgis.structured"
        assert candidate.producer_run_id == "run-1"
        assert candidate.ontology_version == "1"
        assert candidate.source_coordinates == COORDS
        assert candidate.created_at == NOW

    def test_content_hash_rides_along_as_a_supplementary_signal(self) -> None:
        [candidate] = player_builder().build(record({"id": "42"}), context())
        assert candidate.content_hash is not None
        assert candidate.content_hash.startswith("b2:")

    def test_display_name_and_properties(self) -> None:
        builder = player_builder(display_name_field="name", property_fields=("bats",))
        [candidate] = builder.build(record({"id": "42", "name": "Ada", "bats": "L"}), context())
        assert isinstance(candidate, EntityCandidate)
        assert candidate.display_name == "Ada"
        assert candidate.properties == {"bats": "L"}

    def test_a_null_property_is_not_a_property(self) -> None:
        builder = player_builder(property_fields=("bats",))
        [candidate] = builder.build(record({"id": "42", "bats": None}), context())
        assert isinstance(candidate, EntityCandidate)
        assert candidate.properties == {}

    def test_entity_type_can_come_from_a_column(self) -> None:
        builder = EntityCandidateBuilder(
            namespace="usssa", key_field="id", entity_type_field="kind"
        )
        [candidate] = builder.build(record({"id": "1", "kind": "Coach"}), context())
        assert isinstance(candidate, EntityCandidate)
        assert candidate.entity_type == "Coach"
        assert candidate.semantic_key == "coach/usssa/1"

    def test_requires_exactly_one_of_entity_type_or_entity_type_field(self) -> None:
        with pytest.raises(ConfigurationError):
            EntityCandidateBuilder(namespace="n", key_field="id")
        with pytest.raises(ConfigurationError):
            EntityCandidateBuilder(
                namespace="n", key_field="id", entity_type="Player", entity_type_field="kind"
            )

    def test_declares_its_required_fields(self) -> None:
        assert player_builder().required_fields == ("id",)
        assert EntityCandidateBuilder(
            namespace="n", key_field="id", entity_type_field="kind"
        ).required_fields == ("id", "kind")

    def test_an_empty_key_raises_rather_than_minting_a_junk_identity(self) -> None:
        """ts-kg's lesson: free-text IDs destroy ingestion (ADR-0008)."""
        with pytest.raises(ValueError, match="empty"):
            player_builder().build(record({"id": None}), context())

    def test_satisfies_the_protocol(self) -> None:
        assert isinstance(player_builder(), CandidateBuilder)


class TestAttributeCandidateBuilder:
    def test_builds_one_candidate_per_attribute(self) -> None:
        builder = AttributeCandidateBuilder(
            subject=player_builder(), attribute_fields=("height_cm", "weight_kg")
        )
        candidates = builder.build(
            record({"id": "42", "height_cm": 180, "weight_kg": 80}), context()
        )
        assert [c.semantic_key for c in candidates] == [
            "player/usssa/42/height_cm",
            "player/usssa/42/weight_kg",
        ]

    def test_a_null_attribute_asserts_nothing_rather_than_asserting_null(self) -> None:
        """Absence of evidence is not evidence of absence (spec §5.3)."""
        builder = AttributeCandidateBuilder(
            subject=player_builder(), attribute_fields=("height_cm",)
        )
        assert builder.build(record({"id": "42", "height_cm": None}), context()) == []

    def test_subject_is_the_same_ref_the_entity_builder_mints(self) -> None:
        """An attribute must never hang off an entity the ingest did not propose."""
        entity_builder = player_builder()
        attribute_builder = AttributeCandidateBuilder(
            subject=entity_builder, attribute_fields=("height_cm",)
        )
        source = record({"id": "42", "height_cm": 180})
        [entity] = entity_builder.build(source, context())
        [attribute] = attribute_builder.build(source, context())
        assert isinstance(entity, EntityCandidate)
        assert isinstance(attribute, AttributeAssertionCandidate)
        assert attribute.subject == entity.aliases[0]

    def test_valid_period_is_carried(self) -> None:
        builder = AttributeCandidateBuilder(
            subject=player_builder(),
            attribute_fields=("height_cm",),
            valid_from_field="from",
            valid_to_field="to",
        )
        [candidate] = builder.build(
            record({"id": "42", "height_cm": 180, "from": NOW, "to": None}), context()
        )
        assert isinstance(candidate, AttributeAssertionCandidate)
        assert candidate.valid_period is not None
        assert candidate.valid_period.valid_from == NOW

    def test_valid_time_is_part_of_the_facts_identity(self) -> None:
        """A player's 2024 height and 2025 height are two facts, not one overwritten."""
        builder = AttributeCandidateBuilder(
            subject=player_builder(), attribute_fields=("height_cm",), valid_from_field="from"
        )
        [candidate] = builder.build(
            record({"id": "42", "height_cm": 180, "from": NOW}), context()
        )
        assert candidate.semantic_key == "player/usssa/42/height_cm@2026-07-14T00:00:00+00:00"

    def test_attribute_fields_are_not_required_fields(self) -> None:
        """A null attribute is normal — only the subject's key is non-negotiable."""
        builder = AttributeCandidateBuilder(
            subject=player_builder(), attribute_fields=("height_cm",)
        )
        assert builder.required_fields == ("id",)

    def test_requires_at_least_one_attribute_field(self) -> None:
        with pytest.raises(ConfigurationError):
            AttributeCandidateBuilder(subject=player_builder(), attribute_fields=())


class TestRelationCandidateBuilder:
    def relation(self) -> RelationCandidateBuilder:
        return RelationCandidateBuilder(
            relation_type="PLAYS_FOR",
            subject_type="Player",
            subject_namespace="usssa",
            subject_key_field="player_id",
            object_type="Team",
            object_namespace="usssa",
            object_key_field="team_id",
        )

    def test_builds_a_relation_between_namespaced_refs(self) -> None:
        [candidate] = self.relation().build(
            record({"player_id": "42", "team_id": "7"}), context()
        )
        assert isinstance(candidate, RelationCandidate)
        assert candidate.relation_type == "PLAYS_FOR"
        assert candidate.subject == EntityRef(
            entity_type="Player", namespace="usssa", key="42"
        )
        assert candidate.object == EntityRef(entity_type="Team", namespace="usssa", key="7")

    def test_semantic_key_names_both_endpoints(self) -> None:
        [candidate] = self.relation().build(
            record({"player_id": "42", "team_id": "7"}), context()
        )
        assert candidate.semantic_key == "player/usssa/42/PLAYS_FOR/team/usssa/7"

    def test_endpoints_are_entity_refs_never_bare_label_key(self) -> None:
        """ADR-0008 forbids the bare form and the contract rejects it."""
        [candidate] = self.relation().build(
            record({"player_id": "42", "team_id": "7"}), context()
        )
        assert isinstance(candidate, RelationCandidate)
        assert isinstance(candidate.subject, EntityRef)

    def test_an_empty_endpoint_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            self.relation().build(record({"player_id": "42", "team_id": None}), context())

    def test_declares_both_endpoints_as_required(self) -> None:
        assert self.relation().required_fields == ("player_id", "team_id")

    def test_lowercase_relation_type_is_rejected_by_the_contract(self) -> None:
        builder = RelationCandidateBuilder(
            relation_type="plays_for",
            subject_type="Player",
            subject_namespace="n",
            subject_key_field="a",
            object_type="Team",
            object_namespace="n",
            object_key_field="b",
        )
        with pytest.raises(ValueError, match="UPPER_SNAKE"):
            builder.build(record({"a": "1", "b": "2"}), context())


class TestCompositeCandidateBuilder:
    def test_fans_a_row_out_into_entity_attributes_and_relations(self) -> None:
        entity = player_builder()
        composite = CompositeCandidateBuilder(
            [
                entity,
                AttributeCandidateBuilder(subject=entity, attribute_fields=("height_cm",)),
                RelationCandidateBuilder(
                    relation_type="PLAYS_FOR",
                    subject_type="Player",
                    subject_namespace="usssa",
                    subject_key_field="id",
                    object_type="Team",
                    object_namespace="usssa",
                    object_key_field="team_id",
                ),
            ]
        )
        candidates = composite.build(
            record({"id": "42", "height_cm": 180, "team_id": "7"}), context()
        )
        assert [c.candidate_kind for c in candidates] == [
            "entity",
            "attribute_assertion",
            "relation",
        ]

    def test_output_order_is_builder_order(self) -> None:
        """Duplicate suppression keeps the *first* candidate per key — a wobbly
        order would silently change which one survives."""
        entity = player_builder()
        composite = CompositeCandidateBuilder(
            [AttributeCandidateBuilder(subject=entity, attribute_fields=("h",)), entity]
        )
        candidates = composite.build(record({"id": "1", "h": 1}), context())
        assert [c.candidate_kind for c in candidates] == ["attribute_assertion", "entity"]

    def test_unions_required_fields_without_duplicates(self) -> None:
        entity = player_builder()
        composite = CompositeCandidateBuilder(
            [entity, AttributeCandidateBuilder(subject=entity, attribute_fields=("h",))]
        )
        assert composite.required_fields == ("id",)

    def test_requires_at_least_one_builder(self) -> None:
        with pytest.raises(ConfigurationError):
            CompositeCandidateBuilder([])


class TestNoGraphModelsEscape:
    def test_builders_only_ever_produce_candidates(self) -> None:
        """KGIS holds no graph-write surface; a builder cannot even name a
        CanonicalEntity (spec §6 — the agentic-tskg 0/18 failure)."""
        entity = player_builder()
        composite = CompositeCandidateBuilder(
            [entity, AttributeCandidateBuilder(subject=entity, attribute_fields=("h",))]
        )
        built = composite.build(record({"id": "1", "h": 2}), context())
        assert built
        for candidate in built:
            assert isinstance(candidate, CandidateEnvelope)
            assert not isinstance(candidate, (CanonicalEntity, Assertion))
            assert candidate.candidate_kind in IMPLEMENTED_KINDS

    def test_every_built_candidate_round_trips_through_the_contract_union(self) -> None:
        """If it deserializes as a Candidate, it is one — no structural near-miss."""
        entity = player_builder()
        composite = CompositeCandidateBuilder(
            [entity, AttributeCandidateBuilder(subject=entity, attribute_fields=("h",))]
        )
        for candidate in composite.build(record({"id": "1", "h": 2}), context()):
            revived = candidate_adapter.validate_python(candidate.model_dump(mode="python"))
            assert revived == candidate


class TestDeterminism:
    def test_same_record_same_candidates_byte_for_byte(self) -> None:
        builder = player_builder(property_fields=("bats",))
        source = record({"id": "42", "bats": "L"})
        first = builder.build(source, context())
        second = builder.build(source, context())
        assert first == second

    def test_a_different_run_changes_the_trace_but_not_the_candidate_id(self) -> None:
        """Replay proposes the same candidate; the audit stream still tells the runs apart."""
        builder = player_builder()
        source = record({"id": "42"})
        [first] = builder.build(source, context(producer_run_id="run-1"))
        [second] = builder.build(source, context(producer_run_id="run-2"))
        assert first.candidate_id == second.candidate_id
        assert first.trace_id != second.trace_id


class TestEntitySemanticKey:
    def test_lowercases_the_type(self) -> None:
        alias = EntityRef(entity_type="Player", namespace="usssa", key="42")
        assert entity_semantic_key(alias) == "player/usssa/42"
