import json

from fastapi.testclient import TestClient

from serve.main import create_app


def _write_json(path, payload):
    with open(path, "w") as fh:
        json.dump(payload, fh)


def test_api_returns_pipeline_outputs(tmp_path):
    raw_dir = tmp_path / "raw"
    output_dir = tmp_path / "output"
    raw_dir.mkdir()
    output_dir.mkdir()

    _write_json(
        output_dir / "detections.geojson",
        {
            "type": "FeatureCollection",
            "metadata": {"overture_release": "2026-04-15.0"},
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-122.42, 37.77]},
                    "properties": {
                        "obs_name": "Blue Bottle",
                        "detection_type": "stale",
                        "obs_condition": "closed",
                        "confidence": 0.82,
                        "gers_id": "gers-001",
                        "overture_name": "Blue Bottle Coffee",
                        "clip_s3_uri": "s3://bucket/clip.mp4",
                    },
                }
            ],
        },
    )
    _write_json(
        output_dir / "metrics.json",
        {
            "type_counts": {"stale": 1},
            "total_detections": 1,
            "discrepancy_count": 1,
            "rmse_m": 8.5,
            "temporal_advantage": {
                "video_discrepancies": 2,
                "baseline_discrepancies": 1,
                "delta": 1,
                "confidence_delta": 0.15,
            },
        },
    )
    _write_json(
        output_dir / "baseline_detections.geojson",
        {
            "type": "FeatureCollection",
            "metadata": {"overture_release": "2026-04-15.0"},
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-122.42, 37.77]},
                    "properties": {
                        "obs_name": "Blue Bottle",
                        "detection_type": "missing",
                    },
                }
            ],
        },
    )
    _write_json(
        raw_dir / "mapillary_sequences.json",
        [
            {
                "sequence_id": "seq-1",
                "frames": [
                    {"id": "f1", "lon": -122.42, "lat": 37.77, "timestamp": "2024-01-01T00:00:00Z"},
                    {"id": "f2", "lon": -122.421, "lat": 37.771, "timestamp": "2024-01-01T00:00:05Z"},
                ],
            }
        ],
    )

    client = TestClient(create_app(data_raw_dir=str(raw_dir), data_output_dir=str(output_dir)))

    detections = client.get("/api/detections")
    metrics = client.get("/api/metrics")
    sequences = client.get("/api/sequences")
    baseline_detections = client.get("/api/baseline-detections")
    comparison = client.get("/api/comparison")
    index = client.get("/")

    assert detections.status_code == 200
    assert detections.json()["metadata"]["status"] == "ready"
    assert detections.json()["features"][0]["properties"]["detection_type"] == "stale"

    assert metrics.status_code == 200
    assert metrics.json()["status"] == "ready"
    assert metrics.json()["total_detections"] == 1

    assert sequences.status_code == 200
    assert sequences.json()["features"][0]["geometry"]["type"] == "LineString"
    assert sequences.json()["metadata"]["sequence_count"] == 1

    assert baseline_detections.status_code == 200
    assert baseline_detections.json()["metadata"]["dataset"] == "baseline_detections"

    assert comparison.status_code == 200
    assert comparison.json()["status"] == "ready"
    assert comparison.json()["delta"] == 1
    assert comparison.json()["by_type"][0]["baseline_count"] == 1

    assert index.status_code == 200
    assert "GeoSTL Video Intelligence" in index.text


def test_api_handles_missing_artifacts(tmp_path):
    raw_dir = tmp_path / "raw"
    output_dir = tmp_path / "output"
    raw_dir.mkdir()
    output_dir.mkdir()

    client = TestClient(create_app(data_raw_dir=str(raw_dir), data_output_dir=str(output_dir)))

    detections = client.get("/api/detections").json()
    metrics = client.get("/api/metrics").json()
    sequences = client.get("/api/sequences").json()
    baseline_detections = client.get("/api/baseline-detections").json()
    comparison = client.get("/api/comparison").json()

    assert detections["features"] == []
    assert detections["metadata"]["status"] == "missing"

    assert metrics["status"] == "missing"
    assert metrics["total_detections"] == 0

    assert sequences["features"] == []
    assert sequences["metadata"]["status"] == "missing"

    assert baseline_detections["features"] == []
    assert baseline_detections["metadata"]["status"] == "missing"

    assert comparison["status"] == "partial"
    assert comparison["delta"] == 0
