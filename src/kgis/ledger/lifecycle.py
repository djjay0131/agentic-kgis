"""The candidate ledger's ProcessingState transition machine (spec §7.1-§7.2).

Distinct from canonical `CurationStatus` (ADR-0006). R1: the spec ledger
state `SUPERSEDED` is `OBSOLETE` here. Revoke/erase are row-governance
concerns (Task 10), not processing states, so they are absent here.
"""

from __future__ import annotations

from kg_contracts.curation import ProcessingState as PS

TERMINAL_STATES: frozenset[PS] = frozenset(
    {PS.ACCEPTED, PS.REJECTED, PS.INVALID, PS.OBSOLETE, PS.PERMANENT_ERROR}
)

LEGAL_TRANSITIONS: dict[PS, frozenset[PS]] = {
    PS.RECEIVED: frozenset(
        {PS.VALIDATED, PS.INVALID, PS.BLOCKED, PS.RETRYABLE_ERROR, PS.OBSOLETE}
    ),
    PS.VALIDATED: frozenset(
        {PS.RESOLUTION_PENDING, PS.REVIEW_PENDING, PS.ACCEPTED, PS.OBSOLETE, PS.RETRYABLE_ERROR}
    ),
    PS.BLOCKED: frozenset({PS.RECEIVED, PS.REJECTED, PS.INVALID}),
    PS.RESOLUTION_PENDING: frozenset(
        {PS.REVIEW_PENDING, PS.ACCEPTED, PS.REJECTED, PS.OBSOLETE, PS.RETRYABLE_ERROR}
    ),
    PS.REVIEW_PENDING: frozenset({PS.ACCEPTED, PS.REJECTED, PS.OBSOLETE}),
    PS.RETRYABLE_ERROR: frozenset({PS.VALIDATED, PS.RECEIVED, PS.PERMANENT_ERROR, PS.REJECTED}),
    # Terminal states — no outgoing transitions.
    PS.ACCEPTED: frozenset(),
    PS.REJECTED: frozenset(),
    PS.INVALID: frozenset(),
    PS.OBSOLETE: frozenset(),
    PS.PERMANENT_ERROR: frozenset(),
}


class IllegalTransitionError(ValueError):
    """A requested ProcessingState transition is not in `LEGAL_TRANSITIONS`."""


def can_transition(src: PS, dst: PS) -> bool:
    return dst in LEGAL_TRANSITIONS.get(src, frozenset())


def assert_transition(src: PS, dst: PS) -> None:
    if not can_transition(src, dst):
        raise IllegalTransitionError(
            f"illegal ledger transition {src.value} -> {dst.value}"
        )
