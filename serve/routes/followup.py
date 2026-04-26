import os
import tempfile

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile

from process.embeddings import get_client as get_os_client
from process.embeddings import knn_search
from process.followup import (
    create_job,
    delete_followup,
    get_job,
    load_followup,
    run_followup,
)
from process.twelvelabs import embed_video


def build_followup_router() -> APIRouter:
    router = APIRouter()

    @router.post("/events/{detection_id}/followup-video")
    async def upload_followup_video(
        detection_id: str,
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
    ) -> dict:
        suffix = os.path.splitext(file.filename or "upload")[1] or ".mp4"
        fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "wb") as fh:
            content = await file.read()
            fh.write(content)

        job_id = create_job(detection_id)
        background_tasks.add_task(run_followup, job_id, detection_id, tmp_path)
        return {"job_id": job_id, "status": "queued"}

    @router.get("/events/{detection_id}/followup")
    def get_followup(
        detection_id: str,
        job_id: str | None = Query(default=None),
    ) -> dict:
        if job_id:
            job = get_job(job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="Job not found")
            return job
        result = load_followup(detection_id)
        if result is None:
            return {"status": "none"}
        return {"status": "done", "result": result}

    @router.delete("/events/{detection_id}/followup")
    def delete_followup_route(detection_id: str) -> dict:
        deleted = delete_followup(detection_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="No follow-up found")
        return {"status": "deleted"}

    @router.get("/events/{detection_id}/similar")
    def get_similar(detection_id: str, k: int = Query(default=5, ge=1, le=20)) -> dict:
        result = load_followup(detection_id)
        if result is None:
            raise HTTPException(status_code=404, detail="No follow-up for this detection")
        if not result.get("marengo_indexed"):
            raise HTTPException(
                status_code=422,
                detail="Marengo embedding not available for this follow-up (video inputType not supported by Bedrock)",
            )
        clip_uri = result.get("clip_s3_uri")
        if not clip_uri:
            raise HTTPException(status_code=404, detail="Follow-up has no clip URI")
        try:
            embedding = embed_video(clip_uri)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Marengo embed failed: {exc}") from exc
        hits = knn_search(embedding, k=k, client=get_os_client())
        return {"hits": hits}

    return router
