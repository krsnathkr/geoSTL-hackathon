"""Unit tests for analyze/metrics.py."""

import json
import math
import os
import tempfile

import geopandas as gpd
import pytest
from shapely.geometry import Point

from analyze.metrics import (
    compute_and_save,
    compute_detection_metrics,
    compute_temporal_advantage,
    geodesic_distance_m,
    precision_recall_f1,
    rmse,
)
from config.settings import WGS84_CRS


def _make_detections(rows):
    return gpd.GeoDataFrame(
        rows,
        geometry=[Point(r["lon"], r["lat"]) for r in rows],
        crs=WGS84_CRS,
    )


# ── unit helpers ──────────────────────────────────────────────────────────────

def test_precision_recall_f1_perfect():
    result = precision_recall_f1(tp=10, fp=0, fn=0)
    assert result["precision"] == pytest.approx(1.0)
    assert result["recall"] == pytest.approx(1.0)
    assert result["f1"] == pytest.approx(1.0)


def test_precision_recall_f1_zero_division():
    result = precision_recall_f1(tp=0, fp=0, fn=0)
    assert result["precision"] == 0.0
    assert result["f1"] == 0.0


def test_rmse_basic():
    errors = [3.0, 4.0]  # sqrt((9+16)/2) = sqrt(12.5) ≈ 3.536
    assert rmse(errors) == pytest.approx(math.sqrt(12.5), abs=0.01)


def test_rmse_empty():
    assert math.isnan(rmse([]))


def test_geodesic_distance_same_point():
    assert geodesic_distance_m(37.77, -122.42, 37.77, -122.42) == pytest.approx(0.0, abs=0.1)


def test_geodesic_distance_known():
    # ~1 degree of latitude ≈ 111 km
    dist = geodesic_distance_m(37.0, -122.0, 38.0, -122.0)
    assert 110_000 < dist < 112_000


# ── compute_detection_metrics ─────────────────────────────────────────────────

def test_detection_metrics_type_breakdown():
    rows = [
        {"obs_id": "a", "detection_type": "pothole", "confidence": 0.8, "match_distance_m": 10.0, "lat": 37.77, "lon": -122.42},
        {"obs_id": "b", "detection_type": "sidewalk_missing", "confidence": 0.7, "match_distance_m": None, "lat": 37.78, "lon": -122.43},
        {"obs_id": "c", "detection_type": "sidewalk_present", "confidence": 0.9, "match_distance_m": 5.0, "lat": 37.79, "lon": -122.44},
    ]
    gdf = _make_detections(rows)
    metrics = compute_detection_metrics(gdf)
    assert "pothole" in metrics
    assert "sidewalk_missing" in metrics
    assert "sidewalk_present" in metrics
    assert "rmse_m" in metrics


def test_detection_metrics_with_ground_truth():
    rows = [
        {"obs_id": "a", "detection_type": "construction", "confidence": 0.8, "match_distance_m": 10.0, "lat": 37.77, "lon": -122.42},
        {"obs_id": "b", "detection_type": "construction", "confidence": 0.3, "match_distance_m": 45.0, "lat": 37.78, "lon": -122.43},
    ]
    gdf = _make_detections(rows)
    gt = [{"obs_id": "a", "true_type": "construction"}]
    metrics = compute_detection_metrics(gdf, ground_truth=gt)
    assert metrics["construction"]["tp"] == 1
    assert metrics["construction"]["fp"] == 1


# ── temporal advantage ────────────────────────────────────────────────────────

def test_temporal_advantage():
    video_rows = [
        {"obs_id": "a", "detection_type": "construction", "confidence": 0.8, "match_distance_m": 10.0, "lat": 37.77, "lon": -122.42},
        {"obs_id": "b", "detection_type": "pothole", "confidence": 0.7, "match_distance_m": None, "lat": 37.78, "lon": -122.43},
    ]
    base_rows = [
        {"obs_id": "a", "detection_type": "sidewalk_present", "confidence": 0.6, "match_distance_m": 10.0, "lat": 37.77, "lon": -122.42},
    ]
    video = _make_detections(video_rows)
    baseline = _make_detections(base_rows)
    result = compute_temporal_advantage(video, baseline)
    assert result["video_discrepancies"] == 2
    assert result["baseline_discrepancies"] == 0
    assert result["delta"] == 2


# ── compute_and_save ──────────────────────────────────────────────────────────

def test_compute_and_save_writes_json():
    rows = [
        {"obs_id": "a", "detection_type": "construction", "confidence": 0.8, "match_distance_m": 10.0, "lat": 37.77, "lon": -122.42},
        {"obs_id": "b", "detection_type": "sidewalk_missing", "confidence": 0.6, "match_distance_m": None, "lat": 37.78, "lon": -122.43},
    ]
    gdf = _make_detections(rows)

    with tempfile.TemporaryDirectory() as tmp:
        metrics = compute_and_save(gdf, output_dir=tmp)
        assert os.path.exists(os.path.join(tmp, "metrics.json"))
        assert "construction" in metrics
        assert "total_detections" in metrics
        with open(os.path.join(tmp, "metrics.json")) as f:
            loaded = json.load(f)
        assert loaded["total_detections"] == 2
