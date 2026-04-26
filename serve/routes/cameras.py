"""
GET /api/cameras                          — list all cameras with latest analysis
GET /api/cameras/{camera_id}/latest-analysis — single camera latest result
"""

import time

from fastapi import APIRouter, HTTPException

from config.settings import LIVE_CAMERAS
from process.live_camera import embed_url, load_camera_store


def build_cameras_router() -> APIRouter:
    router = APIRouter()

    @router.get("/cameras")
    def list_cameras() -> dict:
        store = load_camera_store()
        cameras = []
        for cam in LIVE_CAMERAS:
            cid = cam["id"]
            latest = store.get(cid, {})
            cameras.append({
                "camera_id": cid,
                "name": cam["name"],
                "lat": cam["lat"],
                "lon": cam["lon"],
                "embed_url": embed_url(cam["youtube_url"]),
                "analysis": latest.get("analysis"),
                "analyzed_at": latest.get("analyzed_at"),
                "status": latest.get("status", "pending"),
            })
        return {
            "cameras": cameras,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    @router.get("/cameras/{camera_id}/latest-analysis")
    def latest_analysis(camera_id: str) -> dict:
        store = load_camera_store()
        if camera_id not in store:
            raise HTTPException(status_code=404, detail="No analysis yet for this camera")
        return store[camera_id]

    return router
