"""Security/policy stub and universal trace ID (spec §5.9).

The universal trace ID is carried across the full pipeline: source record
-> extraction run -> candidates -> validation -> resolution -> curation
operation -> graph mutation -> derived indexes -> consumer query.

`PolicyContext` is a v1 **stub**. It is designed now, before the baseball
graph accumulates youth data, so that every later contract can carry a
policy context from day one. Full enforcement (redaction, tenant
isolation, deletion-behavior execution, etc.) is phased in per spec §5.9;
only the shape ships here.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from kg_contracts._ulid import new_ulid


class DeletionBehavior(StrEnum):
    """How a record should be handled when deletion is requested."""

    HARD_DELETE = "HARD_DELETE"
    TOMBSTONE = "TOMBSTONE"
    RETAIN = "RETAIN"


class PolicyContext(BaseModel):
    """v1 stub carrying policy metadata alongside a contract.

    Full enforcement is phased (spec §5.9); this model ships the shape
    so later contracts don't need a breaking change to add it.
    """

    model_config = ConfigDict(frozen=True)

    actor: str
    tenant: str | None = None
    purpose: str | None = None
    sensitivity_tags: tuple[str, ...] = ()
    redaction_policy: str | None = None
    deletion_behavior: DeletionBehavior = DeletionBehavior.TOMBSTONE


def new_trace_id() -> str:
    """Generate a new universal trace ID: `trace_` + a ULID."""
    return "trace_" + new_ulid()
