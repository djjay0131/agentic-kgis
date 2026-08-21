"""`ExtractionPipeline`: documents → parallel extractors → evidence → `CandidateSink`.

This is the LLM-extraction *front-end* onto the Sprint 1 candidate machinery —
not a second ingestion architecture. It reuses the same candidate seam
(`CandidateSink`), the same `BuildContext` and builders, the same candidate
validation, the same `IngestionReport`, the same clock/id strategies, and the
Plan 2 evidence registry. What it adds is everything free-text needs that a row
reader does not: segmentation, N extractors running in parallel, per-extractor
failure isolation, and evidence linking each candidate to the passage it came
from. Both modes still "submit candidates through `CandidateSink`" (spec §6).

Four properties are load-bearing here:

- **Bounded concurrency.** Extractors run in a thread pool capped at
  `concurrency`; the slow part (the model call) overlaps, while the shared
  registry and sink are only ever touched by the single reduce thread, so no
  SQLite connection is used across threads.
- **Deterministic order despite parallelism.** Work is dispatched and reduced
  in a fixed (document, chunk, extractor) order regardless of which model call
  finishes first, so intra-run duplicate suppression (first-key-wins) and
  replay are stable.
- **Failure isolation.** One (extractor, chunk) failure — a model error, a
  malformed response, an un-buildable row — is caught, recorded on the report
  as a failure (marking it `incomplete`, spec §9), and does not corrupt its
  successful siblings.
- **Honest dry-run.** `plan()` really runs the extractors and shows the exact
  candidates a run *would* submit, submitting none. But LLM extraction is
  **not** reproducible unless the client is: against a nondeterministic client,
  `plan()` warns that a later `run()` may extract differently. Only a
  `deterministic` client (replay / pinned) makes the plan a promise. Evidence
  is written only on `run()`, so `plan()` stays side-effect-free.
"""

from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from kg_contracts.candidates import Candidate
from kg_contracts.evidence import EvidenceRef, EvidenceRelationship
from kg_contracts.ingestion import CompletionClient
from kg_contracts.stores import CandidateSink, LedgerReader, SubmissionStatus
from kgis.builders import BuildContext, SourceScoring
from kgis.clock import Clock, SystemClock
from kgis.evidence.store import SqliteEvidenceRegistry
from kgis.extraction.client import is_deterministic
from kgis.extraction.config import ExtractorConfig
from kgis.extraction.documents import Chunk, Chunker, Document, DocumentSource
from kgis.extraction.extractor import LLMExtractor
from kgis.extraction.provenance import (
    build_chunk_evidence,
    build_document_artifact,
    build_document_evidence,
    chunk_evidence_ref,
    document_evidence_id,
)
from kgis.ids import DeterministicIdStrategy, IdStrategy, new_run_id
from kgis.report import DryRunPlan, IngestionReport
from kgis.validate import CandidateValidator, OntologyCandidateValidator

DEFAULT_BATCH_SIZE = 500
DEFAULT_CONCURRENCY = 4


@dataclass(frozen=True)
class _WorkItem:
    """One unit of parallel work: run one extractor over one chunk."""

    order: int
    document: Document
    chunk: Chunk
    extractor: LLMExtractor
    context: BuildContext


@dataclass(frozen=True)
class _WorkOutcome:
    """The result of one work item — candidates on success, a message on failure."""

    item: _WorkItem
    candidates: tuple[Candidate, ...]
    error: str | None


class ExtractionPipeline:
    """A configured LLM-extraction job (satisfies `kg_contracts.IngestJob`).

    Reusable and side-effect-free until `run()`: constructing one touches no
    document and submits nothing.
    """

    def __init__(
        self,
        *,
        graph_id: str,
        document_source: DocumentSource,
        chunker: Chunker,
        extractors: Sequence[ExtractorConfig],
        client: CompletionClient,
        sink: CandidateSink,
        evidence_registry: SqliteEvidenceRegistry,
        producer: str = "kgis.extraction",
        ontology_version: str = "unversioned",
        candidate_validator: CandidateValidator | None = None,
        clock: Clock | None = None,
        ids: IdStrategy | None = None,
        run_id: str | None = None,
        ledger_reader: LedgerReader | None = None,
        concurrency: int = DEFAULT_CONCURRENCY,
        batch_size: int = DEFAULT_BATCH_SIZE,
        emit_document_artifacts: bool = False,
        job_id: str | None = None,
    ) -> None:
        if not extractors:
            raise ValueError("ExtractionPipeline requires at least one extractor")
        if concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")

        self._graph_id = graph_id
        self._document_source = document_source
        self._chunker = chunker
        self._extractor_configs = tuple(extractors)
        self._client = client
        self._sink = sink
        self._registry = evidence_registry
        self._producer = producer
        self._ontology_version = ontology_version
        self._candidate_validator = candidate_validator or OntologyCandidateValidator(None)
        self._clock = clock or SystemClock()
        self._ids = ids or DeterministicIdStrategy()
        self._run_id = run_id
        self._ledger_reader = ledger_reader
        self._concurrency = concurrency
        self._batch_size = batch_size
        self._emit_document_artifacts = emit_document_artifacts
        self._job_id = job_id or new_run_id().replace("run_", "job_")
        self._extractors = tuple(
            LLMExtractor(config, client) for config in self._extractor_configs
        )

    @property
    def job_id(self) -> str:
        return self._job_id

    def run(self) -> IngestionReport:
        """Extract, create evidence, and submit candidates to the sink."""
        return self._execute(submit=True)

    def plan(self) -> IngestionReport:
        """Dry-run: extract and show what `run()` would submit, submitting none.

        Honest about nondeterminism — against a non-`deterministic` client the
        report carries a `nondeterministic_plan` warning, because a later run
        may extract different candidates from the same documents.
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
            source_type=self._document_source.source_type,
            source_locator=self._document_source.locator,
        )
        if not submit and not is_deterministic(self._client):
            report.warn(
                "nondeterministic_plan",
                "LLM extraction is nondeterministic: this plan reflects one "
                "extraction pass and a later run() may submit different "
                "candidates unless the completion client is a replay/pinned "
                "(deterministic) client.",
            )

        started = self._clock.monotonic()
        planned = self._collect(report, run_id, submit=submit)

        if submit:
            self._submit_all(planned, report)
        else:
            report.plan = self._build_plan(planned)

        report.kind_counts = _count_kinds(planned)
        report.elapsed_seconds = self._clock.monotonic() - started
        return report

    def _collect(
        self, report: IngestionReport, run_id: str, *, submit: bool
    ) -> list[Candidate]:
        """Extract in parallel, then reduce in deterministic order.

        The parallel phase only calls the model, parses, and builds — no shared
        registry or sink. The single-threaded reduce phase writes evidence and
        admits candidates, so SQLite connections stay confined to one thread.
        """
        items = self._plan_work(run_id)
        outcomes = self._extract_all(items, report)

        planned: list[Candidate] = []
        seen_keys: set[str] = set()

        # Document-level artifacts (and their evidence) are emitted once per
        # document, before that document's extracted facts, so ordering stays
        # deterministic.
        artifacts_done: set[str] = set()

        for outcome in outcomes:
            if self._emit_document_artifacts:
                doc = outcome.item.document
                if doc.doc_id not in artifacts_done:
                    artifacts_done.add(doc.doc_id)
                    artifact = self._build_document_artifact(doc, run_id)
                    if self._admit(artifact, report, seen_keys):
                        if submit:
                            self._write_document_evidence(doc, artifact.candidate_id)
                        planned.append(
                            self._cite_document(artifact, doc)
                        )
            if outcome.error is not None:
                continue
            for candidate in outcome.candidates:
                report.candidates_built += 1
                cited = self._cite_chunk(candidate, outcome.item)
                if not self._admit(cited, report, seen_keys):
                    continue
                if submit:
                    self._write_chunk_evidence(outcome.item, cited.candidate_id)
                planned.append(cited)

        return planned

    def _plan_work(self, run_id: str) -> list[_WorkItem]:
        """Enumerate (document, chunk, extractor) work in a fixed order."""
        items: list[_WorkItem] = []
        order = 0
        for document in self._document_source.documents():
            for chunk in self._chunker.chunk(document):
                for extractor in self._extractors:
                    context = self._context_for(extractor.config, run_id)
                    items.append(
                        _WorkItem(
                            order=order,
                            document=document,
                            chunk=chunk,
                            extractor=extractor,
                            context=context,
                        )
                    )
                    order += 1
        return items

    def _extract_all(
        self, items: Sequence[_WorkItem], report: IngestionReport
    ) -> list[_WorkOutcome]:
        """Run all work items in a bounded thread pool, preserving input order.

        `executor.map` yields results in the order the items were submitted,
        not the order they finished — so the reduce phase is deterministic even
        though extraction is concurrent.
        """
        if not items:
            return []
        report.records_read = len({(item.document.doc_id, item.chunk.fragment) for item in items})
        max_workers = min(self._concurrency, len(items))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            outcomes = list(pool.map(self._run_one, items))
        for outcome in outcomes:
            if outcome.error is not None:
                report.fail(outcome.error)
        return outcomes

    def _run_one(self, item: _WorkItem) -> _WorkOutcome:
        """Extract one (chunk, extractor). Failure is captured, never raised.

        Any exception — a model/network error, a malformed response, an
        un-buildable row — becomes a reported failure so a single extractor
        cannot take down the run or its siblings (spec §9). The exception type
        is included so a genuine bug is still visible in the failures list.
        """
        try:
            candidates = item.extractor.extract(item.chunk, item.context)
            return _WorkOutcome(item=item, candidates=tuple(candidates), error=None)
        except Exception as exc:  # noqa: BLE001 - failure isolation is the contract here
            message = (
                f"extractor={item.extractor.name} doc={item.document.doc_id} "
                f"chunk={item.chunk.fragment}: {type(exc).__name__}: {exc}"
            )
            return _WorkOutcome(item=item, candidates=(), error=message)

    def _admit(
        self, candidate: Candidate, report: IngestionReport, seen_keys: set[str]
    ) -> bool:
        """Intra-run dedup then candidate-tier validation — mirrors the pipeline.

        Dedup first (a repeat of an admitted key is not a new observation),
        then the validator; the key is reserved only after validation passes,
        so a rejected candidate does not silence the next same-key sibling.
        """
        if candidate.semantic_key in seen_keys:
            report.candidates_suppressed += 1
            return False
        verdict = self._candidate_validator.validate(candidate)
        if not verdict.valid:
            report.note_candidate_rejection(verdict)
            return False
        seen_keys.add(candidate.semantic_key)
        return True

    def _cite_chunk(self, candidate: Candidate, item: _WorkItem) -> Candidate:
        """Attach the passage's `DERIVED_FROM` evidence ref to the candidate."""
        ref = chunk_evidence_ref(item.chunk, item.extractor.config)
        return _with_ref(candidate, ref)

    def _cite_document(self, artifact: Candidate, document: Document) -> Candidate:
        ref = EvidenceRef(
            evidence_id=document_evidence_id(document),
            relationship=EvidenceRelationship.DERIVED_FROM,
        )
        return _with_ref(artifact, ref)

    def _write_chunk_evidence(self, item: _WorkItem, subject_id: str) -> None:
        evidence = build_chunk_evidence(
            item.chunk, item.extractor.config, observed_at=self._clock.now()
        )
        self._registry.put(evidence)
        self._registry.add_refs(subject_id, [chunk_evidence_ref(item.chunk, item.extractor.config)])

    def _write_document_evidence(self, document: Document, subject_id: str) -> None:
        evidence = build_document_evidence(document, observed_at=self._clock.now())
        self._registry.put(evidence)
        self._registry.add_refs(
            subject_id,
            [
                EvidenceRef(
                    evidence_id=document_evidence_id(document),
                    relationship=EvidenceRelationship.DERIVED_FROM,
                )
            ],
        )

    def _build_document_artifact(self, document: Document, run_id: str) -> Candidate:
        semantic_key = f"artifact/source_document/{document.doc_id}"
        scores = SourceScoring(source_reliability=1.0).to_scores()
        return build_document_artifact(
            document,
            graph_id=self._graph_id,
            producer=self._producer,
            producer_run_id=run_id,
            ontology_version=self._ontology_version,
            scores=scores,
            candidate_id=self._ids.candidate_id(
                graph_id=self._graph_id,
                candidate_kind="artifact",
                semantic_key=semantic_key,
            ),
            trace_id=self._ids.trace_id(
                run_id=run_id,
                graph_id=self._graph_id,
                candidate_kind="artifact",
                semantic_key=semantic_key,
            ),
            created_at=self._clock.now(),
        )

    def _context_for(self, config: ExtractorConfig, run_id: str) -> BuildContext:
        """Per-extractor build context: its own scoring and producer identity."""
        return BuildContext(
            graph_id=self._graph_id,
            producer=config.producer(self._producer),
            producer_run_id=run_id,
            ontology_version=self._ontology_version,
            scoring=config.scoring,
            clock=self._clock,
            ids=self._ids,
        )

    def _submit_all(self, planned: Sequence[Candidate], report: IngestionReport) -> None:
        for batch in _batched(planned, self._batch_size):
            result = self._sink.submit(batch)
            for outcome in result.outcomes:
                report.record(outcome)
                if outcome.status is SubmissionStatus.RECEIVED:
                    report.candidates_submitted += 1

    def _build_plan(self, planned: Sequence[Candidate]) -> DryRunPlan:
        return DryRunPlan(
            would_submit=len(planned),
            by_kind=_count_kinds(planned),
            candidates=tuple(planned),
            truncated=False,
            ledger_duplicates=self._count_ledger_duplicates(planned),
        )

    def _count_ledger_duplicates(self, planned: Sequence[Candidate]) -> int | None:
        """Predict what the sink would reject as DUPLICATE — `None` if unchecked.

        An honest null (ADR-0009): absent a `LedgerReader` we did not check, and
        say so rather than reporting a comforting zero.
        """
        if self._ledger_reader is None:
            return None
        existing = {
            entry.candidate.semantic_key
            for entry in self._ledger_reader.ledger_entries()
            if entry.candidate.graph_id == self._graph_id
        }
        return sum(1 for candidate in planned if candidate.semantic_key in existing)


def _with_ref(candidate: Candidate, ref: EvidenceRef) -> Candidate:
    """Return a copy of `candidate` with `ref` appended to its evidence refs.

    Candidates are frozen; `model_copy` is the only way to attach the passage
    citation the builder could not know about.
    """
    refs = (*candidate.evidence_refs, ref)
    return candidate.model_copy(update={"evidence_refs": refs})


def _batched(items: Sequence[Candidate], size: int) -> list[list[Candidate]]:
    return [list(items[start : start + size]) for start in range(0, len(items), size)]


def _count_kinds(candidates: Sequence[Candidate]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        counts[candidate.candidate_kind] = counts.get(candidate.candidate_kind, 0) + 1
    return dict(sorted(counts.items()))
