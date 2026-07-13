import pytest
from pydantic import ValidationError

from kg_contracts.candidates import CandidateScores
from kg_contracts.policy import AdjudicationRoute, ConfidencePolicy


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
