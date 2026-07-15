# ADR candidate: Record-scoped validation has no contract type

Status: Proposed (candidate)
Date: 2026-07-14
Raised by: Sprint 1 — Core Ingestion Engine (kgis)

## Context

The contract's `ValidationDecision` (spec §7.2, `kg_contracts.curation`) is the
recorded outcome of validating one candidate. Its first field is a required
`candidate_id`, and its `trace_id` likewise comes from a candidate.

Ingestion needs to reject malformed data **before** a candidate is built. The
sprint's own primary invariant — *validation failures never produce
candidates* — requires exactly this ordering: a row with an uncoercible value
or a missing key must be turned away at the record stage, and the whole point
is that no candidate is ever constructed for it.

So at the moment ingestion most needs to record a validation outcome, there is
no candidate, and therefore no `candidate_id` and no candidate `trace_id` to
populate the contract's `ValidationDecision`. The two requirements are in
direct tension:

- If we build the candidate first so it has an ID, then validate, a rejected
  record has already produced a candidate — violating the invariant.
- If we validate first, we have no `candidate_id` for the `ValidationDecision`.

Minting a throwaway `candidate_id` to satisfy the field would be worse than
either: it would name a candidate in the audit stream that was never proposed
and, by the invariant, must never exist. The universal trace ID (spec §5.9) is
supposed to make a real record traceable end to end; a fabricated one pointing
at a phantom candidate corrupts exactly the artifact it is meant to protect.

## Decision (proposed)

Recognize **record-scoped validation** as a first-class concept the contract
does not currently model, and add a contract type for it — a
`RecordValidationDecision` keyed on source coordinates (`source_type` +
`locator` + `fragment`, the idempotency anchor from spec §5.8) rather than on a
`candidate_id`.

Until the owner decides, Sprint 1 ships a `kgis`-local `RecordValidation`
(`src/kgis/validate.py`) that mirrors `ValidationDecision` field-for-field —
same `valid`/`failure_kind` biconditional, same `FailureKind` taxonomy, same
`policy_version` — but is keyed on `(index, coordinates)` and adds a
`warnings` field. Validation therefore runs in two tiers:

1. **Record tier** (`RecordValidation`, kgis) — before candidate creation.
   Delivers the invariant.
2. **Candidate tier** (`ValidationDecision`, contract) — after building, before
   submission. Delivers *CandidateSink always receives valid candidates*, and
   is the correct home for `UNSUPPORTED_ONTOLOGY`, which is a fact about a
   proposed term and so genuinely needs the candidate to exist.

## Rationale

The contract is not wrong; it is **ledger-scoped**. `ValidationDecision` lives
next to the ledger lifecycle, and the ledger only ever sees candidates — so
keying its validation record on a candidate is correct *for the ledger*.
Ingestion simply validates something the ledger never sees: raw records. The
gap is one of coverage, not correctness.

Promoting a record-scoped type into `kg_contracts` matters because every future
ingestion mode hits this same wall. LLM extraction (Plan 3) rejects
un-parseable spans before any candidate exists; a SQL source rejects rows that
violate a source constraint. Each will otherwise grow its own private
record-validation type, and the reusable contract-test discipline (spec §10.2)
cannot cover a type that only exists downstream.

## Alternatives Considered

### Make `candidate_id` optional on `ValidationDecision`

Smallest contract change, but it weakens a type that is correct in its own
domain: a *ledger* validation decision always has a candidate, and making the
field optional invites a `None` where the ledger requires a value. It also
conflates two genuinely different decisions (record vs candidate) under one
type, losing the record's `warnings` and its coordinate key.

### Keep `RecordValidation` permanently in `kgis`

Zero contract change, and it is what Sprint 1 does. The cost is that the
reusable suites cannot enforce record-validation conformance across
implementations, and each adopter reinvents the type — the exact fragmentation
the contracts layer exists to prevent.

## Consequences

### Positive

- The invariant *validation failures never produce candidates* becomes
  structurally guaranteed, not merely observed.
- Record and candidate validation stay independently testable.

### Negative / Tradeoffs

- One concept, two types (`RecordValidation` + `ValidationDecision`) until/unless
  the owner promotes the former. Their biconditional logic is duplicated.

### Risks

- If the two types drift (e.g. a new `FailureKind`), the record tier could lag
  the candidate tier. Mitigated by both importing the same `FailureKind` enum.

## Impacted Areas

- [x] Domain model
- [x] AI architecture
- [x] Implementation

## Related Documents

- `docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md` §7.2
- `src/kgis/validate.py` (the two-tier implementation)
- `docs/adr/0006-three-store-separation.md` (why the ledger is candidate-only)

## Supersedes

None.

## Superseded By

None.
