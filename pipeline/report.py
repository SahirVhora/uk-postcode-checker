"""Print a one-page text profile for a postcode from the local database.

    python -m pipeline.report "B90 3DF"
    python -m pipeline.report B90 3DF
"""

import json
import sys

from .context import Context
from .profile import ProfileBuilder

TYPES = {"D": "Detached", "S": "Semi", "T": "Terraced", "F": "Flat", "O": "Other", "H": "All houses", "ALL": "All types"}
OUTCOME = {"all_offered": "all on-time applicants offered", "category_cleared": "category fully admitted",
           "within_distance": "within last distance offered", "outside_distance": "beyond last distance offered",
           "not_reached": "category not reached", "unknown": "cannot tell"}


def gbp(v) -> str:
    return "n/a" if v is None else f"GBP {v:,.0f}"


def num(v, nd=1, unit="") -> str:
    return "n/a" if v is None else f"{v:.{nd}f}{unit}"


def normalise_postcode(raw: str) -> str:
    s = raw.replace(" ", "").upper()
    return f"{s[:-3]} {s[-3:]}"


def bar(v) -> str:
    if v is None:
        return "[" + " " * 20 + "]  n/a"
    n = int(round(v / 5))
    return "[" + "#" * n + "." * (20 - n) + f"] {v:5.1f}"


def render(ctx, pcds: str) -> str:
    conn = ctx.conn
    builder = ProfileBuilder(conn, ctx.area, ctx.borough_lad())
    p = builder.build(pcds)
    if not p:
        return f"{pcds} is not in the local database (configured outcodes: {', '.join(ctx.area['outcodes'])})."
    runs = {r["source"]: r for r in conn.execute(
        "SELECT * FROM source_runs WHERE id IN (SELECT MAX(id) FROM source_runs GROUP BY source)")}
    asof = lambda s: (runs[s]["fetched_at"] or "")[:10] if runs.get(s) and runs[s]["fetched_at"] and runs[s]["row_count"] else "not loaded"
    out = []
    w = out.append
    w("=" * 78)
    w(f"AREA PROFILE  {pcds}   {p['ward_name'] or ''}, {p['lad_name'] or ''}")
    w(f"Centroid {p['lat']:.5f}, {p['lng']:.5f}   LSOA {p['lsoa21']}   OA {p['oa21']}   ONSPD {p['onspd_release']}")
    w("=" * 78)

    w(f"\nCATCHMENTS (Solihull Council online maps, fetched {asof('catchments')})")
    for key, s in p["schools"].items():
        w(f"  {s['name']:<40} {'IN CATCHMENT' if s['in_catchment'] else 'not in catchment'}")
    w(f"  Other secondary: {', '.join(n for n in p['catchments']['secondary'] if n not in [s['name'] for s in p['schools'].values()]) or 'none'}")
    w(f"  Primary catchments: {', '.join(p['catchments']['primary']) or 'none'}")
    w(f"  In target catchment: {'YES' if p['in_target_catchment'] else 'NO'}")

    w("\nSECONDARY ADMISSIONS (straight line, postcode centre to main pedestrian gate)")
    w("  Postcode-centroid estimate, actual LLPG distance may differ by up to ~0.1 mi.")
    for key, s in p["schools"].items():
        gate = "verified gate" if s["gate_verified"] else "UNVERIFIED gate point"
        w(f"  {s['name']}  {num(s['gate_miles'], 2, ' mi')} ({gate}), {s['policy_year']} policy, PAN {s['pan']}")
        for label, a in (("No sibling, not a feeder pupil", s["default"]), ("Tudor Grange Primary St James pupil", s["st_james"])):
            w(f"    {label}: priority {a['priority']} ({a['category']})")
            w(f"      -> {a['indicator']}")
            for o in a["outcomes"]:
                src = "offer day" if o["entry_point"] == "national_offer_day" else "catchment map"
                w(f"         {o['year']} {src}: last offer '{o['last']}' {num(o['last_miles'], 2, ' mi')}: {OUTCOME[o['outcome']]}")
        maps = [h for h in s["history"] if h["entry_point"] == "catchment_map"]
        if maps:
            w("    Catchment map panel (point in cycle not stated): " +
              "; ".join(f"{h['entry_year']} {h['last_priority']} {num(h['last_distance_miles'], 3, ' mi')}" for h in maps))
    for f in p["feeders"].values():
        w(f"  {f['name']}: {num(f['miles'], 2, ' mi')} ({'verified' if f['gate_verified'] else 'UNVERIFIED'} gate point)")

    w(f"\nSOLD PRICES (HM Land Registry category A, fetched {asof('ppd')}; EPC {asof('epc')})")
    pr = p["prices"]
    w(f"  Level used for scoring: {pr['level_used']}")
    for level in ("postcode", "sector", "outcode"):
        rows = pr["levels"].get(level, {})
        allm = rows.get("ALL")
        if not allm:
            continue
        w(f"  {level:<9} last 24m: {allm['sales_recent']:>4} sales, median {gbp(allm['median_price_recent'])}, "
          f"GBP/sqm {num(allm['median_gbp_per_sqm'], 0)}, 4-bed-equiv median {gbp(allm['median_4bed_equiv'])}, "
          f"trend {num(allm['trend_pct'], 1, '%')}")
    sector = pr["levels"].get("sector", {})
    w("  Sector by type: " + "; ".join(f"{TYPES[t]} {gbp(m['median_price_recent'])} ({m['sales_recent']})"
                                         for t, m in sorted(sector.items()) if t != "ALL" and m["sales_recent"]))
    band = ctx.area["prices"]["flag_band_gbp"]
    sales = conn.execute(
        "SELECT date, price, street, property_type, postcode FROM ppd WHERE category='A' AND postcode=? "
        "AND date >= date((SELECT MAX(date) FROM ppd), '-36 months') ORDER BY date DESC", (pcds,)).fetchall()
    if len(sales) < 5:
        sales = conn.execute(
            "SELECT date, price, street, property_type, postcode FROM ppd WHERE category='A' AND substr(postcode,1,?)=? "
            "AND date >= date((SELECT MAX(date) FROM ppd), '-36 months') ORDER BY date DESC LIMIT 12",
            (len(p["sector"]), p["sector"])).fetchall()
        w(f"  Recent sales in sector {p['sector']} (last 3 years, newest 12; * = GBP {band[0]:,}-{band[1]:,}):")
    else:
        w(f"  Recent sales in {pcds} (last 3 years; * = GBP {band[0]:,}-{band[1]:,}):")
    for s in sales:
        flag = "*" if band[0] <= s["price"] <= band[1] else " "
        w(f"   {flag} {s['date']}  {gbp(s['price']):>13}  {TYPES.get(s['property_type'], s['property_type']):<9} {s['street']}, {s['postcode']}")

    sf = p["safety"]
    lsoa = sf["lsoa"] or {}
    span = conn.execute("SELECT MIN(month), MAX(month) FROM crimes").fetchone()
    w(f"\nCRIME (data.police.uk, {span[0]} to {span[1]}, {lsoa.get('months', 'n/a')} months; LSOA {p['lsoa21']})")
    w(f"  All crime:      {num(lsoa.get('rate_per_1000'))} per 1,000 residents a year  (borough median {num(sf['borough_median_rate'])})")
    w(f"  Family-relevant (burglary, vehicle, violence and sexual, robbery): {num(lsoa.get('family_rate_per_1000'))} "
      f"(borough median {num(sf['borough_median_family_rate'])})")
    top = conn.execute("SELECT category, COUNT(*) n FROM crimes WHERE lsoa21=? GROUP BY category ORDER BY n DESC LIMIT 3",
                       (p["lsoa21"],)).fetchall()
    if top:
        w("  Largest categories: " + ", ".join(f"{t['category']} {t['n']}" for t in top) +
          "  (shopping areas inflate shoplifting counts)")
    imd = sf["imd"] or {}
    w(f"\nDEPRIVATION ({imd.get('release', 'n/a')}, decile 1 = most deprived 10%, 10 = least deprived)")
    w(f"  IMD {imd.get('imd_decile')}  income {imd.get('income_decile')}  crime {imd.get('crime_decile')}  "
      f"living environment {imd.get('living_env_decile')}  education {imd.get('education_decile')}")

    oa = p["community"]["oa"]
    g = lambda k: (oa.get(k) or {}).get("pct")
    w(f"\nCOMMUNITY (Census 2021, output area {p['oa21']}; OpenStreetMap fetched {asof('osm')})")
    w(f"  Asian {num(g('TS021:asian'), 1, '%')}  (Indian {num(g('TS021:indian'), 1, '%')}, Pakistani {num(g('TS021:pakistani'), 1, '%')}, "
      f"Bangladeshi {num(g('TS021:bangladeshi'), 1, '%')}, Chinese {num(g('TS021:chinese'), 1, '%')}, Other Asian {num(g('TS021:other_asian'), 1, '%')})")
    w(f"  Muslim {num(g('TS030:muslim'), 1, '%')}  Sikh {num(g('TS030:sikh'), 1, '%')}  Hindu {num(g('TS030:hindu'), 1, '%')}")
    for kind in ("mosque", "halal", "gurdwara", "mandir"):
        n = p["community"]["nearest"].get(kind)
        if n:
            w(f"  Nearest {kind:<9} {num(n['miles'], 2, ' mi')}  {n['name'] or '(unnamed)'}")

    sc = p["score"]
    w("\nAREA SCORE (percentiles within the pool; weights from config/scoring.yaml)")
    if sc:
        d = json.loads(sc["detail_json"])
        weights = ctx.scoring["weights"]
        for k in ("school", "price", "safety", "community"):
            w(f"  {k:<10} w={weights[k]:<3} {bar(sc[k])}")
            parts = ", ".join(f"{pk} {num(pv, 0)}" for pk, pv in d[k]["parts"].items())
            w(f"             {parts}")
        if d["school"]["capped_not_in_catchment"]:
            w("  School score capped: postcode is in neither target catchment.")
        w(f"  Price basis: {d['price']['basis']}; budget value {gbp(d['price']['budget_value'])} vs budget {gbp(ctx.scoring['budget_gbp'])}")
        w(f"  TOTAL      {bar(sc['total'])}")

    manual = [s for s, r in runs.items() if r["status"].startswith("skipped")]
    unverified = [r["name"] for r in conn.execute("SELECT name FROM school_gates WHERE verified=0")]
    if manual or unverified:
        w("\nMANUAL DATA NEEDED")
        for s in manual:
            w(f"  - {s}: {runs[s]['note'][:160]}")
        if unverified:
            w(f"  - Verify gate coordinates in data/seed/school_gates.csv: {', '.join(unverified)}")
    w("=" * 78)
    return "\n".join(out)


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print(__doc__)
        return 2
    ctx = Context.create(offline=True)
    print(render(ctx, normalise_postcode(" ".join(args))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
