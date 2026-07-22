"""Consumer profile + identity mode — the adoption-gating surface (Issue #2)."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from kg_contracts.candidates import Candidate


class IdentityMode(StrEnum):
    AUTO_MERGE = "AUTO_MERGE"
    REJECT_ONLY = "REJECT_ONLY"


class ConsumerProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    identity_mode: IdentityMode = IdentityMode.AUTO_MERGE
    erasure_enabled: bool = False


BASEBALL_AI_PROFILE = ConsumerProfile(
    identity_mode=IdentityMode.REJECT_ONLY, erasure_enabled=True
)


@runtime_checkable
class IdentityResolver(Protocol):
    """Injected ambiguity oracle. Full ER lands in Plan 5; REJECT_ONLY only
    needs a yes/no ambiguity verdict at submit time."""

    def is_ambiguous(self, candidate: Candidate) -> bool: ...
