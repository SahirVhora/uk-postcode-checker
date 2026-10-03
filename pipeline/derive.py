"""Derived tables computed from loaded sources: distances, nearest places, crime rates, price metrics, scores."""

import logging
import statistics
from datetime import date

from .db import upsert
from .geo import haversine_miles

log = logging.getLogger("pipeline")
PROPERTY_TYPES = ("D", "S", "T", "F", "O")


def gate_distances(conn) -> int:
    gates = conn.execute("SELECT urn, lat, lng FROM school_gates").fetchall()
    rows = [{"pcds": p["pcds"], "urn": g["urn"], "miles": round(haversine_miles(p["lat"], p["lng"], g["lat"], g["lng"]), 3),
             "to_gate": 1}
            for p in conn.execute("SELECT pcds, lat, lng FROM postcodes") for g in gates]
    conn.execute("DELETE FROM postcode_school_distance")
    upsert(conn, "postcode_school_distance", rows, ("pcds", "urn"))
    return len(rows)


def nearest_pois(conn) -> int:
    pois: dict[str, list] = {}
    for r in conn.execute("SELECT osm_key, kind, name, lat, lng FROM osm_pois"):
        pois.setdefault(r["kind"], []).append(r)
    rows = []
    for p in conn.execute("SELECT pcds, lat, lng FROM postcodes"):
        for kind, items in pois.items():
            best = min(items, key=lambda r: haversine_miles(p["lat"], p["lng"], r["lat"], r["lng"]))
            rows.append({"pcds": p["pcds"], "kind": kind, "osm_key": best["osm_key"], "name": best["name"],
                         "miles": round(haversine_miles(p["lat"], p["lng"], best["lat"], best["lng"]), 3)})
    conn.execute("DELETE FROM postcode_poi_nearest")
    upsert(conn, "postcode_poi_nearest", rows, ("pcds", "kind"))
    return len(rows)


def crime_rates(conn, family_categories: list[str]) -> int:
    months = conn.execute("SELECT COUNT(DISTINCT month) FROM crimes").fetchone()[0]
    if not months:
        return 0
    placeholders = ",".join("?" * len(family_categories))
    rows = []
    for b in conn.execute("SELECT lsoa21, lad_code FROM lsoa_boundaries"):
        pop = conn.execute("SELECT count FROM census WHERE geo_code=? AND table_id='TS001' AND category='total'",
                           (b["lsoa21"],)).fetchone()
        total = conn.execute("SELECT COUNT(*) FROM crimes WHERE lsoa21=?", (b["lsoa21"],)).fetchone()[0]
        family = conn.execute(f"SELECT COUNT(*) FROM crimes WHERE lsoa21=? AND category IN ({placeholders})",
                              (b["lsoa21"], *family_categories)).fetchone()[0]
        population = pop[0] if pop else None
        annual = 12 / months
        rows.append({"lsoa21": b["lsoa21"], "lad_code": b["lad_code"], "population": population, "months": months,
                     "total": total, "family": family,
                     "rate_per_1000": round(total * annual / population * 1000, 1) if population else None,
                     "family_rate_per_1000": round(family * annual / population * 1000, 1) if population else None})
    conn.execute("DELETE FROM crime_rates")
    upsert(conn, "crime_rates", rows, ("lsoa21",))
    return len(rows)


def borough_crime_medians(conn, lad_code: str) -> tuple[float | None, float | None]:
    rates = conn.execute("SELECT rate_per_1000, family_rate_per_1000 FROM crime_rates WHERE lad_code=? AND rate_per_1000 IS NOT NULL",
                         (lad_code,)).fetchall()
    if not rates:
        return None, None
    return statistics.median(r[0] for r in rates), statistics.median(r[1] for r in rates)


def months_back(d: date, months: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 - months, 12)
    return date(y, m + 1, min(d.day, 28))


def _metrics(sales: list[dict], ref: date, recent_months: int) -> dict:
    start = months_back(ref, recent_months).isoformat()
    mid = months_back(ref, recent_months // 2).isoformat()
    recent = [s for s in sales if s["date"] > start]
    prices = [s["price"] for s in recent]
    per_sqm = [s["price"] / s["area"] for s in recent if s["area"]]
    four = [s["price"] for s in recent if (s["rooms"] or 0) >= 5]
    newer = [s["price"] for s in recent if s["date"] > mid]
    older = [s["price"] for s in recent if s["date"] <= mid]
    trend = None
    if len(newer) >= 3 and len(older) >= 3:
        trend = round(100 * (statistics.median(newer) / statistics.median(older) - 1), 1)
    return {"sales_recent": len(recent),
            "median_price_recent": int(statistics.median(prices)) if prices else None,
            "median_gbp_per_sqm": round(statistics.median(per_sqm), 0) if per_sqm else None,
            "median_4bed_equiv": int(statistics.median(four)) if four else None,
            "sales_4bed_equiv": len(four), "trend_pct": trend}


def price_metrics(conn, recent_months: int) -> int:
    sales = [dict(r) for r in conn.execute(
        "SELECT p.price, p.date, p.postcode, p.property_type, e.total_floor_area AS area, e.habitable_rooms AS rooms "
        "FROM ppd p LEFT JOIN ppd_epc_match m ON m.tid = p.tid LEFT JOIN epc e ON e.cert_number = m.cert_number "
        "WHERE p.category = 'A'")]
    if not sales:
        return 0
    ref = date.fromisoformat(max(s["date"] for s in sales))
    groups: dict[tuple, list] = {}
    for s in sales:
        pc = s["postcode"] or ""
        if " " not in pc:
            continue
        outcode, inward = pc.split(" ")
        for level, area in (("postcode", pc), ("sector", f"{outcode} {inward[0]}"), ("outcode", outcode)):
            groups.setdefault((level, area, "ALL"), []).append(s)
            groups.setdefault((level, area, s["property_type"]), []).append(s)
            if s["property_type"] in ("D", "S", "T"):
                groups.setdefault((level, area, "H"), []).append(s)  # houses: family-home proxy
    rows = [{"level": lvl, "area": area, "property_type": pt, **_metrics(ss, ref, recent_months)}
            for (lvl, area, pt), ss in groups.items()]
    conn.execute("DELETE FROM price_metrics")
    upsert(conn, "price_metrics", rows, ("level", "area", "property_type"))
    return len(rows)


def run_all(ctx) -> None:
    conn = ctx.conn
    log.info("=== derive")
    log.info("gate distances: %d", gate_distances(conn))
    log.info("nearest places: %d", nearest_pois(conn))
    log.info("crime rates: %d LSOAs", crime_rates(conn, ctx.area["crime"]["family_categories"]))
    log.info("price metrics: %d", price_metrics(conn, ctx.area["prices"]["recent_months"]))
    conn.commit()
    from . import score
    log.info("scores: %d", score.compute(ctx))


def main() -> int:
    """Recompute distances, metrics and scores from the local DB (no network): python -m pipeline.derive"""
    from .context import Context
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    run_all(Context.create(offline=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
