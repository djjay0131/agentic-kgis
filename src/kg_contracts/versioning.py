"""Contract version and component compatibility classes (spec §5.8).

`CONTRACT_VERSION` is stamped into every `CandidateEnvelope` so downstream
consumers can tell which contract shape produced it. Independently,
`VersionChange` records a change to any *versioned component* (an
extractor, a prompt, an embedding model, a validation-rule set, ...) and
forces the author to declare its `CompatibilityClass` up front. Nothing
about a version bump is self-describing: two extractor versions can be
semver-adjacent yet demand a full re-extraction, while two prompt versions
three majors apart might be a no-op for already-extracted candidates. The
compatibility class is the machine-readable signal that downstream
pipelines (revalidation, re-extraction, graph migration, index rebuild)
key off of, so it is mandatory rather than inferred from the version
strings.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

CONTRACT_VERSION: str = "2.0.0"
"""Semver of the kg_contracts contract shape, stamped into every `CandidateEnvelope`."""


class VersionedComponentKind(StrEnum):
    """Kinds of components whose versions are tracked via `VersionChange`."""

    CANDIDATE_SCHEMA = "CANDIDATE_SCHEMA"
    ONTOLOGY_TYPE = "ONTOLOGY_TYPE"
    RELATIONSHIP_DEFINITION = "RELATIONSHIP_DEFINITION"
    VALIDATION_RULES = "VALIDATION_RULES"
    EXTRACTOR = "EXTRACTOR"
    PROMPT = "PROMPT"
    EMBEDDING_MODEL = "EMBEDDING_MODEL"
    RESOLUTION_FEATURES = "RESOLUTION_FEATURES"
    GRAPH_PROJECTION = "GRAPH_PROJECTION"


class CompatibilityClass(StrEnum):
    """What a version change demands of already-produced downstream data."""

    BACKWARD_COMPATIBLE = "BACKWARD_COMPATIBLE"
    REQUIRES_CANDIDATE_REVALIDATION = "REQUIRES_CANDIDATE_REVALIDATION"
    REQUIRES_RE_EXTRACTION = "REQUIRES_RE_EXTRACTION"
    REQUIRES_GRAPH_MIGRATION = "REQUIRES_GRAPH_MIGRATION"
    REQUIRES_DERIVED_INDEX_REBUILD = "REQUIRES_DERIVED_INDEX_REBUILD"


class VersionChange(BaseModel):
    """One version change of a component, with a mandatory compatibility class.

    `from_version=None` means this is the component's first introduction,
    in which case `compatibility` must be `BACKWARD_COMPATIBLE` — there is
    no prior version for a fresh component to be incompatible with.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    component_kind: VersionedComponentKind
    component_name: str = Field(min_length=1)
    # `min_length=1` closes the `from_version=""` loophole (issue #8; ADR
    # candidate 0007 — a pure loophole/bug fix): an empty string is not None,
    # so without this it slips past the `from_version is None` introduction
    # rule below while naming no prior version. "" is never a legitimate
    # version — reject it rather than silently coercing it to None (ADR-0008
    # repair-or-reject discipline).
    from_version: str | None = Field(min_length=1)
    to_version: str = Field(min_length=1)
    compatibility: CompatibilityClass

    @model_validator(mode="after")
    def _check_introduction_is_backward_compatible(self) -> "VersionChange":
        if (
            self.from_version is None
            and self.compatibility is not CompatibilityClass.BACKWARD_COMPATIBLE
        ):
            raise ValueError(
                "a component's first introduction (from_version=None) must be "
                "BACKWARD_COMPATIBLE"
            )
        return self
