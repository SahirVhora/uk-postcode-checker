"""B. Schools: DfE Get Information About Schools (GIAS), all establishment data.

GIAS generates the bulk CSV on demand. The flow mirrors the public Downloads
page: read the 'All establishment data' form, submit it, poll until the file
is generated, then submit the download form. Field names are read from the page
so a layout change fails loudly instead of fetching the wrong file.
"""

import csv
import html as htmllib
import io
import json
import logging
import re
import time
import zipfile

import requests

from .. import SourceFormatChanged
from ..db import upsert
from ..geo import bng_to_wgs84, haversine_miles
from ..http import USER_AGENT

NAME = "gias"
LICENCE = "Open Government Licence v3.0"
BASE = "https://get-information-schools.service.gov.uk"
ALL_DATA_TAG = "all.edubase.data"

log = logging.getLogger(__name__)


def _form_fields(page: str, action: str) -> list[tuple[str, str]]:
    i = page.find(f'action="{action}"')
    if i < 0:
        raise SourceFormatChanged(f"GIAS page has no form posting to {action}")
    form = page[i:page.find("</form>", i)]
    fields = []
    for inp in re.findall(r"<input([^>]*)>", form):
        n = re.search(r'name="([^"]+)"', inp)
        v = re.search(r'value="([^"]*)"', inp)
        if n:
            fields.append((n.group(1), htmllib.unescape(v.group(1) if v else "")))
    return fields


def download_all_establishments() -> bytes:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    page = s.get(f"{BASE}/Downloads", timeout=120).text
    fields = _form_fields(page, "/Downloads/Collate")
    tags = [(n, v) for n, v in fields if n.endswith(".Tag")]
    index = next((n.split("]")[0] + "]" for n, v in tags if v == ALL_DATA_TAG), None)
    if not index:
        raise SourceFormatChanged(f"GIAS Downloads page has no '{ALL_DATA_TAG}' option. Tags: {[v for _, v in tags]}")
    data = [(n, v) for n, v in fields if not n.startswith("Downloads[") or n.startswith(index)]
    data = [(n, "true" if n == f"{index}.Selected" else v) for n, v in data]
    resp = s.post(f"{BASE}/Downloads/Collate", data=data, timeout=120)
    gen_id = resp.url.rstrip("/").rsplit("/", 1)[-1]
    if "/Generated/" not in resp.url:
        raise SourceFormatChanged(f"GIAS did not start generation (landed on {resp.url})")
    for _ in range(150):
        status = s.get(f"{BASE}/Downloads/GenerateAjax/{gen_id}", timeout=60).json()
        if isinstance(status, str):
            status = json.loads(status)
        if status.get("status"):
            break
        time.sleep(2)
    else:
        raise RuntimeError("GIAS file generation did not finish within 5 minutes")
    ready = s.get(BASE + status["redirect"], timeout=120).text
    extract = _form_fields(ready, "/Downloads/Download/Extract")
    resp = s.post(f"{BASE}/Downloads/Download/Extract", data=extract, timeout=600)
    if not resp.content.startswith(b"PK"):
        raise SourceFormatChanged(f"GIAS download is not a zip (content-type {resp.headers.get('content-type')})")
    return resp.content


def fetch(ctx):
    f = ctx.fetcher(NAME)
    ctx.source_url = f"{BASE}/Downloads (All establishment data)"
    return f.blob("all-establishment-data.zip", download_all_establishments, url=ctx.source_url)


def _col(header: list[str], *names: str) -> str:
    for n in names:
        if n in header:
            return n
    raise SourceFormatChanged(f"GIAS CSV has none of the columns {names}")


def parse(ctx, raw: bytes) -> list[dict]:
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        csvs = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not csvs:
            raise SourceFormatChanged(f"GIAS zip has no CSV: {zf.namelist()}")
        text = zf.read(csvs[0]).decode("cp1252", "replace")
    ctx.notes.append(f"file {csvs[0]}")
    reader = csv.DictReader(io.StringIO(text))
    h = reader.fieldnames or []
    c = {
        "urn": _col(h, "URN"), "name": _col(h, "EstablishmentName"),
        "phase": _col(h, "PhaseOfEducation (name)"), "type": _col(h, "TypeOfEstablishment (name)"),
        "status": _col(h, "EstablishmentStatus (name)"), "e": _col(h, "Easting"), "n": _col(h, "Northing"),
        "rel": _col(h, "ReligiousCharacter (name)"), "adm": _col(h, "AdmissionsPolicy (name)"),
        "la_code": _col(h, "LA (code)"), "la_name": _col(h, "LA (name)"), "pc": _col(h, "Postcode"),
    }
    pool = [(p["lat"], p["lng"]) for p in ctx.pool()]
    if not pool:
        raise RuntimeError("Load onspd before gias")
    lat0 = sum(p[0] for p in pool) / len(pool)
    lng0 = sum(p[1] for p in pool) / len(pool)
    radius = ctx.area["schools"]["radius_miles"]
    keep_urns = {s["urn"] for s in ctx.area["target_schools"] + ctx.area.get("feeder_schools", [])}
    rows = []
    for r in reader:
        if r[c["status"]] not in ("Open", "Open, but proposed to close"):
            continue
        if not r[c["e"]] or not r[c["n"]]:
            continue
        lat, lng = bng_to_wgs84(float(r[c["e"]]), float(r[c["n"]]))
        # Cheap prefilter on distance to the pool centre, then exact distance to nearest pool postcode.
        if haversine_miles(lat0, lng0, lat, lng) > radius + 6 and int(r[c["urn"]]) not in keep_urns:
            continue
        nearest = min(haversine_miles(lat, lng, p[0], p[1]) for p in pool)
        if nearest > radius and int(r[c["urn"]]) not in keep_urns:
            continue
        rows.append({
            "urn": int(r[c["urn"]]), "name": r[c["name"]], "phase": r[c["phase"]], "type": r[c["type"]],
            "status": r[c["status"]], "lat": round(lat, 6), "lng": round(lng, 6),
            "religious_character": r[c["rel"]], "admissions_policy": r[c["adm"]],
            "la_code": r[c["la_code"]], "la_name": r[c["la_name"]], "postcode": r[c["pc"]],
            "miles_from_pool": round(nearest, 3),
        })
    return rows


def load(ctx, rows) -> int:
    upsert(ctx.conn, "schools", rows, ("urn",))
    ctx.conn.commit()
    return len(rows)


def validate(ctx) -> list[str]:
    problems = []
    for s in ctx.area["target_schools"] + ctx.area.get("feeder_schools", []):
        row = ctx.conn.execute("SELECT name, status FROM schools WHERE urn=?", (s["urn"],)).fetchone()
        if not row:
            problems.append(f"URN {s['urn']} ({s['name']}) not found as an open school in GIAS")
            continue
        simple = lambda x: re.sub(r"[^a-z]", "", x.lower())
        if simple(s["name"])[:12] not in simple(row["name"]):
            problems.append(f"URN {s['urn']} is '{row['name']}' in GIAS, config says '{s['name']}'")
    by_phase = ctx.conn.execute("SELECT phase, COUNT(*) FROM schools GROUP BY phase").fetchall()
    ctx.notes.append("phases: " + ", ".join(f"{p}={n}" for p, n in by_phase))
    return problems
