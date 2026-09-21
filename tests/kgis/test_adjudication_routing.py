"""End-to-end: candidates a real KGIS run produces must be routable to AUTO.

The defect this pins (issue #43, ADR-0024) was not visible from the contract
layer alone. `ConfidencePolicy` looked correct in isolation and its unit
tests passed — because every one of them hand-supplied an
`identity_confidence`. No *producer* in this platform ever sets that score
(KGIS structurally cannot: it holds no graph read surface, so it cannot know
whether an entity already exists), so a policy that required it required
something no candidate could ever carry, and a measured run routed 0 of 270
candidates to AUTO.

So this suite routes candidates that came out of an actual `IngestPipeline`,
not out of a factory, and asserts counts on both sides of the boundary —
`0 < auto == total` — so it cannot pass by quantifying over an empty set.
"""

from typing import Sequence

from kg_contracts.candidates import Candidate
from kg_contracts.policy import AdjudicationRoute, ConfidencePolicy, IdentityDisposition
from kg_contracts.testing.memory import MemoryCandidateSink
from kgis.builders import SourceScoring
from kgis.clock import FixedClock
from kgis.ids import DeterministicIdStrategy
from kgis.pipeline import IngestPipeline
from kgis.sources.iterable_reader import IterableRecordReader
from scenarios import NOW, player_builder, player_schema

ROWS: tuple[dict[str, str], ...] = tuple(
    {"id": str(i), "name": f"P{i}", "team": str(i % 7), "height_cm": str(150 + i % 40)}
    for i in range(1, 31)
)


def _run(scoring: SourceScoring) -> Sequence[Candidate]:
    sink = MemoryCandidateSink()
    IngestPipeline(
        graph_id="baseball",
        reader=IterableRecordReader(list(ROWS)),
        normalizer=player_schema(),
        builder=player_builder(),
        sink=sink,
        scoring=scoring,
        clock=FixedClock(NOW),
        ids=DeterministicIdStrategy(),
        run_id="run-fixed",
        job_id="job-fixed",
    ).run()
    return sink.received()


def _route_counts(
    candidates: Sequence[Candidate],
    policy: ConfidencePolicy,
    disposition: IdentityDisposition,
) -> dict[AdjudicationRoute, int]:
    counts = {route: 0 for route in AdjudicationRoute}
    for candidate in candidates:
        counts[policy.route(candidate.scores, disposition)] += 1
    return counts


def test_no_kgis_producer_sets_an_identity_confidence():
    # The root cause, stated as an executable fact rather than a grep: the
    # score the gate demands is one no ingestion path fills in.
    candidates = _run(SourceScoring(source_reliability=1.0, extraction_confidence=1.0))
    assert len(candidates) > 0
    assert [c.scores.identity_confidence for c in candidates] == [None] * len(candidates)


def test_new_identity_candidates_from_a_real_run_route_auto():
    # The fix, measured where the defect was measured. A perfect structured
    # read of a fully trusted source, resolved as minting new identities,
    # routes AUTO for EVERY candidate — not "at least one", and not
    # vacuously zero.
    candidates = _run(SourceScoring(source_reliability=1.0, extraction_confidence=1.0))
    total = len(candidates)
    assert total > 0

    counts = _route_counts(candidates, ConfidencePolicy(), IdentityDisposition.NEW_IDENTITY)
    assert counts[AdjudicationRoute.AUTO] == total
    assert counts[AdjudicationRoute.LLM_ASSESS] == 0
    assert counts[AdjudicationRoute.HUMAN] == 0


def test_the_same_run_still_routes_nothing_auto_as_an_existing_identity():
    # The honest-null gate is intact where it belongs: presented as
    # resolutions onto EXISTING identities, the identical candidates carry no
    # resolution confidence and none of them may route AUTO.
    candidates = _run(SourceScoring(source_reliability=1.0, extraction_confidence=1.0))
    total = len(candidates)
    assert total > 0

    counts = _route_counts(
        candidates, ConfidencePolicy(), IdentityDisposition.RESOLVED_EXISTING
    )
    assert counts[AdjudicationRoute.AUTO] == 0
    assert counts[AdjudicationRoute.LLM_ASSESS] == total


def test_a_mediocre_source_does_not_route_auto_even_as_a_new_identity():
    # The fix relaxes the identity dimension only. A source nobody has
    # reason to trust still cannot auto-apply.
    candidates = _run(SourceScoring(source_reliability=0.5, extraction_confidence=1.0))
    total = len(candidates)
    assert total > 0

    counts = _route_counts(candidates, ConfidencePolicy(), IdentityDisposition.NEW_IDENTITY)
    assert counts[AdjudicationRoute.AUTO] == 0
    assert counts[AdjudicationRoute.LLM_ASSESS] == total
