"""FastAPI application for the local YouTube downloader."""

from __future__ import annotations

import shutil
from contextlib import asynccontextmanager

from fastapi import FastAPI


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
    yield


app = FastAPI(title="yt-dl", docs_url=None, redoc_url=None, lifespan=lifespan)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
