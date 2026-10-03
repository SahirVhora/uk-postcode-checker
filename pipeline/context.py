"""Shared run context passed to every source module."""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

from . import CONFIG_DIR, DB_PATH, REPO_ROOT
from .db import connect
from .http import Fetcher

log = logging.getLogger("pipeline")


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@dataclass
class Context:
    conn: object
    area: dict
    scoring: dict
    offline: bool = False
    refresh: bool = False
    env: dict = field(default_factory=dict)
    source_url: str | None = None
    notes: list = field(default_factory=list)
    _fetchers: list = field(default_factory=list)

    @classmethod
    def create(cls, offline=False, refresh=False, db_path: Path = DB_PATH,
               area_path: Path = CONFIG_DIR / "area.yaml", scoring_path: Path = CONFIG_DIR / "scoring.yaml"):
        load_dotenv(REPO_ROOT / ".env")
        env = {k: v for k, v in os.environ.items() if k.startswith("EPC_")}
        return cls(conn=connect(db_path), area=load_yaml(area_path), scoring=load_yaml(scoring_path),
                   offline=offline, refresh=refresh, env=env)

    @property
    def mode(self) -> str:
        return "offline" if self.offline else ("refresh" if self.refresh else "online")

    def fetcher(self, source: str, **kw) -> Fetcher:
        f = Fetcher(source, offline=self.offline, refresh=self.refresh, **kw)
        self._fetchers.append(f)
        return f

    def latest_fetch(self) -> str | None:
        stamps = [s for f in self._fetchers for s in f.fetched_at]
        return max(stamps) if stamps else None

    def reset_run_state(self):
        self.source_url = None
        self.notes = []
        self._fetchers = []

    def pool(self) -> list:
        return self.conn.execute("SELECT * FROM postcodes ORDER BY pcds").fetchall()

    def target_schools(self) -> list[dict]:
        return self.area["target_schools"]

    def borough_lad(self) -> str:
        if self.area.get("borough_lad"):
            return self.area["borough_lad"]
        row = self.conn.execute(
            "SELECT lad_code, COUNT(*) n FROM postcodes GROUP BY lad_code ORDER BY n DESC LIMIT 1").fetchone()
        if not row:
            raise RuntimeError("No postcodes loaded yet; run the onspd source first.")
        return row["lad_code"]

    def pool_lads(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT DISTINCT lad_code FROM postcodes WHERE lad_code IS NOT NULL ORDER BY 1")]
