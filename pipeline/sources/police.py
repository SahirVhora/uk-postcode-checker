"""D. Street-level crime from the data.police.uk API, last N available months.

Area: the bounding box of the borough's LSOAs plus the pool's LSOAs (so the
borough median can be computed). Each month is fetched with a custom polygon;
when the API answers 503 (more than 10,000 crimes) the box is split into four
and retried, recursively. The API does not return an LSOA code, so each point
is assigned to an LSOA by point-in-polygon against ONS LSOA 2021 boundaries.
Crime locations are anonymised by the police (snapped to nearby map points).
"""

import json
import logging

from .. import SourceFormatChanged
from ..db import upsert
from ..geo import PolygonIndex, bbox_poly_param, split_bbox
from ..http import HTTPStatusError

NAME = "police"
LICENCE = "data.police.uk, Open Government Licence v3.0"
API = "https://data.police.uk/api"
MIN_SPAN = 0.004  # degrees; stop splitting below roughly 400 m

log = logging.getLogger(__name__)


def months_available(fetcher, n: int) -> list[str]:
    dates = fetcher.get_json(f"{API}/crimes-street-dates")
    months = sorted({d["date"] for d in dates if "date" in d}, reverse=True)
    if not months:
        raise SourceFormatChanged("crimes-street-dates returned no months")
    return months[:n]


def fetch_tile(fetcher, bbox, month, depth=0) -> list[dict]:
    try:
        body = fetcher.get(f"{API}/crimes-street/all-crime", params={"poly": bbox_poly_param(bbox), "date": month},
                           allowed_statuses=(503,))
    except HTTPStatusError as exc:
        if exc.status != 503:
            raise
        if bbox[2] - bbox[0] < MIN_SPAN:
            raise SourceFormatChanged(f"Police API still over the result cap for a tiny tile {bbox} {month}")
        log.info("tile too dense (%s, depth %d), splitting", month, depth)
        return [c for sub in split_bbox(bbox) for c in fetch_tile(fetcher, sub, month, depth + 1)]
    return json.loads(body)


def area_bbox(conn) -> tuple:
    from shapely.ops import unary_union
    from ..geo import geojson_to_shape
    shapes = [geojson_to_shape(r[0]) for r in conn.execute("SELECT geojson FROM lsoa_boundaries")]
    if not shapes:
        raise RuntimeError("Run lsoa_boundaries before police")
    minx, miny, maxx, maxy = unary_union(shapes).bounds
    return (miny, minx, maxy, maxx)


def fetch(ctx):
    f = ctx.fetcher(NAME, min_interval=0.1)  # API limit is 15 requests/second
    months = months_available(f, ctx.area["crime"]["months"])
    bbox = area_bbox(ctx.conn)
    ctx.source_url = f"{API}/crimes-street/all-crime"
    ctx.notes.append(f"months {months[-1]} to {months[0]}")
    out = []
    for month in months:
        crimes = fetch_tile(f, bbox, month)
        log.info("%s: %d crimes in area box", month, len(crimes))
        out.extend(crimes)
    return out


def parse(ctx, raw) -> list[dict]:
    index = PolygonIndex({r["lsoa21"]: [r["geojson"]] for r in ctx.conn.execute("SELECT lsoa21, geojson FROM lsoa_boundaries")})
    rows = {}
    for c in raw:
        loc = c.get("location") or {}
        try:
            lat, lng = float(loc["latitude"]), float(loc["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        inside = index.containing(lat, lng)
        if not inside:
            continue  # outside the borough and pool LSOAs
        key = str(c.get("id") or c.get("persistent_id"))
        rows[key] = {"crime_key": key, "category": c["category"], "month": c["month"], "lat": lat, "lng": lng,
                     "street": (loc.get("street") or {}).get("name"), "lsoa21": inside[0]}
    return list(rows.values())


def load(ctx, rows) -> int:
    upsert(ctx.conn, "crimes", rows, ("crime_key",))
    ctx.conn.commit()
    return len(rows)


def validate(ctx) -> list[str]:
    per_month = ctx.conn.execute("SELECT month, COUNT(*) FROM crimes GROUP BY month ORDER BY month").fetchall()
    ctx.notes.append("per month: " + ", ".join(f"{m}={n}" for m, n in per_month))
    empty = [m for m, n in per_month if n == 0]
    return [f"months with no crimes: {empty}"] if empty else []
