import json
import os
import threading
import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config.settings import DATA_OUTPUT

REVIEWS_PATH = os.path.join(DATA_OUTPUT, "event_reviews.json")
_reviews_lock = threading.Lock()


class ReviewPayload(BaseModel):
    review_status: str
    override_type: Optional[str] = None
    override_condition: Optional[str] = None
    override_sidewalk_presence: Optional[str] = None
    notes: Optional[str] = None


def _load() -> dict:
    if not os.path.exists(REVIEWS_PATH):
        return {}
    try:
        with open(REVIEWS_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(REVIEWS_PATH), exist_ok=True)
    tmp = REVIEWS_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, REVIEWS_PATH)


def build_review_router() -> APIRouter:
    router = APIRouter()

    @router.post("/events/{detection_id}/review")
    def submit_review(detection_id: str, payload: ReviewPayload) -> dict:
        with _reviews_lock:
            data = _load()
            data[detection_id] = {
                "detection_id": detection_id,
                "review_status": payload.review_status,
                "override_type": payload.override_type,
                "override_condition": payload.override_condition,
                "override_sidewalk_presence": payload.override_sidewalk_presence,
                "notes": payload.notes,
                "reviewed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            _save(data)
        return {"status": "saved", "detection_id": detection_id}

    @router.get("/events/{detection_id}/review")
    def get_review(detection_id: str) -> dict:
        data = _load()
        if detection_id not in data:
            raise HTTPException(status_code=404, detail="No review for this detection")
        return data[detection_id]

    @router.delete("/events/{detection_id}/review")
    def delete_review(detection_id: str) -> dict:
        with _reviews_lock:
            data = _load()
            data.pop(detection_id, None)
            _save(data)
        return {"status": "deleted"}

    @router.get("/reviews")
    def list_reviews() -> dict:
        return {"reviews": _load()}

    return router
