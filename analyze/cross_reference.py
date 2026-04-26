"""
Cross-reference Pegasus observations against Overture Places.

Classification rules:
  missing        — observation is open, no Overture match within 50 m
  stale          — observation is closed/vacant, Overture match exists
  miscategorized — Overture match exists but categories diverge
  validated      — Overture match exists and categories agree (no discrepancy)
"""

import json
import logging
import os
from difflib import SequenceMatcher
from typing import Optional

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from config.settings import (
    DATA_PROCESSED,
    POI_MATCH_RADIUS_M,
    UTM_CRS,
    WGS84_CRS,
)

logger = logging.getLogger(__name__)

# Map Pegasus category labels → Overture primary category substrings
CATEGORY_MAP: dict[str, list[str]] = {
    "restaurant": ["restaurant", "food", "dining", "eat"],
    "cafe": ["cafe", "coffee", "tea", "bakery"],
    "bar": ["bar", "pub", "nightlife", "brewery", "tavern"],
    "retail": ["retail", "shop", "store", "market", "boutique"],
    "hotel": ["hotel", "motel", "lodging", "inn", "hostel"],
    "office": ["office", "professional", "financial", "bank"],
    "service": ["service", "salon", "spa", "laundry", "repair", "gym", "fitness"],
    "other": [],
}

CLOSED_CONDITIONS = {"closed", "vacant", "under_construction"}
OPEN_CONDITIONS = {"open"}


def load_descriptions(data_dir: str = DATA_PROCESSED) -> list[dict]:
    path = os.path.join(data_dir, "descriptions.json")
    with open(path) as f:
        return json.load(f)


def _empty_detections_gdf() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {column: pd.Series(dtype="object") for column in _output_columns()},
        geometry=gpd.GeoSeries([], crs=WGS84_CRS),
        crs=WGS84_CRS,
    )


def descriptions_to_gdf(descriptions: list[dict]) -> gpd.GeoDataFrame:
    """Convert Pegasus description dicts to a GeoDataFrame (WGS84)."""
    rows = []
    for d in descriptions:
        if d.get("lat") is None or d.get("lon") is None:
            continue
        rows.append({
            "obs_id": d["sequence_id"],
            "name": d.get("name", ""),
            "category": d.get("category", "other"),
            "condition": d.get("condition", "unknown"),
            "description": d.get("description", ""),
            "clip_s3_uri": d.get("clip_s3_uri", ""),
            "frame_ids": json.dumps(d.get("frame_ids", [])),
            "lat": d["lat"],
            "lon": d["lon"],
            "geometry": Point(d["lon"], d["lat"]),
        })
    if not rows:
        return gpd.GeoDataFrame(geometry=gpd.GeoSeries([], crs=WGS84_CRS))
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=WGS84_CRS)


def _categories_match(obs_category: str, overture_category: str) -> bool:
    """Return True if Pegasus category is compatible with Overture category string."""
    ov = (overture_category or "").lower()
    synonyms = CATEGORY_MAP.get(obs_category, [])
    return any(s in ov for s in synonyms)


def _name_similarity(a: str, b: str) -> float:
    if not isinstance(a, str) or not isinstance(b, str) or not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _confidence(distance_m: float, name_sim: float, match_radius: float) -> float:
    """Combine proximity and name similarity into a [0, 1] confidence score."""
    if distance_m is None or pd.isna(distance_m):
        return round(0.5 * name_sim, 3)
    prox = max(0.0, 1.0 - distance_m / match_radius)
    return round(0.6 * prox + 0.4 * name_sim, 3)


def classify_detection(
    obs_name: str,
    obs_category: str,
    obs_condition: str,
    overture_name: Optional[str],
    overture_category: Optional[str],
    distance_m: Optional[float],
    match_radius: float = POI_MATCH_RADIUS_M,
) -> tuple[str, float]:
    """
    Return (detection_type, confidence_score).

    detection_type: "missing" | "stale" | "miscategorized" | "validated"
    """
    has_match = distance_m is not None and not pd.isna(distance_m)
    name_sim = _name_similarity(obs_name, overture_name or "")

    if not has_match:
        # No Overture POI nearby
        if obs_condition in OPEN_CONDITIONS:
            return "missing", round(0.55 + 0.15 * (name_sim == 0), 3)
        return "stale", 0.5  # might have existed and closed

    # Overture match found
    conf = _confidence(distance_m, name_sim, match_radius)
    if obs_condition in CLOSED_CONDITIONS:
        return "stale", conf
    if not _categories_match(obs_category, overture_category or ""):
        return "miscategorized", conf
    return "validated", conf


def cross_reference(
    descriptions: list[dict],
    overture_places: gpd.GeoDataFrame,
    match_radius_m: float = POI_MATCH_RADIUS_M,
) -> gpd.GeoDataFrame:
    """
    Spatial-join observations to Overture Places, classify each detection.

    Returns a GeoDataFrame in WGS84 with one row per observation.
    """
    obs_gdf = descriptions_to_gdf(descriptions)
    if obs_gdf.empty:
        logger.warning("No observations with valid coordinates")
        return _empty_detections_gdf()

    # Project to UTM for metre-accurate proximity matching
    obs_utm = obs_gdf.to_crs(UTM_CRS)
    ov_utm = overture_places[["id", "name", "category", "geometry"]].to_crs(UTM_CRS)

    joined = gpd.sjoin_nearest(
        obs_utm,
        ov_utm,
        how="left",
        max_distance=match_radius_m,
        distance_col="distance_m",
        rsuffix="ov",
    )
    # sjoin_nearest renames conflicting obs columns; normalise back to plain names
    rename = {}
    for suffix in ("_left", "_"):
        if f"name{suffix}" in joined.columns:
            rename[f"name{suffix}"] = "name"
        if f"category{suffix}" in joined.columns:
            rename[f"category{suffix}"] = "category"
    if rename:
        joined = joined.rename(columns=rename)

    rows = []
    for _, row in joined.iterrows():
        ov_name_raw = row.get("name_ov")
        ov_cat_raw = row.get("category_ov")
        det_type, conf = classify_detection(
            obs_name=row.get("name", ""),
            obs_category=row.get("category", ""),
            obs_condition=row.get("condition", "unknown"),
            overture_name=ov_name_raw if isinstance(ov_name_raw, str) else None,
            overture_category=ov_cat_raw if isinstance(ov_cat_raw, str) else None,
            distance_m=row.get("distance_m"),
            match_radius=match_radius_m,
        )
        # After sjoin_nearest with rsuffix="ov":
        #   obs columns keep their names; overture 'name'/'category' → 'name_ov'/'category_ov'
        #   overture 'id' has no conflict so stays as 'id'
        raw_id = row.get("id")
        gers = "" if (raw_id is None or (isinstance(raw_id, float) and pd.isna(raw_id))) else str(raw_id)
        ov_name = row.get("name_ov", "")
        ov_cat = row.get("category_ov", "")
        rows.append({
            "obs_id": row["obs_id"],
            "detection_type": det_type,
            "confidence": conf,
            "obs_name": row.get("name", ""),
            "obs_category": row.get("category", ""),
            "obs_condition": row.get("condition", "unknown"),
            "obs_description": row.get("description", ""),
            "gers_id": gers,
            "overture_name": ov_name if isinstance(ov_name, str) else "",
            "overture_category": ov_cat if isinstance(ov_cat, str) else "",
            "distance_m": row.get("distance_m"),
            "clip_s3_uri": row.get("clip_s3_uri", ""),
            "frame_ids": row.get("frame_ids", "[]"),
            "lat": row.get("lat"),
            "lon": row.get("lon"),
            "geometry": Point(row["lon"], row["lat"]),
        })

    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=WGS84_CRS)
    logger.info(
        "Cross-reference complete: %d total (%s)",
        len(gdf),
        ", ".join(f"{t}={n}" for t, n in gdf["detection_type"].value_counts().items()),
    )
    return gdf


def _output_columns() -> list[str]:
    return [
        "obs_id", "detection_type", "confidence", "obs_name", "obs_category",
        "obs_condition", "obs_description", "gers_id", "overture_name", "overture_category",
        "distance_m", "clip_s3_uri", "frame_ids", "lat", "lon",
    ]
