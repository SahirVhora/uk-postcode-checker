"""B. School catchments from Solihull Council's online maps (ArcGIS).

Discovery chain: council landing page -> ArcGIS web app -> web map -> layer by title.
Polygons are stored ONLY in the local DB and cache. Only per-postcode booleans
leave this machine (via export.py).

Catchment features overlap: the council publishes shared zones as separate
features (for example one area is in both the Tudor Grange and Light Hall
catchments), so features are unioned per school and a postcode can belong to
several catchments.
"""

import json
import logging

from .. import SourceFormatChanged
from ..db import upsert
from ..discover import arcgis_query_all, webapp_layers_from_landing_page
from ..geo import PolygonIndex

NAME = "catchments"
LICENCE = "Solihull Metropolitan Borough Council online maps. Used locally for personal reference only; boundaries are not republished."

log = logging.getLogger(__name__)


def fetch(ctx):
    cfg = ctx.area["catchments"]
    f = ctx.fetcher(NAME)
    map_id, layers = webapp_layers_from_landing_page(f, cfg["landing_page"])
    wanted = {"secondary": cfg["secondary_layer_title"], "primary": cfg.get("primary_layer_title")}
    found = {}
    for key, title in wanted.items():
        if not title:
            continue
        match = [lyr for lyr in layers if lyr["title"].strip().lower() == title.strip().lower()]
        if not match:
            if key == "secondary":
                raise SourceFormatChanged(
                    f"Layer '{title}' not found in web map {map_id}. Layers present: {[l['title'] for l in layers]}. "
                    "Stop: do not guess catchment boundaries.")
            log.warning("optional layer '%s' not found", title)
            continue
        found[key] = match[0]["url"]
        log.info("catchment layer %s -> %s", key, found[key])
    ctx.source_url = found["secondary"]
    out = {}
    for key, url in found.items():
        out[key] = {"url": url, "features": arcgis_query_all(f, url, "1=1", geometry=True, fmt="geojson")}
    return out


def parse(ctx, raw) -> list[dict]:
    name_field = ctx.area["catchments"]["school_name_field"]
    rows = []
    for layer, payload in raw.items():
        for i, feat in enumerate(payload["features"]):
            props = feat.get("properties") or {}
            geom = feat.get("geometry")
            if name_field not in props:
                raise SourceFormatChanged(f"Catchment layer {layer} has no '{name_field}' attribute. Attributes: {list(props)}")
            if not geom or geom.get("type") not in ("Polygon", "MultiPolygon"):
                raise SourceFormatChanged(f"Catchment feature in {layer} is not a polygon: {str(geom)[:100]}")
            rows.append({
                "layer": layer,
                "school_name": str(props[name_field]).strip(),
                "feature_id": int(props.get("FID", feat.get("id", i))),
                "geojson": json.dumps(geom),
                "source_url": payload["url"],
            })
    return rows


def assign(conn, target_names: list[str]) -> None:
    """Recompute postcode_catchments and postcodes.in_target_catchment from stored polygons."""
    grouped: dict[tuple[str, str], list] = {}
    for r in conn.execute("SELECT layer, school_name, geojson FROM catchment_polygons"):
        grouped.setdefault((r["layer"], r["school_name"]), []).append(r["geojson"])
    index = PolygonIndex({f"{layer}|{school}": gs for (layer, school), gs in grouped.items()})
    conn.execute("DELETE FROM postcode_catchments")
    links, flags = [], []
    targets = {f"secondary|{n}" for n in target_names}
    for p in conn.execute("SELECT pcds, lat, lng FROM postcodes"):
        inside = index.containing(p["lat"], p["lng"])
        for key in inside:
            layer, school = key.split("|", 1)
            links.append({"pcds": p["pcds"], "layer": layer, "school_name": school})
        flags.append((1 if targets.intersection(inside) else 0, p["pcds"]))
    upsert(conn, "postcode_catchments", links, ("pcds", "layer", "school_name"))
    conn.executemany("UPDATE postcodes SET in_target_catchment = ? WHERE pcds = ?", flags)
    conn.commit()


def load(ctx, rows) -> int:
    ctx.conn.execute("DELETE FROM catchment_polygons")
    upsert(ctx.conn, "catchment_polygons", rows, ("layer", "feature_id"))
    assign(ctx.conn, [s["catchment_name"] for s in ctx.target_schools()])
    return len(rows)


def validate(ctx) -> list[str]:
    conn = ctx.conn
    names = {r[0] for r in conn.execute("SELECT DISTINCT school_name FROM catchment_polygons WHERE layer='secondary'")}
    missing = [s["catchment_name"] for s in ctx.target_schools() if s["catchment_name"] not in names]
    if missing:
        raise SourceFormatChanged(f"Target catchments {missing} not in council layer. Names present: {sorted(names)}")
    problems = []
    for s in ctx.target_schools():
        n = conn.execute("SELECT COUNT(*) FROM postcode_catchments WHERE layer='secondary' AND school_name=?",
                         (s["catchment_name"],)).fetchone()[0]
        ctx.notes.append(f"{s['name']}: {n} pool postcodes in catchment")
        if n == 0:
            problems.append(f"No pool postcodes fall in the {s['name']} catchment; check the outcodes in config/area.yaml")
    total = conn.execute("SELECT SUM(in_target_catchment), COUNT(*) FROM postcodes").fetchone()
    ctx.notes.append(f"in_target_catchment: {total[0]}/{total[1]}")
    return problems
