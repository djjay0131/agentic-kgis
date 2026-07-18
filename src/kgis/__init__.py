"""kgis: the deterministic ingestion engine over the `kg_contracts` ports.

Sprint 1 scope: structured-mode ingestion only —
`Source → Read → Normalize → Validate → Create Candidate(s) → CandidateSink
→ IngestReport`. No LLM extraction, no entity resolution, no graph writes;
those arrive in later plans. The one public write surface anywhere in here is
`kg_contracts.CandidateSink`.

The stages are ports, injected and independently testable; `IngestPipeline`
sequences them. Determinism is a property of the configured pipeline (inject
`FixedClock` + `DeterministicIdStrategy`), not of the harness.
"""

from kgis.builders import (
    AttributeCandidateBuilder,
    BuildContext,
    CandidateBuilder,
    CompositeCandidateBuilder,
    EntityCandidateBuilder,
    RelationCandidateBuilder,
    SourceScoring,
    entity_semantic_key,
)
from kgis.clock import Clock, FixedClock, SystemClock
from kgis.errors import ConfigurationError, KgisError, RecordDataError, SourceReadError
from kgis.ids import DeterministicIdStrategy, IdStrategy, RandomIdStrategy, new_run_id
from kgis.normalize import (
    FieldSpec,
    Normalizer,
    PassthroughNormalizer,
    SchemaNormalizer,
)
from kgis.ontology import CoverageCounter, Ontology, OntologyCoverage
from kgis.pipeline import IngestPipeline
from kgis.records import NormalizedRecord, RecordIssue, SourceRecord
from kgis.report import DryRunPlan, IngestionReport, IngestWarning
from kgis.sources import (
    CsvRecordReader,
    IterableRecordReader,
    JsonRecordReader,
    RecordReader,
)
from kgis.validate import (
    CandidateValidator,
    CompositeRecordValidator,
    IssueValidator,
    OntologyCandidateValidator,
    RecordValidation,
    RecordValidator,
    RequiredValuesValidator,
)

__all__ = [
    # pipeline
    "IngestPipeline",
    # sources
    "CsvRecordReader",
    "IterableRecordReader",
    "JsonRecordReader",
    "RecordReader",
    # normalization
    "FieldSpec",
    "Normalizer",
    "PassthroughNormalizer",
    "SchemaNormalizer",
    # records
    "NormalizedRecord",
    "RecordIssue",
    "SourceRecord",
    # validation
    "CandidateValidator",
    "CompositeRecordValidator",
    "IssueValidator",
    "OntologyCandidateValidator",
    "RecordValidation",
    "RecordValidator",
    "RequiredValuesValidator",
    # ontology
    "CoverageCounter",
    "Ontology",
    "OntologyCoverage",
    # builders
    "AttributeCandidateBuilder",
    "BuildContext",
    "CandidateBuilder",
    "CompositeCandidateBuilder",
    "EntityCandidateBuilder",
    "RelationCandidateBuilder",
    "SourceScoring",
    "entity_semantic_key",
    # report
    "DryRunPlan",
    "IngestionReport",
    "IngestWarning",
    # clock / ids
    "Clock",
    "FixedClock",
    "SystemClock",
    "DeterministicIdStrategy",
    "IdStrategy",
    "RandomIdStrategy",
    "new_run_id",
    # errors
    "ConfigurationError",
    "KgisError",
    "RecordDataError",
    "SourceReadError",
]
