# What is KGIS

**KGIS (Knowledge Graph Ingestion Service)** is a deterministic, evidence-first
platform for turning raw data — database rows, documents, LLM output — into
*proposed* graph facts. It is domain-neutral infrastructure: the same engine
ingests baseball rosters, construction records, or research papers, and it never
guesses about what is true. Every fact it emits carries where it came from, how
reliable that source is, and how confident the extraction was.

The single most important thing to understand about KGIS is what it *doesn't* do:

!!! note "KGIS never writes a graph"
    KGIS has exactly one write surface anywhere in its code:
    [`CandidateSink`](concepts.md#candidatesink). It emits **proposals**
    (`Candidate`s), never graph mutations. Deciding which proposals become
    canonical facts — resolution, merging, curation — is a separate concern,
    owned by KGCS. This split is deliberate and enforced by the contracts
    (ADR-0010).

## The three packages

KGIS ships as three Python packages with a strict separation of concerns:

| Package | Role |
|---|---|
| **`kg_contracts`** | The **frozen ports layer** — the typed protocols, candidate model, identity model, evidence model, and store contracts that everything else depends on. It is versioned (`CONTRACT_VERSION`) and treated as stable. |
| **`kgis`** | The **ingestion engines** — the pipeline, sources, normalizers, validators, builders, the two ingestion modes (structured sync + LLM extraction), and the persistent candidate ledger and evidence registry. |
| **`kg_eval`** | The **evaluation harness** — grades extraction arms against a gold set into reproducible metrics under an *honest-null* policy (ADR-0009): a metric is `None` with a reason when it cannot be measured, never a fabricated `0.0`. |

## The universal seam: `Candidate`

Everything KGIS produces flows through one type. A `Candidate` is a *proposed*
assertion — an entity, an attribute, a relation, an observation, and so on —
that ingestion submits and a downstream curator (KGCS) evaluates. Ingestion
emits; KGCS curates. Because the seam is a single contract type, the two sides
evolve independently and any KGIS mode plugs into any KGCS backend.

```text
raw data ──▶ KGIS (ingestion) ──▶ Candidate ──▶ CandidateSink ──▶ KGCS (curation) ──▶ canonical graph
```

## Where KGIS sits

- **KGIS** is the reusable ingestion platform — this documentation.
- **KGCS** curates candidates into a canonical graph (a separate repo/service
  with its own docs). KGIS names the boundary but does not implement curation.
- **Adopter apps** (baseball-ai, construction-ai, …) configure KGIS for their
  domain and consume the curated graph downstream.

## Where to go next

- [**Why KGIS**](why.md) — the problem it solves and the principles behind it.
- [**Architecture**](architecture.md) — ports & adapters, the Candidate seam,
  the KGIS↔KGCS boundary, and the guarantees.
- [**Quickstart**](usage/quickstart.md) — a minimal end-to-end ingest in a few
  lines.
- [**Concepts**](concepts.md) and [**API basics**](api.md) — the vocabulary and
  the key import map.
