"""Export the public Area Pack (data/area-pack/*.json) served by GitHub Pages.

Only per-postcode aggregates, booleans and distances are written. No catchment
or LSOA polygons, no house numbers or full addresses. The export refuses to
write anything that contains polygon geometry.

    python -m pipeline.export
"""

import json
import logging
import sys
from datetime import date

from . import PACK_DIR, SourceFormatChanged
from .context import Context
from .geo import contains_polygon_geometry
from .profile import ProfileBuilder

log = logging.getLogger("pipeline")
SALES_MONTHS = 36
CENSUS_KEYS = ["TS021:asian", "TS021:indian", "TS021:pakistani", "TS021:bangladeshi", "TS021:chinese",
               "TS021:other_asian", "TS030:muslim", "TS030:sikh", "TS030:hindu", "TS030:christian", "TS030:no_religion"]


def attribution(year: int) -> list[str]:
    return [
        f"Contains HM Land Registry data (c) Crown copyright and database right {year}. This data is licensed under the Open Government Licence v3.0.",
        "Contains public sector information licensed under the Open Government Licence v3.0 (DfE, Ofsted, MHCLG, data.police.uk).",
        f"Source: Office for National Statistics licensed under the Open Government Licence v3.0. Contains OS data (c) Crown copyright and database right {year}. Contains Royal Mail data (c) Royal Mail copyright and database right {year}.",
        "(c) OpenStreetMap contributors, available under the Open Database Licence (ODbL).",
        "Catchment yes/no flags are derived locally from Solihull Council online maps; boundaries are not republished. Always confirm at solihull.gov.uk/onlinemaps.",
    ]


def r(x, nd=2):
    return None if x is None else round(x, nd)


def sources_meta(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT source, url, licence, fetched_at, row_count, status, note FROM source_runs "
        "WHERE id IN (SELECT MAX(id) FROM source_runs GROUP BY source) ORDER BY source").fetchall()
    return [{"source": x["source"], "url": x["url"], "licence": x["licence"], "fetched_at": x["fetched_at"],
             "rows": x["row_count"], "status": x["status"]} for x in rows]


def school_meta(builder: ProfileBuilder, area: dict) -> dict:
    from .admissions_model import load_rules
    out = {}
    for s in area["target_schools"]:
        info = builder.school_info[s["urn"]]
        rules = load_rules(s["rules"])
        out[s["key"]] = {
            "urn": s["urn"], "name": s["name"], "ofsted": info["ofsted"], "performance": info["performance"],
            "history": builder.history[s["urn"]], "gate_verified": bool(builder.gates.get(s["urn"], {}).get("verified")),
            "rules": {"policy_year": rules["policy_year"], "source_url": rules["source_url"], "pan": rules["pan"],
                      "tie_break": rules["tie_break"],
                      "categories": [{"priority": c["priority"], "label": c["label"]} for c in rules["categories"]]},
        }
    for f in area.get("feeder_schools", []):
        info = builder.school_info[f["urn"]]
        out[f["key"]] = {"urn": f["urn"], "name": f["name"], "ofsted": info["ofsted"], "performance": info["performance"],
                         "gate_verified": bool(builder.gates.get(f["urn"], {}).get("verified"))}
    return out


INDICATOR_CODES = {"safe": "historically safe", "all": "offered in every year shown", "none": "not offered in any year shown",
                   "some": "offered in some years shown", "nohist": "no history available"}


def indicator_code(a: dict) -> str:
    """Short code for the historic chance indicator (labels live in index.json)."""
    if a["historically_safe"]:
        return "safe"
    if not a["years"]:
        return "nohist"
    if a["years_admitted"] == a["years"]:
        return "all"
    return "none" if a["years_admitted"] == 0 else "some"


def compact_assessment(a: dict) -> dict:
    return {"priority": a["priority"], "indicator": indicator_code(a),
            "safe": a["historically_safe"], "admitted": a["years_admitted"], "years": a["years"],
            "outcomes": [[o["year"], o["outcome"]] for o in a["outcomes"]]}


def compact_metrics(m: dict) -> dict:
    keys = ("sales_recent", "median_price_recent", "median_gbp_per_sqm", "median_4bed_equiv", "sales_4bed_equiv", "trend_pct")
    return {k: m.get(k) for k in keys}


def shard_id(pcds: str) -> str:
    """Postcodes are grouped by sector plus the first letter of the unit: 'B90 3DF' -> 'B90-3D'."""
    outcode, inward = pcds.split(" ")
    return f"{outcode}-{inward[:2]}"


def compact(p: dict) -> dict:
    """The per-postcode record published in a sector shard."""
    score = p["score"] or {}
    detail = json.loads(score.get("detail_json") or "{}")
    schools = {}
    for key, s in p["schools"].items():
        schools[key] = {
            "in_catchment": s["in_catchment"], "gate_miles": r(s["gate_miles"], 3), "gate_verified": s["gate_verified"],
            "default": compact_assessment(s["default"]),
            "st_james": compact_assessment(s["st_james"]),
        }
    prices = p["prices"]
    lvl = prices["level_used"]
    oa, lsoa = p["community"]["oa"], p["community"]["lsoa"]
    lsoa_crime = p["safety"]["lsoa"] or {}
    imd = p["safety"]["imd"] or {}
    return {
        "lat": r(p["lat"], 5), "lng": r(p["lng"], 5), "ward": p["ward_name"], "lad": p["lad_name"],
        "lsoa21": p["lsoa21"], "oa21": p["oa21"],
        "in_target_catchment": p["in_target_catchment"],
        "catchments": p["catchments"],
        "schools": schools,
        "feeders": {k: {"miles": r(v["miles"], 3), "gate_verified": v["gate_verified"]} for k, v in p["feeders"].items()},
        "prices": {"level_used": lvl, "area": {"postcode": p["pcds"], "sector": p["sector"], "outcode": p["outcode"]}[lvl],
                   "metrics": {t: compact_metrics(m) for t, m in prices["levels"].get(lvl, {}).items()
                               if t in ("ALL", "D", "S", "T", "F")}},
        "safety": {"rate_per_1000": lsoa_crime.get("rate_per_1000"), "family_rate_per_1000": lsoa_crime.get("family_rate_per_1000"),
                   "crimes_12m": lsoa_crime.get("total"), "months": lsoa_crime.get("months"),
                   "borough_median_rate": r(p["safety"]["borough_median_rate"], 1),
                   "borough_median_family_rate": r(p["safety"]["borough_median_family_rate"], 1),
                   "imd_release": imd.get("release"), "imd_decile": imd.get("imd_decile"), "imd_rank": imd.get("imd_rank"),
                   "income_decile": imd.get("income_decile"), "crime_decile": imd.get("crime_decile"),
                   "living_env_decile": imd.get("living_env_decile"), "education_decile": imd.get("education_decile")},
        "community": {"oa": {k: r(oa[k]["pct"], 1) for k in CENSUS_KEYS if k in oa},
                      "lsoa": {k: r(lsoa[k]["pct"], 1) for k in ("TS021:asian", "TS030:muslim") if k in lsoa},
                      "nearest": p["community"]["nearest"]},
        "score": {"school": score.get("school"), "price": score.get("price"), "safety": score.get("safety"),
                  "community": score.get("community"), "total": score.get("total"),
                  "price_raw": detail.get("price", {}).get("raw_before_budget"),
                  "budget_value": detail.get("price", {}).get("budget_value"),
                  "parts": {k: {pk: r(pv, 1) for pk, pv in (detail.get(k) or {}).get("parts", {}).items()}
                            for k in ("school", "price", "safety", "community")},
                  "school_capped": (detail.get("school") or {}).get("capped_not_in_catchment")},
    }


def sector_sales(conn, sector: str) -> list[dict]:
    """Category A sales in the sector over the last SALES_MONTHS months. Street only, never house numbers."""
    rows = conn.execute(
        "SELECT p.date, p.price, p.street, p.locality, p.property_type, p.new_build, p.tenure, p.postcode, "
        "e.total_floor_area, e.habitable_rooms FROM ppd p "
        "LEFT JOIN ppd_epc_match m ON m.tid = p.tid LEFT JOIN epc e ON e.cert_number = m.cert_number "
        "WHERE p.category = 'A' AND substr(p.postcode, 1, length(?)) = ? AND p.date >= date((SELECT MAX(date) FROM ppd), ?) "
        "ORDER BY p.date DESC", (sector, sector, f"-{SALES_MONTHS} months")).fetchall()
    out = []
    for x in rows:
        rooms = x["habitable_rooms"]
        out.append({"date": x["date"], "price": x["price"], "street": x["street"], "locality": x["locality"],
                    "type": x["property_type"], "new_build": x["new_build"] == "Y", "tenure": x["tenure"],
                    "postcode": x["postcode"], "floor_area": x["total_floor_area"],
                    "rooms_band": None if rooms is None else ("6+" if rooms >= 6 else str(rooms))})
    return out


def price_basis(conn) -> str:
    row = conn.execute("SELECT detail_json FROM scores LIMIT 1").fetchone()
    return json.loads(row[0])["price"]["basis"] if row else ""


def shortlist_row(pcds: str, c: dict) -> dict:
    s = c["schools"]
    m = (c["prices"]["metrics"] or {}).get("ALL") or {}
    nearest = c["community"]["nearest"]
    return {
        "pcds": pcds, "outcode": pcds.split(" ")[0], "lat": r(c["lat"], 4), "lng": r(c["lng"], 4),
        "in_target": c["in_target_catchment"],
        "in_tga": s.get("tga", {}).get("in_catchment"), "in_alderbrook": s.get("alderbrook", {}).get("in_catchment"),
        "tga_mi": s.get("tga", {}).get("gate_miles"), "alderbrook_mi": s.get("alderbrook", {}).get("gate_miles"),
        "tga_indicator": s.get("tga", {}).get("default", {}).get("indicator"),
        "alderbrook_indicator": s.get("alderbrook", {}).get("default", {}).get("indicator"),
        "median_price": m.get("median_price_recent"), "price_level": c["prices"]["level_used"],
        "family_rate": c["safety"]["family_rate_per_1000"], "imd_decile": c["safety"]["imd_decile"],
        "asian_pct": c["community"]["oa"].get("TS021:asian"), "muslim_pct": c["community"]["oa"].get("TS030:muslim"),
        "mosque_mi": (nearest.get("mosque") or {}).get("miles"), "halal_mi": (nearest.get("halal") or {}).get("miles"),
        **{k: c["score"][k] for k in ("school", "price", "price_raw", "budget_value", "safety", "community", "total")},
    }


def write_json(path, obj) -> None:
    if contains_polygon_geometry(obj):
        raise SourceFormatChanged(f"Refusing to write {path}: it contains polygon geometry")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(",", ":"), ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def export(ctx, out_dir=PACK_DIR) -> dict:
    conn = ctx.conn
    builder = ProfileBuilder(conn, ctx.area, ctx.borough_lad())
    # The export owns these generated folders: remove stale files before writing new ones.
    for sub in ("postcodes", "sectors"):
        folder = out_dir / sub
        for old in folder.glob("*.json") if folder.exists() else []:
            old.unlink()
    shards: dict[str, dict] = {}
    sectors: set[str] = set()
    index_postcodes, shortlist = {}, []
    for pc in ctx.pool():
        p = builder.build(pc["pcds"])
        c = compact(p)
        sid = shard_id(pc["pcds"])
        shards.setdefault(sid, {})[pc["pcds"]] = c
        sectors.add(pc["sector"])
        index_postcodes[pc["pcds"]] = sid
        shortlist.append(shortlist_row(pc["pcds"], c))
    for sid, postcodes in shards.items():
        write_json(out_dir / "postcodes" / f"{sid}.json", {"shard": sid, "postcodes": postcodes})
    for sector in sorted(sectors):
        levels = {x["property_type"]: compact_metrics(dict(x)) for x in conn.execute(
            "SELECT * FROM price_metrics WHERE level='sector' AND area=?", (sector,))}
        write_json(out_dir / "sectors" / f"{sector.replace(' ', '-')}.json",
                   {"sector": sector, "metrics": levels, "recent_sales": sector_sales(conn, sector),
                    "recent_sales_months": SALES_MONTHS})
    sc = ctx.scoring
    year = date.today().year
    index = {
        "generated_at": date.today().isoformat(), "area": ctx.area["name"], "outcodes": ctx.area["outcodes"],
        "borough_lad": ctx.borough_lad(), "sources": sources_meta(conn), "attribution": attribution(year),
        "scoring": {"weights": sc["weights"], "budget_gbp": sc["budget_gbp"],
                    "over_budget_multiplier": sc["price"]["over_budget_multiplier"],
                    "not_in_catchment_cap": sc["school"]["not_in_catchment_cap"]},
        "schools": school_meta(builder, ctx.area),
        "indicator_labels": INDICATOR_CODES,
        "price_flag_band": ctx.area["prices"]["flag_band_gbp"],
        "price_basis": price_basis(conn),
        "distance_note": "Straight-line distance from the postcode centre to the school gate: postcode-centroid estimate, actual LLPG distance may differ by up to ~0.1 mi.",
        "postcodes": index_postcodes,
    }
    write_json(out_dir / "index.json", index)
    columns = list(shortlist[0].keys()) if shortlist else []
    write_json(out_dir / "shortlist.json", {"generated_at": index["generated_at"], "scoring": index["scoring"],
                                            "attribution": index["attribution"], "columns": columns,
                                            "rows": [[row[col] for col in columns] for row in shortlist]})
    return {"postcodes": len(index_postcodes), "shards": len(shards), "sectors": len(sectors)}


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    ctx = Context.create(offline=True)
    stats = export(ctx)
    total = sum(f.stat().st_size for f in PACK_DIR.rglob("*.json"))
    largest = max(PACK_DIR.rglob("*.json"), key=lambda f: f.stat().st_size)
    print(f"Exported {stats['postcodes']} postcodes in {stats['shards']} postcode files and {stats['sectors']} sector files "
          f"to {PACK_DIR} ({total / 1e6:.1f} MB, largest {largest.name} {largest.stat().st_size / 1e3:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
