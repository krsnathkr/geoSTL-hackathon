"""
Per-event follow-up video processing: upload → Marengo embed → Pegasus describe → sidecar.
"""

import json
import logging
import os
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone

from config.settings import DATA_OUTPUT, S3_WORKSHOP_BUCKET
from process.embeddings import ensure_index
from process.embeddings import get_client as get_os_client
from process.embeddings import index_frame
from process.pegasus import describe_clip, parse_description
from process.twelvelabs import embed_video, upload_to_s3

logger = logging.getLogger(__name__)

FOLLOWUPS_PATH = os.path.join(DATA_OUTPUT, "event_followups.json")
_followups_lock = threading.Lock()
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def create_job(detection_id: str) -> str:
    job_id = f"{detection_id}-{int(time.time() * 1000)}"
    with _jobs_lock:
        _jobs[job_id] = {"status": "queued", "detection_id": detection_id}
    return job_id


def get_job(job_id: str) -> dict | None:
    with _jobs_lock:
        return dict(_jobs.get(job_id, {})) or None


def run_followup(job_id: str, detection_id: str, local_mp4: str) -> None:
    """Entry point for background task: reencode → S3 → Marengo → Pegasus → sidecar."""

    def _set(status: str, **kwargs):
        with _jobs_lock:
            _jobs[job_id].update({"status": status, **kwargs})

    reencoded = None
    try:
        _set("uploading")
        reencoded = _reencode_for_pegasus(local_mp4)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        s3_key = f"event-followups/{detection_id}/{ts}.mp4"
        s3_uri = upload_to_s3(reencoded, s3_key, bucket=S3_WORKSHOP_BUCKET)

        _set("embedding")
        marengo_indexed = False
        try:
            embedding = embed_video(s3_uri)
            os_client = get_os_client()
            ensure_index(os_client)
            index_frame(
                {
                    "id": job_id,
                    "embedding": embedding,
                    "lat": None,
                    "lon": None,
                    "sequence_id": detection_id,
                    "s3_uri": s3_uri,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                client=os_client,
            )
            marengo_indexed = True
        except Exception as embed_exc:
            logger.warning("Marengo video embedding skipped: %s", embed_exc)

        _set("describing")
        raw_text = describe_clip(s3_uri)
        parsed = parse_description(raw_text)

        result = {
            "clip_s3_uri": s3_uri,
            "pegasus": parsed,
            "marengo_indexed": marengo_indexed,
            "embedding_doc_id": job_id if marengo_indexed else None,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }
        _save_followup(detection_id, result)
        _set("done", result=result)

    except Exception as exc:
        logger.exception("Followup job %s failed", job_id)
        _set("error", error=str(exc))
    finally:
        for path in [reencoded, local_mp4]:
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass


def _reencode_for_pegasus(input_path: str) -> str:
    fd, output_path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-r", "24",
        "-vf", "scale='min(1280,iw)':-2",
        "-movflags", "+faststart",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        os.unlink(output_path)
        raise RuntimeError(f"ffmpeg re-encode failed: {result.stderr[-500:]}")
    return output_path


def _save_followup(detection_id: str, result: dict) -> None:
    with _followups_lock:
        data: dict = {}
        if os.path.exists(FOLLOWUPS_PATH):
            try:
                with open(FOLLOWUPS_PATH) as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                data = {}
        data[detection_id] = result
        os.makedirs(os.path.dirname(FOLLOWUPS_PATH), exist_ok=True)
        tmp = FOLLOWUPS_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, FOLLOWUPS_PATH)


def load_followup(detection_id: str) -> dict | None:
    if not os.path.exists(FOLLOWUPS_PATH):
        return None
    try:
        with open(FOLLOWUPS_PATH) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    return data.get(detection_id)


def delete_followup(detection_id: str) -> bool:
    with _followups_lock:
        if not os.path.exists(FOLLOWUPS_PATH):
            return False
        try:
            with open(FOLLOWUPS_PATH) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return False
        if detection_id not in data:
            return False
        del data[detection_id]
        tmp = FOLLOWUPS_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, FOLLOWUPS_PATH)
        return True


def load_all_followups() -> dict:
    if not os.path.exists(FOLLOWUPS_PATH):
        return {}
    try:
        with open(FOLLOWUPS_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
