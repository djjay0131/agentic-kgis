import pytest
from pydantic import ValidationError

from kg_contracts._ulid import new_ulid
from kg_contracts.security import DeletionBehavior, PolicyContext, new_trace_id


def test_ulid_shape_and_uniqueness():
    a, b = new_ulid(), new_ulid()
    assert len(a) == 26 and a != b
    # Crockford base32: no I, L, O, U
    assert all(c in "0123456789ABCDEFGHJKMNPQRSTVWXYZ" for c in a)


def test_ulids_sort_by_time():
    import time

    a = new_ulid()
    time.sleep(0.002)
    b = new_ulid()
    assert a < b  # lexicographic order == creation order


def test_trace_id_prefixed():
    t = new_trace_id()
    assert t.startswith("trace_") and len(t) == len("trace_") + 26


def test_policy_context_stub_defaults_and_frozen():
    ctx = PolicyContext(actor="ingest-pipeline")
    assert ctx.deletion_behavior is DeletionBehavior.TOMBSTONE
    assert ctx.sensitivity_tags == ()
    with pytest.raises(ValidationError):
        ctx.actor = "someone-else"  # type: ignore[misc]


def test_policy_context_requires_actor():
    with pytest.raises(ValidationError):
        PolicyContext()  # type: ignore[call-arg]


def test_policy_context_rejects_unknown_field():
    with pytest.raises(ValidationError):
        PolicyContext(actor="ingest-pipeline", bogus=1)  # type: ignore[call-arg]
