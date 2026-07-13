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

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kg_contracts._ulid import new_ulid
from kg_contracts.evidence import EvidenceRef
from kg_contracts.security import new_trace_id
from kg_contracts.versioning import CONTRACT_VERSION


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
