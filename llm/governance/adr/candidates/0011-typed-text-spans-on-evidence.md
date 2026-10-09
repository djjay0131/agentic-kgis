# ADR candidate 0011: Typed character spans on evidence, and verified per-item quotes

Status: Proposed (awaiting owner promotion)
Date: 2026-10-09
Raised by: Issue #56 (KGPS upstream prerequisite; agentic-kgps#1)

## Context

Span provenance in KGIS was **chunk-level and string-encoded**. A chunk's
in-document coordinate is the fragment `chunk:{i}@chars:{s}-{e}`
(`src/kgis/extraction/documents.py`), folded into `Evidence.source_locator` as
`locator#fragment` (`src/kgis/extraction/provenance.py`). `Evidence` had no
typed span field, so the only way to recover the offsets was to regex-parse the
locator string. Individual extracted items carried no quote or sub-chunk span:
`JsonItemsParser` kept only `values` + `confidence`, contradicting the design
spec §6 promise of "document, span, model, prompt version" per item.

The downstream consumer **KGPS** therefore had to parse the locator
(`kgps/spans.py`) and could only cite a whole paragraph, so sentence-level
faithfulness checks were impossible. `kg_eval.goldset.EvidenceSpan.start/end`
existed but no metric used them.

This is a frozen-`kg_contracts` change. Per the versioning policy
(`src/kg_contracts/versioning.py`) a new **optional** field is a
backward-compatible minor bump; `CONTRACT_VERSION` moves `2.1.0 -> 2.2.0`.

## Decision

### 1. A typed `TextSpan` on `Evidence` (additive contract change)

Add `kg_contracts.evidence.TextSpan` (frozen; `start <= end` and non-negative):

```
TextSpan(start: int, end: int, quote: str | None = None)
```

with `[start, end)` as **document** character offsets — `document.text[start:end]`
is exactly the text the span covers. Add `Evidence.span: TextSpan | None = None`.
`present_evidence` gains an optional `span`. Nothing existing is invalidated and
the legacy `source_locator` string is **unchanged** (backward compatible).

The registry needs no schema change: it already persists the full
`Evidence.model_dump_json()` in its `evidence_json` column, so `span` round-trips
through `put`/`get`/`resolve` for free.

### 2. Every extraction evidence carries its chunk span

`build_chunk_evidence` sets `span=TextSpan(chunk.start, chunk.end)`, so
`document.text[span.start:span.end] == chunk.text` for every extracted
candidate's passage evidence.

### 3. Per-item quotes are verified, never trusted

`ExtractedItem` gains `quote`, `quote_start`, `quote_end`, and `warnings`.
`JsonItemsParser.parse` accepts the chunk (`chunk_text`/`chunk_start`) and lifts
an optional per-item `"quote"` out of the field bag. It **verifies the quote is
an exact substring of the chunk** and computes the document offsets
(`chunk_start + local_index`). A quote that is not an exact substring (or is
non-string or empty) is **dropped with a warning** — a paraphrase is never
stored as a verbatim quote. Dropped-quote warnings surface on the
`IngestionReport` as `code="quote_not_verified"`.

The match is **exact on the raw strings**: there is no Unicode or whitespace
normalisation — no NFC/NFKC folding, no collapsing or trimming of interior or
boundary whitespace. A curly apostrophe versus a straight one, a non-breaking
space versus a space, or a different run of spaces all fail closed and the
quote is dropped as `quote_not_verified`. This is deliberate: a normalising
matcher can silently widen the text a span claims to cover, and a dropped
quote is honest where a mangled one is not.

When two items quote the same text, each is anchored to the **next unused
occurrence** within the chunk (a per-parse set of used offsets), so each gets
its own document span and its own evidence id instead of collapsing onto the
first occurrence. Only when every occurrence is already claimed does an item
fall back to the first occurrence, so a repeated quote still verifies rather
than being dropped.

### 4. Verified quotes produce a span-narrowed `Evidence`

When an item carries a verified quote, extraction emits a second, span-narrowed
`Evidence` (deterministic id keyed on the chunk coordinates **and** the span
offsets plus the extractor/model/prompt versions) and cites it from the
candidate **in addition to** the chunk evidence. Both citations use
`EvidenceRelationship.DERIVED_FROM`.

Because the id folds in the chunk coordinates, **overlapping window chunks can
give the same document span two ids**: a `FixedWindowChunker` with overlap (or
any chunker whose windows overlap) may emit two chunks that both contain one
document character range, so one quoted sentence is collected under two
distinct evidence ids. This is not a correctness fault — both rows carry the
same document `span.start`/`span.end` and the same quote, and de-duplication on
the typed span (not the id) collapses them — but a consumer keying on
`evidence_id` alone will see two rows where it might expect one. It is recorded
here so the behaviour is a documented property, not a surprise; the alternative
(keying only on the document offsets) would collide when two documents share
offsets and would lose the chunk coordinate provenance.

The candidate cites the narrowed evidence; the `LLMExtractor` returns it
alongside the candidate (`ExtractionResult`/`ExtractedCandidate`) and the runner
— the single-threaded reduce point, and the only registry writer — persists it.

### 5. `kg_eval` scores typed-span overlap

`EvidenceValidity` gains `span_overlap_rate` (with `spans_with_offsets` /
`spans_overlapping`). Over each matched gold item that carries `start`/`end`, the
metric checks whether any cited PRESENT evidence carries a typed `Evidence.span`
at the same `source_locator` whose half-open interval overlaps the gold interval.
No matched gold item with offsets is an **honest null** (`MetricValue.insufficient`),
never a fabricated `0.0` (ADR-0009).

## Rationale

**Why `DERIVED_FROM` for both citations.** KGIS records *where a claim came
from*. Whether a quoted sentence actually *supports* (verifies) a claim is
KGCS/KGPS's judgement, not the extractor's — the same reasoning that made
`DERIVED_FROM` the grounding relationship in issue #60. Marking the narrowed
citation `SUPPORTS` would assert a verification KGIS never performed.

**Why verification lives in the parser.** A quote is only ever a verbatim
substring of the source or it is nothing. The parser is the one seam that sees
both the model's output and the chunk text, so it is the honest place to decide;
downstream code then cannot be handed a paraphrase dressed as a quote.

**Why a typed span, not a richer fragment string.** A string is un-queryable
without parsing and couples every consumer to the fragment grammar. A typed
field is the contract; the legacy string stays for backward compatibility so no
existing reader breaks.

**Why the offsets are in the evidence id.** Idempotency: re-extracting the same
document re-collects the same span evidence (`put` is idempotent by id), while
two different quotes in one chunk stay distinct. Keying on offsets rather than
the quote text keeps the id stable when wording outside the span changes.

## Alternatives Considered

### A richer fragment string (e.g. `...@chars:{s}-{e}#q:{qs}-{qe}`)

Rejected. It preserves the very defect being fixed — every consumer parses a
string — and the grammar grows without bound. The additive typed field is
strictly better and leaves the old string intact.

### Store the quote on `Evidence.content` only, no span

Rejected. `content` already carries the passage text; without offsets a
consumer cannot place the quote in the document, which is exactly the
sentence-level capability KGPS needs.

### `SUPPORTS` for the narrowed citation

Rejected (see Rationale). Verification is not KGIS's to claim.

### A `quote`/`span` field on `Candidate` instead of `Evidence`

Rejected. The evidence registry is where citations resolve and where erasure
already reaches (`ErasureCoordinator`); duplicating a span onto the candidate
would create a second, un-governed copy.

## Consequences

### Positive

- `document.text[span.start:span.end] == chunk text` for every extraction
  evidence; a verified quote's span resolves to exactly the quote.
- KGPS can drop `kgps/spans.py` string parsing and cite sub-chunk spans
  (agentic-kgps#1).
- `kg_eval` measures typed span overlap against gold offsets, honest-null when
  the gold set carries none.
- Purely additive: legacy locators, locator parsing, and already-produced
  evidence all keep working; `CONTRACT_VERSION` `2.1.0 -> 2.2.0`.

### Negative / Tradeoffs

- `Evidence` gains an optional field and `TextSpan` is a new public type that
  must then be kept stable.
- A quote the model paraphrases is dropped rather than captured, so extraction
  recall of usable spans depends on the model quoting verbatim.

### Risks

- Low. Additive and optional; the parser verifies before storing, so a bad model
  quote degrades to a warning, not corrupt provenance.

## Impacted Areas

- [ ] Product
- [x] Domain model
- [x] Data architecture
- [x] AI architecture
- [ ] Domain-specific systems (see governance delta)
- [ ] Integrations
- [ ] UX
- [ ] Security/privacy
- [x] Implementation
- [x] Documentation

## Related Documents

- Issue #56 (this repo); KGPS tracking issue djjay0131/agentic-kgps#1
- KGPS design spec §7:
  <https://github.com/djjay0131/agentic-kgps/blob/main/llm/specs/2026-10-07-kgps-design.md>
- ADR-0009 (kg_eval and the honest-null policy) — the overlap metric is
  honest-null when offsets are unknown
- ADR-0023 (candidate model / extractor-version fields) — the per-item
  provenance captured alongside the span
- Implementation: `src/kg_contracts/evidence.py`,
  `src/kg_contracts/versioning.py`, `src/kgis/extraction/provenance.py`,
  `src/kgis/extraction/parse.py`, `src/kgis/extraction/extractor.py`,
  `src/kgis/extraction/runner.py`, `src/kg_eval/metrics.py`
- Tests: `tests/contracts/test_evidence.py`,
  `tests/kgis/extraction/test_parse.py`,
  `tests/kgis/extraction/test_provenance.py`,
  `tests/kgis/extraction/test_extractor.py`,
  `tests/kgis/extraction/test_runner.py`, `tests/kg_eval/test_metrics.py`

## Related Issues / PRs

- Issue #56 (this repo)
- KGPS tracking issue djjay0131/agentic-kgps#1

## Supersedes

None.

## Superseded By

None.
