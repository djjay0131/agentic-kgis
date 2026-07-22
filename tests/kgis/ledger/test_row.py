from datetime import UTC, datetime

from kg_contracts.curation import ProcessingState
from kg_contracts.testing.factories import make_entity_candidate

from kgis.ledger.row import LedgerRow, dedup_key, payload_hash

NOW = datetime(2026, 7, 21, tzinfo=UTC)


def test_dedup_key_uses_graph_and_semantic_key():
    c = make_entity_candidate(graph_id="baseball", key="team/42", semantic_key="team/42")
    assert dedup_key(c) == "baseball\x1fteam/42"


def test_dedup_key_does_not_collide_across_graph_semantic_key_boundary():
    """Without a delimiter between graph_id and semantic_key, distinct
    (graph_id, semantic_key) pairs can concatenate to the same string
    (e.g. "ab"+"cd" == "abc"+"d" == "abcd"). The ASCII Unit Separator
    (0x1F) between them prevents this collision.
    """
    c1 = make_entity_candidate(graph_id="ab", key="k1", semantic_key="cd")
    c2 = make_entity_candidate(graph_id="abc", key="k2", semantic_key="d")
    assert dedup_key(c1) != dedup_key(c2)


def test_for_candidate_projects_received_entry():
    c = make_entity_candidate(key="team/42")
    row = LedgerRow.for_candidate(c, recorded_at=NOW)
    assert row.processing_state is ProcessingState.RECEIVED
    assert row.received_at == c.created_at
    assert row.payload_hash == payload_hash(c)
    entry = row.to_entry()
    assert entry is not None
    assert entry.candidate.candidate_id == c.candidate_id
    assert entry.received_at == c.created_at


def test_erased_row_projects_none():
    c = make_entity_candidate(key="team/42")
    row = LedgerRow.for_candidate(c, recorded_at=NOW).model_copy(
        update={"payload_json": None, "erased_at": NOW, "erasure_reason": "gdpr"}
    )
    assert row.is_erased
    assert row.to_entry() is None
