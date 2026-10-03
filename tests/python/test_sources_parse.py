"""Parser tests for each source, using small fixture files (no network)."""

import csv
import io
import json
import zipfile

import pytest

from pipeline import SourceFormatChanged
from pipeline.sources import catchments, census, epc, gias, imd, ofsted, onspd, osm, performance, police, ppd
from tests.python.conftest import add_postcode


# ---------- A. ONSPD ----------

def onspd_row(pcds, lat="52.402580", lng="-1.814147", doterm=None):
    return {"pcds": pcds, "doterm": doterm, "lat": lat, "long": lng, "oa21cd": "E00051573", "lsoa21cd": "E01010203",
            "msoa21cd": "E02002102", "lad26cd": "E08000029", "wd26cd": "E05016429"}


def test_onspd_latest_release_picks_newest_month():
    results = [{"title": "ONS Postcode Directory (May 2026) for the United Kingdom (Hosted Table)", "id": "a"},
               {"title": "ONS Postcode Directory (August 2026) for the United Kingdom (Hosted Table)", "id": "b"},
               {"title": "Online ONS Postcode Directory (Live)", "id": "c"},
               {"title": "ONS Postcode Directory (February 2026) for the UK (Hosted Table)", "id": "d"}]
    release, item = onspd.latest_release(results)
    assert release == "August 2026" and item["id"] == "b"
    with pytest.raises(SourceFormatChanged):
        onspd.latest_release([{"title": "Something else"}])


def test_onspd_parse_excludes_terminated_and_ungridded(ctx):
    raw = {"release": "August 2026", "names": {"B90 3DF": {"ward_name": "Shirley South", "lad_name": "Solihull"}},
           "rows": [onspd_row("B90 3DF"), onspd_row("B90 9ZZ", doterm=202001), onspd_row("B90 9ZY", lat="99.999999", lng="0")]}
    rows = onspd.parse(ctx, raw)
    assert [r["pcds"] for r in rows] == ["B90 3DF"]
    r = rows[0]
    assert (r["outcode"], r["sector"], r["ward_code"], r["lad_code"], r["ward_name"]) == ("B90", "B90 3", "E05016429", "E08000029", "Shirley South")


def test_onspd_parse_fails_loudly_when_fields_change(ctx):
    row = onspd_row("B90 3DF")
    row.pop("lad26cd")
    with pytest.raises(SourceFormatChanged, match="local authority"):
        onspd.parse(ctx, {"release": "x", "names": {}, "rows": [row]})


# ---------- B. Catchments ----------

def feature(name, fid, coords):
    return {"properties": {"CONAME": name, "FID": fid}, "geometry": {"type": "Polygon", "coordinates": [coords]}}


def test_catchments_parse_and_assign_multi_membership(ctx):
    sq = lambda x, y: [[x, y], [x + 1, y], [x + 1, y + 1], [x, y + 1], [x, y]]
    raw = {"secondary": {"url": "https://example.test/0", "features": [
        feature("Tudor Grange Academy Solihull", 1, sq(0, 0)),
        feature("Alderbrook School", 2, sq(0.5, 0)),
        feature("Light Hall School", 3, sq(5, 5))]}}
    rows = catchments.parse(ctx, raw)
    assert {r["school_name"] for r in rows} == {"Tudor Grange Academy Solihull", "Alderbrook School", "Light Hall School"}
    add_postcode(ctx.conn, "B91 1AA", 0.5, 0.75)   # in both TGA and Alderbrook
    add_postcode(ctx.conn, "B90 1AA", 5.5, 5.5)    # Light Hall only
    catchments.load(ctx, rows)
    got = {r[0]: r[1] for r in ctx.conn.execute("SELECT pcds, in_target_catchment FROM postcodes")}
    assert got == {"B91 1AA": 1, "B90 1AA": 0}
    links = sorted(r[0] for r in ctx.conn.execute("SELECT school_name FROM postcode_catchments WHERE pcds='B91 1AA'"))
    assert links == ["Alderbrook School", "Tudor Grange Academy Solihull"]


def test_catchments_parse_rejects_missing_name_field(ctx):
    raw = {"secondary": {"url": "u", "features": [{"properties": {"NAME": "x"}, "geometry": {"type": "Polygon", "coordinates": []}}]}}
    with pytest.raises(SourceFormatChanged, match="CONAME"):
        catchments.parse(ctx, raw)


# ---------- B. GIAS ----------

def test_gias_parse_converts_grid_refs_and_filters(ctx):
    add_postcode(ctx.conn, "B90 3DF", 52.40258, -1.814147)
    header = ["URN", "EstablishmentName", "PhaseOfEducation (name)", "TypeOfEstablishment (name)", "EstablishmentStatus (name)",
              "Easting", "Northing", "ReligiousCharacter (name)", "AdmissionsPolicy (name)", "LA (code)", "LA (name)", "Postcode"]
    rows = [["136310", "Tudor Grange Academy, Solihull", "Secondary", "Academy converter", "Open", "414170", "278541",
             "Does not apply", "Non-selective", "334", "Solihull", "B91 3PD"],
            ["100000", "Closed School", "Primary", "Community school", "Closed", "414000", "278000", "", "", "334", "Solihull", "B90 1AA"],
            ["200000", "Far Away School", "Primary", "Community school", "Open", "530000", "180000", "", "", "201", "London", "EC1A 1AA"]]
    buf = io.StringIO()
    csv.writer(buf).writerows([header] + rows)
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as zf:
        zf.writestr("edubasealldata20261003.csv", buf.getvalue().encode("cp1252"))
    parsed = gias.parse(ctx, zbuf.getvalue())
    assert [r["urn"] for r in parsed] == [136310]
    assert parsed[0]["lat"] == pytest.approx(52.4045, abs=0.001)
    assert parsed[0]["miles_from_pool"] < 1.5


# ---------- B. Ofsted ----------

def test_ofsted_keeps_legacy_and_report_cards_separate(ctx, fixture_text):
    for urn in (136310, 136994, 999001):
        ctx.conn.execute("INSERT INTO schools (urn, name) VALUES (?, ?)", (urn, str(urn)))
    ctx.source_url = "https://example.test/latest_inspections_as_at_31_August_2026.csv"
    # The fixture only carries the columns the parser needs; the real file has more.
    rows = {r["urn"]: r for r in ofsted.parse(ctx, fixture_text("ofsted_mi_sample.csv").encode())}
    assert set(rows) == {136310, 136994, 999001}            # school outside the pool is skipped
    tga = rows[136310]
    assert tga["legacy_overall_effectiveness"] == "Not judged"
    assert tga["legacy_quality_of_education"] == "1"
    assert tga["legacy_inspection_date"] == "2025-04-29"
    assert rows[136994]["ungraded_outcome"] == "School remains Good"
    rc = rows[999001]
    assert rc["report_card_date"] == "2026-01-10" and rc["rc_inclusion"] == "Strong standard"
    assert rc["legacy_overall_effectiveness"] is None       # never derived from report cards
    assert rc["rc_early_years"] is None                      # 9 = not applicable


def test_ofsted_latest_file_by_date():
    urls = ["https://a/Management_information_-_state-funded_schools_-_latest_inspections_as_at_31_July_2026.csv",
            "https://a/Management_information_-_state-funded_schools_-_latest_inspections_as_at_31_August_2026.csv",
            "https://a/Management_information_-_state-funded_schools_-_latest_inspections_as_at_30_June_2026.csv",
            "https://a/old_format_latest_inspections.csv"]
    assert ofsted.latest_mi_csv(urls).endswith("31_August_2026.csv")


# ---------- B. Performance ----------

def test_performance_progress8_not_published_is_null(ctx, fixture_text):
    for urn in (136310, 136994):
        ctx.conn.execute("INSERT INTO schools (urn, name) VALUES (?, ?)", (urn, str(urn)))
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as zf:
        zf.writestr("2024-2025/334_ks4final.csv", fixture_text("ks4_sample.csv").encode("cp1252"))
    rows = performance.parse(ctx, [("Performancetables_1.zip", zbuf.getvalue())])
    got = {(r["urn"], r["metric"]): r for r in rows}
    assert got[(136310, "ATT8SCR")]["value"] == 58.7
    assert got[(136310, "PTL2BASICS_95")]["value"] == 71.9
    p8 = got[(136310, "P8MEA")]
    assert p8["value"] is None and p8["raw"] == "NA"        # not published: NULL, never 0
    assert got[(136994, "PTEBACC_E_PTQ_EE")]["value"] is None
    assert {r["year"] for r in rows} == {"2024-2025"}


def test_performance_value_parser():
    assert performance.parse_value("65.40%") == 65.4
    assert performance.parse_value("NE") is None
    assert performance.parse_value("") is None
    assert performance.parse_value(None) is None


# ---------- C. PPD ----------

def test_ppd_amend_and_delete_handling(fixture_text):
    rows = ppd.parse_lines(fixture_text("ppd_sample.csv"))
    assert len(rows) == 6 and rows[0]["tid"] == "AAAA0001-0000-0000-0000-000000000001"
    current, deleted = ppd.apply_record_status(rows)
    assert current["AAAA0001-0000-0000-0000-000000000001"]["price"] == 405000   # C replaced the original A
    assert "AAAA0004-0000-0000-0000-000000000004" not in current                 # D removed it
    assert deleted == {"AAAA0004-0000-0000-0000-000000000004"}
    assert current["AAAA0003-0000-0000-0000-000000000003"]["category"] == "B"


def test_ppd_load_deletes_previously_loaded_record(ctx, fixture_text):
    rows = ppd.parse_lines(fixture_text("ppd_sample.csv"))
    ppd.load(ctx, {"rows": rows[:5][-1:], "deleted": set()})                    # load the A record for ...0004
    assert ctx.conn.execute("SELECT COUNT(*) FROM ppd").fetchone()[0] == 1
    current, deleted = ppd.apply_record_status(rows)
    ppd.load(ctx, {"rows": list(current.values()), "deleted": deleted})
    tids = {r[0] for r in ctx.conn.execute("SELECT tid FROM ppd")}
    assert "AAAA0004-0000-0000-0000-000000000004" not in tids and len(tids) == 3


def test_ppd_rejects_wrong_field_count():
    with pytest.raises(SourceFormatChanged):
        ppd.parse_lines('"a","1","2025-01-01 00:00","B90 3DF"\n')


# ---------- C. EPC ----------

def test_epc_certificate_extraction(fixture_json):
    row = epc.from_certificate("1111-2222-3333-4444-5555", fixture_json("epc_certificate_rdsap.json"))
    assert row["total_floor_area"] == 55.0
    assert row["habitable_rooms"] == 3
    assert row["property_type"] == "Flat" and row["built_form"] == "Mid-Terrace"
    assert row["construction_age_band"] == "F"
    assert row["energy_band"] == "C" and row["postcode"] == "B90 3DP"


def test_epc_bulk_csv_old_layout(fixture_text):
    rows = epc.from_csv_rows(fixture_text("epc_bulk_old.csv"))
    assert rows[1]["total_floor_area"] == 95.0 and rows[1]["habitable_rooms"] == 6
    assert rows[2]["uprn"] is None


def test_epc_bulk_keeps_latest_per_property(ctx, fixture_text):
    add_postcode(ctx.conn, "B90 3DE", 52.4, -1.81)
    rows = epc.parse(ctx, {"mode": "csv", "files": [("bulk.csv", fixture_text("epc_bulk_old.csv").encode())]})
    certs = {r["cert_number"] for r in rows}
    assert certs == {"cert-2", "cert-3"}


# ---------- E. Census ----------

def test_census_percentages():
    raw = [{"table": "TS021", "geo_type": "OA", "geo": "E00051573", "cat": "total", "count": 275},
           {"table": "TS021", "geo_type": "OA", "geo": "E00051573", "cat": "asian", "count": 33},
           {"table": "TS030", "geo_type": "OA", "geo": "E00051573", "cat": "total", "count": 274},
           {"table": "TS030", "geo_type": "OA", "geo": "E00051573", "cat": "muslim", "count": 18}]
    rows = {(r["table_id"], r["category"]): r for r in census.parse(None, raw)}
    assert rows[("TS021", "asian")]["pct"] == 12.0
    assert rows[("TS030", "muslim")]["pct"] == 6.57


# ---------- D. IMD ----------

def test_imd_parse_matches_columns_by_name(ctx, fixture_text):
    add_postcode(ctx.conn, "B90 3DF", 52.40258, -1.814147)
    rows = imd.parse(ctx, {"release": "IoD2025", "body": fixture_text("imd_sample.csv").encode()})
    assert len(rows) == 1
    r = rows[0]
    assert (r["imd_rank"], r["imd_decile"], r["income_decile"], r["education_decile"], r["crime_decile"], r["living_env_decile"]) == (24120, 8, 6, 8, 6, 5)


# ---------- D. Police ----------

class FakePoliceFetcher:
    """Returns 503 for any box wider than 0.5 degrees, else one crime at the box centre."""

    def __init__(self):
        self.calls = 0

    def get(self, url, params=None, **_):
        from pipeline.http import HTTPStatusError
        self.calls += 1
        pts = [tuple(map(float, p.split(","))) for p in params["poly"].split(":")]
        lats, lngs = [p[0] for p in pts], [p[1] for p in pts]
        if max(lats) - min(lats) > 0.5:
            raise HTTPStatusError(503, url)
        c = {"id": self.calls, "category": "burglary", "month": params["date"],
             "location": {"latitude": str(sum(lats) / 4), "longitude": str(sum(lngs) / 4), "street": {"name": "On or near X"}}}
        return json.dumps([c]).encode()


def test_police_tiles_split_on_result_cap():
    f = FakePoliceFetcher()
    crimes = police.fetch_tile(f, (52.0, -2.0, 53.0, -1.0), "2026-08")
    assert len(crimes) == 4          # one 503, then four quadrants
    assert f.calls == 5


def test_police_parse_assigns_lsoa_by_point_in_polygon(ctx):
    sq = json.dumps({"type": "Polygon", "coordinates": [[[-1.9, 52.3], [-1.7, 52.3], [-1.7, 52.5], [-1.9, 52.5], [-1.9, 52.3]]]})
    ctx.conn.execute("INSERT INTO lsoa_boundaries (lsoa21, geojson) VALUES ('E01010203', ?)", (sq,))
    raw = [{"id": 1, "category": "burglary", "month": "2026-08", "location": {"latitude": "52.4", "longitude": "-1.8", "street": {"name": "A"}}},
           {"id": 2, "category": "robbery", "month": "2026-08", "location": {"latitude": "51.5", "longitude": "-0.1", "street": {"name": "B"}}}]
    rows = police.parse(ctx, raw)
    assert [(r["crime_key"], r["lsoa21"]) for r in rows] == [("1", "E01010203")]


# ---------- E. OSM ----------

def test_osm_classify():
    assert osm.classify({"amenity": "place_of_worship", "religion": "muslim"}) == "mosque"
    assert osm.classify({"amenity": "place_of_worship", "religion": "sikh"}) == "gurdwara"
    assert osm.classify({"amenity": "place_of_worship", "religion": "hindu"}) == "mandir"
    assert osm.classify({"amenity": "place_of_worship", "religion": "christian"}) is None
    assert osm.classify({"amenity": "fast_food", "diet:halal": "yes", "name": "Chicken"}) == "halal"
    assert osm.classify({"shop": "butcher", "name": "Hafiz Halal Meat"}) == "halal"
    assert osm.classify({"amenity": "bench", "name": "Halal bench"}) is None
