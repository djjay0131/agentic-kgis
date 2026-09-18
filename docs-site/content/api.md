# API basics

A curated map of the key public entry points — not exhaustive generated
reference. It shows *what to import and from where*. For the full surface, read
each package's `__init__.py`; for the reasoning behind a design, follow the ADR
links in [Concepts](concepts.md).

## The pipeline and its stages — `kgis`

The top-level `kgis` package is the ingestion engine.

```python
from kgis import IngestPipeline                    # sequences the stages
from kgis.sources import (                          # RecordReader adapters
    RecordReader,
    IterableRecordReader,
    CsvRecordReader,
    JsonRecordReader,
)
from kgis.normalize import (                         # coerce raw fields to a schema
    Normalizer,
    SchemaNormalizer,
    PassthroughNormalizer,
    FieldSpec,
)
from kgis.builders import (                          # NormalizedRecord -> Candidate(s)
    CandidateBuilder,
    CompositeCandidateBuilder,
    EntityCandidateBuilder,
    AttributeCandidateBuilder,
    RelationCandidateBuilder,
    SourceScoring,
    entity_semantic_key,
)
from kgis.validate import (                          # two-tier validation
    RecordValidator,
    CandidateValidator,
    OntologyCandidateValidator,
)
from kgis.ontology import Ontology
from kgis.clock import Clock, FixedClock, SystemClock
from kgis.ids import DeterministicIdStrategy, RandomIdStrategy, new_run_id
from kgis.report import IngestionReport, DryRunPlan, IngestWarning
```

`IngestPipeline.run()` executes and returns an `IngestionReport`;
`IngestPipeline.plan()` is a dry run with a `DryRunPlan` attached.

## Structured sync — `kgis.structured`

```python
from kgis.structured import (
    StructuredSyncConfig,        # declarative source + mapping -> pipeline
    RowProvider, Snapshot,       # the source port (protocols)
    SqliteRowProvider,           # reference provider over a sqlite3.Connection
    DbapiRowProvider,            # the same over any PEP-249 connection
    StructuredRecordReader,      # RowProvider -> RecordReader adapter
    StructuredEvidenceRecorder,  # per-row Evidence, idempotent
    source_evidence_id,
)
```

`StructuredSyncConfig(...).build_pipeline(sink=..., ledger_reader=...)` wires a
standard `IngestPipeline`. See [Structured sync](usage/structured-sync.md).

## LLM extraction — `kgis.extraction`

```python
from kgis.extraction import (
    ExtractionPipeline,          # documents -> extractors -> evidence -> sink
    ExtractorConfig,             # one configured extractor (data, not code)
    Document, DocumentSource, IterableDocumentSource,
    Chunker, ParagraphChunker, FixedWindowChunker, WholeDocumentChunker,
    CompletionClient,            # the injected LLM seam (re-exported contract)
    RecordingCompletionClient,   # capture a live pass...
    ReplayCompletionClient,      # ...and replay it deterministically
    ReplayMiss, is_deterministic,
    JsonItemsParser, OutputParser,
)
```

See [LLM extraction](usage/llm-extraction.md).

## Persistence — the two stores KGIS provides

```python
from kgis.ledger import (
    SqliteCandidateLedger,       # the durable CandidateSink + LedgerReader
    IdentityMode, IdentityResolver,   # adoption-gating toggles (ADR-0014)
    LedgerRow, IllegalTransitionError,
    open_ledger_db,
)
from kgis.evidence import (
    SqliteEvidenceRegistry,      # resolvable evidence storage
    EvidenceNotFoundError,
    open_evidence_db,
)
```

## The frozen contracts — `kg_contracts`

The stable ports layer everything depends on. The most important names:

```python
from kg_contracts import (
    Candidate, CandidateScores, CandidateEnvelope,   # the universal seam
    EntityCandidate, AttributeAssertionCandidate, RelationCandidate,
    CandidateSink,               # the only write surface
    EntityRef,                   # namespaced identity (no bare Label:key)
    Evidence, EvidenceRef, EvidenceAvailability, AbsenceReason, Provenance,
    ProcessingState,             # candidate lifecycle state
    CONTRACT_VERSION,
)
from kg_contracts.testing.memory import MemoryCandidateSink   # in-memory sink
```

!!! note "`CandidateSink` is the seam you build against"
    Adapter-internal writer protocols (`GraphWriter`, `GraphMutationStore`, …)
    are intentionally *not* part of the consumer-facing surface. If you are
    integrating KGIS, you submit through `CandidateSink` — that is the contract.

## Evaluation — `kg_eval`

The honest-null evaluation harness (ADR-0009):

```python
from kg_eval import (
    GoldSet, GoldEntity, GoldRelation, GoldAttribute, EvidenceSpan,
    ArmConfig, ArmOutput,
    evaluate_extraction, evaluate_arms,
    ExtractionMetrics, MetricValue,          # MetricValue is None + reason when unmeasurable
    compare_arms, AblationResult, AblationVerdict,
    BootstrapConfig, bootstrap_ci,           # seeded, reproducible intervals
    render_json, render_markdown,            # one result model, two renderings
)
```

`kg_eval` grades extraction *arms* against a gold set into reproducible metrics.
Under the honest-null policy a metric is `None` with a reason when it cannot be
measured (never a fabricated `0.0`), and an ablation reports
`INSUFFICIENT_EVIDENCE` / `NO_IMPROVEMENT` rather than a false win.

## Where to read more

- Package exports: `src/kgis/__init__.py`, `src/kg_contracts/__init__.py`,
  `src/kg_eval/__init__.py`, and the subpackage `__init__.py` files.
- Decisions: `llm/governance/adr/README.md` (the ADR index).
- The design spec: `llm/specs/2026-07-09-kgis-kgcs-design.md`.
