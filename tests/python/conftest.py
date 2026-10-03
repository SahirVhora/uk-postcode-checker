"""Shared pytest fixtures. No test touches the network."""

import json
from pathlib import Path

import pytest

from pipeline.context import Context, load_yaml
from pipeline.db import connect

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail loudly if any test tries to make a real HTTP request."""
    import requests

    def blocked(*_a, **_k):
        raise AssertionError("network access attempted in a unit test")

    monkeypatch.setattr(requests.Session, "request", blocked)
    monkeypatch.setattr(requests, "get", blocked)


@pytest.fixture
def ctx(tmp_path):
    """A Context on an empty temporary database with the real config files."""
    return Context(conn=connect(tmp_path / "test.db"), area=load_yaml(REPO / "config" / "area.yaml"),
                   scoring=load_yaml(REPO / "config" / "scoring.yaml"), offline=True)


@pytest.fixture
def fixture_text():
    return lambda name: (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def fixture_json():
    return lambda name: json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def add_postcode(conn, pcds, lat, lng, lsoa="E01010203", oa="E00051573", lad="E08000029"):
    outcode, inward = pcds.split(" ")
    conn.execute(
        "INSERT INTO postcodes (pcds, outcode, sector, lat, lng, oa21, lsoa21, lad_code) VALUES (?,?,?,?,?,?,?,?)",
        (pcds, outcode, f"{outcode} {inward[0]}", lat, lng, oa, lsoa, lad))
