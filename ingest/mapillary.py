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

# Fields to pull per frame. We only download original-resolution frames.
FRAME_FIELDS = "id,geometry,captured_at,sequence,compass_angle,thumb_original_url,thumb_2048_url,thumb_1024_url"

# Max images per API page (Mapillary caps at 2000)
PAGE_LIMIT = 200

# Seconds between retry attempts on rate-limit (429)
RETRY_WAIT = 5

# Query the configured bbox in tiles to avoid oversized Mapillary requests.
TILE_GRID_SIZE = 8
MAX_TILE_SUBDIVISION_DEPTH = 3


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

    all_frames: list[dict] = []
    seen_frame_ids: set[str] = set()
    page = 0

    logger.info("Fetching Mapillary images for Boulder bbox in %dx%d tiles…", TILE_GRID_SIZE, TILE_GRID_SIZE)
    tile_queue: list[tuple[dict[str, float], int]] = [
        (tile_bbox, 0) for tile_bbox in _iter_bbox_tiles(BBOX, TILE_GRID_SIZE)
    ]
    while tile_queue:
        tile_bbox, depth = tile_queue.pop(0)
        params: dict[str, Any] = {
            "bbox": _bbox_to_string(tile_bbox),
            "fields": FRAME_FIELDS,
            "limit": PAGE_LIMIT,
            **_auth_params(),
        }

        try:
            while True:
                resp = _get_with_retry(IMAGES_ENDPOINT, params)
                data = resp.get("data", [])
                page += 1

                new_frames = 0
                for frame in data:
                    frame_id = frame.get("id")
                    if not frame_id or frame_id in seen_frame_ids:
                        continue
                    seen_frame_ids.add(frame_id)
                    all_frames.append(frame)
                    new_frames += 1

                logger.info(
                    "Page %d: %d frames (%d new, total so far: %d)",
                    page,
                    len(data),
                    new_frames,
                    len(all_frames),
                )

                if max_images and len(all_frames) >= max_images:
                    all_frames = all_frames[:max_images]
                    break

                # Mapillary pagination: next cursor in paging.next
                next_cursor = resp.get("paging", {}).get("next")
                if not next_cursor:
                    break
                params["after"] = next_cursor
        except RuntimeError:
            if depth >= MAX_TILE_SUBDIVISION_DEPTH:
                raise
            logger.warning(
                "Tile query failed, subdividing bbox %s at depth %d",
                _bbox_to_string(tile_bbox),
                depth + 1,
            )
            tile_queue = [(child_bbox, depth + 1) for child_bbox in _iter_bbox_tiles(tile_bbox, 2)] + tile_queue
            continue

        if max_images and len(all_frames) >= max_images:
            break

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
    overwrite_existing: bool = False,
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
            if os.path.exists(out_path) and not overwrite_existing:
                continue

            image_url = _preferred_image_url(frame)
            if not image_url:
                image_url = _fetch_image_url(frame_id)
                frame["thumb_original_url"] = image_url or frame.get("thumb_original_url", "")

            if not image_url:
                logger.warning("No downloadable image URL for frame %s — skipping", frame_id)
                continue

            _download_file(image_url, out_path)


def load_sequences(data_dir: str = DATA_RAW) -> list[dict]:
    """Load previously fetched sequences JSON without re-calling the API."""
    path = os.path.join(data_dir, "mapillary_sequences.json")
    with open(path) as f:
        return json.load(f)


def _group_by_sequence(frames: list[dict]) -> list[dict]:
    """Group flat frame list into per-sequence dicts with ordered frame lists."""
    seq_map: dict[str, list[dict]] = {}
    for frame in frames:
        seq_id = frame.get("sequence_id") or frame.get("sequence") or "unknown"
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
        "sequence_id": raw.get("sequence_id") or raw.get("sequence", ""),
        "thumb_original_url": raw.get("thumb_original_url", ""),
        "thumb_2048_url": raw.get("thumb_2048_url", ""),
        "thumb_1024_url": raw.get("thumb_1024_url", ""),
    }


def _bbox_to_string(bbox: dict[str, float]) -> str:
    return f"{bbox['min_lon']},{bbox['min_lat']},{bbox['max_lon']},{bbox['max_lat']}"


def _iter_bbox_tiles(bbox: dict[str, float], grid_size: int) -> list[dict[str, float]]:
    lon_step = (bbox["max_lon"] - bbox["min_lon"]) / grid_size
    lat_step = (bbox["max_lat"] - bbox["min_lat"]) / grid_size
    tiles: list[dict[str, float]] = []

    for lon_index in range(grid_size):
        min_lon = bbox["min_lon"] + lon_index * lon_step
        max_lon = bbox["max_lon"] if lon_index == grid_size - 1 else min_lon + lon_step
        for lat_index in range(grid_size):
            min_lat = bbox["min_lat"] + lat_index * lat_step
            max_lat = bbox["max_lat"] if lat_index == grid_size - 1 else min_lat + lat_step
            tiles.append(
                {
                    "min_lon": min_lon,
                    "min_lat": min_lat,
                    "max_lon": max_lon,
                    "max_lat": max_lat,
                }
            )

    return tiles


def _preferred_image_url(frame: dict) -> str:
    return frame.get("thumb_original_url") or ""


def _fetch_image_url(image_id: str) -> str | None:
    """Fetch the original downloadable image URL for a single image ID."""
    url = IMAGE_DETAIL_ENDPOINT.format(image_id=image_id)
    params = {"fields": "thumb_original_url,thumb_2048_url,thumb_1024_url", **_auth_params()}
    try:
        resp = _get_with_retry(url, params)
        return resp.get("thumb_original_url")
    except Exception as exc:
        logger.warning("Could not fetch image URL for %s: %s", image_id, exc)
        return None


def _get_with_retry(url: str, params: dict, max_retries: int = 3) -> dict:
    """GET with simple retry on timeouts and transient 429/5xx failures."""
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=60)
        except requests.exceptions.RequestException as exc:
            logger.warning("Request error on attempt %d, waiting %ds: %s", attempt, RETRY_WAIT, exc)
            time.sleep(RETRY_WAIT * attempt)
            continue
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
