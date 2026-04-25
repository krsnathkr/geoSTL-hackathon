"""
Store and search frame embeddings in OpenSearch Serverless (AOSS).

Index schema: {embedding: knn_vector[1024], lat, lon, sequence_id, frame_id, timestamp}
"""

import json
import logging
import os
from typing import Optional

import boto3
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

from config.settings import (
    AWS_REGION,
    DATA_PROCESSED,
    OPENSEARCH_ENDPOINT,
    OPENSEARCH_INDEX,
)

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1024


def _get_aoss_auth() -> AWS4Auth:
    """Build SigV4 auth for OpenSearch Serverless."""
    creds = boto3.Session().get_credentials().get_frozen_credentials()
    return AWS4Auth(
        creds.access_key,
        creds.secret_key,
        AWS_REGION,
        "aoss",
        session_token=creds.token,
    )


def get_client() -> OpenSearch:
    """Return an authenticated OpenSearch client for AOSS."""
    host = OPENSEARCH_ENDPOINT.replace("https://", "")
    return OpenSearch(
        hosts=[{"host": host, "port": 443}],
        http_auth=_get_aoss_auth(),
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        timeout=30,
    )


def ensure_index(client: Optional[OpenSearch] = None) -> None:
    """Create the KNN index if it doesn't exist."""
    if client is None:
        client = get_client()

    if client.indices.exists(index=OPENSEARCH_INDEX):
        logger.debug("Index %s already exists", OPENSEARCH_INDEX)
        return

    mapping = {
        "settings": {
            "index": {
                "knn": True,
                "knn.algo_param.ef_search": 100,
            }
        },
        "mappings": {
            "properties": {
                "embedding": {
                    "type": "knn_vector",
                    "dimension": EMBEDDING_DIM,
                    "method": {
                        "name": "hnsw",
                        "space_type": "cosinesimil",
                        "engine": "nmslib",
                    },
                },
                "lat": {"type": "float"},
                "lon": {"type": "float"},
                "sequence_id": {"type": "keyword"},
                "frame_id": {"type": "keyword"},
                "timestamp": {"type": "date", "format": "strict_date_time||epoch_millis"},
                "s3_uri": {"type": "keyword"},
            }
        },
    }
    client.indices.create(index=OPENSEARCH_INDEX, body=mapping)
    logger.info("Created index %s", OPENSEARCH_INDEX)


def index_frame(frame: dict, client: Optional[OpenSearch] = None) -> str:
    """
    Index a single frame embedding.

    frame must have: embedding, lat, lon, sequence_id, id (frame_id), timestamp.
    Returns the OpenSearch document ID.
    """
    if client is None:
        client = get_client()

    doc = {
        "embedding": frame["embedding"],
        "lat": frame["lat"],
        "lon": frame["lon"],
        "sequence_id": frame["sequence_id"],
        "frame_id": frame["id"],
        "timestamp": frame.get("timestamp", ""),
        "s3_uri": frame.get("s3_uri", ""),
    }
    response = client.index(index=OPENSEARCH_INDEX, body=doc, id=frame["id"])
    return response["_id"]


def index_frames_bulk(frames: list[dict], client: Optional[OpenSearch] = None) -> int:
    """
    Index a batch of frames using the bulk API.

    Skips frames where embedding is None.
    Returns the count of successfully indexed documents.
    """
    if client is None:
        client = get_client()

    actions = []
    for frame in frames:
        if frame.get("embedding") is None:
            continue
        actions.append(json.dumps({"index": {"_index": OPENSEARCH_INDEX, "_id": frame["id"]}}))
        actions.append(json.dumps({
            "embedding": frame["embedding"],
            "lat": frame["lat"],
            "lon": frame["lon"],
            "sequence_id": frame["sequence_id"],
            "frame_id": frame["id"],
            "timestamp": frame.get("timestamp", ""),
            "s3_uri": frame.get("s3_uri", ""),
        }))

    if not actions:
        return 0

    body = "\n".join(actions) + "\n"
    response = client.bulk(body=body)

    errors = [item for item in response["items"] if "error" in item.get("index", {})]
    if errors:
        logger.warning("%d bulk indexing errors", len(errors))

    indexed = len(response["items"]) - len(errors)
    logger.info("Bulk indexed %d/%d frames", indexed, len(frames))
    return indexed


def knn_search(
    query_embedding: list[float],
    k: int = 10,
    client: Optional[OpenSearch] = None,
) -> list[dict]:
    """
    Find the k most similar frames to query_embedding.

    Returns a list of hit dicts with _source + _score.
    """
    if client is None:
        client = get_client()

    body = {
        "size": k,
        "query": {
            "knn": {
                "embedding": {
                    "vector": query_embedding,
                    "k": k,
                }
            }
        },
    }
    response = client.search(index=OPENSEARCH_INDEX, body=body)
    hits = response["hits"]["hits"]
    return [{"score": h["_score"], **h["_source"]} for h in hits]


def save_indexed_manifest(frames: list[dict], output_dir: str = DATA_PROCESSED) -> str:
    """Write a JSON manifest of indexed frames (without embeddings) to disk."""
    import os
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, "indexed_segments.json")

    manifest = [
        {k: v for k, v in f.items() if k != "embedding"}
        for f in frames
        if f.get("embedding") is not None
    ]
    with open(out_path, "w") as fh:
        json.dump(manifest, fh)
    logger.info("Saved manifest → %s (%d frames)", out_path, len(manifest))
    return out_path
