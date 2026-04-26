"""
Live camera capture pipeline: yt-dlp → ffmpeg → S3 → Pegasus.
All functions are synchronous — wrap with asyncio.to_thread() at the call site.
"""

import json
import logging
import os
import re
import subprocess
import tempfile
import time
from typing import Optional

from config.settings import (
    LIVE_CAMERA_CLIP_DURATION_SEC,
    LIVE_CAMERAS_OUTPUT,
    S3_WORKSHOP_BUCKET,
)
from process.pegasus import DEFAULT_PROMPT, describe_clip, parse_description
from process.twelvelabs import upload_to_s3

logger = logging.getLogger(__name__)


def _extract_video_id(youtube_url: str) -> Optional[str]:
    patterns = [
        r"[?&]v=([A-Za-z0-9_-]{11})",
        r"youtu\.be/([A-Za-z0-9_-]{11})",
        r"/live/([A-Za-z0-9_-]{11})",
    ]
    for pat in patterns:
        m = re.search(pat, youtube_url)
        if m:
            return m.group(1)
    return None


def embed_url(youtube_url: str) -> Optional[str]:
    """Convert a YouTube watch/live URL to an embeddable iframe src."""
    vid_id = _extract_video_id(youtube_url)
    if not vid_id:
        return None
    return f"https://www.youtube.com/embed/{vid_id}?autoplay=1&mute=1"


def get_stream_url(youtube_url: str) -> str:
    """Run yt-dlp -g to get the raw HLS/m3u8 stream URL."""
    result = subprocess.run(
        ["yt-dlp", "-g", "--no-playlist", youtube_url],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed (rc={result.returncode}): {result.stderr.strip()}")
    url = result.stdout.strip().splitlines()[0]
    if not url:
        raise RuntimeError("yt-dlp returned empty stream URL")
    return url


def capture_clip(stream_url: str, duration_sec: int = LIVE_CAMERA_CLIP_DURATION_SEC) -> str:
    """
    Use ffmpeg to record duration_sec seconds from the stream into a temp MP4.
    Returns the temp file path. Caller must delete it.
    """
    fd, out_path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)

    cmd = [
        "ffmpeg", "-y",
        "-i", stream_url,
        "-t", str(duration_sec),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-vf", "scale='min(1280,iw)':-2",
        "-movflags", "+faststart",
        out_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=duration_sec + 90)
    if result.returncode != 0:
        os.unlink(out_path)
        raise RuntimeError(f"ffmpeg failed: {result.stderr[-500:]}")
    return out_path


def analyze_camera(camera: dict) -> dict:
    """
    Full pipeline for one camera config dict.
    Returns the analysis record saved in live_cameras.json.
    Raises on failure — caller (lifespan loop) should catch broadly.
    """
    camera_id = camera["id"]
    youtube_url = camera["youtube_url"]
    clip_path = None

    try:
        stream_url = get_stream_url(youtube_url)
        clip_path = capture_clip(stream_url)

        s3_key = f"live_cameras/{camera_id}/{int(time.time())}.mp4"
        s3_uri = upload_to_s3(clip_path, s3_key, bucket=S3_WORKSHOP_BUCKET)

        raw_text = describe_clip(s3_uri, prompt=DEFAULT_PROMPT)
        parsed = parse_description(raw_text)

        return {
            "camera_id": camera_id,
            "name": camera["name"],
            "lat": camera["lat"],
            "lon": camera["lon"],
            "youtube_url": youtube_url,
            "embed_url": embed_url(youtube_url),
            "clip_s3_uri": s3_uri,
            "analysis": parsed,
            "analyzed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "ok",
        }
    finally:
        if clip_path and os.path.exists(clip_path):
            os.unlink(clip_path)


def load_camera_store() -> dict:
    """Load live_cameras.json; returns {} if missing or malformed."""
    if not os.path.exists(LIVE_CAMERAS_OUTPUT):
        return {}
    try:
        with open(LIVE_CAMERAS_OUTPUT) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_camera_store(store: dict) -> None:
    """Atomically write the store dict to live_cameras.json."""
    os.makedirs(os.path.dirname(LIVE_CAMERAS_OUTPUT), exist_ok=True)
    tmp = LIVE_CAMERAS_OUTPUT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(store, f, indent=2)
    os.replace(tmp, LIVE_CAMERAS_OUTPUT)
