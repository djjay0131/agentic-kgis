"""Canonical-graph records: bitemporal assertions, entities, conflicts.

ADR-0006 (three-store separation, spec §3.2): the candidate ledger (Task 14)
holds uncertain, replayable proposals with their own processing state;
this module models the *canonical graph* only — accepted identities and
assertions, with explicit validity, scores, and provenance. There is
deliberately **no `PROVISIONAL` status here**: uncertainty is a ledger
concern, not a canonical-graph concern. `CurationStatus` is a three-value
lifecycle (`ACTIVE`/`SUPERSEDED`/`REVOKED`) once a record has been
accepted into the canonical graph.

Every `Assertion` is bitemporal (spec §5.4): `valid_period` is domain
valid time (when the fact is true in the world), while `recorded_at` /
`superseded_at` are transaction time (when the system learned or retired
it). Curation status attaches at the assertion level, not only the whole
entity, so an entity can be certain while one of its properties is
uncertain (spec §5.4). Immutability here is attribute-level only:
`frozen=True` blocks reassigning a field after construction but cannot
stop in-place mutation of a mutable field's contents (e.g. a `dict`/`list`
value). Supersession is performed by writing a new record and setting
`superseded_at` on a copy of the old one; that write is owned by KGCS
executors (Plan 3), not by this contract. Immutability of accepted records
at rest (append-only, no in-place edits) is likewise the ledger/store
layer's responsibility (Plan 2/3), not these models'.

`authority` (who is entitled to assert this) is recorded separately from
every score in `CandidateScores` (spec §7.5): a deterministic sync at high
extraction confidence may still carry stale or wrong data if the source
was never entitled to assert it. `ConflictRecord` preserves competing
assertions rather than overwriting them (spec §7.5): both sides, their
evidence, and their valid periods survive; only `preferred_assertion_id`
and `status` record the current resolution.
"""

import re
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kg_contracts._ulid import new_ulid
from kg_contracts.candidates import CandidateScores
from kg_contracts.derivation import Derivation
from kg_contracts.evidence import EvidenceRef, Provenance, ValidPeriod
from kg_contracts.identity import (
    _ENTITY_TYPE_PATTERN,
    EntityRef,
    check_aliases_match_entity_type,
    is_identity_id,
)

# An assertion id is the `as_` prefix followed by a 26-char Crockford-base32
# ULID (the same alphabet `_ulid.new_ulid` emits: no I, L, O or U). This is
# the counterpart to `identity.is_identity_id` that ADR-0028 flagged as
# missing; `Assertion.superseded_by` is the first field that must name a
# well-formed assertion id.
_ASSERTION_ID_RE = re.compile(r"as_[0-9A-HJKMNP-TV-Z]{26}")


def is_assertion_id(value: str) -> bool:
    """Return True iff `value` is a well-formed assertion id (`as_` + ULID)."""
    return bool(_ASSERTION_ID_RE.fullmatch(value))


class CurationStatus(StrEnum):
    """Canonical-graph lifecycle only (ADR-0006). No `PROVISIONAL` value:
    uncertain records never enter the canonical graph in the first place —
    they live on the candidate ledger (Task 14) instead.
    """

    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class CanonicalEntity(BaseModel):
    """An accepted identity in the canonical graph (spec §3.2).

    Made of its namespaced `aliases`, mirroring `EntityCandidate`: aliases
    must be non-empty and every alias's `entity_type` must match the
    entity's own `entity_type`. `status` covers the *entity* lifecycle;
    individual `Assertion`s about this entity carry their own status too
    (spec §5.4) — an entity can be `ACTIVE` while one of its assertions is
    `SUPERSEDED` or `REVOKED`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    identity_id: str
    entity_type: str = Field(pattern=_ENTITY_TYPE_PATTERN)
    aliases: tuple[EntityRef, ...]
    status: CurationStatus = CurationStatus.ACTIVE
    display_name: str | None = None
    created_at: datetime
    curation_epoch: int

    @model_validator(mode="after")
    def _check_identity_and_aliases(self) -> "CanonicalEntity":
        if not is_identity_id(self.identity_id):
            raise ValueError(f"identity_id is not a valid identity id: {self.identity_id!r}")
        check_aliases_match_entity_type(self.aliases, self.entity_type, owner_noun="entity")
        return self


class Assertion(BaseModel):
    """A single bitemporal fact in the canonical graph (spec §5.4, §7.5).

    Bitemporal: `valid_period` is domain valid time; `recorded_at` and
    `superseded_at` are transaction time. Exactly one of `object_value` /
    `object_identity` must be set — attribute-style facts set
    `object_value`, relation-style facts point at another identity via
    `object_identity` (which must itself be a well-formed identity id).
    `authority` (who is entitled to assert this) is separate from every
    field on `scores`. Immutability here is attribute-level (fields cannot be
    reassigned after construction); supersession writes a new record via a
    copy with `superseded_at` set, performed by KGCS executors (Plan 3), not
    by this contract. Append-only immutability of records at rest is the
    ledger/store layer's responsibility (Plan 2/3), not this model's.

    Two lineage pointers (ADR-0028) are carried as read-only provenance
    metadata, deliberately **outside** the ADR-0021 record seed so adding or
    changing either never re-mints a record id:

    - `source_candidate_ids` names the candidate(s) this record was planned
      from. It is a set-like list: order is the caller's deterministic
      (first-seen) order, duplicates are rejected, and an empty tuple is the
      honest null for a record with no candidate origin (an evolved record).
    - `superseded_by` names the record that replaced this one. It is a
      **partial** invariant: when set, `status` must be `SUPERSEDED`,
      `superseded_at` must be set, and the id must be well-formed. The
      converse is deliberately not required — a `SUPERSEDED` record may carry
      `superseded_by = None` for retirements with no single successor (an
      identity merge, or the non-injective ADR-0021 re-id backfill).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    assertion_id: str = Field(default_factory=lambda: "as_" + new_ulid())
    subject_identity: str
    predicate: str = Field(min_length=1)
    object_value: object | None
    object_identity: str | None
    status: CurationStatus
    valid_period: ValidPeriod
    recorded_at: datetime
    superseded_at: datetime | None = None
    scores: CandidateScores
    evidence_refs: tuple[EvidenceRef, ...]
    authority: str = Field(min_length=1)
    provenance: Provenance
    derivation: Derivation | None = None
    curation_epoch: int
    trace_id: str
    source_candidate_ids: tuple[str, ...] = ()
    superseded_by: str | None = None

    @model_validator(mode="after")
    def _check_subject_and_object(self) -> "Assertion":
        if not is_identity_id(self.subject_identity):
            raise ValueError(
                f"subject_identity is not a valid identity id: {self.subject_identity!r}"
            )
        object_fields_set = sum(
            1 for v in (self.object_value, self.object_identity) if v is not None
        )
        if object_fields_set != 1:
            raise ValueError(
                "exactly one of object_value/object_identity must be set "
                f"(got object_value={self.object_value!r}, "
                f"object_identity={self.object_identity!r})"
            )
        if self.object_identity is not None and not is_identity_id(self.object_identity):
            raise ValueError(
                f"object_identity is not a valid identity id: {self.object_identity!r}"
            )
        return self

    @model_validator(mode="after")
    def _check_lineage_pointers(self) -> "Assertion":
        seen: set[str] = set()
        for candidate_id in self.source_candidate_ids:
            if candidate_id in seen:
                raise ValueError(f"source_candidate_ids contains a duplicate: {candidate_id!r}")
            seen.add(candidate_id)
        if self.superseded_by is not None:
            if self.status is not CurationStatus.SUPERSEDED:
                raise ValueError(
                    "superseded_by is set, so status must be SUPERSEDED "
                    f"(got {self.status!r})"
                )
            if self.superseded_at is None:
                raise ValueError("superseded_by is set, so superseded_at must be set")
            if not is_assertion_id(self.superseded_by):
                raise ValueError(
                    f"superseded_by is not a valid assertion id: {self.superseded_by!r}"
                )
        return self


class ConflictStatus(StrEnum):
    """Whether a `ConflictRecord` has a current preferred assertion."""

    UNRESOLVED = "UNRESOLVED"
    RESOLVED = "RESOLVED"


class ConflictRecord(BaseModel):
    """A preserved conflict between competing assertions (spec §7.5).

    Competing assertions are never overwritten — both (or all) survive as
    ordinary `Assertion` records, and this record tracks which one is
    currently preferred, if any. `preferred_assertion_id` and `status` are
    two faces of one fact, so the model enforces a strict biconditional and
    makes any inconsistent pairing unrepresentable:

    - `preferred_assertion_id is None` ⟺ `status is UNRESOLVED`
    - `preferred_assertion_id is not None` ⟺ `status is RESOLVED`, and the
      preferred id must be one of `assertion_ids`.

    A `RESOLVED` record therefore always names its winner and an
    `UNRESOLVED` record never carries a dangling preference — neither
    `RESOLVED`-without-a-preference nor `UNRESOLVED`-with-a-preference can
    be constructed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    conflict_id: str = Field(default_factory=lambda: "cf_" + new_ulid())
    assertion_ids: tuple[str, ...] = Field(min_length=2)
    preferred_assertion_id: str | None
    resolution_policy: str | None
    status: ConflictStatus

    @model_validator(mode="after")
    def _check_preferred_and_status(self) -> "ConflictRecord":
        if self.preferred_assertion_id is None:
            if self.status is not ConflictStatus.UNRESOLVED:
                raise ValueError(
                    "preferred_assertion_id is unset, so status must be UNRESOLVED "
                    f"(got {self.status!r})"
                )
        else:
            if self.status is not ConflictStatus.RESOLVED:
                raise ValueError(
                    "preferred_assertion_id is set, so status must be RESOLVED "
                    f"(got {self.status!r})"
                )
            if self.preferred_assertion_id not in self.assertion_ids:
                raise ValueError(
                    f"preferred_assertion_id {self.preferred_assertion_id!r} "
                    "is not a member of assertion_ids"
                )
        return self
