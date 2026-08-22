"""The gold set loads from JSON and hashes stably over its content only."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from kg_eval import GoldEntity, GoldRelation, GoldSet

FIXTURE = Path(__file__).parent / "fixtures" / "baseball_gold.json"


def test_loads_from_json_file() -> None:
    gold = GoldSet.from_json_file(FIXTURE)
    assert gold.gold_set_id == "baseball-v1"
    assert len(gold.entities) == 10
    assert len(gold.relations) == 4
    assert len(gold.attributes) == 4
    assert gold.attempted == 10


def test_from_json_string_equivalent_to_file() -> None:
    text = FIXTURE.read_text()
    assert GoldSet.from_json(text) == GoldSet.from_json_file(FIXTURE)


def test_evidence_span_is_parsed() -> None:
    gold = GoldSet.from_json_file(FIXTURE)
    span = gold.entities[0].evidence
    assert span is not None
    assert span.source_locator == "roster.csv#row1"
    assert span.quote == "Player 1"


def test_content_hash_is_stable_and_content_only() -> None:
    gold = GoldSet.from_json_file(FIXTURE)
    same = GoldSet.from_json_file(FIXTURE)
    assert gold.content_hash == same.content_hash

    # renaming the set / editing its description must NOT change the hash
    renamed = gold.model_copy(update={"gold_set_id": "other", "description": "changed"})
    assert renamed.content_hash == gold.content_hash

    # changing an actual label MUST change the hash
    mutated = gold.model_copy(update={"attributes": gold.attributes[:-1]})
    assert mutated.content_hash != gold.content_hash


class TestDuplicateKeysRejected:
    def test_duplicate_entity_key_raises(self) -> None:
        dup = GoldEntity(entity_type="Player", semantic_key="player/p1")
        with pytest.raises(ValidationError, match="duplicate entity gold key"):
            GoldSet(gold_set_id="g", entities=(dup, dup))

    def test_duplicate_relation_key_raises(self) -> None:
        rel = GoldRelation(
            relation_type="PLAYS_FOR", subject="Player:usssa:p1", object="Team:usssa:t1"
        )
        with pytest.raises(ValidationError, match="duplicate relation gold key"):
            GoldSet(gold_set_id="g", relations=(rel, rel))

    def test_distinct_keys_are_accepted(self) -> None:
        gs = GoldSet(
            gold_set_id="g",
            entities=(
                GoldEntity(entity_type="Player", semantic_key="player/p1"),
                GoldEntity(entity_type="Player", semantic_key="player/p2"),
            ),
        )
        assert len(gs.entities) == 2

    def test_loaded_fixture_has_unique_keys(self) -> None:
        # a smoke check that the shipped fixture itself is well-formed
        assert GoldSet.from_json_file(FIXTURE) is not None
