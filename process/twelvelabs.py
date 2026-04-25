"""
Upload frames to S3 and generate Marengo embeddings via AWS Bedrock.

Marengo accepts IMAGE, VIDEO, TEXT, or AUDIO input → returns float[1024] embedding.
"""

import json
import logging
import os
import time
from typing import Optional

import boto3

from config.settings import (
    AWS_REGION,
    MARENGO_MODEL_ID,
    S3_WORKSHOP_BUCKET,
)

logger = logging.getLogger(__name__)

# Marengo embedding dimension
EMBEDDING_DIM = 1024


def get_bedrock_client():
    return boto3.client("bedrock-runtime", region_name=AWS_REGION)


def get_s3_client():
    return boto3.client("s3", region_name=AWS_REGION)


def upload_to_s3(local_path: str, s3_key: str, bucket: str = S3_WORKSHOP_BUCKET) -> str:
    """Upload a local file to S3 and return its s3:// URI."""
    s3 = get_s3_client()
    s3.upload_file(local_path, bucket, s3_key)
    uri = f"s3://{bucket}/{s3_key}"
    logger.debug("Uploaded %s → %s", local_path, uri)
    return uri


def embed_image(s3_uri: str, client=None) -> list[float]:
    """
    Generate a Marengo embedding for a single image already in S3.

    Returns a float[1024] list.
    """
    if client is None:
        client = get_bedrock_client()

    body = json.dumps({"inputType": "IMAGE", "inputS3Uri": s3_uri})
    response = client.invoke_model(
        modelId=MARENGO_MODEL_ID,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    result = json.loads(response["body"].read())
    embedding = result.get("embedding") or result.get("embeddings")
    if embedding is None:
        raise ValueError(f"No embedding in Marengo response: {list(result.keys())}")
    return embedding


def embed_video(s3_uri: str, client=None) -> list[float]:
    """Generate a Marengo embedding for a video clip already in S3."""
    if client is None:
        client = get_bedrock_client()

    body = json.dumps({"inputType": "VIDEO", "inputS3Uri": s3_uri})
    response = client.invoke_model(
        modelId=MARENGO_MODEL_ID,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    result = json.loads(response["body"].read())
    embedding = result.get("embedding") or result.get("embeddings")
    if embedding is None:
        raise ValueError(f"No embedding in Marengo response: {list(result.keys())}")
    return embedding


def embed_text(text: str, client=None) -> list[float]:
    """Generate a Marengo text embedding (useful for semantic search queries)."""
    if client is None:
        client = get_bedrock_client()

    body = json.dumps({"inputType": "TEXT", "inputText": text})
    response = client.invoke_model(
        modelId=MARENGO_MODEL_ID,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    result = json.loads(response["body"].read())
    embedding = result.get("embedding") or result.get("embeddings")
    if embedding is None:
        raise ValueError(f"No embedding in Marengo response: {list(result.keys())}")
    return embedding


def embed_frames_batch(
    frames: list[dict],
    s3_prefix: str = "frames/",
    bucket: str = S3_WORKSHOP_BUCKET,
    delay_between: float = 0.1,
    client=None,
) -> list[dict]:
    """
    Upload and embed a list of frames.

    Each frame dict must have keys: id, local_path (or s3_uri if already uploaded),
    lat, lon, bearing, timestamp, sequence_id.

    Returns the same list with an added 'embedding' key on each dict.
    """
    if client is None:
        client = get_bedrock_client()

    results = []
    for i, frame in enumerate(frames):
        s3_uri = frame.get("s3_uri")
        if not s3_uri:
            local_path = frame["local_path"]
            s3_key = f"{s3_prefix}{frame['sequence_id']}/{frame['id']}.jpg"
            s3_uri = upload_to_s3(local_path, s3_key, bucket=bucket)

        try:
            embedding = embed_image(s3_uri, client=client)
            results.append({**frame, "s3_uri": s3_uri, "embedding": embedding})
            logger.info("[%d/%d] Embedded frame %s", i + 1, len(frames), frame["id"])
        except Exception as exc:
            logger.warning("Failed to embed frame %s: %s", frame["id"], exc)
            results.append({**frame, "s3_uri": s3_uri, "embedding": None, "error": str(exc)})

        if delay_between and i < len(frames) - 1:
            time.sleep(delay_between)

    return results
