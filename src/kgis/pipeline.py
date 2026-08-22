"""The ingestion pipeline: the stages assembled into one `IngestJob`.

    reader → normalize → validate(record) → build → validate(candidate) → sink
                                                                            ↓
                                                                    IngestionReport

Everything is injected. The pipeline owns no policy of its own — no clock, no
IDs, no scoring, no ontology — it only sequences ports it was handed. That is
what makes every stage independently testable and the whole thing
deterministic: swap in a `FixedClock` and a `DeterministicIdStrategy` and two
runs over the same bytes are byte-identical.

Three properties are the reason this file exists, and each is a guarantee the
stage order alone would not give you:

- **Dry-run == execution, except submission.** A single private `_plan()`
  produces the exact candidate stream for *both* modes. `run()` submits it;
  `plan()` does not. There is no second code path that a dry run could
  describe but an execution diverge from — the plan an operator approves is
  the plan that runs.

- **Idempotency is enforced twice, on purpose.** Within a run, a repeated
  semantic key is *suppressed* before it reaches the sink (the same source
  row mapped by two builders, say). Across runs, the sink itself returns
  `DUPLICATE` for a key it already holds. The first keeps a run from
  arguing with itself; the second makes re-ingesting yesterday's file a
  no-op. Neither is redundant.

- **A record failure is isolated; a source failure is not.** One malformed
  row is rejected and the run continues (rejections are data) — and that
  holds at *every* stage a record can fail, not just record validation. The
  builder's declared `required_fields` are checked before any builder runs,
  and data-dependent failures that only surface at build time (a
  `RecordDataError`, a contract model refusing a value) become structured
  record rejections with nothing from that row admitted. A reader that
  dies mid-stream is caught, the report is marked `incomplete`, and the
  candidates already built are kept — never a silent truncation that looks
  like a short source (spec §9).

The pipeline never writes to a graph. Its only write surface is
`CandidateSink` (ADR-0010); it could not upsert an entity if it tried,
because it holds no reference that can.
"""

from typing import Protocol, Sequence, runtime_checkable

from pydantic import ValidationError as PydanticValidationError

from kg_contracts.candidates import Candidate
from kg_contracts.curation import FailureKind
from kg_contracts.ingestion import IngestReport
from kg_contracts.stores import CandidateSink, LedgerReader, SubmissionStatus

from kgis.builders import BuildContext, CandidateBuilder, SourceScoring
from kgis.clock import Clock, SystemClock
from kgis.errors import RecordDataError, SourceReadError
from kgis.ids import DeterministicIdStrategy, IdStrategy, new_run_id
from kgis.normalize import Normalizer
from kgis.ontology import CoverageCounter, Ontology
from kgis.records import NormalizedRecord
from kgis.report import DryRunPlan, IngestionReport
from kgis.sources.base import RecordReader
from kgis.validate import (
    CandidateValidator,
    CompositeRecordValidator,
    IssueValidator,
    OntologyCandidateValidator,
    RecordValidation,
    RecordValidator,
    RequiredValuesValidator,
)

DEFAULT_BATCH_SIZE = 500


@runtime_checkable
class _CandidateIdProbe(Protocol):
    """A ledger reader that can answer "does this candidate_id exist in ANY
    row?" — the global-PK collision `run()` would hit. Optional capability on
    top of the frozen `LedgerReader` contract (kgis-level, e.g.
    `SqliteCandidateLedger.has_candidate_id`); readers without it fall back to
    live-`semantic_key` prediction only.
    """

    def has_candidate_id(self, candidate_id: str) -> bool: ...


class IngestPipeline:
    """One configured ingestion job (spec §6, satisfies `kg_contracts.IngestJob`).

    The constructor wires the stages; `run()` executes them and `plan()`
    dry-runs them. A pipeline is reusable and side-effect-free until `run()`
    is called — building one touches no source and submits nothing.
    """

    def __init__(
        self,
        *,
        graph_id: str,
        reader: RecordReader,
        normalizer: Normalizer,
        builder: CandidateBuilder,
        sink: CandidateSink,
        scoring: SourceScoring,
        ontology: Ontology | None = None,
        producer: str = "kgis.structured",
        ontology_version: str | None = None,
        record_validator: RecordValidator | None = None,
        candidate_validator: CandidateValidator | None = None,
        ontology_strict: bool = True,
        clock: Clock | None = None,
        ids: IdStrategy | None = None,
        run_id: str | None = None,
        ledger_reader: LedgerReader | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        job_id: str | None = None,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")

        self._graph_id = graph_id
        self._reader = reader
        self._normalizer = normalizer
        self._builder = builder
        self._sink = sink
        self._scoring = scoring
        self._ontology = ontology
        self._producer = producer
        # The ontology's own version is the honest default: the terms a run is
        # checked against and the version it stamps on candidates should agree.
        self._ontology_version = ontology_version or (
            ontology.version if ontology is not None else "unversioned"
        )
        # The builder's declared `required_fields` are honored here, not merely
        # honorable: the pipeline composes a `RequiredValuesValidator` for them
        # so a record missing a field a builder cannot work without (a relation
        # endpoint, an entity key) is rejected at the record tier — before any
        # builder runs and can fail on it. An injected validator runs first;
        # the required-fields guard is appended, never replaced.
        base_record_validator = record_validator or IssueValidator()
        required = tuple(builder.required_fields)
        self._record_validator: RecordValidator = (
            CompositeRecordValidator([base_record_validator, RequiredValuesValidator(required)])
            if required
            else base_record_validator
        )
        self._candidate_validator = candidate_validator or OntologyCandidateValidator(
            ontology, strict=ontology_strict
        )
        self._clock = clock or SystemClock()
        self._ids = ids or DeterministicIdStrategy()
        # A pinned run_id makes a run byte-reproducible, trace IDs and all — the
        # strongest form of "deterministic replay". Left None (the default), each
        # invocation is a fresh run with its own trace, so the audit stream can
        # still tell two ingests of the same data apart (spec §5.9).
        self._run_id = run_id
        self._ledger_reader = ledger_reader
        self._batch_size = batch_size
        self._job_id = job_id or new_run_id().replace("run_", "job_")

    @property
    def job_id(self) -> str:
        """Stable id correlating this job's logs and report (`IngestJob`)."""
        return self._job_id

    def run(self) -> IngestReport:
        """Execute the pipeline: build candidates and submit them to the sink.

        Returns an `IngestionReport` (which *is* a contract `IngestReport`).
        The return type is annotated as the contract type to match the
        `IngestJob` protocol exactly; callers wanting the richer surface can
        rely on the concrete class.
        """
        return self._execute(submit=True)

    def plan(self) -> IngestionReport:
        """Dry-run: build exactly what `run()` would, and submit none of it.

        The returned report carries a `DryRunPlan` holding the real built
        candidates. Nothing reaches the sink — `plan()` is safe to call
        against a production sink.
        """
        return self._execute(submit=False)

    # --- internals -----------------------------------------------------------

    def _execute(self, *, submit: bool) -> IngestionReport:
        run_id = self._run_id or new_run_id()
        report = IngestionReport(
            graph_id=self._graph_id,
            job_id=self._job_id,
            producer_run_id=run_id,
            mode="execute" if submit else "dry_run",
            source_type=self._reader.source_type,
            source_locator=self._reader.locator,
        )
        context = BuildContext(
            graph_id=self._graph_id,
            producer=self._producer,
            producer_run_id=run_id,
            ontology_version=self._ontology_version,
            scoring=self._scoring,
            clock=self._clock,
            ids=self._ids,
        )
        coverage = CoverageCounter()
        started = self._clock.monotonic()

        planned = self._collect(report, context, coverage)

        if submit:
            self._submit_all(planned, report)
        else:
            report.plan = self._build_plan(planned)

        report.coverage = coverage.summarize(self._ontology)
        report.kind_counts = _count_kinds(planned)
        report.elapsed_seconds = self._clock.monotonic() - started
        return report

    def _collect(
        self, report: IngestionReport, context: BuildContext, coverage: CoverageCounter
    ) -> list[Candidate]:
        """Run reader → normalize → validate → build → validate for every record.

        Returns the candidates that survived, in stream order, with every
        report counter updated along the way. Submission is deliberately not
        here: this is the shared spine `run()` and `plan()` both walk, and it
        must behave identically for both.
        """
        planned: list[Candidate] = []
        seen_keys: set[str] = set()

        try:
            for source_record in self._reader.read():
                report.records_read += 1
                normalized = self._normalizer.normalize(source_record)

                decision = self._record_validator.validate(normalized)
                for warning in decision.warnings:
                    report.warn(
                        "record_warning",
                        warning,
                        record_index=normalized.index,
                        locator=normalized.coordinates.locator,
                    )
                if not decision.valid:
                    report.note_validation_failure(decision)
                    continue

                try:
                    built = list(self._builder.build(normalized, context))
                except (RecordDataError, PydanticValidationError) as exc:
                    # Data the record tier could not see — an inverted
                    # valid-time interval, a dynamic type violating a contract
                    # constraint — surfaces only at build time. It is still the
                    # *record's* fault, so it becomes a structured rejection
                    # like any other bad row: the run continues, and nothing
                    # built from this row is admitted, partially or otherwise.
                    # Anything else a builder raises is a bug, not data, and
                    # propagates — a programmer error must never be quarantined
                    # as a bad record. Disclosed residual crack (issue #10):
                    # this boundary is not airtight programmer-vs-data
                    # separation. A builder *bug* that constructs a contract
                    # model with wrong-typed data raises PydanticValidationError
                    # and is caught here — quarantined as BAD_DATA rather than
                    # propagating. Defensible (a model refusing a value usually
                    # *is* bad data) and accepted, but a future maintainer must
                    # not mistake this for a guarantee that every builder bug
                    # propagates.
                    report.note_validation_failure(self._build_failure(normalized, exc))
                    continue
                report.records_valid += 1

                for candidate in built:
                    report.candidates_built += 1
                    if not self._admit_candidate(candidate, report, coverage, seen_keys):
                        continue
                    planned.append(candidate)
        except SourceReadError as exc:
            # The source, not a record. Keep what we built; never let a
            # truncated read masquerade as a short source (spec §9).
            report.fail(f"source read failed: {exc}")

        return planned

    def _build_failure(self, record: NormalizedRecord, exc: Exception) -> RecordValidation:
        """A build-time data failure, expressed as the record rejection it is.

        Keyed on `(index, coordinates)` like every record-tier decision — no
        candidate exists to key it on, and none ever will (spec §5.8).
        """
        return RecordValidation(
            index=record.index,
            coordinates=record.coordinates,
            valid=False,
            failure_kind=FailureKind.BAD_DATA,
            reasons=(f"candidate construction failed: {exc}",),
            policy_version=self._record_validator.policy_version,
        )

    def _admit_candidate(
        self,
        candidate: Candidate,
        report: IngestionReport,
        coverage: CoverageCounter,
        seen_keys: set[str],
    ) -> bool:
        """Decide whether one built candidate joins the plan.

        Order matters: intra-run duplicate suppression first (a repeat of an
        *admitted* candidate is not a new observation), then the sink's guard.
        The semantic key is reserved only after validation succeeds — a
        rejected candidate must not claim the dedup slot, because an injected
        validator may legitimately judge content or policy, and the next
        same-key candidate deserves its own verdict rather than silent
        suppression by a failure. Coverage is observed only for candidates
        that will actually be planned, so the report never counts a term it
        dropped.
        """
        if candidate.semantic_key in seen_keys:
            report.candidates_suppressed += 1
            return False

        verdict = self._candidate_validator.validate(candidate)
        if not verdict.valid:
            report.note_candidate_rejection(verdict)
            return False

        seen_keys.add(candidate.semantic_key)
        coverage.observe(candidate)
        return True

    def _submit_all(self, planned: Sequence[Candidate], report: IngestionReport) -> None:
        """Submit surviving candidates to the sink in batches.

        Batching is a transport detail, never a semantic one: a batch of one
        and a batch of 500 must produce identical outcomes (spec §6,
        batch-of-one constraint). The sink owns cross-run idempotency, so its
        `DUPLICATE` verdicts flow straight into the inherited counters via
        `report.record()`.
        """
        for batch in _batched(planned, self._batch_size):
            result = self._sink.submit(batch)
            for outcome in result.outcomes:
                report.record(outcome)
                if outcome.status is SubmissionStatus.RECEIVED:
                    report.candidates_submitted += 1

    def _build_plan(self, planned: Sequence[Candidate]) -> DryRunPlan:
        """Summarize what an execution would submit, without submitting.

        Consults the ledger if — and only if — a `LedgerReader` was injected.
        Absent one, `ledger_duplicates` stays `None`: an honest "we did not
        check", never a comforting zero (ADR-0009).
        """
        ledger_duplicates = self._count_ledger_duplicates(planned)
        return DryRunPlan(
            would_submit=len(planned),
            by_kind=_count_kinds(planned),
            candidates=tuple(planned),
            truncated=False,
            ledger_duplicates=ledger_duplicates,
        )

    def _count_ledger_duplicates(self, planned: Sequence[Candidate]) -> int | None:
        """Predict exactly what `run()`'s sink would reject as a DUPLICATE.

        A planned candidate is a duplicate if EITHER (a) its `semantic_key`
        already has a *live* ledger row (the sink deduplicates live rows), OR
        (b) its `candidate_id` already exists on ANY row — live, revoked, or
        erased tombstone — because that row holds the `candidate_id` PRIMARY
        KEY and the sink's INSERT would collide on it (Issue #16). The two
        checks are OR'd per candidate so a candidate tripping both (the common
        deterministic-id live replay) is counted once. Absent the (b) probe
        (a reader without `has_candidate_id`), prediction degrades to (a) only.
        """
        if self._ledger_reader is None:
            return None
        existing = {
            entry.candidate.semantic_key
            for entry in self._ledger_reader.ledger_entries()
            if entry.candidate.graph_id == self._graph_id
        }
        probe = (
            self._ledger_reader
            if isinstance(self._ledger_reader, _CandidateIdProbe)
            else None
        )
        return sum(
            1
            for candidate in planned
            if candidate.semantic_key in existing
            or (probe is not None and probe.has_candidate_id(candidate.candidate_id))
        )


def _batched(items: Sequence[Candidate], size: int) -> list[list[Candidate]]:
    """Split into fixed-size batches, preserving order."""
    return [list(items[start : start + size]) for start in range(0, len(items), size)]


def _count_kinds(candidates: Sequence[Candidate]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        counts[candidate.candidate_kind] = counts.get(candidate.candidate_kind, 0) + 1
    return dict(sorted(counts.items()))
