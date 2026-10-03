"""B. DfE school performance tables (KS2 and KS4) from Compare school performance.

The service's firewall refuses non-browser clients, and this pipeline does not
impersonate a browser. So the official download ZIPs are imported from
data/manual/performance/ after you download them in a browser (see
docs/MANUAL_CHECKS.md). The pipeline first makes one honest request; if the
service refuses it, it stops with exact instructions instead of guessing.

Progress 8 was not published for some recent years. Those values (NA, NE,
SUPP, ...) are stored as NULL with the raw code kept, never as 0.
"""

import csv
import io
import logging
import re
import zipfile
from pathlib import Path

from .. import REPO_ROOT, ManualInputNeeded, SourceFormatChanged
from ..db import upsert
from ..http import HTTPStatusError

NAME = "performance"
LICENCE = "Open Government Licence v3.0"
SERVICE = "https://www.compare-school-performance.service.gov.uk/download-data"
MANUAL_DIR = REPO_ROOT / "data" / "manual" / "performance"

METRICS = {
    "KS2": ["PTRWM_EXP", "PTRWM_HIGH", "READ_AVERAGE", "MAT_AVERAGE", "GPS_AVERAGE", "TELIG"],
    "KS4": ["ATT8SCR", "P8MEA", "PTL2BASICS_95", "PTEBACC_E_PTQ_EE", "EBACCAPS", "TPUP"],
}
FILE_RE = re.compile(r"(\d{4}-\d{4})/(\d+)_(ks2|ks4)(final|prov|provisional)?\.csv$", re.I)

log = logging.getLogger(__name__)


def parse_value(raw: str | None) -> float | None:
    """'65.40%' -> 65.4; suppression and 'not published' codes -> None."""
    v = (raw or "").strip().rstrip("%")
    try:
        return float(v)
    except ValueError:
        return None


def manual_files() -> list[Path]:
    return sorted(MANUAL_DIR.glob("*.zip")) if MANUAL_DIR.exists() else []


def instructions(ctx) -> str:
    las = sorted({r[0] for r in ctx.conn.execute("SELECT DISTINCT la_name FROM schools WHERE la_name IS NOT NULL")})
    years = ctx.area["schools"]["performance_years"]
    return (
        f"Download KS2 + KS4 results in a browser from {SERVICE}: for each of the latest {years} years, choose "
        f"'Local authority' for each of {', '.join(las)}, tick 'Key stage 2 results (final)' and 'Key stage 4 results (final)', "
        f"then 'Data in CSV format'. Save the ZIPs (unchanged) into {MANUAL_DIR.relative_to(REPO_ROOT)}/ and re-run "
        "python -m pipeline.run --sources performance"
    )


def fetch(ctx):
    files = manual_files()
    ctx.source_url = SERVICE
    if files:
        ctx.notes.append(f"imported {len(files)} manually downloaded ZIP(s)")
        return [(p.name, p.read_bytes()) for p in files]
    if not ctx.offline:
        try:
            ctx.fetcher(NAME).get(SERVICE, use_cache=False)
        except HTTPStatusError as exc:
            raise ManualInputNeeded(f"{SERVICE} refused automated access (HTTP {exc.status}). {instructions(ctx)}")
    raise ManualInputNeeded(instructions(ctx))


def parse(ctx, raw) -> list[dict]:
    wanted = {r[0] for r in ctx.conn.execute("SELECT urn FROM schools")}
    found: dict[tuple, dict] = {}
    for name, blob in raw:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            for member in zf.namelist():
                m = FILE_RE.search(member)
                if not m:
                    continue
                year, stage = m.group(1), m.group(3).upper()
                text = zf.read(member).decode("cp1252", "replace")
                reader = csv.DictReader(io.StringIO(text))
                header = reader.fieldnames or []
                if "URN" not in header:
                    raise SourceFormatChanged(f"{name}:{member} has no URN column")
                missing = [c for c in METRICS[stage] if c not in header]
                if missing:
                    log.warning("%s:%s missing columns %s (stored as not published)", name, member, missing)
                for rec in reader:
                    if not (rec.get("URN") or "").isdigit() or int(rec["URN"]) not in wanted:
                        continue
                    for metric in METRICS[stage]:
                        raw_v = rec.get(metric)
                        found[(int(rec["URN"]), year, stage, metric)] = {
                            "urn": int(rec["URN"]), "year": year, "key_stage": stage, "metric": metric,
                            "value": parse_value(raw_v), "raw": raw_v if raw_v is not None else "column not in file",
                        }
    if not found:
        raise SourceFormatChanged("No KS2/KS4 rows for pool schools in the supplied ZIPs. Check they are the CSV downloads.")
    keep_years = sorted({k[1] for k in found}, reverse=True)[: ctx.area["schools"]["performance_years"]]
    ctx.notes.append(f"years kept: {', '.join(keep_years)}")
    return [r for k, r in found.items() if k[1] in keep_years]


def load(ctx, rows) -> int:
    upsert(ctx.conn, "performance", rows, ("urn", "year", "key_stage", "metric"))
    ctx.conn.commit()
    return len(rows)


def validate(ctx) -> list[str]:
    problems = []
    for s in ctx.area["target_schools"]:
        n = ctx.conn.execute("SELECT COUNT(*) FROM performance WHERE urn=? AND key_stage='KS4'", (s["urn"],)).fetchone()[0]
        if not n:
            problems.append(f"No KS4 results for {s['name']} (URN {s['urn']}) in the imported files")
    return problems
