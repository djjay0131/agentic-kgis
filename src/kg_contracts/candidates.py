"""Candidate contracts: the nine-variant union and its shared envelope.

Per spec §5.2 / ADR-0004-as-amended, every extraction/derivation pipeline
produces one of nine candidate variants (entity, relationship, attribute,
assertion, ...; Tasks 9-10 add the variants themselves), all sharing the
`CandidateEnvelope` base defined here.

A single `confidence` float is banned (spec §5.2, disposition A2): an exact
database import is not proof the database's fact is correct, so scoring
must keep orthogonal signals apart rather than collapsing them into one
number. `CandidateScores` is the replacement:

- `extraction_confidence` (required) — did we read the source correctly?
- `source_reliability` (required) — how trustworthy is this source
  historically?
- `identity_confidence`, `assertion_confidence`, `corroboration_score`
  (optional) — start unknown; filled in later by curation (Plans 3/5).
- `policy_risk` — the consequence class of acting on the candidate.

Every model in this module is frozen and `extra="forbid"` — the forbid is
load-bearing: it is what turns a stray `confidence=` keyword argument into
a hard `ValidationError` instead of a silently accepted, unvalidated field.

`CandidateEnvelope` fields are quoted from spec §5.2/§5.8:

- `semantic_key` is the idempotency key: the stable semantic identity of
  the proposed fact (e.g. "traffic/intersection/101"), NOT a hash.
- `content_hash` is a supplementary signal only, not the idempotency
  anchor — `source_coordinates` is (spec §5.8).
- `representations` are named feature views (e.g. "raw_statement",
  "statement_embedding") — never a single generic embedding field, so a
  candidate can carry multiple representations side by side without one
  overwriting another.
"""

import re
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from kg_contracts._ulid import new_ulid
from kg_contracts.derivation import Derivation
from kg_contracts.evidence import EvidenceRef, ValidPeriod
from kg_contracts.identity import (
    _ENTITY_TYPE_PATTERN,
    EntityRef,
    IdentityLinkKind,
    check_aliases_match_entity_type,
    is_identity_id,
)
from kg_contracts.security import new_trace_id
from kg_contracts.versioning import CONTRACT_VERSION

# entity_type: the single source of `_ENTITY_TYPE_PATTERN` is identity.py
# (imported above), so the three sites that share it cannot drift (issue #8).

# relation_type: validated by hand in a model_validator (to raise a custom
# "UPPER_SNAKE" message), so it is compiled and checked with .fullmatch() —
# `$` alone also matches just before a trailing newline in Python's `re`,
# which would let e.g. "PLAYS_FOR\n" slip through.
_RELATION_TYPE_RE = re.compile(r"[A-Z][A-Z0-9_]*")

SubjectRef = EntityRef | str
"""A relation/attribute-assertion subject or object: a namespaced `EntityRef`
or a bare identity-ID string (`kg://<graph-id>/identity/<ulid>`). A bare
`Label:key` string is not accepted here either — see `_validate_subject_ref`.
"""


def _validate_subject_ref(value: SubjectRef) -> SubjectRef:
    """Shared validator for `SubjectRef` fields.

    An `EntityRef` is always valid. A `str` must be a well-formed identity
    ID (`is_identity_id`); anything else — including the deprecated bare
    `Label:key` form — is rejected naming the offending value (ADR-0008).
    """
    if isinstance(value, str) and not is_identity_id(value):
        raise ValueError(f"subject/object string is not a valid identity id: {value!r}")
    return value


class CandidateScores(BaseModel):
    """Multi-dimensional candidate scoring. A single `confidence` is banned.

    `extraction_confidence` and `source_reliability` are required: every
    producer must state both. The remaining scores start unknown
    (`None`) and are filled in later by curation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    extraction_confidence: float = Field(ge=0.0, le=1.0)
    source_reliability: float = Field(ge=0.0, le=1.0)
    identity_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    assertion_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    corroboration_score: float | None = Field(default=None, ge=0.0, le=1.0)
    policy_risk: float = Field(default=0.0, ge=0.0, le=1.0)


class SourceCoordinates(BaseModel):
    """A stable locator into the source: the primary idempotency anchor.

    Row id, document URI, page/span, ... whatever pins this candidate to
    the exact place in the source it came from (spec §5.8).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_type: str
    locator: str
    fragment: str | None = None


class Representation(BaseModel):
    """One named feature view of a candidate: exactly one of text/vector."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["text", "vector"]
    text: str | None = None
    vector: tuple[float, ...] | None = None
    model: str | None = None

    @model_validator(mode="after")
    def _check_payload_matches_kind(self) -> "Representation":
        if self.kind == "text":
            if self.text is None:
                raise ValueError("kind='text' requires text")
            if self.vector is not None:
                raise ValueError("kind='text' forbids vector")
        else:
            if self.vector is None:
                raise ValueError("kind='vector' requires vector")
            if self.text is not None:
                raise ValueError("kind='vector' forbids text")
        return self


class CandidateEnvelope(BaseModel):
    """Shared base of all nine candidate variants (spec §5.2).

    Variants (Tasks 9-10) narrow `candidate_kind` to a `Literal`
    discriminator and add variant-specific fields.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str = Field(default_factory=lambda: "cand_" + new_ulid())
    graph_id: str
    candidate_kind: str
    producer: str
    producer_run_id: str
    contract_version: str = CONTRACT_VERSION
    ontology_version: str
    evidence_refs: tuple[EvidenceRef, ...] = ()
    source_coordinates: SourceCoordinates
    semantic_key: str = Field(min_length=1)
    content_hash: str | None = None
    representations: dict[str, Representation] = Field(default_factory=dict)
    scores: CandidateScores
    trace_id: str = Field(default_factory=new_trace_id)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EntityCandidate(CandidateEnvelope):
    """A proposed entity identity (spec §5.2, disposition D2).

    A proposed identity is *made of* its namespaced aliases — there is no
    bare-ID fallback. `aliases` must be non-empty, and every alias's
    `entity_type` must equal the candidate's own `entity_type`: a candidate
    proposing a `Player` cannot be identified by a `Coach` alias.
    """

    candidate_kind: Literal["entity"] = "entity"
    entity_type: str = Field(pattern=_ENTITY_TYPE_PATTERN)
    aliases: tuple[EntityRef, ...]
    display_name: str | None = None
    properties: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_aliases(self) -> "EntityCandidate":
        check_aliases_match_entity_type(self.aliases, self.entity_type, owner_noun="candidate")
        return self


class RelationCandidate(CandidateEnvelope):
    """A proposed relation between two subjects (spec §5.2, disposition D2).

    `subject`/`object` accept either a namespaced `EntityRef` or an
    already-minted identity-ID string; a bare `Label:key` string is
    rejected (ADR-0008).
    """

    # NB: `properties` is declared before `object` — once a class body binds
    # a field literally named `object`, mypy resolves later bare `object`
    # annotations in that same body to the field, not the builtin type.
    candidate_kind: Literal["relation"] = "relation"
    relation_type: str
    subject: SubjectRef
    properties: dict[str, object] = Field(default_factory=dict)
    object: SubjectRef
    valid_period: ValidPeriod | None = None

    @model_validator(mode="after")
    def _check_relation(self) -> "RelationCandidate":
        if not _RELATION_TYPE_RE.fullmatch(self.relation_type):
            raise ValueError(
                f"relation_type {self.relation_type!r} must be UPPER_SNAKE "
                f"(fullmatch {_RELATION_TYPE_RE.pattern!r})"
            )
        _validate_subject_ref(self.subject)
        _validate_subject_ref(self.object)
        return self


class AttributeAssertionCandidate(CandidateEnvelope):
    """A proposed fact about an entity (spec §5.2, disposition D2).

    Bitemporal-ready via `valid_period`; transaction time is assigned by
    the ledger (Plan 2), not here.
    """

    candidate_kind: Literal["attribute_assertion"] = "attribute_assertion"
    subject: SubjectRef
    attribute: str = Field(min_length=1)
    value: object
    valid_period: ValidPeriod | None = None

    @model_validator(mode="after")
    def _check_subject(self) -> "AttributeAssertionCandidate":
        _validate_subject_ref(self.subject)
        return self


class ArtifactCandidate(CandidateEnvelope):
    """A proposed produced object (spec §5.2, disposition D2).

    An artifact is not a fact about the world (spec §5.2) — it is a
    produced object (e.g. a cut list), identified by its hash and source
    location rather than by an entity identity.
    """

    candidate_kind: Literal["artifact"] = "artifact"
    artifact_type: str
    artifact_hash: str = Field(min_length=1)
    source_uri: str = Field(min_length=1)
    media_type: str | None = None
    derivation: Derivation | None = None


class ObservationCandidate(CandidateEnvelope):
    """SPEC-LEVEL (implemented in Phase 4): a proposed sensor/measurement
    observation.

    Defined now (A2: no breaking union change later) so the nine-way
    `Candidate` union is complete in v1, but only indicative fields plus an
    open `payload` are validated here — full observation semantics
    (units, method vocabularies, value typing) land with Phase 4
    construction.
    """

    candidate_kind: Literal["observation"] = "observation"
    metric: str
    method: str | None = None
    parameters: dict[str, object] = Field(default_factory=dict)
    value: object = None
    payload: dict[str, object] = Field(default_factory=dict)


class DerivedAssertionCandidate(CandidateEnvelope):
    """SPEC-LEVEL (implemented in Phase 4): a proposed assertion computed
    from other canonical records.

    `derivation` is required even at spec level — a derived assertion
    without lineage is meaningless. `conclusion` and `payload` are open
    placeholders; full conclusion typing lands with Phase 4 construction.
    """

    candidate_kind: Literal["derived_assertion"] = "derived_assertion"
    derivation: Derivation
    conclusion: dict[str, object] = Field(default_factory=dict)
    payload: dict[str, object] = Field(default_factory=dict)


class PlanCandidate(CandidateEnvelope):
    """SPEC-LEVEL (implemented in Phase 4): a proposed generated plan.

    A generated cut list is not a fact about the building — `objective`
    and `inputs` are indicative fields only; full plan semantics land
    with Phase 4 construction.
    """

    candidate_kind: Literal["plan"] = "plan"
    objective: str
    inputs: tuple[str, ...] = ()
    payload: dict[str, object] = Field(default_factory=dict)


class OntologyCandidate(CandidateEnvelope):
    """SPEC-LEVEL (enters the §7.3 PROPOSED→APPROVED lifecycle; wired in
    Plan 3): a proposed ontology term.

    `term_kind` names what is being proposed (an entity type, relation
    type, or attribute); full lifecycle wiring — the PROPOSED→APPROVED
    workflow itself — lands in Plan 3.
    """

    candidate_kind: Literal["ontology"] = "ontology"
    term_kind: Literal["entity_type", "relation_type", "attribute"]
    term: str
    definition: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)


class IdentityLinkCandidate(CandidateEnvelope):
    """SPEC-LEVEL (implemented in Phase 3 retrofit): a proposed cross-graph
    identity link.

    Placeholder validation only: `left`/`right` must be non-empty strings.
    Full endpoint validation (well-formed identity IDs, graph membership)
    lands with the Phase 3 retrofit implementation.
    """

    candidate_kind: Literal["identity_link"] = "identity_link"
    left: str = Field(min_length=1)
    right: str = Field(min_length=1)
    kind: IdentityLinkKind
    payload: dict[str, object] = Field(default_factory=dict)


Candidate = Annotated[
    EntityCandidate
    | RelationCandidate
    | AttributeAssertionCandidate
    | ObservationCandidate
    | DerivedAssertionCandidate
    | ArtifactCandidate
    | PlanCandidate
    | OntologyCandidate
    | IdentityLinkCandidate,
    Field(discriminator="candidate_kind"),
]
"""The nine-variant discriminated union (spec §5.2), keyed on
`candidate_kind`. Four variants are implemented in v1
(`IMPLEMENTED_KINDS`); the remaining five are spec-level (A2/D2)."""

CANDIDATE_KINDS: frozenset[str] = frozenset(
    {
        "entity",
        "relation",
        "attribute_assertion",
        "observation",
        "derived_assertion",
        "artifact",
        "plan",
        "ontology",
        "identity_link",
    }
)
"""All nine candidate-kind strings — the full spec §5.2 union, whether or
not a given kind is implemented by v1 pipelines."""

IMPLEMENTED_KINDS: frozenset[str] = frozenset(
    {"entity", "relation", "attribute_assertion", "artifact"}
)
"""The kinds v1 pipelines actually accept. Admission (KGCS) rejects the
other five spec-level kinds with "defined but not implemented in v1"
rather than a validation error — they are well-formed contracts, just not
yet wired to a producer."""

candidate_adapter: TypeAdapter[Candidate] = TypeAdapter(Candidate)
"""Module-level `TypeAdapter` for deserializing ledger rows / wire
payloads into the correct `Candidate` variant via `candidate_kind`."""
