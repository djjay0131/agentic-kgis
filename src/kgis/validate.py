"""Validation, in two tiers — and why it has to be two.

The contract's `ValidationDecision` (spec §7.2) is keyed on a
**`candidate_id`**. But the pipeline rejects malformed *records*, and a
record that fails validation must never become a candidate — so at the
moment of rejection there is no candidate, and therefore no ID to key the
decision on. Minting a throwaway candidate ID just to satisfy the field
would be a lie in the audit stream: it would name a candidate that was never
proposed and must never exist.

So validation happens at two tiers, each with the type that actually fits:

1. **Record validation** — `RecordValidation`, keyed on `(index,
   coordinates)`. Runs before candidate creation. This is what guarantees
   *"validation failures never produce candidates"*. It is a `kgis` type
   because `kg_contracts` has none for a pre-candidate record; it mirrors
   `ValidationDecision` field-for-field otherwise, including the
   `valid`/`failure_kind` biconditional.

2. **Candidate validation** — the contract's real `ValidationDecision`,
   keyed on the candidate that now exists. Runs after building, before
   submission. This is what guarantees *"CandidateSink always receives valid
   candidates"*, and it is where `UNSUPPORTED_ONTOLOGY` genuinely belongs: an
   ontology violation is a property of the proposed *term*, which is a fact
   about the candidate, not about the row.

That split is an architectural finding, not a workaround; it is written up as
an ADR candidate (`docs/adr/candidates/0001-record-scoped-validation.md`).
The contract is not wrong — it is a *ledger-side* contract, and the ledger
only ever sees candidates. The gap is simply that ingestion validates
something the ledger never sees.

Both tiers reuse the contract's `FailureKind` taxonomy (spec §7.2), so bad
data, an unsupported ontology, and a transient fault keep their distinct
retry/alert behavior — a transient fault must never become a permanent
quarantine.
"""

from typing import Protocol, Sequence, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kg_contracts.candidates import (
    AttributeAssertionCandidate,
    Candidate,
    EntityCandidate,
    RelationCandidate,
    SourceCoordinates,
)
from kg_contracts.curation import FailureKind, ValidationDecision
from kgis.ontology import Ontology
from kgis.records import NormalizedRecord

DEFAULT_POLICY_VERSION = "1"


class RecordValidation(BaseModel):
    """Outcome of validating one *record*, before any candidate exists.

    The record-scoped twin of `kg_contracts.ValidationDecision`, carrying the
    same `valid`/`failure_kind` biconditional: `valid=False` requires a
    `failure_kind` naming why, and `valid=True` forbids one — a decision
    cannot be both accepted and carry a failure reason.

    `warnings` has no counterpart on `ValidationDecision`: a record can be
    accepted *and* worth telling an operator about (a repaired timezone, an
    ignored column), and collapsing that into `reasons` would make a clean
    run look like a dirty one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    index: int = Field(ge=0)
    coordinates: SourceCoordinates
    valid: bool
    failure_kind: FailureKind | None = None
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    policy_version: str = DEFAULT_POLICY_VERSION

    @model_validator(mode="after")
    def _check_failure_kind_matches_valid(self) -> "RecordValidation":
        if not self.valid and self.failure_kind is None:
            raise ValueError("valid=False requires failure_kind")
        if self.valid and self.failure_kind is not None:
            raise ValueError("valid=True forbids failure_kind")
        return self


@runtime_checkable
class RecordValidator(Protocol):
    """Decides whether a normalized record may become a candidate."""

    @property
    def policy_version(self) -> str:
        """Version of the rule set applied — logged on every decision (spec §5.8)."""
        ...

    def validate(self, record: NormalizedRecord) -> RecordValidation:
        """Never raises: an invalid record is a decision, not an exception."""
        ...


@runtime_checkable
class CandidateValidator(Protocol):
    """Guards the sink: the last check a candidate passes before submission."""

    @property
    def policy_version(self) -> str: ...

    def validate(self, candidate: Candidate) -> ValidationDecision:
        """Returns the contract's `ValidationDecision` (spec §7.2)."""
        ...


class IssueValidator:
    """Rejects records that normalization could not read. The baseline validator.

    Everything it needs already happened: normalization is total, so a value
    that could not be coerced, or a required field that was missing, is
    already sitting on the record as an error `RecordIssue`. This validator
    turns those into a decision rather than re-deriving them — which is what
    keeps the two stages independently testable.
    """

    def __init__(self, *, policy_version: str = DEFAULT_POLICY_VERSION) -> None:
        self._policy_version = policy_version

    @property
    def policy_version(self) -> str:
        return self._policy_version

    def validate(self, record: NormalizedRecord) -> RecordValidation:
        warnings = tuple(issue.render() for issue in record.warnings)
        if record.has_errors:
            return RecordValidation(
                index=record.index,
                coordinates=record.coordinates,
                valid=False,
                failure_kind=FailureKind.BAD_DATA,
                reasons=tuple(issue.render() for issue in record.errors),
                warnings=warnings,
                policy_version=self._policy_version,
            )
        return RecordValidation(
            index=record.index,
            coordinates=record.coordinates,
            valid=True,
            reasons=(),
            warnings=warnings,
            policy_version=self._policy_version,
        )


class RequiredValuesValidator:
    """Rejects records whose named fields normalized to `None`.

    Overlaps `FieldSpec(required=True)` on purpose: a field can be optional to
    the *source* (a nullable column) while being mandatory to a *builder* (you
    cannot mint an entity with no key). This validator is how a builder states
    that requirement without the source schema having to lie about its data.
    """

    def __init__(
        self, fields: Sequence[str], *, policy_version: str = DEFAULT_POLICY_VERSION
    ) -> None:
        self._fields = tuple(fields)
        self._policy_version = policy_version

    @property
    def policy_version(self) -> str:
        return self._policy_version

    def validate(self, record: NormalizedRecord) -> RecordValidation:
        missing = [
            name for name in self._fields if record.values.get(name) is None
        ]
        if missing:
            return RecordValidation(
                index=record.index,
                coordinates=record.coordinates,
                valid=False,
                failure_kind=FailureKind.BAD_DATA,
                reasons=tuple(f"required_value: {name!r} is null" for name in missing),
                policy_version=self._policy_version,
            )
        return RecordValidation(
            index=record.index,
            coordinates=record.coordinates,
            valid=True,
            policy_version=self._policy_version,
        )


class CompositeRecordValidator:
    """Runs validators in order and merges their decisions.

    Runs **all** of them rather than short-circuiting on the first failure: an
    operator fixing a bad file wants every reason at once, not one per re-run.
    The merged `failure_kind` is the first failure's, and reasons accumulate
    in validator order, so the result is deterministic.
    """

    def __init__(
        self, validators: Sequence[RecordValidator], *, policy_version: str | None = None
    ) -> None:
        self._validators = tuple(validators)
        self._policy_version = policy_version or "+".join(
            validator.policy_version for validator in validators
        ) or DEFAULT_POLICY_VERSION

    @property
    def policy_version(self) -> str:
        return self._policy_version

    def validate(self, record: NormalizedRecord) -> RecordValidation:
        reasons: list[str] = []
        warnings: list[str] = []
        failure_kind: FailureKind | None = None

        for validator in self._validators:
            decision = validator.validate(record)
            warnings.extend(decision.warnings)
            if not decision.valid:
                reasons.extend(decision.reasons)
                if failure_kind is None:
                    failure_kind = decision.failure_kind

        # Deduplicate while preserving order: two validators can legitimately
        # report the same underlying problem, and the operator should see it once.
        return RecordValidation(
            index=record.index,
            coordinates=record.coordinates,
            valid=failure_kind is None,
            failure_kind=failure_kind,
            reasons=_dedupe(reasons),
            warnings=_dedupe(warnings),
            policy_version=self._policy_version,
        )


class OntologyCandidateValidator:
    """Checks a built candidate's terms against the graph's declared ontology.

    This is the sink's guard, and the reason candidate-tier validation exists:
    an ontology violation is a fact about the proposed *term*, which only
    exists once the candidate does.

    `strict=True` (the default) **rejects** an undeclared term as
    `UNSUPPORTED_ONTOLOGY` — a distinct failure kind from `BAD_DATA` precisely
    so it can be alerted and retried differently (spec §7.2): the data may be
    perfect and the *ontology* simply behind.

    `strict=False` admits the candidate but still names the unknown term in
    `reasons`, which the pipeline surfaces as a warning. Either way the term
    is reported — spec §6: "Unknown types reported, never hidden." The one
    thing neither mode does is stay quiet.

    With no ontology (`None`), every candidate passes: a graph that declares
    no vocabulary constrains nothing.
    """

    def __init__(
        self,
        ontology: Ontology | None,
        *,
        strict: bool = True,
        policy_version: str = DEFAULT_POLICY_VERSION,
    ) -> None:
        self._ontology = ontology
        self._strict = strict
        self._policy_version = policy_version

    @property
    def policy_version(self) -> str:
        return self._policy_version

    def validate(self, candidate: Candidate) -> ValidationDecision:
        reasons = self._unknown_terms(candidate)
        rejected = bool(reasons) and self._strict
        return ValidationDecision(
            candidate_id=candidate.candidate_id,
            valid=not rejected,
            failure_kind=FailureKind.UNSUPPORTED_ONTOLOGY if rejected else None,
            reasons=reasons,
            policy_version=self._policy_version,
            trace_id=candidate.trace_id,
        )

    def _unknown_terms(self, candidate: Candidate) -> tuple[str, ...]:
        ontology = self._ontology
        if ontology is None:
            return ()
        if isinstance(candidate, EntityCandidate):
            if not ontology.declares_entity_type(candidate.entity_type):
                return (f"entity_type {candidate.entity_type!r} is not in the ontology",)
        elif isinstance(candidate, RelationCandidate):
            if not ontology.declares_relation_type(candidate.relation_type):
                return (f"relation_type {candidate.relation_type!r} is not in the ontology",)
        elif isinstance(candidate, AttributeAssertionCandidate):
            if not ontology.declares_attribute(candidate.attribute):
                return (f"attribute {candidate.attribute!r} is not in the ontology",)
        return ()


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    """Order-preserving dedupe — determinism matters more than speed here."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)
