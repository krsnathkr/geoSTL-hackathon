import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config.settings import DATA_OUTPUT, DATA_RAW
from serve.routes.data import build_router


def create_app(
    data_raw_dir: str = DATA_RAW,
    data_output_dir: str = DATA_OUTPUT,
    static_dir: str | None = None,
) -> FastAPI:
    if static_dir is None:
        static_dir = os.path.join(os.path.dirname(__file__), "static")

    app = FastAPI(title="GeoSTL Hackathon", version="0.1.0")
    app.include_router(
        build_router(data_raw_dir=data_raw_dir, data_output_dir=data_output_dir),
        prefix="/api",
    )

    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(os.path.join(static_dir, "index.html"))

    return app


app = create_app()
