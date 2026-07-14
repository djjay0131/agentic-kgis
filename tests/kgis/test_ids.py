"""`IdStrategy` is the backbone of idempotency — these tests pin the exact
asymmetry between `candidate_id` (keyed on the fact) and `trace_id` (keyed
on the run) that the rest of the sprint's determinism guarantees rest on.
"""

from kgis.ids import (
    DeterministicIdStrategy,
    RandomIdStrategy,
    new_run_id,
    random_suffix,
    stable_suffix,
)

_FACT = {"graph_id": "g1", "candidate_kind": "entity", "semantic_key": "player/usssa/42"}


class TestStableSuffix:
    def test_is_pure(self) -> None:
        assert stable_suffix("a", "b") == stable_suffix("a", "b")

    def test_is_ulid_shaped(self) -> None:
        suffix = stable_suffix("a", "b")
        assert len(suffix) == 26
        assert set(suffix) <= set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")

    def test_part_boundaries_are_not_ambiguous(self) -> None:
        # Naive concatenation would make these collide.
        assert stable_suffix("ab", "c") != stable_suffix("a", "bc")

    def test_distinct_inputs_give_distinct_suffixes(self) -> None:
        assert stable_suffix("a") != stable_suffix("b")


class TestDeterministicIdStrategy:
    def test_same_fact_gives_same_candidate_id(self) -> None:
        strategy = DeterministicIdStrategy()
        assert strategy.candidate_id(**_FACT) == strategy.candidate_id(**_FACT)

    def test_candidate_id_ignores_the_run(self) -> None:
        """The whole point: a replay proposes the *same* candidate."""
        strategy = DeterministicIdStrategy()
        first = strategy.candidate_id(**_FACT)
        second = DeterministicIdStrategy().candidate_id(**_FACT)
        assert first == second

    def test_different_semantic_key_gives_different_candidate_id(self) -> None:
        strategy = DeterministicIdStrategy()
        other = {**_FACT, "semantic_key": "player/usssa/43"}
        assert strategy.candidate_id(**_FACT) != strategy.candidate_id(**other)

    def test_different_kind_gives_different_candidate_id(self) -> None:
        strategy = DeterministicIdStrategy()
        other = {**_FACT, "candidate_kind": "relation"}
        assert strategy.candidate_id(**_FACT) != strategy.candidate_id(**other)

    def test_different_graph_gives_different_candidate_id(self) -> None:
        strategy = DeterministicIdStrategy()
        other = {**_FACT, "graph_id": "g2"}
        assert strategy.candidate_id(**_FACT) != strategy.candidate_id(**other)

    def test_trace_id_is_stable_within_a_run(self) -> None:
        strategy = DeterministicIdStrategy()
        assert strategy.trace_id(run_id="r1", **_FACT) == strategy.trace_id(run_id="r1", **_FACT)

    def test_trace_id_differs_across_runs(self) -> None:
        """A replay must not collapse into the previous run's trace (spec §5.9)."""
        strategy = DeterministicIdStrategy()
        assert strategy.trace_id(run_id="r1", **_FACT) != strategy.trace_id(run_id="r2", **_FACT)

    def test_candidate_and_trace_ids_are_prefixed(self) -> None:
        strategy = DeterministicIdStrategy()
        assert strategy.candidate_id(**_FACT).startswith("cand_")
        assert strategy.trace_id(run_id="r1", **_FACT).startswith("trace_")


class TestRandomIdStrategy:
    def test_candidate_ids_are_fresh_each_call(self) -> None:
        strategy = RandomIdStrategy()
        assert strategy.candidate_id(**_FACT) != strategy.candidate_id(**_FACT)

    def test_random_suffix_is_ulid_shaped(self) -> None:
        suffix = random_suffix()
        assert len(suffix) == 26
        assert set(suffix) <= set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")

    def test_new_run_id_is_prefixed_and_unique(self) -> None:
        assert new_run_id().startswith("run_")
        assert new_run_id() != new_run_id()
