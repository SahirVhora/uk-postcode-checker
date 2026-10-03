"""Evaluate admissions rules (config/admissions_rules/*.json) against admissions history.

Rules are data: a new policy year is a new JSON file, not a code change.
"""

import json
from functools import lru_cache
from pathlib import Path

from . import REPO_ROOT

DEFAULT_PROFILE = {"in_catchment": False, "feeder": None, "sibling": False, "staff": False,
                   "lac": False, "medical_social": False}


@lru_cache(maxsize=None)
def load_rules(path: str) -> dict:
    p = Path(path)
    if not p.is_absolute():
        p = REPO_ROOT / p
    return json.loads(p.read_text(encoding="utf-8"))


def category_for(rules: dict, profile: dict) -> dict:
    """First oversubscription category whose requirements the applicant meets."""
    prof = {**DEFAULT_PROFILE, **profile}
    for cat in rules["categories"]:
        if all(prof.get(k) == v for k, v in cat["requires"].items()):
            return cat
    raise ValueError(f"No category matched {profile} in {rules['school_name']} rules")


def label_priority(rules: dict, label: str | None) -> tuple[str, int | None]:
    """Map a published 'last child offered' label to ('all_offered', None) or ('priority', n)."""
    text = (label or "").lower()
    for alias in rules["history_label_aliases"]:
        if alias["match"] in text:
            if alias.get("outcome") == "all_offered":
                return "all_offered", None
            return "priority", alias["priority"]
    return "unknown", None


def year_outcome(rules: dict, applicant: dict, distance_miles: float | None, row: dict) -> str:
    """Would this applicant have been offered a place in that year?

    Returns 'all_offered', 'category_cleared' (every applicant in their category got a place),
    'within_distance', 'outside_distance', 'not_reached' (their category got no places) or 'unknown'.
    """
    kind, last_p = label_priority(rules, row.get("last_priority"))
    if kind == "all_offered":
        return "all_offered"
    if kind == "unknown":
        return "unknown"
    p = applicant["priority"]
    if last_p > p:
        return "category_cleared"
    if last_p < p:
        return "not_reached"
    label = (row.get("last_priority") or "").lower()
    if "sibling" in label and "without sibling" not in label and not applicant.get("sibling"):
        return "not_reached"  # places in this category ran out within the sibling sub-group
    last = row.get("last_distance_miles")
    if last is None or distance_miles is None:
        return "unknown"
    return "within_distance" if distance_miles <= last else "outside_distance"


ADMITTED = {"all_offered", "category_cleared", "within_distance"}


def assess(rules: dict, history: list[dict], profile: dict, distance_miles: float | None, years: int = 3) -> dict:
    """Category, per-year outcomes and the historic chance indicator for one applicant profile."""
    cat = category_for(rules, profile)
    applicant = {**DEFAULT_PROFILE, **profile, "priority": cat["priority"]}
    offer_day = sorted((h for h in history if h["entry_point"] == "national_offer_day"),
                       key=lambda h: h["entry_year"], reverse=True)[:years]
    basis = offer_day or sorted(history, key=lambda h: h["entry_year"], reverse=True)[:years]
    outcomes = [{"year": h["entry_year"], "entry_point": h["entry_point"], "last": h["last_priority"],
                 "last_miles": h["last_distance_miles"], "outcome": year_outcome(rules, applicant, distance_miles, h)}
                for h in basis]
    admitted = sum(o["outcome"] in ADMITTED for o in outcomes)
    fully = all(o["outcome"] in ("all_offered", "category_cleared") for o in outcomes)
    if not outcomes:
        indicator = "no history available"
    elif profile.get("in_catchment") and fully and len(outcomes) >= years:
        indicator = "historically safe"
    elif admitted == len(outcomes):
        indicator = "offered in every year shown"
    elif admitted == 0:
        indicator = "not offered in any year shown"
    else:
        indicator = f"offered in {admitted} of {len(outcomes)} years"
    return {"priority": cat["priority"], "category": cat["label"], "outcomes": outcomes,
            "years_admitted": admitted, "years": len(outcomes), "indicator": indicator,
            "historically_safe": indicator == "historically safe"}
