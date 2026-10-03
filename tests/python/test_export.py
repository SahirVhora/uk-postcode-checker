"""The published Area Pack must never contain polygons or house-level addresses."""

import json
from pathlib import Path

import pytest

from pipeline import SourceFormatChanged
from pipeline.export import shard_id, write_json
from pipeline.geo import contains_polygon_geometry

from pipeline.packcheck import FORBIDDEN_KEYS, main as packcheck_main

PACK = Path(__file__).resolve().parents[2] / "data" / "area-pack"


def walk_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from walk_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_keys(v)


def pack_files():
    return sorted(PACK.rglob("*.json"))


def test_pack_exists():
    assert (PACK / "index.json").exists(), "run python -m pipeline.export"
    assert len(pack_files()) > 3


@pytest.mark.parametrize("path", pack_files(), ids=lambda p: str(p.relative_to(PACK)))
def test_pack_file_has_no_polygons_or_addresses(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    assert not contains_polygon_geometry(data), f"{path} contains polygon geometry"
    assert not FORBIDDEN_KEYS & set(walk_keys(data)), f"{path} contains forbidden keys"
    assert path.stat().st_size < 500_000, "pre-commit check-added-large-files limit"


def test_index_lists_every_postcode_shard():
    index = json.loads((PACK / "index.json").read_text())
    shards = {p.stem for p in (PACK / "postcodes").glob("*.json")}
    assert set(index["postcodes"].values()) == shards
    assert all(a for a in index["attribution"])


def test_write_json_refuses_polygons(tmp_path):
    with pytest.raises(SourceFormatChanged):
        write_json(tmp_path / "x.json", {"a": {"type": "MultiPolygon", "coordinates": []}})
    assert not (tmp_path / "x.json").exists()


def test_shard_id():
    assert shard_id("B90 3DF") == "B90-3D"
    assert shard_id("B9 4AA") == "B9-4A"


def test_packcheck_cli_flags_bad_file(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"x": {"paon": "37"}}')
    good = tmp_path / "good.json"
    good.write_text('{"lat": 52.4}')
    assert packcheck_main([str(bad)]) == 1
    assert packcheck_main([str(good)]) == 0
