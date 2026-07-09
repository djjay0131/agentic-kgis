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
- Contract test suite in kg_contracts.testing; every GraphStore
  implementation must pass it.
- Graph-level decisions via registry + advisor, human-gated v1 (ADR-0005).
