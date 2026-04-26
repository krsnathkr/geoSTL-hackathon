"""Unit tests for ingest/mapillary.py — mocks HTTP so no API calls are made."""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
import requests

from ingest.mapillary import (
    _iter_bbox_tiles,
    _get_with_retry,
    _group_by_sequence,
    _parse_frame,
    download_frames,
    fetch_sequences,
    load_sequences,
)

RAW_FRAME = {
    "id": "img-001",
    "geometry": {"type": "Point", "coordinates": [-122.42, 37.77]},
    "captured_at": "2024-03-15T10:00:00Z",
    "sequence_id": "seq-abc",
    "compass_angle": 90.0,
    "thumb_original_url": "https://cdn.mapillary.com/img-001-original.jpg",
    "thumb_2048_url": "https://cdn.mapillary.com/img-001.jpg",
}

RAW_FRAME_2 = {
    "id": "img-002",
    "geometry": {"type": "Point", "coordinates": [-122.43, 37.78]},
    "captured_at": "2024-03-15T10:00:05Z",
    "sequence_id": "seq-abc",
    "compass_angle": 91.0,
    "thumb_original_url": "https://cdn.mapillary.com/img-002-original.jpg",
    "thumb_2048_url": "https://cdn.mapillary.com/img-002.jpg",
}


def test_parse_frame():
    frame = _parse_frame(RAW_FRAME)
    assert frame["id"] == "img-001"
    assert frame["lon"] == pytest.approx(-122.42)
    assert frame["lat"] == pytest.approx(37.77)
    assert frame["bearing"] == 90.0
    assert frame["sequence_id"] == "seq-abc"
    assert frame["thumb_original_url"] == "https://cdn.mapillary.com/img-001-original.jpg"


def test_parse_frame_accepts_sequence_field():
    raw_frame = dict(RAW_FRAME)
    raw_frame.pop("sequence_id")
    raw_frame["sequence"] = "seq-live"
    frame = _parse_frame(raw_frame)
    assert frame["sequence_id"] == "seq-live"


def test_group_by_sequence_ordering():
    frames = [RAW_FRAME_2, RAW_FRAME]  # reversed order
    seqs = _group_by_sequence(frames)
    assert len(seqs) == 1
    assert seqs[0]["sequence_id"] == "seq-abc"
    # Should be sorted by timestamp ascending
    assert seqs[0]["frames"][0]["id"] == "img-001"
    assert seqs[0]["frames"][1]["id"] == "img-002"


def test_group_by_sequence_multiple():
    frame_b = dict(RAW_FRAME, sequence_id="seq-xyz", id="img-010")
    seqs = _group_by_sequence([RAW_FRAME, frame_b])
    seq_ids = {s["sequence_id"] for s in seqs}
    assert seq_ids == {"seq-abc", "seq-xyz"}


@patch("ingest.mapillary._iter_bbox_tiles")
@patch("ingest.mapillary._get_with_retry")
def test_fetch_sequences_saves_json(mock_get, mock_tiles):
    mock_tiles.return_value = [{"min_lon": -1, "min_lat": -1, "max_lon": 1, "max_lat": 1}]
    mock_get.return_value = {
        "data": [RAW_FRAME, RAW_FRAME_2],
        "paging": {},
    }

    with tempfile.TemporaryDirectory() as tmp:
        seqs = fetch_sequences(output_dir=tmp, max_images=10)
        assert len(seqs) == 1
        assert seqs[0]["sequence_id"] == "seq-abc"
        assert len(seqs[0]["frames"]) == 2

        out_path = os.path.join(tmp, "mapillary_sequences.json")
        assert os.path.exists(out_path)
        with open(out_path) as f:
            loaded = json.load(f)
        assert loaded[0]["sequence_id"] == "seq-abc"


@patch("ingest.mapillary._iter_bbox_tiles")
@patch("ingest.mapillary._get_with_retry")
def test_fetch_sequences_pagination(mock_get, mock_tiles):
    """Two pages: first has next cursor, second does not."""
    mock_tiles.return_value = [{"min_lon": -1, "min_lat": -1, "max_lon": 1, "max_lat": 1}]
    mock_get.side_effect = [
        {"data": [RAW_FRAME], "paging": {"next": "cursor_xyz"}},
        {"data": [RAW_FRAME_2], "paging": {}},
    ]

    with tempfile.TemporaryDirectory() as tmp:
        seqs = fetch_sequences(output_dir=tmp)
        frames = seqs[0]["frames"]
        assert len(frames) == 2


@patch("ingest.mapillary._iter_bbox_tiles")
@patch("ingest.mapillary._get_with_retry")
def test_fetch_sequences_deduplicates_across_tiles(mock_get, mock_tiles):
    mock_tiles.return_value = [
        {"min_lon": -1, "min_lat": -1, "max_lon": 0, "max_lat": 0},
        {"min_lon": 0, "min_lat": 0, "max_lon": 1, "max_lat": 1},
    ]
    mock_get.side_effect = [
        {"data": [RAW_FRAME], "paging": {}},
        {"data": [RAW_FRAME], "paging": {}},
    ]

    with tempfile.TemporaryDirectory() as tmp:
        seqs = fetch_sequences(output_dir=tmp)
        assert len(seqs) == 1
        assert len(seqs[0]["frames"]) == 1


@patch("ingest.mapillary._iter_bbox_tiles")
@patch("ingest.mapillary._get_with_retry")
def test_fetch_sequences_subdivides_failed_tile(mock_get, mock_tiles):
    root_tile = {"min_lon": -1, "min_lat": -1, "max_lon": 1, "max_lat": 1}
    child_tiles = [
        {"min_lon": -1, "min_lat": -1, "max_lon": 0, "max_lat": 0},
        {"min_lon": 0, "min_lat": -1, "max_lon": 1, "max_lat": 0},
        {"min_lon": -1, "min_lat": 0, "max_lon": 0, "max_lat": 1},
        {"min_lon": 0, "min_lat": 0, "max_lon": 1, "max_lat": 1},
    ]

    def tile_side_effect(bbox, grid_size):
        if bbox == root_tile and grid_size == 8:
            return [root_tile]
        if bbox == root_tile and grid_size == 2:
            return child_tiles
        return [bbox]

    mock_tiles.side_effect = tile_side_effect
    mock_get.side_effect = [
        RuntimeError("tile too large"),
        {"data": [RAW_FRAME], "paging": {}},
        {"data": [], "paging": {}},
        {"data": [], "paging": {}},
        {"data": [], "paging": {}},
    ]

    with tempfile.TemporaryDirectory() as tmp:
        seqs = fetch_sequences(output_dir=tmp)
        assert len(seqs) == 1
        assert len(seqs[0]["frames"]) == 1


def test_load_sequences_roundtrip():
    seqs = [{"sequence_id": "seq-abc", "frames": [_parse_frame(RAW_FRAME)]}]
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "mapillary_sequences.json")
        with open(path, "w") as f:
            json.dump(seqs, f)
        loaded = load_sequences(data_dir=tmp)
    assert loaded[0]["sequence_id"] == "seq-abc"
    assert loaded[0]["frames"][0]["id"] == "img-001"


def test_iter_bbox_tiles_returns_grid():
    tiles = _iter_bbox_tiles(
        {"min_lon": 0.0, "min_lat": 0.0, "max_lon": 2.0, "max_lat": 2.0},
        grid_size=2,
    )
    assert len(tiles) == 4
    assert tiles[0] == {"min_lon": 0.0, "min_lat": 0.0, "max_lon": 1.0, "max_lat": 1.0}
    assert tiles[-1] == {"min_lon": 1.0, "min_lat": 1.0, "max_lon": 2.0, "max_lat": 2.0}


@patch("ingest.mapillary._download_file")
def test_download_frames_prefers_original_and_can_overwrite(mock_download):
    sequences = [{"sequence_id": "seq-abc", "frames": [_parse_frame(RAW_FRAME)]}]

    with tempfile.TemporaryDirectory() as tmp:
        seq_dir = os.path.join(tmp, "images", "seq-abc")
        os.makedirs(seq_dir, exist_ok=True)
        out_path = os.path.join(seq_dir, "img-001.jpg")
        with open(out_path, "wb") as f:
            f.write(b"old")

        download_frames(sequences, output_dir=tmp, overwrite_existing=False)
        mock_download.assert_not_called()

        download_frames(sequences, output_dir=tmp, overwrite_existing=True)
        mock_download.assert_called_once_with(
            "https://cdn.mapillary.com/img-001-original.jpg",
            out_path,
        )


@patch("ingest.mapillary._download_file")
@patch("ingest.mapillary._fetch_image_url")
def test_download_frames_skips_when_original_unavailable(mock_fetch_image_url, mock_download):
    frame = dict(_parse_frame(RAW_FRAME))
    frame["thumb_original_url"] = ""
    frame["thumb_2048_url"] = "https://cdn.mapillary.com/img-001-2048.jpg"
    frame["thumb_1024_url"] = "https://cdn.mapillary.com/img-001-1024.jpg"
    sequences = [{"sequence_id": "seq-abc", "frames": [frame]}]
    mock_fetch_image_url.return_value = None

    with tempfile.TemporaryDirectory() as tmp:
        download_frames(sequences, output_dir=tmp, overwrite_existing=True)

    mock_fetch_image_url.assert_called_once_with("img-001")
    mock_download.assert_not_called()


@patch("ingest.mapillary.time.sleep")
@patch("ingest.mapillary.requests.get")
def test_get_with_retry_recovers_from_timeout(mock_get, mock_sleep):
    success = MagicMock(status_code=200)
    success.json.return_value = {"data": [RAW_FRAME], "paging": {}}
    success.raise_for_status.return_value = None

    mock_get.side_effect = [
        requests.exceptions.ReadTimeout("timed out"),
        success,
    ]

    result = _get_with_retry("https://graph.mapillary.com/images", {"bbox": "1,2,3,4"})

    assert result["data"][0]["id"] == "img-001"
    assert mock_get.call_count == 2
    mock_sleep.assert_called_once()
