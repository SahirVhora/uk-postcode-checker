"""A. Postcode backbone: ONS Postcode Directory (latest release) via the ONS Open Geography Portal.

The latest ONSPD hosted table is discovered by searching the ONSGeography_data
ArcGIS catalogue and parsing the release month from the item title. Field names
that carry a year suffix (lad26cd, wd26cd) are matched by pattern.
"""

import json
import logging
import random
import re
from datetime import datetime

from .. import SourceFormatChanged
from ..db import upsert
from ..discover import arcgis_item, arcgis_query_all, arcgis_search
from ..geo import haversine_miles

NAME = "onspd"
LICENCE = "Open Government Licence v3.0 (contains OS data and Royal Mail data, see ons.gov.uk/methodology/geography/licences)"
POSTCODES_IO = "https://api.postcodes.io/postcodes"
TITLE_RE = re.compile(r"^ONS Postcode Directory \((\w+) (\d{4})\) for the (?:United Kingdom|UK) \(Hosted Table\)$")

log = logging.getLogger(__name__)


def latest_release(results: list[dict]) -> tuple[str, dict]:
    """Pick the newest ONSPD hosted table from catalogue search results."""
    best = None
    for item in results:
        m = TITLE_RE.match(item.get("title", "").strip())
        if not m:
            continue
        when = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%B %Y")
        if best is None or when > best[0]:
            best = (when, item)
    if not best:
        titles = [r.get("title") for r in results]
        raise SourceFormatChanged(f"No 'ONS Postcode Directory (<Month YYYY>) ... (Hosted Table)' item found. Titles seen: {titles}")
    return best[0].strftime("%B %Y"), best[1]


def pick_field(fields: list[str], pattern: str, what: str) -> str:
    for f in fields:
        if re.fullmatch(pattern, f, re.I):
            return f
    raise SourceFormatChanged(f"ONSPD has no {what} field matching /{pattern}/. Fields: {fields}")


def fetch(ctx):
    f = ctx.fetcher(NAME)
    results = arcgis_search(f, 'title:"ONS Postcode Directory" AND owner:ONSGeography_data AND type:"Feature Service"', num=30)
    release, item = latest_release(results)
    detail = arcgis_item(f, item["id"])
    layer = detail["url"].rstrip("/") + "/0"
    log.info("ONSPD release %s at %s", release, layer)
    ctx.source_url = layer
    outcodes = ctx.area["outcodes"]
    where = " OR ".join(f"pcds LIKE '{oc} %'" for oc in outcodes)
    features = arcgis_query_all(f, layer, where)
    rows = [feat["attributes"] for feat in features]
    names = postcodes_io_names(ctx.fetcher("postcodes_io", min_interval=0.2),
                               [r["pcds"] for r in rows if not r.get("doterm")])
    return {"release": release, "rows": rows, "names": names}


def postcodes_io_names(fetcher, postcodes: list[str]) -> dict:
    """Ward and district names (ONSPD carries codes only). Bulk lookups of 100."""
    out = {}
    for i in range(0, len(postcodes), 100):
        chunk = sorted(postcodes[i:i + 100])
        body = fetcher.post(POSTCODES_IO, data=json.dumps({"postcodes": chunk}),
                            headers={"Content-Type": "application/json"})
        for item in json.loads(body).get("result", []):
            res = item.get("result")
            if res:
                out[item["query"]] = {"ward_name": res.get("admin_ward"), "lad_name": res.get("admin_district"),
                                      "lat": res.get("latitude"), "lng": res.get("longitude"),
                                      "lsoa21": (res.get("codes") or {}).get("lsoa21") or (res.get("codes") or {}).get("lsoa")}
    return out


def parse(ctx, raw) -> list[dict]:
    rows = raw["rows"]
    if not rows:
        raise SourceFormatChanged("ONSPD query returned no postcodes for the configured outcodes.")
    fields = list(rows[0].keys())
    lad = pick_field(fields, r"lad\d{2}cd", "local authority")
    ward = pick_field(fields, r"wd\d{2}cd", "ward")
    for need in ("pcds", "doterm", "lat", "long", "oa21cd", "lsoa21cd", "msoa21cd"):
        pick_field(fields, need, need)
    out = []
    for r in rows:
        if r.get("doterm"):
            continue  # terminated postcode
        lat, lng = float(r["lat"]), float(r["long"])
        if lat > 90:  # ONSPD uses 99.999999 when no grid reference exists
            continue
        pcds = r["pcds"].strip().upper()
        outcode, inward = pcds.split(" ")
        names = raw["names"].get(pcds, {})
        out.append({
            "pcds": pcds, "outcode": outcode, "sector": f"{outcode} {inward[0]}",
            "lat": lat, "lng": lng,
            "oa21": r["oa21cd"], "lsoa21": r["lsoa21cd"], "msoa21": r["msoa21cd"],
            "ward_code": r[ward], "ward_name": names.get("ward_name"),
            "lad_code": r[lad], "lad_name": names.get("lad_name"),
            "onspd_release": raw["release"], "in_target_catchment": None,
        })
    return out


def load(ctx, rows) -> int:
    conn = ctx.conn
    keep = {r["pcds"] for r in rows}
    outcodes = ctx.area["outcodes"]
    existing = conn.execute(
        f"SELECT pcds FROM postcodes WHERE outcode IN ({','.join('?' * len(outcodes))})", outcodes).fetchall()
    stale = [(e[0],) for e in existing if e[0] not in keep]
    conn.executemany("DELETE FROM postcodes WHERE pcds = ?", stale)
    # Preserve catchment flags computed by the catchments source.
    for r in rows:
        r.pop("in_target_catchment")
    upsert(conn, "postcodes", rows, ("pcds",))
    conn.commit()
    return len(rows)


def validate(ctx, sample_size: int = 5) -> list[str]:
    """Cross-check random postcodes against postcodes.io (cached lookups)."""
    pool = ctx.pool()
    if len(pool) < 100:
        raise SourceFormatChanged(f"Only {len(pool)} live postcodes loaded; expected thousands for {ctx.area['outcodes']}.")
    rng = random.Random(42)
    sample = rng.sample(list(pool), min(sample_size, len(pool)))
    names = postcodes_io_names(ctx.fetcher("postcodes_io"), [r["pcds"] for r in sample])
    problems = []
    for r in sample:
        ref = names.get(r["pcds"])
        if not ref:
            problems.append(f"{r['pcds']}: not found on postcodes.io")
            continue
        drift = haversine_miles(r["lat"], r["lng"], ref["lat"], ref["lng"]) * 1609.34
        if drift > 50:
            problems.append(f"{r['pcds']}: centroid differs from postcodes.io by {drift:.0f} m")
        if ref["lsoa21"] and ref["lsoa21"] != r["lsoa21"]:
            problems.append(f"{r['pcds']}: LSOA {r['lsoa21']} vs postcodes.io {ref['lsoa21']}")
    ctx.notes.append(f"postcodes.io cross-check: {len(sample) - len(problems)}/{len(sample)} matched")
    return problems
