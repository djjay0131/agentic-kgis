"""Identity IDs, namespaced entity refs, and identity links (ADR-0008).

*Phase-0 lesson (ts-kg `canonical.py` / agentic-tskg 0/18 failure):* free-text
IDs destroy ingestion. The discipline that survived is: repair when the fix
is unambiguous, otherwise reject **naming the offending value** rather than
silently coercing it. ADR-0008 upgrades the format but keeps that discipline.

Every canonical entity gets an immutable internal identity ID shaped
`kg://<graph-id>/identity/<ulid>`. External aliases are namespaced
(`EntityRef{entity_type, namespace, key}`) and are only ever rendered as
`Type:namespace:key` at adapter boundaries — the bare `Label:key` form used
by ts-kg said nothing about who issued the key, and is deprecated: it MUST
NOT be accepted silently. `EntityRef.parse` is strict repair-or-reject;
unambiguous repair (e.g. case-folding a known namespace) is an admission-time
concern (KGCS, Plan 3), not a contract concern.
"""

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kg_contracts._ulid import new_ulid
from kg_contracts.evidence import Provenance

_GRAPH_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_IDENTITY_ID_RE = re.compile(
    r"^kg://(?P<graph_id>[a-z][a-z0-9-]*)/identity/(?P<ulid>[0-9A-Z]{26})$"
)
_ENTITY_TYPE_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")
_NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9_.-]*$")


class IdentityError(ValueError):
    """An identity ID or entity ref could not be constructed or parsed."""


def new_identity_id(graph_id: str) -> str:
    """Mint a new immutable identity ID: `kg://<graph-id>/identity/<ulid>`."""
    if not _GRAPH_ID_RE.match(graph_id):
        raise IdentityError(f"invalid graph_id {graph_id!r}: must match {_GRAPH_ID_RE.pattern}")
    return f"kg://{graph_id}/identity/{new_ulid()}"


def is_identity_id(value: str) -> bool:
    """Return True iff `value` is a well-formed identity ID."""
    return bool(_IDENTITY_ID_RE.match(value))


def parse_identity_id(value: str) -> tuple[str, str]:
    """Parse an identity ID into `(graph_id, ulid)`, or raise `IdentityError`."""
    match = _IDENTITY_ID_RE.match(value)
    if match is None:
        raise IdentityError(f"not a valid identity id: {value!r}")
    return match.group("graph_id"), match.group("ulid")


class EntityRef(BaseModel):
    """A namespaced external alias for an entity.

    `namespace` names who issued `key` (e.g. `doi`, `orcid`, `usssa`,
    `vttsi`, `postgres.intersections`). `render()`/`parse()` are for
    adapter boundaries only — internal code should carry `EntityRef`
    instances, not their string rendering.
    """

    model_config = ConfigDict(frozen=True)

    entity_type: str = Field(pattern=_ENTITY_TYPE_RE.pattern)
    namespace: str = Field(pattern=_NAMESPACE_RE.pattern)
    key: str

    @model_validator(mode="after")
    def _check_key(self) -> "EntityRef":
        if not self.key.strip():
            raise ValueError("key must be non-empty after strip")
        return self

    def render(self) -> str:
        """Render as `Type:namespace:key`, for use at adapter boundaries."""
        return f"{self.entity_type}:{self.namespace}:{self.key}"

    @staticmethod
    def parse(text: str) -> "EntityRef":
        """Strict repair-or-reject parse of `Type:namespace:key`.

        Splits on the first two colons. Raises `IdentityError` naming the
        raw input on any violation, including the deprecated bare
        `Label:key` form (ADR-0008): that message names the missing
        namespace explicitly so callers can't mistake it for a different
        failure.
        """
        parts = text.split(":", 2)
        if len(parts) == 2:
            raise IdentityError(
                f"invalid entity ref {text!r}: namespace is missing "
                "(bare Label:key is deprecated, ADR-0008)"
            )
        if len(parts) != 3:
            raise IdentityError(f"invalid entity ref {text!r}: expected Type:namespace:key")
        entity_type, namespace, key = parts
        try:
            return EntityRef(entity_type=entity_type, namespace=namespace, key=key)
        except ValueError as exc:
            raise IdentityError(f"invalid entity ref {text!r}: {exc}") from exc


class IdentityLinkKind(StrEnum):
    """How two identities relate across graphs."""

    SAME_AS = "SAME_AS"
    POSSIBLY_SAME_AS = "POSSIBLY_SAME_AS"
    RELATED_TO = "RELATED_TO"


class IdentityLink(BaseModel):
    """A cross-graph identity link, contract-complete in v1 (spec §5.1).

    Both endpoints must be valid identity IDs and may belong to different
    graphs. `authority` names who is entitled to assert the mapping and is
    mandatory and distinct from any confidence score (that lives on the
    resolution layer that produces links, not here).
    """

    model_config = ConfigDict(frozen=True)

    link_id: str = Field(default_factory=lambda: "il_" + new_ulid())
    left_identity: str
    right_identity: str
    kind: IdentityLinkKind
    authority: str
    provenance: Provenance
    evidence_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _check_endpoints(self) -> "IdentityLink":
        if not is_identity_id(self.left_identity):
            raise ValueError(f"left_identity is not a valid identity id: {self.left_identity!r}")
        if not is_identity_id(self.right_identity):
            raise ValueError(f"right_identity is not a valid identity id: {self.right_identity!r}")
        if self.left_identity == self.right_identity:
            raise ValueError("an identity link cannot link an identity to itself")
        return self
