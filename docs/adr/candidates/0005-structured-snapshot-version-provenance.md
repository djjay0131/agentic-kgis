# ADR candidate: A candidate has no first-class home for its source snapshot version

Status: Proposed (candidate)
Date: 2026-08-21
Raised by: Plan 4 — Structured Sync (kgis)

## Context

Deterministic structured sync reads rows from a **pinned snapshot** of a
database source (spec §5.8, ADR-0009): a repeatable-read view with a stable
`version` token. Two runs over the same snapshot see byte-identical rows, which
is what lets `plan()` and `run()` agree; a re-sync that read changed data gets a
new version, which is the honest signal that it observed something different.

That snapshot version is genuine provenance an operator will want on the
resulting candidates — *which* read of the source produced this fact? But the
frozen contract has nowhere purpose-built to record it:

- `SourceCoordinates` (spec §5.2) is `source_type` + `locator` + `fragment`.
  `fragment` is the per-row anchor (a primary key); `locator` names the source
  as a whole. None of the three is a source-version/cursor/watermark field.
- `CandidateEnvelope` has `content_hash` (a change-detection signal for the
  candidate's *content*, not the source read) and no source-version field.

## Decision (proposed)

Recognize a **source snapshot version / cursor** as first-class ingestion
provenance and give it a home on the contract — most likely an optional
`source_version: str | None` (or `snapshot`/`cursor`) field on
`SourceCoordinates`, alongside `fragment`. It would carry a database
transaction/snapshot id, a watermark value, or a deterministic content token,
and be stamped onto every candidate a structured run produces.

Until the owner decides, Plan 4 ships a `kgis`-local workaround: the
`StructuredRecordReader` encodes the snapshot version into the `locator`
(`sqlite://players@snapshot=<version>`) by default, so the version travels on
each candidate's `source_coordinates` without any contract change. This is
toggleable (`include_snapshot_in_locator=False`) for callers who want the
locator to stay snapshot-independent. The snapshot version is also exposed
directly on the reader (`reader.snapshot_version`) and drives deterministic
evidence ids (`kgis.structured.source_evidence_id`).

## Rationale

Overloading `locator` works but conflates two things the contract deliberately
keeps apart: *where* a source is (stable) and *when/which version* of it was
read (varying). It also means two runs over different snapshots produce
candidates whose `locator` differs, which is mildly surprising for a field
documented as "the source as a whole". A dedicated field keeps `locator` stable
across data revisions while still recording the read version, and every future
structured/streaming source (a Kafka offset, a CDC LSN, a Spanner read
timestamp) wants exactly this field.

Idempotency is unaffected either way: `candidate_id` is content-addressed on
`(graph_id, kind, semantic_key)`, never on coordinates, so the ledger recognizes
the same fact as a duplicate across snapshots regardless of where the version
lives.

## Alternatives Considered

### Keep encoding the version in `locator` permanently

Zero contract change (what Plan 4 does). The cost is the `where`/`which-version`
conflation above and per-snapshot `locator` churn; acceptable as a workaround,
fragmenting if every source reinvents its own encoding.

### Put it in `content_hash` or `representations`

Wrong homes: `content_hash` is about the candidate's content changing, and
`representations` are feature views. Neither means "the source read version".

## Consequences

### Positive

- Source read-version provenance becomes first-class and uniform across
  structured, CDC, and streaming sources.
- `locator` regains its documented "source as a whole" stability.

### Negative / Tradeoffs

- One more optional field on a frozen, widely-constructed contract model.

### Risks

- Low. Purely additive; the workaround already produces the value, so promotion
  is a move, not a redesign.

## Impacted Areas

- [x] Domain model
- [x] Implementation

## Related Documents

- `src/kgis/structured/reader.py` (locator workaround)
- `src/kgis/structured/providers.py` (snapshot version derivation)
- `docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md` §5.8
- `docs/adr/0009-kg-eval-and-honest-null.md` (plan/run honesty)

## Supersedes

None.

## Superseded By

None.
