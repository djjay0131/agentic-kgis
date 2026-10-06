"""In-memory reference adapters (spec §10.2).

Pure dicts/lists — no I/O, no engine code. This is the ONE place under
`kg_contracts` where in-memory adapters are allowed: they exist so every
implementation of a port (memory, Neo4j, Spanner, ...) and every adopter
repo can run `contract.py`'s reusable suites with zero infrastructure
(Phase-0 lesson, vttsi contract-test discipline). `MemoryGraphStore` is
the first backend with full temporal-query support — it declares
`supports_temporal_queries=True` and `supports_snapshot_reads=True`, and
every later backend is validated against the same suites this store
already passes.

Owner ruling R2: `MemoryGraphStore.apply()` composes the adapter-internal
writer primitives from `stores.py` (`GraphWriter.put_entity`/
`put_assertion`/`mark_superseded`, `TransactionalGraphWriter.begin`/
`commit`/`rollback`, `BulkGraphWriter.put_entities`) as its actual
internal mutation surface, so `MemoryGraphStore` implements all three
writer protocols for real rather than only the executor-facing `apply()`
entry point.
"""

from datetime import datetime
from typing import Sequence

from kg_contracts.assertions import Assertion, CanonicalEntity, CurationStatus
from kg_contracts.candidates import Candidate
from kg_contracts.curation import CurationOperationType, Precondition, ProcessingState
from kg_contracts.identity import EntityRef
from kg_contracts.stores import (
    AdapterCapabilities,
    CommitResult,
    GraphMutationBatch,
    GraphReadOptions,
    LedgerEntry,
    LedgerReadOptions,
    SubmissionOutcome,
    SubmissionResult,
    SubmissionStatus,
    UnsupportedCapabilityError,
)

_TxnSnapshot = tuple[dict[str, CanonicalEntity], dict[str, list[Assertion]], dict[str, int], int]


class MemoryCandidateSink:
    """Dict-backed candidate ledger: `CandidateSink` write + `LedgerReader` read.

    Idempotency is by **semantic key**, never content hash (spec §5.8):
    the first submission for a given `(graph_id, semantic_key)` pair is
    `RECEIVED`; every later submission of that same pair is `DUPLICATE`,
    regardless of what changed in the payload or content hash.

    One store, two *separate* access paths (ADR-0006, ADR-0011): `submit()`
    is the `CandidateSink` write surface; `ledger_entries()` /
    `ledger_entry()` are the `LedgerReader` read surface. They are distinct
    protocols over the same backing dict — a canonical `GraphReader` can
    never reach this data. This reference models only synchronous admission,
    so every admitted candidate sits in `ProcessingState.RECEIVED`; the
    async lifecycle transitions (VALIDATED, REVIEW_PENDING, ...) belong to
    the ledger store built in Plan 2. `received_at` is taken from the
    candidate's own `created_at`, keeping this test double clock-free and
    deterministic.
    """

    def __init__(self) -> None:
        self._seen_keys: set[tuple[str, str]] = set()
        self._received: list[Candidate] = []

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities()

    def submit(self, candidates: Sequence[Candidate]) -> SubmissionResult:
        outcomes: list[SubmissionOutcome] = []
        for candidate in candidates:
            key = (candidate.graph_id, candidate.semantic_key)
            if key in self._seen_keys:
                outcomes.append(
                    SubmissionOutcome(
                        candidate_id=candidate.candidate_id,
                        status=SubmissionStatus.DUPLICATE,
                        reason=f"semantic_key {candidate.semantic_key!r} already received",
                        trace_id=candidate.trace_id,
                    )
                )
                continue
            self._seen_keys.add(key)
            self._received.append(candidate)
            outcomes.append(
                SubmissionOutcome(
                    candidate_id=candidate.candidate_id,
                    status=SubmissionStatus.RECEIVED,
                    trace_id=candidate.trace_id,
                )
            )
        return SubmissionResult(outcomes=tuple(outcomes))

    def received(self) -> list[Candidate]:
        """Test helper: candidates actually admitted (RECEIVED), in order."""
        return list(self._received)

    # --- LedgerReader (separate access path from any GraphReader) -------------

    def _entry(self, candidate: Candidate) -> LedgerEntry:
        return LedgerEntry(
            candidate=candidate,
            processing_state=ProcessingState.RECEIVED,
            received_at=candidate.created_at,
        )

    def ledger_entries(
        self, options: LedgerReadOptions = LedgerReadOptions()
    ) -> list[LedgerEntry]:
        entries: list[LedgerEntry] = []
        for candidate in self._received:
            if options.graph_id is not None and candidate.graph_id != options.graph_id:
                continue
            if (
                options.processing_states is not None
                and ProcessingState.RECEIVED not in options.processing_states
            ):
                continue
            entries.append(self._entry(candidate))
        return entries

    def ledger_entry(self, candidate_id: str) -> LedgerEntry | None:
        for candidate in self._received:
            if candidate.candidate_id == candidate_id:
                return self._entry(candidate)
        return None


class MemoryGraphStore:
    """Dict/list-backed reference `GraphMutationStore` + `GraphReader`.

    `apply()` supports `CREATE_IDENTITY`, `ATTACH_ASSERTION`,
    `REVOKE_IDENTITY` (ADR-0025 — the reference implementation of the
    `CREATE_IDENTITY` inverse, so a rollback can be demonstrated rather
    than asserted) and `RESTORE_IDENTITY` (ADR-0027 — the exact inverse of
    `REVOKE_IDENTITY`, preserving the original creation epoch); the other
    five `CurationOperationType` values raise `NotImplementedError` naming
    Plan 3. Preconditions of kind `entity_version` are checked
    against an internal per-identity version counter; any other
    precondition kind is not enforced by this reference adapter (Plan 1
    curation plans only ever emit `entity_version` preconditions). A
    failed precondition leaves the store completely unchanged (atomicity)
    — operations are validated and built before any of them is applied.
    """

    def __init__(self) -> None:
        self._epoch: int = 0
        self._entities: dict[str, CanonicalEntity] = {}
        self._assertions: dict[str, list[Assertion]] = {}
        self._entity_versions: dict[str, int] = {}
        self._txn_snapshot: _TxnSnapshot | None = None

    # --- CapabilityDeclaring -------------------------------------------------

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(supports_temporal_queries=True, supports_snapshot_reads=True)

    # --- GraphWriter (adapter-internal; used by apply()) ----------------------

    def put_entity(self, entity: CanonicalEntity) -> None:
        self._entities[entity.identity_id] = entity

    def put_assertion(self, assertion: Assertion) -> None:
        self._assertions.setdefault(assertion.subject_identity, []).append(assertion)

    def mark_superseded(self, assertion_id: str, at: datetime) -> None:
        for subject_assertions in self._assertions.values():
            for index, assertion in enumerate(subject_assertions):
                if assertion.assertion_id == assertion_id:
                    subject_assertions[index] = assertion.model_copy(
                        update={"status": CurationStatus.SUPERSEDED, "superseded_at": at}
                    )
                    return
        raise KeyError(f"no assertion with assertion_id {assertion_id!r}")

    # --- TransactionalGraphWriter (adapter-internal) --------------------------

    def begin(self) -> None:
        self._txn_snapshot = (
            dict(self._entities),
            {subject: list(assertions) for subject, assertions in self._assertions.items()},
            dict(self._entity_versions),
            self._epoch,
        )

    def commit(self) -> None:
        self._txn_snapshot = None

    def rollback(self) -> None:
        if self._txn_snapshot is None:
            raise RuntimeError("rollback() called without a matching begin()")
        entities, assertions, versions, epoch = self._txn_snapshot
        self._entities = entities
        self._assertions = assertions
        self._entity_versions = versions
        self._epoch = epoch
        self._txn_snapshot = None

    # --- BulkGraphWriter (adapter-internal) -----------------------------------

    def put_entities(self, entities: Sequence[CanonicalEntity]) -> int:
        count = 0
        for entity in entities:
            self.put_entity(entity)
            count += 1
        return count

    # --- GraphMutationStore (executor-facing) ---------------------------------

    def apply(
        self, batch: GraphMutationBatch, preconditions: Sequence[Precondition]
    ) -> CommitResult:
        failed = tuple(p for p in preconditions if not self._precondition_holds(p))
        if failed:
            return CommitResult(
                batch_id=batch.batch_id, committed=False, failed_preconditions=failed
            )

        new_epoch = self._epoch + 1
        # Operations apply in order, and build a **staged** view so a later
        # operation sees an earlier one in the same batch. That is what makes
        # `CREATE_IDENTITY` followed by `REVOKE_IDENTITY` of the same target a
        # coherent single batch — it commits a tombstone at this batch's epoch
        # (issue #50a) — instead of failing with a misleading "unknown
        # identity" because the target is not yet in `self._entities`.
        staged_entities: dict[str, CanonicalEntity] = {}
        new_assertions: list[Assertion] = []
        touched_subjects: list[str] = []
        for operation in batch.operations:
            if operation.type is CurationOperationType.CREATE_IDENTITY:
                entity = CanonicalEntity.model_validate(
                    {**operation.payload, "curation_epoch": new_epoch}
                )
                staged_entities[entity.identity_id] = entity
                touched_subjects.append(entity.identity_id)
            elif operation.type is CurationOperationType.ATTACH_ASSERTION:
                assertion = Assertion.model_validate(
                    {**operation.payload, "curation_epoch": new_epoch}
                )
                new_assertions.append(assertion)
                touched_subjects.append(assertion.subject_identity)
            elif operation.type is CurationOperationType.REVOKE_IDENTITY:
                identity_id = operation.payload.get("identity_id")
                if not isinstance(identity_id, str):
                    return CommitResult(
                        batch_id=batch.batch_id,
                        committed=False,
                        error=(
                            "REVOKE_IDENTITY payload requires a string identity_id "
                            f"(got {identity_id!r})"
                        ),
                    )
                existing = staged_entities.get(identity_id, self._entities.get(identity_id))
                if existing is None:
                    return CommitResult(
                        batch_id=batch.batch_id,
                        committed=False,
                        error=f"REVOKE_IDENTITY names an unknown identity: {identity_id!r}",
                    )
                # Issue #50b: a revoke with nothing left to revoke must fail
                # loudly rather than commit a no-op epoch that looks like it
                # did something — the canonical-graph analogue of ADR-0013's
                # ledger `revoke()`, which raises `KeyError` when the row is
                # already revoked/erased. Checked against the staged status so
                # a batch that revokes the same identity twice also fails.
                if existing.status is CurationStatus.REVOKED:
                    return CommitResult(
                        batch_id=batch.batch_id,
                        committed=False,
                        error=(
                            "REVOKE_IDENTITY targets an already-revoked identity: "
                            f"{identity_id!r}"
                        ),
                    )
                # `curation_epoch` is deliberately NOT advanced: it records
                # the epoch the identity was created in, and moving it
                # forward would make the identity vanish from every
                # epoch-scoped read of the history that created it — a
                # rollback that erases the record of what it rolled back.
                # Only `status` changes; the record itself is retained.
                staged_entities[identity_id] = existing.model_copy(
                    update={"status": CurationStatus.REVOKED}
                )
                touched_subjects.append(identity_id)
            elif operation.type is CurationOperationType.RESTORE_IDENTITY:
                identity_id = operation.payload.get("identity_id")
                if not isinstance(identity_id, str):
                    return CommitResult(
                        batch_id=batch.batch_id,
                        committed=False,
                        error=(
                            "RESTORE_IDENTITY payload requires a string identity_id "
                            f"(got {identity_id!r})"
                        ),
                    )
                existing = staged_entities.get(identity_id, self._entities.get(identity_id))
                if existing is None:
                    return CommitResult(
                        batch_id=batch.batch_id,
                        committed=False,
                        error=f"RESTORE_IDENTITY names an unknown identity: {identity_id!r}",
                    )
                # Issue #51 / ADR-0027: the mirror of the double-revoke rule. A
                # restore with nothing to restore must fail loudly rather than
                # commit a no-op epoch, so it is a non-commit naming the
                # identity against the staged status (a batch that restores the
                # same identity twice also fails). Only `REVOKED` can be
                # restored; an ACTIVE or SUPERSEDED identity is not.
                if existing.status is not CurationStatus.REVOKED:
                    return CommitResult(
                        batch_id=batch.batch_id,
                        committed=False,
                        error=(
                            "RESTORE_IDENTITY targets an identity that is not revoked: "
                            f"{identity_id!r} (status {existing.status.value})"
                        ),
                    )
                # `curation_epoch` is deliberately NOT advanced, exactly as in a
                # revoke: the epoch records when the identity was created, and
                # moving it would make the identity vanish from epoch-scoped
                # reads of the history that created it. The restore commits as
                # its own epoch (the append-only status-change entry), while the
                # record keeps its original stamp, so `REVOKED @ E -> ACTIVE @
                # E` is epoch-preserving in both directions.
                staged_entities[identity_id] = existing.model_copy(
                    update={"status": CurationStatus.ACTIVE}
                )
                touched_subjects.append(identity_id)
            else:
                raise NotImplementedError(
                    f"{operation.type} is not implemented in Plan 1 (lands in Plan 3)"
                )

        for entity in staged_entities.values():
            self.put_entity(entity)
        for assertion in new_assertions:
            self.put_assertion(assertion)
        for subject in touched_subjects:
            self._entity_versions[subject] = self._entity_versions.get(subject, 0) + 1

        self._epoch = new_epoch
        return CommitResult(batch_id=batch.batch_id, committed=True, new_epoch=new_epoch)

    def _precondition_holds(self, precondition: Precondition) -> bool:
        if precondition.kind != "entity_version":
            return True
        actual = self._entity_versions.get(precondition.subject, 0)
        return str(actual) == precondition.expected

    # --- GraphReader / TemporalGraphReader ------------------------------------

    def current_epoch(self) -> int:
        return self._epoch

    def get_entity(
        self, identity_id: str, options: GraphReadOptions = GraphReadOptions()
    ) -> CanonicalEntity | None:
        self._check_temporal_options(options)
        entity = self._entities.get(identity_id)
        if entity is None or not self._is_visible(entity.curation_epoch, entity.status, options):
            return None
        return entity

    def find_entities(
        self,
        entity_type: str | None = None,
        alias: EntityRef | None = None,
        options: GraphReadOptions = GraphReadOptions(),
    ) -> list[CanonicalEntity]:
        self._check_temporal_options(options)
        results: list[CanonicalEntity] = []
        for entity in self._entities.values():
            if not self._is_visible(entity.curation_epoch, entity.status, options):
                continue
            if entity_type is not None and entity.entity_type != entity_type:
                continue
            if alias is not None and alias not in entity.aliases:
                continue
            results.append(entity)
        return results

    def assertions_for(
        self, identity_id: str, options: GraphReadOptions = GraphReadOptions()
    ) -> list[Assertion]:
        self._check_temporal_options(options)
        # Issue #49 / ADR-0026: a revoked identity takes its assertions with
        # it. `REVOKE_IDENTITY` tombstones the entity, so a default canonical
        # read of that identity's assertions must return nothing rather than
        # leave live assertions hanging off an identity no reader can see.
        # This is a READ-layer shield, not an assertion mutation: the
        # assertion's own status (ACTIVE or SUPERSEDED) is preserved, so
        # history keeps the fact that it was superseded rather than revoked.
        # `include_revoked=True` is the history surface that returns them,
        # and the assertion's own `_is_visible` status filter still applies
        # underneath — a SUPERSEDED assertion on a revoked identity therefore
        # needs BOTH flags, keeping the two switches independent.
        if not self._subject_visible(identity_id, options):
            return []
        results: list[Assertion] = []
        for assertion in self._assertions.get(identity_id, []):
            if not self._is_visible(assertion.curation_epoch, assertion.status, options):
                continue
            if options.valid_at is not None and not _valid_at_matches(assertion, options.valid_at):
                continue
            if options.transaction_at is not None and not _transaction_at_matches(
                assertion, options.transaction_at
            ):
                continue
            results.append(assertion)
        return results

    def neighborhood(
        self, identity_id: str, hops: int = 1, options: GraphReadOptions = GraphReadOptions()
    ) -> list[CanonicalEntity]:
        self._check_temporal_options(options)
        visited = {identity_id}
        frontier = {identity_id}
        result: list[CanonicalEntity] = []
        for _ in range(hops):
            next_frontier: set[str] = set()
            for subject in frontier:
                for assertion in self.assertions_for(subject, options):
                    target = assertion.object_identity
                    if target is None or target in visited:
                        continue
                    visited.add(target)
                    entity = self.get_entity(target, options)
                    if entity is not None:
                        next_frontier.add(target)
                        result.append(entity)
            frontier = next_frontier
            if not frontier:
                break
        return result

    def _check_temporal_options(self, options: GraphReadOptions) -> None:
        wants_temporal = options.valid_at is not None or options.transaction_at is not None
        if wants_temporal and not self.capabilities().supports_temporal_queries:
            raise UnsupportedCapabilityError(
                "valid_at/transaction_at require an adapter with supports_temporal_queries"
            )

    def _subject_visible(self, identity_id: str, options: GraphReadOptions) -> bool:
        """Whether the *subject identity* permits its assertions to be read.

        Only `REVOKED` shields: an unknown subject is left alone (an orphan
        assertion is a separate concern), and `SUPERSEDED` identities are out
        of scope here because ADR-0026 extends only the `REVOKE_IDENTITY`
        tombstone. `include_revoked` is the single switch that reveals a
        withdrawn identity and, with it, its assertions.
        """
        entity = self._entities.get(identity_id)
        if entity is None:
            return True
        if entity.status is CurationStatus.REVOKED:
            return options.include_revoked
        return True

    def _is_visible(
        self, record_epoch: int, status: CurationStatus, options: GraphReadOptions
    ) -> bool:
        if options.curation_epoch is not None and record_epoch > options.curation_epoch:
            return False
        # REVOKED visibility: hidden by default since ADR-0025, which is the
        # durable read-semantics change the previous comment here said this
        # needed ("an ADR, not a test-double tweak"). Without it
        # `REVOKE_IDENTITY` would change nothing a reader can observe, and a
        # rollback that changes nothing observable is not a rollback.
        # Nothing is deleted: the record keeps its original `curation_epoch`
        # and `include_revoked=True` is the history surface that returns it.
        # The two flags are independent — `include_superseded` never reveals
        # a REVOKED record and `include_revoked` never reveals a SUPERSEDED
        # one.
        if status is CurationStatus.SUPERSEDED and not options.include_superseded:
            return False
        if status is CurationStatus.REVOKED and not options.include_revoked:
            return False
        return True


def _valid_at_matches(assertion: Assertion, valid_at: datetime) -> bool:
    period = assertion.valid_period
    if period.valid_from is not None and valid_at < period.valid_from:
        return False
    if period.valid_to is not None and valid_at > period.valid_to:
        return False
    return True


def _transaction_at_matches(assertion: Assertion, transaction_at: datetime) -> bool:
    if assertion.recorded_at > transaction_at:
        return False
    if assertion.superseded_at is not None and assertion.superseded_at <= transaction_at:
        return False
    return True
