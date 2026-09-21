# kgis adopter notes

Gotchas an adopter wiring `kgis` into their own pipeline needs to know. These
are intentional behaviors, not bugs — documented here so their blast radius is
not a surprise in production.

## `CompositeCandidateBuilder`: all-or-nothing row rejection (issue #11)

This section is the source of truth for the behavior; the
`CompositeCandidateBuilder` docstring gives a one-paragraph summary and points
here.

`CompositeCandidateBuilder` fans one record across several sub-builders (e.g. a
player-entity builder plus a plays-for-relation builder). Its `required_fields`
property **unions every sub-builder's `required_fields`**, and the pipeline
composes those into a record-tier `RequiredValuesValidator` that runs *before
any builder does*. So:

> A record missing **one** sub-builder's required field is rejected as a whole
> row. Every candidate from every co-builder is dropped — not just the
> candidate that needed the missing field.

### Concrete example (baseball-ai)

A composite of a `Player`-entity builder and a `PLAYS_FOR`-relation builder,
over a row whose `team` is null:

- the relation builder needs `team` (a relation endpoint), so `team` is in the
  composite's unioned required set;
- the record therefore fails the record tier and is quarantined **whole**;
- the otherwise-valid `Player` **entity** is dropped too, even though the entity
  builder never needed `team`.

### Why it is this way

This is deliberate: "no partial candidates from a failed row" (PR #9 round-2),
so a half-ingested row can never leave a dangling entity with no relations, or a
relation with no entity. It is pinned by the pipeline row-rejection tests in
`tests/kgis/test_pipeline.py`.

### If you do not want this

Do not add a field to a sub-builder's `required_fields` if that field should be
optional to the row. Move the missing-value handling *inside* that builder's
`build()` (e.g. skip emitting the relation when `team` is absent) so the
co-builders' candidates still survive. `required_fields` is a hard, row-level
gate — reserve it for fields whose absence should sink the entire row.

## Installing without the `[dev]` extra (issue #37)

`pip install agentic-kgis` — no extras — is now enough to `import kgis`. Before
0.2.1 it was not: `kgis/evidence/__init__.py` eagerly imported a reusable
`pytest` suite, so `import kgis` raised `ModuleNotFoundError: No module named
'pytest'` unless you had installed `.[dev]`. The runtime dependency set is
`pydantic>=2.0` and nothing else, and `tests/test_packaging.py` now sweeps every
module in `kg_contracts`, `kgis` and `kg_eval` to keep it that way.

Nothing about the public surface changed. `from kgis.evidence import
EvidenceRegistryContract` and `from kgis.evidence.contract import
EvidenceRegistryContract` both still work; the first is resolved lazily, so it
pulls `pytest` only at the moment you touch the name — which is what you want,
since the suite is something you subclass in your own test run.

Two consequences of that laziness, if you are writing capability-detection code:

- `hasattr(kgis.evidence, "EvidenceRegistryContract")` **raises**
  `ModuleNotFoundError` in an environment without `pytest`, rather than
  returning `False` (`hasattr` only swallows `AttributeError`). Probe with
  `importlib.util.find_spec("pytest")` instead.
- `dir(kgis.evidence)` still lists the name, and `from kgis.evidence import *`
  still exports it.

### Pinning

There are still **no tags and no PyPI release** (issue #38), so a SHA remains the
only exact pin. The version bump to `0.2.1` at least makes the importable tree
distinguishable from the broken one: a build from this commit or later reports
`importlib.metadata.version("agentic-kgis") == "0.2.1"`, and a `pip`-resolvable
constraint of `agentic-kgis>=0.2.1` against a git install now means something.
`agentic-kgcs`'s `agentic-kgis>=0.2.0` does not.

## `AUTO` was unreachable before 0.3.0 (issue #43, ADR-0024)

If you wired `ConfidencePolicy` into a curation pipeline against 0.2.x and
found that *nothing* ever routed `AUTO`, this is why — and it was our bug, not
your wiring.

`ConfidencePolicy.route()` took only a `CandidateScores` and, by default,
refused `AUTO` unless `identity_confidence >= 0.95`. **Nothing in this platform
produces an `identity_confidence.** `SourceScoring.to_scores()` is the only
`CandidateScores` construction site in production code and never sets it; the
LLM extractor only ever updates `extraction_confidence`; `kg_eval` never
constructs one. The only other writer is `kg_contracts.testing.factories`, a
test double — which is why the unit tests passed while every real run
deadlocked.

Measured in this repository: a real `IngestPipeline` run over a 90-row
structured source produced 270 candidates and routed **0** of them `AUTO` under
an unmodified `ConfidencePolicy()`. Raising the source to
`SourceScoring(source_reliability=1.0, extraction_confidence=1.0,
policy_risk=0.0)` changed nothing. The `agentic-kg` adopter measured the same
0-`AUTO` outcome on a different corpus.

### What changed

`route()` now takes a second argument:

```python
policy.route(candidate.scores, IdentityDisposition.NEW_IDENTITY)
```

`IdentityDisposition` says what your resolution stage concluded:

| value | meaning | effect on the `AUTO` identity gate |
|---|---|---|
| `RESOLVED_EXISTING` (default) | linked to an existing identity | requires `identity_confidence >= auto_min_identity_confidence`; a missing score blocks |
| `NEW_IDENTITY` | no existing identity matched; a new one is minted | an **absent** score no longer blocks; a **stated** score is still enforced |
| `UNRESOLVED` | resolution did not run, or abstained | `AUTO` blocked outright |

The default is `RESOLVED_EXISTING`, which is what `route()` always assumed, so
**no existing call site changes behaviour**. You reach `AUTO` by feeding your
resolution outcome into the gate — which is what ADR-0007 always intended.

### How to wire it

If your resolver produces a `ResolutionDecision`, do not derive the disposition
by hand:

```python
route = policy.route(candidate.scores, decision.identity_disposition())
```

`ResolutionDecision.identity_disposition()` maps `create_new_identity` →
`NEW_IDENTITY`, a named `resolved_identity` → `RESOLVED_EXISTING`, and neither
→ `UNRESOLVED`. (`create_new_identity=True` with a non-null
`resolved_identity` is now a `ValidationError`: the two claims contradict.)

### What did *not* get weaker

`NEW_IDENTITY` relaxes the identity dimension and nothing else. A new-identity
candidate still needs `extraction_confidence >= auto_min_extraction`,
`source_reliability >= auto_min_source_reliability`, and a `policy_risk` inside
`auto_max_policy_risk`; and if your resolver *does* state a low
`identity_confidence`, that still blocks `AUTO`. If you want new identities
gated too, set `ConfidencePolicy(allow_auto_for_new_identity=False)` — a config
change, no code.

## `CREATE_IDENTITY` is now reversible (issue #44, ADR-0025)

`CurationOperationType` had no inverse for `CREATE_IDENTITY`, so a committed
curation run of creations — the normal first-ingest case — could not be
compensated at all. `REVOKE_IDENTITY` closes the gap.

- **Payload**: `{"identity_id": "<identity id>"}`, optional `"reason"`. Put the
  pre-revoke `CanonicalEntity` dump in the operation's `reversal_data` so the
  revoke is itself compensable by a `CREATE_IDENTITY`.
- **Effect**: a tombstone. `CanonicalEntity.status` becomes `REVOKED`; the
  record is retained and keeps its **original** `curation_epoch`, so an
  epoch-scoped read of the epoch that created the identity still finds it.
  Nothing is deleted and nothing is superseded.
- **Pairing**: `kg_contracts.INVERSE_OPERATION_TYPES` publishes which operation
  type compensates which. `PROMOTE_ONTOLOGY_TERM` is deliberately absent — it
  still has no inverse (issue #45).

### Read-semantics change — check this one

`GraphReadOptions` gains `include_revoked: bool = False`, **and `REVOKED`
records are now hidden from canonical reads by default.** Without that, a
revoke would change nothing any reader could observe.

`include_superseded` and `include_revoked` are independent; neither reveals the
other's records. If you were writing `REVOKED` entities or assertions by hand
and relying on seeing them in a default read, add `include_revoked=True`. No
in-platform operation produced `REVOKED` records before 0.3.0, so this only
affects records you constructed yourself.

### If you implement your own `GraphMutationStore`

You must handle `REVOKE_IDENTITY`. `MemoryGraphStore.apply()` is the reference
implementation: preserve `curation_epoch`, change only `status`, and refuse to
commit (`committed=False` with an `error`) when the named identity does not
exist rather than silently skipping it.

### Pinning

Still no tags and no PyPI release (issue #38), so a SHA remains the only exact
pin. The version is `0.3.0`; `agentic-kgis>=0.3.0` is the constraint that means
"has a reachable `AUTO` route and a reversible `CREATE_IDENTITY`".
