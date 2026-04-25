"""Unit tests for ingest/mapillary.py — mocks HTTP so no API calls are made."""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from ingest.mapillary import (
    _group_by_sequence,
    _parse_frame,
    fetch_sequences,
    load_sequences,
)

RAW_FRAME = {
    "id": "img-001",
    "geometry": {"type": "Point", "coordinates": [-122.42, 37.77]},
    "captured_at": "2024-03-15T10:00:00Z",
    "sequence_id": "seq-abc",
    "compass_angle": 90.0,
    "thumb_2048_url": "https://cdn.mapillary.com/img-001.jpg",
}

RAW_FRAME_2 = {
    "id": "img-002",
    "geometry": {"type": "Point", "coordinates": [-122.43, 37.78]},
    "captured_at": "2024-03-15T10:00:05Z",
    "sequence_id": "seq-abc",
    "compass_angle": 91.0,
    "thumb_2048_url": "https://cdn.mapillary.com/img-002.jpg",
}


def test_parse_frame():
    frame = _parse_frame(RAW_FRAME)
    assert frame["id"] == "img-001"
    assert frame["lon"] == pytest.approx(-122.42)
    assert frame["lat"] == pytest.approx(37.77)
    assert frame["bearing"] == 90.0
    assert frame["sequence_id"] == "seq-abc"


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


@patch("ingest.mapillary._get_with_retry")
def test_fetch_sequences_saves_json(mock_get):
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


@patch("ingest.mapillary._get_with_retry")
def test_fetch_sequences_pagination(mock_get):
    """Two pages: first has next cursor, second does not."""
    mock_get.side_effect = [
        {"data": [RAW_FRAME], "paging": {"next": "cursor_xyz"}},
        {"data": [RAW_FRAME_2], "paging": {}},
    ]

    with tempfile.TemporaryDirectory() as tmp:
        seqs = fetch_sequences(output_dir=tmp)
        frames = seqs[0]["frames"]
        assert len(frames) == 2


def test_load_sequences_roundtrip():
    seqs = [{"sequence_id": "seq-abc", "frames": [_parse_frame(RAW_FRAME)]}]
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "mapillary_sequences.json")
        with open(path, "w") as f:
            json.dump(seqs, f)
        loaded = load_sequences(data_dir=tmp)
    assert loaded[0]["sequence_id"] == "seq-abc"
    assert loaded[0]["frames"][0]["id"] == "img-001"
