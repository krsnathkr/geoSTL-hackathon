"""Unit tests for analyze/export.py."""

import json
import os
import tempfile

import geopandas as gpd
import pytest
from shapely.geometry import Point

from analyze.export import export_all, load_detections, to_geojson, to_geoparquet
from config.settings import WGS84_CRS


def _make_detections():
    rows = [
        {
            "obs_id": "seq-1",
            "detection_type": "stale",
            "confidence": 0.82,
            "obs_name": "Blue Bottle",
            "obs_category": "cafe",
            "obs_condition": "closed",
            "gers_id": "gers-001",
            "overture_name": "Blue Bottle Coffee",
            "overture_category": "cafe",
            "distance_m": 8.5,
            "clip_s3_uri": "s3://bucket/clip1.mp4",
            "frame_ids": '["f1", "f2"]',
            "lat": 37.77,
            "lon": -122.42,
        },
        {
            "obs_id": "seq-2",
            "detection_type": "missing",
            "confidence": 0.68,
            "obs_name": "New Taqueria",
            "obs_category": "restaurant",
            "obs_condition": "open",
            "gers_id": "",
            "overture_name": "",
            "overture_category": "",
            "distance_m": None,
            "clip_s3_uri": "s3://bucket/clip2.mp4",
            "frame_ids": '["f3"]',
            "lat": 37.78,
            "lon": -122.43,
        },
        {
            "obs_id": "seq-3",
            "detection_type": "validated",
            "confidence": 0.91,
            "obs_name": "Starbucks",
            "obs_category": "cafe",
            "obs_condition": "open",
            "gers_id": "gers-002",
            "overture_name": "Starbucks",
            "overture_category": "cafe",
            "distance_m": 3.0,
            "clip_s3_uri": "",
            "frame_ids": "[]",
            "lat": 37.79,
            "lon": -122.44,
        },
    ]
    return gpd.GeoDataFrame(
        rows,
        geometry=[Point(r["lon"], r["lat"]) for r in rows],
        crs=WGS84_CRS,
    )


# ── to_geojson ────────────────────────────────────────────────────────────────

def test_to_geojson_creates_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = to_geojson(_make_detections(), output_dir=tmp)
        assert os.path.exists(path)


def test_to_geojson_valid_structure():
    with tempfile.TemporaryDirectory() as tmp:
        path = to_geojson(_make_detections(), output_dir=tmp)
        with open(path) as f:
            fc = json.load(f)
        assert fc["type"] == "FeatureCollection"
        assert len(fc["features"]) == 3
        feat = fc["features"][0]
        assert feat["type"] == "Feature"
        assert feat["geometry"]["type"] == "Point"
        assert "detection_type" in feat["properties"]
        assert "gers_id" in feat["properties"]


def test_to_geojson_exclude_validated():
    with tempfile.TemporaryDirectory() as tmp:
        path = to_geojson(_make_detections(), output_dir=tmp, exclude_validated=True)
        with open(path) as f:
            fc = json.load(f)
        types = [f["properties"]["detection_type"] for f in fc["features"]]
        assert "validated" not in types
        assert len(fc["features"]) == 2


def test_to_geojson_has_metadata():
    with tempfile.TemporaryDirectory() as tmp:
        path = to_geojson(_make_detections(), output_dir=tmp)
        with open(path) as f:
            fc = json.load(f)
        assert "overture_release" in fc["metadata"]


# ── to_geoparquet ─────────────────────────────────────────────────────────────

def test_to_geoparquet_creates_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = to_geoparquet(_make_detections(), output_dir=tmp)
        assert os.path.exists(path)


def test_to_geoparquet_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        to_geoparquet(_make_detections(), output_dir=tmp)
        loaded = gpd.read_parquet(os.path.join(tmp, "detections.geoparquet"))
        assert len(loaded) == 3
        assert "discrepancy_type" in loaded.columns  # renamed from detection_type
        assert "overture_id" in loaded.columns  # renamed from gers_id


def test_to_geoparquet_exclude_validated():
    with tempfile.TemporaryDirectory() as tmp:
        to_geoparquet(_make_detections(), output_dir=tmp, exclude_validated=True)
        loaded = gpd.read_parquet(os.path.join(tmp, "detections.geoparquet"))
        assert len(loaded) == 2
        assert "validated" not in loaded["discrepancy_type"].values


# ── export_all + load_detections ──────────────────────────────────────────────

def test_export_all_returns_both_paths():
    with tempfile.TemporaryDirectory() as tmp:
        paths = export_all(_make_detections(), output_dir=tmp)
        assert "geojson" in paths
        assert "geoparquet" in paths
        assert os.path.exists(paths["geojson"])
        assert os.path.exists(paths["geoparquet"])


def test_load_detections_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        export_all(_make_detections(), output_dir=tmp, exclude_validated=False)
        loaded = load_detections(data_dir=tmp)
        assert isinstance(loaded, gpd.GeoDataFrame)
        assert len(loaded) == 3


def test_export_all_handles_empty_detection_frame():
    empty = gpd.GeoDataFrame(geometry=gpd.GeoSeries([], crs=WGS84_CRS), crs=WGS84_CRS)
    with tempfile.TemporaryDirectory() as tmp:
        paths = export_all(empty, output_dir=tmp)
        assert os.path.exists(paths["geojson"])
        assert os.path.exists(paths["geoparquet"])
