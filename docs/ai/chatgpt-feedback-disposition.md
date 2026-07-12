# Disposition: ChatGPT Feedback on KGIS/KGCS Design

Status: Revised after chief-reviewer findings (pending owner approval)
Last updated: 2026-07-10
Input: `chatgpt-feedback-2026-07.md` (verbatim capture)
Output when approved: design spec v2 + ADR amendments + **governance-delta
amendment** + memory-bank update + Plan 1 rewrite
Review: chief-reviewer verdict "Request Changes" (findings F1–F8) — all
findings addressed in this revision; see PR #1 discussion.

## Summary judgment

The feedback is high quality and mostly correct. It arrives at the ideal
moment: zero code exists, so the expensive changes (contracts, write-path
model, ER architecture) cost only re-planning. Recommendation: **accept the
architectural core of the feedback, producing spec v2**, with the
scope-control modifications below. The single biggest accepted change is
the candidate-ledger / canonical-graph separation, which supersedes part of
ADR-0003's "PROVISIONAL nodes in the graph" model.

## Accepted — architectural amendments (spec v2 + ADR changes)

| # | Item | Consequence |
|---|---|---|
| A1 | **Three-store separation**: candidate ledger (immutable assertions/workspace) / canonical graph (accepted identities+assertions only) / derived projections (disposable: GraphRAG, indices). Uncertain candidates never appear as ordinary graph entities. Curation epochs/watermarks; `GraphReadOptions` read contract. | New ADR-0006 superseding ADR-0003 in part (layered write path survives; "PROVISIONAL nodes in main graph" does not). Spec §3/§7 rewrite. |
| A2 | **Typed candidate model**: discriminated union of NINE variants (entity / relation / attribute-assertion / observation / derived-assertion / artifact / plan / ontology / identity-link — resolving the feedback's own §3-vs-§8 inconsistency by including Artifact and PlanCandidate as union members) + shared `CandidateEnvelope` + `CandidateScores` score set replacing single `confidence`. Multiple named representations (feature views) per candidate. Curation status attaches at assertion level, not only whole-node level (fact-level uncertainty must not be forced onto entity status). | Spec §5 rewrite; Plan 1 rewrite. See D2 for v1 variant subset. |
| A3 | **Evidence as first-class contract** (vttsi-evidence promotion): resolvable evidence IDs, availability present/absent/error, EvidenceRef relationships (supports/contradicts/derived_from/contextualizes), never silently dropped. | New contracts module + evidence registry in v1. |
| A4 | **Identity model**: immutable internal identity ID + namespaced external aliases (`EntityRef{entity_type, namespace, key}`; rendered `Label:namespace:key` at boundaries). Bare `Label:key` deprecated for cross-project use. | Amends canonical-ID contract; ts-kg `canonical.py` lineage preserved as the repair discipline, format upgraded. |
| A5 | **ER architecture replaced**: normalization/exact rules → multi-channel blocking (embeddings = one channel) → typed pairwise features (incl. mutually-exclusive evidence) → calibrated matcher → cluster validation → deterministic policy gate. LLM = bounded, evidence-citing adviser (`ResolutionAssessment`), never the merge authority (mirrors vttsi-llm-score's clamp-and-fallback discipline). Golden sets + cost-matrix threshold calibration; full score-vector logging. | New ADR; spec §7 rewrite. Embedding-threshold funnel (0.90/0.95 bands) dropped as the decision mechanism. |
| A6 | **Multi-agent debate demoted** from standard resolution tier to experimental kg_eval arm. | Amends spec §7. (Confidence routing as a *policy* concept survives for adjudication routing and the graph advisor; the Maker/Hater/Arbiter tier does not ship in v1.) |
| A7 | **Bitemporal assertions** (valid time + transaction time) in contracts from v1. | New contracts module. |
| A8 | **Derivation lineage** + method-determinism ≠ factual confidence. Deterministic sync no longer auto-`ACTIVE` at "confidence 1.0"; entry policy uses the score set (extraction certainty vs source reliability vs authority). | Amends spec §6/§7; new Derivation contract. |
| A9 | **Pure curation core / executor split**: Candidate → ValidationDecision → ResolutionDecision → CurationPlan → GraphMutationBatch → CommitResult, all serializable; executor applies with optimistic preconditions against a cluster snapshot. Curation actions as explicit operations (MERGE_IDENTITIES, SPLIT_IDENTITY, ...) with compensating rollback. | Replaces the "CuratedGraphStore wrapper" as the *internal* architecture; the unbypassable-gate *property* is preserved and strengthened via A10 (applications hold no synchronous write path at all). Durable decision → **new ADR-0010** (write-path mechanism: curation core, executor, two-level store contracts). |
| A10 | **Two-level store contracts**: `CandidateSink` (application-facing; the only surface projects get) and `GraphMutationStore` (internal, executor-only). Split reader/writer protocols + adapter capability declarations (supports_transactions, temporal, vector, ...). | Spec §5 rewrite; supersedes exposing raw `upsert_nodes` to consumers. |
| A11 | **Ontology lifecycle**: PROPOSED → APPROVED → OBSERVED → DEPRECATED, layered on data-backed activation (a type may be approved before instances exist; "active" for writes still requires approval, and observation is tracked separately). | Amends spec §7 ontology gate. |
| A12 | **Candidate processing states** (RECEIVED…RETRYABLE_ERROR/PERMANENT_ERROR) separated from entity curation status; failure taxonomy distinguishes bad data / unsupported ontology / transient faults. Gate scope limited to canonical semantic mutations (ledger/audit/index writes not gated). | Amends spec §7/§9. |
| A13 | **kg_eval package** (vttsi-eval pattern): named arms, ablations, honest-null discipline; extraction/resolution/graph-outcome metrics. LLM-enhanced pipelines must earn defaults on named metrics. | New package in agentic-kgis (see R2); added to plan sequence. |
| A14 | **Cross-graph identity contracts in v1** (global identity ID, graph-local ID, aliases, SAME_AS / POSSIBLY_SAME_AS / RELATED_TO, mapping authority+provenance). Implementation minimal; contracts complete. | New contracts module. |
| A15 | **Advisor upgraded**: 12-factor set; four outcome architectures (extend / shared-logical-separate-physical / separate-with-shared-identity-registry / fully-isolated) instead of binary extend-vs-new. | Amends ADR-0005 + spec §8. |
| A16 | **Conflict representation** (preserve competing assertions + evidence + preferred-resolution policy) and **source authority separated from confidence**. | Spec §7 addition. |
| A17 | **Backlog controls + milestone reporting**: ingest reports count extracted/validated/resolved/accepted/materialized/indexed separately; queue SLOs, backpressure, source quarantine. | Spec §6/§9 amendment. |
| A18 | **Adoption plan revised**: Phase 0 contract extraction from VTTSI → Phase 1 baseball (greenfield) → Phase 2 traffic *shadow* integration (fixtures, no rewrite) → Phase 3 research-paper retrofit (migration acid test) → Phase 4 construction (derivation/artifact modeling). Minimal migration tooling scheduled before Phase 3 — ALL SIX items the feedback marked non-deferrable: graph scanner, adapter export, candidate generation from existing graph state, invariant checker, dry-run diff, reconciliation report. Phase 0 is the research input to Plan 1 (contracts v2 written fresh with vttsi-contracts/ts-kg/vttsi-evidence as reference), not a separate plan. | Amends spec §11 AND the governance delta's adopter ordering. Each phase now has a distinct validation purpose. |
| A19 | **Review operations model** widened beyond approve/reject: edit, split, relabel, link, merge-elsewhere, "same concept, different scope" (OpenRefine reconciliation semantics). Review-domain API is v1; UI stays deferred. | Spec §7 amendment. |
| A20 | **Schema/ontology/extractor versioning** with compatibility classes (backward-compatible / revalidate / re-extract / migrate / rebuild-index); idempotency via stable source coordinates + semantic keys, not content hash alone. | Spec §5/§6 amendment. |
| A21 | **Security/policy contract stub + universal trace ID** (actor, tenant/purpose, redaction, deletion behavior) — designed before baseball accumulates youth data; full enforcement phased. | Spec §9 amendment; delta already flags youth data. |
| A22 | **Prior-art actions**: benchmark Splink AND dedupe as the calibrated-matcher baseline during the baseball PoC (buy-before-build for the matcher); study Graphiti (temporal), Senzing concepts (evidence-aggregation ER, why/why-not APIs), DataHub aspects (independently versioned metadata components), OpenMetadata (governance/trust metadata for the registry), OpenRefine (reconciliation ops). LlamaIndex property-graph extractors and LangChain LLMGraphTransformer are candidates for thin `Extractor` adapters behind the Candidate contract — never direct graph insertion. GraphRAG artifacts are disposable projections, never canonical, and **derived projections are built only from canonical data at a published epoch** (spec v2 invariant). | Research tasks in Plan sequence; no wholesale adoption. |

## Deferred (agreed or scoped)

| # | Item | Reason |
|---|---|---|
| D1 | Streaming ingestion; polished web review UI; comprehensive migration framework (beyond A18's six retrofit-minimum tools); fully automated graph decisions; multi-agent debate (now an eval arm). Constraint carried into v1 design: batch APIs must be shaped so a batch of one can later behave as an event (streaming stays a transport change, not a redesign). | Matches both our original deferrals and ChatGPT's list. |
| D2 | Full 9-variant candidate union *implementations*. Contracts define all nine variants in v1; v1 pipelines implement entity / relation / attribute-assertion / artifact. Observation, derived-assertion, plan, ontology, identity-link implementations land with the phases that need them (construction → derived/plan; retrofit → identity-link). | Keeps v1 buildable; contracts stay complete so no breaking change later. |
| D3 | Advisor automated scoring of all 12 factors. v1 scores identity value, ontology compatibility, tenancy, lifecycle, computational coupling; remaining factors appear as a structured human checklist in the Recommendation. | Human is in the loop in v1 anyway (ADR-0005); checklist preserves the full factor set without speculative scorers. |

## Rejected / modified

| # | Item | Disposition |
|---|---|---|
| R1 | Rename/reposition KGCS as an "assertion and identity curation layer". | **Keep the KGCS name** (repos, governance, memory established). **Adopt the framing** in the spec's mission language: KGCS manages knowledge admission, identity, evidence, and graph state — not domain reasoning. |
| R2 | Four-package split implying possible repo proliferation (kg-contracts / kg-ingestion / kg-curation / kg-eval). | **Accept the module boundaries, keep the two-repo layout** (ADR-0002 stands): agentic-kgis ships kg_contracts + kgis + kg_eval; agentic-kgcs ships kgcs. Extraction to more repos remains the documented escape hatch. |
| R3 | "Temporal canonical graph" fully realized in v1 (epochs + bitemporal queries on all backends). | **Contracts and canonical-graph data model: yes (A7). Full temporal *query* support on every backend: no** — capability-declared (A10), implemented first on the memory store, then per-backend as adopters need it. |

## Consequences

1. **Design spec v2** required — sections 3, 5, 6, 7, 8, 9, 11 change materially. The spec's core theses survive: contract+library, candidate-first, unbypassable admission path, provenance everywhere, confidence-policy-driven automation path, registry+advisor. New spec invariant: derived projections are built only from canonical data at a published curation epoch.
2. **Governance delta amendment** (agentic-kgis and agentic-kgcs) — four delta principles are invalidated by accepted items and must be reworded mechanism-neutrally: principle 2 (`Label:key` → namespaced identity/aliases per A4), principle 3 ("through CuratedGraphStore" → "no application-facing surface can mutate canonical graph state; only KGCS executors apply mutation batches", per A9/A10), principle 4 (single confidence → CandidateScores per A2), principle 6 (content hash → source coordinates + semantic keys per A20). Also: adopter ordering (A18 five-phase sequence replaces "baseball first, agentic-kg second") and milestone labels remapped to the new plan sequence.
3. **ADRs**:
   - ADR-0006 — three-store separation (candidate ledger / canonical graph / derived projections) + curation epochs. Supersedes ADR-0003's "PROVISIONAL nodes in the main graph" clause.
   - ADR-0007 — ER architecture: deterministic/statistical baseline + bounded evidence-citing LLM adviser + policy gate + cluster validation. Supersedes ADR-0003's Maker/Hater/Arbiter consensus-tier clause.
   - ADR-0008 — identity model: immutable internal identity ID + namespaced aliases.
   - ADR-0009 — kg_eval package + honest-null policy (LLM arms must earn defaults on named metrics).
   - ADR-0010 — write-path mechanism: pure curation core → CurationPlan → executor with preconditions; two-level store contracts (CandidateSink app-facing, GraphMutationStore executor-only). Supersedes ADR-0003's "CuratedGraphStore wrapper" clause.
   - ADR-0004 amendment — CandidateScores replaces single confidence; supersedes ADR-0003's "confidence-1.0 syncs enter ACTIVE" clause (entry policy now uses the score set).
   - ADR-0005 amendment — 12 advisor factors, four outcome architectures.
   - ADR-0002 amendment — agentic-kgis ships THREE packages (kg_contracts, kgis, kg_eval).
   - ADR-0003 net status: Accepted → Superseded in part, with every dead clause enumerated above and routed; the layered-write-path principle itself (deterministic admission inline-equivalent, probabilistic curation async) survives.
4. **Memory-bank updates** in both repos (activeContext/progress: spec v2 pending, revised plan sequence, disposition outcome) — per the governance review checklist.
5. **Plan 1 rewrite** before execution (contracts changed substantially). Plan sequence becomes: 1 bootstrap+contracts v2 (Phase 0 VTTSI reference reading feeds this) → 2 candidate ledger + evidence registry → 3 curation core + executor → 4 ingestion modes → 5a ER blocking/features/calibrated matcher + golden-set construction → 5b LLM adviser + cluster validation + Splink/dedupe benchmark → 6 kg_eval + review API → 7 registry + advisor.
6. **Scope honesty**: v1 build effort grows materially versus the original spec — net-new: evidence registry, candidate ledger, bitemporal contracts, kg_eval, review-operation API, and golden-set labeling (a human-labor line item for the baseball domain). The sunk cost of the amendments is near zero (no code existed), but total v1 cost is meaningfully higher; the trade is accepted deliberately for the reasons in the Summary.
7. **No code is invalidated** — nothing was built. Governance/bootstrap work is unaffected.

## Open questions for the owner

1. Approve this disposition as scoped (including R1–R3)?
2. Phase 0 "contract extraction from VTTSI" — extract from `vttsi-contracts`/`ts-kg`/`vttsi-evidence` as *reference reading* while writing kg_contracts v2 fresh (recommended), or literally import/vendor their code?
3. kg_eval as a third package in agentic-kgis (recommended, R2) — confirm.
