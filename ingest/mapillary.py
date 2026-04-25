"""
Fetch Mapillary sequences and frame images for the SF bbox.

Outputs:
  data/raw/mapillary_sequences.json          — sequence metadata + per-frame GPS
  data/raw/images/{sequence_id}/{frame_id}.jpg — sampled frame images
"""

import json
import logging
import os
import time
from typing import Any

import requests

from config.settings import (
    BBOX,
    DATA_RAW,
    FRAME_SAMPLE_INTERVAL,
    MAPILLARY_ACCESS_TOKEN,
    MAPILLARY_API_BASE,
)

logger = logging.getLogger(__name__)

IMAGES_ENDPOINT = f"{MAPILLARY_API_BASE}/images"
IMAGE_DETAIL_ENDPOINT = f"{MAPILLARY_API_BASE}/{{image_id}}"

# Fields to pull per frame
FRAME_FIELDS = "id,geometry,captured_at,sequence_id,compass_angle,thumb_2048_url"

# Max images per API page (Mapillary caps at 2000)
PAGE_LIMIT = 2000

# Seconds between retry attempts on rate-limit (429)
RETRY_WAIT = 5


def _auth_params() -> dict:
    return {"access_token": MAPILLARY_ACCESS_TOKEN}


def fetch_sequences(
    output_dir: str = DATA_RAW,
    max_images: int | None = None,
) -> list[dict]:
    """
    Fetch all images in the SF bbox from Mapillary and group them by sequence.

    Returns a list of sequence dicts:
      {sequence_id, frames: [{id, lat, lon, bearing, timestamp, thumb_2048_url}]}
    """
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, "mapillary_sequences.json")

    bbox_str = (
        f"{BBOX['min_lon']},{BBOX['min_lat']},{BBOX['max_lon']},{BBOX['max_lat']}"
    )

    params: dict[str, Any] = {
        "bbox": bbox_str,
        "fields": FRAME_FIELDS,
        "limit": PAGE_LIMIT,
        **_auth_params(),
    }

    all_frames: list[dict] = []
    page = 0

    logger.info("Fetching Mapillary images for SF bbox…")
    while True:
        resp = _get_with_retry(IMAGES_ENDPOINT, params)
        data = resp.get("data", [])
        all_frames.extend(data)
        page += 1
        logger.info("Page %d: %d frames (total so far: %d)", page, len(data), len(all_frames))

        if max_images and len(all_frames) >= max_images:
            all_frames = all_frames[:max_images]
            break

        # Mapillary pagination: next cursor in paging.next
        next_cursor = resp.get("paging", {}).get("next")
        if not next_cursor:
            break
        params["after"] = next_cursor

    sequences = _group_by_sequence(all_frames)
    logger.info("Grouped into %d sequences", len(sequences))

    with open(out_path, "w") as f:
        json.dump(sequences, f)
    logger.info("Saved → %s", out_path)

    return sequences


def download_frames(
    sequences: list[dict],
    output_dir: str = DATA_RAW,
    sample_every_n: int = 1,
) -> None:
    """
    Download frame images for each sequence into data/raw/images/{sequence_id}/.

    sample_every_n skips frames to reduce download volume — set to 1 for all.
    """
    images_root = os.path.join(output_dir, "images")
    os.makedirs(images_root, exist_ok=True)

    for seq in sequences:
        seq_id = seq["sequence_id"]
        seq_dir = os.path.join(images_root, seq_id)
        os.makedirs(seq_dir, exist_ok=True)

        frames = seq["frames"]
        sampled = frames[::sample_every_n]
        logger.info("Sequence %s: downloading %d/%d frames", seq_id, len(sampled), len(frames))

        for frame in sampled:
            frame_id = frame["id"]
            out_path = os.path.join(seq_dir, f"{frame_id}.jpg")
            if os.path.exists(out_path):
                continue

            thumb_url = frame.get("thumb_2048_url")
            if not thumb_url:
                thumb_url = _fetch_thumb_url(frame_id)
                frame["thumb_2048_url"] = thumb_url

            if not thumb_url:
                logger.warning("No thumb URL for frame %s — skipping", frame_id)
                continue

            _download_file(thumb_url, out_path)


def load_sequences(data_dir: str = DATA_RAW) -> list[dict]:
    """Load previously fetched sequences JSON without re-calling the API."""
    path = os.path.join(data_dir, "mapillary_sequences.json")
    with open(path) as f:
        return json.load(f)


def _group_by_sequence(frames: list[dict]) -> list[dict]:
    """Group flat frame list into per-sequence dicts with ordered frame lists."""
    seq_map: dict[str, list[dict]] = {}
    for frame in frames:
        seq_id = frame.get("sequence_id", "unknown")
        seq_map.setdefault(seq_id, []).append(_parse_frame(frame))

    # Sort each sequence's frames by captured_at
    result = []
    for seq_id, seq_frames in seq_map.items():
        seq_frames.sort(key=lambda f: f["timestamp"])
        result.append({"sequence_id": seq_id, "frames": seq_frames})

    result.sort(key=lambda s: s["frames"][0]["timestamp"] if s["frames"] else "")
    return result


def _parse_frame(raw: dict) -> dict:
    """Flatten a raw Mapillary image response into our internal frame schema."""
    geom = raw.get("geometry", {})
    coords = geom.get("coordinates", [None, None])
    return {
        "id": raw["id"],
        "lon": coords[0],
        "lat": coords[1],
        "bearing": raw.get("compass_angle"),
        "timestamp": raw.get("captured_at", ""),
        "sequence_id": raw.get("sequence_id", ""),
        "thumb_2048_url": raw.get("thumb_2048_url", ""),
    }


def _fetch_thumb_url(image_id: str) -> str | None:
    """Fetch thumb_2048_url for a single image ID (fallback if not in batch response)."""
    url = IMAGE_DETAIL_ENDPOINT.format(image_id=image_id)
    params = {"fields": "thumb_2048_url", **_auth_params()}
    try:
        resp = _get_with_retry(url, params)
        return resp.get("thumb_2048_url")
    except Exception as exc:
        logger.warning("Could not fetch thumb URL for %s: %s", image_id, exc)
        return None


def _get_with_retry(url: str, params: dict, max_retries: int = 3) -> dict:
    """GET with simple retry on 429/5xx."""
    for attempt in range(1, max_retries + 1):
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code == 429 or resp.status_code >= 500:
            logger.warning("HTTP %d on attempt %d, waiting %ds…", resp.status_code, attempt, RETRY_WAIT)
            time.sleep(RETRY_WAIT * attempt)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"Failed after {max_retries} attempts: {url}")


def _download_file(url: str, dest: str) -> None:
    """Stream download a file to dest path."""
    with requests.get(url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    seqs = fetch_sequences(max_images=500)
    print(f"Sequences: {len(seqs)}")
    if seqs:
        print(f"First sequence: {seqs[0]['sequence_id']}, frames: {len(seqs[0]['frames'])}")
    # Download sample — 1 in every FRAME_SAMPLE_INTERVAL frames
    download_frames(seqs, sample_every_n=FRAME_SAMPLE_INTERVAL)
    print("Done.")
