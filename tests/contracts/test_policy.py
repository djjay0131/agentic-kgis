import pytest
from pydantic import ValidationError

from kg_contracts.candidates import CandidateScores
from kg_contracts.policy import AdjudicationRoute, ConfidencePolicy, IdentityDisposition


def scores(**kw: float) -> CandidateScores:
    base = dict(extraction_confidence=0.99, source_reliability=0.95,
                identity_confidence=0.99)
    base.update(kw)
    return CandidateScores(**base)  # type: ignore[arg-type]


def test_routes_are_auto_llm_assess_human_only():
    # CONSENSUS is gone: multi-agent debate is an experimental kg_eval arm (A6)
    assert {r.value for r in AdjudicationRoute} == {"AUTO", "LLM_ASSESS", "HUMAN"}


def test_high_everything_routes_auto():
    assert ConfidencePolicy().route(scores()) is AdjudicationRoute.AUTO


def test_exact_import_is_not_auto_without_source_reliability():
    # deterministic sync no longer enters ACTIVE automatically at "confidence 1.0"
    # (spec 5.5 / ADR-0004 as amended): the score set decides, not extraction alone
    s = scores(extraction_confidence=1.0, source_reliability=0.5)
    assert ConfidencePolicy().route(s) is AdjudicationRoute.LLM_ASSESS


def test_missing_identity_confidence_blocks_auto():
    s = CandidateScores(extraction_confidence=0.99, source_reliability=0.99)
    assert ConfidencePolicy().route(s) is AdjudicationRoute.LLM_ASSESS


def test_policy_risk_forces_human_review():
    assert ConfidencePolicy().route(scores(policy_risk=0.9)) \
        is AdjudicationRoute.HUMAN


def test_low_extraction_routes_human():
    s = scores(extraction_confidence=0.3)
    assert ConfidencePolicy().route(s) is AdjudicationRoute.HUMAN


def test_automation_is_config_not_code():
    # the learning-system endgame: loosen thresholds by config, no code change
    p = ConfidencePolicy(auto_min_extraction=0.5, assess_min_extraction=0.2,
                         auto_min_source_reliability=0.4,
                         require_identity_confidence_for_auto=False)
    s = CandidateScores(extraction_confidence=0.6, source_reliability=0.5)
    assert p.route(s) is AdjudicationRoute.AUTO


def test_threshold_ordering_enforced():
    with pytest.raises(ValidationError, match="ordered"):
        ConfidencePolicy(auto_min_extraction=0.5, assess_min_extraction=0.8)


def test_human_min_policy_risk_is_config_driven():
    # same scores, different config, no code change: lowering the HUMAN
    # cutoff turns a formerly-LLM_ASSESS moderate-risk candidate into HUMAN.
    s = scores(policy_risk=0.4)
    assert ConfidencePolicy().route(s) is AdjudicationRoute.LLM_ASSESS
    lowered = ConfidencePolicy(human_min_policy_risk=0.3)
    assert lowered.route(s) is AdjudicationRoute.HUMAN


def test_policy_risk_ordering_enforced():
    with pytest.raises(ValidationError, match="ordered"):
        ConfidencePolicy(auto_max_policy_risk=0.6, human_min_policy_risk=0.5)


@pytest.mark.parametrize(
    "field",
    [
        "auto_min_extraction",
        "auto_min_source_reliability",
        "auto_max_policy_risk",
        "assess_min_extraction",
        "auto_min_identity_confidence",
    ],
)
def test_thresholds_are_bounded_to_unit_interval(field: str):
    # every threshold is a probability/score in [0, 1]: a nonsense value is
    # rejected at construction, not left to silently distort routing (issue #8).
    with pytest.raises(ValidationError):
        ConfidencePolicy(**{field: 1.5})  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        ConfidencePolicy(**{field: -0.1})  # type: ignore[arg-type]


def test_moderate_risk_poor_extraction_routes_human():
    # moderate risk floors at LLM_ASSESS but must not LOWER a genuinely bad
    # extraction below HUMAN: the extraction route (HUMAN) is more conservative.
    s = scores(extraction_confidence=0.3, policy_risk=0.4)
    assert ConfidencePolicy().route(s) is AdjudicationRoute.HUMAN


def test_moderate_risk_good_extraction_routes_llm_assess():
    # moderate risk with strong extraction: the risk floor (LLM_ASSESS) wins,
    # never AUTO, even though extraction alone would have allowed AUTO.
    s = scores(policy_risk=0.4)
    assert ConfidencePolicy().route(s) is AdjudicationRoute.LLM_ASSESS


# --- ADR-0024: the identity disposition is an input to the gate -------------
#
# Before ADR-0024, `route()` applied the existing-identity resolution gate to
# every candidate, and nothing in kg_contracts/kgis/kg_eval ever produces an
# `identity_confidence` — so no candidate any producer in this platform emits
# could ever route AUTO. These tests pin both halves of the fix: the gate now
# distinguishes "no resolution to be confident about" from "resolution
# confidence unknown", and it does so WITHOUT letting a low stated score, a
# weak extraction, or a risky candidate through.


def test_identity_disposition_has_exactly_three_states():
    assert {d.value for d in IdentityDisposition} == {
        "RESOLVED_EXISTING",
        "NEW_IDENTITY",
        "UNRESOLVED",
    }


def test_route_defaults_to_resolved_existing():
    # The disposition `route()` always assumed implicitly. Passing it
    # explicitly must be indistinguishable from omitting it, or the fix
    # would have silently re-routed every existing caller.
    s = CandidateScores(extraction_confidence=0.99, source_reliability=0.99)
    policy = ConfidencePolicy()
    assert policy.route(s) is policy.route(s, IdentityDisposition.RESOLVED_EXISTING)
    good = scores()
    assert policy.route(good) is policy.route(good, IdentityDisposition.RESOLVED_EXISTING)


def test_new_identity_routes_auto_without_an_identity_confidence():
    # THE DEADLOCK FIX. A candidate minting a brand-new identity has no
    # resolution to be confident about, so a missing identity_confidence is
    # not-applicable rather than unknown, and must not block AUTO.
    s = CandidateScores(extraction_confidence=0.99, source_reliability=0.99)
    assert s.identity_confidence is None
    assert (
        ConfidencePolicy().route(s, IdentityDisposition.NEW_IDENTITY)
        is AdjudicationRoute.AUTO
    )


def test_new_identity_with_a_low_stated_identity_confidence_does_not_route_auto():
    # "Not applicable" excuses an ABSENT score, never a LOW one. Without this
    # the fix would be a silent weakening: a resolver reporting 0.10 would be
    # ignored simply because the candidate is minting a new identity.
    s = CandidateScores(
        extraction_confidence=0.99, source_reliability=0.99, identity_confidence=0.10
    )
    assert (
        ConfidencePolicy().route(s, IdentityDisposition.NEW_IDENTITY)
        is AdjudicationRoute.LLM_ASSESS
    )


def test_new_identity_does_not_bypass_the_extraction_gate():
    # The identity dimension is the only one NEW_IDENTITY relaxes.
    s = CandidateScores(extraction_confidence=0.85, source_reliability=0.99)
    assert (
        ConfidencePolicy().route(s, IdentityDisposition.NEW_IDENTITY)
        is AdjudicationRoute.LLM_ASSESS
    )


def test_new_identity_does_not_bypass_the_source_reliability_gate():
    s = CandidateScores(extraction_confidence=0.99, source_reliability=0.50)
    assert (
        ConfidencePolicy().route(s, IdentityDisposition.NEW_IDENTITY)
        is AdjudicationRoute.LLM_ASSESS
    )


def test_new_identity_does_not_bypass_the_policy_risk_floor():
    s = CandidateScores(
        extraction_confidence=0.99, source_reliability=0.99, policy_risk=0.9
    )
    assert (
        ConfidencePolicy().route(s, IdentityDisposition.NEW_IDENTITY)
        is AdjudicationRoute.HUMAN
    )


def test_allow_auto_for_new_identity_is_config_not_code():
    # An adopter that never wants an identity minted without oversight turns
    # the relaxation off by config, and the SAME scores drop back to
    # LLM_ASSESS with no code change (principle 9).
    s = CandidateScores(extraction_confidence=0.99, source_reliability=0.99)
    assert (
        ConfidencePolicy().route(s, IdentityDisposition.NEW_IDENTITY)
        is AdjudicationRoute.AUTO
    )
    strict = ConfidencePolicy(allow_auto_for_new_identity=False)
    assert strict.route(s, IdentityDisposition.NEW_IDENTITY) is AdjudicationRoute.LLM_ASSESS


def test_unresolved_blocks_auto_even_with_a_perfect_identity_confidence():
    # UNRESOLVED means no resolver looked at this candidate. A hand-supplied
    # identity_confidence cannot buy AUTO for a resolution that never
    # happened — and this is exactly where UNRESOLVED and RESOLVED_EXISTING
    # diverge observably, on identical scores.
    s = scores(identity_confidence=0.99)
    policy = ConfidencePolicy()
    assert policy.route(s, IdentityDisposition.RESOLVED_EXISTING) is AdjudicationRoute.AUTO
    assert policy.route(s, IdentityDisposition.UNRESOLVED) is AdjudicationRoute.LLM_ASSESS


def test_disabling_the_gate_still_disables_it_for_every_disposition():
    # require_identity_confidence_for_auto=False remains the master switch:
    # with it clear, no disposition — not even UNRESOLVED — blocks AUTO.
    s = CandidateScores(extraction_confidence=0.99, source_reliability=0.99)
    policy = ConfidencePolicy(require_identity_confidence_for_auto=False)
    for disposition in IdentityDisposition:
        assert policy.route(s, disposition) is AdjudicationRoute.AUTO, disposition
