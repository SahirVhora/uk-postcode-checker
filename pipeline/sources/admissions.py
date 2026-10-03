"""B. Secondary admissions history from Solihull Council PDFs.

Two kinds of evidence are parsed with pdfplumber:

* 'How secondary places were offered' table: last priority and distance on
  national offer day, three intake years, every Solihull secondary school.
  Stored with entry_point = 'national_offer_day'.
* Per-school catchment map PDFs, which carry a 'Priority and distance of the
  last child offered a place' panel. The PDFs do not say at which point in the
  cycle the figures were taken, so they are stored separately with
  entry_point = 'catchment_map' and never merged with offer-day figures.

PDFs are discovered from the council pages listed in config/area.yaml. The
seed file data/seed/admissions_history.csv holds hand-entered rows; each run
compares them with the parsed figures and reports any mismatch.
"""

import csv
import io
import logging
import re

import pdfplumber

from .. import SEED_DIR, SourceFormatChanged
from ..db import upsert
from ..discover import html_links_with_heading

NAME = "admissions"
LICENCE = "Solihull Metropolitan Borough Council published admissions information"
SEED_FILE = SEED_DIR / "admissions_history.csv"
STOP = {"and", "the", "school", "academy", "sixth", "form", "of", "catholic", "college"}
MAP_ROW = re.compile(r"(?P<year>20\d{2})\s+(?P<label>(?:Priority|Criteria)\s+\d+)\s+(?P<what>[A-Za-z][A-Za-z ]*?)\s*-\s*(?P<dist>\d+\.\d+)\s*miles")

log = logging.getLogger(__name__)


def tokens(name: str) -> set[str]:
    return {t for t in re.findall(r"[a-z]+", name.lower().replace("'", "")) if t not in STOP}


def match_urn(name: str, schools: list[tuple[int, str]]) -> int | None:
    """Resolve a council school name to a URN: smallest GIAS name whose tokens contain all of name's tokens."""
    want = tokens(name)
    if not want:
        return None
    cands = [(len(tokens(n)), urn) for urn, n in schools if want <= tokens(n)]
    cands.sort()
    if not cands or (len(cands) > 1 and cands[0][0] == cands[1][0]):
        return None
    return cands[0][1]


def pdf_text(blob: bytes) -> str:
    with pdfplumber.open(io.BytesIO(blob)) as pdf:
        return " ".join(" ".join(w["text"] for w in p.extract_words(use_text_flow=True)) for p in pdf.pages)


def parse_offer_rows(text: str, tables: list[list[list]]) -> list[dict]:
    """Rows of the 'How secondary places were offered' table, one per school and intake year."""
    years = [int(y) for y in re.findall(r"September (20\d{2}) admissions", text)]
    if len(years) < 2:
        raise SourceFormatChanged("Offer table has no 'September YYYY admissions' column headings")
    out = []
    for table in tables:
        for row in table:
            cells = [(c or "").replace("\n", " ").strip() for c in row]
            if len(cells) < 2 + 2 * len(years) or not cells[1].isdigit():
                continue
            school, pan = cells[0], int(cells[1])
            for i, year in enumerate(years):
                crit, dist = cells[2 + 2 * i], cells[3 + 2 * i]
                if not crit:
                    continue
                out.append({"school": school, "entry_year": year, "pan": pan, "last_priority": crit,
                            "last_distance_miles": float(dist) if re.fullmatch(r"\d+(\.\d+)?", dist) else None})
    if not out:
        raise SourceFormatChanged("Offer table PDF parsed but no school rows were found")
    return out


def parse_offer_table(blob: bytes) -> list[dict]:
    with pdfplumber.open(io.BytesIO(blob)) as pdf:
        page = pdf.pages[0]
        return parse_offer_rows(page.extract_text() or "", page.extract_tables())


def parse_map_panel(text: str) -> tuple[str, list[dict]] | None:
    i = text.find("Priority and distance of the last child offered a place")
    if i < 0:
        return None
    seg = text[i:i + 600]
    m = re.search(r"offered a place\s+(.+?)\s+Catchment Area", seg)
    if not m:
        return None
    rows = [{"entry_year": int(r["year"]), "last_priority": f"{r['label']} {r['what'].strip()}",
             "last_distance_miles": float(r["dist"])} for r in MAP_ROW.finditer(seg)]
    return m.group(1).strip(), rows


def fetch(ctx):
    f = ctx.fetcher(NAME)
    pdfs = {}
    for page in ctx.area["admissions"]["pages"]:
        for url, _text, heading in html_links_with_heading(f.get_text(page), page):
            if url.lower().endswith(".pdf") and (re.search(r"secondary-places-were-offered", url, re.I)
                                                 or re.search(r"catchment-map", url, re.I)):
                pdfs[url] = pdfs.get(url) or heading
    if not any(re.search(r"secondary-places-were-offered", u, re.I) for u in pdfs):
        raise SourceFormatChanged("No 'How secondary places were offered' PDF linked from the configured council pages")
    log.info("admissions PDFs found: %d", len(pdfs))
    ctx.source_url = next(u for u in pdfs if re.search(r"secondary-places-were-offered", u, re.I))
    return {url: (pdfs[url], f.get(url)) for url in sorted(pdfs)}


def parse(ctx, raw) -> list[dict]:
    schools = [(r[0], r[1]) for r in ctx.conn.execute("SELECT urn, name FROM schools WHERE phase != 'Primary'")]
    rows, unmatched = [], set()
    for url, (heading, blob) in raw.items():
        if re.search(r"secondary-places-were-offered", url, re.I):
            for r in parse_offer_table(blob):
                urn = match_urn(r["school"], schools)
                if not urn:
                    unmatched.add(r["school"])
                    continue
                note = "All on time applicants offered" if "all on time" in r["last_priority"].lower() else None
                rows.append({"urn": urn, "entry_year": r["entry_year"], "entry_point": "national_offer_day",
                             "pan": r["pan"], "applications": None, "first_prefs": None,
                             "last_priority": r["last_priority"], "last_distance_miles": r["last_distance_miles"],
                             "source_url": url, "note": note})
        else:
            panel = parse_map_panel(pdf_text(blob))
            if not panel:
                continue
            school, entries = panel
            # The panel often names the school without its town ('Tudor Grange Academy'); the page heading
            # above the link names it in full, so use it when the panel name alone is ambiguous.
            urn = match_urn(school, schools)
            if not urn and heading and tokens(school) <= tokens(heading):
                urn = match_urn(heading, schools)
            if not urn:
                unmatched.add(school)
                continue
            for e in entries:
                rows.append({"urn": urn, "entry_year": e["entry_year"], "entry_point": "catchment_map", "pan": None,
                             "applications": None, "first_prefs": None, "last_priority": e["last_priority"],
                             "last_distance_miles": e["last_distance_miles"], "source_url": url,
                             "note": "Catchment map panel; point in the admissions cycle not stated"})
    if unmatched:
        ctx.notes.append(f"schools outside the 5 mile school list or not matched: {', '.join(sorted(unmatched))}")
    return rows


def read_seed() -> list[dict]:
    if not SEED_FILE.exists():
        return []
    with open(SEED_FILE, newline="", encoding="utf-8") as fh:
        out = []
        for r in csv.DictReader(fh):
            num = lambda v, t: t(v) if v not in (None, "") else None
            out.append({"urn": int(r["urn"]), "entry_year": int(r["entry_year"]), "entry_point": r["entry_point"],
                        "pan": num(r["pan"], int), "applications": num(r["applications"], int),
                        "first_prefs": num(r["first_prefs"], int), "last_priority": r["last_priority"] or None,
                        "last_distance_miles": num(r["last_distance_miles"], float),
                        "source_url": r["source_url"], "note": r["note"]})
        return out


def load(ctx, rows) -> int:
    seed = read_seed()
    parsed = {(r["urn"], r["entry_year"], r["entry_point"], r["source_url"]): r for r in rows}
    ctx._seed_check = []
    for s in seed:
        key = (s["urn"], s["entry_year"], s["entry_point"], s["source_url"])
        p = parsed.get(key)
        if p is None:
            parsed[key] = s  # only in the seed file: keep it, marked by its note
            ctx._seed_check.append(f"seed row {key[:3]} not found in parsed PDFs (kept as seed)")
        elif p["last_distance_miles"] != s["last_distance_miles"]:
            ctx._seed_check.append(f"seed {key[:3]} distance {s['last_distance_miles']} != PDF {p['last_distance_miles']}")
        else:
            p["pan"] = p["pan"] or s["pan"]
            p["note"] = f"{p['note']}. Matches user seed value"
    upsert(ctx.conn, "admissions_history", list(parsed.values()), ("urn", "entry_year", "entry_point", "source_url"))
    ctx.conn.commit()
    return len(parsed)


def validate(ctx) -> list[str]:
    problems = list(getattr(ctx, "_seed_check", []))
    for s in ctx.area["target_schools"]:
        q = "SELECT entry_year, last_priority, last_distance_miles FROM admissions_history WHERE urn=? AND entry_point=? ORDER BY entry_year"
        offer = ctx.conn.execute(q, (s["urn"], "national_offer_day")).fetchall()
        maps = {r[0]: r for r in ctx.conn.execute(q, (s["urn"], "catchment_map"))}
        if not offer:
            problems.append(f"No offer-day history for {s['name']}: manual data needed")
        for r in offer:
            m = maps.get(r[0])
            if m and (m[2] is None or r[2] is None or abs(m[2] - r[2]) > 0.02):
                problems.append(f"{s['name']} {r[0]}: offer day '{r[1]} {r[2]}' vs catchment map '{m[1]} {m[2]}' differ")
    return problems
