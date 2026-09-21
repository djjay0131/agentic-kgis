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

`route()` also takes an `IdentityDisposition` (ADR-0024). Resolution
confidence is confidence in linking a candidate to an **existing**
identity; a candidate that mints a brand-new identity has no resolution to
be confident about, so gating it on a resolution score is a category
error. Before ADR-0024 `route()` took only a `CandidateScores` and
therefore applied the existing-identity gate to every candidate — and
because nothing in KGIS, KGCS, or kg_eval ever produces an
`identity_confidence` (KGIS structurally cannot: it holds no graph read
surface, so it cannot know whether an entity already exists), the gate
could never be satisfied and no candidate could ever route `AUTO`.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kg_contracts.candidates import CandidateScores


class AdjudicationRoute(StrEnum):
    """Where a candidate's adjudication decision is routed."""

    AUTO = "AUTO"
    LLM_ASSESS = "LLM_ASSESS"
    HUMAN = "HUMAN"


class IdentityDisposition(StrEnum):
    """What resolution concluded about *which* identity a candidate belongs to.

    This is the missing input to the adjudication gate (ADR-0024).
    `identity_confidence` answers "is this the entity we think it is?" —
    a question that only exists once there is an existing entity to be
    wrong about. Three states, because "resolution has not decided" is
    genuinely different from both of the decisions it could reach:

    - `RESOLVED_EXISTING` — resolution linked this candidate to an existing
      identity. `identity_confidence` is the confidence in *that link*, and
      `AUTO` requires it (honest-null: a missing score blocks). This is the
      default, because it is the assumption `route()` always made
      implicitly; naming it changes no existing caller's routing.
    - `NEW_IDENTITY` — resolution ran and found no existing identity to link
      to, so a new one is minted. There is no link to be confident about, so
      a *missing* `identity_confidence` is not-applicable rather than
      unknown and does not block `AUTO` (subject to
      `ConfidencePolicy.allow_auto_for_new_identity`). A *stated*
      `identity_confidence` is still enforced — the not-applicable reading
      excuses an absent score, never a low one.
    - `UNRESOLVED` — resolution has not run, or ran and abstained. Nothing is
      known about which identity this is, so `AUTO` is blocked outright
      while `require_identity_confidence_for_auto` is set — a hand-supplied
      `identity_confidence` cannot buy `AUTO` for a candidate no resolver
      ever looked at.

    `ResolutionDecision.identity_disposition()` (`kg_contracts.curation`)
    maps a resolution outcome onto these three values, so a caller never
    has to derive the disposition by hand.
    """

    RESOLVED_EXISTING = "RESOLVED_EXISTING"
    NEW_IDENTITY = "NEW_IDENTITY"
    UNRESOLVED = "UNRESOLVED"


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
         AND `source_reliability >= auto_min_source_reliability` AND the
         *identity gate* (below) passes.
      2. else `LLM_ASSESS` if `extraction_confidence >= assess_min_extraction`.
      3. else `HUMAN`.

    The identity gate reads `identity_disposition` (ADR-0024). With
    `require_identity_confidence_for_auto` set:

    - `RESOLVED_EXISTING` (the default) — requires `identity_confidence >=
      auto_min_identity_confidence`. A **missing** `identity_confidence` is
      not silently treated as good enough: honest-null blocks `AUTO`.
    - `NEW_IDENTITY` — a new identity has no resolution to be confident
      about, so an absent `identity_confidence` does not block; `AUTO` is
      permitted iff `allow_auto_for_new_identity`, and a *stated*
      `identity_confidence` is still held to
      `auto_min_identity_confidence`.
    - `UNRESOLVED` — blocked outright: nothing resolved this candidate, so
      there is no identity claim to act on at all.

    Clearing `require_identity_confidence_for_auto` disables the whole gate,
    exactly as before.

    Taking the more conservative of the two means moderate risk never
    *lowers* the route below what extraction alone would give: a
    moderate-risk candidate with good extraction routes `LLM_ASSESS` (the
    risk floor), but a moderate-risk candidate with extraction below
    `assess_min_extraction` still escalates to `HUMAN` (the extraction
    route wins). Moderate risk sets a floor, it does not cap escalation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Every threshold is a probability/score in [0, 1]. The per-field ge/le
    # bounds are a fail-closed NARROWING of the frozen contract (issue #8;
    # ADR-0021): they reject a nonsense threshold (e.g. 1.5) at
    # construction rather than letting it silently distort routing. Since
    # CandidateScores fields are already bounded [0, 1], an out-of-range
    # threshold is meaningless. The ordering validator and routing are unchanged.
    policy_version: str = "1"
    auto_min_extraction: float = Field(default=0.95, ge=0.0, le=1.0)
    auto_min_source_reliability: float = Field(default=0.90, ge=0.0, le=1.0)
    auto_max_policy_risk: float = Field(default=0.20, ge=0.0, le=1.0)
    human_min_policy_risk: float = Field(default=0.5, ge=0.0, le=1.0)
    assess_min_extraction: float = Field(default=0.80, ge=0.0, le=1.0)
    require_identity_confidence_for_auto: bool = True
    auto_min_identity_confidence: float = Field(default=0.95, ge=0.0, le=1.0)
    # ADR-0024. Data, not code (principle 9): an adopter that never wants an
    # identity minted without oversight sets this False and every
    # `NEW_IDENTITY` candidate floors at `LLM_ASSESS`, with no code change.
    # It defaults True because blocking here is what deadlocked adjudication:
    # a brand-new identity can never acquire a resolution confidence, so a
    # policy that demands one demands the impossible.
    allow_auto_for_new_identity: bool = True

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

    def _identity_confidence_meets_threshold(self, scores: CandidateScores) -> bool:
        """Whether a *stated* `identity_confidence` clears the AUTO threshold.

        `None` fails here: this helper answers "is the stated score good
        enough", and an absent score states nothing. Whether absence blocks
        is `_identity_gate_ok`'s decision, not this one's.
        """
        return (
            scores.identity_confidence is not None
            and scores.identity_confidence >= self.auto_min_identity_confidence
        )

    def _identity_gate_ok(
        self, scores: CandidateScores, identity_disposition: IdentityDisposition
    ) -> bool:
        """Whether the identity dimension permits `AUTO` (ADR-0024)."""
        if not self.require_identity_confidence_for_auto:
            return True
        if identity_disposition is IdentityDisposition.UNRESOLVED:
            return False
        if identity_disposition is IdentityDisposition.NEW_IDENTITY:
            if not self.allow_auto_for_new_identity:
                return False
            # Absent: not-applicable, so it does not block. Present: still
            # enforced — "no resolution to be confident about" excuses a
            # missing score, never a low one.
            if scores.identity_confidence is None:
                return True
            return self._identity_confidence_meets_threshold(scores)
        return self._identity_confidence_meets_threshold(scores)

    def _extraction_route(
        self, scores: CandidateScores, identity_disposition: IdentityDisposition
    ) -> AdjudicationRoute:
        """The route the confidence scores alone would give, ignoring risk."""
        if (
            scores.extraction_confidence >= self.auto_min_extraction
            and scores.source_reliability >= self.auto_min_source_reliability
            and self._identity_gate_ok(scores, identity_disposition)
        ):
            return AdjudicationRoute.AUTO
        if scores.extraction_confidence >= self.assess_min_extraction:
            return AdjudicationRoute.LLM_ASSESS
        return AdjudicationRoute.HUMAN

    def route(
        self,
        scores: CandidateScores,
        identity_disposition: IdentityDisposition = IdentityDisposition.RESOLVED_EXISTING,
    ) -> AdjudicationRoute:
        """Route `scores` to the more conservative of risk floor and extraction route.

        `identity_disposition` names what resolution concluded about this
        candidate's identity (ADR-0024). It defaults to
        `RESOLVED_EXISTING` — the assumption this method always made
        implicitly — so an existing caller's routing is unchanged.
        """
        return _more_conservative(
            self._risk_floor(scores),
            self._extraction_route(scores, identity_disposition),
        )
