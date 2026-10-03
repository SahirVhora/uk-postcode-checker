"""C. HM Land Registry Price Paid Data, yearly files for the last N years.

Yearly file links are discovered from the gov.uk Price Paid Data pages. Each
file is streamed once and only lines for the configured outcodes are cached
(byte-for-byte, unchanged), so offline rebuilds do not need the full files.

Record status: A = addition, C = change (replaces the earlier record), D = delete.
Category: A = standard price paid, B = additional (repossessions, buy-to-let,
non-private buyers). Default views use category A only.
"""

import csv
import io
import logging
import re

import requests

from .. import SourceFormatChanged
from ..db import upsert
from ..discover import govuk_content, govuk_links
from ..http import USER_AGENT

NAME = "ppd"
LICENCE = ("Contains HM Land Registry data (c) Crown copyright and database right. Licensed under the Open Government "
           "Licence v3.0. Address data: Royal Mail and Ordnance Survey permit personal/non-commercial display only.")
LANDING = "government/statistical-data-sets/price-paid-data-downloads"
COLUMNS = ["tid", "price", "date", "postcode", "property_type", "new_build", "tenure", "paon", "saon", "street",
           "locality", "town", "district", "county", "category", "record_status"]

log = logging.getLogger(__name__)


def yearly_urls(fetcher) -> dict[int, str]:
    links = govuk_links(govuk_content(fetcher, LANDING))
    yearly_page = next((u for u, t in links if re.search(r"price-paid-data-yearly-file", u)), None)
    if not yearly_page:
        raise SourceFormatChanged(f"No link to the yearly file page on gov.uk/{LANDING}")
    content = govuk_content(fetcher, yearly_page)
    urls = {}
    for u, _ in govuk_links(content):
        m = re.search(r"/pp-(\d{4})\.csv$", u)
        if m:
            urls[int(m.group(1))] = u
    if not urls:
        raise SourceFormatChanged(f"No pp-YYYY.csv links on {yearly_page}")
    return urls


def stream_filter(url: str, prefixes: tuple[str, ...]) -> bytes:
    """Download a yearly file and keep only lines whose postcode starts with one of prefixes."""
    kept = []
    with requests.get(url, stream=True, timeout=600, headers={"User-Agent": USER_AGENT}) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            # Postcode is the 4th quoted field: "{tid}","price","date","B90 3DF",...
            parts = line.split(b'","', 4)
            if len(parts) > 3 and parts[3].startswith(prefixes):
                kept.append(line)
    log.info("%s: kept %d lines", url, len(kept))
    return b"\n".join(kept) + (b"\n" if kept else b"")


def fetch(ctx):
    f = ctx.fetcher(NAME)
    urls = yearly_urls(f)
    years = sorted(urls)[-ctx.area["prices"]["ppd_years"]:]
    outcodes = ctx.area["outcodes"]
    prefixes = tuple(f"{oc} ".encode() for oc in outcodes)
    ctx.source_url = urls[years[-1]]
    out = []
    for y in years:
        name = f"pp-{y}-{'_'.join(outcodes)}.csv"
        out.append((y, urls[y], f.blob(name, lambda u=urls[y]: stream_filter(u, prefixes), url=urls[y])))
    ctx.notes.append(f"years {years[0]}-{years[-1]}")
    return out


def parse_lines(text: str) -> list[dict]:
    rows = []
    for rec in csv.reader(io.StringIO(text)):
        if not rec:
            continue
        if len(rec) != len(COLUMNS):
            raise SourceFormatChanged(f"PPD line has {len(rec)} fields, expected {len(COLUMNS)}: {rec[:4]}")
        r = dict(zip(COLUMNS, rec))
        r["tid"] = r["tid"].strip("{}")
        r["price"] = int(r["price"])
        r["date"] = r["date"][:10]
        rows.append(r)
    return rows


def apply_record_status(rows: list[dict]) -> tuple[dict, set]:
    """Apply A/C/D in file order. Returns (current records by tid, deleted tids)."""
    current, deleted = {}, set()
    for r in rows:
        status = r["record_status"]
        if status in ("A", "C"):
            current[r["tid"]] = r
            deleted.discard(r["tid"])
        elif status == "D":
            current.pop(r["tid"], None)
            deleted.add(r["tid"])
        else:
            raise SourceFormatChanged(f"Unknown PPD record status '{status}' for {r['tid']}")
    return current, deleted


def parse(ctx, raw):
    rows = []
    for _year, _url, blob in raw:
        rows.extend(parse_lines(blob.decode("utf-8", "replace")))
    current, deleted = apply_record_status(rows)
    return {"rows": list(current.values()), "deleted": deleted}


def load(ctx, parsed) -> int:
    conn = ctx.conn
    conn.executemany("DELETE FROM ppd WHERE tid = ?", [(t,) for t in parsed["deleted"]])
    upsert(conn, "ppd", parsed["rows"], ("tid",))
    conn.commit()
    return len(parsed["rows"])


def validate(ctx) -> list[str]:
    by_year = ctx.conn.execute("SELECT substr(date,1,4) y, COUNT(*), SUM(category='A') FROM ppd GROUP BY y ORDER BY y").fetchall()
    ctx.notes.append("sales by year (all/cat A): " + ", ".join(f"{y}={n}/{a}" for y, n, a in by_year))
    unmatched = ctx.conn.execute(
        "SELECT COUNT(*) FROM ppd WHERE postcode NOT IN (SELECT pcds FROM postcodes)").fetchone()[0]
    return [f"{unmatched} sales have postcodes not in the live ONSPD pool (terminated or new postcodes)"] if unmatched else []
