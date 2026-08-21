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

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kg_contracts.candidates import CandidateScores


class AdjudicationRoute(StrEnum):
    """Where a candidate's adjudication decision is routed."""

    AUTO = "AUTO"
    LLM_ASSESS = "LLM_ASSESS"
    HUMAN = "HUMAN"


# Route severity for choosing the more conservative of two candidate routes.
# HUMAN is the most conservative (most oversight), AUTO the least.
_ROUTE_SEVERITY: dict[AdjudicationRoute, int] = {
    AdjudicationRoute.AUTO: 0,
    AdjudicationRoute.LLM_ASSESS: 1,
    AdjudicationRoute.HUMAN: 2,
}


def _more_conservative(a: AdjudicationRoute, b: AdjudicationRoute) -> AdjudicationRoute:
    """Return whichever of `a`/`b` demands more oversight (HUMAN > LLM_ASSESS > AUTO)."""
    return a if _ROUTE_SEVERITY[a] >= _ROUTE_SEVERITY[b] else b


class ConfidencePolicy(BaseModel):
    """Config (not code) mapping a `CandidateScores` set to an `AdjudicationRoute`.

    Every threshold is a field on this model — nothing about the routing
    decision is a hardcoded literal, so automating (or tightening) a
    decision later is a policy config change, never a code change.

    `route` computes two candidate routes and returns **the more
    conservative of the two** (HUMAN > LLM_ASSESS > AUTO):

    - the *policy-risk floor*, driven by `policy_risk`:
      1. `policy_risk > human_min_policy_risk` → floor is `HUMAN`.
      2. `policy_risk > auto_max_policy_risk` (moderate risk) → floor is
         `LLM_ASSESS`: moderate-risk candidates can never route `AUTO`.
      3. otherwise → floor is `AUTO` (risk imposes no restriction).
    - the *extraction-based route*, driven by the confidence scores:
      1. `AUTO` requires `extraction_confidence >= auto_min_extraction`
         AND `source_reliability >= auto_min_source_reliability` AND, when
         `require_identity_confidence_for_auto` is set, `identity_confidence
         >= auto_min_identity_confidence`. A **missing** `identity_confidence`
         is not silently treated as good enough — honest-null blocks `AUTO`
         rather than defaulting to pass.
      2. else `LLM_ASSESS` if `extraction_confidence >= assess_min_extraction`.
      3. else `HUMAN`.

    Taking the more conservative of the two means moderate risk never
    *lowers* the route below what extraction alone would give: a
    moderate-risk candidate with good extraction routes `LLM_ASSESS` (the
    risk floor), but a moderate-risk candidate with extraction below
    `assess_min_extraction` still escalates to `HUMAN` (the extraction
    route wins). Moderate risk sets a floor, it does not cap escalation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Every threshold is a probability/score in [0, 1]. The ordering
    # validator and conservative routing already fail closed, but per-field
    # ge/le bounds reject a nonsense threshold (e.g. 1.5) at construction
    # rather than letting it silently distort routing (issue #8).
    policy_version: str = "1"
    auto_min_extraction: float = Field(default=0.95, ge=0.0, le=1.0)
    auto_min_source_reliability: float = Field(default=0.90, ge=0.0, le=1.0)
    auto_max_policy_risk: float = Field(default=0.20, ge=0.0, le=1.0)
    human_min_policy_risk: float = Field(default=0.5, ge=0.0, le=1.0)
    assess_min_extraction: float = Field(default=0.80, ge=0.0, le=1.0)
    require_identity_confidence_for_auto: bool = True
    auto_min_identity_confidence: float = Field(default=0.95, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_thresholds_ordered(self) -> "ConfidencePolicy":
        if self.auto_min_extraction < self.assess_min_extraction:
            raise ValueError(
                "auto_min_extraction must be ordered >= assess_min_extraction "
                f"(got auto_min_extraction={self.auto_min_extraction!r}, "
                f"assess_min_extraction={self.assess_min_extraction!r})"
            )
        if self.human_min_policy_risk < self.auto_max_policy_risk:
            raise ValueError(
                "human_min_policy_risk must be ordered >= auto_max_policy_risk "
                f"(got human_min_policy_risk={self.human_min_policy_risk!r}, "
                f"auto_max_policy_risk={self.auto_max_policy_risk!r})"
            )
        return self

    def _risk_floor(self, scores: CandidateScores) -> AdjudicationRoute:
        """The least-conservative route `policy_risk` alone permits."""
        if scores.policy_risk > self.human_min_policy_risk:
            return AdjudicationRoute.HUMAN
        if scores.policy_risk > self.auto_max_policy_risk:
            return AdjudicationRoute.LLM_ASSESS
        return AdjudicationRoute.AUTO

    def _extraction_route(self, scores: CandidateScores) -> AdjudicationRoute:
        """The route the confidence scores alone would give, ignoring risk."""
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

    def route(self, scores: CandidateScores) -> AdjudicationRoute:
        """Route `scores` to the more conservative of risk floor and extraction route."""
        return _more_conservative(
            self._risk_floor(scores), self._extraction_route(scores)
        )
