import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config.settings import DATA_OUTPUT, DATA_RAW, LIVE_CAMERAS, LIVE_CAMERA_INTERVAL_SEC
from process.live_camera import analyze_camera, load_camera_store, save_camera_store
from serve.routes.cameras import build_cameras_router
from serve.routes.data import build_router
from serve.routes.followup import build_followup_router
from serve.routes.review import build_review_router

logger = logging.getLogger(__name__)


async def _camera_loop() -> None:
    try:
        while True:
            store = load_camera_store()
            for cam in LIVE_CAMERAS:
                try:
                    result = await asyncio.to_thread(analyze_camera, cam)
                    store[cam["id"]] = result
                    save_camera_store(store)
                    logger.info(
                        "Camera %s analyzed: condition=%s",
                        cam["id"],
                        (result.get("analysis") or {}).get("condition", "unknown"),
                    )
                except Exception as exc:
                    logger.error("Camera %s analysis failed: %s", cam["id"], exc)
                    if cam["id"] not in store:
                        store[cam["id"]] = {
                            "camera_id": cam["id"],
                            "name": cam.get("name", cam["id"]),
                            "lat": cam.get("lat"),
                            "lon": cam.get("lon"),
                            "status": "error",
                            "error": str(exc),
                        }
                        save_camera_store(store)
            await asyncio.sleep(LIVE_CAMERA_INTERVAL_SEC)
    except asyncio.CancelledError:
        logger.info("Camera loop cancelled")
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    camera_task = asyncio.create_task(_camera_loop())
    try:
        yield
    finally:
        camera_task.cancel()
        try:
            await camera_task
        except asyncio.CancelledError:
            pass


def create_app(
    data_raw_dir: str = DATA_RAW,
    data_output_dir: str = DATA_OUTPUT,
    static_dir: str | None = None,
) -> FastAPI:
    if static_dir is None:
        static_dir = os.path.join(os.path.dirname(__file__), "static")

    app = FastAPI(title="GeoSTL Hackathon", version="0.1.0", lifespan=lifespan)
    app.include_router(
        build_router(data_raw_dir=data_raw_dir, data_output_dir=data_output_dir),
        prefix="/api",
    )
    app.include_router(build_followup_router(), prefix="/api")
    app.include_router(build_cameras_router(), prefix="/api")
    app.include_router(build_review_router(), prefix="/api")

    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(os.path.join(static_dir, "index.html"))

    return app


app = create_app()
