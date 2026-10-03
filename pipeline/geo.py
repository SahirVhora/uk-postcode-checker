"""Geometry helpers: distances, coordinate conversion, point-in-polygon, tiling."""

import json
import math
from functools import lru_cache

from pyproj import Transformer
from shapely import STRtree
from shapely.geometry import Point, box, shape
from shapely.ops import unary_union
from shapely.prepared import prep

from .packcheck import contains_polygon_geometry  # noqa: F401  (re-exported for callers)

EARTH_RADIUS_MILES = 3958.7613

DISTANCE_CAVEAT = "postcode-centroid estimate, actual LLPG distance may differ by up to ~0.1 mi"


def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in miles (same formula as distKm in index.html)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = p2 - p1
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


@lru_cache(maxsize=1)
def _bng_transformer() -> Transformer:
    return Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)


def bng_to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    """Convert British National Grid to (lat, lng)."""
    lng, lat = _bng_transformer().transform(easting, northing)
    return lat, lng


def geojson_to_shape(geojson: str | dict):
    geom = json.loads(geojson) if isinstance(geojson, str) else geojson
    return shape(geom)


def union_shapes(geojsons) -> object:
    return unary_union([geojson_to_shape(g) for g in geojsons])


class PolygonIndex:
    """Polygons keyed by name (features with the same name are unioned) for point-in-polygon tests."""

    def __init__(self, named_geojsons: dict[str, list]):
        self._shapes = {name: union_shapes(gs) for name, gs in named_geojsons.items()}
        self._names = list(self._shapes)
        self._tree = STRtree([self._shapes[n] for n in self._names])
        self._prepared = {name: prep(s) for name, s in self._shapes.items()}

    def containing(self, lat: float, lng: float) -> list[str]:
        """Names of all polygons covering the point (boundary counts as inside)."""
        pt = Point(lng, lat)
        hits = self._tree.query(pt)
        return sorted(self._names[i] for i in hits if self._prepared[self._names[i]].covers(pt))

    def shape(self, name: str):
        return self._shapes[name]


def bbox_of_points(points, pad: float = 0.0) -> tuple[float, float, float, float]:
    lats = [p[0] for p in points]
    lngs = [p[1] for p in points]
    return (min(lats) - pad, min(lngs) - pad, max(lats) + pad, max(lngs) + pad)


def split_bbox(bbox):
    """Split (min_lat, min_lng, max_lat, max_lng) into four quadrants."""
    s, w, n, e = bbox
    mid_lat, mid_lng = (s + n) / 2, (w + e) / 2
    return [(s, w, mid_lat, mid_lng), (s, mid_lng, mid_lat, e),
            (mid_lat, w, n, mid_lng), (mid_lat, mid_lng, n, e)]


def bbox_poly_param(bbox) -> str:
    """data.police.uk poly parameter: lat,lng pairs separated by colons."""
    s, w, n, e = bbox
    corners = [(n, w), (n, e), (s, e), (s, w)]
    return ":".join(f"{lat:.6f},{lng:.6f}" for lat, lng in corners)


def bbox_shape(bbox):
    s, w, n, e = bbox
    return box(w, s, e, n)
