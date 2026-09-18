# Quickstart

This walks through a minimal, deterministic end-to-end ingest: read records →
normalize → validate → build candidates → submit them to a `CandidateSink`, then
read the report. It mirrors the way pipelines are assembled in the test suite
(`tests/kgis/scenarios.py`).

## Install

KGIS is a Python package (Python 3.11+). With [`uv`](https://docs.astral.sh/uv/):

```bash
uv add agentic-kgis          # or: pip install agentic-kgis
```

## A minimal pipeline

We ingest three player rows into an in-memory sink. Every stage is explicit and
injected, so you can see exactly what the pipeline does.

```python
from datetime import UTC, datetime

from kg_contracts.testing.memory import MemoryCandidateSink
from kgis import IngestPipeline
from kgis.builders import (
    AttributeCandidateBuilder,
    CompositeCandidateBuilder,
    EntityCandidateBuilder,
    RelationCandidateBuilder,
    SourceScoring,
)
from kgis.clock import FixedClock
from kgis.ids import DeterministicIdStrategy
from kgis.normalize import FieldSpec, SchemaNormalizer
from kgis.ontology import Ontology
from kgis.sources import IterableRecordReader

PLAYERS = (
    {"id": "1", "name": "Ada", "team": "10", "height_cm": "170"},
    {"id": "2", "name": "Grace", "team": "10", "height_cm": "175"},
    {"id": "3", "name": "Alan", "team": "20", "height_cm": "180"},
)

# 1. Normalize: coerce raw string fields to a typed schema.
normalizer = SchemaNormalizer(
    [
        FieldSpec(name="id", type="str", required=True),
        FieldSpec(name="name", type="str"),
        FieldSpec(name="team", type="str"),
        FieldSpec(name="height_cm", type="int"),
    ]
)

# 2. Build: one row becomes an entity, an attribute assertion, and a relation.
#    Identity is namespaced — EntityRef{entity_type, namespace, key} — never a
#    bare "Player:1".
entity = EntityCandidateBuilder(
    entity_type="Player", namespace="usssa", key_field="id", display_name_field="name"
)
builder = CompositeCandidateBuilder(
    [
        entity,
        AttributeCandidateBuilder(subject=entity, attribute_fields=("height_cm",)),
        RelationCandidateBuilder(
            relation_type="PLAYS_FOR",
            subject_type="Player",
            subject_namespace="usssa",
            subject_key_field="id",
            object_type="Team",
            object_namespace="usssa",
            object_key_field="team",
        ),
    ]
)

# 3. An ontology to validate candidates against (optional but recommended).
ontology = Ontology(
    version="1",
    entity_types=frozenset({"Player", "Team"}),
    relation_types=frozenset({"PLAYS_FOR"}),
    attributes=frozenset({"height_cm"}),
)

# 4. The sink — the ONLY write surface. Here, in-memory for a demo.
sink = MemoryCandidateSink()

# 5. Wire the pipeline. FixedClock + DeterministicIdStrategy make it deterministic.
pipeline = IngestPipeline(
    graph_id="baseball",
    reader=IterableRecordReader(PLAYERS),
    normalizer=normalizer,
    builder=builder,
    sink=sink,
    scoring=SourceScoring(source_reliability=0.8),
    ontology=ontology,
    clock=FixedClock(datetime(2026, 7, 14, tzinfo=UTC)),
    ids=DeterministicIdStrategy(),
    run_id="run-fixed",
    job_id="job-fixed",
)

report = pipeline.run()
print(report.summary())
```

Note the two confidence axes: `SourceScoring(source_reliability=0.8)` sets *how
trustworthy the source is*; `extraction_confidence` defaults to `1.0` here
because a structured read is exact. They are never a single collapsed number.

## Reading the report

`run()` returns an `IngestionReport` — a stage-by-stage account of what happened,
not just a success flag:

```python
report.records_read          # 3
report.candidates_built      # 9  (3 entities + 3 attributes + 3 relations)
report.candidates_submitted  # 9
report.received              # 9  (accepted by the sink)
report.duplicates            # 0
report.succeeded             # True
report.summary()             # one-line human summary

sink.received()              # the list of Candidate objects the sink accepted
```

## Plan vs. run

Call `plan()` instead of `run()` for a **dry run**: it executes every stage
*except* submission and returns the same report shape with a `DryRunPlan`
attached (`report.plan.would_submit`, `report.plan.by_kind`). Nothing is written.

```python
dry = pipeline.plan()
print(dry.plan.would_submit)   # what a real run would submit
```

!!! tip "Determinism is opt-in"
    Deterministic output requires injecting `FixedClock` +
    `DeterministicIdStrategy` (as above). With the defaults (`SystemClock`,
    `RandomIdStrategy`) each run gets fresh timestamps and IDs.

## Next steps

- [**Structured sync**](structured-sync.md) — ingest from a real database with
  snapshot semantics and cross-run idempotency via a durable ledger.
- [**LLM extraction**](llm-extraction.md) — ingest from documents with
  first-class evidence and provenance.
- [**API basics**](../api.md) — the key import map.
