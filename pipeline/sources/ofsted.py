"""B. Ofsted: State-funded schools inspections and outcomes, management information.

The latest 'latest inspections' CSV is discovered from the gov.uk statistics page.
Ofsted replaced single-word overall judgements with report cards from November
2025. Both are stored side by side. No single grade is ever derived from report
cards, and 'Not judged' overall effectiveness is kept as published.
"""

import csv
import io
import logging
import re
from datetime import datetime

from .. import SourceFormatChanged
from ..db import upsert
from ..discover import govuk_content, govuk_links

NAME = "ofsted"
LICENCE = "Open Government Licence v3.0"
LANDING = "government/statistical-data-sets/monthly-management-information-ofsteds-school-inspections-outcomes"

# normalised header -> column
COLUMNS = {
    "urn": "urn",
    "legacy_overall_effectiveness": "latest oeif overall effectiveness",
    "legacy_inspection_date": "inspection start date of latest oeif graded inspection",
    "legacy_quality_of_education": "latest oeif quality of education",
    "legacy_behaviour": "latest oeif behaviour and attitudes",
    "legacy_personal_development": "latest oeif personal development",
    "legacy_leadership": "latest oeif effectiveness of leadership and management",
    "ungraded_outcome": "ungraded inspection overall outcome",
    "ungraded_date": "date of latest ungraded inspection",
    "report_card_date": "inspection start date",
    "rc_safeguarding": "safeguarding standards",
    "rc_inclusion": "inclusion",
    "rc_curriculum_teaching": "curriculum and teaching",
    "rc_achievement": "achievement",
    "rc_attendance_behaviour": "attendance and behaviour",
    "rc_personal_development": "personal development and wellbeing",
    "rc_early_years": "early years (where applicable)",
    "rc_post16": "post-16 provision (where applicable)",
    "rc_leadership": "leadership and governance",
}
DATE_FIELDS = {"legacy_inspection_date", "ungraded_date", "report_card_date"}

log = logging.getLogger(__name__)


def norm(h: str) -> str:
    return re.sub(r"\s+", " ", h.strip().lower())


def clean(value: str | None) -> str | None:
    v = (value or "").strip()
    return None if v in ("", "NULL", "9") else v  # 9 = not applicable in Ofsted MI


def iso_date(value: str | None) -> str | None:
    v = clean(value)
    if not v:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(v, fmt).date().isoformat()
        except ValueError:
            pass
    raise SourceFormatChanged(f"Unrecognised Ofsted date '{v}'")


def latest_mi_csv(urls: list[str]) -> str | None:
    """Pick the 'latest_inspections_as_at_<d>_<Month>_<yyyy>.csv' file with the newest date."""
    best = None
    for u in urls:
        m = re.search(r"latest_inspections_as_at_(\d{1,2})_([A-Za-z]+)_(\d{4})\.csv$", u)
        if not m:
            continue
        month = m.group(2)[:3].title()
        when = datetime.strptime(f"{m.group(1)} {month} {m.group(3)}", "%d %b %Y")
        if best is None or when > best[0]:
            best = (when, u)
    return best[1] if best else None


def fetch(ctx):
    f = ctx.fetcher(NAME)
    links = govuk_links(govuk_content(f, LANDING))
    url = latest_mi_csv([u for u, _ in links])
    if not url:
        raise SourceFormatChanged(f"No dated 'latest inspections ... as at <date>' CSV linked from gov.uk/{LANDING}")
    log.info("Ofsted MI: %s", url)
    ctx.source_url = url
    return f.get(url)


def parse(ctx, raw: bytes) -> list[dict]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    reader = csv.reader(io.StringIO(text))
    header = [norm(h) for h in next(reader)]
    idx = {}
    for key, col in COLUMNS.items():
        if col not in header:
            raise SourceFormatChanged(f"Ofsted MI has no column '{col}'. Columns: {header}")
        idx[key] = header.index(col)
    wanted = {r[0] for r in ctx.conn.execute("SELECT urn FROM schools")}
    rows = []
    for rec in reader:
        if not rec or not rec[idx["urn"]].isdigit() or int(rec[idx["urn"]]) not in wanted:
            continue
        row = {"urn": int(rec[idx["urn"]]), "source_file": ctx.source_url.rsplit("/", 1)[-1]}
        for key, i in idx.items():
            if key == "urn":
                continue
            row[key] = iso_date(rec[i]) if key in DATE_FIELDS else clean(rec[i])
        rows.append(row)
    return rows


def load(ctx, rows) -> int:
    upsert(ctx.conn, "ofsted", rows, ("urn",))
    ctx.conn.commit()
    return len(rows)


def validate(ctx) -> list[str]:
    missing = ctx.conn.execute(
        "SELECT COUNT(*) FROM schools s LEFT JOIN ofsted o USING (urn) WHERE o.urn IS NULL AND s.phase IN ('Primary','Secondary')"
    ).fetchone()[0]
    rc = ctx.conn.execute("SELECT COUNT(*) FROM ofsted WHERE report_card_date IS NOT NULL").fetchone()[0]
    ctx.notes.append(f"{rc} schools with report cards")
    return [f"{missing} open primary/secondary schools have no Ofsted MI row (new or not yet inspected)"] if missing else []
