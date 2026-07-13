"""Score-set-aware `ConfidencePolicy` (spec §5.10).

`ConfidencePolicy` is a shared contract, not a KGCS internal: it routes
adjudication for entity promotion AND the registry's extend-vs-new
decision. It is evaluated over the full `CandidateScores` set and the
candidate's consequence class (`policy_risk`) rather than a single float
(spec §5.2, disposition A2) — the whole point of keeping scores
multi-dimensional is that a policy can weigh them differently instead of
collapsing them into one number first.

Routes are `AUTO | LLM_ASSESS | HUMAN`. The v1 `CONSENSUS` tier
(multi-agent debate) is demoted to an experimental kg_eval arm and is NOT
a route here (disposition A6) — it is a separate evaluation harness, not
something production adjudication can select.

Thresholds are fields on `ConfidencePolicy`, i.e. data, not code:
automating a decision later (loosening a threshold, or dropping the
`require_identity_confidence_for_auto` gate) is a policy config change,
never a code change.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator

from kg_contracts.candidates import CandidateScores


class AdjudicationRoute(StrEnum):
    """Where a candidate's adjudication decision is routed."""

    AUTO = "AUTO"
    LLM_ASSESS = "LLM_ASSESS"
    HUMAN = "HUMAN"


class ConfidencePolicy(BaseModel):
    """Config (not code) mapping a `CandidateScores` set to an `AdjudicationRoute`.

    `route` applies, in order:

    1. `policy_risk > auto_max_policy_risk` never routes AUTO — a
       high-consequence candidate goes to at least `LLM_ASSESS`, and above
       0.5 to `HUMAN` regardless of how confident the other scores are.
    2. AUTO additionally requires `extraction_confidence >=
       auto_min_extraction` AND `source_reliability >=
       auto_min_source_reliability` AND, when
       `require_identity_confidence_for_auto` is set, `identity_confidence
       >= auto_min_identity_confidence`. A **missing** `identity_confidence`
       is not silently treated as good enough — honest-null blocks AUTO
       rather than defaulting to pass.
    3. Otherwise `LLM_ASSESS` if `extraction_confidence >=
       assess_min_extraction`.
    4. Otherwise `HUMAN`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_version: str = "1"
    auto_min_extraction: float = 0.95
    auto_min_source_reliability: float = 0.90
    auto_max_policy_risk: float = 0.20
    assess_min_extraction: float = 0.80
    require_identity_confidence_for_auto: bool = True
    auto_min_identity_confidence: float = 0.95

    @model_validator(mode="after")
    def _check_thresholds_ordered(self) -> "ConfidencePolicy":
        if self.auto_min_extraction < self.assess_min_extraction:
            raise ValueError(
                "auto_min_extraction must be ordered >= assess_min_extraction "
                f"(got auto_min_extraction={self.auto_min_extraction!r}, "
                f"assess_min_extraction={self.assess_min_extraction!r})"
            )
        return self

    def route(self, scores: CandidateScores) -> AdjudicationRoute:
        """Route `scores` to an `AdjudicationRoute` per the ordered rules above."""
        if scores.policy_risk > 0.5:
            return AdjudicationRoute.HUMAN
        if scores.policy_risk > self.auto_max_policy_risk:
            return AdjudicationRoute.LLM_ASSESS

        identity_ok = (not self.require_identity_confidence_for_auto) or (
            scores.identity_confidence is not None
            and scores.identity_confidence >= self.auto_min_identity_confidence
        )
        if (
            scores.extraction_confidence >= self.auto_min_extraction
            and scores.source_reliability >= self.auto_min_source_reliability
            and identity_ok
        ):
            return AdjudicationRoute.AUTO

        if scores.extraction_confidence >= self.assess_min_extraction:
            return AdjudicationRoute.LLM_ASSESS

        return AdjudicationRoute.HUMAN
