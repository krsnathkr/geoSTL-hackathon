"""
Export sidewalk inventory findings to GeoJSON and GeoParquet for submission and the web UI.

Outputs:
  data/output/detections.geojson      — GeoJSON FeatureCollection
  data/output/detections.geoparquet   — GeoParquet (Overture-compatible schema)
"""

import hashlib
import json
import logging
import os
from typing import Optional

import geopandas as gpd
import pandas as pd

from config.settings import DATA_OUTPUT, OVERTURE_RELEASE, WGS84_CRS

logger = logging.getLogger(__name__)

NON_ISSUE_TYPES = {"validated", "sidewalk_present", "sidewalk_unclear"}

REQUIRED_PROPERTIES = [
    "detection_id",
    "obs_id",
    "detection_type",
    "confidence",
    "obs_name",
    "obs_category",
    "obs_condition",
    "obs_description",
    "sidewalk_presence",
    "sidewalk_width_m",
    "curb_ramp_status",
    "obstructions",
    "hazards",
    "crossing_features",
    "transport_id",
    "transport_name",
    "transport_class",
    "match_distance_m",
    "clip_s3_uri",
    "frame_ids",
    "lat",
    "lon",
]


def _ensure_required_columns(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    for col in REQUIRED_PROPERTIES:
        if col not in gdf.columns:
            gdf[col] = None
    return gdf


def _exclude_non_issues(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return gdf[~gdf["detection_type"].isin(NON_ISSUE_TYPES)]


def to_geojson(
    detections: gpd.GeoDataFrame,
    output_dir: str = DATA_OUTPUT,
    filename: str = "detections.geojson",
    exclude_validated: bool = False,
) -> str:
    """
    Write detections as a GeoJSON FeatureCollection.

    Returns the path to the written file.
    """
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, filename)

    gdf = detections.copy()
    gdf = _ensure_required_columns(gdf)
    if exclude_validated:
        gdf = _exclude_non_issues(gdf)

    gdf = gdf.to_crs(WGS84_CRS)

    # Serialise frame_ids: stored as JSON string, keep as-is in GeoJSON
    feature_collection = {
        "type": "FeatureCollection",
        "metadata": {
            "overture_release": OVERTURE_RELEASE,
            "crs": "EPSG:4326",
            "detection_types": sorted(gdf["detection_type"].dropna().unique().tolist()),
        },
        "features": [],
    }

    for _, row in gdf.iterrows():
        props = {col: _serialise(row.get(col)) for col in REQUIRED_PROPERTIES}
        # Stable detection_id derived from obs_id so the frontend can reference it
        if not props.get("detection_id"):
            seed = str(props.get("obs_id") or "")
            props["detection_id"] = hashlib.sha256(seed.encode()).hexdigest()[:16]

        feature_collection["features"].append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [row.geometry.x, row.geometry.y],
            },
            "properties": props,
        })

    with open(out_path, "w") as f:
        json.dump(feature_collection, f, indent=2)

    logger.info("Saved GeoJSON → %s (%d features)", out_path, len(gdf))
    return out_path


def to_geoparquet(
    detections: gpd.GeoDataFrame,
    output_dir: str = DATA_OUTPUT,
    filename: str = "detections.geoparquet",
    exclude_validated: bool = False,
) -> str:
    """
    Write detections as GeoParquet using the sidewalk inventory schema.

    Returns the path to the written file.
    """
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, filename)

    gdf = detections.copy()
    gdf = _ensure_required_columns(gdf)
    if exclude_validated:
        gdf = _exclude_non_issues(gdf)

    gdf = gdf.to_crs(WGS84_CRS)

    rename_map = {
        "obs_id": "source_id",
        "obs_name": "observed_name",
        "obs_category": "observed_category",
        "obs_condition": "observed_condition",
    }
    gdf = gdf.rename(columns=rename_map)

    gdf["overture_release"] = OVERTURE_RELEASE
    gdf["schema_version"] = "1.0"

    for list_like in ["frame_ids", "obstructions", "hazards", "crossing_features"]:
        if list_like in gdf.columns:
            gdf[list_like] = gdf[list_like].astype(str)

    drop_cols = [c for c in gdf.columns if c not in [
        "source_id",
        "detection_type",
        "confidence",
        "observed_name",
        "observed_category",
        "observed_condition",
        "obs_description",
        "sidewalk_presence",
        "sidewalk_width_m",
        "curb_ramp_status",
        "obstructions",
        "hazards",
        "crossing_features",
        "transport_id",
        "transport_name",
        "transport_class",
        "match_distance_m",
        "clip_s3_uri",
        "frame_ids",
        "lat",
        "lon",
        "overture_release",
        "schema_version",
        "geometry",
    ]]
    gdf = gdf.drop(columns=drop_cols, errors="ignore")

    gdf.to_parquet(out_path, index=False)
    logger.info("Saved GeoParquet → %s (%d rows)", out_path, len(gdf))
    return out_path


def export_all(
    detections: gpd.GeoDataFrame,
    output_dir: str = DATA_OUTPUT,
    exclude_validated: bool = True,
) -> dict[str, str]:
    """Write both GeoJSON and GeoParquet. Returns {format: path}."""
    paths = {
        "geojson": to_geojson(detections, output_dir, exclude_validated=exclude_validated),
        "geoparquet": to_geoparquet(detections, output_dir, exclude_validated=exclude_validated),
    }
    return paths


def load_detections(data_dir: str = DATA_OUTPUT) -> gpd.GeoDataFrame:
    """Load previously exported GeoParquet detections."""
    path = os.path.join(data_dir, "detections.geoparquet")
    return gpd.read_parquet(path)


def _serialise(val):
    """Make a value safe for JSON serialisation."""
    if val is None:
        return None
    if isinstance(val, float) and (val != val):  # NaN
        return None
    if hasattr(val, "item"):  # numpy scalar
        return val.item()
    return val
