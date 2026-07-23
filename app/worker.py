"""Run one download on a background thread, pushing progress to its job."""

from __future__ import annotations

import threading
from typing import Any

from app import downloader
from app.downloader import Choices
from app.jobs import JobState

PP_STAGES = {
    "Merger": "merging",
    "FFmpegMerger": "merging",
    "FFmpegEmbedSubtitle": "embedding",
    "EmbedSubtitle": "embedding",
    "FFmpegExtractAudio": "audio",
    "ExtractAudio": "audio",
}


def make_hooks(job: JobState):
    """Build the (progress, postprocessor) hook pair for a job."""

    def progress(payload: dict[str, Any]) -> None:
        if payload.get("status") != "downloading":
            return
        info = payload.get("info_dict") or {}
        job.stage = "audio" if info.get("vcodec") in (None, "none") else "video"

        total = payload.get("total_bytes") or payload.get("total_bytes_estimate")
        downloaded = payload.get("downloaded_bytes") or 0
        job.percent = (downloaded / total * 100) if total else 0.0
        job.speed = _speed(payload.get("speed"))
        job.eta = payload.get("eta")
        job.emit()

    def postprocess(payload: dict[str, Any]) -> None:
        stage = PP_STAGES.get(str(payload.get("postprocessor")))
        if stage and payload.get("status") == "started":
            job.stage = stage
            job.emit()

    return progress, postprocess


def run_job(job: JobState, url: str, choices: Choices) -> None:
    """Download synchronously, updating the job as it goes."""
    job.status = "running"
    job.emit()
    progress, postprocess = make_hooks(job)
    try:
        path = downloader.run(url, choices, job.tmpdir, progress, postprocess)
    except Exception as exc:  # yt-dlp raises a wide variety of errors
        job.fail(_clean(str(exc)))
        return
    job.finish(path)


def start(job: JobState, url: str, choices: Choices) -> threading.Thread:
    thread = threading.Thread(
        target=run_job, args=(job, url, choices), daemon=True, name=f"job-{job.id[:8]}"
    )
    thread.start()
    return thread


def _speed(value: float | None) -> str | None:
    if not value:
        return None
    mib = value / 1024 / 1024
    return f"{mib:.1f} MiB/s" if mib >= 1 else f"{value / 1024:.0f} KiB/s"


def _clean(message: str) -> str:
    return message.replace("ERROR: ", "").strip()
