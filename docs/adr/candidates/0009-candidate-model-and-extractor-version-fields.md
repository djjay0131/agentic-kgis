# ADR candidate: First-class model / extractor-version fields on the candidate envelope

Status: Proposed (candidate)
Date: 2026-08-21
Raised by: Plan 4 — LLM document extraction (kgis)

## Context

LLM extraction (spec §6) must capture, per emitted candidate, *which extractor
and which model produced it* and at *which versions* — the spec's provenance
requirement is explicit: "full provenance (document, span, model, prompt
version)". Re-extraction identity and audit both depend on it.

`CandidateEnvelope` (frozen, `kg_contracts.candidates`) has no field for any of
this. Its provenance-bearing fields are `producer` (a single string),
`producer_run_id`, `ontology_version`, and `trace_id`. There is no `model_id`,
no `extractor_version`, no `prompt_version`, and no per-candidate model
representation slot beyond `representations[*].model`.

`Provenance` (`kg_contracts.evidence`) *does* carry `model` and
`prompt_version` — but only on `Evidence`, not on the candidate. A candidate
learns its model only transitively, by resolving an evidence ref.

## Decision (proposed)

Consider adding an optional, structured extractor/model provenance block to
`CandidateEnvelope` — e.g. `model_id: str | None`, `model_version: str | None`,
`extractor_id: str | None`, `extractor_version: str | None`,
`prompt_version: str | None` (or a single nested `ProducerInfo` model) — so a
candidate names its producing model and versions directly, without a caller
having to overload `producer` or resolve evidence to recover them.

This is additive and optional (structured-sync candidates leave them `None`),
so it does not break the frozen union.

## Rationale

The information is load-bearing for extraction provenance and for reproducing
or invalidating an extraction when a model or prompt changes (spec §5.6 version
classes: "extractor versions change"). Squeezing it into `producer` makes it
un-queryable without string parsing; routing it only through `Evidence.provenance`
means a consumer holding a candidate cannot answer "what model made this?"
without a registry round-trip that may fail (a dangling ref) for a reason
unrelated to the question.

## Plan 4 workaround (respecting the frozen contract)

No contract change was made. Extraction captures the provenance across the
three surfaces the current envelope *does* offer:

1. **`producer`** encodes extractor id + version:
   `kgis.extraction:<extractor_id>@<extractor_version>`
   (`ExtractorConfig.producer()`).
2. **`representations["source_passage"].model`** carries the `model_id` on the
   candidate itself (`LLMExtractor._finalize`), so a consumer holding only the
   candidate can read its model.
3. **`Evidence.provenance`** (`model`, `prompt_version`, `actor=extractor_id`)
   carries the full model + prompt versions on the passage evidence each
   candidate cites (`build_chunk_evidence`), which is the authoritative,
   audit-grade record.

This works and is honest, but the model/version live in three places instead of
one typed block, and `model_version`/`extractor_version` are only fully
recoverable via the evidence round-trip.

## Consequences

### Positive

- A candidate self-describes its producing model and versions, queryable
  without parsing `producer` or resolving evidence.
- Extraction, derivation (Phase 4), and any future model-backed producer share
  one provenance shape.

### Negative / Tradeoffs

- Adds optional fields to the frozen envelope that must then be kept stable.
- Overlaps `Evidence.provenance.model` — the two would need a documented
  relationship (candidate = self-report; evidence = audit record).

### Risks

- Low. Purely additive and optional; changes no existing behavior.

## Impacted Areas

- [x] Domain model
- [x] AI architecture
- [x] Implementation

## Related Documents

- `src/kgis/extraction/config.py` (`ExtractorConfig.producer`)
- `src/kgis/extraction/extractor.py` (`source_passage` representation)
- `src/kgis/extraction/provenance.py` (`build_chunk_evidence`)
- `docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md` §5.6, §6
- `docs/adr/0004-dual-ingestion-modes.md`

## Supersedes

None.

## Superseded By

None.
