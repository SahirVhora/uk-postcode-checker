"""B. School gate coordinates used for admission distances.

Solihull measures straight-line distance from the home's LLPG point to the
school's main pedestrian gate. Gate points live in data/seed/school_gates.csv,
which you verify by hand on the council map (docs/MANUAL_CHECKS.md).

If the CSV does not exist yet it is seeded from the council's own 'Nearest
Secondary Schools' / 'Nearest Primary and Junior Schools' layers (the layers the
TGA admission policy tells parents to use for distance checks), with
verified=0. Rows you have checked should be set to verified=1; they are never
overwritten.
"""

import csv
import logging
import re

from .. import SEED_DIR, SourceFormatChanged
from ..db import upsert
from ..discover import arcgis_query_all, webapp_layers_from_landing_page

NAME = "gates"
LICENCE = "Seed from Solihull Council online maps; verified by hand"
SEED_FILE = SEED_DIR / "school_gates.csv"
FIELDS = ["urn", "name", "lat", "lng", "verified", "source", "note"]
POINT_LAYERS = {"Primary": "Nearest Primary and Junior Schools", "Secondary": "Nearest Secondary Schools and Sixth Form Colleges"}

log = logging.getLogger(__name__)


def tokens(name: str) -> set[str]:
    stop = {"and", "the", "school", "academy", "sixth", "form", "primary", "of"}
    return {t for t in re.findall(r"[a-z]+", name.lower()) if t not in stop}


def seed_from_council(ctx) -> list[dict]:
    f = ctx.fetcher(NAME)
    _, layers = webapp_layers_from_landing_page(f, ctx.area["catchments"]["landing_page"])
    by_title = {l["title"]: l["url"] for l in layers}
    schools = ctx.area["target_schools"] + ctx.area.get("feeder_schools", [])
    rows = []
    for s in schools:
        phase = ctx.conn.execute("SELECT phase FROM schools WHERE urn=?", (s["urn"],)).fetchone()
        layer_title = POINT_LAYERS["Primary" if phase and phase[0] == "Primary" else "Secondary"]
        if layer_title not in by_title:
            raise SourceFormatChanged(f"Council web map has no '{layer_title}' layer")
        feats = arcgis_query_all(f, by_title[layer_title], "1=1", geometry=True)
        want = tokens(s["name"])
        match = [ft for ft in feats if want <= tokens(ft["attributes"].get("CONAME", ""))]
        match.sort(key=lambda ft: len(tokens(ft["attributes"]["CONAME"])))
        if not match:
            raise SourceFormatChanged(f"No point for '{s['name']}' in council layer '{layer_title}'")
        g = match[0]["geometry"]
        rows.append({
            "urn": s["urn"], "name": s["name"], "lat": round(g["y"], 6), "lng": round(g["x"], 6), "verified": 0,
            "source": f"Solihull online maps layer '{layer_title}' ({match[0]['attributes']['CONAME']})",
            "note": "UNVERIFIED: confirm this is the main pedestrian gate on solihull.gov.uk/onlinemaps",
        })
    return rows


def fetch(ctx):
    ctx.source_url = str(SEED_FILE.relative_to(SEED_DIR.parent.parent))
    if not SEED_FILE.exists():
        rows = seed_from_council(ctx)
        with open(SEED_FILE, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
        log.warning("created %s with %d UNVERIFIED gate points", SEED_FILE, len(rows))
    with open(SEED_FILE, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def parse(ctx, raw) -> list[dict]:
    out = []
    for r in raw:
        lat, lng = float(r["lat"]), float(r["lng"])
        if not (49 < lat < 61 and -8 < lng < 2):
            raise SourceFormatChanged(f"Gate for URN {r['urn']} is outside Great Britain: {lat},{lng}")
        out.append({"urn": int(r["urn"]), "name": r["name"], "lat": lat, "lng": lng,
                    "verified": int(r.get("verified") or 0), "source": r.get("source")})
    return out


def load(ctx, rows) -> int:
    upsert(ctx.conn, "school_gates", rows, ("urn",))
    ctx.conn.commit()
    return len(rows)


def validate(ctx) -> list[str]:
    unverified = [r["name"] for r in ctx.conn.execute("SELECT name FROM school_gates WHERE verified = 0")]
    return [f"Unverified gate coordinates: {', '.join(unverified)}"] if unverified else []
