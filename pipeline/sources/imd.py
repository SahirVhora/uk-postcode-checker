"""D. English Indices of Deprivation: the latest release published on gov.uk.

The newest 'English indices of deprivation YYYY' statistics page is found by
checking gov.uk from the current year downwards; the 'File 7' all-ranks CSV is
taken from it. Columns are matched by name pattern. Decile 1 = most deprived.
"""

import csv
import io
import logging
import re
from datetime import date

from .. import SourceFormatChanged
from ..db import upsert
from ..discover import govuk_content, govuk_links
from ..http import HTTPStatusError, OfflineCacheMiss

NAME = "imd"
LICENCE = "Ministry of Housing, Communities and Local Government. Open Government Licence v3.0"
COLS = {
    "lsoa21": r"^LSOA code \(2021\)$",
    "lad_code": r"^Local Authority District code",
    "imd_rank": r"^Index of Multiple Deprivation \(IMD\) Rank",
    "imd_decile": r"^Index of Multiple Deprivation \(IMD\) Decile",
    "income_decile": r"^Income Decile",
    "crime_decile": r"^Crime Decile",
    "living_env_decile": r"^Living Environment Decile",
    "education_decile": r"^Education.*Skills and Training Decile",
}

log = logging.getLogger(__name__)


def fetch(ctx):
    f = ctx.fetcher(NAME)
    for year in range(date.today().year, 2014, -1):
        try:
            # 404s are cached too, so an offline rebuild replays the same year probe.
            content = govuk_content(f, f"government/statistics/english-indices-of-deprivation-{year}",
                                    allowed_statuses=(404,))
        except HTTPStatusError as exc:
            if exc.status == 404:
                continue
            raise
        except OfflineCacheMiss:
            continue  # offline: a year that was never probed online (for example a later calendar year)
        links = govuk_links(content)
        url = next((u for u, t in links if re.search(r"File_?7", u, re.I) and u.lower().endswith(".csv")), None)
        if not url:
            raise SourceFormatChanged(f"IoD {year} page has no File 7 CSV")
        log.info("IoD%d File 7: %s", year, url)
        ctx.source_url = url
        return {"release": f"IoD{year}", "body": f.get(url)}
    raise SourceFormatChanged("No English indices of deprivation release found on gov.uk")


def parse(ctx, raw) -> list[dict]:
    reader = csv.reader(io.StringIO(raw["body"].decode("utf-8-sig", "replace")))
    header = [re.sub(r"\s+", " ", h).strip() for h in next(reader)]
    idx = {}
    for key, pat in COLS.items():
        hits = [i for i, h in enumerate(header) if re.search(pat, h)]
        if not hits:
            raise SourceFormatChanged(f"IoD file has no column matching /{pat}/")
        idx[key] = hits[0]
    keep_lads = set(ctx.pool_lads()) | {ctx.borough_lad()}
    keep_lsoas = {r[0] for r in ctx.conn.execute("SELECT DISTINCT lsoa21 FROM postcodes")}
    rows = []
    for rec in reader:
        if not rec:
            continue
        if rec[idx["lad_code"]] not in keep_lads and rec[idx["lsoa21"]] not in keep_lsoas:
            continue
        row = {"lsoa21": rec[idx["lsoa21"]], "release": raw["release"], "lad_code": rec[idx["lad_code"]]}
        for key in COLS:
            if key not in ("lsoa21", "lad_code"):
                row[key] = int(float(rec[idx[key]]))
        rows.append(row)
    return rows


def load(ctx, rows) -> int:
    upsert(ctx.conn, "imd", rows, ("lsoa21",))
    ctx.conn.commit()
    return len(rows)


def validate(ctx) -> list[str]:
    missing = ctx.conn.execute(
        "SELECT COUNT(DISTINCT lsoa21) FROM postcodes WHERE lsoa21 NOT IN (SELECT lsoa21 FROM imd)").fetchone()[0]
    release = ctx.conn.execute("SELECT DISTINCT release FROM imd").fetchall()
    ctx.notes.append(f"release {', '.join(r[0] for r in release)}")
    return [f"{missing} pool LSOAs have no IMD row"] if missing else []
