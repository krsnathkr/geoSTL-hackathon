"""
Export detections to GeoJSON and GeoParquet for submission and the web UI.

Outputs:
  data/output/detections.geojson      — GeoJSON FeatureCollection
  data/output/detections.geoparquet   — GeoParquet (Overture-compatible schema)
"""

import json
import logging
import os
from typing import Optional

import geopandas as gpd
import pandas as pd

from config.settings import DATA_OUTPUT, OVERTURE_RELEASE, WGS84_CRS

logger = logging.getLogger(__name__)

# Required properties per GeoJSON feature (Overture contribution format)
REQUIRED_PROPERTIES = [
    "obs_id",
    "detection_type",
    "confidence",
    "obs_name",
    "obs_category",
    "obs_condition",
    "gers_id",
    "overture_name",
    "overture_category",
    "distance_m",
    "clip_s3_uri",
    "frame_ids",
    "lat",
    "lon",
]


def to_geojson(
    detections: gpd.GeoDataFrame,
    output_dir: str = DATA_OUTPUT,
    filename: str = "detections.geojson",
    exclude_validated: bool = False,
) -> str:
    """
    Write detections as a GeoJSON FeatureCollection.

    exclude_validated: omit 'validated' rows (no discrepancy) to keep file small.
    Returns the path to the written file.
    """
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, filename)

    gdf = detections.copy()
    if exclude_validated:
        gdf = gdf[gdf["detection_type"] != "validated"]

    gdf = gdf.to_crs(WGS84_CRS)

    # Ensure all required columns exist (fill missing with None)
    for col in REQUIRED_PROPERTIES:
        if col not in gdf.columns:
            gdf[col] = None

    # Serialise frame_ids: stored as JSON string, keep as-is in GeoJSON
    feature_collection = {
        "type": "FeatureCollection",
        "metadata": {
            "overture_release": OVERTURE_RELEASE,
            "crs": "EPSG:4326",
            "detection_types": ["missing", "stale", "miscategorized"],
        },
        "features": [],
    }

    for _, row in gdf.iterrows():
        props = {col: _serialise(row.get(col)) for col in REQUIRED_PROPERTIES}

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
    Write detections as GeoParquet conforming to Overture's schema extension.

    Returns the path to the written file.
    """
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, filename)

    gdf = detections.copy()
    if exclude_validated:
        gdf = gdf[gdf["detection_type"] != "validated"]

    gdf = gdf.to_crs(WGS84_CRS)

    # Rename to Overture-compatible column names
    rename_map = {
        "obs_id": "source_id",
        "detection_type": "discrepancy_type",
        "obs_name": "observed_name",
        "obs_category": "observed_category",
        "obs_condition": "observed_condition",
        "gers_id": "overture_id",
        "distance_m": "match_distance_m",
    }
    gdf = gdf.rename(columns=rename_map)

    # Add Overture metadata columns
    gdf["overture_release"] = OVERTURE_RELEASE
    gdf["schema_version"] = "1.0"

    # Ensure frame_ids is a string (list stored as JSON)
    if "frame_ids" in gdf.columns:
        gdf["frame_ids"] = gdf["frame_ids"].astype(str)

    # Drop columns that break parquet schema
    drop_cols = [c for c in gdf.columns if c not in [
        "source_id", "discrepancy_type", "confidence", "observed_name",
        "observed_category", "observed_condition", "overture_id",
        "overture_name", "overture_category", "match_distance_m",
        "clip_s3_uri", "frame_ids", "lat", "lon",
        "overture_release", "schema_version", "geometry",
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
