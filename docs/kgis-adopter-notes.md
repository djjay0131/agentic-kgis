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
