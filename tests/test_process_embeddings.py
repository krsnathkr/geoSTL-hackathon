"""Unit tests for process/embeddings.py — OpenSearch client fully mocked."""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from process.embeddings import (
    index_frame,
    index_frames_bulk,
    knn_search,
    save_indexed_manifest,
)

FAKE_EMBEDDING = [0.1] * 1024


def _mock_client():
    client = MagicMock()
    client.indices.exists.return_value = True
    return client


def test_index_frame_sends_correct_doc():
    client = _mock_client()
    client.index.return_value = {"_id": "img-001"}

    frame = {
        "id": "img-001",
        "embedding": FAKE_EMBEDDING,
        "lat": 37.77,
        "lon": -122.42,
        "sequence_id": "seq-abc",
        "timestamp": "2024-03-15T10:00:00Z",
        "s3_uri": "s3://bucket/img-001.jpg",
    }
    doc_id = index_frame(frame, client=client)
    assert doc_id == "img-001"

    call_body = client.index.call_args[1]["body"]
    assert call_body["frame_id"] == "img-001"
    assert call_body["lat"] == pytest.approx(37.77)
    assert len(call_body["embedding"]) == 1024


def test_index_frames_bulk_skips_none_embeddings():
    client = _mock_client()
    client.bulk.return_value = {
        "items": [{"index": {"_id": "img-001"}}],
        "errors": False,
    }

    frames = [
        {"id": "img-001", "embedding": FAKE_EMBEDDING, "lat": 37.77, "lon": -122.42,
         "sequence_id": "seq-abc", "timestamp": "", "s3_uri": ""},
        {"id": "img-002", "embedding": None, "lat": 37.78, "lon": -122.43,
         "sequence_id": "seq-abc", "timestamp": "", "s3_uri": ""},
    ]
    count = index_frames_bulk(frames, client=client)
    # Only 1 frame had a valid embedding
    assert count == 1
    bulk_body = client.bulk.call_args[1]["body"]
    assert "img-001" in bulk_body
    assert "img-002" not in bulk_body


def test_index_frames_bulk_empty():
    client = _mock_client()
    count = index_frames_bulk([], client=client)
    assert count == 0
    client.bulk.assert_not_called()


def test_knn_search_returns_hits():
    client = _mock_client()
    client.search.return_value = {
        "hits": {
            "hits": [
                {
                    "_score": 0.95,
                    "_source": {
                        "frame_id": "img-001",
                        "lat": 37.77,
                        "lon": -122.42,
                        "sequence_id": "seq-abc",
                        "timestamp": "2024-03-15T10:00:00Z",
                    },
                }
            ]
        }
    }
    results = knn_search(FAKE_EMBEDDING, k=1, client=client)
    assert len(results) == 1
    assert results[0]["score"] == pytest.approx(0.95)
    assert results[0]["frame_id"] == "img-001"


def test_knn_search_query_structure():
    client = _mock_client()
    client.search.return_value = {"hits": {"hits": []}}
    knn_search(FAKE_EMBEDDING, k=5, client=client)

    query_body = client.search.call_args[1]["body"]
    assert "knn" in query_body["query"]
    assert query_body["size"] == 5


def test_save_indexed_manifest():
    frames = [
        {"id": "img-001", "embedding": FAKE_EMBEDDING, "lat": 37.77, "lon": -122.42,
         "sequence_id": "seq-abc", "timestamp": ""},
        {"id": "img-002", "embedding": None, "lat": 37.78, "lon": -122.43,
         "sequence_id": "seq-abc", "timestamp": ""},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        path = save_indexed_manifest(frames, output_dir=tmp)
        assert os.path.exists(path)
        with open(path) as f:
            data = json.load(f)
        # Only frame with embedding should appear
        assert len(data) == 1
        assert data[0]["id"] == "img-001"
        # Embedding should not be in manifest
        assert "embedding" not in data[0]
