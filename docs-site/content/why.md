# Why KGIS

Building a knowledge graph from messy, real-world data is easy to do badly. The
usual failure mode is to let *uncertainty become contamination*: an extractor
writes a probably-correct node straight into the graph, every downstream query
now has to remember to filter it out, and a later correction silently changes
answers nobody re-checked. KGIS exists to make that failure mode impossible.

## The problem

Adopter applications — a baseball analytics app, a construction-records app, a
research graph — all need the same thing: a way to pull data from many sources
into a governed graph, *with provenance*, *reproducibly*, and *without each app
reinventing ingestion*. What they do **not** want is:

- Ingestion code welded to one domain, so nothing is reusable.
- Extractors that write graph nodes directly, so a bad guess is now a fact.
- A single "confidence" number that conflates *how trustworthy the source is*
  with *how sure the extraction was*.
- Missing data recorded as `0.0`, which is indistinguishable from a real zero.
- Non-deterministic runs that can't be replayed or audited.

## The principles

KGIS is built around a small set of load-bearing commitments. Each is enforced
in code and recorded as an Architecture Decision Record (ADR).

### 1. Ingestion never writes a graph

The only write surface in all of `kgis` is
[`CandidateSink`](concepts.md#candidatesink). Ingestion emits **proposals**;
curation (KGCS) decides what becomes canonical. Uncertain candidates live in a
**candidate ledger**, never as ordinary graph nodes, so a graph traversal can
never accidentally treat a proposal as a real fact (ADR-0006, ADR-0010).

### 2. Separation of ingestion from curation

The `Candidate` seam splits the two halves cleanly. KGIS knows how to *read,
normalize, validate, and propose*; KGCS knows how to *resolve, merge, and
commit*. Neither reaches across the seam. This is what makes KGIS reusable
across unrelated domains.

### 3. Evidence-first, with honest nulls

Every candidate can cite the passage or row it came from as resolvable
`Evidence`. Evidence availability is always one of **PRESENT / ABSENT / ERROR**,
and a dangling evidence reference *raises* — it is never silently dropped. When
something can't be measured, KGIS records an **honest null** (a `None` with a
reason), not a comfortable `0.0` (ADR-0009).

### 4. Two confidence axes, kept distinct

KGIS never collapses trust into a single float. `source_reliability` (how
trustworthy the source is) and `extraction_confidence` (how sure this particular
extraction was) are separate, independently scored axes on `CandidateScores`. An
exact CSV read can be `extraction_confidence=1.0` while its
`source_reliability` is whatever the source deserves (ADR-0004 as amended).

### 5. Namespaced identity

Identity is structural: `EntityRef{entity_type, namespace, key}`, rendered as
`Label:namespace:key` (e.g. `Athlete:usssa:12345`) only at adapter boundaries.
The bare `Label:key` form is forbidden for cross-project use, because it says
nothing about *who issued the key*. Every canonical entity also has an immutable
internal identity ID that survives key corrections, merges, and splits
(ADR-0008).

### 6. Determinism and idempotency

A KGIS pipeline is deterministic when you inject a `FixedClock` and a
`DeterministicIdStrategy`: same input, byte-identical output. `candidate_id`s
are content-addressed, so re-ingesting the same data is idempotent — the durable
ledger dedups it across runs.

### 7. Frozen contracts as the shared seam

`kg_contracts` is a versioned, stable ports layer. Engines and adopters depend
on it; it does not depend on them. Changing it is a governed event, not a
casual edit — which is why several improvements ship as in-code workarounds that
respect the frozen contract, with the contract change deferred and documented in
an ADR.

## The payoff

Because of these principles, an adopter gets governed, auditable, reproducible
ingestion for free, and can answer "what does this system do for data
governance?" by pointing at the contracts rather than at a bespoke integration.

Read on: the [**Architecture**](architecture.md) page shows how the ports,
the Candidate seam, and the KGIS↔KGCS boundary fit together.
