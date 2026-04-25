"""Unit tests for analyze/cross_reference.py — no external I/O."""

import pytest
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from analyze.cross_reference import (
    classify_detection,
    cross_reference,
    descriptions_to_gdf,
    _categories_match,
    _name_similarity,
)
from config.settings import WGS84_CRS


def _make_overture(id_="gers-001", name="Blue Bottle Coffee", category="cafe", lat=37.7700, lon=-122.4200):
    return gpd.GeoDataFrame(
        [{"id": id_, "name": name, "category": category, "geometry": Point(lon, lat)}],
        geometry="geometry",
        crs=WGS84_CRS,
    )


def _make_desc(name="Blue Bottle", category="cafe", condition="open", lat=37.7700, lon=-122.4200, seq_id="seq-1"):
    return {
        "sequence_id": seq_id,
        "name": name,
        "category": category,
        "condition": condition,
        "lat": lat,
        "lon": lon,
        "clip_s3_uri": "",
        "frame_ids": [],
    }


# ── helpers ───────────────────────────────────────────────────────────────────

def test_categories_match_cafe():
    assert _categories_match("cafe", "coffee_shop") is True
    assert _categories_match("cafe", "retail") is False


def test_categories_match_restaurant():
    assert _categories_match("restaurant", "food_and_beverage") is True
    assert _categories_match("restaurant", "hotel") is False


def test_name_similarity_identical():
    assert _name_similarity("Blue Bottle", "Blue Bottle") == pytest.approx(1.0)


def test_name_similarity_different():
    assert _name_similarity("Blue Bottle", "Starbucks") < 0.5


def test_name_similarity_empty():
    assert _name_similarity("", "Blue Bottle") == pytest.approx(0.0)


# ── classify_detection ────────────────────────────────────────────────────────

def test_classify_missing_open_no_match():
    det_type, conf = classify_detection(
        obs_name="New Taco Spot", obs_category="restaurant", obs_condition="open",
        overture_name=None, overture_category=None, distance_m=None,
    )
    assert det_type == "missing"
    assert conf > 0


def test_classify_stale_closed_with_match():
    det_type, conf = classify_detection(
        obs_name="Blue Bottle", obs_category="cafe", obs_condition="closed",
        overture_name="Blue Bottle Coffee", overture_category="cafe",
        distance_m=10.0,
    )
    assert det_type == "stale"
    assert conf > 0.5


def test_classify_stale_vacant_with_match():
    det_type, conf = classify_detection(
        obs_name="Old Store", obs_category="retail", obs_condition="vacant",
        overture_name="Old Store", overture_category="retail",
        distance_m=20.0,
    )
    assert det_type == "stale"


def test_classify_miscategorized():
    det_type, conf = classify_detection(
        obs_name="Mission Cafe", obs_category="restaurant", obs_condition="open",
        overture_name="Mission Cafe", overture_category="retail_store",
        distance_m=5.0,
    )
    assert det_type == "miscategorized"


def test_classify_validated():
    det_type, conf = classify_detection(
        obs_name="Tartine", obs_category="cafe", obs_condition="open",
        overture_name="Tartine Bakery", overture_category="cafe_and_bakery",
        distance_m=8.0,
    )
    assert det_type == "validated"


# ── descriptions_to_gdf ───────────────────────────────────────────────────────

def test_descriptions_to_gdf_basic():
    descs = [_make_desc()]
    gdf = descriptions_to_gdf(descs)
    assert len(gdf) == 1
    assert gdf.crs.to_epsg() == 4326
    assert gdf.iloc[0].geometry.x == pytest.approx(-122.42)


def test_descriptions_to_gdf_skips_missing_coords():
    descs = [_make_desc(), {"sequence_id": "no-coords", "lat": None, "lon": None}]
    gdf = descriptions_to_gdf(descs)
    assert len(gdf) == 1


# ── cross_reference ───────────────────────────────────────────────────────────

def test_cross_reference_finds_match():
    descs = [_make_desc(condition="closed")]
    overture = _make_overture()
    gdf = cross_reference(descs, overture, match_radius_m=100)
    assert len(gdf) == 1
    assert gdf.iloc[0]["detection_type"] == "stale"
    assert gdf.iloc[0]["gers_id"] == "gers-001"


def test_cross_reference_missing_when_no_overture_nearby():
    descs = [_make_desc(lat=37.80, lon=-122.50)]  # far from any Overture POI
    overture = _make_overture(lat=37.77, lon=-122.42)
    gdf = cross_reference(descs, overture, match_radius_m=50)
    assert gdf.iloc[0]["detection_type"] == "missing"
    assert gdf.iloc[0]["gers_id"] in ("", None)


def test_cross_reference_empty_descriptions():
    gdf = cross_reference([], _make_overture())
    assert isinstance(gdf, gpd.GeoDataFrame)
    assert len(gdf) == 0
