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
