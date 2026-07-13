"""First-class evidence contract (spec §5.3).

Evidence is never silently dropped: availability is always one of PRESENT,
ABSENT, or ERROR, and each state carries the information that explains it
(content/hash, an absence reason, or an error message respectively). This
keeps "no source queried", "source omitted it", "source unavailable",
"sources contradict", and "source states unknown" distinct from each other
and from a genuinely present fact — so an LLM reading graph context can't
mistake absent data for an inferred fact (Phase-0 lesson, vttsi-evidence).

Evidence IDs are deterministic and citable by default (`source:key@window`)
so re-collection is idempotent; callers may supply their own `evidence_id`,
and a random ULID-based ID is only a fallback for one-off evidence.

The constructor helpers (`present_evidence`, `absent_evidence`,
`error_evidence`) make an invalid availability combination unrepresentable
at call sites, not just rejected by a validator.

Storage and providers that produce `Evidence` live in `kgis` (Plan 2); this
module only defines the contract.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kg_contracts._ulid import new_ulid


class ValidPeriod(BaseModel):
    """Domain valid-time interval.

    Shared by Evidence, assertion candidates (Task 9), and assertions
    (Task 11). Open-ended on either side; `valid_from <= valid_to` when
    both are set.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    valid_from: datetime | None = None
    valid_to: datetime | None = None

    @model_validator(mode="after")
    def _check_ordering(self) -> "ValidPeriod":
        if (
            self.valid_from is not None
            and self.valid_to is not None
            and self.valid_from > self.valid_to
        ):
            raise ValueError("valid_from must be <= valid_to")
        return self


class Provenance(BaseModel):
    """Where a record came from. Never dropped."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str
    source_ref: str | None = None
    actor: str
    model: str | None = None
    prompt_version: str | None = None


class EvidenceAvailability(StrEnum):
    """Whether evidence content is actually present."""

    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    ERROR = "ERROR"


class AbsenceReason(StrEnum):
    """Why evidence is absent, distinguishing the flavors of "no data"."""

    NOT_QUERIED = "NOT_QUERIED"
    SOURCE_OMITTED = "SOURCE_OMITTED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    SOURCES_CONTRADICT = "SOURCES_CONTRADICT"
    SOURCE_STATES_UNKNOWN = "SOURCE_STATES_UNKNOWN"


class Evidence(BaseModel):
    """A single piece of evidence, with explicit availability.

    Cross-field rules (enforced below): each state requires its own field
    and excludes the other states' fields, mirroring the constructor
    helpers' parameter surfaces. PRESENT requires `content` or
    `payload_hash` and forbids `absence_reason`/`error`; ABSENT requires
    `absence_reason` and forbids `content`/`payload_hash`/`error`; ERROR
    requires `error` and forbids `content`/`payload_hash`/`absence_reason`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: str = Field(default_factory=lambda: "ev_" + new_ulid())
    source_type: str
    source_locator: str
    observed_at: datetime
    valid_time: ValidPeriod | None = None
    availability: EvidenceAvailability
    absence_reason: AbsenceReason | None = None
    payload_hash: str | None = None
    content: str | None = None
    error: str | None = None
    provenance: Provenance

    @model_validator(mode="after")
    def _check_availability_shape(self) -> "Evidence":
        if self.availability is EvidenceAvailability.PRESENT:
            if self.content is None and self.payload_hash is None:
                raise ValueError("PRESENT evidence requires content or payload_hash")
            if self.absence_reason is not None:
                raise ValueError("PRESENT evidence forbids absence_reason")
            if self.error is not None:
                raise ValueError("PRESENT evidence forbids error")
        elif self.availability is EvidenceAvailability.ABSENT:
            if self.absence_reason is None:
                raise ValueError("ABSENT evidence requires absence_reason")
            if self.content is not None:
                raise ValueError("ABSENT evidence forbids content")
            if self.payload_hash is not None:
                raise ValueError("ABSENT evidence forbids payload_hash")
            if self.error is not None:
                raise ValueError("ABSENT evidence forbids error")
        elif self.availability is EvidenceAvailability.ERROR:
            if self.error is None:
                raise ValueError("ERROR evidence requires error")
            if self.content is not None:
                raise ValueError("ERROR evidence forbids content")
            if self.payload_hash is not None:
                raise ValueError("ERROR evidence forbids payload_hash")
            if self.absence_reason is not None:
                raise ValueError("ERROR evidence forbids absence_reason")
        return self


class EvidenceRelationship(StrEnum):
    """How a candidate/assertion relates to a piece of evidence."""

    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    DERIVED_FROM = "DERIVED_FROM"
    CONTEXTUALIZES = "CONTEXTUALIZES"


class EvidenceRef(BaseModel):
    """How a candidate/assertion cites evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: str
    relationship: EvidenceRelationship


def present_evidence(
    *,
    evidence_id: str | None = None,
    source_type: str,
    source_locator: str,
    observed_at: datetime,
    provenance: Provenance,
    valid_time: ValidPeriod | None = None,
    content: str | None = None,
    payload_hash: str | None = None,
) -> Evidence:
    """Build PRESENT evidence. Requires `content` or `payload_hash`."""
    return Evidence(
        evidence_id=evidence_id if evidence_id is not None else "ev_" + new_ulid(),
        source_type=source_type,
        source_locator=source_locator,
        observed_at=observed_at,
        availability=EvidenceAvailability.PRESENT,
        provenance=provenance,
        valid_time=valid_time,
        content=content,
        payload_hash=payload_hash,
    )


def absent_evidence(
    *,
    evidence_id: str | None = None,
    source_type: str,
    source_locator: str,
    observed_at: datetime,
    reason: AbsenceReason,
    provenance: Provenance,
    valid_time: ValidPeriod | None = None,
) -> Evidence:
    """Build ABSENT evidence with a required `reason`."""
    return Evidence(
        evidence_id=evidence_id if evidence_id is not None else "ev_" + new_ulid(),
        source_type=source_type,
        source_locator=source_locator,
        observed_at=observed_at,
        availability=EvidenceAvailability.ABSENT,
        provenance=provenance,
        valid_time=valid_time,
        absence_reason=reason,
    )


def error_evidence(
    *,
    evidence_id: str | None = None,
    source_type: str,
    source_locator: str,
    observed_at: datetime,
    error: str,
    provenance: Provenance,
    valid_time: ValidPeriod | None = None,
) -> Evidence:
    """Build ERROR evidence with a required `error` message."""
    return Evidence(
        evidence_id=evidence_id if evidence_id is not None else "ev_" + new_ulid(),
        source_type=source_type,
        source_locator=source_locator,
        observed_at=observed_at,
        availability=EvidenceAvailability.ERROR,
        provenance=provenance,
        valid_time=valid_time,
        error=error,
    )
