# ADR-0014: Identity mode and consumer profile as the adoption-gating surface

Status: Accepted
Date: 2026-07-21

## Context

Issue #2 asks for a way for a consuming application (first concretely,
baseball-ai) to adopt the candidate ledger without waiting for full entity
resolution (ER), which is scoped to Plan 5. baseball-ai specifically needs:

- A way to *not* silently auto-link two candidates whose identity is
  ambiguous — an incorrect auto-merge in a domain like player/roster
  identity is costly to unwind and erodes trust in the ledger as a source of
  truth.
- A clear, deterministic, per-application toggle set it can point to when
  answering "what does this ledger do for data governance," rather than a
  bespoke integration contract per consumer.

Full ER (calibrated scoring, adviser, deterministic policy gate — ADR-0007)
is a substantial piece of work deferred to Plan 5. Issue #2 needs something
real and testable *now*, without blocking on that work, and without
speculatively building ER machinery that Plan 5 might design differently.

## Decision

Introduce a small, explicit configuration surface in
`src/kgis/ledger/config.py`:

- **`IdentityMode(StrEnum)`**: `AUTO_MERGE` (default) and `REJECT_ONLY`.
  `AUTO_MERGE` is the ledger's existing behavior (submission does not itself
  reject on identity ambiguity — full auto-linking is Plan 5's concern).
  `REJECT_ONLY` rejects ambiguous identity matches at `submit()` time instead
  of auto-linking them: an ambiguous candidate becomes a synchronous
  `SubmissionOutcome(status=SubmissionStatus.INVALID, reason="ambiguous
  identity match rejected (REJECT_ONLY)")` — quarantined at the door rather
  than admitted and reconciled later.
- **`IdentityResolver` (runtime-checkable `Protocol`)**: a single-method
  ambiguity oracle, `is_ambiguous(candidate: Candidate) -> bool`, injected
  into `SqliteCandidateLedger.__init__`. This is deliberately *not* the full
  ER pipeline — it is a yes/no seam that lets `REJECT_ONLY` be real and
  testable today (see Task 10's test with an always-ambiguous stub
  resolver), with a full calibrated resolver dropped in later without
  changing the `submit()` contract or the ledger's public surface. No
  resolver (`None`, the default) means nothing is ever considered ambiguous,
  so `REJECT_ONLY` with no resolver behaves like `AUTO_MERGE` for identity
  purposes (harmless default; still correct if a consumer forgets to wire a
  resolver, since it is fail-open on this specific check rather than
  fail-closed in a way that would block all submissions).
- **`ConsumerProfile(BaseModel, frozen=True, extra="forbid")`**: bundles the
  toggles one consuming application selects at construction time —
  `identity_mode: IdentityMode = AUTO_MERGE` and
  `erasure_enabled: bool = False` (gates `erase()`, ADR-0013). This is the
  stable, versioned contract adopters point at, rather than a grab-bag of
  constructor kwargs on `SqliteCandidateLedger`.
- **`BASEBALL_AI_PROFILE = ConsumerProfile(identity_mode=REJECT_ONLY,
  erasure_enabled=True)`**: baseball-ai's concrete profile — it wants
  ambiguous identity matches rejected rather than auto-merged, and it wants
  the erasure surface (ADR-0013) turned on.
- `SqliteCandidateLedger.__init__` gains `profile: ConsumerProfile | None =
  None` (defaults to `ConsumerProfile()`, i.e. `AUTO_MERGE` +
  `erasure_enabled=False` — today's behavior, unchanged for existing
  callers) and `resolver: IdentityResolver | None = None`.

## Rationale

- **Adopters need a decision today, not a roadmap item.** Issue #2 is
  specifically about *unblocking baseball-ai's adoption*, not about shipping
  ER early. A profile + reject-only mode is a real, load-bearing governance
  decision a consuming app can make now, while full ER ships later on its
  own timeline (Plan 5) without invalidating this contract.
- **The oracle seam keeps this honest.** Rather than hand-waving "ambiguity
  detection" as a TODO, `IdentityResolver` is a real injected dependency with
  a trivial default (never ambiguous) and a fully testable override (always
  ambiguous), so `REJECT_ONLY`'s rejection path is exercised by an actual
  test today (Task 10), not left as an unverified stub.
- **One profile object beats scattered toggles.** Bundling
  `identity_mode`/`erasure_enabled` (and future toggles) into one frozen,
  named `ConsumerProfile` gives adopters (and this ADR) one stable thing to
  name and version, rather than an ever-growing constructor signature.
- **Default preserves existing behavior.** `ConsumerProfile()` defaults to
  `AUTO_MERGE` + `erasure_enabled=False`, so every existing caller of
  `SqliteCandidateLedger()` (Tasks 4-9) is unaffected; the new surface is
  strictly additive/opt-in.

## Alternatives Considered

### Build a minimal real ER pipeline now instead of an oracle seam

Rejected for this task. ADR-0007 already scopes a calibrated pipeline with a
bounded LLM adviser and a deterministic policy gate for Plan 5; building even
a "minimal" version now risks a second, divergent design and does not
unblock Issue #2 any faster than an injectable oracle does. The seam
(`IdentityResolver`) is deliberately the smallest interface that keeps
`REJECT_ONLY` swappable for the real thing later without a breaking change.

### Boolean flags directly on `SqliteCandidateLedger.__init__` instead of a `ConsumerProfile`

Rejected. Individual kwargs (`identity_mode=...`, `erasure_enabled=...`,
and whatever Issue #2 or future issues add) don't give adopters one stable,
named, versionable artifact to point at ("baseball-ai uses
`BASEBALL_AI_PROFILE`") and make it harder to keep the *set* of toggles
consistent — a `ConsumerProfile` model is the more honest artifact for what
is really a per-application governance policy object.

## Consequences

### Positive

- baseball-ai (and future adopters) get a concrete, named profile
  (`BASEBALL_AI_PROFILE`) to adopt today, satisfying Issue #2 without
  blocking on Plan 5 ER.
- `REJECT_ONLY` is genuinely testable now via the oracle seam, not a
  documented-but-unverified promise.
- Zero behavior change for existing callers (`AUTO_MERGE` + no resolver is
  the default and matches pre-Task-10 behavior).

### Negative / Tradeoffs

- `IdentityResolver` is a deliberately thin yes/no oracle; it does not carry
  match candidates, scores, or explanations the way a full ER adviser would.
  Consumers needing more than a boolean today must build their own resolver
  logic ahead of Plan 5's richer pipeline.
- `ConsumerProfile` will likely grow more fields as further adoption-gating
  issues surface; each addition needs its own default that preserves
  existing behavior (as `erasure_enabled=False` and `identity_mode=AUTO_MERGE`
  do here).

### Risks

- A consumer could set `REJECT_ONLY` without wiring a resolver, silently
  getting `AUTO_MERGE`-equivalent behavior for identity ambiguity. This is
  intentional fail-open behavior on this specific check (not a full failure
  mode) but should be called out prominently in any onboarding docs for
  `ConsumerProfile`.

## Impacted Areas

- [ ] Product
- [ ] Domain model
- [x] Data architecture
- [ ] AI architecture
- [x] Domain-specific systems (see governance delta)
- [ ] Integrations
- [x] Security/privacy
- [x] Implementation
- [x] Documentation

## Related Documents

- ADR-0007 (entity-resolution architecture) — the full pipeline this
  profile's `IdentityResolver` seam defers to
- ADR-0013 (ledger revoke and erasure) — `erase()` is gated by
  `ConsumerProfile.erasure_enabled` introduced here
- Plan: `docs/superpowers/plans/2026-07-17-plan-2-candidate-ledger-evidence-registry.md`
  (Task Group 1, Task 10)
- Implementation: `src/kgis/ledger/config.py` (`IdentityMode`,
  `ConsumerProfile`, `BASEBALL_AI_PROFILE`, `IdentityResolver`),
  `src/kgis/ledger/store.py` (`SqliteCandidateLedger.__init__`, `submit`)

## Related Issues / PRs

- Issue #2 (baseball-ai adoption-gating: revoke/erasure + reject-only
  identity)

## Supersedes

None.

## Superseded By

None.
