"""FastAPI application for the local YouTube downloader."""

from __future__ import annotations

import asyncio
import base64
import functools
import hashlib
import json
import os
import queue
import re
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from app import auth, jobs, worker
from app.downloader import Choices, InvalidChoices, validate
from app.jobs import registry
from app.probe import ProbeError, probe

STATIC_DIR = Path(__file__).parent / "static"
KEEPALIVE_SECONDS = 15
TERMINAL = ("done", "failed")
# Downloads running at once, all users together (CPU, bandwidth, disk).
MAX_ACTIVE_JOBS = int(os.environ.get("MAX_ACTIVE_JOBS", "3"))
MAX_URL_LENGTH = 2048
# Refuse new downloads below this much free space where jobs are written.
MIN_FREE_BYTES = int(os.environ.get("MIN_FREE_MB", "1024")) * 1024 * 1024


class ProbeRequest(BaseModel):
    url: str = Field(max_length=MAX_URL_LENGTH)


class JobRequest(BaseModel):
    url: str = Field(max_length=MAX_URL_LENGTH)
    mode: str
    height: int | None = None
    container: str = "mp4"
    subtitle_langs: list[str] = Field(default_factory=list)
    include_auto: bool = False
    audio_format: str = "best"
    bitrate: str | None = None
    audio_lang: str | None = None
    all_audio_langs: bool = False


def check_ffmpeg() -> None:
    """Fail fast when ffmpeg is missing — merging and transcoding need it."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg was not found on PATH. Install it before starting the server "
            "(Debian/Ubuntu: sudo apt install ffmpeg)."
        )


def check_auth() -> None:
    """With REQUIRE_AUTH set, a missing SSO configuration must not open the app."""
    if auth.auth_required() and auth.CONFIG is None:
        raise RuntimeError("REQUIRE_AUTH is set but OAUTH_SERVER_URL is empty.")


@asynccontextmanager
async def lifespan(_: FastAPI):
    check_auth()
    check_ffmpeg()
    registry.purge_orphans()
    registry.start_sweeper()
    yield


app = FastAPI(title="yt-dl", docs_url=None, redoc_url=None, lifespan=lifespan)
app.include_router(auth.router)

# Everything under /api except the health check requires a signed-in user
# (a no-op when authentication is off, see app/auth.py).
PROTECTED = [Depends(auth.require_user)]
User = Annotated[dict | None, Depends(auth.require_user)]


def _script_hashes(html: str) -> str:
    """CSP sources for the page's inline scripts, so no other script can run."""
    scripts = re.findall(r"<script>(.*?)</script>", html, flags=re.S)
    return " ".join(
        "'sha256-%s'" % base64.b64encode(hashlib.sha256(s.encode()).digest()).decode()
        for s in scripts
    )


CSP = "; ".join([
    "default-src 'self'",
    f"script-src 'self' {_script_hashes((STATIC_DIR / 'index.html').read_text())}",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' https: data:",  # video thumbnails come from the sites' CDNs
    "connect-src 'self'",
    "worker-src 'self'",
    "manifest-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if auth.CONFIG is not None and auth.CONFIG.secure_cookie:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    if request.url.path.startswith(("/api/", "/auth/")):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/probe", dependencies=PROTECTED)
def api_probe(request: ProbeRequest) -> dict:
    _require_http(request.url)
    try:
        return probe(request.url)
    except ProbeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/jobs")
def api_create_job(request: JobRequest, user: User) -> dict[str, str]:
    _require_http(request.url)
    choices = Choices(
        mode=request.mode,
        height=request.height,
        container=request.container,
        subtitle_langs=request.subtitle_langs,
        include_auto=request.include_auto,
        audio_format=request.audio_format,
        bitrate=request.bitrate,
        audio_lang=request.audio_lang,
        all_audio_langs=request.all_audio_langs,
    )
    try:
        validate(choices)
    except InvalidChoices as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if registry.active() >= MAX_ACTIVE_JOBS:
        raise HTTPException(status_code=429, detail="Too many downloads in progress, try again shortly.")
    if shutil.disk_usage(jobs.JOBS_DIR or tempfile.gettempdir()).free < MIN_FREE_BYTES:
        raise HTTPException(status_code=507, detail="Not enough disk space on the server.")
    job = registry.create(owner=_owner(user))
    worker.start(job, request.url, choices)
    return {"job_id": job.id}


@app.get("/api/jobs/{job_id}")
def api_job_status(job_id: str, user: User) -> dict:
    return _job_or_404(job_id, user).snapshot()


@app.get("/api/jobs/{job_id}/events")
async def api_job_events(job_id: str, user: User) -> StreamingResponse:
    job = _job_or_404(job_id, user)

    async def stream() -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        while True:
            try:
                payload = job.events.get_nowait()
            except queue.Empty:
                # Nothing pending: a job that already finished still owes the
                # client one terminal event, otherwise wait for the next update.
                if job.status in TERMINAL:
                    yield f"data: {json.dumps(job.snapshot())}\n\n"
                    return
                getter = functools.partial(job.events.get, True, KEEPALIVE_SECONDS)
                try:
                    payload = await loop.run_in_executor(None, getter)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
            yield f"data: {json.dumps(payload)}\n\n"
            if payload["status"] in TERMINAL:
                return

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/jobs/{job_id}/file")
def api_job_file(job_id: str, user: User) -> FileResponse:
    job = _job_or_404(job_id, user)
    if job.status != "done" or job.filepath is None:
        raise HTTPException(status_code=409, detail="This download is not ready yet.")
    return FileResponse(
        job.filepath,
        filename=job.filepath.name,
        media_type="application/octet-stream",
        background=BackgroundTask(registry.remove, job.id),
    )


@app.get("/")
def index(request: Request):
    try:
        auth.require_user(request)
    except HTTPException:
        return auth.login_redirect(request)
    return FileResponse(STATIC_DIR / "index.html")


# PWA files live at the root: a service worker only controls pages under the
# path it is served from, so /sw.js is needed to cover "/".
PWA_FILES = {
    "manifest.webmanifest": "application/manifest+json",
    "sw.js": "text/javascript",
    "icon-192.png": "image/png",
    "icon-512.png": "image/png",
    "icon-maskable-512.png": "image/png",
    "favicon.ico": "image/x-icon",
    "apple-touch-icon.png": "image/png",
}


@app.get("/{name}", include_in_schema=False)
def pwa_file(name: str) -> FileResponse:
    media_type = PWA_FILES.get(name)
    if media_type is None:
        raise HTTPException(status_code=404)
    headers = {"Cache-Control": "no-cache"} if name == "sw.js" else None
    return FileResponse(STATIC_DIR / name, media_type=media_type, headers=headers)


def _require_http(url: str) -> None:
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Only http(s) URLs are supported.")


def _owner(user: dict | None) -> int | None:
    return user["id"] if user else None


def _job_or_404(job_id: str, user: dict | None):
    """A job is only visible to the user who started it."""
    job = registry.get(job_id)
    if job is None or job.owner != _owner(user):
        raise HTTPException(status_code=404, detail="Unknown job.")
    return job
