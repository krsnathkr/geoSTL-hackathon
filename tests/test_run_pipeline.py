import json
import os
from unittest.mock import patch

import geopandas as gpd
import pytest
from shapely.geometry import Point

from run_pipeline import _selected_stages, collect_local_frames, run_pipeline
from config.settings import WGS84_CRS


def test_selected_stages_range():
    assert _selected_stages("ingest", "analyze") == ["ingest", "embed", "describe", "analyze"]
    assert _selected_stages("describe", "analyze") == ["describe", "analyze"]


def test_collect_local_frames_filters_missing_files(tmp_path):
    images_dir = tmp_path / "images"
    seq_dir = images_dir / "seq-1"
    seq_dir.mkdir(parents=True)
    frame_path = seq_dir / "f1.jpg"
    frame_path.write_bytes(b"jpg")

    sequences = [
        {
            "sequence_id": "seq-1",
            "frames": [
                {"id": "f1", "lat": 37.77, "lon": -122.42, "bearing": 10, "timestamp": "t1"},
                {"id": "f2", "lat": 37.78, "lon": -122.43, "bearing": 20, "timestamp": "t2"},
            ],
        }
    ]

    frames = collect_local_frames(sequences, str(images_dir))
    assert len(frames) == 1
    assert frames[0]["id"] == "f1"
    assert frames[0]["local_path"] == str(frame_path)


@patch("run_pipeline.compute_and_save")
@patch("run_pipeline.export_all")
@patch("run_pipeline.cross_reference")
@patch("run_pipeline.load_places")
@patch("run_pipeline.load_json_artifact")
@patch("run_pipeline.load_descriptions")
def test_run_pipeline_analyze_only(
    mock_load_descriptions,
    mock_load_json_artifact,
    mock_load_places,
    mock_cross_reference,
    mock_export_all,
    mock_compute_and_save,
    tmp_path,
):
    raw_dir = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    output_dir = tmp_path / "output"
    raw_dir.mkdir()
    processed_dir.mkdir()
    output_dir.mkdir()

    mock_load_descriptions.return_value = [{"sequence_id": "seq-1", "lat": 37.77, "lon": -122.42}]
    mock_load_json_artifact.return_value = [{"sequence_id": "seq-1", "lat": 37.77, "lon": -122.42}]
    mock_load_places.return_value = gpd.GeoDataFrame(
        [{"id": "gers-001", "name": "Blue Bottle", "category": "cafe", "geometry": Point(-122.42, 37.77)}],
        geometry="geometry",
        crs=WGS84_CRS,
    )
    mock_cross_reference.side_effect = [
        gpd.GeoDataFrame(
            [{"obs_id": "seq-1", "detection_type": "stale", "lat": 37.77, "lon": -122.42}],
            geometry=[Point(-122.42, 37.77)],
            crs=WGS84_CRS,
        ),
        gpd.GeoDataFrame(
            [{"obs_id": "seq-1", "detection_type": "validated", "lat": 37.77, "lon": -122.42}],
            geometry=[Point(-122.42, 37.77)],
            crs=WGS84_CRS,
        ),
    ]
    mock_export_all.return_value = {
        "geojson": str(output_dir / "detections.geojson"),
        "geoparquet": str(output_dir / "detections.geoparquet"),
    }
    mock_compute_and_save.return_value = {
        "type_counts": {"stale": 1},
        "temporal_advantage": {"delta": 1},
    }

    result = run_pipeline(
        from_stage="analyze",
        to_stage="analyze",
        data_raw_dir=str(raw_dir),
        data_processed_dir=str(processed_dir),
        data_output_dir=str(output_dir),
    )

    assert result["status"] == "ok"
    assert result["detections"] == 1
    assert result["baseline_detections"] == 1
    assert result["type_counts"] == {"stale": 1}
    assert result["has_temporal_advantage"] is True
    assert mock_compute_and_save.call_args.kwargs["baseline_detections"] is not None


@patch("run_pipeline.download_frames")
@patch("run_pipeline.fetch_sequences")
@patch("run_pipeline.fetch_transportation")
@patch("run_pipeline.fetch_places")
def test_run_pipeline_ingest_only(
    mock_fetch_places,
    mock_fetch_transportation,
    mock_fetch_sequences,
    mock_download_frames,
    tmp_path,
):
    raw_dir = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    output_dir = tmp_path / "output"
    raw_dir.mkdir()
    processed_dir.mkdir()
    output_dir.mkdir()

    mock_fetch_sequences.return_value = [{"sequence_id": "seq-1", "frames": []}]

    result = run_pipeline(
        from_stage="ingest",
        to_stage="ingest",
        data_raw_dir=str(raw_dir),
        data_processed_dir=str(processed_dir),
        data_output_dir=str(output_dir),
    )

    assert result["status"] == "ok"
    assert result["stages"] == ["ingest"]
    mock_fetch_places.assert_called_once()
    mock_fetch_transportation.assert_called_once()
    mock_fetch_sequences.assert_called_once()
    mock_download_frames.assert_called_once()
    assert mock_download_frames.call_args.kwargs["overwrite_existing"] is False


@patch("run_pipeline.download_frames")
@patch("run_pipeline.fetch_sequences")
@patch("run_pipeline.fetch_transportation")
@patch("run_pipeline.fetch_places")
def test_run_pipeline_ingest_only_skip_transportation(
    mock_fetch_places,
    mock_fetch_transportation,
    mock_fetch_sequences,
    mock_download_frames,
    tmp_path,
):
    raw_dir = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    output_dir = tmp_path / "output"
    raw_dir.mkdir()
    processed_dir.mkdir()
    output_dir.mkdir()

    mock_fetch_sequences.return_value = [{"sequence_id": "seq-1", "frames": []}]

    result = run_pipeline(
        from_stage="ingest",
        to_stage="ingest",
        data_raw_dir=str(raw_dir),
        data_processed_dir=str(processed_dir),
        data_output_dir=str(output_dir),
        skip_transportation=True,
    )

    assert result["status"] == "ok"
    mock_fetch_places.assert_called_once()
    mock_fetch_transportation.assert_not_called()
    mock_fetch_sequences.assert_called_once()
    mock_download_frames.assert_called_once()


@patch("run_pipeline.download_frames")
@patch("run_pipeline.fetch_sequences")
@patch("run_pipeline.fetch_transportation")
@patch("run_pipeline.fetch_places")
def test_run_pipeline_ingest_can_redownload_frames(
    mock_fetch_places,
    mock_fetch_transportation,
    mock_fetch_sequences,
    mock_download_frames,
    tmp_path,
):
    raw_dir = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    output_dir = tmp_path / "output"
    raw_dir.mkdir()
    processed_dir.mkdir()
    output_dir.mkdir()

    mock_fetch_sequences.return_value = [{"sequence_id": "seq-1", "frames": []}]

    result = run_pipeline(
        from_stage="ingest",
        to_stage="ingest",
        data_raw_dir=str(raw_dir),
        data_processed_dir=str(processed_dir),
        data_output_dir=str(output_dir),
        redownload_frames=True,
        skip_transportation=True,
    )

    assert result["status"] == "ok"
    mock_fetch_places.assert_called_once()
    mock_fetch_transportation.assert_not_called()
    assert mock_download_frames.call_args.kwargs["overwrite_existing"] is True


@patch("run_pipeline.save_indexed_manifest")
@patch("run_pipeline.index_frames_bulk")
@patch("run_pipeline.ensure_index")
@patch("run_pipeline.embed_frames_batch")
@patch("run_pipeline.load_sequences")
def test_run_pipeline_embed_continues_when_index_unavailable(
    mock_load_sequences,
    mock_embed_frames_batch,
    mock_ensure_index,
    mock_index_frames_bulk,
    mock_save_indexed_manifest,
    tmp_path,
    caplog,
):
    raw_dir = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    output_dir = tmp_path / "output"
    images_dir = raw_dir / "images" / "seq-1"
    images_dir.mkdir(parents=True)
    processed_dir.mkdir()
    output_dir.mkdir()

    frame_path = images_dir / "f1.jpg"
    frame_path.write_bytes(b"jpg")

    mock_load_sequences.return_value = [
        {
            "sequence_id": "seq-1",
            "frames": [
                {"id": "f1", "lat": 37.77, "lon": -122.42, "bearing": 10, "timestamp": "t1"},
            ],
        }
    ]
    mock_embed_frames_batch.return_value = [
        {
            "id": "f1",
            "sequence_id": "seq-1",
            "lat": 37.77,
            "lon": -122.42,
            "timestamp": "t1",
            "local_path": str(frame_path),
            "embedding": [0.1, 0.2],
        }
    ]
    mock_ensure_index.side_effect = RuntimeError("AuthenticationException(401)")

    with caplog.at_level("WARNING"):
        result = run_pipeline(
            from_stage="embed",
            to_stage="embed",
            data_raw_dir=str(raw_dir),
            data_processed_dir=str(processed_dir),
            data_output_dir=str(output_dir),
        )

    assert result["status"] == "ok"
    assert result["stages"] == ["embed"]
    assert "vector index unavailable" in caplog.text
    mock_index_frames_bulk.assert_not_called()
    mock_save_indexed_manifest.assert_not_called()
