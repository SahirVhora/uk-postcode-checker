"""Print data-quality checks for the local database, for comparison against official sites.

    python -m pipeline.validate

Shows row counts per table, null rates for key columns, the PPD to EPC match
rate, the latest status of each source, and five random spot-check postcodes
with all their metrics and the official pages to compare them against.
"""

import random
import sys

from .context import Context
from .db import LOCAL_ONLY_TABLES, SCHEMA
from .matching import match_rate
from .profile import ProfileBuilder

NULL_CHECKS = {
    "postcodes": ["ward_name", "lsoa21", "oa21", "in_target_catchment"],
    "schools": ["lat", "phase"],
    "ofsted": ["legacy_overall_effectiveness", "ungraded_outcome", "report_card_date"],
    "performance": ["value"],
    "ppd": ["street", "paon"],
    "epc": ["total_floor_area", "habitable_rooms"],
    "crimes": ["lsoa21"],
    "crime_rates": ["population", "rate_per_1000"],
    "scores": ["school", "price", "safety", "community", "total"],
}


def tables() -> list[str]:
    import re
    return re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", SCHEMA)


def main(argv=None) -> int:
    ctx = Context.create(offline=True)
    conn = ctx.conn
    print("ROW COUNTS")
    for t in tables():
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t:<26}{n:>9}{'   (local only, never exported)' if t in LOCAL_ONLY_TABLES else ''}")

    print("\nNULL RATES")
    for t, cols in NULL_CHECKS.items():
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        if not n:
            print(f"  {t:<14} (empty)")
            continue
        rates = ", ".join(f"{c} {conn.execute(f'SELECT AVG({c} IS NULL) FROM {t}').fetchone()[0]:.0%}" for c in cols)
        print(f"  {t:<14} {rates}")

    matched, total = match_rate(conn)
    print(f"\nPPD TO EPC MATCH RATE: {matched}/{total} = {matched / total:.1%}" if total else "\nPPD TO EPC MATCH RATE: no sales")
    if total and not conn.execute("SELECT COUNT(*) FROM epc").fetchone()[0]:
        print("  (EPC not loaded: see docs/MANUAL_CHECKS.md)")

    print("\nSOURCES (latest run)")
    for r in conn.execute("SELECT source, status, row_count, fetched_at FROM source_runs "
                          "WHERE id IN (SELECT MAX(id) FROM source_runs GROUP BY source) ORDER BY source"):
        print(f"  {r['source']:<16}{r['status']:<30}{r['row_count'] if r['row_count'] is not None else '':>8}  {r['fetched_at'] or ''}")

    print("\nSPOT CHECKS (compare with the official sites listed)")
    builder = ProfileBuilder(conn, ctx.area, ctx.borough_lad())
    pool = [r["pcds"] for r in ctx.pool()]
    for pcds in random.Random(2026).sample(pool, min(5, len(pool))):
        p = builder.build(pcds)
        sc = p["score"] or {}
        lv = p["prices"]["levels"].get(p["prices"]["level_used"], {}).get("ALL") or {}
        oa = p["community"]["oa"]
        lsoa = p["safety"]["lsoa"] or {}
        imd = p["safety"]["imd"] or {}
        print(f"\n  {pcds}  ({p['ward_name']}, LSOA {p['lsoa21']})")
        print(f"    catchments: {', '.join(p['catchments']['secondary']) or 'none'}  -> check solihull.gov.uk/onlinemaps")
        for s in p["schools"].values():
            print(f"    {s['name']}: {s['gate_miles']} mi, {s['default']['indicator']}")
        print(f"    prices ({p['prices']['level_used']}): {lv.get('sales_recent')} sales, median {lv.get('median_price_recent')}"
              "  -> check landregistry.data.gov.uk/app/ppd")
        print(f"    crime: {lsoa.get('rate_per_1000')} per 1,000 (family {lsoa.get('family_rate_per_1000')})  -> check police.uk")
        print(f"    IMD decile {imd.get('imd_decile')} ({imd.get('release')})"
              "  -> check imd-by-postcode.opendatacommunities.org")
        print(f"    Asian {(oa.get('TS021:asian') or {}).get('pct')}%, Muslim {(oa.get('TS030:muslim') or {}).get('pct')}% (OA {p['oa21']})"
              "  -> check nomisweb.co.uk")
        print(f"    score: school {sc.get('school')}, price {sc.get('price')}, safety {sc.get('safety')}, "
              f"community {sc.get('community')}, total {sc.get('total')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
