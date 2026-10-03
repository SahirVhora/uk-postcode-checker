"""E. Census 2021 via the Nomis API: ethnic group (TS021), religion (TS030), usual residents (TS001).

Dataset IDs and category codes are looked up in the Nomis catalogue at run time.
Counts are stored at Output Area and LSOA level for every local authority in
the pool plus the borough used for comparisons.
"""

import csv
import io
import logging

from .. import SourceFormatChanged
from ..db import upsert
from ..discover import NOMIS_API, nomis_codelist, nomis_dataset_id, nomis_dimension_name

NAME = "census"
LICENCE = "Office for National Statistics, Census 2021 via Nomis. Open Government Licence v3.0"

# table -> (dimension prefix, {our category: description suffix to match})
TABLES = {
    "TS021": ("C2021_ETH", {
        "total": "Total: All usual residents",
        "asian": "Asian, Asian British or Asian Welsh",
        "indian": "Asian, Asian British or Asian Welsh: Indian",
        "pakistani": "Asian, Asian British or Asian Welsh: Pakistani",
        "bangladeshi": "Asian, Asian British or Asian Welsh: Bangladeshi",
        "chinese": "Asian, Asian British or Asian Welsh: Chinese",
        "other_asian": "Asian, Asian British or Asian Welsh: Other Asian",
    }),
    "TS030": ("C2021_RELIGION", {
        "total": "Total: All usual residents",
        "muslim": "Muslim", "sikh": "Sikh", "hindu": "Hindu", "christian": "Christian", "no_religion": "No religion",
    }),
    "TS001": ("C2021_RESTYPE", {"total": "Total: All usual residents"}),
}
GEO_TYPES = {"TYPE150": "OA", "TYPE151": "LSOA"}
PAGE = 25000

log = logging.getLogger(__name__)


def fetch(ctx):
    f = ctx.fetcher(NAME)
    lads = sorted(set(ctx.pool_lads()) | {ctx.borough_lad()})
    out = []
    for table, (dim_prefix, wanted) in TABLES.items():
        ds = nomis_dataset_id(f, table)
        dim = nomis_dimension_name(f, ds, dim_prefix)
        codes = nomis_codelist(f, ds, dim.lower())
        by_desc = {v: k for k, v in codes.items()}
        missing = [d for d in wanted.values() if d not in by_desc]
        if missing:
            raise SourceFormatChanged(f"Nomis {table} has no categories {missing}")
        code_to_cat = {by_desc[desc]: cat for cat, desc in wanted.items()}
        for lad in lads:
            for geo_type in GEO_TYPES:
                offset = 0
                while True:
                    params = {"geography": f"{lad}{geo_type}", dim.lower(): ",".join(code_to_cat),
                              "measures": "20100", "select": f"geography_code,{dim.lower()},obs_value",
                              "recordoffset": offset, "recordlimit": PAGE}
                    text = f.get_text(f"{NOMIS_API}/dataset/{ds}.data.csv", params=params)
                    rows = list(csv.DictReader(io.StringIO(text)))
                    for r in rows:
                        out.append({"table": table, "geo_type": GEO_TYPES[geo_type], "geo": r["GEOGRAPHY_CODE"],
                                    "cat": code_to_cat.get(r[dim.upper()]), "count": int(float(r["OBS_VALUE"]))})
                    if len(rows) < PAGE:
                        break
                    offset += PAGE
        ctx.source_url = f"{NOMIS_API}/dataset/{ds}"
    ctx.notes.append(f"local authorities: {', '.join(lads)}")
    return out


def parse(ctx, raw) -> list[dict]:
    totals = {(r["geo"], r["table"]): r["count"] for r in raw if r["cat"] == "total"}
    rows = []
    for r in raw:
        if r["cat"] is None:
            raise SourceFormatChanged(f"Unexpected Nomis category in {r}")
        total = totals.get((r["geo"], r["table"]))
        rows.append({"geo_code": r["geo"], "geo_type": r["geo_type"], "table_id": r["table"], "category": r["cat"],
                     "count": r["count"], "pct": round(100 * r["count"] / total, 2) if total else None})
    return rows


def load(ctx, rows) -> int:
    upsert(ctx.conn, "census", rows, ("geo_code", "table_id", "category"))
    ctx.conn.commit()
    return len(rows)


def validate(ctx) -> list[str]:
    missing = ctx.conn.execute(
        "SELECT COUNT(*) FROM postcodes p WHERE NOT EXISTS (SELECT 1 FROM census c WHERE c.geo_code = p.oa21 AND c.table_id='TS021')"
    ).fetchone()[0]
    return [f"{missing} pool postcodes have no OA-level census data"] if missing else []
