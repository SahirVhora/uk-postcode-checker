"""Match Land Registry sales (PPD) to the latest EPC for the same property.

Matching function (documented in docs/DATA_SOURCES.md):

1. Candidates are EPCs with exactly the same postcode as the sale.
2. Both addresses are normalised: upper case, '&' -> 'AND', punctuation removed,
   common street suffix abbreviations expanded (RD -> ROAD, ST -> STREET, ...),
   flat/apartment/unit prefixes removed, whitespace collapsed.
3. The PPD 'number part' is SAON + PAON (e.g. 'FLAT 9' + 'BRONTE COURT' -> '9 BRONTE COURT';
   '' + '37' -> '37'). The EPC number part is the start of its address lines up to
   where the PPD street name begins.
4. method 'exact': EPC number part equals PPD number part and the PPD street appears in the EPC address.
   method 'tokens': every PPD number-part token and street token appears in the EPC address,
   and the EPC address has no extra numeric token (prevents '1 HIGH ROAD' matching 'FLAT 1, 10 HIGH ROAD').
5. If several EPCs qualify with the best method, the most recent certificate wins.

Match rate = matched sales / all sales with a postcode in the pool.
"""

import re

ABBREVIATIONS = {
    "RD": "ROAD", "ST": "STREET", "AVE": "AVENUE", "AV": "AVENUE", "CL": "CLOSE", "CRES": "CRESCENT",
    "DR": "DRIVE", "GDNS": "GARDENS", "GR": "GROVE", "LN": "LANE", "PL": "PLACE", "SQ": "SQUARE", "CT": "COURT",
}
UNIT_WORDS = {"FLAT", "APARTMENT", "APT", "UNIT", "MAISONETTE"}


def normalise(text: str | None) -> str:
    t = (text or "").upper().replace("&", " AND ")
    t = re.sub(r"[^A-Z0-9 ]", " ", t)
    words = [ABBREVIATIONS.get(w, w) for w in t.split()]
    return " ".join(w for w in words if w not in UNIT_WORDS)


def ppd_parts(sale) -> tuple[str, str]:
    number = normalise(f"{sale['saon'] or ''} {sale['paon'] or ''}")
    return number, normalise(sale["street"])


def epc_address(epc) -> str:
    return normalise(" ".join(filter(None, [epc["address1"], epc["address2"], epc["address3"]])))


def match_method(sale, epc) -> str | None:
    number, street = ppd_parts(sale)
    addr = epc_address(epc)
    if not number:
        return None
    if street and f" {street}" not in f" {addr}":
        return None
    epc_number = addr.split(f" {street}")[0].strip() if street else addr
    if epc_number == number:
        return "exact"
    addr_tokens = addr.split()
    ppd_tokens = number.split() + street.split()
    if all(tok in addr_tokens for tok in ppd_tokens):
        extra_numbers = [t for t in addr_tokens if re.fullmatch(r"\d+[A-Z]?", t) and t not in number.split()]
        if not extra_numbers:
            return "tokens"
    return None


def best_match(sale, candidates) -> tuple[str, str] | None:
    scored = [(m, epc) for epc in candidates if (m := match_method(sale, epc))]
    if not scored:
        return None
    best = "exact" if any(m == "exact" for m, _ in scored) else "tokens"
    newest = max((e for m, e in scored if m == best), key=lambda e: e["registration_date"] or "")
    return newest["cert_number"], best


def match_all(conn) -> float:
    """Recompute ppd_epc_match for all sales. Returns the match rate."""
    by_postcode: dict[str, list] = {}
    for e in conn.execute("SELECT * FROM epc"):
        by_postcode.setdefault(e["postcode"], []).append(e)
    conn.execute("DELETE FROM ppd_epc_match")
    rows, total = [], 0
    for sale in conn.execute("SELECT * FROM ppd WHERE postcode IN (SELECT pcds FROM postcodes)"):
        total += 1
        m = best_match(sale, by_postcode.get(sale["postcode"], []))
        if m:
            rows.append((sale["tid"], m[0], m[1]))
    conn.executemany("INSERT INTO ppd_epc_match (tid, cert_number, method) VALUES (?, ?, ?)", rows)
    conn.commit()
    return len(rows) / total if total else 0.0


def match_rate(conn) -> tuple[int, int]:
    matched = conn.execute("SELECT COUNT(*) FROM ppd_epc_match").fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM ppd WHERE postcode IN (SELECT pcds FROM postcodes)").fetchone()[0]
    return matched, total
