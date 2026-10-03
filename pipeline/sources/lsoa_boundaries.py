"""D. LSOA 2021 boundaries (ONS Open Geography Portal), used only to assign police
crime points to LSOAs. The police API does not return an LSOA code, so points are
placed with point-in-polygon. Stored locally only.
"""

import json
import logging
import re

from .. import SourceFormatChanged
from ..db import upsert
from ..discover import arcgis_item, arcgis_query_all, arcgis_search

NAME = "lsoa_boundaries"
LICENCE = "Source: Office for National Statistics licensed under the Open Government Licence v3.0. Contains OS data (c) Crown copyright and database right"
TITLE_RE = re.compile(r"^Lower layer Super Output Areas \(December 2021\) Boundaries EW BGC(?: \(V(\d+)\))?$")

log = logging.getLogger(__name__)


def fetch(ctx):
    f = ctx.fetcher(NAME)
    results = arcgis_search(f, 'title:"Lower layer Super Output Areas (December 2021) Boundaries EW BGC" AND owner:ONSGeography_data AND type:"Feature Service"')
    cands = []
    for r in results:
        m = TITLE_RE.match(r.get("title", "").strip())
        if m:
            cands.append((int(m.group(1) or 0), r))
    if not cands:
        raise SourceFormatChanged(f"No LSOA 2021 BGC boundary service found. Titles: {[r.get('title') for r in results]}")
    item = max(cands, key=lambda c: c[0])[1]
    layer = arcgis_item(f, item["id"])["url"].rstrip("/") + "/0"
    ctx.source_url = layer
    wanted = sorted({r[0] for r in ctx.conn.execute(
        "SELECT lsoa21 FROM imd WHERE lad_code = ? UNION SELECT DISTINCT lsoa21 FROM postcodes", (ctx.borough_lad(),))})
    if not wanted:
        raise RuntimeError("Run onspd and imd before lsoa_boundaries")
    feats = []
    for i in range(0, len(wanted), 100):
        chunk = wanted[i:i + 100]
        where = "LSOA21CD IN (" + ",".join(f"'{c}'" for c in chunk) + ")"
        feats.extend(arcgis_query_all(f, layer, where, geometry=True, fmt="geojson"))
    return feats


def parse(ctx, raw) -> list[dict]:
    lad = {r[0]: r[1] for r in ctx.conn.execute("SELECT lsoa21, lad_code FROM imd")}
    rows = []
    for feat in raw:
        props, geom = feat.get("properties") or {}, feat.get("geometry")
        if "LSOA21CD" not in props or not geom:
            raise SourceFormatChanged(f"Unexpected LSOA feature: {list(props)}")
        rows.append({"lsoa21": props["LSOA21CD"], "name": props.get("LSOA21NM"),
                     "lad_code": lad.get(props["LSOA21CD"]), "geojson": json.dumps(geom)})
    return rows


def load(ctx, rows) -> int:
    upsert(ctx.conn, "lsoa_boundaries", rows, ("lsoa21",))
    ctx.conn.commit()
    return len(rows)


def validate(ctx) -> list[str]:
    missing = ctx.conn.execute(
        "SELECT COUNT(DISTINCT lsoa21) FROM postcodes WHERE lsoa21 NOT IN (SELECT lsoa21 FROM lsoa_boundaries)").fetchone()[0]
    return [f"{missing} pool LSOAs have no boundary"] if missing else []
