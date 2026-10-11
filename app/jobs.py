"""In-memory job registry: one download, one temp directory, one event queue."""

from __future__ import annotations

import os
import queue
import shutil
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TTL_SECONDS = 30 * 60
# A download still running past the TTL is left alone up to this age.
MAX_RUNNING_SECONDS = 4 * 3600
SWEEP_INTERVAL = 5 * 60
# Dedicated folder for job files (Docker volume). Unset: the system temp dir.
JOBS_DIR = os.environ.get("JOBS_DIR") or None


@dataclass
class JobState:
    """Everything the API knows about one download."""

    id: str
    tmpdir: Path
    owner: int | None = None  # SSO user id; None when authentication is off
    status: str = "pending"  # pending | running | done | failed
    stage: str = "queued"  # queued | video | audio | merging | embedding | ready
    percent: float = 0.0
    speed: str | None = None
    eta: int | None = None
    error: str | None = None
    filepath: Path | None = None
    filename: str | None = None
    created_at: float = field(default_factory=time.time)
    events: queue.Queue = field(default_factory=queue.Queue)

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "stage": self.stage,
            "percent": round(self.percent, 1),
            "speed": self.speed,
            "eta": self.eta,
            "error": self.error,
            "filename": self.filename,
        }

    def emit(self) -> None:
        self.events.put(self.snapshot())

    def fail(self, message: str) -> None:
        self.status = "failed"
        self.error = message
        self.emit()

    def finish(self, path: Path) -> None:
        self.status = "done"
        self.stage = "ready"
        self.percent = 100.0
        self.filepath = path
        self.filename = path.name
        self.emit()


class JobRegistry:
    """Thread-safe map of job id to state, with temp-dir cleanup."""

    def __init__(self) -> None:
        self._jobs: dict[str, JobState] = {}
        self._lock = threading.Lock()

    def create(self, owner: int | None = None) -> JobState:
        job_id = uuid.uuid4().hex
        job = JobState(id=job_id, tmpdir=Path(tempfile.mkdtemp(prefix="ytdl-", dir=JOBS_DIR)), owner=owner)
        with self._lock:
            self._jobs[job_id] = job
        return job

    def get(self, job_id: str) -> JobState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def active(self) -> int:
        """Jobs still downloading (not yet done or failed)."""
        with self._lock:
            return sum(j.status in ("pending", "running") for j in self._jobs.values())

    def remove(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.pop(job_id, None)
        if job is not None:
            shutil.rmtree(job.tmpdir, ignore_errors=True)

    def sweep(self, now: float | None = None) -> list[str]:
        """Drop jobs older than the TTL. Returns the ids removed."""
        now = now or time.time()
        with self._lock:
            stale = [
                j.id for j in self._jobs.values()
                if j.created_at < now - TTL_SECONDS
                and (j.status in ("done", "failed") or j.created_at < now - MAX_RUNNING_SECONDS)
            ]
        for job_id in stale:
            self.remove(job_id)
        return stale

    def purge_orphans(self) -> None:
        """Jobs live in memory: files left by a previous run belong to nobody."""
        if JOBS_DIR is None:
            return
        Path(JOBS_DIR).mkdir(parents=True, exist_ok=True)
        for path in Path(JOBS_DIR).glob("ytdl-*"):
            shutil.rmtree(path, ignore_errors=True)

    def start_sweeper(self) -> threading.Thread:
        def loop() -> None:
            while True:
                time.sleep(SWEEP_INTERVAL)
                self.sweep()

        thread = threading.Thread(target=loop, daemon=True, name="job-sweeper")
        thread.start()
        return thread


registry = JobRegistry()
