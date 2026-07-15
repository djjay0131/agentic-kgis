"""Shared builders for the pipeline and invariant suites.

Kept in a plain module (not `conftest.py`) so test files can *import* these
helpers directly — pytest puts this directory on `sys.path`, so
`from scenarios import build_pipeline` resolves without any package wiring.
conftest.py holds only fixtures.

`build_pipeline` is the single place a fully-wired deterministic pipeline is
assembled, so a test states only what it cares about (the source, an
ontology, a strictness flag) and inherits a `FixedClock` +
`DeterministicIdStrategy` everywhere else. Determinism is the default here
precisely because most tests check something other than timing or id-shape.
"""

from datetime import UTC, datetime
from typing import Sequence

from kg_contracts.testing.memory import MemoryCandidateSink
from kgis.builders import (
    AttributeCandidateBuilder,
    CandidateBuilder,
    CompositeCandidateBuilder,
    EntityCandidateBuilder,
    RelationCandidateBuilder,
    SourceScoring,
)
from kgis.clock import FixedClock
from kgis.ids import DeterministicIdStrategy
from kgis.normalize import FieldSpec, SchemaNormalizer
from kgis.ontology import Ontology
from kgis.pipeline import IngestPipeline
from kgis.sources.base import RecordReader
from kgis.sources.iterable_reader import IterableRecordReader

NOW = datetime(2026, 7, 14, tzinfo=UTC)

PLAYERS: tuple[dict[str, str], ...] = (
    {"id": "1", "name": "Ada", "team": "10", "height_cm": "170"},
    {"id": "2", "name": "Grace", "team": "10", "height_cm": "175"},
    {"id": "3", "name": "Alan", "team": "20", "height_cm": "180"},
)


def player_schema() -> SchemaNormalizer:
    return SchemaNormalizer(
        [
            FieldSpec(name="id", type="str", required=True),
            FieldSpec(name="name", type="str"),
            FieldSpec(name="team", type="str"),
            FieldSpec(name="height_cm", type="int"),
        ]
    )


def player_builder() -> CompositeCandidateBuilder:
    entity = EntityCandidateBuilder(
        entity_type="Player", namespace="usssa", key_field="id", display_name_field="name"
    )
    attributes = AttributeCandidateBuilder(subject=entity, attribute_fields=("height_cm",))
    relation = RelationCandidateBuilder(
        relation_type="PLAYS_FOR",
        subject_type="Player",
        subject_namespace="usssa",
        subject_key_field="id",
        object_type="Team",
        object_namespace="usssa",
        object_key_field="team",
    )
    return CompositeCandidateBuilder([entity, attributes, relation])


def baseball_ontology() -> Ontology:
    return Ontology(
        version="1",
        entity_types=frozenset({"Player", "Team"}),
        relation_types=frozenset({"PLAYS_FOR"}),
        attributes=frozenset({"height_cm"}),
    )


def build_pipeline(
    *,
    reader: RecordReader | None = None,
    records: Sequence[dict[str, str]] = PLAYERS,
    builder: CandidateBuilder | None = None,
    ontology: Ontology | None = None,
    ontology_strict: bool = True,
    sink: MemoryCandidateSink | None = None,
    **overrides: object,
) -> IngestPipeline:
    # Deterministic defaults a test may override (e.g. a ticking clock);
    # `overrides` wins, so these are set only when the caller did not.
    defaults: dict[str, object] = {
        "clock": FixedClock(NOW),
        "ids": DeterministicIdStrategy(),
        "job_id": "job-fixed",
    }
    return IngestPipeline(
        graph_id="baseball",
        reader=reader if reader is not None else IterableRecordReader(records),
        normalizer=player_schema(),
        builder=builder if builder is not None else player_builder(),
        sink=sink if sink is not None else MemoryCandidateSink(),
        scoring=SourceScoring(source_reliability=0.8),
        ontology=ontology,
        ontology_strict=ontology_strict,
        **{**defaults, **overrides},  # type: ignore[arg-type]
    )
