"""LLM document-extraction ingestion mode (Plan 4, spec §6).

A config-driven front-end onto the shared candidate pipeline: documents are
segmented into chunks with stable coordinates, per-entity-type extractors run
in parallel behind an injected `CompletionClient`, their structured output is
parsed and built into the correct `Candidate` variant by the *same* builders
structured sync uses, each candidate cites the passage it came from as
resolvable `Evidence`, and everything is submitted through `CandidateSink`.

No vendor SDK appears here: the LLM is injected as a `CompletionClient`
protocol, and deterministic tests use the replay client. Extraction is
nondeterministic against a live model — `plan()` says so honestly.

The public surface is exposed here rather than on the top-level `kgis`
package; the orchestrator reconciles top-level re-exports during integration.
"""

from kg_contracts.ingestion import CompletionClient
from kgis.extraction.client import (
    RecordingCompletionClient,
    ReplayCompletionClient,
    ReplayMiss,
    StaticCompletionClient,
    is_deterministic,
    request_key,
)
from kgis.extraction.config import ExtractorConfig
from kgis.extraction.documents import (
    Chunk,
    Chunker,
    Document,
    DocumentSource,
    FixedWindowChunker,
    IterableDocumentSource,
    ParagraphChunker,
    WholeDocumentChunker,
)
from kgis.extraction.extractor import LLMExtractor
from kgis.extraction.parse import (
    ExtractedItem,
    ExtractionParseError,
    JsonItemsParser,
    OutputParser,
)
from kgis.extraction.provenance import (
    build_chunk_evidence,
    build_document_artifact,
    build_document_evidence,
    chunk_evidence_id,
    chunk_evidence_ref,
    document_evidence_id,
)
from kgis.extraction.runner import (
    DEFAULT_CONCURRENCY,
    ExtractionPipeline,
)

# CompletionClient is re-exported from the frozen contract (imported above) as
# the canonical injection seam, so callers import one name for it.

__all__ = [
    "DEFAULT_CONCURRENCY",
    "Chunk",
    "Chunker",
    "CompletionClient",
    "Document",
    "DocumentSource",
    "ExtractedItem",
    "ExtractionParseError",
    "ExtractionPipeline",
    "ExtractorConfig",
    "FixedWindowChunker",
    "IterableDocumentSource",
    "JsonItemsParser",
    "LLMExtractor",
    "OutputParser",
    "ParagraphChunker",
    "RecordingCompletionClient",
    "ReplayCompletionClient",
    "ReplayMiss",
    "StaticCompletionClient",
    "WholeDocumentChunker",
    "build_chunk_evidence",
    "build_document_artifact",
    "build_document_evidence",
    "chunk_evidence_id",
    "chunk_evidence_ref",
    "document_evidence_id",
    "is_deterministic",
    "request_key",
]
