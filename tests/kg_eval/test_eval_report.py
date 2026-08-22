"""Reports render deterministically to JSON and Markdown and never fake a zero."""

import json
from pathlib import Path

from helpers import lossy_arm, perfect_arm

from kg_eval import (
    BootstrapConfig,
    GoldSet,
    compare_arms,
    evaluate_arms,
    render_json,
    render_markdown,
)

FIXTURE = Path(__file__).parent / "fixtures" / "baseball_gold.json"
BOOT = BootstrapConfig(seed=11, n_resamples=300, min_items=8)


def gold() -> GoldSet:
    return GoldSet.from_json_file(FIXTURE)


def build_result():
    g = gold()
    ablation = compare_arms(lossy_arm(), perfect_arm(), g, metric="entity.recall", boot=BOOT)
    return evaluate_arms(
        (lossy_arm(), perfect_arm()),
        g,
        boot=BOOT,
        ablations=(ablation,),
    )


def test_json_is_deterministic_and_valid() -> None:
    a = render_json(build_result())
    b = render_json(build_result())
    assert a == b
    parsed = json.loads(a)
    assert parsed["gold_set_id"] == "baseball-v1"
    assert len(parsed["arms"]) == 2


def test_json_keys_are_sorted_for_diffability() -> None:
    text = render_json(build_result())
    parsed = json.loads(text)
    # every object in the tree must serialize with sorted keys
    def _keys_sorted(obj: object) -> bool:
        if isinstance(obj, dict):
            keys = list(obj.keys())
            return keys == sorted(keys) and all(_keys_sorted(v) for v in obj.values())
        if isinstance(obj, list):
            return all(_keys_sorted(v) for v in obj)
        return True

    assert _keys_sorted(parsed)
    # top-level ordering is visible directly
    top = [line.strip().split(":")[0] for line in text.splitlines() if line.startswith("  \"")]
    assert top == sorted(top)


def test_markdown_is_deterministic() -> None:
    a = render_markdown(build_result())
    b = render_markdown(build_result())
    assert a == b


def test_markdown_reports_honest_null_not_zero() -> None:
    # an arm with no candidates of a category renders "insufficient", not 0.000
    empty = lossy_arm().model_copy(update={"candidates": ()})
    result = evaluate_arms((empty,), gold())
    md = render_markdown(result)
    assert "insufficient" in md
    assert "Ontology violations: insufficient" in md  # None -> honest null


def test_markdown_contains_arms_and_ablation_sections() -> None:
    md = render_markdown(build_result())
    assert "# kg_eval report: baseball-v1" in md
    assert "### Arm: rules-only" in md
    assert "### Arm: rules+llm" in md
    assert "## Ablations" in md
    assert "Verdict:" in md


def test_json_and_markdown_come_from_same_model() -> None:
    result = build_result()
    # both renderers agree on the gold-set hash they were built from
    assert result.gold_set_hash in render_markdown(result)
    assert result.gold_set_hash in render_json(result)
