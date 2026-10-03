import json

import pytest

from pipeline.geo import (PolygonIndex, bbox_poly_param, bng_to_wgs84, contains_polygon_geometry, haversine_miles,
                          split_bbox)


def square(lng0, lat0, size):
    return json.dumps({"type": "Polygon", "coordinates": [[[lng0, lat0], [lng0 + size, lat0], [lng0 + size, lat0 + size],
                                                            [lng0, lat0 + size], [lng0, lat0]]]})


def test_haversine_known_distances():
    # London Charing Cross to Birmingham New Street is about 101 miles in a straight line.
    assert haversine_miles(51.5074, -0.1278, 52.4778, -1.8990) == pytest.approx(101.5, abs=1.0)
    # One degree of latitude is about 69.1 miles.
    assert haversine_miles(52.0, -1.8, 53.0, -1.8) == pytest.approx(69.09, abs=0.05)
    assert haversine_miles(52.4, -1.8, 52.4, -1.8) == 0


def test_haversine_matches_school_gate_case():
    # Council points for the TGA and Alderbrook gates are about 0.2 miles apart.
    d = haversine_miles(52.404559, -1.793016, 52.406194, -1.797301)
    assert 0.18 < d < 0.24


def test_bng_to_wgs84_matches_onspd():
    # ONSPD August 2026: B90 3DF east1m 412741, north1m 278300, lat 52.402580, long -1.814147.
    lat, lng = bng_to_wgs84(412741, 278300)
    assert lat == pytest.approx(52.402580, abs=2e-5)
    assert lng == pytest.approx(-1.814147, abs=2e-5)


def test_point_in_polygon_with_overlapping_catchments():
    idx = PolygonIndex({
        "A": [square(0, 0, 1)],
        "B": [square(0.5, 0.5, 1)],                  # overlaps A
        "C": [square(5, 5, 1), square(7, 7, 1)],     # two separate features unioned under one name
    })
    assert idx.containing(0.25, 0.25) == ["A"]
    assert idx.containing(0.75, 0.75) == ["A", "B"]  # shared zone belongs to both
    assert idx.containing(7.5, 7.5) == ["C"]
    assert idx.containing(3, 3) == []
    assert idx.containing(0, 0.5) == ["A"]           # boundary counts as inside


def test_split_bbox_and_poly_param():
    quads = split_bbox((52.0, -2.0, 53.0, -1.0))
    assert len(quads) == 4
    assert quads[0] == (52.0, -2.0, 52.5, -1.5)
    assert bbox_poly_param((52.0, -2.0, 53.0, -1.0)) == "53.000000,-2.000000:53.000000,-1.000000:52.000000,-1.000000:52.000000,-2.000000"


def test_contains_polygon_geometry_detects_geojson_and_rings():
    assert contains_polygon_geometry({"a": {"type": "Polygon", "coordinates": []}})
    assert contains_polygon_geometry({"x": {"rings": [[[0, 0]]]}})
    assert contains_polygon_geometry([[[0, 0], [1, 1]]])
    assert not contains_polygon_geometry({"lat": 52.4, "lng": -1.8, "outcomes": [[2026, "within_distance"]]})
