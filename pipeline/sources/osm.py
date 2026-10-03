"""E. Community places from OpenStreetMap via the Overpass API.

Kinds: mosque (place_of_worship + religion=muslim), gurdwara (religion=sikh),
mandir (religion=hindu), halal (diet:halal=yes|only, or a shop/restaurant/
cafe/takeaway whose name contains 'halal').
"""

import json
import logging
import re

from .. import SourceFormatChanged
from ..db import upsert

NAME = "osm"
LICENCE = "(c) OpenStreetMap contributors, Open Database Licence (ODbL) 1.0"
OVERPASS = "https://overpass-api.de/api/interpreter"
FOOD = r"^(restaurant|fast_food|cafe|food_court)$"

log = logging.getLogger(__name__)


def build_query(bbox) -> str:
    s, w, n, e = bbox
    b = f"({s:.5f},{w:.5f},{n:.5f},{e:.5f})"
    return (
        "[out:json][timeout:120];("
        f'nwr["amenity"="place_of_worship"]["religion"~"^(muslim|sikh|hindu)$"]{b};'
        f'nwr["diet:halal"~"^(yes|only)$"]{b};'
        f'nwr["shop"]["name"~"halal",i]{b};'
        f'nwr["amenity"~"{FOOD}"]["name"~"halal",i]{b};'
        ");out center tags;"
    )


def classify(tags: dict) -> str | None:
    if tags.get("amenity") == "place_of_worship":
        return {"muslim": "mosque", "sikh": "gurdwara", "hindu": "mandir"}.get(tags.get("religion"))
    if tags.get("diet:halal") in ("yes", "only"):
        return "halal"
    if "halal" in (tags.get("name") or "").lower() and (tags.get("shop") or re.match(FOOD, tags.get("amenity") or "")):
        return "halal"
    return None


def fetch(ctx):
    pool = ctx.pool()
    pad_lat = ctx.area["osm"]["radius_miles"] / 69.0
    pad_lng = pad_lat / 0.61  # cos(52.4 deg)
    bbox = (min(p["lat"] for p in pool) - pad_lat, min(p["lng"] for p in pool) - pad_lng,
            max(p["lat"] for p in pool) + pad_lat, max(p["lng"] for p in pool) + pad_lng)
    ctx.source_url = OVERPASS
    # Overpass answers 406/429/504 when busy; POST is recommended for long queries.
    f = ctx.fetcher(NAME, extra_retry=(406, 503))
    data = json.loads(f.post(OVERPASS, data={"data": build_query(bbox)}, timeout=180))
    if "elements" not in data:
        raise SourceFormatChanged(f"Overpass response has no elements: {str(data)[:200]}")
    return data["elements"]


def parse(ctx, raw) -> list[dict]:
    rows = []
    for el in raw:
        tags = el.get("tags") or {}
        kind = classify(tags)
        lat = el.get("lat", (el.get("center") or {}).get("lat"))
        lng = el.get("lon", (el.get("center") or {}).get("lon"))
        if not kind or lat is None:
            continue
        rows.append({"osm_key": f"{el['type']}/{el['id']}", "kind": kind, "name": tags.get("name"),
                     "lat": float(lat), "lng": float(lng)})
    return rows


def load(ctx, rows) -> int:
    upsert(ctx.conn, "osm_pois", rows, ("osm_key",))
    ctx.conn.commit()
    return len(rows)


def validate(ctx) -> list[str]:
    kinds = dict(ctx.conn.execute("SELECT kind, COUNT(*) FROM osm_pois GROUP BY kind").fetchall())
    ctx.notes.append(", ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
    return [f"no {k} found in OSM within the search area" for k in ("mosque", "gurdwara", "mandir", "halal") if not kinds.get(k)]
