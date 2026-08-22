# System Patterns — agentic-kgis

- Ports and adapters: kg_contracts defines Protocols; engines/LLMs injected
  (ADR-0001, ADR-0002).
- Candidate as universal seam: both ingestion modes emit Candidate
  (proposal + confidence + Provenance); KGCS gate does all graph writes
  (ADR-0004).
- Canonical IDs: `Label:key`, PascalCase label — validated at GraphNode
  construction (type-level unbypassable).
- Layered write path (ADR-0003): deterministic gates inline, probabilistic
  curation async over PROVISIONAL nodes.
- Idempotency: content hash on every Candidate; re-ingest is a no-op.
  Durable across runs via the persistent (SQLite) candidate ledger + evidence
  registry, with a unified live-row predicate shared by index/dedup/reads.
- Contract test suite in kg_contracts.testing; every GraphStore
  implementation must pass it.
- Graph-level decisions via registry + advisor, human-gated v1 (ADR-0005):
  persistent RegistryStore + a 12-factor extend-vs-new advisor that emits four
  outcomes plus an INSUFFICIENT_INFORMATION honest-null and never auto-creates
  graphs.
- Honest-null throughout: kg_eval reports per named arm with abstention/
  hallucination metrics and honest-null ablation verdicts rather than forcing a
  score; the advisor and eval both prefer "insufficient information" to a guess.
