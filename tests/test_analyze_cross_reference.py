"""Unit tests for analyze/cross_reference.py — no external I/O."""

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point

from analyze.cross_reference import (
    classify_observation,
    cross_reference,
    descriptions_to_gdf,
    observation_confidence,
)
from config.settings import WGS84_CRS


def _make_transport():
    return gpd.GeoDataFrame(
        [
            {
                "id": "segment-001",
                "name": "Pearl Street",
                "class": "residential",
                "geometry": LineString([(-122.4201, 37.7699), (-122.4199, 37.7701)]),
            }
        ],
        geometry="geometry",
        crs=WGS84_CRS,
    )


def _make_desc(**overrides):
    base = {
        "sequence_id": "seq-1",
        "name": "sidewalk_segment",
        "category": "sidewalk",
        "condition": "good",
        "sidewalk_presence": "present",
        "sidewalk_width_m": 1.8,
        "curb_ramp_status": "present",
        "obstructions": [],
        "hazards": [],
        "crossing_features": [],
        "lat": 37.7700,
        "lon": -122.4200,
        "clip_s3_uri": "",
        "frame_ids": [],
        "description": "",
    }
    base.update(overrides)
    return base


def test_classify_observation_present():
    findings = classify_observation(_make_desc())
    assert findings == ["sidewalk_present"]


def test_classify_observation_multiple_issues():
    findings = classify_observation(
        _make_desc(
            condition="under_construction",
            curb_ramp_status="absent",
            obstructions=["temporary_barrier"],
            hazards=["pothole", "construction_zone"],
        )
    )
    assert "sidewalk_present" in findings
    assert "curb_ramp_missing" in findings
    assert "obstruction" in findings
    assert "pothole" in findings
    assert "construction" in findings


def test_observation_confidence_increases_with_evidence():
    high = observation_confidence(_make_desc(crossing_features=["crosswalk"], hazards=["pothole"]))
    low = observation_confidence(_make_desc(sidewalk_presence="unclear", sidewalk_width_m=None, curb_ramp_status="unclear"))
    assert high > low


def test_descriptions_to_gdf_includes_sidewalk_fields():
    gdf = descriptions_to_gdf([_make_desc()])
    assert len(gdf) == 1
    assert gdf.iloc[0]["sidewalk_presence"] == "present"
    assert gdf.iloc[0].geometry == Point(-122.42, 37.77)


def test_cross_reference_creates_inventory_findings():
    gdf = cross_reference(
        [
            _make_desc(
                curb_ramp_status="absent",
                obstructions=["utility_pole"],
                hazards=["pothole"],
            )
        ],
        _make_transport(),
    )
    assert len(gdf) >= 4
    assert set(gdf["detection_type"]) >= {"sidewalk_present", "curb_ramp_missing", "obstruction", "pothole"}
    assert gdf.iloc[0]["transport_id"] == "segment-001"


def test_cross_reference_without_transport():
    gdf = cross_reference([_make_desc(sidewalk_presence="absent")], None)
    assert len(gdf) == 0  # sidewalk_missing suppressed — highways produce false positives


def test_cross_reference_empty_descriptions():
    gdf = cross_reference([], _make_transport())
    assert isinstance(gdf, gpd.GeoDataFrame)
    assert len(gdf) == 0
    assert "detection_type" in gdf.columns
