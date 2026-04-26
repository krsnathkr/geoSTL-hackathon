"""
Compute evaluation metrics for the detection pipeline.

Metrics:
  - Precision, Recall, F1 proxy per finding type
  - Match-distance RMSE (metres) when transport segment links exist
  - Video-sequence vs. single-frame baseline comparison
  - Finding density per km²

Output: data/output/metrics.json
"""

import json
import logging
import math
import os
from typing import Optional

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Geod

from config.settings import DATA_OUTPUT, UTM_CRS, WGS84_CRS

logger = logging.getLogger(__name__)

# Geodesic calculator (WGS84)
_GEOD = Geod(ellps="WGS84")
NON_ISSUE_TYPES = {"validated", "sidewalk_present", "sidewalk_unclear"}

# ── Geospatial distance ───────────────────────────────────────────────────────

def geodesic_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return geodesic distance in metres between two WGS84 points."""
    _, _, dist = _GEOD.inv(lon1, lat1, lon2, lat2)
    return abs(dist)


# ── Core metrics ──────────────────────────────────────────────────────────────

def precision_recall_f1(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def rmse(errors_m: list[float]) -> float:
    """Root mean square error of a list of position errors in metres."""
    if not errors_m:
        return float("nan")
    return round(math.sqrt(sum(e ** 2 for e in errors_m) / len(errors_m)), 2)


# ── Detection-level metrics ───────────────────────────────────────────────────

def compute_detection_metrics(
    detections: gpd.GeoDataFrame,
    ground_truth: Optional[list[dict]] = None,
) -> dict:
    """
    Compute precision/recall/F1 per detection type and overall geospatial RMSE.

    ground_truth: optional list of {obs_id, true_type} dicts for supervised eval.
    If not provided, uses confidence > 0.6 as a proxy for TP.
    """
    results: dict = {}

    detection_types = sorted(detections["detection_type"].dropna().unique().tolist())
    for det_type in detection_types:
        subset = detections[detections["detection_type"] == det_type]
        if ground_truth:
            gt_ids = {r["obs_id"] for r in ground_truth if r["true_type"] == det_type}
            tp = int(subset["obs_id"].isin(gt_ids).sum())
            fp = len(subset) - tp
            fn = len(gt_ids) - tp
        else:
            # Proxy: high confidence → TP, low confidence → FP
            tp = int((subset["confidence"] >= 0.6).sum())
            fp = int((subset["confidence"] < 0.6).sum())
            # FN estimate: detections we likely missed (validated rows with low conf)
            fn = 0

        results[det_type] = precision_recall_f1(tp, fp, fn)

    # Overall geospatial RMSE: distance between observation GPS and matched Overture GPS
    # We only compute this for rows that have a GERS match (distance_m not null)
    distance_column = "match_distance_m" if "match_distance_m" in detections.columns else "distance_m"
    matched = detections[detections[distance_column].notna()] if distance_column in detections.columns else detections.iloc[0:0]
    errors = matched[distance_column].dropna().tolist() if distance_column in matched.columns else []
    results["rmse_m"] = rmse(errors)
    results["rmse_matched_count"] = len(errors)

    return results


def compute_area_km2(gdf: gpd.GeoDataFrame) -> float:
    """Compute the area of the bounding box of the GeoDataFrame in km²."""
    bounds = gdf.to_crs(UTM_CRS).total_bounds  # [minx, miny, maxx, maxy] in metres
    width_m = bounds[2] - bounds[0]
    height_m = bounds[3] - bounds[1]
    return round((width_m * height_m) / 1_000_000, 4)


def false_positive_rate_per_km2(detections: gpd.GeoDataFrame) -> float:
    """Estimate false positive rate per km² (low-confidence detections / area)."""
    area = compute_area_km2(detections)
    if area == 0:
        return float("nan")
    fp_count = int((detections["confidence"] < 0.5).sum())
    return round(fp_count / area, 4)


# ── Temporal advantage (video vs. still-frame baseline) ───────────────────────

def compute_temporal_advantage(
    video_detections: gpd.GeoDataFrame,
    baseline_detections: gpd.GeoDataFrame,
) -> dict:
    """
    Compare video-sequence pipeline vs. single-frame baseline.

    baseline_detections should be produced from only the first frame of each sequence.
    Returns improvement ratios and delta counts.
    """
    video_disc = video_detections[~video_detections["detection_type"].isin(NON_ISSUE_TYPES)]
    base_disc = baseline_detections[~baseline_detections["detection_type"].isin(NON_ISSUE_TYPES)]

    result: dict = {
        "video_discrepancies": len(video_disc),
        "baseline_discrepancies": len(base_disc),
        "delta": len(video_disc) - len(base_disc),
    }

    # Per-type
    det_types = sorted(set(video_disc["detection_type"].dropna()) | set(base_disc["detection_type"].dropna()))
    for det_type in det_types:
        v_count = int((video_disc["detection_type"] == det_type).sum())
        b_count = int((base_disc["detection_type"] == det_type).sum())
        result[f"video_{det_type}"] = v_count
        result[f"baseline_{det_type}"] = b_count

    # Mean confidence improvement
    if not video_disc.empty and not base_disc.empty:
        result["video_mean_confidence"] = round(float(video_disc["confidence"].mean()), 4)
        result["baseline_mean_confidence"] = round(float(base_disc["confidence"].mean()), 4)
        result["confidence_delta"] = round(
            result["video_mean_confidence"] - result["baseline_mean_confidence"], 4
        )

    return result


# ── Full metrics pipeline ─────────────────────────────────────────────────────

def _sanitize_nans(obj):
    """Recursively replace float NaN with None so json.dump writes valid JSON."""
    if isinstance(obj, float) and math.isnan(obj):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_nans(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_nans(v) for v in obj]
    return obj


def compute_and_save(
    detections: gpd.GeoDataFrame,
    baseline_detections: Optional[gpd.GeoDataFrame] = None,
    ground_truth: Optional[list[dict]] = None,
    output_dir: str = DATA_OUTPUT,
) -> dict:
    """
    Compute all metrics and write data/output/metrics.json.

    Returns the full metrics dict.
    """
    os.makedirs(output_dir, exist_ok=True)

    metrics = compute_detection_metrics(detections, ground_truth=ground_truth)

    metrics["total_detections"] = len(detections)
    metrics["discrepancy_count"] = int((~detections["detection_type"].isin(NON_ISSUE_TYPES)).sum())

    if not detections.empty:
        metrics["fp_per_km2"] = false_positive_rate_per_km2(detections)
        metrics["area_km2"] = compute_area_km2(detections)
        metrics["detections_per_km2"] = round(
            metrics["discrepancy_count"] / max(metrics["area_km2"], 0.001), 2
        )

    if baseline_detections is not None and not baseline_detections.empty:
        metrics["temporal_advantage"] = compute_temporal_advantage(
            detections, baseline_detections
        )

    # Detection type breakdown
    type_counts = detections["detection_type"].value_counts().to_dict()
    metrics["type_counts"] = {k: int(v) for k, v in type_counts.items()}

    out_path = os.path.join(output_dir, "metrics.json")
    with open(out_path, "w") as f:
        json.dump(_sanitize_nans(metrics), f, indent=2)
    logger.info("Saved metrics → %s", out_path)

    return metrics
