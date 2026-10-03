"""SQLite schema and helpers for the local Area Pack database."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS source_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    run_at TEXT NOT NULL,
    mode TEXT NOT NULL,
    url TEXT,
    licence TEXT,
    fetched_at TEXT,
    row_count INTEGER,
    status TEXT NOT NULL,
    note TEXT
);

CREATE TABLE IF NOT EXISTS postcodes (
    pcds TEXT PRIMARY KEY,
    outcode TEXT NOT NULL,
    sector TEXT NOT NULL,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    oa21 TEXT, lsoa21 TEXT, msoa21 TEXT,
    ward_code TEXT, ward_name TEXT,
    lad_code TEXT, lad_name TEXT,
    onspd_release TEXT,
    in_target_catchment INTEGER
);

-- Local only. Never exported or committed.
CREATE TABLE IF NOT EXISTS catchment_polygons (
    layer TEXT NOT NULL,
    school_name TEXT NOT NULL,
    feature_id INTEGER NOT NULL,
    geojson TEXT NOT NULL,
    source_url TEXT,
    PRIMARY KEY (layer, feature_id)
);

CREATE TABLE IF NOT EXISTS postcode_catchments (
    pcds TEXT NOT NULL,
    layer TEXT NOT NULL,
    school_name TEXT NOT NULL,
    PRIMARY KEY (pcds, layer, school_name)
);

CREATE TABLE IF NOT EXISTS schools (
    urn INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    phase TEXT, type TEXT, status TEXT,
    lat REAL, lng REAL,
    religious_character TEXT,
    admissions_policy TEXT,
    la_code TEXT, la_name TEXT,
    postcode TEXT,
    miles_from_pool REAL
);

CREATE TABLE IF NOT EXISTS ofsted (
    urn INTEGER PRIMARY KEY,
    source_file TEXT,
    legacy_overall_effectiveness TEXT,
    legacy_inspection_date TEXT,
    legacy_quality_of_education TEXT,
    legacy_behaviour TEXT,
    legacy_personal_development TEXT,
    legacy_leadership TEXT,
    ungraded_outcome TEXT,
    ungraded_date TEXT,
    report_card_date TEXT,
    rc_safeguarding TEXT,
    rc_inclusion TEXT,
    rc_curriculum_teaching TEXT,
    rc_achievement TEXT,
    rc_attendance_behaviour TEXT,
    rc_personal_development TEXT,
    rc_early_years TEXT,
    rc_post16 TEXT,
    rc_leadership TEXT
);

CREATE TABLE IF NOT EXISTS performance (
    urn INTEGER NOT NULL,
    year TEXT NOT NULL,
    key_stage TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL,
    raw TEXT,
    PRIMARY KEY (urn, year, key_stage, metric)
);

CREATE TABLE IF NOT EXISTS school_gates (
    urn INTEGER PRIMARY KEY,
    name TEXT,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0,
    source TEXT
);

CREATE TABLE IF NOT EXISTS admissions_history (
    urn INTEGER NOT NULL,
    entry_year INTEGER NOT NULL,
    entry_point TEXT NOT NULL,
    pan INTEGER,
    applications INTEGER,
    first_prefs INTEGER,
    last_priority TEXT,
    last_distance_miles REAL,
    source_url TEXT NOT NULL,
    note TEXT,
    PRIMARY KEY (urn, entry_year, entry_point, source_url)
);

CREATE TABLE IF NOT EXISTS postcode_school_distance (
    pcds TEXT NOT NULL,
    urn INTEGER NOT NULL,
    miles REAL NOT NULL,
    to_gate INTEGER NOT NULL,
    PRIMARY KEY (pcds, urn)
);

CREATE TABLE IF NOT EXISTS ppd (
    tid TEXT PRIMARY KEY,
    price INTEGER NOT NULL,
    date TEXT NOT NULL,
    postcode TEXT,
    property_type TEXT,
    new_build TEXT,
    tenure TEXT,
    paon TEXT, saon TEXT, street TEXT, locality TEXT, town TEXT, district TEXT, county TEXT,
    category TEXT,
    record_status TEXT
);

CREATE TABLE IF NOT EXISTS epc (
    cert_number TEXT PRIMARY KEY,
    uprn TEXT,
    address1 TEXT, address2 TEXT, address3 TEXT,
    postcode TEXT,
    registration_date TEXT,
    total_floor_area REAL,
    habitable_rooms INTEGER,
    property_type TEXT,
    built_form TEXT,
    energy_band TEXT,
    construction_age_band TEXT,
    schema TEXT
);

CREATE TABLE IF NOT EXISTS ppd_epc_match (
    tid TEXT PRIMARY KEY,
    cert_number TEXT NOT NULL,
    method TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS census (
    geo_code TEXT NOT NULL,
    geo_type TEXT NOT NULL,
    table_id TEXT NOT NULL,
    category TEXT NOT NULL,
    count INTEGER NOT NULL,
    pct REAL,
    PRIMARY KEY (geo_code, table_id, category)
);

-- Local only (official ONS boundaries, used to assign crimes to LSOAs).
CREATE TABLE IF NOT EXISTS lsoa_boundaries (
    lsoa21 TEXT PRIMARY KEY,
    name TEXT,
    lad_code TEXT,
    geojson TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS crimes (
    crime_key TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    month TEXT NOT NULL,
    lat REAL, lng REAL,
    street TEXT,
    lsoa21 TEXT
);

CREATE TABLE IF NOT EXISTS imd (
    lsoa21 TEXT PRIMARY KEY,
    release TEXT NOT NULL,
    lad_code TEXT,
    imd_rank INTEGER,
    imd_decile INTEGER,
    income_decile INTEGER,
    crime_decile INTEGER,
    living_env_decile INTEGER,
    education_decile INTEGER
);

CREATE TABLE IF NOT EXISTS osm_pois (
    osm_key TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    name TEXT,
    lat REAL NOT NULL,
    lng REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS postcode_poi_nearest (
    pcds TEXT NOT NULL,
    kind TEXT NOT NULL,
    osm_key TEXT,
    name TEXT,
    miles REAL,
    PRIMARY KEY (pcds, kind)
);

CREATE TABLE IF NOT EXISTS crime_rates (
    lsoa21 TEXT PRIMARY KEY,
    lad_code TEXT,
    population INTEGER,
    months INTEGER,
    total INTEGER,
    family INTEGER,
    rate_per_1000 REAL,
    family_rate_per_1000 REAL
);

CREATE TABLE IF NOT EXISTS price_metrics (
    level TEXT NOT NULL,
    area TEXT NOT NULL,
    property_type TEXT NOT NULL,
    sales_recent INTEGER,
    median_price_recent INTEGER,
    median_gbp_per_sqm REAL,
    median_4bed_equiv INTEGER,
    sales_4bed_equiv INTEGER,
    trend_pct REAL,
    PRIMARY KEY (level, area, property_type)
);

CREATE TABLE IF NOT EXISTS scores (
    pcds TEXT PRIMARY KEY,
    school REAL,
    price REAL,
    safety REAL,
    community REAL,
    total REAL,
    detail_json TEXT
);
"""

LOCAL_ONLY_TABLES = ("catchment_polygons", "lsoa_boundaries")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def upsert(conn: sqlite3.Connection, table: str, rows: list[dict], key: tuple[str, ...]) -> int:
    """Insert rows, updating non-key columns when the natural key already exists."""
    if not rows:
        return 0
    columns = list(rows[0].keys())
    placeholders = ", ".join("?" for _ in columns)
    updates = ", ".join(f"{c} = excluded.{c}" for c in columns if c not in key)
    conflict = f"ON CONFLICT ({', '.join(key)}) DO " + (f"UPDATE SET {updates}" if updates else "NOTHING")
    sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) {conflict}"
    conn.executemany(sql, [tuple(r[c] for c in columns) for r in rows])
    return len(rows)


def record_run(conn, source, mode, status, url=None, licence=None, fetched_at=None, row_count=None, note=None):
    conn.execute(
        "INSERT INTO source_runs (source, run_at, mode, url, licence, fetched_at, row_count, status, note) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (source, utc_now(), mode, url, licence, fetched_at, row_count, status, note),
    )
    conn.commit()


def count(conn, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
