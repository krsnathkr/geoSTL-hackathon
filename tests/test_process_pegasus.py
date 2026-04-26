"""Unit tests for process/pegasus.py — ffmpeg and AWS calls mocked."""

import json
import os
import tempfile
from unittest.mock import MagicMock, call, patch

import pytest

from process.pegasus import (
    describe_clip,
    frames_to_clip,
    parse_description,
    process_sequence_clip,
    process_all_sequences,
)


# ── parse_description ────────────────────────────────────────────────────────

def test_parse_clean_json():
    raw = '{"name": "Blue Bottle Coffee", "category": "cafe", "condition": "open"}'
    result = parse_description(raw)
    assert result["name"] == "Blue Bottle Coffee"
    assert result["category"] == "cafe"
    assert result["condition"] == "open"


def test_parse_json_with_code_fence():
    raw = '```json\n{"name": "Tartine", "category": "restaurant", "condition": "open"}\n```'
    result = parse_description(raw)
    assert result["name"] == "Tartine"


def test_parse_fallback_regex():
    raw = 'name: "Mission Burrito", category: "restaurant", condition: "closed"'
    result = parse_description(raw)
    assert result["name"] == "Mission Burrito"
    assert result["condition"] == "closed"


def test_parse_missing_fields_uses_defaults():
    result = parse_description("{}")
    assert result["name"] == ""
    assert result["category"] == "other"
    assert result["condition"] == "unknown"


def test_parse_preserves_raw():
    raw = '{"name": "Test", "category": "cafe", "condition": "open"}'
    result = parse_description(raw)
    assert result["raw"] == raw


# ── describe_clip ─────────────────────────────────────────────────────────────

def _mock_stream_response(text: str) -> MagicMock:
    """Build a fake InvokeModelWithResponseStream response."""
    chunk_bytes = json.dumps({"message": text}).encode()
    event = {"chunk": {"bytes": chunk_bytes}}
    mock_resp = MagicMock()
    mock_resp.__getitem__ = lambda self, key: iter([event]) if key == "body" else None
    return mock_resp


def test_describe_clip_accumulates_stream():
    client = MagicMock()
    expected = '{"name": "Four Barrel", "category": "cafe", "condition": "open"}'
    client.invoke_model_with_response_stream.return_value = _mock_stream_response(expected)

    result = describe_clip("s3://bucket/clip.mp4", client=client)
    assert result == expected


def test_describe_clip_uses_correct_model():
    from config.settings import PEGASUS_MODEL_ID
    client = MagicMock()
    client.invoke_model_with_response_stream.return_value = _mock_stream_response("{}")
    describe_clip("s3://bucket/clip.mp4", client=client)
    kwargs = client.invoke_model_with_response_stream.call_args[1]
    assert kwargs["modelId"] == PEGASUS_MODEL_ID


def test_describe_clip_sends_video_input_type():
    client = MagicMock()
    client.invoke_model_with_response_stream.return_value = _mock_stream_response("{}")
    describe_clip("s3://bucket/clip.mp4", client=client)
    kwargs = client.invoke_model_with_response_stream.call_args[1]
    body = json.loads(kwargs["body"])
    assert body["inputPrompt"]
    assert body["mediaSource"]["s3Location"]["uri"] == "s3://bucket/clip.mp4"


# ── frames_to_clip ────────────────────────────────────────────────────────────

@patch("process.pegasus.subprocess.run")
def test_frames_to_clip_calls_ffmpeg(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stderr="")
    with tempfile.NamedTemporaryFile(suffix=".jpg") as f1, \
         tempfile.NamedTemporaryFile(suffix=".jpg") as f2, \
         tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as out:
        out_path = out.name

    try:
        frames_to_clip([f1.name, f2.name], output_path=out_path)
        assert mock_run.called
        cmd = mock_run.call_args[0][0]
        assert "ffmpeg" in cmd
        assert out_path in cmd
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)


@patch("process.pegasus.subprocess.run")
def test_frames_to_clip_raises_on_ffmpeg_failure(mock_run):
    mock_run.return_value = MagicMock(returncode=1, stderr="error: codec not found")
    with tempfile.NamedTemporaryFile(suffix=".jpg") as f:
        with pytest.raises(RuntimeError, match="ffmpeg failed"):
            frames_to_clip([f.name, f.name])


def test_frames_to_clip_empty_raises():
    with pytest.raises(ValueError, match="empty"):
        frames_to_clip([])


# ── process_sequence_clip ─────────────────────────────────────────────────────

@patch("process.pegasus.upload_to_s3")
@patch("process.pegasus.frames_to_clip")
def test_process_sequence_clip_full_pipeline(mock_clip, mock_upload):
    mock_clip.return_value = "/tmp/fake.mp4"
    mock_upload.return_value = "s3://bucket/clips/seq1.mp4"

    client = MagicMock()
    raw_resp = '{"name": "Sightglass Coffee", "category": "cafe", "condition": "open"}'
    client.invoke_model_with_response_stream.return_value = _mock_stream_response(raw_resp)

    frame_meta = [
        {"id": "f1", "lat": 37.77, "lon": -122.42, "bearing": 0.0, "timestamp": "2024-01-01T00:00:00Z"},
        {"id": "f2", "lat": 37.78, "lon": -122.43, "bearing": 5.0, "timestamp": "2024-01-01T00:00:05Z"},
    ]

    result = process_sequence_clip(
        sequence_id="seq1",
        frame_paths=["/tmp/f1.jpg", "/tmp/f2.jpg"],
        frame_meta=frame_meta,
        client=client,
    )

    assert result["sequence_id"] == "seq1"
    assert result["name"] == "Sightglass Coffee"
    assert result["category"] == "cafe"
    assert result["condition"] == "open"
    assert result["lat"] == pytest.approx((37.77 + 37.78) / 2)


@patch("process.pegasus.process_sequence_clip")
def test_process_all_sequences_baseline_duplicates_single_frame(mock_process, tmp_path):
    seq_dir = tmp_path / "seq1"
    seq_dir.mkdir()
    frame_path = seq_dir / "f1.jpg"
    frame_path.write_bytes(b"jpg")

    mock_process.return_value = {
        "sequence_id": "seq1",
        "name": "Cafe",
        "category": "cafe",
        "condition": "open",
        "lat": 37.77,
        "lon": -122.42,
        "frame_ids": ["f1", "f1"],
        "raw_response": "{}",
        "clip_s3_uri": "s3://bucket/baseline.mp4",
    }

    sequences = [
        {
            "sequence_id": "seq1",
            "frames": [{"id": "f1", "lat": 37.77, "lon": -122.42, "timestamp": "2024-01-01T00:00:00Z"}],
        }
    ]

    result = process_all_sequences(
        sequences=sequences,
        images_dir=str(tmp_path),
        output_dir=str(tmp_path),
        max_frames_per_clip=1,
        min_frames_per_clip=1,
        duplicate_single_frame=True,
        output_filename="baseline_descriptions.json",
        s3_prefix="baseline-clips/",
        client=MagicMock(),
    )

    assert len(result) == 1
    args = mock_process.call_args[0]
    assert args[0] == "seq1"
    assert args[1] == [str(frame_path), str(frame_path)]
    assert args[2][0]["id"] == "f1"
    assert args[2][1]["id"] == "f1"
