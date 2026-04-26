"""
Convert Pegasus sidewalk observations into inventory findings.

This module no longer treats observations as POI discrepancies. Instead it
emits one or more sidewalk findings per sequence, optionally linked to the
nearest Overture transportation segment when that dataset is available.
"""

import json
import logging
import os
import re
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

TRANSPORT_MATCH_RADIUS_M = POI_MATCH_RADIUS_M


def load_descriptions(data_dir: str = DATA_PROCESSED) -> list[dict]:
    path = os.path.join(data_dir, "descriptions.json")
    with open(path) as f:
        return json.load(f)


def _output_columns() -> list[str]:
    return [
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


def _empty_detections_gdf() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {column: pd.Series(dtype="object") for column in _output_columns()},
        geometry=gpd.GeoSeries([], crs=WGS84_CRS),
        crs=WGS84_CRS,
    )


def _normalize_label(value: str) -> str:
    label = re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower()).strip("_")
    return label or "unknown"


def _string_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [str(v).strip() for v in parsed if str(v).strip()]
        return [item.strip() for item in text.split(",") if item.strip()]
    return [str(value).strip()] if str(value).strip() else []


def descriptions_to_gdf(descriptions: list[dict]) -> gpd.GeoDataFrame:
    rows = []
    for d in descriptions:
        if d.get("lat") is None or d.get("lon") is None:
            continue
        rows.append(
            {
                "obs_id": d["sequence_id"],
                "name": d.get("name", "sidewalk_segment"),
                "category": d.get("category", "sidewalk"),
                "condition": d.get("condition", "unknown"),
                "description": d.get("description", ""),
                "sidewalk_presence": d.get("sidewalk_presence", "unclear"),
                "sidewalk_width_m": d.get("sidewalk_width_m"),
                "width_category": d.get("width_category", "unknown"),
                "curb_ramp_status": d.get("curb_ramp_status", "unclear"),
                "surface_material": d.get("surface_material", "unknown"),
                "surface_defects": _string_list(d.get("surface_defects")),
                "lighting": d.get("lighting", "unknown"),
                "obstructions": _string_list(d.get("obstructions")),
                "hazards": _string_list(d.get("hazards")),
                "crossing_features": _string_list(d.get("crossing_features")),
                "clip_s3_uri": d.get("clip_s3_uri", ""),
                "frame_ids": json.dumps(d.get("frame_ids", [])),
                "lat": d["lat"],
                "lon": d["lon"],
                "geometry": Point(d["lon"], d["lat"]),
            }
        )
    if not rows:
        return gpd.GeoDataFrame(geometry=gpd.GeoSeries([], crs=WGS84_CRS))
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=WGS84_CRS)


def observation_confidence(row: pd.Series) -> float:
    score = 0.55
    if row.get("sidewalk_presence") in {"present", "absent"}:
        score += 0.15
    if row.get("sidewalk_width_m") is not None:
        score += 0.05
    if row.get("curb_ramp_status") in {"present", "absent", "not_applicable"}:
        score += 0.05
    if row.get("obstructions"):
        score += 0.05
    if row.get("hazards"):
        score += 0.05
    if row.get("crossing_features"):
        score += 0.05
    return round(min(score, 0.95), 3)


def classify_observation(row: pd.Series) -> list[str]:
    findings: list[str] = []
    presence = (row.get("sidewalk_presence") or "unclear").lower()
    condition = (row.get("condition") or "unknown").lower()
    curb_ramp_status = (row.get("curb_ramp_status") or "unclear").lower()
    width_category = (row.get("width_category") or "unknown").lower()
    lighting = (row.get("lighting") or "unknown").lower()
    surface_material = (row.get("surface_material") or "unknown").lower()
    obstructions = [_normalize_label(v) for v in row.get("obstructions") or []]
    hazards = [_normalize_label(v) for v in row.get("hazards") or []]
    surface_defects = [_normalize_label(v) for v in row.get("surface_defects") or []]
    crossing_features = [_normalize_label(v) for v in row.get("crossing_features") or []]

    # Sidewalk presence — skip "unclear" to avoid flooding the map with low-signal points
    if presence == "absent":
        findings.append("sidewalk_missing")
    elif presence == "present":
        findings.append("sidewalk_present")
    # presence == "unclear" → no finding emitted

    # Curb ramp issues
    if curb_ramp_status == "absent":
        findings.append("curb_ramp_missing")
    elif curb_ramp_status == "present_noncompliant":
        findings.append("ada_noncompliant_ramp")

    # Walkway condition
    if condition == "poor":
        findings.append("poor_condition")
    elif condition == "blocked":
        findings.append("blocked_path")
    elif condition == "under_construction":
        findings.append("construction")
    elif condition == "fair":
        findings.append("fair_condition")

    # Narrow sidewalk (ADA minimum is 1.2 m / 4 ft)
    if presence == "present" and width_category == "narrow":
        findings.append("narrow_sidewalk")

    # Obstructions blocking the path
    if obstructions:
        findings.append("obstruction")

    # Surface defects (cracking, heaving, vegetation encroachment, etc.)
    if surface_defects:
        findings.append("surface_defect")

    # Specific hazards
    if any("pothole" in hazard for hazard in hazards):
        findings.append("pothole")
    if any(
        hazard in {"uneven_surface", "broken_pavement", "trip_hazard", "surface_damage"}
        for hazard in hazards
    ):
        findings.append("surface_hazard")
    if any(hazard in {"construction_zone", "construction"} for hazard in hazards):
        findings.append("construction")
    if any(hazard in {"debris", "standing_water", "ice", "flooding"} for hazard in hazards):
        findings.append("hazard")

    # Unpaved / informal surface material
    if presence == "present" and surface_material in {"gravel", "dirt"}:
        findings.append("unpaved_surface")

    # Inadequate lighting
    if lighting == "inadequate":
        findings.append("poor_lighting")

    # Intersection visible (curb ramp assessed) but no pedestrian crossing markings detected
    if curb_ramp_status in {"absent", "present_noncompliant"} and not crossing_features:
        findings.append("missing_crossing_features")

    deduped: list[str] = []
    for finding in findings:
        if finding not in deduped:
            deduped.append(finding)
    return deduped


def _transport_columns(transport_segments: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    cols = [col for col in ["id", "name", "class", "subclass", "geometry"] if col in transport_segments.columns]
    return transport_segments[cols]


def cross_reference(
    descriptions: list[dict],
    transport_segments: Optional[gpd.GeoDataFrame] = None,
    match_radius_m: float = TRANSPORT_MATCH_RADIUS_M,
) -> gpd.GeoDataFrame:
    obs_gdf = descriptions_to_gdf(descriptions)
    if obs_gdf.empty:
        logger.warning("No observations with valid coordinates")
        return _empty_detections_gdf()

    joined = obs_gdf.copy()
    if transport_segments is not None and not transport_segments.empty:
        obs_utm = obs_gdf.to_crs(UTM_CRS)
        transport_utm = _transport_columns(transport_segments).to_crs(UTM_CRS)
        joined = gpd.sjoin_nearest(
            obs_utm,
            transport_utm,
            how="left",
            max_distance=match_radius_m,
            distance_col="match_distance_m",
            rsuffix="transport",
        ).to_crs(WGS84_CRS)
    else:
        joined["match_distance_m"] = None

    rows = []
    for _, row in joined.iterrows():
        findings = classify_observation(row)
        confidence = observation_confidence(row)
        transport_id = row.get("id")
        transport_name = row.get("name_transport", row.get("name_right", ""))
        transport_class = row.get("class", "")
        if not isinstance(transport_name, str):
            transport_name = ""
        if not isinstance(transport_class, str):
            transport_class = ""

        for finding_index, finding in enumerate(findings):
            rows.append(
                {
                    "obs_id": f"{row['obs_id']}:{finding_index}",
                    "detection_type": finding,
                    "confidence": confidence,
                    "obs_name": row.get("name", "sidewalk_segment"),
                    "obs_category": row.get("category", "sidewalk"),
                    "obs_condition": row.get("condition", "unknown"),
                    "obs_description": row.get("description", ""),
                    "sidewalk_presence": row.get("sidewalk_presence", "unclear"),
                    "sidewalk_width_m": row.get("sidewalk_width_m"),
                    "curb_ramp_status": row.get("curb_ramp_status", "unclear"),
                    "obstructions": json.dumps(row.get("obstructions", [])),
                    "hazards": json.dumps(row.get("hazards", [])),
                    "crossing_features": json.dumps(row.get("crossing_features", [])),
                    "transport_id": "" if transport_id is None or (isinstance(transport_id, float) and pd.isna(transport_id)) else str(transport_id),
                    "transport_name": transport_name,
                    "transport_class": transport_class,
                    "match_distance_m": row.get("match_distance_m"),
                    "clip_s3_uri": row.get("clip_s3_uri", ""),
                    "frame_ids": row.get("frame_ids", "[]"),
                    "lat": row.get("lat"),
                    "lon": row.get("lon"),
                    "geometry": Point(row["lon"], row["lat"]),
                }
            )

    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=WGS84_CRS)
    logger.info(
        "Inventory analysis complete: %d findings (%s)",
        len(gdf),
        ", ".join(f"{t}={n}" for t, n in gdf["detection_type"].value_counts().items()),
    )
    return gdf
