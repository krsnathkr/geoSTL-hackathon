"""
Generate structured POI descriptions from video clips via Pegasus 1.2 on Bedrock.

Pegasus accepts VIDEO only (not still images). This module:
  1. Stitches sampled JPEG frames into a short MP4 clip via ffmpeg
  2. Uploads the clip to S3
  3. Calls Pegasus via InvokeModelWithResponseStream
  4. Parses the text response into {name, category, condition}

Output: data/processed/descriptions.json
"""

import json
import logging
import os
import re
import subprocess
import tempfile
from typing import Optional

from config.settings import (
    AWS_REGION,
    DATA_PROCESSED,
    FRAME_SAMPLE_INTERVAL,
    PEGASUS_MODEL_ID,
    S3_WORKSHOP_BUCKET,
)
from process.twelvelabs import get_bedrock_client, upload_to_s3, _s3_location

logger = logging.getLogger(__name__)

DEFAULT_PROMPT = (
    "You are analyzing a street-level video sequence for a geospatial audit. "
    "Examine the video carefully and return a JSON object with exactly these keys:\n"
    '{"name": "<name from signage, or descriptive label if no signage: e.g. \'residential street\', \'park trail\', \'university building\'>", '
    '"category": "<one of: restaurant, cafe, retail, office, hotel, bar, service, residential, park, university, parking, transit, trail, other>", '
    '"condition": "<one of: open, closed, vacant, under_construction, good, fair, poor, unknown>", '
    '"description": "<2-3 sentences: describe the buildings, signs, activity, infrastructure, and surroundings visible in the video>"}\n'
    "Extract the most prominent feature. If no business is visible, describe the area type (park, residential, campus, commercial corridor, etc). "
    "Respond ONLY with valid JSON, no other text."
)


def frames_to_clip(
    frame_paths: list[str],
    fps: int = 5,
    output_path: Optional[str] = None,
    target_duration_sec: float = 10.0,
) -> str:
    """
    Stitch a list of JPEG frame paths into an MP4 clip using ffmpeg.

    fps controls the output frame rate (5fps from 5-second sampled frames ≈ real time).
    Returns the path to the created MP4 file.
    """
    if not frame_paths:
        raise ValueError("frame_paths is empty — cannot create clip")

    if output_path is None:
        suffix = ".mp4"
        fd, output_path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)

    # Write frame paths to a concat file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as concat_file:
        frame_duration = target_duration_sec / len(frame_paths)
        for path in frame_paths:
            concat_file.write(f"file '{os.path.abspath(path)}'\n")
            concat_file.write(f"duration {frame_duration:.4f}\n")
        concat_path = concat_file.name

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_path,
        "-vf", f"fps={fps}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    os.unlink(concat_path)

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{result.stderr}")

    logger.debug("Created clip: %s (%d frames)", output_path, len(frame_paths))
    return output_path


def describe_clip(
    s3_uri: str,
    prompt: str = DEFAULT_PROMPT,
    client=None,
) -> str:
    """
    Call Pegasus 1.2 on a video clip already in S3.

    Uses InvokeModelWithResponseStream and returns the full accumulated response text.
    """
    if client is None:
        client = get_bedrock_client()

    body = json.dumps({
        "inputPrompt": prompt,
        "mediaSource": {
            "s3Location": _s3_location(s3_uri),
        },
        "temperature": 0.2,
        "maxOutputTokens": 512,
    })

    response = client.invoke_model_with_response_stream(
        modelId=PEGASUS_MODEL_ID,
        body=body,
        contentType="application/json",
        accept="application/json",
    )

    chunks = []
    for event in response["body"]:
        chunk = event.get("chunk")
        if chunk:
            raw = chunk["bytes"].decode("utf-8")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                chunks.append(raw)
                continue

            text_piece = data.get("message")
            if text_piece is None:
                text_piece = (
                    data.get("outputText")
                    or data.get("text")
                    or data.get("completion")
                    or ""
                )
            chunks.append(text_piece)

    return "".join(chunks).strip()


def parse_description(raw_text: str) -> dict:
    """
    Parse Pegasus output into {name, category, condition}.

    Tries JSON first; falls back to regex extraction.
    """
    # Strip markdown code fences if present
    text = re.sub(r"```(?:json)?\s*", "", raw_text).strip().rstrip("```").strip()

    try:
        data = json.loads(text)
        return {
            "name": data.get("name", ""),
            "category": data.get("category", "other"),
            "condition": data.get("condition", "unknown"),
            "description": data.get("description", ""),
            "raw": raw_text,
        }
    except (json.JSONDecodeError, ValueError):
        pass

    # Regex fallback
    name_m = re.search(r'"?name"?\s*[=:]\s*"([^"]+)"', text, re.IGNORECASE)
    cat_m = re.search(r'"?category"?\s*[=:]\s*"([^"]+)"', text, re.IGNORECASE)
    cond_m = re.search(r'"?condition"?\s*[=:]\s*"([^"]+)"', text, re.IGNORECASE)
    desc_m = re.search(r'"?description"?\s*[=:]\s*"([^"]+)"', text, re.IGNORECASE)

    return {
        "name": name_m.group(1) if name_m else "",
        "category": cat_m.group(1) if cat_m else "other",
        "condition": cond_m.group(1) if cond_m else "unknown",
        "description": desc_m.group(1) if desc_m else "",
        "raw": raw_text,
    }


def process_sequence_clip(
    sequence_id: str,
    frame_paths: list[str],
    frame_meta: list[dict],
    s3_prefix: str = "clips/",
    bucket: str = S3_WORKSHOP_BUCKET,
    client=None,
) -> dict:
    """
    Full pipeline for one sequence: stitch → upload → describe → parse.

    frame_meta: list of frame dicts with {id, lat, lon, bearing, timestamp}.
    Returns a dict with sequence_id, description fields, centroid lat/lon, and frame evidence.
    """
    clip_path = None
    try:
        clip_path = frames_to_clip(frame_paths)
        s3_key = f"{s3_prefix}{sequence_id}.mp4"
        s3_uri = upload_to_s3(clip_path, s3_key, bucket=bucket)

        raw_text = describe_clip(s3_uri, client=client)
        parsed = parse_description(raw_text)

        # Compute centroid of sampled frames
        lats = [f["lat"] for f in frame_meta if f.get("lat")]
        lons = [f["lon"] for f in frame_meta if f.get("lon")]
        centroid_lat = sum(lats) / len(lats) if lats else None
        centroid_lon = sum(lons) / len(lons) if lons else None

        return {
            "sequence_id": sequence_id,
            "clip_s3_uri": s3_uri,
            "name": parsed["name"],
            "category": parsed["category"],
            "condition": parsed["condition"],
            "description": parsed.get("description", ""),
            "lat": centroid_lat,
            "lon": centroid_lon,
            "frame_ids": [f["id"] for f in frame_meta],
            "raw_response": parsed["raw"],
        }
    finally:
        if clip_path and os.path.exists(clip_path):
            os.unlink(clip_path)


def process_all_sequences(
    sequences: list[dict],
    images_dir: str,
    output_dir: str = DATA_PROCESSED,
    max_frames_per_clip: int = 10,
    min_frames_per_clip: int = 2,
    duplicate_single_frame: bool = False,
    output_filename: str = "descriptions.json",
    s3_prefix: str = "clips/",
    client=None,
) -> list[dict]:
    """
    Process every sequence: stitch frames → Pegasus → parse → save JSON manifest.

    sequences: output of mapillary.load_sequences()
    images_dir: root of data/raw/images/{sequence_id}/{frame_id}.jpg
    """
    os.makedirs(output_dir, exist_ok=True)

    if client is None:
        client = get_bedrock_client()

    all_results = []
    for seq in sequences:
        seq_id = seq["sequence_id"]
        frames = seq["frames"]

        # Collect frame paths that were actually downloaded
        seq_img_dir = os.path.join(images_dir, seq_id)
        sampled = []
        for frame in frames[:max_frames_per_clip]:
            path = os.path.join(seq_img_dir, f"{frame['id']}.jpg")
            if os.path.exists(path):
                sampled.append((path, frame))

        if duplicate_single_frame and len(sampled) == 1:
            sampled = [sampled[0], sampled[0]]

        if len(sampled) < min_frames_per_clip:
            logger.warning(
                "Sequence %s: fewer than %d downloaded frames — skipping",
                seq_id,
                min_frames_per_clip,
            )
            continue

        paths, metas = zip(*sampled)
        try:
            result = process_sequence_clip(
                seq_id,
                list(paths),
                list(metas),
                s3_prefix=s3_prefix,
                client=client,
            )
            all_results.append(result)
            logger.info(
                "Sequence %s → name=%r category=%r condition=%r",
                seq_id, result["name"], result["category"], result["condition"],
            )
        except Exception as exc:
            logger.error("Failed to process sequence %s: %s", seq_id, exc)

    out_path = os.path.join(output_dir, output_filename)
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2)
    logger.info("Saved descriptions → %s (%d sequences)", out_path, len(all_results))

    return all_results
