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
from kg_contracts.curation import CurationOperationType, Precondition
from kg_contracts.identity import EntityRef
from kg_contracts.stores import (
    AdapterCapabilities,
    CommitResult,
    GraphMutationBatch,
    GraphReadOptions,
    SubmissionOutcome,
    SubmissionResult,
    SubmissionStatus,
    UnsupportedCapabilityError,
)

_TxnSnapshot = tuple[dict[str, CanonicalEntity], dict[str, list[Assertion]], dict[str, int], int]


class MemoryCandidateSink:
    """Dict-backed candidate ledger keyed by `(graph_id, semantic_key)`.

    Idempotency is by **semantic key**, never content hash (spec §5.8):
    the first submission for a given `(graph_id, semantic_key)` pair is
    `RECEIVED`; every later submission of that same pair is `DUPLICATE`,
    regardless of what changed in the payload or content hash.
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


class MemoryGraphStore:
    """Dict/list-backed reference `GraphMutationStore` + `GraphReader`.

    `apply()` supports `CREATE_IDENTITY` and `ATTACH_ASSERTION` (Plan 1);
    the other five `CurationOperationType` values raise `NotImplementedError`
    naming Plan 3. Preconditions of kind `entity_version` are checked
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
        new_entities: list[CanonicalEntity] = []
        new_assertions: list[Assertion] = []
        for operation in batch.operations:
            if operation.type is CurationOperationType.CREATE_IDENTITY:
                new_entities.append(
                    CanonicalEntity.model_validate(
                        {**operation.payload, "curation_epoch": new_epoch}
                    )
                )
            elif operation.type is CurationOperationType.ATTACH_ASSERTION:
                new_assertions.append(
                    Assertion.model_validate({**operation.payload, "curation_epoch": new_epoch})
                )
            else:
                raise NotImplementedError(
                    f"{operation.type} is not implemented in Plan 1 (lands in Plan 3)"
                )

        for entity in new_entities:
            self.put_entity(entity)
        for assertion in new_assertions:
            self.put_assertion(assertion)

        touched_subjects = [e.identity_id for e in new_entities] + [
            a.subject_identity for a in new_assertions
        ]
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

    def _is_visible(
        self, record_epoch: int, status: CurationStatus, options: GraphReadOptions
    ) -> bool:
        if options.curation_epoch is not None and record_epoch > options.curation_epoch:
            return False
        if status is CurationStatus.SUPERSEDED and not options.include_superseded:
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
