import pytest

from pipeline.admissions_model import assess, category_for, label_priority, load_rules, year_outcome
from pipeline.sources import admissions

TGA = "config/admissions_rules/tga-solihull-2027-28.json"
ALD = "config/admissions_rules/alderbrook-2027-28.json"


def history(*rows, entry_point="national_offer_day"):
    return [{"entry_year": y, "entry_point": entry_point, "last_priority": p, "last_distance_miles": d} for y, p, d in rows]


def test_tga_categories_follow_policy():
    rules = load_rules(TGA)
    assert category_for(rules, {})["priority"] == 7
    assert category_for(rules, {"in_catchment": True})["priority"] == 6
    assert category_for(rules, {"feeder": "st_james"})["priority"] == 3
    assert category_for(rules, {"feeder": "hockley_heath"})["priority"] == 7          # needs catchment too
    assert category_for(rules, {"feeder": "hockley_heath", "in_catchment": True})["priority"] == 4


def test_alderbrook_categories_follow_policy():
    rules = load_rules(ALD)
    assert category_for(rules, {"in_catchment": True})["priority"] == 4
    assert category_for(rules, {"sibling": True})["priority"] == 5
    assert category_for(rules, {})["priority"] == 6


def test_history_labels_match_by_text_in_order():
    ald, tga = load_rules(ALD), load_rules(TGA)
    assert label_priority(ald, "Sibling (Out of Catchment)") == ("priority", 5)
    assert label_priority(ald, "Distance") == ("priority", 6)
    assert label_priority(tga, "Catchment (without sibling)") == ("priority", 6)
    assert label_priority(tga, "All on time applicants offered") == ("all_offered", None)
    assert label_priority(tga, "Children of Staff") == ("unknown", None)


def test_year_outcomes():
    tga = load_rules(TGA)
    out_of_catchment = {"priority": 7, "sibling": False}
    in_catchment = {"priority": 6, "sibling": False}
    row = {"last_priority": "Distance", "last_distance_miles": 0.8}
    assert year_outcome(tga, out_of_catchment, 0.79, row) == "within_distance"
    assert year_outcome(tga, out_of_catchment, 0.81, row) == "outside_distance"
    assert year_outcome(tga, in_catchment, 3.0, row) == "category_cleared"
    row24 = {"last_priority": "Catchment (without sibling)", "last_distance_miles": 2.42}
    assert year_outcome(tga, in_catchment, 2.0, row24) == "within_distance"
    assert year_outcome(tga, in_catchment, 2.5, row24) == "outside_distance"
    assert year_outcome(tga, out_of_catchment, 0.1, row24) == "not_reached"
    sib = {"last_priority": "Catchment (with sibling)", "last_distance_miles": 1.0}
    assert year_outcome(tga, in_catchment, 0.5, sib) == "not_reached"                  # siblings took the last places


def test_historically_safe_requires_catchment_fully_admitted_every_year():
    ald = load_rules(ALD)
    h = history((2026, "Distance", 1.59), (2025, "Sibling (Out of Catchment)", 3.75), (2024, "Distance", 0.54))
    a = assess(ald, h, {"in_catchment": True}, 0.75)
    assert a["indicator"] == "historically safe" and a["historically_safe"]
    out = assess(ald, h, {"in_catchment": False}, 0.75)
    assert out["priority"] == 6 and out["years_admitted"] == 1                        # only 2026 (1.59 mi)
    tga = load_rules(TGA)
    h2 = history((2026, "Distance", 0.8), (2025, "Distance", 0.14), (2024, "Catchment (without sibling)", 2.42))
    a2 = assess(tga, h2, {"in_catchment": True}, 2.0)
    assert a2["indicator"] == "offered in every year shown" and not a2["historically_safe"]   # 2024 was by distance


def test_offer_day_history_preferred_over_catchment_map():
    ald = load_rules(ALD)
    h = history((2025, "Priority 6 Distance", 0.405), entry_point="catchment_map") + history((2025, "Distance", 0.2))
    a = assess(ald, h, {}, 0.3)
    assert [o["entry_point"] for o in a["outcomes"]] == ["national_offer_day"]
    assert a["outcomes"][0]["outcome"] == "outside_distance"


def test_offer_table_rows(fixture_json):
    fx = fixture_json("admissions_rows.json")
    rows = admissions.parse_offer_rows(fx["text"], fx["tables"])
    tga = {(r["entry_year"]): r for r in rows if r["school"] == "Tudor Grange Academy Solihull"}
    assert tga[2026]["last_distance_miles"] == 0.8 and tga[2024]["last_priority"] == "Catchment (without sibling)"
    hoe = [r for r in rows if r["school"].startswith("Heart")]
    assert hoe[0]["last_distance_miles"] is None and "All on time" in hoe[0]["last_priority"]
    with pytest.raises(Exception):
        admissions.parse_offer_rows("no headings", fx["tables"])


def test_catchment_map_panel(fixture_json):
    school, rows = admissions.parse_map_panel(fixture_json("admissions_rows.json")["map_text"])
    assert school == "Alderbrook"
    assert [(r["entry_year"], r["last_priority"], r["last_distance_miles"]) for r in rows] == [
        (2025, "Priority 6 Distance", 0.405), (2024, "Priority 5 Distance", 0.546), (2023, "Criteria 3 Sibling", 1.745)]


def test_school_name_matching_refuses_ambiguity():
    schools = [(136310, "Tudor Grange Academy, Solihull"), (146379, "Tudor Grange Academy Kingshurst"),
               (140731, "Tudor Grange Academy Redditch"), (136994, "Alderbrook School")]
    assert admissions.match_urn("Alderbrook", schools) == 136994
    assert admissions.match_urn("Tudor Grange Academy Solihull", schools) == 136310
    assert admissions.match_urn("Tudor Grange Academy", schools) is None
