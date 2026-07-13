"""Derivation lineage (spec §5.5).

Method determinism is not factual confidence: a stud-count calculation can
be perfectly deterministic while its inputs (wall extraction, scale,
opening recognition) are uncertain. Contracts therefore separate method
determinism (`deterministic`), source reliability, input confidence,
assertion confidence, and reproducibility (`reproducible`) instead of
collapsing them into one score.

Derivation lineage is a directed graph reachable by following `inputs`
refs — e.g. DWG → DXF → line segments → inferred wall → wall length →
stud quantity → takeoff → cut list — covering source artifacts,
transformation runs, code/config/model versions, input and output
assertions, warnings, units, and coordinate systems. A content hash alone
cannot capture this graph structure or the confidence signals riding
alongside it.
"""

from pydantic import BaseModel, ConfigDict, Field


class DerivationInput(BaseModel):
    """One input consumed by a derivation, referencing another record.

    `kind` names what `ref` points at — `"evidence"`, `"assertion"`,
    `"artifact"`, or `"candidate"` — and `ref` is that record's ID.
    Following `inputs` refs transitively is how the lineage graph is
    walked (e.g. from a stud-quantity assertion back through wall-length
    and inferred-wall assertions to the source DWG artifact).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str
    ref: str


class Derivation(BaseModel):
    """How a derived assertion was computed from canonical inputs.

    `deterministic` describes the *method* (would re-running it on the
    same inputs give the same output?) and is orthogonal to whether the
    `inputs` themselves are trustworthy — a deterministic stud calculation
    over an uncertain wall extraction is still deterministic. `reproducible`
    additionally tracks whether re-running is actually expected to succeed
    right now (e.g. `False` if the implementation or an external model it
    depends on has since changed incompatibly).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    method: str = Field(min_length=1)
    deterministic: bool
    inputs: tuple[DerivationInput, ...]
    implementation_version: str = Field(min_length=1)
    parameters: dict[str, object] = Field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    units: str | None = None
    coordinate_system: str | None = None
    reproducible: bool = True
