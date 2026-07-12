# ChatGPT Feedback: KGIS/KGCS Design Review (verbatim capture)

Status: Captured
Last updated: 2026-07-10
Source: ChatGPT conversation, 2026-07-09/10, via the briefing packet in
`chatgpt-briefing-kgis-kgcs.md` (manual paste; PR #1). Two responses: the
initial review, and an updated review after ChatGPT read the GitHub repos
(baseball-ai, construction-ai, vttsi-contracts, vttsi-evidence,
vttsi-score-deterministic, vttsi-llm-score, vttsi-eval).
Disposition: `chatgpt-feedback-disposition.md`.

---

## Response 1: Initial review

Overall assessment

The core architecture is sound: candidate-first ingestion, a hard deterministic write gate, provenance everywhere, reversible curation, and backend-neutral contracts are the right foundations.

My main disagreement is with treating entity resolution as a mostly linear embedding-threshold funnel. Embeddings should help generate candidates and contribute evidence, but they should not be the primary decision statistic. I would also avoid physically writing every uncertain extracted entity into the main graph as a normal PROVISIONAL node. That can turn uncertainty into operational contamination.

The most important architectural distinction to sharpen is:

A candidate is an assertion about the world, not yet an entity in the world.

Preserve that distinction throughout KGIS and KGCS.

### 1. Memory mining

What I actually remember from our conversations

My retained context is much stronger for the research-paper system than for the traffic-safety, construction, or baseball graph implementations. I do not want to invent conclusions that I cannot substantiate.

Research-paper knowledge graph

We had settled on a system that would ingest scholarly material and extract more than bibliographic metadata. The graph was intended to capture:

- papers and authors;
- research problems;
- proposed ideas or approaches;
- assumptions and constraints;
- datasets and metrics;
- relationships such as EXTENDS, CONTRADICTS, DEPENDS_ON, or semantically similar links;
- provenance back to the paper and preferably the relevant text span.

The ingestion plan included PDF-to-text processing, document sectioning, and LLM-based structured extraction using a normalized JSON schema. You specifically wanted few-shot examples for identifying problem statements, assumptions, constraints, datasets, and metrics.

One concrete design we discussed was that a problem should have at least two embeddings:

- the raw problem statement;
- a richer representation combining the statement with assumptions and constraints.

That matters to KGIS: a universal Candidate should support multiple named representations or feature views, rather than one generic embedding field.

You also wanted the review interface to show extracted idea or problem cards with:

- accept;
- edit;
- delete;
- nearest-neighbor or related-problem suggestions.

That overlaps closely with KGCS's review and entity-resolution responsibilities. A useful conclusion is that review is not only approve/reject. It must support correction, splitting, relabeling, linking, and "same concept but materially different scope."

We discussed ranking research problems using signals such as:

- availability of a dataset;
- availability of metrics;
- venue quality or weight;
- confidence;
- freshness decay.

That argues for separating:

1. extraction confidence;
2. entity-resolution confidence;
3. evidence quality;
4. utility or ranking scores.

A single Candidate.confidence will become ambiguous quickly.

The earlier design also anticipated hybrid retrieval: symbolic graph traversal combined with vector similarity. The graph was not meant to replace vector retrieval, and vector similarity was not meant to define graph truth.

Ontology behavior

The research-paper design was already leaning toward domain-specific structured types, not a fully open-ended LLM-generated ontology. Extractors were expected to populate known concepts such as problems, assumptions, datasets, and metrics.

That supports your config-driven per-entity-type extractors.

However, the prior idea that extracted concepts could evolve through review conflicts somewhat with a literal interpretation of:

types activate only when real data backs them.

Data-backed ontology activation is useful, but an ontology also represents permitted meaning, governance, and intended future states. A new type may need approval before instances exist. I would distinguish:

- PROPOSED;
- APPROVED;
- OBSERVED;
- DEPRECATED;

rather than deriving ontology validity purely from instance counts.

GraphRAG

The prior research graph was intended to support question answering and discovery, but our conclusions implicitly favored a graph that was useful independently of RAG. That is important: do not let Microsoft-style GraphRAG community generation dictate your canonical graph model.

Microsoft GraphRAG builds an extracted entity graph, community hierarchy, and community summaries for retrieval. That is a useful derived index, not necessarily the authoritative domain graph.

Your reusable libraries should make GraphRAG artifacts disposable and reproducible:

- communities;
- summaries;
- retrieval projections;
- chunk-to-entity indices;
- cached neighborhood descriptions.

They should not be first-class canonical facts unless independently curated.

Multi-graph themes from other work

A recurring theme across your projects has been reuse without forcing unrelated domains into one schema. Your insurance/CDM work, although not presented as a KG project here, repeatedly exposed the danger of assuming that similarly named concepts have the same semantics across domains. Party, Account, Product, Coverage, and organizational ownership all needed explicit modeling rather than superficial name matching.

That informs the extend-vs-new advisor:

- lexical overlap is weak evidence;
- shared entity names do not imply ontology compatibility;
- ownership, lifecycle, security boundaries, and source authority can outweigh domain similarity.

What I do not reliably remember

I do not have sufficiently specific retained conclusions about:

- the VTTSI/traffic-safety ontology;
- the exact Spanner Graph ingestion architecture;
- construction graph curation behavior;
- baseball graph schemas;
- a previously agreed single-graph versus multi-graph decision for those projects.

I remember the broader project directions, but not enough verified detail to claim specific prior decisions.

General knowledge that should inform the design

Your design overlaps strongly with several established patterns:

- data contracts and staged ingestion;
- record linkage/reconciliation;
- event sourcing and bitemporal data;
- metadata lineage systems;
- human-in-the-loop data quality;
- materialized graph projections;
- entity registries or master-data-management systems.

The architecture will be stronger if KGCS is treated partly as a graph-oriented master-data and assertion-management layer, not merely an LLM cleanup service.

### 2. Layered write path critique

The biggest weakness: uncertain assertions become visible entities too early

Putting each uncertain extraction into the graph as a PROVISIONAL entity creates several problems:

- graph traversals can accidentally treat it as real;
- provisional duplicates inflate degree and community structure;
- GraphRAG summaries may repeat or amplify uncertain facts;
- consumers must remember to filter status everywhere;
- provisional nodes may acquire relationships before identity is resolved;
- a merge later changes neighborhoods and derived metrics unpredictably.

I would use three logical stores or namespaces:

1. Candidate ledger — immutable proposed assertions and entities: candidate ID; source record or text span; extractor and model version; ontology version; normalized payload; evidence; quality signals; deduplication fingerprint; processing state.
2. Canonical graph — only accepted identities and assertions, with explicit validity and confidence.
3. Derived projections — search indices, GraphRAG communities, embeddings, aggregates, summaries, and application-specific views.

These may live in the same physical database, but the contracts must make the separation unavoidable.

Backlog pressure

A provisional backlog can grow faster than curation capacity. The dangerous failure is not just storage growth. It is priority inversion:

- easy high-confidence candidates are processed quickly;
- difficult, high-value entities remain unresolved;
- repeated ingestion adds more candidates for the same unresolved cluster;
- human review becomes an unbounded queue;
- the system appears healthy because throughput remains high.

KGCS needs explicit backlog controls: queue age; queue depth by entity type and source; unresolved candidate-cluster size; value or risk priority; curation service-level objectives; maximum allowed provisional exposure; backpressure to KGIS; source throttling or quarantine.

Do not let KGIS claim a successful ingestion merely because candidates were emitted. Report separate milestones: extracted; validated; identity-resolved; accepted; materialized; indexed.

Consumer consistency

Filtering on status = ACCEPTED is not enough. Consumers need a read contract: canonical_only; canonical_plus_provisional; as_of_transaction_time; valid_at_domain_time; minimum evidence level; ontology version; curation snapshot or watermark.

Without a graph snapshot or curation watermark, one query can observe a partially promoted batch.

A good approach is an atomic curation epoch:

1. resolve and validate candidates;
2. prepare changes;
3. commit canonical mutations;
4. advance the graph's visible curation watermark;
5. rebuild or invalidate derived projections.

Readers use a published epoch rather than whatever happens to be present.

Concurrent merge conflicts

Two workers can make locally reasonable but globally incompatible decisions: merge A→B; merge B→C; simultaneously merge A→D; later discover that B and C should remain separate.

This is not solved by database transactions alone because the decisions may occur at different times and involve stale candidate sets.

Use: cluster-level locking or optimistic version checks; canonical representative versions; union operations with explicit preconditions; re-evaluation when a cluster changes; deterministic survivor selection; idempotent merge-operation IDs; a constraint that a candidate resolution is based on a recorded cluster snapshot.

The resolver should decide against an identity cluster, not against one arbitrary node.

Reversibility is harder than a SUPERSEDED_BY chain

A merge changes more than the node: relationships are rewired; properties are consolidated; aliases are added; derived embeddings change; summaries and communities change; downstream caches may consume the merged identity; external IDs may be republished.

A reversible merge therefore needs an operation log containing: pre-merge member set; property lineage; edge lineage; conflict-resolution decisions; canonical-ID changes; affected derived projections; downstream publication markers.

I would model curation actions as explicit operations: CREATE_IDENTITY; ATTACH_ASSERTION; MERGE_IDENTITIES; SPLIT_IDENTITY; REASSIGN_ASSERTION; RETRACT_ASSERTION; PROMOTE_ONTOLOGY_TERM.

A rollback is then a compensating operation, not deletion of history.

Canonical ID repair risk

Label:key is readable, but identity frequently outlives labels and natural keys.

Problems include: a paper title changes; an athlete changes teams; an organization renames; ontology labels are renamed; a source key was wrong; two source systems reuse the same key; the same real entity has several legitimate identifiers.

I would use an immutable internal identity ID and make Label:key a canonical locator or qualified alias:

kg://graph-id/identity/01J...

with aliases such as:

Paper:doi:10.xxxx/abcd
Athlete:usssa:12345
Organization:source-system:ABC

If Label:key must remain the public ID, make key namespace mandatory. Bare Player:123 is unsafe across projects.

Fail-closed can become fail-stopped

Failing closed is appropriate for canonical writes, but the system must distinguish: bad data; unsupported ontology; transient adapter failure; stale schema cache; unavailable embedding service; duplicated operation; infrastructure outage.

All should reject canonical mutation, but they need different retry and alert behavior. Otherwise transient faults become permanent quarantines.

"Every graph write" may be too broad

The synchronous gate should protect canonical semantic mutations. It should not necessarily gate: audit-log appends; candidate-ledger writes; queue-state transitions; derived-index updates; operational metadata.

Otherwise the gate becomes a single bottleneck and failure domain.

### 3. Entity resolution

Embedding thresholds should not be the architecture

In 2026, embeddings are useful evidence, but a cosine threshold of 0.90 or 0.95 is not portable across: embedding models; entity types; languages; text lengths; attribute composition; graph domains; candidate-pool difficulty.

A 0.95 similarity between two short organization names means something very different from 0.95 between two research-problem descriptions.

A better pipeline is:

Stage 1: normalization and exact rules — DOI, ORCID, VIN, permit number, source-native ID; normalized email or phone; canonical name variants; unit normalization; date and location normalization; deterministic source crosswalks. These rules should still produce explainable evidence rather than silently merging.

Stage 2: blocking or candidate generation — exact or phonetic name blocks; identifier prefixes; geography and date ranges; source-specific keys; approximate nearest neighbors from embeddings; graph-neighborhood overlap; type-specific lexical retrieval. Recall matters here. Embeddings fit well as one blocking channel.

Stage 3: pairwise feature computation — typed features: name similarity; identifier agreement or contradiction; temporal compatibility; geographic distance; shared affiliations; attribute rarity; source reliability; embedding similarity; graph-neighborhood compatibility; mutually exclusive evidence. The last category is critical. Two athletes with similar names but overlapping appearances on different teams at the same time may be different people.

Stage 4: calibrated matcher — probabilistic linkage; gradient-boosted classifier; logistic model; cross-encoder; rules plus learned weights. Splink implements scalable probabilistic record linkage and deduplication for records without unique identifiers. Its core pattern—blocking, comparison features, and probabilistic scoring—is much closer to the foundation you need than raw cosine thresholds. Senzing is also worth studying because it treats entity resolution as incremental evidence aggregation, emphasizes explainability, and now supports semantic embeddings as an additional scored signal rather than the entire method.

Stage 5: cluster consistency — pairwise matches do not automatically produce valid clusters. If A matches B; B matches C; A contradicts C — simple transitive closure is wrong. Add cluster-level constraints and re-score prospective cluster membership. Some entity types may permit one source record per source; others may permit many.

Stage 6: adjudication — route based on risk and uncertainty, not fixed similarity bands: auto-link when calibrated error risk is below the domain threshold; human review for high-impact uncertain cases; LLM explanation or evidence extraction where textual reasoning is useful; abstain when evidence is insufficient.

The LLM evaluator's role

Use an LLM to: normalize difficult unstructured attributes; compare supporting passages; identify contradictions; explain why a match may or may not hold; generate features for a calibrated decision system.

Do not let the LLM be the sole adjudicator for the middle band unless the cost of error is low.

Multi-agent debate

I would not make multi-agent debate a standard resolution tier in v1. It adds: cost; latency; correlated errors; difficult calibration; unstable outputs; audit complexity. Multiple agents using similar models and evidence are not independent votes. A better escalation is: 1. strong matcher; 2. independent evidence retrieval; 3. one constrained adjudicator; 4. human review for high-risk unresolved cases.

You can later test debate experimentally against the simpler baseline. Do not assume it improves resolution.

Calibration discipline

Maintain thresholds per: graph; entity type; source pair; matcher version; consequence class.

Measure at least: pairwise precision and recall; cluster precision and recall; false-merge rate; false-split rate; review yield; abstention rate; calibration error; performance by source and entity subtype.

False merges usually cost more than false splits because merges contaminate all attached facts. Define an explicit cost matrix.

You need a labeled golden set containing: obvious matches; obvious nonmatches; hard negatives; aliases; homonyms; near-duplicate descriptions; temporal conflicts; source-specific noise.

Thresholds should be learned from validation curves or expected-cost optimization—not selected because 0.90 and 0.95 sound conservative.

Also log the full score vector and model versions. A single stored final confidence is not enough to reproduce decisions.

### 4. Extend-vs-new advisor

Your four factors are necessary but insufficient.

Keep the four, but define them more precisely.

Domain overlap — split into: shared real-world entities; shared questions/use cases; shared source systems; shared vocabulary. Two graphs may share a domain but serve incompatible operational purposes.

Ontology compatibility — evaluate: concept equivalence; relationship semantics; cardinality constraints; identity rules; temporal model; evidence requirements; naming and identifier policies; schema governance authority.

Tenancy and access — include: row/node/edge-level policy capabilities; purpose limitation; consent; export restrictions; legal jurisdiction; data residency; deletion requirements; inference leakage through traversal or embeddings.

Lifecycle — include: update cadence; retention; archival policy; rebuildability; source-of-truth ownership; expected schema volatility; decommissioning authority.

Missing production factors:

Identity authority — who is allowed to declare that two entities are the same? A research-paper graph may trust DOI and ORCID. A baseball graph may have fragmented league and tournament identifiers. Shared identity is often the strongest reason to extend a graph—or the strongest reason not to.

Blast radius and failure isolation — can a bad ingestion corrupt unrelated workloads? can one ontology migration block another team? can a high-volume domain exhaust indexes or query resources? can an ER mistake cross tenant boundaries?

Workload compatibility — traversal patterns; write volume; analytical versus transactional use; latency requirements; full-text and vector needs; temporal query requirements; batch rebuild frequency; graph algorithm usage. Even semantically compatible graphs may need separate physical stores but a shared logical identity layer.

Scale and cost profile — node and edge growth; embedding volume; hotspot risk; index count; retention cost; curation workload; cross-domain traversal value.

Governance and stewardship — who owns: ontology changes; identity decisions; source onboarding; quality objectives; incident response; access approvals? Shared graph ownership can become organizational deadlock.

Compliance and sensitivity classification — a baseball athlete-development graph may contain minors' data. That makes cross-graph linkage, access, retention, and derived inference materially different from a public research-paper graph.

Deployment and availability requirements — different recovery-point, recovery-time, regional, and availability requirements can justify separate graphs.

Portability and backend affinity — some graphs may require features not evenly supported across backends: temporal indexing; vector search; full-text search; triggers; constraints; graph algorithms; transactional semantics.

Semantic coupling value — the advisor should estimate not only overlap, but the expected value of cross-domain traversal. Combining graphs without meaningful cross-domain questions creates cost without benefit.

Rebuild and deletion boundaries — a graph that can be regenerated entirely from papers behaves differently from one containing human curation or operational annotations that cannot easily be recreated.

Do not force a binary outcome. The advisor should return one of at least four architectures:

1. Extend the same logical and physical graph
2. Shared logical graph, separate physical partitions
3. Separate graphs with a shared identity registry
4. Fully isolated graphs with explicit cross-graph mappings

DataHub and OpenMetadata are useful analogues for graph registry design because they model ownership, domains/data products, lineage, quality, freshness, and operational context as first-class metadata.

### 5. Gaps

Assertion-level modeling — the central object should probably be an assertion: source asserts: subject / predicate / object/value / valid time / evidence / confidence. An entity and its asserted facts have different curation lifecycles. You can be certain that an entity exists while uncertain about one property. Do not force whole-node status to carry fact-level uncertainty.

Bitemporal semantics — add both valid time (when the fact is true in the domain) and transaction time (when the system learned, accepted, or superseded it). This matters across all four likely domains: paper affiliation changes; traffic conditions and events; construction status and ownership; athlete team, age group, measurements, and development history. Graphiti is worth studying specifically because it treats temporal facts, provenance, and evolving context as central concepts. Temporal validity should not be deferred.

Schema and ontology evolution — versioned contracts for: candidate schemas; ontology types; relationship definitions; validation rules; extractors; prompts; embedding models; resolution features; graph projections. Define compatibility classes: backward compatible; requires candidate revalidation; requires re-extraction; requires graph migration; requires derived-index rebuild.

Cross-graph identity — belongs in v1 at least at the contract level. Define: global identity ID; graph-local identity ID; alias or external identifier; SAME_AS, POSSIBLY_SAME_AS, and RELATED_TO semantics; authority and provenance for mappings.

Evaluation framework — this is absolutely v1. For extraction: entity precision/recall; relation precision/recall; attribute accuracy; evidence-span accuracy; hallucination rate; ontology violation rate; source coverage; stability across repeated runs. For curation: false merge and split rates; abstention; review agreement; rollback frequency; queue age; time to canonicalization. For graph usefulness: competency-question success; retrieval recall; answer faithfulness; provenance completeness; multi-hop query correctness. Microsoft GraphRAG itself warns that indexing is expensive, which reinforces the need to benchmark whether derived graph and community structures improve your actual tasks before making them default.

Source and evidence authority — confidence is not source authority. A deterministic database sync at confidence 1.0 may still contain incorrect or stale data. Record separately: extraction certainty; source reliability; source authority; freshness; corroboration; conflict status.

Conflict representation — do not overwrite conflicting claims simply because one wins curation. Preserve: both assertions; their evidence; their valid periods; the current preferred assertion; the resolution policy; unresolved conflict status.

Idempotency beyond content hashes — content hashes can fail when: the same fact is worded differently; document chunking changes; normalization changes; extractor version changes; source records are reordered. Use stable source coordinates and semantic assertion keys where possible.

Capability negotiation for graph adapters — a minimal GraphStore protocol risks becoming either lowest-common-denominator and weak, or secretly backend-specific through leaky abstractions. Define capability declarations: supports_transactions; supports_temporal_queries; supports_vector_search; supports_full_text; supports_constraints; supports_bulk_upsert; supports_snapshot_reads; supports_graph_algorithms. Keep Cypher/GQL out of the core interface, but allow optional capability-specific extension protocols.

Security and policy — add: actor identity; tenant and purpose context; policy decision; sensitive-field handling; redaction; audit access; deletion/tombstone behavior; derived-artifact deletion. This should be designed before the baseball graph accumulates youth data.

Observability — trace one source record through: source → extraction run → candidates → validation → resolution → curation operation → graph mutation → derived indexes → consumer query. That trace ID should be universal.

Deliberate deferrals — streaming ingestion: reasonable to defer; design batch APIs so a batch of one can later behave like an event. Web review UI: reasonable to defer the polished UI; do not defer the review-domain API or review-operation model (a CLI or notebook interface is enough for v1; OpenRefine's reconciliation workflow is worth borrowing conceptually). Migration tooling: a full migration framework can wait, but your second adoption target is explicitly a retrofit — therefore v1 needs at least: graph scanner; adapter export; candidate generation from existing graph state; invariant checker; dry-run diff; reconciliation report. Fully automated graph decisions: correct deferral. Multi-agent debate: I would defer this before several of the items above.

### 6. Prior art

No single project appears to provide your full combination. Building the integration layer is justified. But several components should be studied or reused:

- Graphiti — best source of ideas for temporal assertions and evolving facts (episode/source modeling; temporal fact invalidation; provenance; incremental ingestion; retrieval architecture). Do not adopt wholesale if backend neutrality and formal curation workflows are core requirements.
- LlamaIndex Property Graph Index — useful extraction and retrieval component, not the governance layer. Keep its output behind the Candidate contract.
- LangChain LLMGraphTransformer — useful thin extraction adapter; treat as one possible CandidateExtractor, not an architectural foundation.
- Senzing — strongest commercial-style ER reference: incremental entity resolution; feature-based evidence; relationship-aware resolution; explainability; "why" and "why not" APIs; semantic embeddings as one signal. Its conceptual model should strongly influence KGCS even without adoption.
- Splink — strong open-source baseline for structured entity resolution (blocking, comparison features, probabilistic scoring, threshold calibration).
- dedupe — worth evaluating for active-learning-assisted ER; compare directly with Splink during the baseball proof of concept.
- OpenRefine reconciliation — best reference for human adjudication semantics: candidate lists; reconciliation status; bulk judgment; match versus new-entity decisions; operation history; external authority matching.
- DataHub — best reference for registry, lineage, ingestion recipes, ownership, and assertions. Its "aspects" model is especially relevant: version independent semantic components instead of whole nodes.
- OpenMetadata — strong reference for governance and operational trust metadata (domains, data products, owners, lineage, quality tests, freshness, usage).
- Microsoft GraphRAG — use as a derived indexing and evaluation reference, not an ingestion foundation.

### Recommended v1 boundary

1. kg_contracts — Candidate, assertion, evidence, identity, graph descriptor, adapter capabilities, curation operation.
2. Candidate ledger — immutable, replayable, versioned, and separate from canonical graph semantics.
3. Deterministic gate — contract validation, identity syntax, ontology enforcement, policy checks, idempotency, and transaction-safe materialization.
4. Entity resolution baseline — normalization → multi-channel blocking → typed feature scoring → calibrated decision → human abstention. No multi-agent debate yet.
5. Temporal canonical graph — assertion-level provenance, valid time, transaction time, conflicts, reversible merge/split operations, and published curation epochs.
6. Evaluation and observability — golden datasets, extraction metrics, ER metrics, competency questions, lineage tracing, and dry-run diffs.

The architecture is worth building, but I would rename or reposition KGCS internally as an assertion and identity curation layer.

---

## [User to ChatGPT]: "great feedback. can u also connect to github and read through what the other repos have traffic, construction, baseball, and then provide an updated feedback?"

---

## Response 2: Updated feedback after reviewing the repositories

I reviewed the accessible GitHub repositories for: baseball-ai, construction-ai, vttsi-contracts, vttsi-evidence, vttsi-score-deterministic, vttsi-llm-score, vttsi-eval.

The biggest update to my earlier feedback is this:

KGIS and KGCS should consolidate the architectural disciplines already proven in VTTSI, but they should not absorb domain algorithms or turn every project output into a generic graph candidate.

The traffic repositories demonstrate a strong separation among contracts, evidence, deterministic computation, LLM augmentation, and evaluation. That separation is more mature than the initial KGIS/KGCS summary conveyed.

The construction project also reveals that your universal ingestion model needs to handle derived measurements and computation artifacts, not only extracted nodes and edges.

The baseball repository is currently essentially greenfield, so it remains the right first adopter—but it will not initially exercise all the difficult migration and compatibility cases.

### 1. What the repositories confirm

VTTSI already contains the seed of kg_contracts. The proposed contracts library is clearly descended from vttsi-contracts: a lightweight interface-only package; no database drivers or network code; Pydantic shared schemas; an engine-neutral GraphStore; canonical Label:key IDs; interchangeable protocol implementations; ports-and-adapters as the explicit architecture; freedom to change transport later.

So the core direction is validated. You are not inventing a speculative abstraction; you are promoting a working seam into a reusable library.

Updated recommendation: do not merely copy this interface into kg_contracts. Split it into narrower protocols (GraphReader, GraphWriter, TransactionalGraphWriter, BulkGraphWriter, TemporalGraphReader). Once Neo4j, Spanner Graph, research-paper ingestion, temporal curation, and rollback all share the interface, one broad protocol will become either too weak or too demanding. Use capability discovery so adapters can expose optional behavior without contaminating the base contract.

Canonical-ID repair solves a real prior failure. The Label:key decision was specifically introduced because the earlier traffic-KG ingestion produced human-readable labels where canonical identifiers were required. The existing behavior (preserve canonical, reject label conflict, strip label prefix, reject empty) supports the proposed repair-or-reject gate.

But modify the format before making it universal. The current implementation does not establish: graph namespace; source namespace; key type; identifier authority; escaping/normalization; versioning; aliases; graph-local vs globally meaningful IDs. Bare Player:1234 says nothing about who issued the key. Retain readability but qualify the key (Intersection:vttsi:101, Paper:doi:10.1145/..., Athlete:usssa:1234) or represent it structurally (EntityRef{entity_type, namespace, key}) and render as string only at adapter boundaries. Also add an immutable internal identity ID — a corrected natural key should not require replacing the entity's identity.

### 2. The traffic repositories suggest a better library boundary

Evidence is already a first-class system, not just candidate metadata. vttsi-evidence records: stable evidence ID; source; kind; time window; availability; payload; provenance; reason. Availability is explicitly present / absent / error. Providers do not throw failures upward; scores cite evidence IDs that resolve back to timestamped sources.

Updated recommendation: make Evidence its own contract (EvidenceRef{evidence_id, relationship: supports|contradicts|derived_from|contextualizes}; Evidence{evidence_id, source_type, source_locator, observed_at, valid_time, availability, payload_hash, content, error, provenance}). It should live in kg_contracts; storage and providers in KGIS or a small kg_evidence module.

Why absence matters: "no source queried", "source omitted it", "source unavailable", "sources contradict", "source states unknown" are different states. Representing them prevents an LLM seeing graph context from turning absent data into an inferred fact.

VTTSI demonstrates the right deterministic/LLM relationship. The LLM scorer: obtains the deterministic baseline; gathers additional evidence; asks the LLM for a bounded adjustment; requires rationale and cited evidence; clamps the adjustment; falls back to the deterministic result on any failure.

Updated entity-resolution recommendation: mirror that design — deterministic/statistical ER baseline → additional unstructured evidence → LLM produces bounded recommendation (ResolutionAssessment{recommendation: same|different|insufficient_evidence, evidence_ids, contradictions, rationale, confidence}) → deterministic policy gate makes the final decision. The LLM should not directly issue the merge. The LLM can improve the baseline, but it cannot silently make the result less grounded.

Failure should be represented, not erased. A candidate should not only be accepted/rejected/quarantined. Suggested processing states: RECEIVED, VALIDATED, INVALID, BLOCKED, RESOLUTION_PENDING, REVIEW_PENDING, ACCEPTED, REJECTED, SUPERSEDED, RETRYABLE_ERROR, PERMANENT_ERROR — and these must not be confused with ontology-level entity states such as PROVISIONAL.

### 3. The construction repository changes the Candidate design

Construction is a deterministic processing system (DWG/DXF/PDF parsing → wall geometry → stud/plate calculation → takeoff JSON; CV, LLM interpretation, optimization, code compliance planned). KGIS will eventually ingest outputs with fundamentally different epistemic status: parsed geometry; inferred boundaries; calculated counts; optimized plans; detected objects; interpreted annotations; compliance conclusions. Those cannot all be represented as proposed node/edge + confidence + provenance.

Updated recommendation: distinguish candidates, assertions, and artifacts — EntityCandidate, RelationCandidate, AttributeAssertion, DerivedObservation (metric, method, parameters), Artifact (type, content hash, source URI), PlanCandidate (inputs, objective). A generated cut list is not a fact about the building. A calculated takeoff is not necessarily an observed quantity. Putting all three into ordinary nodes and edges would blur reality, inference, and recommendation.

Deterministic does not automatically mean confidence 1.0. Stud calculation may be deterministic given correct wall extraction, scale, height, spacing, opening recognition, and rule assumptions — the computation can be perfectly deterministic while the inputs are uncertain. Separate: method determinism; source reliability; input confidence; assertion confidence; calculation reproducibility. Derivation{method, deterministic, inputs, implementation_version} makes output exactly reproducible without being declared unquestionably true.

KGIS needs derivation lineage, not only ingestion provenance: DWG → DXF → line segments → inferred wall → wall length → stud quantity → takeoff → cut list is a directed derivation graph. Provenance must support: source artifacts; transformation runs; code version; configuration; model version; input assertions; output assertions; warnings; units; coordinate systems; scale; reproducibility status. A content hash alone will not capture that.

The construction roadmap reinforces hybrid extraction: CAD parser, CV, LLM annotation interpreter, and building-rule engine each produce separate assertions and evidence; a curation policy combines them. Do not collapse them prematurely into one confidence score.

### 4. Baseball remains the right first adopter — with a qualification

baseball-ai is genuinely greenfield: good for establishing clean contracts, namespaces, ontology lifecycle, evidence handling, temporal history, resolution benchmarks, review operations, adapters, registry descriptors. But it will not prove: migration from existing schemas; compatibility with existing consumers; reproduction of legacy merge behavior; large provisional backlogs; Neo4j-vs-Spanner adapter differences; rollback of previously materialized identities; schema drift.

Adjusted adoption plan:

- Phase 0: contract extraction from VTTSI — generalize only the proven primitives (IDs, evidence, graph reader/writer protocols, provenance, operation results, failure representation).
- Phase 1: baseball greenfield.
- Phase 2: traffic shadow integration — wrap existing contracts, run KGIS/KGCS in parallel against traffic fixtures; do not rewrite traffic.
- Phase 3: research-paper retrofit — the true curation and migration acid test.
- Phase 4: construction integration — derivation, measurement, artifact, unit, and plan modeling.

### 5. Evaluation must be a first-class library, not a later feature

vttsi-eval provides: named interchangeable arms; deterministic-vs-LLM comparison; ablations; agreement and correlation metrics; bootstrap confidence intervals; explainability-compliance checks; structured reports; explicit support for a null conclusion when the LLM does not help. That honest-null discipline should be promoted into the reusable architecture.

Add kg_eval alongside KGIS and KGCS (kg-contracts, kg-ingestion, kg-curation, kg-eval). Extraction arms (rules-only, LLM-only, rules+LLM, parser+CV, parser+CV+LLM); resolution arms (exact identifiers, probabilistic linkage, embedding-only, cross-encoder, probabilistic+LLM adjudication, human gold standard); metrics as listed in Response 1.

Key policy: an LLM-enhanced pipeline should not become the default merely because it produces more output. It must demonstrate improvement on a named metric without unacceptably worsening false merges, unsupported assertions, review workload, latency, cost, or reproducibility.

### 6. Revised critique of the layered write path

Preserve the traffic repos' pure-core pattern. The deterministic scorer is pure logic with injected TrafficSource; the LLM scorer injects client, baseline, providers, resolver; prompt construction and response mapping are pure functions. KGCS should follow exactly this structure: a pure curation core (evaluate_candidate(candidate, graph_snapshot, ontology, policy) → decision, no database connection) and a separate executor (executor.apply(decision, expected_version)). This makes decisions testable, replayable, comparable, explainable, backend-independent.

Use decisions and operations, not a magical wrapping gate. Make it explicit: Candidate → ValidationDecision → ResolutionDecision → CurationPlan → GraphMutationBatch → CommitResult. Each object serializable and auditable. CurationPlan{plan_id, candidate_ids, snapshot_version, operations, preconditions, evidence_ids, policy_version}. The adapter applies a mutation batch only if preconditions still hold. This substantially reduces async merge conflicts.

Do not expose provisional identities as ordinary graph facts. Traffic separates evidence collection from scoring; unavailable evidence does not become a fake observation. Likewise an unresolved identity candidate should not become an ordinary domain entity merely because it was extracted. Recommended physical model: candidate ledger / assertion workspace; canonical domain graph; derived retrieval projections — may share one database but need separate labels, access paths, and reader contracts. A GraphRAG consumer should default to canonical data only.

### 7. Revised entity-resolution architecture

Steps: 1. deterministic identity rules; 2. blocking (lexical, geographic, temporal, source, embedding ANN, shared relationships); 3. statistical or learned baseline (calibrated probability from typed features); 4. evidence collection (missing evidence explicitly represented); 5. optional LLM assessment (citing evidence IDs); 6. deterministic policy (merge automatically / retain separately / request review / gather more evidence / abstain); 7. cluster validation (temporal constraints, unique-source membership, mutually exclusive attributes, cluster consistency, tenant boundaries).

Drop multi-agent debate from v1. The traffic design gets reliability from: strong deterministic baseline; structured output; cited evidence; bounded LLM authority; fallback; ablation testing. Multi-agent debate should remain an experimental evaluation arm, not an architectural tier.

### 8. Revised Candidate contract

Use a discriminated union: EntityCandidate | RelationCandidate | AttributeAssertionCandidate | ObservationCandidate | DerivedAssertionCandidate | OntologyCandidate | IdentityLinkCandidate, discriminated by candidate_kind.

All candidates share an envelope: CandidateEnvelope{candidate_id, graph_id, candidate_kind, producer, producer_run_id, contract_version, ontology_version, evidence_refs, source_coordinates, extraction_confidence, source_reliability, content_hash, semantic_key, created_at}.

Do not use one universal confidence. CandidateScores{extraction_confidence, identity_confidence, assertion_confidence, source_reliability, corroboration_score, policy_risk}. This prevents an exact database import from being interpreted as proof that the database's fact is correct.

### 9. Revised graph-store contract

The VTTSI GraphStore directly exposes upsert_nodes/upsert_edges — appropriate originally, but it conflicts with the rule that ingestion never performs raw writes.

Keep raw adapters internal. Two levels: GraphMutationStore (adapter-level, used only by KGCS executors: apply(batch, preconditions) → CommitResult) and CandidateSink (application-facing: submit(candidates) → SubmissionResult). Projects depend on CandidateSink, not GraphMutationStore — otherwise developers will bypass the pipeline by calling upsert_nodes() because it is convenient.

Graph reads need explicit consistency: GraphReadOptions{curation_epoch, valid_at, transaction_at, include_provisional, include_superseded, minimum_evidence_policy}. Without this, different projects will invent inconsistent filters.

### 10. Revised extend-versus-new advisor

Additional factor from the repos: computational semantics. Traffic contains domain scoring algorithms; construction contains geometry and material calculations. Those computations may use the graph but should not become graph-platform responsibilities. Ask: do the graphs merely share entities, or share assertion semantics, computational models, evidence policy, curation authority? Would joining them cause one domain's computed outputs to be mistaken for another domain's canonical facts?

Revised factor set (score at least): 1. shared identity value; 2. ontology compatibility; 3. assertion and evidence semantics; 4. temporal-model compatibility; 5. tenancy, privacy, and access; 6. lifecycle and retention; 7. workload and backend compatibility; 8. governance and stewardship; 9. failure/blast-radius requirements; 10. cross-domain traversal value; 11. computational-model coupling; 12. rebuild and deletion boundaries.

"Domain overlap" alone is too broad — two projects can both concern transportation while having no reason to share a canonical graph.

### 11. Updated v1 priorities

Required: 1. contracts (namespaced identities, candidates, assertions, evidence, source coordinates, temporal ranges, derivations, curation operations, adapter capabilities); 2. candidate ledger (immutable, replayable); 3. evidence registry (vttsi-evidence pattern: resolvable IDs, present/absent/error, timestamped provenance, no silent dropping); 4. deterministic curation core (pure functions creating plans); 5. mutation executor (backend-specific, transaction-aware, optimistic preconditions); 6. ER baseline (blocking, typed features, calibrated scoring, abstention, cluster checks); 7. evaluation harness (modeled after vttsi-eval, honest-null outcomes); 8. temporal assertions (valid + transaction time from the beginning); 9. derivation lineage; 10. review API (even without a polished UI).

Still reasonable to defer: streaming ingestion; polished web review interface; fully automated graph-placement decisions; multi-agent debate; comprehensive migration framework.

Cannot really be deferred: a minimal existing-graph scanner and dry-run diff; cross-graph identity contracts; evaluation; schema versioning; temporal validity; evidence availability states; adapter capability negotiation.

### 12. Final architectural shape recommended

kg-contracts (identity, evidence, candidates, assertions, temporal, derivation, operations, graph capabilities); kg-ingestion (structured sync, document extraction, CAD/parser ingestion, extractor orchestration, evidence providers, candidate ledger, plan/coverage analysis); kg-curation (validation, ontology policy, identity resolution, cluster validation, curation planning, review queues, mutation execution, rollback/compensation, audit); kg-eval (extraction benchmarks, resolution benchmarks, ablation arms, competency questions, provenance checks, structured reports); project-specific code (traffic scoring, construction calculations, baseball development models, research-paper ranking).

KGIS and KGCS should manage knowledge admission, identity, evidence, and graph state. They should not become the home for domain-specific reasoning algorithms. Traffic safety scoring belongs in the traffic project. Stud calculations belong in construction. Athlete-development assessment belongs in baseball. Research-opportunity ranking belongs in the research project. Those domain systems should consume and emit shared contracts, but remain independently testable components.

### Bottom line

After reading the repositories, I am more positive about the overall direction. The proposed libraries are a natural consolidation of patterns you have already implemented successfully.

The principal changes I would make are:

1. Promote evidence to a first-class shared contract.
2. Replace one flat Candidate with typed candidate/assertion variants.
3. Separate deterministic reproducibility from factual confidence.
4. Make the LLM a bounded, evidence-citing adviser to ER—not the merge authority.
5. Build kg-eval alongside KGIS and KGCS.
6. Keep uncertain candidates outside the ordinary canonical graph.
7. Use namespaced aliases plus immutable identity IDs instead of relying solely on Label:key.
8. Add derivation lineage for construction-style calculated outputs.
9. Preserve the current traffic repos' pure-core/injected-adapter architecture.
10. Use baseball to establish clean conventions, traffic to validate compatibility, research papers to validate migration and curation, and construction to validate derivations and artifact modeling.
