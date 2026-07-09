# KGIS / KGCS — Knowledge Graph Ingestion & Curation Services: High-Level Design

**Date:** 2026-07-09
**Status:** Approved design (pre-implementation)
**Repos:** `agentic-kgis` (this repo) and `agentic-kgcs`
**Author:** djjay0131, with Claude (brainstorming session)

## 1. Problem

Every active project in this portfolio builds or plans a knowledge graph, and each has
independently reinvented pieces of ingestion and curation. The best implementations of
each concern live in different repos:

| Capability | Best existing implementation |
|---|---|
| LLM extraction pipeline (docs → entities) | `agentic-kg` (`ingestion.py::ingest_papers`, 5-way parallel extractors) |
| Deterministic structured sync (DB → graph) | `ts-kg` (`sync.py`, idempotent id-keyed upsert) |
| Canonical-ID enforcement (repair-or-reject) | `ts-kg` (`canonical.py`; motivated by agentic-tskg's 0/18 ingestion failure) |
| Data-backed-only ontology | `ts-kg` (`ontology.py`, `validate_ontology.py`) |
| Entity resolution / dedup / confidence routing | `agentic-kg` (dual-entity Mention→Concept, auto/evaluator/consensus/human routing) |
| Human review queue | `agentic-kg` (`review_queue.py`, priority SLAs) |
| Versioning & provenance | `construction-ai` (`provenance.py`: `_version/_status` stamps, `SUPERSEDED_BY` chains, rollback) |
| Engine-agnostic graph contract | `vttsi-contracts` (`GraphStore` Protocol; Spanner/Neo4j/memory adapters) |
| Multi-graph infrastructure | `construction-platform` ADR-012 (one shared Spanner instance, many IAM-isolated graph DBs) |

Nothing today answers the **semantic** question of when new data warrants a new graph
versus extending an existing one (ADR-012 answers only the infrastructure layer).

KGIS and KGCS consolidate these proven patterns into two reusable libraries that every
current and future project consumes.

## 2. Requirements (from brainstorming Q&A)

1. **Consumption model:** contract + library (the `vttsi-contracts` ports-and-adapters
   pattern). No always-on service in v1; a service wrapper can be added later.
2. **Ingestion scope (v1):** both modes — deterministic structured sync AND unstructured
   LLM extraction.
3. **Curation scope (v1):** all four primitives — canonical ID + ontology gate, entity
   resolution/dedup, human review queue, versioning & provenance.
4. **New-graph-vs-extend:** graph registry + scoring advisor; human confirms in v1, with
   an explicit architectural path to full automation (confidence-routed policy, since
   the consuming systems are learning systems).
5. **Contracts location:** a `kg_contracts` subpackage inside `agentic-kgis`;
   `agentic-kgcs` depends on it. `vttsi-contracts` is eventually superseded by
   re-exporting from `kg_contracts`.
6. **Adoption:** everything eventually; **baseball-ai first** (greenfield), then
   **agentic-kg** quickly (acid-test retrofit), then ts-kg / construction-ai.

## 3. Architecture decision: layered write path (chosen from 3 approaches)

Considered:

- **A — Strict synchronous gateway:** all curation inline. Rejected: probabilistic steps
  (dedup, human review) would block ingestion.
- **B — Post-hoc curation:** ingest writes freely, curation sweeps afterward. Rejected:
  permits uncurated data into graphs — precisely the failure mode the agentic-tskg
  post-mortem paid for.
- **C — Layered (CHOSEN):** curation split by nature:
  - **Inline write gate** (synchronous, deterministic, cheap, unbypassable):
    canonical-ID repair-or-reject, data-backed ontology validation, versioned and
    provenance-stamped writes.
  - **Async curation plane** (probabilistic, expensive): new entities land
    `PROVISIONAL`; entity resolution runs confidence-routed and promotes/merges them.

C matches how `agentic-kg` already behaves (mentions written immediately, concept
linking routed by confidence), and the provisional→promoted lifecycle is the seam where
human gating becomes automation: raising the confidence threshold at which promotion
skips the human is a config change, not a code change. The same pattern governs the
graph-level extend-vs-new decision.

## 4. System overview

```
┌─────────────────────────────────────────────────────────────┐
│  Consumer project (baseball-ai, agentic-kg, ts-kg, ...)     │
│                                                             │
│   sources ──▶ KGIS (extract/sync) ──▶ KGCS gate ──▶ graph   │
│                    │                      ▲                 │
│                    ▼                      │                 │
│              Graph Registry ◀── KGCS async curation plane   │
│              (extend vs new)      (dedup, review, promote)  │
└─────────────────────────────────────────────────────────────┘
```

- `agentic-kgis` ships two packages: `kg_contracts` (domain-neutral ports) and `kgis`
  (ingestion implementations).
- `agentic-kgcs` ships `kgcs` (curation implementations), depending only on
  `kg_contracts`.
- Consumer projects import both, inject their own graph backend and sources, and never
  hold a raw `GraphStore` — only a `CuratedGraphStore`.

## 5. Contracts layer (`agentic-kgis/src/kg_contracts/`)

```
schemas.py       GraphNode, GraphEdge, Candidate, Provenance (Pydantic)
graph_store.py   GraphStore Protocol (generalized from vttsi-contracts)
ingestion.py     Source, Extractor, IngestJob protocols
curation.py      WriteGate, Resolver, ReviewQueue protocols + CurationStatus
registry.py      GraphDescriptor, RegistryStore protocol, Recommendation
ids.py           canonical Label:key helpers (from ts-kg canonical.py)
```

Key decisions:

1. **`GraphStore` generalizes `vttsi-contracts`** — `upsert_nodes`, `upsert_edges`,
   `get_node`, `neighborhood`, `find_nodes`. Engine-agnostic per ADR-010: no
   Cypher/GQL on the protocol. Memory, Neo4j, and Spanner Graph adapters satisfy it,
   so KGIS/KGCS serve agentic-kg and construction-ai (Neo4j) and ts-kg (Spanner)
   without engine coupling.
2. **`Candidate` is the universal ingestion output** — a proposed node/edge plus
   confidence plus `Provenance`, emitted by both ingestion modes. KGIS never performs
   raw graph writes; `Candidate` is the KGIS→KGCS seam.
3. **`CurationStatus` lifecycle:** `PROVISIONAL → ACTIVE → SUPERSEDED / REVOKED`
   (construction-ai's states plus the provisional entry state). Every node carries
   status plus provenance stamps (`_version`, `_created_at`, `_created_by`, `_reason`).
4. **`ConfidencePolicy` is a shared contract**, not a KGCS internal: thresholds map to
   routes (auto / llm-evaluate / consensus / human). Used for entity promotion AND the
   registry's extend-vs-new decision. Automating a decision later = policy config
   change.
5. Contracts contain no engine code, no LLM code, no I/O.

## 6. KGIS — ingestion (`agentic-kgis/src/kgis/`)

```
sources/base.py         SourceAdapter wrapping a kg_contracts.Source
sources/sql.py          read-only SQL source (ts-kg PostgresIntersectionSource pattern)
extraction/documents.py document loading + segmentation (parser injected)
extraction/extractor.py LLMExtractor: prompt + output schema → typed Candidates
extraction/runner.py    parallel multi-extractor execution, failure isolation
pipeline.py             IngestJob: source → candidates → gate → IngestReport
registry_client.py      consults Graph Registry before any ingest run
cli.py                  kgis ingest / kgis plan / kgis validate
```

**Two modes, one pipeline:**

- **Structured sync:** `SourceAdapter` maps rows deterministically to `Candidate`s with
  `confidence=1.0`. Idempotent by canonical ID; re-running is a no-op unless data
  changed.
- **LLM extraction:** documents segmented, then N extractors run in parallel with
  per-extractor failure isolation (agentic-kg's `asyncio.gather` + `_run` pattern).
  Each extractor = one entity type; emits `Candidate`s with model-reported confidence
  and full `Provenance` (document, span, model, prompt version).

Both modes hand the `Candidate` stream to the KGCS gate. **KGIS is constructed with a
`CuratedGraphStore`, never a raw `GraphStore`** — the agentic-tskg 0/18 failure is
structurally impossible.

**Ingest flow:**

```
kgis ingest --graph <registry-name> --source <adapter> [--extractors ...]
  1. registry_client: resolve graph → backend, ontology, policy
     (or run the extend-vs-new advisor if no graph specified)
  2. plan: dry-run — candidate counts by type, ontology coverage,
     would-be rejections (data-backed-only check). Mandatory before
     first ingest into any graph. Unbacked types reported, never hidden.
  3. execute: stream Candidates through the KGCS gate in batches
  4. report: IngestReport — accepted/repaired/rejected/provisional counts,
     rejection reasons, provenance manifest. Persisted artifact; input to
     the registry advisor and future learning systems.
```

**Key decisions:**

1. **Extractors are data, not code:** an extractor = (entity schema, prompt template,
   model config) registered per graph. baseball-ai defines player/skill/drill
   extractors as config; agentic-kg's five extractors port as configs.
2. **LLM provider injected** behind a small `CompletionClient` protocol (portfolio uses
   both Claude and OpenAI; KGIS mandates neither).
3. **Idempotency:** candidates carry a content hash (agentic-kg's `taxonomy_hash`
   generalized) so re-ingesting is safe and cheap.

## 7. KGCS — curation (`agentic-kgcs/src/kgcs/`)

```
gate/curated_store.py   CuratedGraphStore: wraps any GraphStore
gate/canonical.py       repair-or-reject Label:key enforcement (ts-kg)
gate/ontology.py        declarative ontology registry + data-backed activation
gate/versioning.py      versioned writes, SUPERSEDED_BY chains, rollback
plane/resolver.py       entity resolution: embedding match → confidence routing
plane/promoter.py       PROVISIONAL → ACTIVE transitions, merge execution
plane/normalizer.py     cross-type disambiguation (agentic-kg E-7 pattern)
review/queue.py         persistent review queue, priorities + SLAs
review/cli.py           kgcs review — work the queue from the terminal
policy.py               ConfidencePolicy loading/evaluation
audit.py                every curation action → immutable audit record
```

**Inline gate** (`CuratedGraphStore`), applied in order on every write:

1. **Canonical ID** — repair if unambiguous, reject naming the offending ID, never
   silently coerce.
2. **Ontology** — node/edge type must be declared and active; edges require both
   endpoint types active. Unknown types reject with "declare it or drop it."
3. **Versioned write** — unchanged data is a no-op; changed data creates a new version
   chained by `SUPERSEDED_BY`; stamped with status/version/actor/reason.
   Sub-1.0-confidence candidates enter `PROVISIONAL`; confidence-1.0 structured syncs
   enter `ACTIVE`.

Rejections are data, not exceptions: rejected candidates land in a quarantine store
with provenance, surfaced in the `IngestReport`.

**Async curation plane** (per graph, scheduled or post-ingest):

1. **Resolve** — for each `PROVISIONAL` entity, embedding-similarity search against
   `ACTIVE` entities of the same type (per-type thresholds; agentic-kg defaults:
   ~0.90 concepts, ~0.95 named things).
2. **Route by `ConfidencePolicy`** — high: auto-merge/promote; medium: single LLM
   evaluator; low: multi-agent consensus (Maker/Hater/Arbiter); floor: human queue.
3. **Promote or merge** — dual-entity (Mention → `INSTANCE_OF` → Concept) where the
   graph's ontology opts in; otherwise direct merge with version chaining. **Every
   merge is reversible** via rollback.
4. **Audit** — immutable record of who/what decided, confidence, evidence. The audit
   stream is the training corpus that later justifies raising auto-promotion
   thresholds (the human-to-automated path).

**Human review:** `kgcs review` CLI presents queue items (candidate vs. match,
evidence, provenance) for approve / reject / merge-elsewhere. Priority + SLA metadata
(24h/7d/30d). A web UI is out of scope for v1; the queue schema is the contract a
future UI builds on.

## 8. Graph Registry & extend-vs-new advisor

A deliberately boring store (SQLite for v1, Postgres optional). The schema
(`GraphDescriptor`, `Recommendation`) and `RegistryStore` protocol live in
`kg_contracts.registry`; the SQLite implementation lives in `kgis` (contracts stay
I/O-free). One `GraphDescriptor` per graph:

```
GraphDescriptor:
  name, owner, domain (free text + tags)
  backend (spanner | neo4j | memory) + connection ref (secret NAME, never a secret)
  ontology summary (active node/edge types + descriptions)
  policy ref (this graph's ConfidencePolicy config)
  lineage (created_at, created_by, decision_record)
```

**Advisor:** runs when an ingest targets no existing graph or a `plan` shows heavy
ontology mismatch. Scores the incoming candidates against every registered descriptor
on four factors:

1. **Domain overlap** — embedding similarity of domain descriptions/tags
2. **Ontology compatibility** — type overlap, or cleanly-disjoint extension
3. **Tenancy/access** — different owners or IAM boundaries → separate graphs
4. **Lifecycle** — throwaway experiment vs. long-lived system → separate

The advisor implementation lives in `kgcs` (it is a graph-level curation decision),
invoked by `kgis`'s `registry_client` during `plan`.

Output: a scored `Recommendation` (extend graph X / create new) with explicit reasons.
**v1: every recommendation routes to a human** (via the `kgcs review` surface). The
decision AND its outcome are recorded in registry lineage — the corpus that calibrates
automated thresholds later through the same `ConfidencePolicy` mechanism.

New-graph provisioning follows ADR-012: a new database on the shared Spanner instance
(or a Neo4j database), then a registry entry.

## 9. Error handling

- **Ingestion:** per-extractor and per-batch failure isolation; a failed extractor
  yields a partial `IngestReport` marked incomplete — never a silent gap. Source/LLM
  outages retry with backoff, then park the job as resumable (content hashes make
  resume idempotent).
- **Gate:** rejections are data (quarantine + reasons); exceptions are bugs. Fail
  closed: if the ontology or registry cannot be loaded, writes stop.
- **Curation plane:** promotion/merge are idempotent, versioned, reversible; a crash
  mid-resolution is recovered by re-running over remaining `PROVISIONAL` nodes.

## 10. Testing

- **Contract test suite** in `kg_contracts`: reusable tests any
  `GraphStore`/`Source`/`ReviewQueue` implementation must pass (vttsi discipline).
- Unit tests against `MemoryGraphStore` — no infrastructure required.
- LLM extractors: recorded fixtures for determinism + a small live smoke test.
- One end-to-end scenario per ingestion mode (sync a table / ingest a document →
  gate → resolve → promote), runnable fully in-memory.
- CI per repo; cross-repo CI installs `kg_contracts` from GitHub (vttsi pattern).

## 11. Adoption path

1. **Bootstrap:** `git init` both repos (kgis done 2026-07-09), scaffold packages,
   establish Constellize memory banks (`llm/memory_bank/`, 5 core files — matching
   agentic-kg's current convention) in each repo.
2. **baseball-ai (first adopter):** registry decision (new graph) → define
   player/skill/drill extractors as config → ingest real documents → work the review
   queue. Exercises every component end-to-end; resolves baseball-ai's deferred
   "implement KG now?" question.
3. **agentic-kg (acid test):** port its five extractors to KGIS configs and its
   curation stack to KGCS policies. KGCS must reproduce behavior agentic-kg already
   has; divergences are KGCS bugs. Validates the libraries before ts-kg and
   construction-ai follow.
4. **ts-kg / construction-ai / future projects:** adopt incrementally;
   `vttsi-contracts` re-exports from `kg_contracts` during transition.

## 12. Out of scope for v1

- Web UI for the review queue (CLI only; queue schema is the future UI's contract)
- Streaming ingestion (Kafka/BSM-style; designed for in the Candidate model, not built)
- Fully automated extend-vs-new decisions (architecture supports it; v1 human-gated)
- A deployed KGIS/KGCS network service (library-first; service wrapper later)
- Migration tooling for existing graph data (adopters start at the write path)
