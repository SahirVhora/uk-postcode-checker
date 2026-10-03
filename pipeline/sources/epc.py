"""C. EPC domestic certificates from MHCLG 'Get energy performance of buildings data'.

The old opendatacommunities API now redirects to get-energy-performance-data.
communities.gov.uk. Two routes are supported:

1. API: set EPC_API_TOKEN in .env (bearer token from your account page after
   signing in with GOV.UK One Login). For each pool postcode the domestic
   search lists certificates; the latest certificate per property is then
   fetched in full for floor area and habitable rooms.
2. Bulk CSV: download the domestic CSV for the relevant councils from the
   service and save it under data/manual/epc/. Column names are matched
   case-insensitively so both the old and new CSV layouts work.
"""

import csv
import io
import json
import logging
import zipfile
from pathlib import Path

from .. import REPO_ROOT, ManualInputNeeded, SourceFormatChanged
from ..db import upsert
from ..http import HTTPStatusError

NAME = "epc"
LICENCE = ("Open Government Licence v3.0 for EPC data; address fields are subject to Royal Mail and Ordnance Survey "
           "rights (see the service licensing guidance). Used for local matching only, addresses are not published.")
API = "https://api.get-energy-performance-data.communities.gov.uk"
SERVICE = "https://get-energy-performance-data.communities.gov.uk/"
MANUAL_DIR = REPO_ROOT / "data" / "manual" / "epc"

PROPERTY_TYPE = {"0": "House", "1": "Bungalow", "2": "Flat", "3": "Maisonette", "4": "Park home"}
BUILT_FORM = {"1": "Detached", "2": "Semi-Detached", "3": "End-Terrace", "4": "Mid-Terrace",
              "5": "Enclosed End-Terrace", "6": "Enclosed Mid-Terrace"}
CSV_ALIASES = {
    "cert_number": ["lmk_key", "certificate_number", "certificatenumber"],
    "uprn": ["uprn"],
    "address1": ["address1", "address_line_1", "addressline1"],
    "address2": ["address2", "address_line_2", "addressline2"],
    "address3": ["address3", "address_line_3", "addressline3"],
    "postcode": ["postcode"],
    "registration_date": ["lodgement_date", "registration_date", "registrationdate", "inspection_date"],
    "total_floor_area": ["total_floor_area"],
    "habitable_rooms": ["number_habitable_rooms", "habitable_room_count"],
    "property_type": ["property_type"],
    "built_form": ["built_form"],
    "energy_band": ["current_energy_rating", "current_energy_efficiency_band"],
    "construction_age_band": ["construction_age_band"],
}

log = logging.getLogger(__name__)


def find_key(obj, key):
    """Depth-first search for the first value under key in nested dicts/lists."""
    if isinstance(obj, dict):
        if key in obj and not isinstance(obj[key], (dict, list)):
            return obj[key]
        if key in obj and isinstance(obj[key], dict) and "value" in obj[key]:
            return obj[key]["value"]
        for v in obj.values():
            found = find_key(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = find_key(v, key)
            if found is not None:
                return found
    return None


def from_certificate(cert_number: str, payload: dict) -> dict:
    """Extract the fields we need from a full certificate JSON (schemas vary by version)."""
    d = payload.get("data", payload)
    ptype = find_key(d, "property_type")
    bform = find_key(d, "built_form")
    rooms = find_key(d, "habitable_room_count") or find_key(d, "number_habitable_rooms")
    area = find_key(d, "total_floor_area")
    return {
        "cert_number": cert_number,
        "uprn": str(find_key(d, "uprn") or "") or None,
        "address1": find_key(d, "address_line_1"), "address2": find_key(d, "address_line_2"),
        "address3": find_key(d, "address_line_3"),
        "postcode": (find_key(d, "postcode") or "").upper() or None,
        "registration_date": find_key(d, "registration_date"),
        "total_floor_area": float(area) if area not in (None, "") else None,
        "habitable_rooms": int(rooms) if str(rooms or "").isdigit() else None,
        "property_type": PROPERTY_TYPE.get(str(ptype), ptype if ptype not in (None, "") else None),
        "built_form": BUILT_FORM.get(str(bform), bform if bform not in (None, "") else None),
        "energy_band": find_key(d, "current_energy_efficiency_band"),
        "construction_age_band": find_key(d, "construction_age_band"),
        "schema": find_key(d, "schema_type") or find_key(d, "assessment_type"),
    }


def from_csv_rows(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    header = {h.lower().strip(): h for h in (reader.fieldnames or [])}
    cols = {}
    for field, aliases in CSV_ALIASES.items():
        cols[field] = next((header[a] for a in aliases if a in header), None)
    for need in ("cert_number", "postcode", "total_floor_area"):
        if not cols[need]:
            raise SourceFormatChanged(f"EPC CSV has no column for {need}. Columns: {list(header)}")
    out = []
    for r in reader:
        g = lambda f: (r.get(cols[f]) or "").strip() if cols[f] else ""
        area, rooms = g("total_floor_area"), g("habitable_rooms")
        out.append({
            "cert_number": g("cert_number"), "uprn": g("uprn") or None,
            "address1": g("address1") or None, "address2": g("address2") or None, "address3": g("address3") or None,
            "postcode": g("postcode").upper() or None, "registration_date": g("registration_date")[:10] or None,
            "total_floor_area": float(area) if area else None,
            "habitable_rooms": int(float(rooms)) if rooms.replace(".", "", 1).isdigit() else None,
            "property_type": g("property_type") or None, "built_form": g("built_form") or None,
            "energy_band": g("energy_band") or None, "construction_age_band": g("construction_age_band") or None,
            "schema": "bulk-csv",
        })
    return out


def manual_files() -> list[Path]:
    if not MANUAL_DIR.exists():
        return []
    return sorted(p for p in MANUAL_DIR.iterdir() if p.suffix.lower() in (".csv", ".zip"))


def fetch(ctx):
    files = manual_files()
    if files:
        ctx.source_url = f"{SERVICE} (bulk CSV import)"
        ctx.notes.append(f"imported {len(files)} bulk file(s)")
        return {"mode": "csv", "files": [(p.name, p.read_bytes()) for p in files]}
    token = ctx.env.get("EPC_API_TOKEN")
    if not token:
        raise ManualInputNeeded(
            "No EPC data: set EPC_API_TOKEN in .env (sign in at "
            f"{SERVICE} with GOV.UK One Login, copy the bearer token from 'My account'), or save the domestic bulk CSV "
            f"for Solihull and neighbouring councils into {MANUAL_DIR.relative_to(REPO_ROOT)}/.")
    ctx.source_url = f"{API}/api/domestic/search"
    f = ctx.fetcher(NAME, min_interval=0.06)  # 6000 requests per 5 minutes
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"} if token else {}
    latest = {}
    for p in ctx.pool():
        try:
            body = f.get(f"{API}/api/domestic/search", params={"postcode": p["pcds"], "page_size": 5000},
                         headers=headers, allowed_statuses=(404,))
        except HTTPStatusError as exc:
            if exc.status == 404:
                continue  # no certificates for this postcode
            if exc.status in (401, 403):
                raise ManualInputNeeded(f"EPC API rejected the token (HTTP {exc.status}); refresh EPC_API_TOKEN in .env")
            raise
        for c in json.loads(body).get("data", []):
            prop = c.get("uprn") or f"{c.get('postcode')}|{c.get('addressLine1')}|{c.get('addressLine2')}"
            if prop not in latest or (c.get("registrationDate") or "") > (latest[prop].get("registrationDate") or ""):
                latest[prop] = c
    certs = []
    for c in latest.values():
        num = c["certificateNumber"]
        payload = f.get_json(f"{API}/api/certificate", params={"certificate_number": num}, headers=headers)
        certs.append(from_certificate(num, payload))
    return {"mode": "api", "certs": certs}


def parse(ctx, raw) -> list[dict]:
    if raw["mode"] == "api":
        return raw["certs"]
    pool = {r["pcds"] for r in ctx.pool()}
    rows = []
    for name, blob in raw["files"]:
        if name.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                texts = [zf.read(m).decode("utf-8-sig", "replace") for m in zf.namelist()
                         if m.lower().endswith(".csv") and "recommend" not in m.lower()]
        else:
            texts = [blob.decode("utf-8-sig", "replace")]
        for t in texts:
            rows.extend(r for r in from_csv_rows(t) if r["postcode"] in pool)
    # keep the latest certificate per property
    latest = {}
    for r in rows:
        prop = r["uprn"] or f"{r['postcode']}|{r['address1']}|{r['address2']}"
        if prop not in latest or (r["registration_date"] or "") > (latest[prop]["registration_date"] or ""):
            latest[prop] = r
    return list(latest.values())


def load(ctx, rows) -> int:
    upsert(ctx.conn, "epc", rows, ("cert_number",))
    ctx.conn.commit()
    from ..matching import match_all
    rate = match_all(ctx.conn)
    ctx.notes.append(f"PPD to EPC match rate {rate:.1%}")
    return len(rows)


def validate(ctx) -> list[str]:
    n = ctx.conn.execute("SELECT COUNT(*), SUM(total_floor_area IS NULL), SUM(habitable_rooms IS NULL) FROM epc").fetchone()
    ctx.notes.append(f"{n[0]} certificates, {n[1]} without floor area, {n[2]} without habitable rooms")
    return []
