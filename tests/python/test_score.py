import pytest

from pipeline.score import (ks4_points, ofsted_points, percentile_ranks, price_with_budget, total_score,
                            weighted_mean)


def test_percentile_ranks_direction_and_ties():
    pct = percentile_ranks({"a": 1.0, "b": 2.0, "c": 2.0, "d": 3.0, "e": None}, higher_is_better=True)
    assert pct["a"] == 0 and pct["d"] == 100
    assert pct["b"] == pct["c"] == 50
    assert pct["e"] is None
    low = percentile_ranks({"near": 0.2, "far": 2.0}, higher_is_better=False)
    assert low["near"] == 100 and low["far"] == 0
    assert percentile_ranks({"only": 5.0}, True)["only"] == 50


def test_weighted_mean_reweights_missing_components():
    assert weighted_mean({"a": 100, "b": 0}, {"a": 1, "b": 1}) == 50
    assert weighted_mean({"a": 100, "b": None}, {"a": 1, "b": 1}) == 100      # missing is dropped, not zero
    assert weighted_mean({"a": None}, {"a": 1}) is None


def test_score_parity_cases(fixture_json):
    fx = fixture_json("score_parity.json")
    for case in fx["cases"]:
        assert total_score(case["subs"], case["weights"]) == case["expected"]
    for case in fx["budget_cases"]:
        assert price_with_budget(case["raw"], case["budget_value"], case["budget"], case["multiplier"]) == case["expected"]


def test_weight_change_moves_total():
    subs = {"school": 90, "price": 10, "safety": 50, "community": 50}
    school_heavy = total_score(subs, {"school": 80, "price": 10, "safety": 5, "community": 5})
    price_heavy = total_score(subs, {"school": 10, "price": 80, "safety": 5, "community": 5})
    assert school_heavy > 75 > 25 > price_heavy


def test_budget_penalty_is_hard():
    assert price_with_budget(90, 560000, 550000, 0.25) == 22.5
    assert price_with_budget(90, 550000, 550000, 0.25) == 90


def test_ks4_progress8_not_published_does_not_zero_the_score():
    info = {"performance": {"2024-2025": {"KS4": {"ATT8SCR": {"value": 58.7, "raw": "58.7"}, "P8MEA": {"value": None, "raw": "NA"}}}}}
    pts, basis = ks4_points(info)
    assert pts == pytest.approx(71.75) and "58.7" in basis
    assert ks4_points({"performance": {}}) == (None, "KS4 results not available")


def test_ofsted_points_never_collapse_report_cards():
    assert ofsted_points({"ofsted": {"legacy_quality_of_education": "1", "legacy_inspection_date": "2025-04-29"}})[0] == 100
    assert ofsted_points({"ofsted": {"ungraded_outcome": "School remains Good"}})[0] == 66.7
    pts, basis = ofsted_points({"ofsted": {"report_card_date": "2026-01-10", "rc_achievement": "Strong standard"}})
    assert pts is None and "report card" in basis
    assert ofsted_points(None) == (None, "no graded judgement published")
