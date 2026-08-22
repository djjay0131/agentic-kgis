"""Named evaluation arms and their outputs.

An *arm* is one interchangeable pipeline configuration under test — "rules
only", "rules+LLM", and so on (ADR-0009 §arms). `ArmConfig` is its identity: a
name, a description, and a free-form `config` mapping (thresholds, model ids,
feature flags). The `config_hash` is a stable digest of that mapping, so two
runs that claim to be the same arm can be proven to have used the same
configuration — an ablation that silently changed a threshold is not an
ablation, it is a confound.

`ArmOutput` is what an arm actually produced on a corpus: the `Candidate`
objects, the evidence store they cite into (by `evidence_id`), and the honest
operational counts ADR-0009 insists on — how many inputs were attempted, how
many the arm *abstained* on, how many it *failed* on, and optional cost/latency
that is `None` when it was never measured. The harness grades `ArmOutput`
against a `GoldSet`; it does not run the arms itself (that is Stream-B
ingestion, integrated later).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kg_contracts.candidates import Candidate
from kg_contracts.evidence import Evidence


class CostLatency(BaseModel):
    """Optional cost/latency measurements — every field may be `None`.

    ADR-0009 requires cost and latency to be part of the honest-null ledger,
    but only *when measured*: an unmeasured latency is `None`, never 0.0, so a
    report can never imply an arm was free or instant when it simply was not
    timed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    latency_seconds: float | None = Field(default=None, ge=0.0)
    cost_usd: float | None = Field(default=None, ge=0.0)
    tokens: int | None = Field(default=None, ge=0)


class ArmConfig(BaseModel):
    """The reproducible identity of one evaluation arm.

    `config` holds whatever distinguishes this arm (model id, thresholds,
    enabled features); `config_hash` is a deterministic digest of it so
    "the same arm" is a checkable claim, not a label.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    arm_id: str = Field(min_length=1)
    description: str | None = None
    config: Mapping[str, object] = Field(default_factory=dict)

    @property
    def config_hash(self) -> str:
        """Stable SHA-256 of `config` (sorted keys), independent of arm_id."""
        encoded = json.dumps(dict(self.config), sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ArmOutput(BaseModel):
    """What one arm produced on a corpus, plus its honest operational counts.

    `candidates` are graded against the gold set. `evidence` is the store the
    candidates' `EvidenceRef`s resolve into, keyed by `evidence_id`; an
    `EvidenceRef` with no entry here is an unresolvable citation, which the
    evidence-validity metric counts against the arm.

    `abstained`/`failed` are honest-null signals: an arm that declines to
    answer (abstain) or errors (fail) is recorded, never quietly treated as a
    zero-yield success. `attempted` overrides the gold set's own input count as
    the rate denominator when the arm knows exactly how many inputs it saw.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    arm: ArmConfig
    candidates: tuple[Candidate, ...] = ()
    evidence: Mapping[str, Evidence] = Field(default_factory=dict)
    attempted: int | None = Field(default=None, ge=0)
    abstained: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    cost: CostLatency | None = None

    @model_validator(mode="after")
    def _check_counts_within_attempted(self) -> ArmOutput:
        """`abstained + failed` cannot exceed `attempted` when it is known.

        Without this bound, `abstention_rate`/`failure_rate` could exceed 1.0 —
        a nonsensical rate that reads like a metric bug rather than the bad
        input it actually is. When `attempted` is `None` (the arm did not report
        an input count) there is no denominator to bound against, so the counts
        pass through and the rates report honest-null instead (ADR-0009).
        """
        if self.attempted is not None and self.abstained + self.failed > self.attempted:
            raise ValueError(
                f"abstained ({self.abstained}) + failed ({self.failed}) exceeds "
                f"attempted ({self.attempted})"
            )
        return self
