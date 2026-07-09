# Product Context — agentic-kgis

Every project here (agentic-kg, ts-kg/vttsi, construction-ai, baseball-ai)
builds a knowledge graph and each reinvented ingestion. KGIS consolidates
the two proven modes: idempotent structured sync (ts-kg sync.py lineage)
and parallel LLM extraction (agentic-kg ingest_papers lineage).

Consumers: baseball-ai first (greenfield), then agentic-kg (acid-test
retrofit), then ts-kg / construction-ai. Consumption model: contract +
library (ADR-0001) — no deployed service in v1.
