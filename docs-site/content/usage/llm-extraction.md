# LLM extraction

LLM extraction ingests from **documents** rather than rows. Documents are
segmented into chunks with stable coordinates; per-entity-type extractors run in
parallel behind an injected `CompletionClient`; their structured output is parsed
and built into candidates by the *same* builders structured sync uses; each
candidate cites the passage it came from as resolvable `Evidence`; and
everything is submitted through `CandidateSink`. No vendor SDK appears anywhere —
the LLM is injected as a `CompletionClient` protocol.

## An extractor is data, not code

The unit of configuration is `ExtractorConfig`: one configured extractor for one
target entity type — a schema, a prompt template, a model id, a builder, and
scoring/version metadata. You typically run several (e.g. a player extractor and
a skill extractor) over the same documents.

```python
from kgis.builders import EntityCandidateBuilder, SourceScoring
from kgis.extraction.config import ExtractorConfig

player = ExtractorConfig(
    extractor_id="player",
    target_type="Player",
    builder=EntityCandidateBuilder(
        namespace="baseball",
        key_field="player_id",
        entity_type="Player",
        display_name_field="name",
    ),
    prompt_template="Extract players from:\n{text}",
    system_prompt="You extract Player entities.",
    model_id="fake-model-1",
    model_version="2026-08",
    extractor_version="1",
    prompt_version="p1",
    # Two axes: how trustworthy the source is, and how sure the extraction is.
    scoring=SourceScoring(source_reliability=0.7, extraction_confidence=0.5),
)
```

Note again the **two confidence axes**. For an LLM extraction,
`extraction_confidence` genuinely matters — a model guess is not an exact read —
and it stays separate from `source_reliability`, which scores the document.

## Documents in, candidates out

```python
from kgis.evidence.store import SqliteEvidenceRegistry
from kgis.extraction.documents import (
    Document,
    IterableDocumentSource,
    ParagraphChunker,
)
from kgis.extraction.runner import ExtractionPipeline
from kgis.ledger.store import SqliteCandidateLedger

doc = Document(
    doc_id="doc-1",
    text="Ada is a shortstop known for hitting.\n\nGrace coaches fielding.",
    source_type="scouting_report",
    locator="s3://reports/doc-1.txt",
)

ledger = SqliteCandidateLedger("baseball-ledger.db")
registry = SqliteEvidenceRegistry("baseball-evidence.db")

pipeline = ExtractionPipeline(
    graph_id="baseball",
    document_source=IterableDocumentSource([doc], source_type="scouting_report"),
    chunker=ParagraphChunker(),
    extractors=[player],                 # one or more ExtractorConfig
    client=my_completion_client,         # your injected CompletionClient
    sink=ledger,
    evidence_registry=registry,
)

report = pipeline.run()
print(report.candidates_built, report.candidates_submitted)
ledger.close()
registry.close()
```

The `CompletionClient` is a one-method protocol
(`complete(prompt, *, system=None) -> str`). You inject an adapter over whatever
model you use; KGIS imports no vendor SDK.

## Determinism: record then replay

A live model is **non-deterministic**, and KGIS is honest about it: `plan()`
warns rather than pretending a dry run predicts a live run byte-for-byte. To make
extraction reproducible, capture one real pass with `RecordingCompletionClient`
and replay it with `ReplayCompletionClient`:

```python
from kgis.extraction.client import RecordingCompletionClient, ReplayCompletionClient

# 1. Record: wrap the live client, run once — every prompt/response is captured.
recording = RecordingCompletionClient(live_client)
ExtractionPipeline(..., client=recording).run()

# 2. Replay: a deterministic client primed from the recording.
replay = ReplayCompletionClient.from_recording(recording)
ExtractionPipeline(..., client=replay, clock=FixedClock(...), run_id="run-fixed").run()
```

A `ReplayCompletionClient` raises `ReplayMiss` if asked for a prompt it never
recorded — replays can't silently drift. `is_deterministic(client)` tells you
whether a client advertises determinism.

## First-class evidence and provenance

Every extracted candidate cites the **chunk** it came from as resolvable
`Evidence` (and optionally the whole document as an artifact). The chunk
coordinates are stable — `document.text[start:end] == chunk.text` — so the
citation is a real, checkable fragment, not a vague pointer. Evidence is written
to the injected `SqliteEvidenceRegistry`, and a dangling reference *raises*
rather than being dropped (see [Concepts → Evidence](../concepts.md#evidence)).

## Failure isolation

If one extractor's model returns unparseable output, that failure is isolated:
the run yields a **partial report marked `incomplete=True`** with the failure
captured in `report.failures`, never a silent gap. Honest partial results beat a
false success.

## Next steps

- [**Concepts**](../concepts.md) — candidates, the ledger, evidence, identity,
  determinism.
- [**Evaluation**](../api.md#evaluation-kg_eval) — grade extraction arms with
  `kg_eval` under the honest-null policy.
