"""`StructuredSyncConfig`: the explicit mapping from a source to a pipeline.

Structured sync's "mapping" is just the Sprint 1 stages named together — a
`Normalizer` (source columns → canonical fields) and a `CandidateBuilder`
(canonical fields → existing candidate variants). This config is the single
place they are wired onto a `RowProvider`, so a caller states the source, the
schema, and the builder, and gets back a fully-wired `IngestPipeline` with the
structured reader already in place.

Nothing here invents a graph model. It reuses `SchemaNormalizer` /
`CompositeCandidateBuilder` / the entity/attribute/relation builders verbatim
(`kgis.builders`), and the pipeline it returns is the same `IngestPipeline`
every other source uses — with the same `plan()`/`run()`, the same
`CandidateSink` write surface, and no graph-write surface anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from kg_contracts.stores import CandidateSink, LedgerReader
from kgis.builders import CandidateBuilder, SourceScoring
from kgis.clock import Clock
from kgis.ids import IdStrategy
from kgis.normalize import Normalizer
from kgis.ontology import Ontology
from kgis.pipeline import IngestPipeline
from kgis.structured.port import RowProvider
from kgis.structured.reader import DEFAULT_BATCH_SIZE, StructuredRecordReader


@dataclass(frozen=True)
class StructuredSyncConfig:
    """A declarative structured-sync job: source + mapping + scoring.

    `build_pipeline()` is the only method that touches the source. The config
    itself is inert and reusable — assembling it opens no snapshot and submits
    nothing, exactly like constructing an `IngestPipeline`.
    """

    graph_id: str
    provider: RowProvider
    normalizer: Normalizer
    builder: CandidateBuilder
    scoring: SourceScoring
    ontology: Ontology | None = None
    producer: str = "kgis.structured"
    include_snapshot_in_locator: bool = True
    batch_size: int = DEFAULT_BATCH_SIZE
    reader_overrides: dict[str, object] = field(default_factory=dict)

    def reader(self) -> StructuredRecordReader:
        """A fresh structured reader over this config's provider."""
        return StructuredRecordReader(
            self.provider,
            batch_size=self.batch_size,
            include_snapshot_in_locator=self.include_snapshot_in_locator,
        )

    def build_pipeline(
        self,
        *,
        sink: CandidateSink,
        ledger_reader: LedgerReader | None = None,
        ids: IdStrategy | None = None,
        clock: Clock | None = None,
        run_id: str | None = None,
        job_id: str | None = None,
        ontology_strict: bool = True,
    ) -> IngestPipeline:
        """Wire the structured reader into a standard `IngestPipeline`.

        Everything past the reader is the Sprint 1 spine: no structured-specific
        submission path exists, so `plan()`/`run()` honesty and the ledger's
        cross-run idempotency come for free from the shared pipeline.
        """
        return IngestPipeline(
            graph_id=self.graph_id,
            reader=self.reader(),
            normalizer=self.normalizer,
            builder=self.builder,
            sink=sink,
            scoring=self.scoring,
            ontology=self.ontology,
            producer=self.producer,
            ledger_reader=ledger_reader,
            ids=ids,
            clock=clock,
            run_id=run_id,
            job_id=job_id,
            ontology_strict=ontology_strict,
            batch_size=self.batch_size,
        )
