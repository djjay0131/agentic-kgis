"""Ledger-side candidate lifecycle and curation/review pipeline (spec
§7.1-§7.2, §7.6, §7.8; ADR-0006, ADR-0010).

`ProcessingState` is the candidate **ledger**'s own state machine — deliberately
separate from `CurationStatus` (canonical-graph lifecycle, `assertions.py`,
ADR-0006). A candidate moves through validation, resolution, and review
independently of whether anything it produces is ever accepted into the
canonical graph; there is no `PROVISIONAL` value here either, because
uncertainty already *is* the ledger's whole reason for existing.

Owner ruling R1: the spec's ledger state named `SUPERSEDED` is renamed here
to `OBSOLETE` (a candidate obsoleted by a newer candidate covering the same
fact). `CurationStatus` also defines a `SUPERSEDED` value for the canonical
graph; keeping both machines' value sets disjoint means a status string can
never be silently reinterpreted as the wrong machine's state once it leaves
this module's context.

Every `CurationOperation` logs enough to reverse itself (`reversal_data`:
pre-merge member set, lineage, affected projections) — rollback is always a
compensating operation, never deletion of history. `CurationPlan` (spec
§7.1) is the unit the executor applies: a snapshot version, its operations,
optimistic-concurrency `Precondition`s, and the evidence/policy that
justified it. Every model here is frozen and JSON-serializable — full round
trip via `model_dump_json`/`model_validate_json` is the executor seam
(ADR-0010): a `CurationPlan` must survive being written to a queue or log
and read back byte-for-byte equivalent.

`ResolutionDecision` logs the full score vector and matcher/snapshot
versions (spec §7.4) — a single stored final confidence cannot reproduce a
decision after the fact. `ReviewAction` (spec §7.6) follows OpenRefine
semantics: plain approve/reject is not enough for a real curation UI, so
`EDIT`/`SPLIT`/`RELABEL`/`LINK`/`MERGE_ELSEWHERE`/
`SAME_CONCEPT_DIFFERENT_SCOPE` are first-class actions, each auditable via
`AuditRecord` (spec §7.8) — the audit stream is the training corpus that
later justifies raising auto-promotion thresholds.
"""

from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kg_contracts._frozen import FrozenDictFloat, FrozenDictObject
from kg_contracts._ulid import new_ulid
from kg_contracts.policy import AdjudicationRoute, IdentityDisposition


class ProcessingState(StrEnum):
    """The candidate ledger's own lifecycle (spec §7.1-§7.2, ADR-0006).

    Disjoint from `CurationStatus` (`assertions.py`): this is a ledger state
    machine, not a canonical-graph status. `OBSOLETE` (owner ruling R1,
    spec's `SUPERSEDED` renamed) means a candidate has been obsoleted by a
    newer candidate covering the same fact — distinct from
    `CurationStatus.SUPERSEDED`, which is a canonical-graph assertion being
    replaced.
    """

    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    INVALID = "INVALID"
    BLOCKED = "BLOCKED"
    RESOLUTION_PENDING = "RESOLUTION_PENDING"
    REVIEW_PENDING = "REVIEW_PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    OBSOLETE = "OBSOLETE"
    RETRYABLE_ERROR = "RETRYABLE_ERROR"
    PERMANENT_ERROR = "PERMANENT_ERROR"


class FailureKind(StrEnum):
    """Why validation failed (spec §7.2) — each kind gets different
    retry/alert behavior so a transient fault never becomes a permanent
    quarantine (fail-closed must not become fail-stopped).
    """

    BAD_DATA = "BAD_DATA"
    UNSUPPORTED_ONTOLOGY = "UNSUPPORTED_ONTOLOGY"
    TRANSIENT_FAULT = "TRANSIENT_FAULT"


class CurationOperationType(StrEnum):
    """The kinds of compensable operation a `CurationPlan` may carry.

    "Compensable" is load-bearing: every type here must have an inverse
    *in this vocabulary*, or a plan containing it cannot be rolled back at
    all. The pairing is:

    | operation | inverse |
    |---|---|
    | `CREATE_IDENTITY` | `REVOKE_IDENTITY` |
    | `REVOKE_IDENTITY` | `CREATE_IDENTITY` |
    | `ATTACH_ASSERTION` | `RETRACT_ASSERTION` |
    | `RETRACT_ASSERTION` | `ATTACH_ASSERTION` |
    | `MERGE_IDENTITIES` | `SPLIT_IDENTITY` |
    | `SPLIT_IDENTITY` | `MERGE_IDENTITIES` |
    | `REASSIGN_ASSERTION` | `REASSIGN_ASSERTION` (endpoints swapped) |
    | `PROMOTE_ONTOLOGY_TERM` | none yet — see issue #45 |

    `REVOKE_IDENTITY` (ADR-0025) closes the `CREATE_IDENTITY` gap. It is a
    **tombstone, not a deletion and not a supersession**: it sets
    `CanonicalEntity.status` to `REVOKED` and leaves the record — and its
    original `curation_epoch` — in place, so an epoch-scoped read still
    finds the identity that was created. Supersession would have been
    wrong twice over: nothing replaces a reversed identity, and
    `GraphReadOptions.include_superseded` would then resurrect it in
    exactly the history views that must show it as withdrawn.

    Payloads (the shapes an executor must accept):

    - `CREATE_IDENTITY` — a `CanonicalEntity` dump.
    - `ATTACH_ASSERTION` — an `Assertion` dump.
    - `REVOKE_IDENTITY` — `{"identity_id": <identity id>}`, plus an optional
      `"reason"`. Deliberately *not* a whole entity dump: the executor
      revokes the entity that is actually in the graph, so a stale copy in
      the plan cannot overwrite it. The pre-revoke entity belongs in the
      operation's `reversal_data`, which is what lets `REVOKE_IDENTITY`
      itself be compensated by a `CREATE_IDENTITY`.
    """

    CREATE_IDENTITY = "CREATE_IDENTITY"
    REVOKE_IDENTITY = "REVOKE_IDENTITY"
    ATTACH_ASSERTION = "ATTACH_ASSERTION"
    MERGE_IDENTITIES = "MERGE_IDENTITIES"
    SPLIT_IDENTITY = "SPLIT_IDENTITY"
    REASSIGN_ASSERTION = "REASSIGN_ASSERTION"
    RETRACT_ASSERTION = "RETRACT_ASSERTION"
    PROMOTE_ONTOLOGY_TERM = "PROMOTE_ONTOLOGY_TERM"


INVERSE_OPERATION_TYPES: dict[CurationOperationType, CurationOperationType] = {
    CurationOperationType.CREATE_IDENTITY: CurationOperationType.REVOKE_IDENTITY,
    CurationOperationType.REVOKE_IDENTITY: CurationOperationType.CREATE_IDENTITY,
    CurationOperationType.ATTACH_ASSERTION: CurationOperationType.RETRACT_ASSERTION,
    CurationOperationType.RETRACT_ASSERTION: CurationOperationType.ATTACH_ASSERTION,
    CurationOperationType.MERGE_IDENTITIES: CurationOperationType.SPLIT_IDENTITY,
    CurationOperationType.SPLIT_IDENTITY: CurationOperationType.MERGE_IDENTITIES,
    CurationOperationType.REASSIGN_ASSERTION: CurationOperationType.REASSIGN_ASSERTION,
}
"""Which operation type compensates which (ADR-0025).

The compensator itself lives in `agentic-kgcs` — this is the *vocabulary*
half, published here so the two repos cannot disagree about which type
reverses which, and so "is this operation compensable at all?" is a lookup
against the contract rather than a judgement re-made in each executor.

`PROMOTE_ONTOLOGY_TERM` is absent because it has no inverse yet (issue #45):
absence here is the honest statement that a plan containing it is not fully
compensable, not an oversight to be papered over with a plausible-looking
entry."""


class CurationOperation(BaseModel):
    """One compensable step in a `CurationPlan`.

    `reversal_data` carries whatever is needed to undo this operation later
    (pre-merge member set, lineage, affected projections) — rollback is a
    compensating operation, not deletion of history. `payload` and
    `reversal_data` are read-only at rest, not just attribute-level frozen:
    both are `FrozenDict` fields (Issue #7), so in-place mutation of the
    dict itself raises `TypeError` — `frozen=True` alone only blocks
    reassigning the field, it does not stop `op.payload["x"] = 1`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)

    operation_id: str = Field(default_factory=lambda: "op_" + new_ulid())
    type: CurationOperationType
    payload: FrozenDictObject
    reversal_data: FrozenDictObject = Field(default_factory=dict)


class Precondition(BaseModel):
    """Optimistic-concurrency guard on a `CurationPlan` (spec §7.1).

    e.g. `kind="cluster_version", subject=<identity_id>, expected="17"`:
    resolution decides against an identity cluster at a known version,
    never one arbitrary node.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str
    subject: str
    expected: str


class ValidationDecision(BaseModel):
    """Outcome of validating one candidate (spec §7.2).

    `valid=False` requires a `failure_kind` naming why; `valid=True`
    forbids one — a decision cannot be both accepted and carry a failure
    reason.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    valid: bool
    failure_kind: FailureKind | None
    reasons: tuple[str, ...]
    policy_version: str
    trace_id: str

    @model_validator(mode="after")
    def _check_failure_kind_matches_valid(self) -> "ValidationDecision":
        if not self.valid and self.failure_kind is None:
            raise ValueError("valid=False requires failure_kind")
        if self.valid and self.failure_kind is not None:
            raise ValueError("valid=True forbids failure_kind")
        return self


class ResolutionDecision(BaseModel):
    """Outcome of resolving one candidate against the identity graph (spec
    §7.4).

    The full `score_vector` and `matcher_version`/`snapshot_version` are
    logged — a single stored final confidence cannot reproduce a decision.

    `identity_disposition()` projects this decision onto the three-state
    input `ConfidencePolicy.route()` needs (ADR-0024): this model is where
    "did we link to an existing identity, mint a new one, or decide
    nothing?" is already known, so the adjudication gate reads it from here
    rather than each caller re-deriving it from two fields.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    resolved_identity: str | None
    create_new_identity: bool
    route: AdjudicationRoute
    score_vector: FrozenDictFloat
    matcher_version: str | None
    snapshot_version: str = Field(min_length=1)
    trace_id: str

    @model_validator(mode="after")
    def _check_score_vector_nonempty(self) -> "ResolutionDecision":
        if not self.score_vector:
            raise ValueError("score_vector must be non-empty")
        return self

    @model_validator(mode="after")
    def _check_new_identity_names_no_existing_one(self) -> "ResolutionDecision":
        # Fail-closed narrowing (ADR-0021 pattern, ADR-0024): minting a new
        # identity and naming an existing one it resolved to are mutually
        # exclusive claims. Left representable, the contradiction would map
        # to `NEW_IDENTITY` — waiving the resolution gate for a decision that
        # says, in its other field, that it resolved.
        if self.create_new_identity and self.resolved_identity is not None:
            raise ValueError(
                "create_new_identity=True forbids resolved_identity "
                f"(got resolved_identity={self.resolved_identity!r})"
            )
        return self

    def identity_disposition(self) -> IdentityDisposition:
        """This decision as the identity input to `ConfidencePolicy.route()`.

        `create_new_identity` wins outright (the validator above guarantees
        it cannot also name a resolved identity). Otherwise a named
        `resolved_identity` is `RESOLVED_EXISTING`; no identity and no
        instruction to mint one is an abstention, which is `UNRESOLVED` —
        never silently treated as a resolution.
        """
        if self.create_new_identity:
            return IdentityDisposition.NEW_IDENTITY
        if self.resolved_identity is None:
            return IdentityDisposition.UNRESOLVED
        return IdentityDisposition.RESOLVED_EXISTING


class CurationPlan(BaseModel):
    """The unit an executor applies (spec §7.1, verbatim shape).

    Frozen and fully JSON-serializable — round trip via
    `model_dump_json`/`model_validate_json` is the executor seam
    (ADR-0010): a plan must survive being written to a queue or log and
    read back byte-for-byte equivalent.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    plan_id: str = Field(default_factory=lambda: "pl_" + new_ulid())
    candidate_ids: tuple[str, ...] = Field(min_length=1)
    snapshot_version: str
    operations: tuple[CurationOperation, ...]
    preconditions: tuple[Precondition, ...]
    evidence_ids: tuple[str, ...]
    policy_version: str


class ReviewAction(StrEnum):
    """Reviewer actions on a `ReviewItem` (spec §7.6, OpenRefine semantics).

    Plain approve/reject alone is not enough for a real curation UI.
    """

    APPROVE = "APPROVE"
    REJECT = "REJECT"
    EDIT = "EDIT"
    SPLIT = "SPLIT"
    RELABEL = "RELABEL"
    LINK = "LINK"
    MERGE_ELSEWHERE = "MERGE_ELSEWHERE"
    SAME_CONCEPT_DIFFERENT_SCOPE = "SAME_CONCEPT_DIFFERENT_SCOPE"


class ReviewItem(BaseModel):
    """A unit of work enqueued for human review (spec §7.6).

    `priority` drives SLA: P1=24h, P2=7d, P3=30d.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    item_id: str = Field(default_factory=lambda: "rv_" + new_ulid())
    kind: str
    payload: FrozenDictObject
    priority: Literal["P1", "P2", "P3"] = "P3"
    reason: str
    enqueued_at: datetime


class ReviewDecision(BaseModel):
    """A reviewer's resolution of one `ReviewItem` (spec §7.6).

    `action=EDIT` requires `edited_payload` — an edit with nothing to apply
    is not a real edit.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    item_id: str
    action: ReviewAction
    actor: str
    edited_payload: FrozenDictObject | None = None
    note: str | None = None
    decided_at: datetime

    @model_validator(mode="after")
    def _check_edit_requires_edited_payload(self) -> "ReviewDecision":
        if self.action is ReviewAction.EDIT and self.edited_payload is None:
            raise ValueError("action=EDIT requires edited_payload")
        return self


@runtime_checkable
class ReviewQueue(Protocol):
    """The review pipeline's storage contract (spec §7.6).

    Operation history is part of the contract, not an afterthought — the
    future review UI builds on `history()` directly.
    """

    def enqueue(self, item: ReviewItem) -> str: ...

    def pending(self, limit: int = 50) -> list[ReviewItem]: ...

    def resolve(self, decision: ReviewDecision) -> None: ...

    def history(self, item_id: str) -> list[ReviewDecision]: ...


class AuditRecord(BaseModel):
    """An audit-stream entry for one applied operation (spec §7.8).

    `score_vector` is read-only at rest: it is a `FrozenDict` field
    (Issue #7), so `frozen=True` (blocking reassignment) is joined by
    in-place mutation of the dict itself raising `TypeError`. Append-only
    at the stream level — no in-place edits or deletions of an already
    written record — is still enforced by the ledger/store layer (Plan
    2/3), not by this model. The audit stream is the training corpus that
    later justifies raising auto-promotion thresholds.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    audit_id: str = Field(default_factory=lambda: "au_" + new_ulid())
    operation_id: str
    decided_by: str
    score_vector: FrozenDictFloat
    evidence_ids: tuple[str, ...]
    policy_version: str
    trace_id: str
    recorded_at: datetime
