"""Standalone check that the public Area Pack holds no polygons or house-level addresses.

Stdlib only, so it runs as a pre-commit hook without the pipeline dependencies:

    python3 -m pipeline.packcheck [files...]
"""

import json
import sys
from pathlib import Path

PACK_DIR = Path(__file__).resolve().parent.parent / "data" / "area-pack"
FORBIDDEN_KEYS = {"paon", "saon", "geojson", "geometry", "rings", "coordinates", "address1", "uprn"}
POLYGON_TYPES = {"polygon", "multipolygon", "feature", "featurecollection", "geometrycollection"}


def contains_polygon_geometry(obj) -> bool:
    """True if obj (parsed JSON) contains any GeoJSON polygon or coordinate ring."""
    if isinstance(obj, dict):
        if str(obj.get("type", "")).lower() in POLYGON_TYPES:
            return True
        if "rings" in obj or "coordinates" in obj or "geometry" in obj:
            return True
        return any(contains_polygon_geometry(v) for v in obj.values())
    if isinstance(obj, list):
        if obj and isinstance(obj[0], list) and obj[0] and isinstance(obj[0][0], list):
            return True  # nested coordinate arrays
        return any(contains_polygon_geometry(v) for v in obj)
    return False


def forbidden_keys(obj) -> set[str]:
    found = set()
    if isinstance(obj, dict):
        found |= FORBIDDEN_KEYS & set(obj)
        for v in obj.values():
            found |= forbidden_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            found |= forbidden_keys(v)
    return found


def problems(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out = []
    if contains_polygon_geometry(data):
        out.append(f"{path}: contains polygon geometry")
    keys = forbidden_keys(data)
    if keys:
        out.append(f"{path}: contains forbidden keys {sorted(keys)}")
    return out


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    files = [Path(a) for a in args if a.endswith(".json")] if args else sorted(PACK_DIR.rglob("*.json"))
    errors = [e for f in files for e in problems(f)]
    for e in errors:
        print(e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
