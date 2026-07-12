# External Review Briefing: KGIS/KGCS Design (for ChatGPT)

Status: Draft
Last updated: 2026-07-09
Purpose: briefing packet pasted into ChatGPT to elicit design feedback and
mine prior discussion history. Responses land in
`docs/ai/chatgpt-feedback-2026-07.md`, then a disposition pass proposes
spec/ADR amendments.

---

## PASTE BELOW THIS LINE

I'm designing two reusable Python libraries that every knowledge-graph
project I run will adopt, and I want your critique plus anything relevant
you remember from our past conversations. Full design summary first, then
specific questions.

### What I'm building

**KGIS (Knowledge Graph Ingestion Service)** and **KGCS (Knowledge Graph
Curation Service)** — contract-first libraries (not deployed services)
consolidating patterns proven across my projects (research-paper KG on
Neo4j, traffic-safety KG on Spanner Graph, construction KG, planned
baseball athlete-development KG).

**Contracts (`kg_contracts`):** engine-agnostic `GraphStore` protocol (no
Cypher/GQL on the interface; Spanner/Neo4j/in-memory adapters), canonical
`Label:key` node IDs, and a universal `Candidate` type — every ingestion
mode emits candidates (proposed node/edge + confidence + provenance +
content hash), never raw writes.

**KGIS ingestion, two modes, one pipeline:** (1) deterministic structured
sync from databases (idempotent, confidence 1.0); (2) LLM extraction from
documents (parallel per-entity-type extractors defined as config — schema +
prompt + model — with failure isolation). Mandatory dry-run "plan" step
reports ontology coverage before first ingest.

**KGCS curation, layered write path:** an inline synchronous gate wraps
every graph write (canonical-ID repair-or-reject; declarative
data-backed-only ontology — types activate only when real data backs them;
versioned writes with SUPERSEDED_BY chains and rollback). Probabilistic
curation runs async: new entities land PROVISIONAL, then embedding-based
entity resolution routes by confidence — auto-merge (>0.95), single LLM
evaluator (0.80–0.95), multi-agent debate (0.50–0.80), human review queue
(below). Every merge reversible; every curation action gets an immutable
audit record. Rejections are quarantined data, not exceptions; the gate
fails closed.

**Multi-graph management:** a graph registry (one descriptor per graph:
domain, backend, ontology summary, owner, lineage) plus an extend-vs-new
advisor scoring four factors — domain overlap, ontology compatibility,
tenancy/access, lifecycle. v1 routes recommendations to a human; decisions
+ outcomes are recorded, and automation later means raising confidence
thresholds (config), calibrated on that recorded corpus.

**Adoption order:** baseball-ai (greenfield) first, then retrofit the
research-paper KG (acid test: KGCS must reproduce its existing curation
behavior), then the rest.

### Questions

1. **Memory mining:** What do you remember from our previous conversations
   about knowledge graphs — ingestion pipelines, curation, entity
   resolution, ontology design, multi-graph vs single-graph decisions,
   GraphRAG, or specific projects (traffic safety / VTTSI, research
   papers, construction, baseball)? List anything that contradicts,
   overlaps with, or should inform this design. Be specific about what we
   concluded, not just topics.
2. **Layered write path critique:** inline deterministic gate + async
   probabilistic curation over PROVISIONAL nodes. Where does this design
   break down? What failure modes am I not seeing (e.g., PROVISIONAL
   backlog, consumers reading half-curated graphs, merge conflicts between
   async promotions)?
3. **Entity resolution:** embedding-cosine thresholds (0.90/0.95) routed to
   LLM evaluators/debate/human. Is this still the right architecture in
   2026, or would you structure resolution differently (blocking + feature
   scoring, cross-encoders, clustering-based ER)? What calibration
   discipline should the thresholds have?
4. **Extend-vs-new advisor:** are my four factors (domain overlap, ontology
   compatibility, tenancy, lifecycle) the right ones? What factors do
   production multi-tenant graph platforms use that I'm missing?
5. **Gaps:** What's conspicuously missing for v1? Candidates I already
   deferred deliberately: streaming ingestion, web review UI, migration
   tooling for existing graphs, fully automated graph decisions. Wrong
   deferrals? Missing entirely (temporal validity, schema evolution,
   cross-graph entity identity, eval/benchmarks for extraction quality)?
6. **Prior art:** Libraries/systems solving this same "reusable ingestion +
   curation over pluggable graph stores" problem that I should study or
   reuse instead of building (Graphiti, LlamaIndex KG, LangChain graph
   transformers, Senzing, OpenRefine/dedupe patterns, DataHub/OpenMetadata
   governance patterns)?

Answer each numbered question under its own heading. For question 1,
distinguish clearly between what you actually remember from our chats vs
general knowledge.

## PASTE ABOVE THIS LINE
