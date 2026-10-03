"""Build the full per-postcode profile used by scoring, export and the text report."""

from .admissions_model import assess, load_rules
from .derive import borough_crime_medians
from .geo import DISTANCE_CAVEAT

MIN_SALES = 3  # minimum recent sales before a price level is used


class ProfileBuilder:
    """Caches area-wide lookups so profiles for thousands of postcodes stay fast."""

    def __init__(self, conn, area: dict, borough_lad: str):
        self.conn = conn
        self.area = area
        self.borough_lad = borough_lad
        self.medians = borough_crime_medians(conn, borough_lad)
        self.targets = area["target_schools"]
        self.feeders = area.get("feeder_schools", [])
        self.history = {s["urn"]: [dict(r) for r in conn.execute(
            "SELECT * FROM admissions_history WHERE urn=? ORDER BY entry_year DESC", (s["urn"],))] for s in self.targets}
        self.gates = {r["urn"]: dict(r) for r in conn.execute("SELECT * FROM school_gates")}
        self.school_info = {s["urn"]: self._school_info(s["urn"]) for s in self.targets + self.feeders}
        self.years = area["admissions"]["history_years"]

    def _school_info(self, urn: int) -> dict:
        school = self.conn.execute("SELECT * FROM schools WHERE urn=?", (urn,)).fetchone()
        ofsted = self.conn.execute("SELECT * FROM ofsted WHERE urn=?", (urn,)).fetchone()
        perf = self.conn.execute("SELECT year, key_stage, metric, value, raw FROM performance WHERE urn=? ORDER BY year DESC",
                                 (urn,)).fetchall()
        by_year: dict = {}
        for r in perf:
            by_year.setdefault(r["year"], {}).setdefault(r["key_stage"], {})[r["metric"]] = {"value": r["value"], "raw": r["raw"]}
        return {"urn": urn, "name": school["name"] if school else None, "phase": school["phase"] if school else None,
                "ofsted": dict(ofsted) if ofsted else None, "performance": by_year}

    def price_block(self, pc: dict) -> dict:
        levels = (("postcode", pc["pcds"]), ("sector", pc["sector"]), ("outcode", pc["outcode"]))
        out, chosen = {}, None
        for level, key in levels:
            rows = self.conn.execute("SELECT * FROM price_metrics WHERE level=? AND area=?", (level, key)).fetchall()
            out[level] = {r["property_type"]: {k: r[k] for k in r.keys() if k not in ("level", "area", "property_type")}
                          for r in rows}
            all_row = out[level].get("ALL")
            if chosen is None and all_row and all_row["sales_recent"] >= MIN_SALES:
                chosen = level
        return {"levels": out, "level_used": chosen or "outcode"}

    def build(self, pcds: str) -> dict | None:
        c = self.conn
        pc = c.execute("SELECT * FROM postcodes WHERE pcds=?", (pcds,)).fetchone()
        if not pc:
            return None
        pc = dict(pc)
        links = c.execute("SELECT layer, school_name FROM postcode_catchments WHERE pcds=? ORDER BY layer, school_name",
                          (pcds,)).fetchall()
        catchments = {"secondary": [r[1] for r in links if r[0] == "secondary"],
                      "primary": [r[1] for r in links if r[0] == "primary"]}
        dist = {r["urn"]: r["miles"] for r in c.execute("SELECT urn, miles FROM postcode_school_distance WHERE pcds=?", (pcds,))}

        schools = {}
        for s in self.targets:
            rules = load_rules(s["rules"])
            in_c = s["catchment_name"] in catchments["secondary"]
            miles = dist.get(s["urn"])
            hist = self.history[s["urn"]]
            schools[s["key"]] = {
                "urn": s["urn"], "name": s["name"], "in_catchment": in_c,
                "gate_miles": miles, "gate_verified": bool(self.gates.get(s["urn"], {}).get("verified")),
                "distance_note": DISTANCE_CAVEAT,
                "policy_year": rules["policy_year"], "policy_url": rules["source_url"], "pan": rules["pan"],
                "default": assess(rules, hist, {"in_catchment": in_c}, miles, self.years),
                "st_james": assess(rules, hist, {"in_catchment": in_c, "feeder": "st_james"}, miles, self.years),
                "history": hist,
            }
        feeders = {f["key"]: {"urn": f["urn"], "name": f["name"], "miles": dist.get(f["urn"]),
                              "gate_verified": bool(self.gates.get(f["urn"], {}).get("verified"))} for f in self.feeders}

        crime = c.execute("SELECT * FROM crime_rates WHERE lsoa21=?", (pc["lsoa21"],)).fetchone()
        imd = c.execute("SELECT * FROM imd WHERE lsoa21=?", (pc["lsoa21"],)).fetchone()

        def census(geo):
            out = {}
            for r in c.execute("SELECT table_id, category, count, pct FROM census WHERE geo_code=?", (geo,)):
                out[f"{r['table_id']}:{r['category']}"] = {"count": r["count"], "pct": r["pct"]}
            return out

        nearest = {r["kind"]: {"name": r["name"], "miles": r["miles"]}
                   for r in c.execute("SELECT kind, name, miles FROM postcode_poi_nearest WHERE pcds=?", (pcds,))}
        score = c.execute("SELECT * FROM scores WHERE pcds=?", (pcds,)).fetchone()
        return {
            **pc,
            "in_target_catchment": bool(pc["in_target_catchment"]),
            "catchments": catchments,
            "schools": schools,
            "feeders": feeders,
            "prices": self.price_block(pc),
            "safety": {
                "lsoa": dict(crime) if crime else None,
                "borough_lad": self.borough_lad,
                "borough_median_rate": self.medians[0], "borough_median_family_rate": self.medians[1],
                "imd": dict(imd) if imd else None,
            },
            "community": {"oa": census(pc["oa21"]), "lsoa": census(pc["lsoa21"]), "nearest": nearest},
            "score": dict(score) if score else None,
        }
