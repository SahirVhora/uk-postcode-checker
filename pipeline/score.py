"""Area score: four sub-scores (0 to 100) and a weighted total. Formula in docs/SCORING.md.

Sub-scores are built from components. Distances, prices, crime rates and
community measures are percentile-ranked within the pool; yes/no facts, IMD
deciles, Ofsted judgements and Attainment 8 use fixed scales. A component with
no data (for example KS4 results not imported, Progress 8 not published) is
dropped and the remaining component weights are re-normalised; it never counts as 0.
"""

import json
import logging
import math

from .profile import ProfileBuilder

log = logging.getLogger("pipeline")
OFSTED_GRADE = {"1": 100.0, "2": 66.7, "3": 33.3, "4": 0.0}
UNGRADED_TEXT = [("outstanding", 100.0), ("good", 66.7), ("requires improvement", 33.3), ("inadequate", 0.0),
                 ("serious weaknesses", 0.0), ("special measures", 0.0)]


def percentile_ranks(values: dict, higher_is_better: bool) -> dict:
    """Map key -> percentile (0 to 100) among non-null values; ties share their average rank."""
    present = sorted((v, k) for k, v in values.items() if v is not None)
    n = len(present)
    out = {k: None for k in values}
    if n == 0:
        return out
    i = 0
    while i < n:
        j = i
        while j + 1 < n and present[j + 1][0] == present[i][0]:
            j += 1
        pct = 50.0 if n == 1 else ((i + j) / 2) / (n - 1) * 100
        for _, k in present[i:j + 1]:
            out[k] = round(pct if higher_is_better else 100 - pct, 2)
        i = j + 1
    return out


def round2(x: float) -> float:
    """Round half up to 2 decimals, exactly like Math.round(x * 100) / 100 in the browser."""
    return math.floor(x * 100 + 0.5) / 100


def weighted_mean(parts: dict, weights: dict) -> float | None:
    """Weighted mean over components that have a value; missing ones are re-weighted away."""
    num = sum(weights[k] * v for k, v in parts.items() if v is not None and weights.get(k))
    den = sum(weights[k] for k, v in parts.items() if v is not None and weights.get(k))
    return round2(num / den) if den else None


def price_with_budget(raw: float | None, budget_value: float | None, budget: float, multiplier: float) -> float | None:
    """Hard penalty: the price sub-score is multiplied down when the family-home price is above budget."""
    if raw is None:
        return None
    if budget_value is not None and budget_value > budget:
        return round2(raw * multiplier)
    return raw


def total_score(subscores: dict, weights: dict) -> float | None:
    """Same formula as areaTotalScore() in index.html and shortlist.html."""
    return weighted_mean(subscores, weights)


def ofsted_points(info: dict | None) -> tuple[float | None, str]:
    """Points from published judgements only. Report cards are never collapsed into one grade."""
    o = (info or {}).get("ofsted") or {}
    q = o.get("legacy_quality_of_education")
    if q in OFSTED_GRADE:
        return OFSTED_GRADE[q], f"quality of education grade {q} ({o.get('legacy_inspection_date')})"
    text = (o.get("ungraded_outcome") or "").lower()
    for word, pts in UNGRADED_TEXT:
        if word in text:
            return pts, f"ungraded inspection: {o.get('ungraded_outcome')} ({o.get('ungraded_date')})"
    if o.get("report_card_date"):
        return None, "report card only: not converted to a single grade"
    return None, "no graded judgement published"


def ks4_points(info: dict | None) -> tuple[float | None, str]:
    perf = (info or {}).get("performance") or {}
    for year in sorted(perf, reverse=True):
        a8 = (perf[year].get("KS4") or {}).get("ATT8SCR", {}).get("value")
        if a8 is not None:
            return round(max(0.0, min(100.0, (a8 - 30) / 40 * 100)), 2), f"Attainment 8 {a8} ({year})"
    return None, "KS4 results not available"


def compute(ctx) -> int:
    conn, cfg = ctx.conn, ctx.scoring
    builder = ProfileBuilder(conn, ctx.area, ctx.borough_lad())
    profiles = {p["pcds"]: builder.build(p["pcds"]) for p in ctx.pool()}
    keys = list(profiles)
    t = {s["key"]: s for s in ctx.area["target_schools"]}
    tga, ald = ("tga", "alderbrook") if {"tga", "alderbrook"} <= set(t) else tuple(list(t)[:2])
    feeder = (ctx.area.get("feeder_schools") or [{}])[0].get("key")

    def get(fn):
        out = {}
        for k in keys:
            try:
                out[k] = fn(profiles[k])
            except (KeyError, TypeError):
                out[k] = None
        return out

    # Raw inputs
    raw = {
        "tga_gate": get(lambda p: p["schools"][tga]["gate_miles"]),
        "ald_gate": get(lambda p: p["schools"][ald]["gate_miles"]),
        "feeder": get(lambda p: p["feeders"][feeder]["miles"]),
        "family_rate": get(lambda p: p["safety"]["lsoa"]["family_rate_per_1000"]),
        "asian_pct": get(lambda p: p["community"]["oa"]["TS021:asian"]["pct"]),
        "muslim_pct": get(lambda p: p["community"]["oa"]["TS030:muslim"]["pct"]),
        "mosque": get(lambda p: p["community"]["nearest"]["mosque"]["miles"]),
        "halal": get(lambda p: p["community"]["nearest"]["halal"]["miles"]),
    }

    def price_inputs(p):
        block = p["prices"]["levels"].get(p["prices"]["level_used"], {}).get("ALL") or {}
        # Proxy when EPC is missing: median house price (D+S+T), finest level with enough sales.
        house = next((p["prices"]["levels"].get(lv, {}).get("H") for lv in ("postcode", "sector", "outcode")
                      if (p["prices"]["levels"].get(lv, {}).get("H") or {}).get("sales_recent", 0) >= 3), None) or {}
        return block.get("median_gbp_per_sqm"), block.get("median_4bed_equiv"), house.get("median_price_recent")

    prices = {k: price_inputs(profiles[k]) for k in keys}
    epc_available = any(v[0] is not None for v in prices.values())
    raw["gbp_sqm"] = {k: v[0] for k, v in prices.items()}
    raw["four_bed"] = {k: v[1] for k, v in prices.items()}
    raw["median_price"] = {k: v[2] for k, v in prices.items()}

    pct = {
        "tga_gate": percentile_ranks(raw["tga_gate"], False),
        "ald_gate": percentile_ranks(raw["ald_gate"], False),
        "feeder": percentile_ranks(raw["feeder"], False),
        "family_rate": percentile_ranks(raw["family_rate"], False),
        "asian_pct": percentile_ranks(raw["asian_pct"], True),
        "muslim_pct": percentile_ranks(raw["muslim_pct"], True),
        "mosque": percentile_ranks(raw["mosque"], False),
        "halal": percentile_ranks(raw["halal"], False),
        "gbp_sqm": percentile_ranks(raw["gbp_sqm"], False),
        "four_bed": percentile_ranks(raw["four_bed"], False),
        "median_price": percentile_ranks(raw["median_price"], False),
    }

    sc = cfg["school"]
    pw, sw, cw = cfg["price"]["components"], cfg["safety"]["components"], cfg["community"]["components"]
    weights = cfg["weights"]
    rows = []
    for k in keys:
        p = profiles[k]
        st, sa = p["schools"][tga], p["schools"][ald]
        relevant = [x for x in (st, sa) if x["in_catchment"]] or sorted(
            (st, sa), key=lambda x: x["gate_miles"] if x["gate_miles"] is not None else 1e9)[:1]
        of = [ofsted_points(builder.school_info[x["urn"]]) for x in relevant]
        ks = [ks4_points(builder.school_info[x["urn"]]) for x in relevant]
        safety_years = [100 * x["default"]["years_admitted"] / x["default"]["years"] for x in (st, sa) if x["default"]["years"]]
        school_parts = {
            "in_tga_catchment": 100.0 if st["in_catchment"] else 0.0,
            "in_alderbrook_catchment": 100.0 if sa["in_catchment"] else 0.0,
            "tga_gate_distance": pct["tga_gate"][k],
            "alderbrook_gate_distance": pct["ald_gate"][k],
            "st_james_distance": pct["feeder"][k],
            "admission_safety": round(max(safety_years), 2) if safety_years else None,
            "ofsted": max((v for v, _ in of if v is not None), default=None),
            "ks4_attainment": max((v for v, _ in ks if v is not None), default=None),
        }
        school = weighted_mean(school_parts, sc["components"])
        capped = False
        if school is not None and not p["in_target_catchment"] and school > sc["not_in_catchment_cap"]:
            school, capped = float(sc["not_in_catchment_cap"]), True

        if epc_available:
            price_parts = {"gbp_per_sqm": pct["gbp_sqm"][k], "four_bed_median": pct["four_bed"][k]}
            price_weights = pw
            budget_value = raw["four_bed"][k]
            price_basis = "GBP per sqm and 4-bed-equivalent median (EPC matched)"
        else:
            price_parts = {"median_price_proxy": pct["median_price"][k]}
            price_weights = {"median_price_proxy": 100}
            budget_value = raw["median_price"][k]
            price_basis = "PROXY: median house price (detached, semi, terraced), finest level with 3+ sales; EPC floor areas not loaded"
        price_raw = weighted_mean(price_parts, price_weights)
        price = price_with_budget(price_raw, budget_value, cfg["budget_gbp"], cfg["price"]["over_budget_multiplier"])

        imd = p["safety"]["imd"] or {}
        safety_parts = {
            "family_crime_rate": pct["family_rate"][k],
            "imd_crime_decile": round((imd["crime_decile"] - 1) / 9 * 100, 2) if imd.get("crime_decile") else None,
            "imd_decile": round((imd["imd_decile"] - 1) / 9 * 100, 2) if imd.get("imd_decile") else None,
        }
        safety = weighted_mean(safety_parts, sw)
        community_parts = {"asian_pct": pct["asian_pct"][k], "muslim_pct": pct["muslim_pct"][k],
                           "nearest_mosque": pct["mosque"][k], "nearest_halal": pct["halal"][k]}
        community = weighted_mean(community_parts, cw)
        subs = {"school": school, "price": price, "safety": safety, "community": community}
        detail = {
            "school": {"parts": school_parts, "capped_not_in_catchment": capped,
                       "ofsted_basis": [b for _, b in of], "ks4_basis": [b for _, b in ks]},
            "price": {"parts": price_parts, "raw_before_budget": price_raw, "budget_value": budget_value,
                      "basis": price_basis, "level_used": p["prices"]["level_used"]},
            "safety": {"parts": safety_parts}, "community": {"parts": community_parts},
        }
        rows.append((k, school, price, safety, community, total_score(subs, weights), json.dumps(detail)))
    conn.execute("DELETE FROM scores")
    conn.executemany("INSERT INTO scores (pcds, school, price, safety, community, total, detail_json) VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    return len(rows)
