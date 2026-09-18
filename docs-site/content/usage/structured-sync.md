# Structured sync

Structured sync ingests from a **database-shaped source** — a table, a query
result, any PEP-249 (DB-API) connection — through the *same* pipeline spine as
the quickstart. It is not a second ingestion architecture: a `RowProvider` is
pinned to a repeatable-read `Snapshot`, adapted to a `RecordReader` by
`StructuredRecordReader`, and from there normalize → validate → build →
`CandidateSink` is unchanged. There is no graph-write surface here, as everywhere
in `kgis`.

## The shape of a structured job

`StructuredSyncConfig` is a declarative, inert description of a job: source +
mapping (a `Normalizer` and a `CandidateBuilder`) + scoring. Constructing it
opens no snapshot and submits nothing. `build_pipeline()` is the only method that
touches the source.

```python
from datetime import UTC, datetime

from kgis.builders import (
    AttributeCandidateBuilder,
    CompositeCandidateBuilder,
    EntityCandidateBuilder,
    RelationCandidateBuilder,
    SourceScoring,
)
from kgis.clock import FixedClock
from kgis.ledger.store import SqliteCandidateLedger
from kgis.normalize import FieldSpec, SchemaNormalizer
from kgis.structured import SqliteRowProvider, StructuredSyncConfig


def make_config(conn) -> StructuredSyncConfig:
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
    return StructuredSyncConfig(
        graph_id="baseball",
        # The DB-API source, pinned to a repeatable-read snapshot on read.
        provider=SqliteRowProvider(conn, table="players", key_fields=("id",)),
        normalizer=SchemaNormalizer(
            [
                FieldSpec(name="id", type="str", required=True),
                FieldSpec(name="name", type="str"),
                FieldSpec(name="team", type="str"),
                FieldSpec(name="height_cm", type="int"),
            ]
        ),
        builder=builder,
        scoring=SourceScoring(source_reliability=0.9),
    )
```

`SqliteRowProvider` wraps an injected `sqlite3.Connection`; `DbapiRowProvider`
does the same over any PEP-249 connection. The provider is the injected *source
port* — KGIS never opens a database for you.

## Running the job through a durable ledger

The `CandidateSink` for a real job is usually the **persistent candidate
ledger**, `SqliteCandidateLedger`. Passing it as `ledger_reader` too gives the
pipeline cross-run idempotency for free.

```python
ledger = SqliteCandidateLedger("baseball-ledger.db")

pipeline = make_config(conn).build_pipeline(
    sink=ledger,
    ledger_reader=ledger,
    clock=FixedClock(datetime(2026, 8, 21, tzinfo=UTC)),
    run_id="run-fixed",
)

report = pipeline.run()
print(report.received)   # e.g. 9 = 3 entities + 3 attributes + 3 relations
ledger.close()
```

## `plan()` vs `run()`

As with any pipeline, `plan()` is a dry run (build everything, submit nothing)
and `run()` executes. On structured sync there is an important honesty
guarantee *and* a caveat:

!!! warning "Reuse the same pipeline instance for plan-then-run"
    `plan()` then `run()` on the **same** pipeline share one cached snapshot
    (the reader opens it once), so they see byte-identical rows — the dry run
    genuinely predicts the execution. Two *separate* pipelines each open their
    own snapshot with no interlock; if the source mutates between them they can
    diverge. Reuse one pipeline/reader instance for both, or compare
    `config.reader().snapshot_version` across the two.

Even without that discipline a mid-flight mutation is *detectable, not silent*:
`candidate_id` is content-addressed (so the same fact still dedups in the
ledger) and the snapshot version is an observable token in the coordinates
locator.

## Cross-run idempotency

Because `candidate_id`s are content-addressed and the ledger is durable,
**re-ingesting the same snapshot is idempotent** — the second run submits the
same candidates and the ledger recognizes them as duplicates rather than
creating new rows. This is what makes a scheduled re-sync safe.

## Per-row evidence

Structured sync can record **per-row `Evidence`** through the evidence registry,
produced and linked idempotently. Use `StructuredEvidenceRecorder` and
`source_evidence_id` (from `kgis.structured`) with a `SqliteEvidenceRegistry`.
Each candidate then cites the exact source row it came from, and that reference
resolves back through the registry — evidence is never a dangling pointer (see
[Concepts → Evidence](../concepts.md#evidence)).

## Next steps

- [**LLM extraction**](llm-extraction.md) — the document-driven mode.
- [**Concepts**](../concepts.md) — the ledger, evidence, identity, determinism.
