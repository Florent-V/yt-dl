"""FastAPI application for the local YouTube downloader."""

from __future__ import annotations

import asyncio
import functools
import json
import queue
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from app import worker
from app.downloader import Choices, InvalidChoices, validate
from app.jobs import registry
from app.probe import ProbeError, probe

STATIC_DIR = Path(__file__).parent / "static"
KEEPALIVE_SECONDS = 15
TERMINAL = ("done", "failed")


class ProbeRequest(BaseModel):
    url: str


class JobRequest(BaseModel):
    url: str
    mode: str
    height: int | None = None
    container: str = "mp4"
    subtitle_langs: list[str] = Field(default_factory=list)
    include_auto: bool = False
    audio_format: str = "best"
    bitrate: str | None = None


def check_ffmpeg() -> None:
    """Fail fast when ffmpeg is missing — merging and transcoding need it."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg was not found on PATH. Install it before starting the server "
            "(Debian/Ubuntu: sudo apt install ffmpeg)."
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    check_ffmpeg()
    registry.start_sweeper()
    yield


app = FastAPI(title="yt-dl", docs_url=None, redoc_url=None, lifespan=lifespan)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/probe")
def api_probe(request: ProbeRequest) -> dict:
    _require_http(request.url)
    try:
        return probe(request.url)
    except ProbeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/jobs")
def api_create_job(request: JobRequest) -> dict[str, str]:
    _require_http(request.url)
    choices = Choices(
        mode=request.mode,
        height=request.height,
        container=request.container,
        subtitle_langs=request.subtitle_langs,
        include_auto=request.include_auto,
        audio_format=request.audio_format,
        bitrate=request.bitrate,
    )
    try:
        validate(choices)
    except InvalidChoices as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    job = registry.create()
    worker.start(job, request.url, choices)
    return {"job_id": job.id}


@app.get("/api/jobs/{job_id}")
def api_job_status(job_id: str) -> dict:
    return _job_or_404(job_id).snapshot()


@app.get("/api/jobs/{job_id}/events")
async def api_job_events(job_id: str) -> StreamingResponse:
    job = _job_or_404(job_id)

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
def api_job_file(job_id: str) -> FileResponse:
    job = _job_or_404(job_id)
    if job.status != "done" or job.filepath is None:
        raise HTTPException(status_code=409, detail="This download is not ready yet.")
    return FileResponse(
        job.filepath,
        filename=job.filepath.name,
        media_type="application/octet-stream",
        background=BackgroundTask(registry.remove, job.id),
    )


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


def _require_http(url: str) -> None:
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Only http(s) URLs are supported.")


def _job_or_404(job_id: str):
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job.")
    return job
