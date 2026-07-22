import pytest
from kg_contracts.curation import ProcessingState as PS
from kgis.ledger.lifecycle import (
    IllegalTransitionError,
    TERMINAL_STATES,
    assert_transition,
    can_transition,
)


def test_legal_forward_path():
    assert can_transition(PS.RECEIVED, PS.VALIDATED)
    assert can_transition(PS.VALIDATED, PS.RESOLUTION_PENDING)
    assert can_transition(PS.RESOLUTION_PENDING, PS.REVIEW_PENDING)
    assert can_transition(PS.REVIEW_PENDING, PS.ACCEPTED)
    assert can_transition(PS.RETRYABLE_ERROR, PS.VALIDATED)  # retry re-enters


def test_r1_obsolete_replaces_superseded():
    assert can_transition(PS.VALIDATED, PS.OBSOLETE)
    assert not hasattr(PS, "SUPERSEDED")  # ledger machine has no SUPERSEDED


def test_terminal_states_have_no_exits():
    for state in TERMINAL_STATES:
        assert not can_transition(state, PS.VALIDATED)


def test_illegal_transition_raises_naming_states():
    with pytest.raises(IllegalTransitionError, match="ACCEPTED.*RECEIVED"):
        assert_transition(PS.ACCEPTED, PS.RECEIVED)
