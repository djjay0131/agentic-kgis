# Sprint 1 — Core Ingestion Engine: report

Date: 2026-07-14
Branch: `feature/sprint-1-core-ingestion`
Scope: the first end-to-end deterministic ingestion pipeline in `src/kgis/`,
built entirely on the merged `kg_contracts` v2 interfaces. No graph writes, no
entity resolution, no LLM extraction, no GraphRAG — those are later plans.

---

## 1. Implementation summary

A project can now ingest structured data and produce `Candidate`s using only
the merged contracts, through one injected, deterministic pipeline:

```
RecordReader → Normalizer → RecordValidator → CandidateBuilder → CandidateValidator → CandidateSink
                                                                                          ↓
                                                                                   IngestionReport
```

Every stage is an injected port, independently testable, composed by
`IngestPipeline` (which satisfies `kg_contracts.IngestJob`).

Modules delivered (`src/kgis/`):

| Module | Responsibility |
|---|---|
| `clock.py` | Injected time (`Clock` / `SystemClock` / `FixedClock`); `now()` vs `monotonic()` kept separate |
| `ids.py` | `IdStrategy`; deterministic content-addressed IDs keyed on the *fact*, traces keyed on the *run* |
| `records.py` | `SourceRecord` / `NormalizedRecord` / `RecordIssue` — internal pipeline models, never contracts |
| `errors.py` | The few exceptions (a run stops, a record does not) |
| `sources/` | `RecordReader` port + iterable / CSV / JSON readers; no databases |
| `normalize.py` | Total, deterministic, format-erasing coercion to canonical types |
| `validate.py` | Two-tier validation (record tier + candidate tier) reusing the contract `FailureKind` |
| `ontology.py` | `Ontology` + coverage (unknown *and* unused terms; honest-null ratio) |
| `builders.py` | Entity / attribute / relation candidate builders; no graph models |
| `report.py` | `IngestionReport` extending the contract's `IngestReport` |
| `pipeline.py` | Orchestration, dry-run, idempotency, `CandidateSink` submission |
| `testing/` | Reusable `RecordReaderContract` suite (mirrors `kg_contracts.testing`) |

**Tests:** 310 kgis tests added; **481 pass repo-wide** (171 existing contract
tests unaffected). `ruff check src tests`, `mypy src` (strict) green. Delivered
as 8 small implement → test → verify → commit increments.

Every sprint-brief invariant is encoded as a law in `tests/kgis/test_invariants.py`:
same input → same candidates; dry-run == execution except submission;
validation failures never produce candidates; stage ordering; deterministic
replay; `CandidateSink` always receives valid candidates; plus cross-format
equivalence (CSV/JSON/JSON-Lines/iterable agree) and batch-of-one equivalence.

### How each brief requirement was met

- **Everything dependency-injected** — the pipeline owns no clock, IDs,
  scoring, ontology, or sink; it only sequences ports it was handed.
- **Uniform sources** — CSV, JSON, JSON-Lines, and Python iterables are
  interchangeable behind `RecordReader`; the pipeline cannot tell them apart.
- **Deterministic normalization** — no clock/locale/randomness; refuses to
  guess (`True` ≠ `1`, `"42.5"` ≠ int); repairs only the unambiguous
  (naive datetime → UTC, with a warning).
- **Validation rejects, never writes** — a rejected record contributes zero
  candidates; the candidate tier guards the sink.
- **Candidate creation is the only path** — builders emit only `Candidate`
  variants and cannot name a `CanonicalEntity`/`Assertion`.
- **CandidateSink integration** — the sole write surface; verified against
  `kg_contracts`' own `CandidateSinkContract`.
- **Rich reporting** — records processed, candidates emitted, validation
  failures, two kinds of duplicate, warnings, elapsed time, dry-run plan, and
  ontology coverage.
- **Dry-run** — a single `_plan()` spine builds exactly what execution submits
  and submits nothing.
- **Idempotency** — intra-run semantic-key suppression + cross-run sink dedup;
  deterministic IDs make a replay recognizable as the same facts.

---

## 2. Architecture observations

Three tensions between the frozen contracts and the requested pipeline shape
surfaced. None was resolved by redesigning a contract; each is filed as an ADR
candidate (`docs/adr/candidates/`) with an in-code workaround.

1. **`ValidationDecision` is candidate-scoped, but records are rejected before
   candidates exist** (candidate 0001). The invariant "validation failures
   never produce candidates" and the contract's required `candidate_id` cannot
   both hold at the record stage. Resolved with two-tier validation: a
   `kgis` `RecordValidation` (record tier) and the contract's
   `ValidationDecision` (candidate tier). The contract is not wrong — it is
   ledger-scoped, and the ledger only sees candidates.

2. **`Source.fetch()` yields `Candidate`, so the stages compose inward**
   (candidate 0002). The brief's linear `Source → Read → …` diagram inverts the
   actual dependency: read/normalize/validate/build are the *implementation* of
   a candidate source, not consumers of one. `IngestPipeline` is that
   composition. A thin `fetch()` facade is a deferred, additive follow-up.

3. **Two additive contract gaps** (candidate 0003): no public deterministic-ID
   helper on `kg_contracts` (so `kgis.ids` reimplements the Crockford encoder),
   and `GraphDescriptor` declares no attribute vocabulary (so ontology coverage
   can enforce entity/relation terms from the registry but not attributes).

One bug was caught by the sprint's own tests and fixed in place: `coverage_ratio`
reconstructed the declared term set from the used/unused fields, which made an
*unconstrained* ontology indistinguishable from a *fully covered* one and
reported 100 % coverage for a graph declaring no vocabulary — precisely the
reassuring lie ADR-0009's honest-null policy exists to prevent. The declared
vocabulary is now stored explicitly; both no-ontology and no-terms report an
honest `None`.

---

## 3. Performance observations

- **In-memory, deterministic, fast.** 481 tests run in ~1.2 s; the engine does
  no I/O beyond reading the source. No profiling was warranted at this scale.
- **Submission is batched** (`DEFAULT_BATCH_SIZE = 500`), and batch size is
  proven to be transport-only — a batch of 1 and a batch of 500 produce
  identical ledgers and identical reports. This is what lets the deferred
  streaming future (spec's batch-of-one → event) be a transport change, not a
  redesign.
- **Idempotency is O(candidates) memory** within a run: a `set` of seen
  semantic keys. Fine for the batch sizes in scope; a very large single run
  would want a bounded/streaming dedup, noted for Sprint 2.
- **Dry-run trades memory for fidelity.** `DryRunPlan` retains the *real* built
  candidates (not a summary) so "dry-run == execution" is byte-checkable. For a
  huge source this is the one place planning costs more than executing; the
  `truncated` flag exists so a cap on the retained list can never be mistaken
  for a small plan, but the cap itself is not yet wired (Sprint 2).
- **ID minting is a blake2b digest per candidate** — negligible, and pure, so
  it never becomes a determinism hazard.

---

## 4. Implementation pain points

- **The `ValidationDecision` key** (observation 1) was the sharpest: it forced
  a real decision about *where* rejection happens, early, before any pipeline
  code existed. Getting it right first is why the invariant holds cleanly.
- **`Source` returning `Candidate`** briefly inverted the mental model of the
  whole pipeline; the spec's module list resolved it, but only after reading it
  closely rather than trusting the brief's diagram.
- **`Candidate` is an `Annotated` union**, so `isinstance(x, Candidate)` raises
  `TypeError`. Tests assert against `CandidateEnvelope` and round-trip through
  `candidate_adapter` instead — the latter is a stronger check anyway.
- **No `SourceContract` existed** in `kg_contracts.testing` despite spec §10.2
  calling for reusable `Source` suites. Rather than depend on a missing
  contract, `kgis` ships its own `RecordReaderContract`; whether a canonical
  `Source` suite belongs in `kg_contracts` is bound up with candidate 0002.
- **Windows line endings**: git warns LF→CRLF on every file; harmless but
  noisy. A `.gitattributes` normalizing to LF would quiet it (Sprint 2 hygiene).
- **PowerShell here-strings** mangle multi-line commit messages; switched to
  `git commit -F <file>`.

---

## 5. Recommendations for Sprint 2

Ordered by leverage:

1. **Owner review of the three ADR candidates.** 0001 (record-scoped
   validation) and 0003-B (attribute vocabulary) both want small, additive
   `kg_contracts` changes that every later ingestion mode will otherwise work
   around independently. Deciding them now prevents divergence.
2. **The candidate ledger (Plan 2).** This sprint submits into the *memory*
   `CandidateSink`. A persistent ledger with the real `ProcessingState`
   lifecycle turns cross-run idempotency from a test fact into a durable one,
   and lets dry-run's ledger-duplicate count run against real history.
3. **Evidence registry (Plan 2).** The null-value rule ("a missing height
   asserts nothing") is correct but currently *silent*. `Evidence`'s ABSENT
   state is how the pipeline should say "we looked and found nothing"; wiring
   the registry lets absence be recorded rather than merely skipped.
4. **A `StructuredSource.fetch()` adapter** (candidate 0002) once a consumer
   needs the bare `Source` shape — small, and it closes the loop with the
   contract's named interface.
5. **A CLI** (`kgis ingest` / `kgis plan` / `kgis validate`, spec §6) over the
   pipeline — the dry-run/execute split is already the right shape for it.
6. **Streaming/bounded dedup and dry-run truncation** before the first
   genuinely large source, so memory stays O(1) in run size.
7. **`.gitattributes`** to normalize line endings and quiet the CRLF warnings.

The engine is production-quality for its scope: deterministic, honest in its
reporting, and structurally unable to bypass the candidate seam or touch a
graph. It is a foundation later plans can build on without relitigating it.
