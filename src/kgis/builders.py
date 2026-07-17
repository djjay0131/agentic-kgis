"""Candidate creation: `NormalizedRecord` → `Candidate`. The last `kgis` stage.

No graph model appears in this layer, and none ever may. A builder produces
`EntityCandidate` / `RelationCandidate` / `AttributeAssertionCandidate` —
*proposals*. It cannot produce a `CanonicalEntity` or an `Assertion`, because
those are things the curation service decides, not things an ingest asserts.
That is the agentic-tskg 0/18 failure made structurally impossible (spec §6):
KGIS holds no graph-write surface, so there is no "helpful" direct upsert to
reach for.

Three decisions worth stating plainly:

**`source_reliability` has no default.** Per ADR-0004 as amended, a
deterministic read of a source is not evidence the source is *right*:
`extraction_confidence=1.0` is legitimate for an exact CSV read, while
`source_reliability` is scored on its own, honest axis. Making it a required
field is how that stays true — a caller must state what the source is worth,
and cannot accidentally inherit a flattering default. The remaining scores
(`identity_confidence`, `assertion_confidence`, `corroboration_score`) start
`None`: unknown, for curation to fill in later. Not zero, not one.

**A null value produces no candidate.** If a row's `height_cm` is empty, the
builder emits nothing for it — it does not emit an assertion that the height
*is* null. Absence of evidence is not evidence of absence (spec §5.3), and an
`AttributeAssertionCandidate` has no way to say "we looked and found
nothing"; that is what `Evidence`'s ABSENT state is for, and it arrives with
the evidence registry in Plan 2.

**`semantic_key` is the fact's identity, and it is derived, not hashed.**
Spec §5.8: idempotency rides on stable source coordinates and semantic keys,
with content hashes as a *supplementary* signal only — a hash changes when
the wording changes, which is exactly when you least want a duplicate. So the
key is composed (`player/usssa/42/height_cm`) and the `content_hash` rides
along beside it for change detection.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol, Sequence, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from kg_contracts.candidates import (
    AttributeAssertionCandidate,
    Candidate,
    CandidateScores,
    EntityCandidate,
    RelationCandidate,
)
from kg_contracts.evidence import ValidPeriod
from kg_contracts.identity import EntityRef
from kgis.clock import Clock
from kgis.errors import ConfigurationError, RecordDataError
from kgis.ids import IdStrategy
from kgis.records import NormalizedRecord


class SourceScoring(BaseModel):
    """What a structured source claims for the candidates it produces.

    `source_reliability` is required on purpose (ADR-0004 as amended). A
    perfect read of an unreliable source is still just a perfect read of an
    unreliable source, and a default here would let that distinction quietly
    evaporate.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_reliability: float = Field(ge=0.0, le=1.0)
    extraction_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    """Legitimately 1.0 for an exact structured read: we are certain we read
    the row correctly. This says nothing about whether the row is true."""

    policy_risk: float = Field(default=0.0, ge=0.0, le=1.0)

    def to_scores(self) -> CandidateScores:
        """The full score set. The unknown axes stay `None` — honest nulls that
        curation fills in later, never zeros that a policy would read as
        'scored low'."""
        return CandidateScores(
            extraction_confidence=self.extraction_confidence,
            source_reliability=self.source_reliability,
            policy_risk=self.policy_risk,
        )


@dataclass(frozen=True)
class BuildContext:
    """The per-run facts every candidate needs, injected at build time.

    Passed to `build()` rather than held on the builder so that builders are
    stateless and reusable across runs: the *run* owns its identity, clock,
    and ID strategy, and a builder configured once can serve any of them.
    """

    graph_id: str
    producer: str
    producer_run_id: str
    ontology_version: str
    scoring: SourceScoring
    clock: Clock
    ids: IdStrategy


@runtime_checkable
class CandidateBuilder(Protocol):
    """Turns one validated record into zero or more candidates (spec §6)."""

    @property
    def required_fields(self) -> tuple[str, ...]:
        """Fields this builder cannot work without.

        Declared rather than discovered so the pipeline *does* wire a
        `RequiredValuesValidator` for them automatically and reject the
        record before construction — and so a builder pointed at a field
        the normalizer never produces fails at assembly, not silently at
        row 40,000.
        """
        ...

    def build(self, record: NormalizedRecord, context: BuildContext) -> Sequence[Candidate]:
        """Build candidates. Only ever called with a record that passed validation."""
        ...


def _content_hash(payload: object) -> str:
    """A supplementary change-detection signal, never the idempotency anchor
    (spec §5.8). Sorted keys so it is stable across dict orderings."""
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return "b2:" + hashlib.blake2b(encoded, digest_size=16).hexdigest()


def _text(record: NormalizedRecord, field: str) -> str | None:
    """Read `field` as a non-empty string, or `None`."""
    value = record.values.get(field)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _valid_period(
    record: NormalizedRecord, valid_from_field: str | None, valid_to_field: str | None
) -> ValidPeriod | None:
    if valid_from_field is None and valid_to_field is None:
        return None
    valid_from = record.values.get(valid_from_field) if valid_from_field else None
    valid_to = record.values.get(valid_to_field) if valid_to_field else None
    if valid_from is None and valid_to is None:
        return None
    period = ValidPeriod.model_validate({"valid_from": valid_from, "valid_to": valid_to})
    return period


def _period_suffix(period: ValidPeriod | None) -> str:
    """Valid-time is part of a fact's identity: a player's 2024 height and their
    2025 height are two facts, not one fact overwritten."""
    if period is None or period.valid_from is None:
        return ""
    return f"@{period.valid_from.isoformat()}"


class EntityCandidateBuilder:
    """Row → one `EntityCandidate`.

    `entity_type` is either fixed for the whole source, or read per-row from
    `entity_type_field` (a source with a `type` column). Exactly one of the two.

    `properties` are inline descriptive values carried on the identity itself.
    Facts about the entity that deserve evidence, valid-time, and independent
    curation belong in `AttributeCandidateBuilder` instead — an
    `AttributeAssertionCandidate` is a first-class bitemporal claim, an entity
    property is not.
    """

    def __init__(
        self,
        *,
        namespace: str,
        key_field: str,
        entity_type: str | None = None,
        entity_type_field: str | None = None,
        display_name_field: str | None = None,
        property_fields: Sequence[str] = (),
    ) -> None:
        if (entity_type is None) == (entity_type_field is None):
            raise ConfigurationError(
                "EntityCandidateBuilder requires exactly one of entity_type= or entity_type_field="
            )
        self._namespace = namespace
        self._key_field = key_field
        self._entity_type = entity_type
        self._entity_type_field = entity_type_field
        self._display_name_field = display_name_field
        self._property_fields = tuple(property_fields)

    @property
    def required_fields(self) -> tuple[str, ...]:
        if self._entity_type_field is not None:
            return (self._key_field, self._entity_type_field)
        return (self._key_field,)

    def entity_ref(self, record: NormalizedRecord) -> EntityRef:
        """The namespaced alias this row identifies. Shared with the other builders,
        so a relation's subject and the entity it points at cannot drift apart."""
        key = _text(record, self._key_field)
        if key is None:
            raise RecordDataError(f"entity key field {self._key_field!r} is empty")
        entity_type = self._resolve_entity_type(record)
        return EntityRef(entity_type=entity_type, namespace=self._namespace, key=key)

    def _resolve_entity_type(self, record: NormalizedRecord) -> str:
        if self._entity_type is not None:
            return self._entity_type
        assert self._entity_type_field is not None  # guaranteed by the constructor
        entity_type = _text(record, self._entity_type_field)
        if entity_type is None:
            raise RecordDataError(f"entity type field {self._entity_type_field!r} is empty")
        return entity_type

    def build(self, record: NormalizedRecord, context: BuildContext) -> Sequence[Candidate]:
        alias = self.entity_ref(record)
        semantic_key = entity_semantic_key(alias)
        properties = {
            field: record.values[field]
            for field in self._property_fields
            # A null property is not a property. See the module docstring: we
            # do not assert that a value *is* null.
            if record.values.get(field) is not None
        }
        return [
            EntityCandidate(
                candidate_id=context.ids.candidate_id(
                    graph_id=context.graph_id,
                    candidate_kind="entity",
                    semantic_key=semantic_key,
                ),
                graph_id=context.graph_id,
                producer=context.producer,
                producer_run_id=context.producer_run_id,
                ontology_version=context.ontology_version,
                source_coordinates=record.coordinates,
                semantic_key=semantic_key,
                content_hash=_content_hash(
                    {"alias": alias.render(), "properties": properties}
                ),
                scores=context.scoring.to_scores(),
                trace_id=context.ids.trace_id(
                    run_id=context.producer_run_id,
                    graph_id=context.graph_id,
                    candidate_kind="entity",
                    semantic_key=semantic_key,
                ),
                created_at=context.clock.now(),
                entity_type=alias.entity_type,
                aliases=(alias,),
                display_name=(
                    _text(record, self._display_name_field)
                    if self._display_name_field is not None
                    else None
                ),
                properties=properties,
            )
        ]


class AttributeCandidateBuilder:
    """Row → one `AttributeAssertionCandidate` per non-null attribute field.

    The subject is the same `EntityRef` the `EntityCandidateBuilder` would
    mint for this row — the two builders share `subject` so an attribute can
    never end up hanging off an entity the ingest did not also propose.
    """

    def __init__(
        self,
        *,
        subject: EntityCandidateBuilder,
        attribute_fields: Sequence[str],
        valid_from_field: str | None = None,
        valid_to_field: str | None = None,
    ) -> None:
        if not attribute_fields:
            raise ConfigurationError("AttributeCandidateBuilder requires attribute_fields")
        self._subject = subject
        self._attribute_fields = tuple(attribute_fields)
        self._valid_from_field = valid_from_field
        self._valid_to_field = valid_to_field

    @property
    def required_fields(self) -> tuple[str, ...]:
        # The attribute fields themselves are NOT required: a null one simply
        # produces no candidate. Only the subject's key is non-negotiable.
        return self._subject.required_fields

    def build(self, record: NormalizedRecord, context: BuildContext) -> Sequence[Candidate]:
        alias = self._subject.entity_ref(record)
        period = _valid_period(record, self._valid_from_field, self._valid_to_field)
        subject_key = entity_semantic_key(alias)

        candidates: list[Candidate] = []
        for attribute in self._attribute_fields:
            value = record.values.get(attribute)
            if value is None:
                continue  # No fact to assert. See the module docstring.
            semantic_key = f"{subject_key}/{attribute}{_period_suffix(period)}"
            candidates.append(
                AttributeAssertionCandidate(
                    candidate_id=context.ids.candidate_id(
                        graph_id=context.graph_id,
                        candidate_kind="attribute_assertion",
                        semantic_key=semantic_key,
                    ),
                    graph_id=context.graph_id,
                    producer=context.producer,
                    producer_run_id=context.producer_run_id,
                    ontology_version=context.ontology_version,
                    source_coordinates=record.coordinates,
                    semantic_key=semantic_key,
                    content_hash=_content_hash({"attribute": attribute, "value": value}),
                    scores=context.scoring.to_scores(),
                    trace_id=context.ids.trace_id(
                        run_id=context.producer_run_id,
                        graph_id=context.graph_id,
                        candidate_kind="attribute_assertion",
                        semantic_key=semantic_key,
                    ),
                    created_at=context.clock.now(),
                    subject=alias,
                    attribute=attribute,
                    value=value,
                    valid_period=period,
                )
            )
        return candidates


class RelationCandidateBuilder:
    """Row → one `RelationCandidate` between two namespaced entity refs.

    Both endpoints are `EntityRef`s, never bare `Label:key` strings — ADR-0008
    forbids the latter outright, and the contract rejects them.
    """

    def __init__(
        self,
        *,
        relation_type: str,
        subject_type: str,
        subject_namespace: str,
        subject_key_field: str,
        object_type: str,
        object_namespace: str,
        object_key_field: str,
        property_fields: Sequence[str] = (),
        valid_from_field: str | None = None,
        valid_to_field: str | None = None,
    ) -> None:
        self._relation_type = relation_type
        self._subject_type = subject_type
        self._subject_namespace = subject_namespace
        self._subject_key_field = subject_key_field
        self._object_type = object_type
        self._object_namespace = object_namespace
        self._object_key_field = object_key_field
        self._property_fields = tuple(property_fields)
        self._valid_from_field = valid_from_field
        self._valid_to_field = valid_to_field

    @property
    def required_fields(self) -> tuple[str, ...]:
        return (self._subject_key_field, self._object_key_field)

    def build(self, record: NormalizedRecord, context: BuildContext) -> Sequence[Candidate]:
        subject = self._ref(
            record, self._subject_key_field, self._subject_type, self._subject_namespace
        )
        target = self._ref(
            record, self._object_key_field, self._object_type, self._object_namespace
        )
        period = _valid_period(record, self._valid_from_field, self._valid_to_field)
        semantic_key = (
            f"{entity_semantic_key(subject)}/{self._relation_type}/"
            f"{entity_semantic_key(target)}{_period_suffix(period)}"
        )
        properties = {
            field: record.values[field]
            for field in self._property_fields
            if record.values.get(field) is not None
        }
        return [
            RelationCandidate(
                candidate_id=context.ids.candidate_id(
                    graph_id=context.graph_id,
                    candidate_kind="relation",
                    semantic_key=semantic_key,
                ),
                graph_id=context.graph_id,
                producer=context.producer,
                producer_run_id=context.producer_run_id,
                ontology_version=context.ontology_version,
                source_coordinates=record.coordinates,
                semantic_key=semantic_key,
                content_hash=_content_hash(
                    {
                        "subject": subject.render(),
                        "relation": self._relation_type,
                        "object": target.render(),
                        "properties": properties,
                    }
                ),
                scores=context.scoring.to_scores(),
                trace_id=context.ids.trace_id(
                    run_id=context.producer_run_id,
                    graph_id=context.graph_id,
                    candidate_kind="relation",
                    semantic_key=semantic_key,
                ),
                created_at=context.clock.now(),
                relation_type=self._relation_type,
                subject=subject,
                object=target,
                properties=properties,
                valid_period=period,
            )
        ]

    def _ref(
        self, record: NormalizedRecord, field: str, entity_type: str, namespace: str
    ) -> EntityRef:
        key = _text(record, field)
        if key is None:
            raise RecordDataError(f"relation endpoint field {field!r} is empty")
        return EntityRef(entity_type=entity_type, namespace=namespace, key=key)


class CompositeCandidateBuilder:
    """Fans one record out across several builders — a row becomes an entity,
    its attributes, and its relations in one pass.

    Output order is builder order, then each builder's own order. Determinism
    is not decoration here: the pipeline's intra-run duplicate suppression
    keeps the *first* candidate for a semantic key, so a wobbly order would
    silently change which one survives.
    """

    def __init__(self, builders: Sequence[CandidateBuilder]) -> None:
        if not builders:
            raise ConfigurationError("CompositeCandidateBuilder requires at least one builder")
        self._builders = tuple(builders)

    @property
    def builders(self) -> tuple[CandidateBuilder, ...]:
        return self._builders

    @property
    def required_fields(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for builder in self._builders:
            for field in builder.required_fields:
                seen[field] = None
        return tuple(seen)

    def build(self, record: NormalizedRecord, context: BuildContext) -> Sequence[Candidate]:
        candidates: list[Candidate] = []
        for builder in self._builders:
            candidates.extend(builder.build(record, context))
        return candidates


def entity_semantic_key(alias: EntityRef) -> str:
    """The stable semantic identity of an entity: `type/namespace/key`.

    Lower-cased type, matching the spec's `traffic/intersection/101` example.
    This is a *composed* key, deliberately not a hash — see the module docstring.
    """
    return f"{alias.entity_type.lower()}/{alias.namespace}/{alias.key}"
