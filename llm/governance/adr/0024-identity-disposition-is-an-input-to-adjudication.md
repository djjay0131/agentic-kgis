# ADR-0024: The identity disposition is an input to the adjudication gate

Status: Accepted
Date: 2026-09-21
Raised by: Issue #43 — adjudication deadlock found by the `agentic-kg` adopter

## Context

`ConfidencePolicy.route()` took exactly one argument, a `CandidateScores`,
and refused `AUTO` unless `identity_confidence >=
auto_min_identity_confidence` whenever `require_identity_confidence_for_auto`
was set (the default). A *missing* `identity_confidence` deliberately blocked
`AUTO` rather than defaulting to pass — an honest-null design that is right
in itself.

**Nothing in this platform ever produces an `identity_confidence.**
Verified by exhaustive search of `kg_contracts`, `kgis` and `kg_eval` on
`main` at 34b5be7:

- `SourceScoring.to_scores()` (`src/kgis/builders.py`) is the *only*
  `CandidateScores` construction site in production code, and it sets
  `extraction_confidence`, `source_reliability` and `policy_risk` only. Its
  own docstring says the rest "start `None`: unknown, for curation to fill
  in later. Not zero, not one."
- The LLM extractor (`src/kgis/extraction/extractor.py`) copies scores
  forward updating `extraction_confidence` alone.
- The only other construction site is
  `src/kg_contracts/testing/factories.py` — a test double.
- `kg_eval` never constructs one.

So the gate demanded a score no candidate could carry. Measured in this
repository: a real `IngestPipeline` run over a 90-row structured source
emits **270 candidates, of which 0 route `AUTO`** under an unmodified
`ConfidencePolicy()` — all 270 route `LLM_ASSESS`, and all 270 carry
`identity_confidence=None`. Re-running with the most generous scoring the
platform can express (`SourceScoring(source_reliability=1.0,
extraction_confidence=1.0, policy_risk=0.0)`) still yields 0 `AUTO`.
Constructing the same policy with `require_identity_confidence_for_auto=False`
and changing nothing else flips all 270 to `AUTO`, isolating this gate as the
sole cause. The deterministic core therefore planned nothing, on any corpus,
for any adopter. (`agentic-kg` measured the same 0-`AUTO` result on a
different corpus and a different candidate count; the ratio, not the count,
is the invariant.)

The deeper fault is not the missing producer. It is that `route()` had no
way to know *what kind of identity claim it was gating*. `identity_confidence`
answers "is this the entity we think it is?" — a question that only exists
once there is an existing entity to be wrong about. A candidate proposing a
**brand-new** identity has no resolution to be confident about, so gating it
on a resolution score is a category error, and one the signature made
unavoidable: `ResolutionDecision.create_new_identity` — the field that knows
— was not an input to the gate.

## Decision

Make the identity disposition an explicit input to adjudication.

1. `kg_contracts.policy.IdentityDisposition`, a three-value `StrEnum`:
   `RESOLVED_EXISTING`, `NEW_IDENTITY`, `UNRESOLVED`.
2. `ConfidencePolicy.route(scores, identity_disposition=RESOLVED_EXISTING)`.
   The default is `RESOLVED_EXISTING` because that is the assumption
   `route()` always made implicitly; naming it re-routes no existing caller.
3. The identity gate, when `require_identity_confidence_for_auto` is set:
   - `RESOLVED_EXISTING` — requires `identity_confidence >=
     auto_min_identity_confidence`. A missing score blocks. Unchanged.
   - `NEW_IDENTITY` — an **absent** `identity_confidence` is not-applicable
     rather than unknown and does not block. A **stated**
     `identity_confidence` is still held to `auto_min_identity_confidence`.
   - `UNRESOLVED` — blocked outright. No resolver looked at this candidate,
     so a hand-supplied `identity_confidence` cannot buy `AUTO` for a
     resolution that never happened. This is strictly stronger than the
     previous behaviour.
   - Clearing `require_identity_confidence_for_auto` still disables the whole
     gate for every disposition.
4. `ConfidencePolicy.allow_auto_for_new_identity: bool = True` — the
   relaxation is data, not code (principle 9). An adopter that never wants an
   identity minted without oversight sets it `False` and every `NEW_IDENTITY`
   candidate floors at `LLM_ASSESS`, with no code change.
5. `ResolutionDecision.identity_disposition()` projects a resolution outcome
   onto the enum, so no caller derives it by hand:
   `create_new_identity` → `NEW_IDENTITY`; a named `resolved_identity` →
   `RESOLVED_EXISTING`; neither → `UNRESOLVED`.
6. A fail-closed narrowing (ADR-0021 pattern) on `ResolutionDecision`:
   `create_new_identity=True` forbids a non-null `resolved_identity`. Left
   representable, that contradiction would map to `NEW_IDENTITY` and waive
   the resolution gate for a decision that says, in its other field, that it
   resolved.

## Rationale

This is a **contract bug**, not a missing producer. `identity_confidence` is
confidence in a *resolution*, and a new identity has no resolution to be
confident about; there is no honest number to supply. The fix removes a
demand that could never be met, and removes it only where the demand was
meaningless.

The safety property the gate exists to provide survives intact, and is
pinned by tests that fail when it does not:

- A `NEW_IDENTITY` candidate still needs `extraction_confidence >=
  auto_min_extraction`, `source_reliability >= auto_min_source_reliability`,
  and a `policy_risk` inside `auto_max_policy_risk`. The identity dimension
  is the only one relaxed.
- A `NEW_IDENTITY` candidate whose resolver *did* state a low
  `identity_confidence` is still blocked. "Not applicable" excuses an absent
  score, never a low one.
- `UNRESOLVED` is now blocked unconditionally, closing a hole the old
  signature left open.
- The relaxation is reachable only by a caller that explicitly says
  `NEW_IDENTITY`, which asserts that a resolution pass ran and found no
  match. It is not silent, and it is not the default.

Consequently an adopter does not get `AUTO` for free: they get it by wiring
resolution output into the gate, which is exactly what ADR-0007 mandates
(stage 6, "deterministic policy gate routing on calibrated error risk and
consequence class: auto-link / retain separately / human review / gather
evidence / abstain"). "Retain separately" is `NEW_IDENTITY`.

## Alternatives Considered

### Produce an `identity_confidence` in KGIS extractors/builders

Rejected, and it is the worse option by a wide margin. KGIS holds no graph
read surface by design (ADR-0010, governance principle 3: "no
application-facing surface can mutate canonical graph state"; `builders.py`:
"KGIS holds no graph-write surface, so there is no 'helpful' direct upsert
to reach for"). It therefore cannot know whether an entity already exists,
and any number it emitted would be a *fabricated resolution confidence* —
precisely the dishonest null that `SourceScoring` was written to prevent.
For a genuinely new identity there is no true value to produce at all: `1.0`
and `0.0` are both lies. This option manufactures a number to satisfy a
check rather than fixing the check.

### Flip `require_identity_confidence_for_auto` to `False` by default

Rejected: it silently removes the gate for *every* candidate, including
those resolving onto existing identities where resolution confidence is
exactly the right thing to demand. It would trade a platform that plans
nothing for a platform that auto-merges on no identity evidence — a false
merge, which ADR-0007 records as the costlier error.

### Leave it to each adopter to configure

Rejected: every adopter hits this on day one, and the only configurations
that unblock them are the two rejected above. A default that no adopter can
use is a platform defect, not a configuration choice.

### Derive the disposition inside `route()` from the scores

Rejected: `CandidateScores` does not know, and cannot know, whether a
candidate resolves to an existing identity. Guessing (e.g. "absent score
means new identity") would reintroduce exactly the silent default the
honest-null design forbids, and would make `UNRESOLVED` unrepresentable.

## Consequences

### Positive

- The deterministic curation core can produce a non-empty plan, which it
  could not before, for any adopter, ever.
- The gate's hidden assumption is now explicit and auditable: every routing
  decision names which identity claim it was gating.
- `UNRESOLVED` is strictly safer than the behaviour it replaces.
- The relaxation is a policy field, so tightening it is a config change.

### Negative / Tradeoffs

- `route()` grows a parameter. Defaulted, so no existing call site changes.
- An adopter must now feed resolution output into the gate to reach `AUTO`.
  That is the intended architecture (ADR-0007), but it is work an adopter
  expecting `AUTO` from raw ingest scores will have to do.
- `NEW_IDENTITY` is a caller assertion the contract cannot verify — the same
  trust model as `source_reliability`.

### Risks

- A caller that passes `NEW_IDENTITY` indiscriminately weakens its own gate.
  Mitigated by the default (`RESOLVED_EXISTING`), by
  `allow_auto_for_new_identity`, and by
  `ResolutionDecision.identity_disposition()` making the correct derivation
  the path of least effort.
- False splits (a new identity auto-created where one already existed) rise
  if blocking recall is poor. That is the failure mode ADR-0007 already
  assigns to blocking and to `kg_eval` measurement, not to this gate.

## Impacted Areas

- [x] Domain model
- [x] AI architecture
- [x] Implementation
- [x] Documentation

## Related Documents

- `src/kg_contracts/policy.py`, `src/kg_contracts/curation.py`
- `tests/contracts/test_policy.py`, `tests/kgis/test_adjudication_routing.py`
- `llm/specs/2026-07-09-kgis-kgcs-design.md` §5.10, §7.4
- ADR-0007 (entity-resolution architecture), ADR-0009 (honest null),
  ADR-0021 (fail-closed contract narrowings)

## Related Issues / PRs

- Issue #43

## Supersedes

None. ADR-0004-as-amended's `CandidateScores` shape is unchanged; this ADR
changes what the *gate* demands of it, not what producers must state.

## Superseded By

None.
