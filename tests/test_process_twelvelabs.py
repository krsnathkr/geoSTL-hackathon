"""Unit tests for process/twelvelabs.py — all AWS calls mocked."""

import io
import json
from unittest.mock import MagicMock, patch

import pytest

from process.twelvelabs import embed_image, embed_text, embed_frames_batch, EMBEDDING_DIM


def _mock_bedrock_response(embedding: list[float]) -> MagicMock:
    body_bytes = json.dumps({"embedding": embedding}).encode()
    mock_resp = MagicMock()
    mock_resp.__getitem__ = lambda self, key: (
        io.BytesIO(body_bytes) if key == "body" else None
    )
    return mock_resp


def _fake_embedding(dim: int = EMBEDDING_DIM) -> list[float]:
    return [0.1] * dim


def test_embed_image_returns_vector():
    client = MagicMock()
    client.invoke_model.return_value = _mock_bedrock_response(_fake_embedding())
    result = embed_image("s3://bucket/frame.jpg", client=client)
    assert len(result) == EMBEDDING_DIM
    assert result[0] == pytest.approx(0.1)


def test_embed_image_uses_correct_model():
    from config.settings import MARENGO_MODEL_ID
    client = MagicMock()
    client.invoke_model.return_value = _mock_bedrock_response(_fake_embedding())
    embed_image("s3://bucket/frame.jpg", client=client)
    call_kwargs = client.invoke_model.call_args[1]
    assert call_kwargs["modelId"] == MARENGO_MODEL_ID


def test_embed_image_input_type():
    client = MagicMock()
    client.invoke_model.return_value = _mock_bedrock_response(_fake_embedding())
    embed_image("s3://bucket/frame.jpg", client=client)
    body = json.loads(client.invoke_model.call_args[1]["body"])
    assert body["inputType"] == "image"
    assert body["mediaSource"]["s3Location"]["uri"] == "s3://bucket/frame.jpg"


def test_embed_text():
    client = MagicMock()
    client.invoke_model.return_value = _mock_bedrock_response(_fake_embedding())
    result = embed_text("blue bottle coffee shop", client=client)
    assert len(result) == EMBEDDING_DIM
    body = json.loads(client.invoke_model.call_args[1]["body"])
    assert body["inputType"] == "text"


def test_embed_image_missing_embedding_raises():
    client = MagicMock()
    body_bytes = json.dumps({"result": "ok"}).encode()
    mock_resp = MagicMock()
    mock_resp.__getitem__ = lambda self, key: (
        io.BytesIO(body_bytes) if key == "body" else None
    )
    client.invoke_model.return_value = mock_resp
    with pytest.raises(ValueError, match="No embedding"):
        embed_image("s3://bucket/frame.jpg", client=client)


@patch("process.twelvelabs.upload_to_s3")
def test_embed_frames_batch(mock_upload):
    mock_upload.return_value = "s3://bucket/frames/seq1/img1.jpg"
    client = MagicMock()
    client.invoke_model.return_value = _mock_bedrock_response(_fake_embedding())

    frames = [
        {
            "id": "img1",
            "local_path": "/tmp/img1.jpg",
            "lat": 37.77,
            "lon": -122.42,
            "bearing": 90.0,
            "timestamp": "2024-01-01T00:00:00Z",
            "sequence_id": "seq1",
        }
    ]
    results = embed_frames_batch(frames, client=client)
    assert len(results) == 1
    assert results[0]["embedding"] is not None
    assert len(results[0]["embedding"]) == EMBEDDING_DIM


@patch("process.twelvelabs.upload_to_s3")
def test_embed_frames_batch_handles_failure(mock_upload):
    mock_upload.return_value = "s3://bucket/frame.jpg"
    client = MagicMock()
    client.invoke_model.side_effect = RuntimeError("Bedrock timeout")

    frames = [
        {
            "id": "bad",
            "local_path": "/tmp/bad.jpg",
            "lat": 37.7,
            "lon": -122.4,
            "bearing": 0.0,
            "timestamp": "",
            "sequence_id": "seq1",
        }
    ]
    results = embed_frames_batch(frames, client=client)
    assert results[0]["embedding"] is None
    assert "error" in results[0]
