# KGIS / KGCS — Knowledge Graph Ingestion & Curation Services: High-Level Design

**Version:** v2, 2026-07-10, amended per external review PR #1
**Date:** 2026-07-09 (v1), 2026-07-10 (v2)
**Status:** Approved design (pre-implementation)
**Repos:** `agentic-kgis` (this repo) and `agentic-kgcs`
**Author:** djjay0131, with Claude (brainstorming session; v2 amendments per
approved disposition of external design review)

## Revision history

| Version | Date | Change |
|---|---|---|
| v1 | 2026-07-09 | Initial approved design from brainstorming session. Backed by ADRs 0001–0005. |
| v2 | 2026-07-10 | Amended per external (ChatGPT) design review, PR #1. Requirements source: `docs/ai/chatgpt-feedback-disposition.md` (approved; items A1–A22, D1–D3, R1–R3). Sections 3, 5, 6, 7, 8, 9, 11 reworked; §10 extended with `kg_eval`. New ADRs 0006–0010; ADRs 0002/0004/0005 amended; ADR-0003 superseded in part. |

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
| Entity resolution / dedup / confidence routing | `agentic-kg` (dual-entity Mention→Concept, confidence-routed adjudication) |
| Human review queue | `agentic-kg` (`review_queue.py`, priority SLAs) |
| Versioning & provenance | `construction-ai` (`provenance.py`: `_version/_status` stamps, `SUPERSEDED_BY` chains, rollback) |
| Evidence as first-class records (present/absent/error) | `vttsi-evidence` (resolvable evidence IDs, availability states, provenance) |
| Deterministic baseline + bounded LLM adjustment | `vttsi-score-deterministic` + `vttsi-llm-score` (clamp-and-fallback discipline) |
| Honest-null evaluation harness | `vttsi-eval` (named arms, ablations, null conclusions) |
| Engine-agnostic graph contract | `vttsi-contracts` (`GraphStore` Protocol; Spanner/Neo4j/memory adapters) |
| Multi-graph infrastructure | `construction-platform` ADR-012 (one shared Spanner instance, many IAM-isolated graph DBs) |

Nothing today answers the **semantic** question of when new data warrants a new graph
versus extending an existing one (ADR-012 answers only the infrastructure layer).

KGIS and KGCS consolidate these proven patterns into reusable libraries that every
current and future project consumes.

**Scope framing (v2):** KGIS and KGCS manage **knowledge admission, identity,
evidence, and graph state** — not domain reasoning. Traffic-safety scoring belongs in
the traffic project; stud calculations in construction; athlete-development assessment
in baseball; research-opportunity ranking in the research project. Domain systems
consume and emit the shared contracts but remain independently testable components.
The name KGCS ("Curation Service") is retained; this framing defines what curation
means here.

The central architectural distinction, preserved throughout both libraries: **a
candidate is an assertion about the world, not yet an entity in the world.**

## 2. Requirements (from brainstorming Q&A; adoption ordering revised in v2)

1. **Consumption model:** contract + library (the `vttsi-contracts` ports-and-adapters
   pattern). No always-on service in v1; a service wrapper can be added later.
2. **Ingestion scope (v1):** both modes — deterministic structured sync AND unstructured
   LLM extraction.
3. **Curation scope (v1):** all four primitives — canonical ID + ontology gate, entity
   resolution/dedup, human review queue, versioning & provenance.
4. **New-graph-vs-extend:** graph registry + scoring advisor; human confirms in v1, with
   an explicit architectural path to full automation (confidence-routed policy, since
   the consuming systems are learning systems).
5. **Contracts location:** `agentic-kgis` ships three packages — `kg_contracts`
   (domain-neutral ports), `kgis` (ingestion), and `kg_eval` (evaluation, v2) —
   `agentic-kgcs` depends only on `kg_contracts`. `vttsi-contracts` is eventually
   superseded by re-exporting from `kg_contracts`. (ADR-0002 as amended.)
6. **Adoption:** everything eventually, via the five-phase sequence in §11 (v2):
   VTTSI contract reference → baseball greenfield → traffic shadow → research-paper
   retrofit → construction derivations.

## 3. Architecture decision: layered write path over three separated stores

### 3.1 Layered write path (v1 decision, survives)

Considered in v1:

- **A — Strict synchronous gateway:** all curation inline. Rejected: probabilistic steps
  (dedup, human review) would block ingestion.
- **B — Post-hoc curation:** ingest writes freely, curation sweeps afterward. Rejected:
  permits uncurated data into graphs — precisely the failure mode the agentic-tskg
  post-mortem paid for.
- **C — Layered (CHOSEN):** curation split by nature — deterministic admission checks
  run synchronously and cheaply; probabilistic curation (entity resolution, LLM
  assessment, human review) runs asynchronously.

### 3.2 Three-store separation (v2, ADR-0006)

The v1 mechanism — uncertain entities written into the main graph as `PROVISIONAL`
nodes — is **superseded**. Provisional nodes in the graph turn uncertainty into
operational contamination: traversals treat them as real, duplicates inflate degree and
community structure, derived summaries amplify uncertain facts, and every consumer must
remember to filter. Instead, three logical stores with contract-enforced separation
(they may share one physical database but never one access path):

1. **Candidate ledger** — immutable, replayable proposed assertions and entities:
   candidate ID, source coordinates, extractor and model version, ontology version,
   normalized payload, evidence refs, quality signals, deduplication keys, processing
   state. Uncertain candidates live here — never as ordinary graph entities.
2. **Canonical graph** — only accepted identities and assertions, with explicit
   validity, scores, and provenance.
3. **Derived projections** — disposable, reproducible artifacts: search indices,
   GraphRAG communities and summaries, embeddings caches, aggregates,
   application-specific views. Never canonical facts unless independently curated.

**Invariant (v2): derived projections are built only from canonical data at a
published curation epoch.**

### 3.3 Curation epochs and read consistency

Canonical mutations commit as atomic **curation epochs**: resolve and validate
candidates → prepare a mutation batch → commit canonical mutations → advance the
graph's visible curation watermark → rebuild or invalidate affected derived
projections. Readers consume a published epoch, never "whatever is present", so one
query can never observe a partially promoted batch.

All graph reads take explicit consistency options:

```
GraphReadOptions:
  curation_epoch          # snapshot/watermark to read at
  valid_at                # domain (valid-time) point
  transaction_at          # system (transaction-time) point
  include_provisional     # opt-in ledger visibility (default: canonical only)
  include_superseded
  minimum_evidence_policy
```

Without this contract, every project would invent inconsistent status filters. GraphRAG
and other projection builders default to canonical-only reads at a published epoch.

The seam where human gating becomes automation survives from v1: raising the
policy threshold at which promotion skips the human is a config change, not a code
change. The same pattern governs the graph-level extend-vs-new decision (§8).

## 4. System overview

```
┌────────────────────────────────────────────────────────────────────┐
│  Consumer project (baseball-ai, agentic-kg, ts-kg, ...)            │
│                                                                    │
│  sources ─▶ KGIS (extract/sync) ─▶ CandidateSink ─▶ candidate      │
│                  │                                  ledger         │
│                  ▼                                    │            │
│            Graph Registry             KGCS curation core           │
│            (extend vs new)         (validate, resolve, plan)       │
│                                             │                      │
│                                     CurationPlan                   │
│                                             ▼                      │
│                                    KGCS executor ─▶ canonical      │
│                                  (preconditions)     graph         │
│                                                        │ epoch     │
│                                                        ▼           │
│                                              derived projections   │
└────────────────────────────────────────────────────────────────────┘
```

- `agentic-kgis` ships three packages: `kg_contracts` (domain-neutral ports),
  `kgis` (ingestion implementations), and `kg_eval` (evaluation harness).
- `agentic-kgcs` ships `kgcs` (curation implementations), depending only on
  `kg_contracts`.
- Consumer projects import the libraries and inject their own graph backend and
  sources. **Applications hold no synchronous write path to the canonical graph at
  all**: the only application-facing write surface is `CandidateSink` (§5.6); only
  KGCS executors apply mutation batches.

## 5. Contracts layer (`agentic-kgis/src/kg_contracts/`)

```
identity.py      EntityRef, identity IDs, aliases, cross-graph identity
candidates.py    9-variant candidate union, CandidateEnvelope, CandidateScores
evidence.py      Evidence, EvidenceRef, availability states
assertions.py    bitemporal assertion model, conflict representation
derivation.py    Derivation, derivation lineage
stores.py        CandidateSink, GraphMutationStore, split reader/writer
                 protocols, capability declarations, GraphReadOptions
curation.py      curation operations, decisions, CurationPlan, processing
                 states, ReviewQueue protocol, review operations
ingestion.py     Source, Extractor, IngestJob protocols, IngestReport
registry.py      GraphDescriptor, RegistryStore protocol, Recommendation
policy.py        ConfidencePolicy (score-set-aware routing)
security.py      policy context stub: actor, tenant/purpose, redaction,
                 deletion behavior; universal trace ID
versioning.py    contract/ontology/extractor versions, compatibility classes
```

Contracts contain no engine code, no LLM code, no I/O. `kg_contracts` v2 is written
**fresh**, using `vttsi-contracts`, `ts-kg`, and `vttsi-evidence` as reference reading
— no code vendoring (owner decision, 2026-07-10).

### 5.1 Identity model (ADR-0008)

Every canonical entity has an **immutable internal identity ID** (e.g.
`kg://<graph-id>/identity/01J...`) plus **namespaced external aliases**. Aliases are
structured, not string-first:

```
EntityRef{entity_type, namespace, key}    # rendered "Label:namespace:key"
                                          # only at adapter boundaries
```

Examples: `Paper:doi:10.1145/...`, `Athlete:usssa:12345`, `Intersection:vttsi:101`.
Bare `Label:key` (`Player:123`) is **deprecated for cross-project use** — it says
nothing about who issued the key. Identity outlives labels and natural keys: a
corrected natural key never replaces the entity's identity, only its aliases. The
ts-kg `canonical.py` repair-or-reject discipline is preserved (repair if unambiguous,
reject naming the offending ID, never silently coerce); only the ID format is upgraded.

**Cross-graph identity is contract-complete in v1** (implementation minimal): global
identity ID, graph-local identity ID, alias/external identifiers, `SAME_AS` /
`POSSIBLY_SAME_AS` / `RELATED_TO` link semantics, and authority + provenance for every
mapping.

### 5.2 Candidate model (ADR-0004 as amended)

`Candidate` is a **discriminated union of nine variants** (discriminator:
`candidate_kind`):

1. `EntityCandidate` — a proposed identity.
2. `RelationCandidate` — a proposed relationship.
3. `AttributeAssertionCandidate` — a proposed fact about an entity.
4. `ObservationCandidate` — a measured value (metric, method, parameters).
5. `DerivedAssertionCandidate` — a computed conclusion with derivation lineage.
6. `ArtifactCandidate` — a produced object (type, content hash, source URI); an
   artifact is not a fact about the world.
7. `PlanCandidate` — a recommendation/plan (inputs, objective); a generated cut list
   is not a fact about the building.
8. `OntologyCandidate` — a proposed ontology term (enters the §7.3 lifecycle).
9. `IdentityLinkCandidate` — a proposed cross-graph or intra-graph identity link.

All nine variants are defined in v1 contracts. v1 pipelines implement entity /
relation / attribute-assertion / artifact; the rest land with the adoption phases that
need them (§11).

All variants share an envelope:

```
CandidateEnvelope:
  candidate_id, graph_id, candidate_kind
  producer, producer_run_id
  contract_version, ontology_version
  evidence_refs: list[EvidenceRef]
  source_coordinates          # stable locator into the source
  semantic_key                # idempotency key (see §5.8)
  content_hash                # supplementary idempotency signal
  representations             # named feature views (e.g. raw statement,
                              # statement+assumptions embedding) — never a
                              # single generic embedding field
  scores: CandidateScores
  trace_id, created_at
```

**A single `confidence` float is banned.** The score set keeps orthogonal signals
apart — an exact database import is not proof the database's fact is correct:

```
CandidateScores:
  extraction_confidence   # did we read the source correctly?
  identity_confidence     # is this the entity we think it is?
  assertion_confidence    # is the asserted fact true?
  source_reliability      # how trustworthy is this source historically?
  corroboration_score     # independent support
  policy_risk             # consequence class of acting on it
```

Source **authority** (who is entitled to assert this) is recorded separately from all
scores (§7.5). **Curation status attaches at assertion level**, not only whole-node
level: an entity can be certain while one of its properties is uncertain; fact-level
uncertainty is never forced onto entity status.

### 5.3 Evidence contract (promoted from vttsi-evidence)

Evidence is a first-class contract, not candidate metadata:

```
Evidence:
  evidence_id               # stable, resolvable
  source_type, source_locator
  observed_at, valid_time
  availability: present | absent | error
  payload_hash, content, error, provenance

EvidenceRef:
  evidence_id
  relationship: supports | contradicts | derived_from | contextualizes
```

Availability is explicit because absence has distinct meanings — "no source queried",
"source omitted it", "source unavailable", "sources contradict", "source states
unknown" — and representing them prevents an LLM reading graph context from turning
absent data into an inferred fact. Evidence is **never silently dropped**; providers
record absence/error rather than throwing failures upward. Scores and decisions cite
evidence IDs that resolve back to timestamped sources. Storage and providers live in
`kgis`; the contract lives here.

### 5.4 Bitemporal assertions

Every canonical assertion carries both **valid time** (when the fact is true in the
domain) and **transaction time** (when the system learned, accepted, or superseded it)
— from v1, in the contracts and the canonical data model. This matters in all target
domains: paper affiliations change; traffic conditions are momentary; construction
status evolves; athletes change teams and age groups. Full temporal *query* support on
every backend is not required in v1: it is capability-declared (§5.7), implemented
first on the memory store, then per-backend as adopters need it.

### 5.5 Derivation lineage

Method determinism is not factual confidence: a stud calculation can be perfectly
deterministic while its inputs (wall extraction, scale, opening recognition) are
uncertain. Contracts separate method determinism, source reliability, input
confidence, assertion confidence, and reproducibility:

```
Derivation{method, deterministic: bool, inputs, implementation_version}
```

Derivation lineage is a directed graph (DWG → DXF → line segments → inferred wall →
wall length → stud quantity → takeoff → cut list), covering source artifacts,
transformation runs, code/config/model versions, input and output assertions,
warnings, units, coordinate systems, and reproducibility status. A content hash alone
cannot capture this. Consequence for ingestion: **deterministic sync no longer enters
`ACTIVE` automatically at "confidence 1.0"** — entry policy evaluates the score set
(extraction certainty vs. source reliability vs. authority). See ADR-0004 as amended.

### 5.6 Store contracts: two levels (ADR-0010)

Raw graph adapters are internal. Two write surfaces, deliberately asymmetric:

- **`CandidateSink`** — the **only** application-facing write surface:
  `submit(candidates) -> SubmissionResult`. Projects depend on this and nothing else.
- **`GraphMutationStore`** — adapter-level, used **only by KGCS executors**:
  `apply(batch, preconditions) -> CommitResult`.

Exposing `upsert_nodes`/`upsert_edges` to consumers (the vttsi-contracts shape) is
superseded: convenient raw writes are how pipelines get bypassed. Read/write protocols
are split rather than one broad `GraphStore`: `GraphReader`, `GraphWriter`,
`TransactionalGraphWriter`, `BulkGraphWriter`, `TemporalGraphReader`. One broad
protocol becomes either too weak or too demanding once Neo4j, Spanner Graph, temporal
curation, and rollback all share it.

### 5.7 Adapter capability declarations

Adapters declare optional behavior instead of leaking it:

```
supports_transactions, supports_temporal_queries, supports_vector_search,
supports_full_text, supports_constraints, supports_bulk_upsert,
supports_snapshot_reads, supports_graph_algorithms
```

Cypher/GQL stays off the core contracts; capability-specific extension protocols are
the escape hatch. Engine-agnostic per the v1 decision: memory, Neo4j, and Spanner
Graph adapters remain interchangeable.

### 5.8 Versioning and idempotency

Versioned contracts cover: candidate schemas, ontology types, relationship
definitions, validation rules, extractors, prompts, embedding models, resolution
features, and graph projections. Every version change declares a **compatibility
class**: backward-compatible / requires candidate revalidation / requires
re-extraction / requires graph migration / requires derived-index rebuild.

Idempotency uses **stable source coordinates + semantic assertion keys**, with content
hashes as a supplementary signal only — hashes fail when the same fact is worded
differently, chunking changes, normalization changes, or extractor versions change.

### 5.9 Security/policy stub and universal trace ID

A policy-context contract stub ships in v1 (full enforcement phased): actor identity,
tenant and purpose context, policy decision, sensitive-field handling, redaction,
audit access, deletion/tombstone behavior, and derived-artifact deletion. This is
designed **before** the baseball graph accumulates youth data.

Every source record carries one **universal trace ID** through: source → extraction
run → candidates → validation → resolution → curation operation → graph mutation →
derived indexes → consumer query.

### 5.10 ConfidencePolicy

`ConfidencePolicy` remains a shared contract (not a KGCS internal), now evaluated over
the `CandidateScores` set and consequence class rather than a single float. It routes
adjudication (auto / LLM-assess / human) for entity promotion AND the registry's
extend-vs-new decision. Automating a decision later = policy config change.

## 6. KGIS — ingestion (`agentic-kgis/src/kgis/`)

```
sources/base.py         SourceAdapter wrapping a kg_contracts.Source
sources/sql.py          read-only SQL source (ts-kg PostgresIntersectionSource pattern)
extraction/documents.py document loading + segmentation (parser injected)
extraction/extractor.py LLMExtractor: prompt + output schema → typed Candidates
extraction/runner.py    parallel multi-extractor execution, failure isolation
evidence/registry.py    evidence registry (vttsi-evidence pattern)
ledger.py               candidate ledger implementation
pipeline.py             IngestJob: source → candidates → CandidateSink → IngestReport
registry_client.py      consults Graph Registry before any ingest run
cli.py                  kgis ingest / kgis plan / kgis validate
```

**Two modes, one pipeline:**

- **Structured sync:** `SourceAdapter` maps rows deterministically to candidates.
  High extraction confidence and recorded method determinism — **not** an automatic
  claim that the source's facts are true; `source_reliability` and authority are
  scored separately (§5.5). Idempotent by source coordinates + semantic key.
- **LLM extraction:** documents segmented, then N extractors run in parallel with
  per-extractor failure isolation (agentic-kg's `asyncio.gather` + `_run` pattern).
  Each extractor = one entity type; emits typed candidates with model-reported
  extraction confidence and full provenance (document, span, model, prompt version)
  plus evidence refs.

Both modes submit candidates through **`CandidateSink`** into the candidate ledger.
KGIS holds no graph-write surface of any kind — the agentic-tskg 0/18 failure is
structurally impossible, and so is "helpful" direct upsert.

**Batch-of-one constraint (v2):** all batch APIs are shaped so that a batch of one
candidate can later behave as an event. Streaming ingestion stays deferred, but as a
transport change, not a redesign.

**Ingest flow:**

```
kgis ingest --graph <registry-name> --source <adapter> [--extractors ...]
  1. registry_client: resolve graph → backend, ontology, policy
     (or run the extend-vs-new advisor if no graph specified)
  2. plan: dry-run — candidate counts by type/kind, ontology coverage,
     would-be rejections. Mandatory before first ingest into any graph.
     Unknown types reported, never hidden.
  3. execute: submit candidate batches via CandidateSink
  4. report: IngestReport (persisted artifact; input to the registry
     advisor and future learning systems)
```

**Per-milestone reporting (v2):** KGIS never claims a successful ingestion merely
because candidates were emitted. `IngestReport` counts each stage separately —
**extracted / validated / identity-resolved / accepted / materialized / indexed** —
plus rejection reasons, quarantine contents, and a provenance manifest. A run that
emits 10,000 candidates of which 40 reach the canonical graph reports exactly that.

**Key decisions (v1, surviving):**

1. **Extractors are data, not code:** an extractor = (entity schema, prompt template,
   model config) registered per graph. baseball-ai defines player/skill/drill
   extractors as config; agentic-kg's five extractors port as configs.
2. **LLM provider injected** behind a small `CompletionClient` protocol (portfolio uses
   both Claude and OpenAI; KGIS mandates neither).
3. Third-party extractors (LlamaIndex property-graph extractors, LangChain
   `LLMGraphTransformer`) may be wrapped as thin `Extractor` adapters emitting
   candidates — never direct graph insertion (v2, per prior-art review).

## 7. KGCS — curation (`agentic-kgcs/src/kgcs/`)

```
core/validate.py        pure validation: candidate → ValidationDecision
core/resolve.py         pure resolution: candidate + cluster snapshot → ResolutionDecision
core/plan.py            decisions → CurationPlan (serializable)
core/ontology.py        ontology lifecycle + policy evaluation (pure)
executor/executor.py    apply(CurationPlan) with optimistic preconditions
executor/compensate.py  compensating rollback from the operation log
er/normalize.py         stage 1: normalization + deterministic identity rules
er/blocking.py          stage 2: multi-channel candidate generation
er/features.py          stage 3: typed pairwise features
er/matcher.py           stage 4: calibrated matcher
er/clusters.py          stage 5: cluster validation
er/adviser.py           bounded LLM ResolutionAssessment
review/api.py           review-domain API (operations model, v1)
review/queue.py         persistent review queue, priorities + SLAs
review/cli.py           kgcs review — work the queue from the terminal
policy.py               ConfidencePolicy loading/evaluation; deterministic policy gate
audit.py                every curation action → immutable audit record
backlog.py              queue SLOs, backpressure, quarantine controls
```

### 7.1 Pure curation core → CurationPlan → executor (ADR-0010)

KGCS follows the traffic repos' pure-core/injected-adapter architecture. The curation
core is pure logic — `evaluate_candidate(candidate, graph_snapshot, ontology, policy)
→ decision` — with no database connection. The full pipeline is explicit, and every
object in it is serializable and auditable:

```
Candidate → ValidationDecision → ResolutionDecision → CurationPlan
          → GraphMutationBatch → CommitResult
```

```
CurationPlan{plan_id, candidate_ids, snapshot_version, operations,
             preconditions, evidence_ids, policy_version}
```

A separate **executor** applies plans against `GraphMutationStore` only if
optimistic preconditions still hold against the recorded **cluster snapshot** —
resolution decides against an identity cluster at a known version, never against one
arbitrary node. This bounds concurrent-merge conflicts (merge A→B while another worker
merges A→D): stale-snapshot plans fail their preconditions and are re-evaluated.
Merge-operation IDs are idempotent; survivor selection is deterministic.

**Curation actions are explicit operations**, not implicit writes:
`CREATE_IDENTITY`, `ATTACH_ASSERTION`, `MERGE_IDENTITIES`, `SPLIT_IDENTITY`,
`REASSIGN_ASSERTION`, `RETRACT_ASSERTION`, `PROMOTE_ONTOLOGY_TERM`. Every operation
logs enough to reverse it — pre-merge member set, property lineage, edge lineage,
conflict-resolution decisions, canonical-ID changes, affected derived projections,
downstream publication markers. **Rollback is a compensating operation, not deletion
of history.** The v1 "wrap every write in a `CuratedGraphStore`" mechanism is
superseded; the unbypassable-gate *property* is strengthened — applications hold no
synchronous canonical write path at all (§5.6).

### 7.2 Inline deterministic admission (gate scope, v2-narrowed)

Deterministic admission checks run synchronously on candidate submission: contract
validation, identity syntax (repair-or-reject), ontology enforcement, policy checks,
idempotency. The synchronous gate protects **canonical semantic mutations only** — it
does not gate audit-log appends, candidate-ledger writes, queue-state transitions,
derived-index updates, or operational metadata; otherwise it becomes a bottleneck and
a single failure domain.

**Candidate processing states** are separate from entity/assertion curation status:

```
RECEIVED → VALIDATED | INVALID | BLOCKED
         → RESOLUTION_PENDING → REVIEW_PENDING
         → ACCEPTED | REJECTED | SUPERSEDED
         → RETRYABLE_ERROR | PERMANENT_ERROR
```

The failure taxonomy distinguishes bad data, unsupported ontology, and transient
faults (adapter failure, stale schema cache, unavailable embedding service,
infrastructure outage). All reject canonical mutation; each gets different retry and
alert behavior, so transient faults never become permanent quarantines
(fail-closed must not become fail-stopped).

Rejections are data, not exceptions: rejected candidates land in a quarantine store
with provenance, surfaced in the `IngestReport`.

### 7.3 Ontology lifecycle (v2)

Ontology terms have governance states layered over data-backed activation:

```
PROPOSED → APPROVED → OBSERVED → DEPRECATED
```

An ontology represents permitted meaning and intended future states, not just observed
instance counts: a type may be **approved before instances exist**. "Active for
writes" still requires approval; observation (instances exist) is tracked separately.
Unknown types reject with "propose it or drop it"; `OntologyCandidate` +
`PROMOTE_ONTOLOGY_TERM` are the paths in.

### 7.4 Entity resolution (ADR-0007)

The v1 embedding-threshold funnel (0.90/0.95 similarity bands as the decision
mechanism) is **superseded**. Cosine thresholds are not portable across embedding
models, entity types, languages, text lengths, or candidate-pool difficulty.
Embeddings remain useful — as one blocking channel and one feature. The pipeline:

1. **Normalization + deterministic identity rules** — DOI, ORCID, VIN, source-native
   IDs, normalized names/emails/units/dates, deterministic source crosswalks. Rules
   produce explainable evidence; they never silently merge.
2. **Multi-channel blocking** (recall matters) — exact/phonetic name blocks,
   identifier prefixes, geography/date ranges, source keys, embedding ANN,
   graph-neighborhood overlap, type-specific lexical retrieval.
3. **Typed pairwise features** — name similarity, identifier agreement or
   contradiction, temporal compatibility, geographic distance, shared affiliations,
   attribute rarity, source reliability, embedding similarity, neighborhood
   compatibility, and — critically — **mutually exclusive evidence** (two athletes
   with similar names appearing on different teams at the same time).
4. **Calibrated matcher** — probabilistic linkage / gradient-boosted / logistic /
   cross-encoder / rules+learned weights, producing a calibrated match probability.
   Splink and dedupe are benchmarked as buy-before-build baselines during the
   baseball PoC (§11).
5. **Cluster validation** — pairwise matches do not make valid clusters; if A~B, B~C,
   A contradicts C, transitive closure is wrong. Cluster-level constraints (temporal
   consistency, unique-source membership, mutually exclusive attributes, tenant
   boundaries) re-score prospective membership.
6. **Deterministic policy gate** — routes on calibrated error risk and consequence
   class, not fixed similarity bands: auto-link / retain separately / request human
   review / gather more evidence / abstain.

**The LLM is a bounded, evidence-citing adviser — never the merge authority**
(mirrors vttsi-llm-score's clamp-and-fallback discipline). It normalizes difficult
attributes, compares passages, identifies contradictions, and returns

```
ResolutionAssessment{recommendation: same | different | insufficient_evidence,
                     evidence_ids, contradictions, rationale, confidence}
```

which enters the policy gate as evidence. On any LLM failure, the deterministic
baseline stands. Multi-agent debate (Maker/Hater/Arbiter) is **demoted to an
experimental `kg_eval` arm**; confidence routing as a *policy* concept survives for
adjudication routing and the graph advisor.

**Calibration discipline:** thresholds are maintained per graph, entity type, source
pair, matcher version, and consequence class — learned from validation curves or
expected-cost optimization against a **labeled golden set** (obvious matches and
nonmatches, hard negatives, aliases, homonyms, near-duplicate descriptions, temporal
conflicts, source-specific noise) and an **explicit cost matrix** (false merges
usually cost more than false splits: merges contaminate all attached facts). Metrics
tracked in `kg_eval` (§10). Every decision logs the **full score vector and model
versions** — a single stored final confidence cannot reproduce a decision.

### 7.5 Conflict representation and source authority (v2)

Competing assertions are preserved, not overwritten: both assertions, their evidence,
their valid periods, the current preferred assertion, the resolution policy applied,
and unresolved-conflict status. Source **authority** (who may declare a fact, e.g.
DOI/ORCID for papers vs. fragmented league identifiers for baseball) is recorded
separately from every confidence score: a deterministic sync at high extraction
confidence may still carry stale or wrong data. Recorded separately: extraction
certainty, source reliability, source authority, freshness, corroboration, conflict
status.

### 7.6 Review operations (v2-widened)

Review is not only approve/reject. The review-domain API (v1; polished UI deferred)
supports: **approve, reject, edit, split, relabel, link, merge-elsewhere, and "same
concept, different scope"** — OpenRefine reconciliation semantics (candidate lists,
reconciliation status, bulk judgment, match-vs-new-entity, operation history).
`kgcs review` CLI presents queue items (candidate vs. match, evidence, provenance)
with priority + SLA metadata (24h/7d/30d). The queue schema and operations model are
the contract a future UI builds on.

### 7.7 Backlog controls (v2)

The dangerous ledger failure is priority inversion, not storage growth: easy
candidates flow, hard high-value clusters starve, and throughput looks healthy. KGCS
tracks queue age, queue depth by entity type and source, unresolved-cluster size, and
value/risk priority; enforces curation SLOs and a maximum allowed provisional
exposure; and applies **backpressure to KGIS** with source throttling or quarantine
when curation capacity is exceeded.

### 7.8 Audit

Every curation action produces an immutable audit record (who/what decided, score
vector, evidence IDs, policy version, trace ID). The audit stream is the training
corpus that later justifies raising auto-promotion thresholds — the human-to-automated
path.

## 8. Graph Registry & extend-vs-new advisor

A deliberately boring store (SQLite for v1, Postgres optional). The schema
(`GraphDescriptor`, `Recommendation`) and `RegistryStore` protocol live in
`kg_contracts.registry`; the SQLite implementation lives in `kgis` (contracts stay
I/O-free). One `GraphDescriptor` per graph:

```
GraphDescriptor:
  name, owner, domain (free text + tags)
  backend (spanner | neo4j | memory) + connection ref (secret NAME, never a secret)
  ontology summary (approved/observed node/edge types + descriptions)
  policy ref (this graph's ConfidencePolicy config)
  capability profile (adapter capability declarations)
  lineage (created_at, created_by, decision_record)
```

**Advisor (ADR-0005 as amended):** runs when an ingest targets no existing graph or a
`plan` shows heavy ontology mismatch. Twelve factors:

1. Shared identity value (who is the identity authority; is shared identity the reason
   to join — or to stay apart)
2. Ontology compatibility (concept equivalence, relationship semantics, cardinality,
   identity rules, governance authority)
3. Assertion and evidence semantics
4. Temporal-model compatibility
5. Tenancy, privacy, and access (including minors' data, purpose limitation,
   inference leakage through traversal or embeddings)
6. Lifecycle and retention
7. Workload and backend compatibility
8. Governance and stewardship
9. Failure/blast-radius requirements
10. Cross-domain traversal value (overlap without cross-domain questions = cost
    without benefit)
11. Computational-model coupling (domain algorithms may use the graph but must not
    become platform responsibilities; would joining cause one domain's computed
    outputs to be read as another's canonical facts?)
12. Rebuild and deletion boundaries (regenerable vs. irreplaceable human curation)

**Domain overlap alone is explicitly insufficient** — two projects can both concern
transportation with no reason to share a canonical graph.

**Four outcome architectures** (not a binary):

1. Extend the same logical and physical graph
2. Shared logical graph, separate physical partitions
3. Separate graphs with a shared identity registry
4. Fully isolated graphs with explicit cross-graph mappings

v1 automated scoring covers factors 1, 2, 5, 6, and 11; the remaining factors appear
as a **structured human checklist inside every `Recommendation`** — the full factor
set is preserved without speculative scorers, and a human adjudicates every
recommendation in v1 anyway. The decision AND its outcome are recorded in registry
lineage — the corpus that calibrates automated thresholds later through the same
`ConfidencePolicy` mechanism.

The advisor implementation lives in `kgcs` (a graph-level curation decision), invoked
by `kgis`'s `registry_client` during `plan`. New-graph provisioning follows ADR-012: a
new database on the shared Spanner instance (or a Neo4j database), then a registry
entry. DataHub (aspects: independently versioned metadata components) and OpenMetadata
(governance/trust metadata) are the registry's design references.

## 9. Error handling, security, and observability

- **Ingestion:** per-extractor and per-batch failure isolation; a failed extractor
  yields a partial `IngestReport` marked incomplete — never a silent gap. Source/LLM
  outages retry with backoff, then park the job as resumable (source coordinates +
  semantic keys make resume idempotent).
- **Admission:** rejections are data (quarantine + reasons); exceptions are bugs. Fail
  closed on canonical mutation — but the failure taxonomy (§7.2) gives bad data,
  unsupported ontology, and transient faults distinct retry/alert behavior so the
  system never silently fail-stops.
- **Curation:** plans are serializable and idempotent; a crash mid-resolution is
  recovered by re-running pending plans — preconditions reject any plan whose cluster
  snapshot went stale. All mutations are reversible via compensating operations.
- **Backpressure:** backlog controls (§7.7) bound provisional exposure; quarantined
  sources are reported, never dropped.
- **Security/policy:** every operation executes in a policy context (actor,
  tenant/purpose, redaction, deletion behavior — §5.9). v1 ships the contract stub
  and threads it through; enforcement hardens per adopter, before the baseball graph
  accumulates youth data.
- **Observability:** the universal trace ID (§5.9) makes one source record traceable
  end-to-end: source → extraction run → candidates → validation → resolution →
  curation operation → graph mutation → derived indexes → consumer query.

## 10. Evaluation (`kg_eval`) and testing

### 10.1 kg_eval (ADR-0009)

Evaluation is a first-class package in `agentic-kgis` (vttsi-eval pattern): named
interchangeable arms, ablations, agreement/correlation metrics, bootstrap confidence
intervals, structured reports, and **explicit support for a null conclusion**.

- **Extraction arms:** rules-only, LLM-only, rules+LLM, parser+CV, parser+CV+LLM.
- **Resolution arms:** exact identifiers, probabilistic linkage, embedding-only,
  cross-encoder, probabilistic+LLM adjudication, multi-agent debate (experimental),
  human gold standard.
- **Extraction metrics:** entity/relation precision+recall, attribute accuracy,
  evidence-span accuracy, hallucination rate, ontology-violation rate, source
  coverage, run-to-run stability.
- **Resolution/curation metrics:** pairwise and cluster precision+recall, false-merge
  and false-split rates, abstention rate, calibration error, review yield and
  agreement, rollback frequency, queue age, time to canonicalization, per-source and
  per-subtype breakdowns.
- **Graph-outcome metrics:** competency-question success, retrieval recall, answer
  faithfulness, provenance completeness, multi-hop correctness — including whether
  derived GraphRAG structures improve actual tasks before they become defaults
  (indexing is expensive).

**Honest-null policy:** an LLM-enhanced pipeline never becomes a default merely
because it produces more output. It must demonstrate improvement on a **named metric**
without unacceptably worsening false merges, unsupported assertions, review workload,
latency, cost, or reproducibility. "The LLM did not help" is a valid, publishable
result.

### 10.2 Testing

- **Contract test suite** in `kg_contracts`: reusable tests any
  `CandidateSink`/`GraphMutationStore`/`Source`/`ReviewQueue` implementation must pass
  (vttsi discipline), including capability-declaration conformance.
- Unit tests against the memory adapters — no infrastructure required; the memory
  store is the first backend with full temporal-query support.
- Curation core is pure: decisions are testable, replayable, and comparable without
  any database.
- LLM extractors and the ER adviser: recorded fixtures for determinism + a small live
  smoke test.
- One end-to-end scenario per ingestion mode (sync a table / ingest a document →
  ledger → curation core → executor → canonical graph → epoch publish), runnable
  fully in-memory.
- CI per repo; cross-repo CI installs `kg_contracts` from GitHub (vttsi pattern).

## 11. Adoption path (five phases, v2)

Each phase has a distinct validation purpose. No phase is skippable by an adopter of
its capability class.

- **Phase 0 — VTTSI contract reference (input to Plan 1, not a separate plan):** read
  `vttsi-contracts`, `ts-kg`, and `vttsi-evidence` as reference material and write
  `kg_contracts` v2 **fresh** — generalize the proven primitives (IDs, evidence,
  reader/writer protocols, provenance, operation results, failure representation); no
  code vendoring (owner decision, 2026-07-10).
- **Phase 1 — baseball-ai (greenfield):** registry decision (new graph) → extractors
  as config → ingest real documents → work the review queue → build the ER golden set
  and benchmark Splink and dedupe as calibrated-matcher baselines. Establishes clean
  conventions: namespaced identity, ontology lifecycle, evidence handling, temporal
  history, review operations. Golden-set labeling is a named human-labor line item.
- **Phase 2 — traffic shadow integration:** wrap existing VTTSI contracts and run
  KGIS/KGCS in parallel against traffic **fixtures** — no rewrite. Validates
  compatibility with a mature production-shaped consumer.
- **Phase 3 — research-paper (agentic-kg) retrofit:** the migration and curation acid
  test. **Before Phase 3 begins, six migration-minimum tools must exist** (all
  non-deferrable): graph scanner, adapter export, candidate generation from existing
  graph state, invariant checker, dry-run diff, reconciliation report.
- **Phase 4 — construction-ai:** derivation lineage, observation/derived-assertion/
  artifact/plan candidate variants, unit and coordinate-system handling.

**Plan sequence** (milestones; labels in the governance delta):

1. Bootstrap + `kg_contracts` v2 (fed by Phase 0)
2. Candidate ledger + evidence registry
3. Curation core + executor
4. Ingestion modes (structured sync + LLM extraction)
5. Entity resolution — 5a: blocking, typed features, calibrated matcher, golden-set
   construction; 5b: LLM adviser, cluster validation, Splink/dedupe benchmark
6. `kg_eval` + review API
7. Registry + advisor

**Prior-art research tasks** (scheduled within the plan sequence; study, no wholesale
adoption): Graphiti (temporal assertions, fact invalidation), Senzing concepts
(evidence-aggregation ER, why/why-not explainability APIs), DataHub aspects,
OpenMetadata governance metadata, OpenRefine reconciliation operations, Microsoft
GraphRAG strictly as a derived-indexing and evaluation reference.

**Scope honesty:** v2 grows v1 build effort materially — net-new: evidence registry,
candidate ledger, bitemporal contracts, `kg_eval`, review-operation API, golden-set
labeling. Nothing was invalidated (no code existed); the cost is accepted
deliberately.

## 12. Deferred / out of scope for v1

- **Streaming ingestion** — deferred; the batch-of-one constraint (§6) keeps it a
  transport change.
- **Polished web review UI** — deferred; the review-domain API and operations model
  (§7.6) are v1 and are the future UI's contract.
- **Comprehensive migration framework** — deferred beyond the six Phase-3-minimum
  tools (§11), which are not deferrable.
- **Fully automated graph decisions** (entity- and graph-level) — architecture
  supports them; v1 is human-gated with the config-change automation path.
- **Multi-agent debate** — not an architectural tier; experimental `kg_eval` arm only.
- **Full 9-variant candidate implementations** — contracts complete in v1; pipelines
  for observation / derived-assertion / plan / ontology / identity-link land with the
  phases that need them (§5.2, §11).
- **Advisor automated scoring of all 12 factors** — v1 scores five; the rest ship as
  the structured checklist (§8).
- **Full temporal query support on every backend** — capability-declared; memory
  store first, others as adopters need them (§5.4).
- **A deployed KGIS/KGCS network service** — library-first; service wrapper later.
