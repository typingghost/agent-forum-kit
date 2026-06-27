from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import PROJECT_ROOT, settings
from app.database import get_connection, init_schema
from app.routes.forum import router as forum_router
from app.routes.library import router as library_router
from app.routes.meeting_room import router as meeting_room_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    with get_connection() as conn:
        init_schema(conn)
    yield


app = FastAPI(title="Agent Forum Kit", version="0.5.0", lifespan=lifespan)
app.include_router(forum_router)
app.include_router(library_router)
app.include_router(meeting_room_router)


@app.middleware("http")
async def no_cache_static_assets(request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response

static_dir = PROJECT_ROOT / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")
upload_dir = settings.upload_root or PROJECT_ROOT / "data" / "uploads"
upload_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=upload_dir), name="uploads")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "agent-forum-kit"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(static_dir / "index.html")
