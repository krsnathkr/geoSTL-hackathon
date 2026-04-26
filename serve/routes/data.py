import json
import os
from typing import Any

from fastapi import APIRouter


def build_router(data_raw_dir: str, data_output_dir: str) -> APIRouter:
    router = APIRouter()

    detections_path = os.path.join(data_output_dir, "detections.geojson")
    baseline_detections_path = os.path.join(data_output_dir, "baseline_detections.geojson")
    metrics_path = os.path.join(data_output_dir, "metrics.json")
    sequences_path = os.path.join(data_raw_dir, "mapillary_sequences.json")

    @router.get("/detections")
    def get_detections() -> dict[str, Any]:
        return load_detections_geojson(detections_path)

    @router.get("/baseline-detections")
    def get_baseline_detections() -> dict[str, Any]:
        return load_detections_geojson(
            baseline_detections_path,
            dataset_name="baseline_detections",
        )

    @router.get("/metrics")
    def get_metrics() -> dict[str, Any]:
        return load_metrics(metrics_path)

    @router.get("/sequences")
    def get_sequences() -> dict[str, Any]:
        return load_sequences_geojson(sequences_path)

    @router.get("/comparison")
    def get_comparison() -> dict[str, Any]:
        detections = load_detections_geojson(detections_path)
        baseline_detections = load_detections_geojson(
            baseline_detections_path,
            dataset_name="baseline_detections",
        )
        metrics = load_metrics(metrics_path)
        return build_comparison_payload(detections, baseline_detections, metrics)

    return router


def load_detections_geojson(path: str, dataset_name: str = "detections") -> dict[str, Any]:
    if not os.path.exists(path):
        return empty_feature_collection(
            {"dataset": dataset_name, "status": "missing", "path": path}
        )

    with open(path) as fh:
        data = json.load(fh)

    if data.get("type") != "FeatureCollection":
        raise ValueError(f"Invalid detections GeoJSON at {path}")

    metadata = dict(data.get("metadata", {}))
    metadata.setdefault("dataset", dataset_name)
    metadata["status"] = "ready"
    data["metadata"] = metadata
    data.setdefault("features", [])
    return data


def load_metrics(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return {
            "status": "missing",
            "dataset": "metrics",
            "path": path,
            "type_counts": {},
            "total_detections": 0,
            "discrepancy_count": 0,
        }

    with open(path) as fh:
        data = json.load(fh)

    data["status"] = "ready"
    data.setdefault("dataset", "metrics")
    return data


def build_comparison_payload(
    detections: dict[str, Any],
    baseline_detections: dict[str, Any],
    metrics: dict[str, Any],
) -> dict[str, Any]:
    video_counts = count_detection_types(detections.get("features", []))
    baseline_counts = count_detection_types(baseline_detections.get("features", []))
    temporal_advantage = metrics.get("temporal_advantage", {})

    by_type = []
    detection_types = sorted(set(video_counts) | set(baseline_counts))
    for detection_type in detection_types:
        video_count = video_counts.get(detection_type, 0)
        baseline_count = baseline_counts.get(detection_type, 0)
        by_type.append(
            {
                "detection_type": detection_type,
                "video_count": video_count,
                "baseline_count": baseline_count,
                "delta": video_count - baseline_count,
            }
        )

    return {
        "status": comparison_status(
            detections.get("metadata", {}).get("status"),
            baseline_detections.get("metadata", {}).get("status"),
            metrics.get("status"),
        ),
        "video_discrepancies": temporal_advantage.get(
            "video_discrepancies",
            sum(video_counts.values()),
        ),
        "baseline_discrepancies": temporal_advantage.get(
            "baseline_discrepancies",
            sum(baseline_counts.values()),
        ),
        "delta": temporal_advantage.get(
            "delta",
            sum(video_counts.values()) - sum(baseline_counts.values()),
        ),
        "confidence_delta": temporal_advantage.get("confidence_delta"),
        "by_type": by_type,
    }


def load_sequences_geojson(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return empty_feature_collection(
            {"dataset": "sequences", "status": "missing", "path": path}
        )

    with open(path) as fh:
        sequences = json.load(fh)

    features = []
    for sequence in sequences:
        frames = sequence.get("frames", [])
        coordinates = [
            [frame.get("lon"), frame.get("lat")]
            for frame in frames
            if frame.get("lon") is not None and frame.get("lat") is not None
        ]
        if len(coordinates) < 2:
            continue

        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coordinates},
                "properties": {
                    "sequence_id": sequence.get("sequence_id", ""),
                    "frame_count": len(frames),
                    "start_timestamp": frames[0].get("timestamp", "") if frames else "",
                    "end_timestamp": frames[-1].get("timestamp", "") if frames else "",
                },
            }
        )

    return empty_feature_collection(
        {
            "dataset": "sequences",
            "status": "ready",
            "sequence_count": len(features),
        },
        features,
    )


def empty_feature_collection(
    metadata: dict[str, Any] | None = None,
    features: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "metadata": metadata or {},
        "features": features or [],
    }


def count_detection_types(features: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for feature in features:
        detection_type = feature.get("properties", {}).get("detection_type")
        if not detection_type:
            continue
        counts[detection_type] = counts.get(detection_type, 0) + 1
    return counts


def comparison_status(*statuses: Any) -> str:
    return "ready" if all(status == "ready" for status in statuses) else "partial"
