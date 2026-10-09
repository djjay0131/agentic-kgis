# Changelog

All notable changes to `agentic-kgis` (and the `kg_contracts` / `kg_eval`
packages it ships). Versions follow semver; `kg_contracts.CONTRACT_VERSION`
is versioned separately and noted per release.

## 0.5.0 — 2026-10-09

First tagged release (`v0.5.0`). 0.4.0 was intentionally skipped: the owner
chose to land the full KGPS (provenance) prerequisite set before tagging.
`kg_contracts` CONTRACT_VERSION: **2.0.0 → 2.2.0** (additive, backward
compatible). Consumers validating contract versions exactly should adopt
compatible-minor acceptance (agentic-kgcs#53).

### Added
- **Version provenance (ADR-0022, ADR-0023; #57, #64).**
  `SourceCoordinates.source_version`; `CandidateEnvelope.model_id /
  model_version / extractor_version / prompt_version`;
  `Provenance.model_version`. Populated by extraction and structured sync.
- **Provenance read ports (ADR-0029; #59, #66).**
  `GraphReader.get_assertion(assertion_id, options)` with the same visibility
  rules as `assertions_for`; `AdapterCapabilities.supports_assertion_lookup`;
  `SqliteEvidenceRegistry.subjects_for(evidence_id, relationship=None)`.
  Memory store rejects duplicate `assertion_id` attaches.
- **Typed spans and verified quotes (#56, #67).** `TextSpan(start, end,
  quote)` and `Evidence.span`; chunk evidence carries its span; per-item quotes
  are verified as exact substrings (repeated quotes anchor to successive
  occurrences) and emit span-narrowed evidence; `quote_not_verified` warnings;
  `kg_eval` `span_overlap_rate`.
- **Erasure coordinator (#61, #65).** `kgis.erasure.ErasureCoordinator`
  cascades a ledger erase to the evidence registry: refs removed, orphaned
  evidence redacted (content and span quote cleared, hash and offsets kept),
  redaction audited, re-ingestion cannot restore redacted content.
- `RESTORE_IDENTITY` reverses a revoke at the original epoch (ADR-0027, #55).

### Changed
- **`kg_eval` grounding vs. verification (#60, #62).**
  `unsupported_assertion_count` now means *ungrounded* (no PRESENT
  `SUPPORTS`/`DERIVED_FROM` evidence); new `unverified_assertion_count`
  (no PRESENT `SUPPORTS`). Previously real extraction output scored 100%
  unsupported.
- `OutputParser.parse` accepts keyword-only `chunk_text` / `chunk_start`
  (custom parsers with the old `parse(raw)` signature must add them).
- Revoke-identity assertion shield and batch semantics (ADR-0026, #49/#50, #54).

## 0.3.0 and earlier

Untagged; see git history and `docs/kgis-adopter-notes.md`.
