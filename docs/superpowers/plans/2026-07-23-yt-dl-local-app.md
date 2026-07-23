# yt-dl Local Downloader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A localhost web app that downloads a single YouTube video — with quality and subtitle choice, or audio-only at a chosen bitrate — and hands the file to the browser.

**Architecture:** One FastAPI process serves both a static HTML page and a JSON API. `yt-dlp` is used as a Python library in a worker thread per job. Job state is in-memory; progress reaches the browser over SSE; each job downloads into its own temp directory which is deleted after the file is sent.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, yt-dlp, ffmpeg (system), pytest, vanilla JS (no build step), `uv` for dependency management.

## Global Constraints

- Python `>=3.11` — the code uses `X | None` annotations and `from __future__ import annotations`.
- Dependencies limited to: `fastapi`, `uvicorn[standard]`, `yt-dlp`. Dev extras: `pytest`, `httpx`.
- No database, no persistence, no auth. Single user, localhost only.
- No frontend build step. `app/static/index.html` is one self-contained file.
- `noplaylist: True` on every `yt-dlp` call — a URL carrying `list=` must yield one video.
- Every network-touching test is marked `@pytest.mark.network` and deselected by default.
- Temp directory TTL is 30 minutes; the sweeper runs every 5 minutes.
- Run everything through `uv run` — never a bare `python`/`pytest`.

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | uv project, deps, pytest markers |
| `app/probe.py` | URL → UI-shaped summary of qualities and subtitle tracks |
| `app/downloader.py` | `Choices` dataclass, validation, pure opts builder, download runner |
| `app/jobs.py` | `JobState`, thread-safe registry, TTL sweeper |
| `app/main.py` | FastAPI routes, SSE stream, startup checks, static mount |
| `app/static/index.html` | Entire UI |
| `run.sh` | Start command |
| `tests/*` | One test module per app module, plus API and network tests |

---

### Task 1: Project scaffold and ffmpeg startup check

**Files:**
- Create: `pyproject.toml`, `app/__init__.py`, `app/main.py`, `run.sh`, `tests/__init__.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: nothing
- Produces: `app.main.app` (FastAPI instance), `app.main.check_ffmpeg() -> None` (raises `RuntimeError` when ffmpeg is absent)

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "yt-dl"
version = "0.1.0"
description = "Local YouTube downloader for personal use"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "yt-dlp>=2025.1.15",
]

[project.optional-dependencies]
dev = ["pytest>=8", "httpx>=0.27"]

[tool.pytest.ini_options]
markers = ["network: test requires internet access"]
addopts = "-m 'not network'"
testpaths = ["tests"]
```

- [ ] **Step 2: Install dependencies**

```bash
uv sync --extra dev
```

Expected: creates `.venv/`, resolves fastapi, uvicorn, yt-dlp, pytest, httpx.

- [ ] **Step 3: Write the failing test**

Create `tests/test_api.py`:

```python
from fastapi.testclient import TestClient

from app.main import app, check_ffmpeg

client = TestClient(app)


def test_health_reports_ok():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_check_ffmpeg_raises_when_missing(monkeypatch):
    monkeypatch.setattr("app.main.shutil.which", lambda _: None)
    try:
        check_ffmpeg()
    except RuntimeError as exc:
        assert "ffmpeg" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
```

- [ ] **Step 4: Run it to make sure it fails**

Run: `uv run pytest tests/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 5: Write the minimal implementation**

Create empty `app/__init__.py` and `tests/__init__.py`. Create `app/main.py`:

```python
"""FastAPI application for the local YouTube downloader."""

from __future__ import annotations

import shutil

from fastapi import FastAPI

app = FastAPI(title="yt-dl", docs_url=None, redoc_url=None)


def check_ffmpeg() -> None:
    """Fail fast when ffmpeg is missing — merging and transcoding need it."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg was not found on PATH. Install it before starting the server "
            "(Debian/Ubuntu: sudo apt install ffmpeg)."
        )


@app.on_event("startup")
def on_startup() -> None:
    check_ffmpeg()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 6: Run the tests and make sure they pass**

Run: `uv run pytest tests/test_api.py -v`
Expected: 2 passed

- [ ] **Step 7: Create `run.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
exec uv run uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8000}" "$@"
```

Then: `chmod +x run.sh`

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock app tests run.sh
git commit -m "feat: scaffold FastAPI app with ffmpeg startup check"
```

---

### Task 2: Probe — shape yt-dlp info into a UI summary

**Files:**
- Create: `app/probe.py`, `tests/test_probe.py`, `tests/fixtures/__init__.py`
- Test: `tests/test_probe.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `app.probe.ProbeError(Exception)`
  - `app.probe.summarize(info: dict) -> dict` with keys `title`, `uploader`, `duration`, `thumbnail`, `video_qualities`, `subtitles`
  - `app.probe.probe(url: str) -> dict` (network; raises `ProbeError`)

- [ ] **Step 1: Write the failing test**

Create `tests/test_probe.py`:

```python
import pytest

from app.probe import ProbeError, probe, summarize

INFO = {
    "title": "Example Video",
    "uploader": "Example Channel",
    "duration": 212,
    "thumbnail": "https://example.com/thumb.jpg",
    "formats": [
        {"height": 1080, "vcodec": "avc1", "fps": 60, "filesize": 90_000_000},
        {"height": 1080, "vcodec": "vp9", "fps": 60, "filesize": 70_000_000},
        {"height": 720, "vcodec": "avc1", "fps": 30, "filesize_approx": 40_000_000},
        {"height": None, "vcodec": "none", "acodec": "opus", "filesize": 3_000_000},
        {"height": 360, "vcodec": "avc1", "fps": 30, "filesize": 10_000_000},
    ],
    "subtitles": {"en": [{"name": "English"}], "fr": [{"name": "French"}]},
    "automatic_captions": {"en": [{"name": "English (auto)"}], "de": [{}]},
}


def test_summarize_extracts_metadata():
    result = summarize(INFO)
    assert result["title"] == "Example Video"
    assert result["uploader"] == "Example Channel"
    assert result["duration"] == 212
    assert result["thumbnail"] == "https://example.com/thumb.jpg"


def test_qualities_are_deduped_and_descending():
    heights = [q["height"] for q in summarize(INFO)["video_qualities"]]
    assert heights == [1080, 720, 360]


def test_quality_keeps_largest_filesize_per_height():
    top = summarize(INFO)["video_qualities"][0]
    assert top["filesize_approx"] == 90_000_000
    assert top["label"] == "1080p"
    assert top["fps"] == 60


def test_audio_only_formats_are_skipped():
    assert all(q["height"] for q in summarize(INFO)["video_qualities"])


def test_manual_subtitles_come_first_and_auto_dupes_are_dropped():
    subs = summarize(INFO)["subtitles"]
    manual = [s for s in subs if not s["auto"]]
    auto = [s for s in subs if s["auto"]]
    assert [s["lang"] for s in manual] == ["en", "fr"]
    assert [s["lang"] for s in auto] == ["de"]


def test_subtitle_without_name_falls_back_to_lang_code():
    de = next(s for s in summarize(INFO)["subtitles"] if s["lang"] == "de")
    assert de["name"] == "de"


def test_missing_fields_get_safe_defaults():
    result = summarize({})
    assert result["title"] == "Untitled"
    assert result["duration"] == 0
    assert result["video_qualities"] == []
    assert result["subtitles"] == []


def test_probe_wraps_download_error(monkeypatch):
    import yt_dlp

    class Boom:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download):
            raise yt_dlp.utils.DownloadError("ERROR: Video unavailable")

    monkeypatch.setattr("app.probe.yt_dlp.YoutubeDL", lambda opts: Boom())
    with pytest.raises(ProbeError) as excinfo:
        probe("https://youtu.be/x")
    assert str(excinfo.value) == "Video unavailable"


@pytest.mark.network
def test_probe_real_video():
    result = probe("https://www.youtube.com/watch?v=aqz-KE-bpKQ")
    assert result["title"]
    assert result["video_qualities"]
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest tests/test_probe.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.probe'`

- [ ] **Step 3: Write the minimal implementation**

Create `app/probe.py`:

```python
"""Reduce a yt-dlp info dict to the small summary the UI needs."""

from __future__ import annotations

from typing import Any

import yt_dlp

PROBE_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
    "skip_download": True,
}


class ProbeError(Exception):
    """Raised when a URL cannot be inspected."""


def probe(url: str) -> dict[str, Any]:
    """Fetch metadata for a single video without downloading it."""
    try:
        with yt_dlp.YoutubeDL(PROBE_OPTS) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise ProbeError(_clean(str(exc))) from exc
    except Exception as exc:  # network stack, parsing, anything else
        raise ProbeError(str(exc)) from exc

    if info is None:
        raise ProbeError("No video found at that URL.")
    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            raise ProbeError("No video found at that URL.")
        info = entries[0]
    return summarize(info)


def summarize(info: dict[str, Any]) -> dict[str, Any]:
    """Shape a raw info dict into the fields the frontend consumes."""
    return {
        "title": info.get("title") or "Untitled",
        "uploader": info.get("uploader") or "",
        "duration": int(info.get("duration") or 0),
        "thumbnail": info.get("thumbnail") or "",
        "video_qualities": _qualities(info.get("formats") or []),
        "subtitles": _subtitles(info),
    }


def _qualities(formats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per distinct height, keeping the largest variant of each."""
    best: dict[int, dict[str, Any]] = {}
    for fmt in formats:
        height = fmt.get("height")
        if not height or fmt.get("vcodec") in (None, "none"):
            continue
        size = fmt.get("filesize") or fmt.get("filesize_approx")
        current = best.get(height)
        if current is None or (size or 0) > (current["filesize_approx"] or 0):
            best[height] = {
                "height": height,
                "label": f"{height}p",
                "fps": int(fmt.get("fps") or 0),
                "filesize_approx": size,
            }
    return sorted(best.values(), key=lambda q: q["height"], reverse=True)


def _subtitles(info: dict[str, Any]) -> list[dict[str, Any]]:
    """Manual tracks first, then auto-generated ones the manual list lacks."""
    manual = info.get("subtitles") or {}
    automatic = info.get("automatic_captions") or {}

    out = [
        {"lang": lang, "name": _track_name(tracks, lang), "auto": False}
        for lang, tracks in sorted(manual.items())
    ]
    out += [
        {"lang": lang, "name": _track_name(tracks, lang), "auto": True}
        for lang, tracks in sorted(automatic.items())
        if lang not in manual
    ]
    return out


def _track_name(tracks: list[dict[str, Any]], lang: str) -> str:
    for track in tracks:
        if track.get("name"):
            return str(track["name"])
    return lang


def _clean(message: str) -> str:
    return message.replace("ERROR: ", "").strip()
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `uv run pytest tests/test_probe.py -v`
Expected: 8 passed, 1 deselected (the network test)

- [ ] **Step 5: Commit**

```bash
git add app/probe.py tests/test_probe.py
git commit -m "feat: shape yt-dlp metadata into UI summary"
```

---

### Task 3: Downloader — choices, validation, opts builder

**Files:**
- Create: `app/downloader.py`, `tests/test_downloader.py`
- Test: `tests/test_downloader.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `app.downloader.Choices` dataclass: `mode`, `height`, `container`, `subtitle_langs`, `include_auto`, `audio_format`, `bitrate`
  - `app.downloader.InvalidChoices(ValueError)`
  - `app.downloader.validate(choices: Choices) -> None`
  - `app.downloader.build_opts(choices: Choices, outdir: Path, hook=None, pp_hook=None) -> dict`
  - `app.downloader.default_container(has_subtitles: bool) -> str`
  - `app.downloader.AUDIO_CODECS`, `app.downloader.BITRATES`

- [ ] **Step 1: Write the failing test**

Create `tests/test_downloader.py`:

```python
from pathlib import Path

import pytest

from app.downloader import (
    Choices,
    InvalidChoices,
    build_opts,
    default_container,
    validate,
)

OUT = Path("/tmp/job")


def test_video_format_selector_caps_height():
    opts = build_opts(Choices(mode="video", height=1080), OUT)
    assert opts["format"] == "bv*[height<=1080]+ba/b[height<=1080]"
    assert opts["merge_output_format"] == "mp4"


def test_video_without_height_takes_best():
    opts = build_opts(Choices(mode="video", height=None), OUT)
    assert opts["format"] == "bv*+ba/b"


def test_subtitles_enable_embedding():
    choices = Choices(
        mode="video", height=720, container="mkv", subtitle_langs=["en", "fr"]
    )
    opts = build_opts(choices, OUT)
    assert opts["writesubtitles"] is True
    assert opts["subtitleslangs"] == ["en", "fr"]
    assert opts["merge_output_format"] == "mkv"
    assert {"key": "FFmpegEmbedSubtitle", "already_have_subtitle": False} in opts[
        "postprocessors"
    ]


def test_auto_subtitles_are_opt_in():
    without = build_opts(Choices(mode="video", subtitle_langs=["en"]), OUT)
    assert without["writeautomaticsub"] is False
    with_auto = build_opts(
        Choices(mode="video", subtitle_langs=["en"], include_auto=True), OUT
    )
    assert with_auto["writeautomaticsub"] is True


def test_no_subtitle_keys_when_none_selected():
    opts = build_opts(Choices(mode="video", height=720), OUT)
    assert "writesubtitles" not in opts
    assert "postprocessors" not in opts


def test_audio_transcode_sets_codec_and_bitrate():
    opts = build_opts(Choices(mode="audio", audio_format="mp3", bitrate="320"), OUT)
    assert opts["format"] == "ba/b"
    assert opts["postprocessors"] == [
        {
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "320",
        }
    ]


def test_audio_best_skips_the_extract_postprocessor():
    opts = build_opts(Choices(mode="audio", audio_format="best"), OUT)
    assert opts["format"] == "ba/b"
    assert "postprocessors" not in opts


def test_common_opts_are_always_present():
    opts = build_opts(Choices(mode="video"), OUT)
    assert opts["noplaylist"] is True
    assert opts["retries"] == 3
    assert opts["fragment_retries"] == 10
    assert str(OUT) in opts["outtmpl"]


def test_hooks_are_wired_when_given():
    hook, pp_hook = (lambda d: None), (lambda d: None)
    opts = build_opts(Choices(mode="video"), OUT, hook=hook, pp_hook=pp_hook)
    assert opts["progress_hooks"] == [hook]
    assert opts["postprocessor_hooks"] == [pp_hook]


def test_default_container_prefers_mkv_with_subtitles():
    assert default_container(has_subtitles=True) == "mkv"
    assert default_container(has_subtitles=False) == "mp4"


@pytest.mark.parametrize(
    "choices",
    [
        Choices(mode="stream"),
        Choices(mode="video", container="avi"),
        Choices(mode="video", height=-1),
        Choices(mode="audio", audio_format="wav"),
        Choices(mode="audio", audio_format="mp3", bitrate="999"),
        Choices(mode="audio", audio_format="best", bitrate="320"),
    ],
)
def test_validate_rejects_bad_input(choices):
    with pytest.raises(InvalidChoices):
        validate(choices)


def test_validate_accepts_good_input():
    validate(Choices(mode="video", height=1080, container="mkv"))
    validate(Choices(mode="audio", audio_format="opus", bitrate="192"))
    validate(Choices(mode="audio", audio_format="best"))
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest tests/test_downloader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.downloader'`

- [ ] **Step 3: Write the minimal implementation**

Create `app/downloader.py`:

```python
"""Map user choices onto yt-dlp options and run the download."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yt_dlp

AUDIO_CODECS = ("mp3", "m4a", "opus")
AUDIO_FORMATS = ("best",) + AUDIO_CODECS
BITRATES = ("320", "256", "192", "128")
CONTAINERS = ("mp4", "mkv")

Hook = Callable[[dict[str, Any]], None]


class InvalidChoices(ValueError):
    """Raised when a request describes a download that cannot be built."""


class DownloadFailed(Exception):
    """Raised when yt-dlp finishes without producing a file."""


@dataclass
class Choices:
    """What the user asked for, straight from the UI."""

    mode: str  # "video" | "audio"
    height: int | None = None
    container: str = "mp4"
    subtitle_langs: list[str] = field(default_factory=list)
    include_auto: bool = False
    audio_format: str = "best"
    bitrate: str | None = None


def default_container(has_subtitles: bool) -> str:
    """MKV carries subtitle tracks that MP4 would mangle into mov_text."""
    return "mkv" if has_subtitles else "mp4"


def validate(choices: Choices) -> None:
    if choices.mode not in ("video", "audio"):
        raise InvalidChoices(f"Unknown mode: {choices.mode!r}")

    if choices.mode == "video":
        if choices.container not in CONTAINERS:
            raise InvalidChoices(f"Unknown container: {choices.container!r}")
        if choices.height is not None and choices.height <= 0:
            raise InvalidChoices("Height must be a positive number.")
        return

    if choices.audio_format not in AUDIO_FORMATS:
        raise InvalidChoices(f"Unknown audio format: {choices.audio_format!r}")
    if choices.audio_format == "best":
        if choices.bitrate is not None:
            raise InvalidChoices(
                "A bitrate cannot be set when keeping the original audio stream."
            )
        return
    if choices.bitrate is not None and choices.bitrate not in BITRATES:
        raise InvalidChoices(f"Unknown bitrate: {choices.bitrate!r}")


def build_opts(
    choices: Choices,
    outdir: Path,
    hook: Hook | None = None,
    pp_hook: Hook | None = None,
) -> dict[str, Any]:
    """Pure translation of choices into a yt-dlp options dict."""
    opts: dict[str, Any] = {
        "outtmpl": str(outdir / "%(title).150B.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "fragment_retries": 10,
        "windowsfilenames": True,
    }
    if hook is not None:
        opts["progress_hooks"] = [hook]
    if pp_hook is not None:
        opts["postprocessor_hooks"] = [pp_hook]

    if choices.mode == "video":
        height = choices.height
        opts["format"] = (
            f"bv*[height<={height}]+ba/b[height<={height}]" if height else "bv*+ba/b"
        )
        opts["merge_output_format"] = choices.container
        if choices.subtitle_langs:
            opts["writesubtitles"] = True
            opts["writeautomaticsub"] = choices.include_auto
            opts["subtitleslangs"] = list(choices.subtitle_langs)
            opts["postprocessors"] = [
                {"key": "FFmpegEmbedSubtitle", "already_have_subtitle": False}
            ]
        return opts

    opts["format"] = "ba/b"
    if choices.audio_format != "best":
        opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": choices.audio_format,
                "preferredquality": choices.bitrate or "192",
            }
        ]
    return opts


def run(
    url: str,
    choices: Choices,
    outdir: Path,
    hook: Hook | None = None,
    pp_hook: Hook | None = None,
) -> Path:
    """Download into `outdir` and return the finished file."""
    opts = build_opts(choices, outdir, hook, pp_hook)
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    files = [p for p in outdir.iterdir() if p.is_file()]
    if not files:
        raise DownloadFailed("yt-dlp produced no output file.")
    # Sidecar subtitle files may linger; the media file is the largest one.
    return max(files, key=lambda p: p.stat().st_size)
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `uv run pytest tests/test_downloader.py -v`
Expected: 17 passed

- [ ] **Step 5: Commit**

```bash
git add app/downloader.py tests/test_downloader.py
git commit -m "feat: build yt-dlp options from user choices"
```

---

### Task 4: Job registry with progress and TTL sweep

**Files:**
- Create: `app/jobs.py`, `tests/test_jobs.py`
- Test: `tests/test_jobs.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `app.jobs.JobState` with fields `id`, `tmpdir`, `status`, `stage`, `percent`, `speed`, `eta`, `error`, `filepath`, `filename`, `created_at`, `events`; methods `snapshot() -> dict`, `emit() -> None`, `fail(message: str) -> None`, `finish(path: Path) -> None`
  - `app.jobs.JobRegistry` with `create()`, `get(job_id)`, `remove(job_id)`, `sweep(now=None) -> list[str]`, `start_sweeper()`
  - `app.jobs.TTL_SECONDS`, `app.jobs.SWEEP_INTERVAL`

- [ ] **Step 1: Write the failing test**

Create `tests/test_jobs.py`:

```python
import threading

from app.jobs import TTL_SECONDS, JobRegistry


def test_create_returns_job_with_temp_dir():
    registry = JobRegistry()
    job = registry.create()
    assert job.tmpdir.is_dir()
    assert registry.get(job.id) is job
    registry.remove(job.id)


def test_remove_deletes_temp_dir_and_forgets_job():
    registry = JobRegistry()
    job = registry.create()
    tmpdir = job.tmpdir
    registry.remove(job.id)
    assert not tmpdir.exists()
    assert registry.get(job.id) is None


def test_get_unknown_id_returns_none():
    assert JobRegistry().get("nope") is None


def test_snapshot_exposes_progress_fields():
    registry = JobRegistry()
    job = registry.create()
    job.stage = "video"
    job.percent = 42.5
    snapshot = job.snapshot()
    assert snapshot["id"] == job.id
    assert snapshot["stage"] == "video"
    assert snapshot["percent"] == 42.5
    assert snapshot["status"] == "pending"
    registry.remove(job.id)


def test_emit_queues_a_snapshot():
    registry = JobRegistry()
    job = registry.create()
    job.stage = "merging"
    job.emit()
    assert job.events.get_nowait()["stage"] == "merging"
    registry.remove(job.id)


def test_fail_sets_status_and_emits():
    registry = JobRegistry()
    job = registry.create()
    job.fail("Video unavailable")
    assert job.status == "failed"
    assert job.error == "Video unavailable"
    assert job.events.get_nowait()["error"] == "Video unavailable"
    registry.remove(job.id)


def test_finish_records_file_and_completes_progress():
    registry = JobRegistry()
    job = registry.create()
    target = job.tmpdir / "Example Video.mkv"
    target.write_bytes(b"data")
    job.finish(target)
    assert job.status == "done"
    assert job.percent == 100.0
    assert job.filename == "Example Video.mkv"
    assert job.events.get_nowait()["status"] == "done"
    registry.remove(job.id)


def test_sweep_removes_jobs_past_the_ttl():
    registry = JobRegistry()
    old = registry.create()
    fresh = registry.create()
    old.created_at -= TTL_SECONDS + 1
    removed = registry.sweep()
    assert removed == [old.id]
    assert registry.get(old.id) is None
    assert registry.get(fresh.id) is fresh
    assert not old.tmpdir.exists()
    registry.remove(fresh.id)


def test_registry_is_thread_safe():
    registry = JobRegistry()
    jobs = []

    def make():
        jobs.append(registry.create())

    threads = [threading.Thread(target=make) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len({job.id for job in jobs}) == 20
    for job in jobs:
        registry.remove(job.id)
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest tests/test_jobs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.jobs'`

- [ ] **Step 3: Write the minimal implementation**

Create `app/jobs.py`:

```python
"""In-memory job registry: one download, one temp directory, one event queue."""

from __future__ import annotations

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
SWEEP_INTERVAL = 5 * 60


@dataclass
class JobState:
    """Everything the API knows about one download."""

    id: str
    tmpdir: Path
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

    def create(self) -> JobState:
        job_id = uuid.uuid4().hex
        job = JobState(id=job_id, tmpdir=Path(tempfile.mkdtemp(prefix="ytdl-")))
        with self._lock:
            self._jobs[job_id] = job
        return job

    def get(self, job_id: str) -> JobState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def remove(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.pop(job_id, None)
        if job is not None:
            shutil.rmtree(job.tmpdir, ignore_errors=True)

    def sweep(self, now: float | None = None) -> list[str]:
        """Drop jobs older than the TTL. Returns the ids removed."""
        cutoff = (now or time.time()) - TTL_SECONDS
        with self._lock:
            stale = [j.id for j in self._jobs.values() if j.created_at < cutoff]
        for job_id in stale:
            self.remove(job_id)
        return stale

    def start_sweeper(self) -> threading.Thread:
        def loop() -> None:
            while True:
                time.sleep(SWEEP_INTERVAL)
                self.sweep()

        thread = threading.Thread(target=loop, daemon=True, name="job-sweeper")
        thread.start()
        return thread


registry = JobRegistry()
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `uv run pytest tests/test_jobs.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add app/jobs.py tests/test_jobs.py
git commit -m "feat: add in-memory job registry with TTL cleanup"
```

---

### Task 5: Worker — run a download and report progress

**Files:**
- Create: `app/worker.py`, `tests/test_worker.py`
- Test: `tests/test_worker.py`

**Interfaces:**
- Consumes: `app.jobs.JobState`, `app.downloader.Choices`, `app.downloader.run`
- Produces:
  - `app.worker.make_hooks(job) -> tuple[Hook, Hook]`
  - `app.worker.run_job(job: JobState, url: str, choices: Choices) -> None`
  - `app.worker.start(job: JobState, url: str, choices: Choices) -> threading.Thread`

Progress hook payloads from yt-dlp carry `status`, `downloaded_bytes`, `total_bytes` (or `total_bytes_estimate`), `speed`, `eta`, and `info_dict`. The stage comes from the format being fetched: `vcodec == "none"` means the audio stream.

- [ ] **Step 1: Write the failing test**

Create `tests/test_worker.py`:

```python
from pathlib import Path

import pytest

from app.downloader import Choices
from app.jobs import JobRegistry
from app.worker import make_hooks, run_job


@pytest.fixture
def job():
    registry = JobRegistry()
    created = registry.create()
    yield created
    registry.remove(created.id)


def test_hook_reports_video_stage_and_percent(job):
    hook, _ = make_hooks(job)
    hook(
        {
            "status": "downloading",
            "downloaded_bytes": 50,
            "total_bytes": 200,
            "speed": 1_048_576,
            "eta": 12,
            "info_dict": {"vcodec": "avc1", "acodec": "none"},
        }
    )
    assert job.stage == "video"
    assert job.percent == 25.0
    assert job.speed == "1.0 MiB/s"
    assert job.eta == 12
    assert job.events.get_nowait()["percent"] == 25.0


def test_hook_reports_audio_stage(job):
    hook, _ = make_hooks(job)
    hook(
        {
            "status": "downloading",
            "downloaded_bytes": 1,
            "total_bytes_estimate": 4,
            "info_dict": {"vcodec": "none", "acodec": "opus"},
        }
    )
    assert job.stage == "audio"
    assert job.percent == 25.0


def test_hook_tolerates_unknown_total(job):
    hook, _ = make_hooks(job)
    hook({"status": "downloading", "downloaded_bytes": 10, "info_dict": {}})
    assert job.percent == 0.0
    assert job.speed is None


def test_postprocessor_hook_maps_stages(job):
    _, pp_hook = make_hooks(job)
    pp_hook({"status": "started", "postprocessor": "Merger"})
    assert job.stage == "merging"
    pp_hook({"status": "started", "postprocessor": "FFmpegEmbedSubtitle"})
    assert job.stage == "embedding"
    pp_hook({"status": "started", "postprocessor": "FFmpegExtractAudio"})
    assert job.stage == "audio"


def test_run_job_finishes_with_the_produced_file(job, monkeypatch):
    produced = job.tmpdir / "Example.mkv"
    produced.write_bytes(b"x" * 10)
    monkeypatch.setattr("app.worker.downloader.run", lambda *a, **k: produced)

    run_job(job, "https://youtu.be/x", Choices(mode="video"))

    assert job.status == "done"
    assert job.filepath == produced
    assert job.filename == "Example.mkv"


def test_run_job_records_failure_message(job, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("ERROR: Video unavailable")

    monkeypatch.setattr("app.worker.downloader.run", boom)

    run_job(job, "https://youtu.be/x", Choices(mode="video"))

    assert job.status == "failed"
    assert job.error == "Video unavailable"


def test_run_job_marks_running_before_downloading(job, monkeypatch):
    seen = {}

    def capture(*args, **kwargs):
        seen["status"] = job.status
        target = job.tmpdir / "a.mp4"
        target.write_bytes(b"x")
        return target

    monkeypatch.setattr("app.worker.downloader.run", capture)
    run_job(job, "https://youtu.be/x", Choices(mode="video"))
    assert seen["status"] == "running"
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest tests/test_worker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.worker'`

- [ ] **Step 3: Write the minimal implementation**

Create `app/worker.py`:

```python
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
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `uv run pytest tests/test_worker.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add app/worker.py tests/test_worker.py
git commit -m "feat: run downloads on worker threads with progress hooks"
```

---

### Task 6: API routes — probe, create job, SSE, file

**Files:**
- Modify: `app/main.py` (replace the Task 1 body, keeping `check_ffmpeg` and `/api/health`)
- Modify: `tests/test_api.py` (add route tests to the Task 1 tests)

**Interfaces:**
- Consumes: `app.probe.probe`, `app.probe.ProbeError`, `app.downloader.Choices`, `app.downloader.validate`, `app.downloader.InvalidChoices`, `app.jobs.registry`, `app.worker.start`
- Produces: routes `POST /api/probe`, `POST /api/jobs`, `GET /api/jobs/{id}`, `GET /api/jobs/{id}/events`, `GET /api/jobs/{id}/file`, `GET /` (static page)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_api.py`:

```python
import json

import pytest

from app.jobs import registry


@pytest.fixture(autouse=True)
def clean_registry():
    yield
    for job_id in list(registry._jobs):
        registry.remove(job_id)


def test_probe_returns_summary(monkeypatch):
    monkeypatch.setattr(
        "app.main.probe", lambda url: {"title": "Example", "video_qualities": []}
    )
    response = client.post("/api/probe", json={"url": "https://youtu.be/x"})
    assert response.status_code == 200
    assert response.json()["title"] == "Example"


def test_probe_surfaces_yt_dlp_message(monkeypatch):
    from app.probe import ProbeError

    def boom(url):
        raise ProbeError("Video unavailable")

    monkeypatch.setattr("app.main.probe", boom)
    response = client.post("/api/probe", json={"url": "https://youtu.be/x"})
    assert response.status_code == 400
    assert response.json()["detail"] == "Video unavailable"


def test_probe_rejects_non_http_url():
    response = client.post("/api/probe", json={"url": "file:///etc/passwd"})
    assert response.status_code == 400


def test_create_job_returns_id_and_starts_worker(monkeypatch):
    started = {}

    def fake_start(job, url, choices):
        started["url"] = url
        started["mode"] = choices.mode

    monkeypatch.setattr("app.main.worker.start", fake_start)
    response = client.post(
        "/api/jobs",
        json={"url": "https://youtu.be/x", "mode": "video", "height": 1080},
    )
    assert response.status_code == 200
    assert registry.get(response.json()["job_id"]) is not None
    assert started == {"url": "https://youtu.be/x", "mode": "video"}


def test_create_job_rejects_invalid_choices(monkeypatch):
    monkeypatch.setattr("app.main.worker.start", lambda *a: None)
    response = client.post(
        "/api/jobs",
        json={
            "url": "https://youtu.be/x",
            "mode": "audio",
            "audio_format": "best",
            "bitrate": "320",
        },
    )
    assert response.status_code == 400
    assert "bitrate" in response.json()["detail"].lower()


def test_job_status_returns_snapshot():
    job = registry.create()
    response = client.get(f"/api/jobs/{job.id}")
    assert response.status_code == 200
    assert response.json()["status"] == "pending"


def test_unknown_job_is_404():
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.get("/api/jobs/nope/file").status_code == 404


def test_file_before_completion_is_409():
    job = registry.create()
    assert client.get(f"/api/jobs/{job.id}/file").status_code == 409


def test_file_download_returns_the_media(monkeypatch):
    job = registry.create()
    target = job.tmpdir / "Example Video.mkv"
    target.write_bytes(b"media-bytes")
    job.finish(target)

    response = client.get(f"/api/jobs/{job.id}/file")
    assert response.status_code == 200
    assert response.content == b"media-bytes"
    assert "Example Video.mkv" in response.headers["content-disposition"]


def test_events_stream_emits_snapshots_until_done():
    job = registry.create()
    target = job.tmpdir / "a.mp4"
    target.write_bytes(b"x")
    job.stage = "video"
    job.emit()
    job.finish(target)

    with client.stream("GET", f"/api/jobs/{job.id}/events") as response:
        assert response.status_code == 200
        payloads = [
            json.loads(line[6:])
            for line in response.iter_lines()
            if line.startswith("data: ")
        ]

    assert payloads[0]["stage"] == "video"
    assert payloads[-1]["status"] == "done"


def test_index_page_is_served():
    response = client.get("/")
    assert response.status_code == 200
    assert "yt-dl" in response.text
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest tests/test_api.py -v`
Expected: FAIL — the new routes return 404 / `AttributeError: module 'app.main' has no attribute 'probe'`

- [ ] **Step 3: Write the implementation**

Replace `app/main.py` with:

```python
"""FastAPI application for the local YouTube downloader."""

from __future__ import annotations

import asyncio
import functools
import json
import queue
import shutil
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

app = FastAPI(title="yt-dl", docs_url=None, redoc_url=None)


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


def _require_http(url: str) -> None:
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Only http(s) URLs are supported.")


@app.on_event("startup")
def on_startup() -> None:
    check_ffmpeg()
    registry.start_sweeper()


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
        yield f"data: {json.dumps(job.snapshot())}\n\n"
        while True:
            getter = functools.partial(job.events.get, True, KEEPALIVE_SECONDS)
            try:
                payload = await loop.run_in_executor(None, getter)
            except queue.Empty:
                yield ": keepalive\n\n"
                continue
            yield f"data: {json.dumps(payload)}\n\n"
            if payload["status"] in ("done", "failed"):
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


def _job_or_404(job_id: str):
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job.")
    return job
```

Note: the SSE stream sends the current snapshot first so a client that connects after the job finished still receives a terminal event.

- [ ] **Step 4: Run the tests and make sure they pass**

The index test needs a file to exist. Create a placeholder `app/static/index.html` containing `<h1>yt-dl</h1>` — Task 7 replaces it.

Run: `uv run pytest -v`
Expected: all pass (test_index_page_is_served included)

- [ ] **Step 5: Commit**

```bash
git add app/main.py app/static/index.html tests/test_api.py
git commit -m "feat: add probe, job, SSE and file-download routes"
```

---

### Task 7: The UI

**Files:**
- Modify: `app/static/index.html` (replace the placeholder with the full page)

**Interfaces:**
- Consumes: `POST /api/probe`, `POST /api/jobs`, `GET /api/jobs/{id}/events`, `GET /api/jobs/{id}/file`
- Produces: nothing consumed by other tasks

**REQUIRED SUB-SKILL:** invoke `frontend-design:frontend-design` before writing the page.

Behavior the page must implement:

1. URL field plus a **Probe** button; Enter in the field probes too.
2. While probing, the button is disabled and shows a working state. Errors render in a dismissible banner using the `detail` string from the API.
3. On success, show thumbnail, title, uploader, and duration formatted `H:MM:SS` (or `M:SS` under an hour).
4. Two tabs: **Video** and **Audio**.
   - Video: a quality `<select>` built from `video_qualities` (label + approximate size in MB when known); a container `<select>` (MP4/MKV); a scrollable subtitle list of checkboxes with manual tracks first, then an "Auto-generated" group.
   - Selecting any subtitle switches the container to MKV once and shows a one-line note explaining why; the user may switch back.
   - Checking any auto-generated track sets `include_auto: true` in the request.
   - Audio: format `<select>` (Best / MP3 / M4A / Opus) and bitrate `<select>` (320/256/192/128). Choosing **Best** disables the bitrate select and the request omits `bitrate`.
5. **Download** posts to `/api/jobs`, then opens `new EventSource("/api/jobs/" + id + "/events")`.
6. Progress: a bar bound to `percent`, plus a line reading `stage · speed · ETA`. Stage labels: `queued → Queued`, `video → Downloading video`, `audio → Downloading audio`, `merging → Merging streams`, `embedding → Embedding subtitles`, `ready → Ready`.
7. On `status === "done"`: close the EventSource and set `window.location = "/api/jobs/" + id + "/file"` to trigger the browser save dialog.
8. On `status === "failed"`: close the EventSource and show `error` in the banner.

- [ ] **Step 1: Invoke the frontend-design skill**

Read it before writing markup so the page has a deliberate visual direction rather than default styling.

- [ ] **Step 2: Write `app/static/index.html`**

One self-contained file: markup, a `<style>` block, and a `<script>` block. No external requests of any kind — no CDN fonts, no CDN scripts. System font stack only.

- [ ] **Step 3: Verify the page loads**

Run: `uv run pytest tests/test_api.py::test_index_page_is_served -v`
Expected: PASS

- [ ] **Step 4: Start the server and check it by hand**

```bash
./run.sh
```

Open `http://127.0.0.1:8000`, probe a real video, confirm the quality and subtitle lists populate.

- [ ] **Step 5: Commit**

```bash
git add app/static/index.html
git commit -m "feat: add the downloader UI"
```

---

### Task 8: End-to-end verification and README

**Files:**
- Create: `tests/test_integration.py`, `README.md`

**Interfaces:**
- Consumes: everything above
- Produces: nothing

- [ ] **Step 1: Write the network test**

Create `tests/test_integration.py`:

```python
"""Real downloads. Run with: uv run pytest -m network"""

import pytest

from app.downloader import Choices, run
from app.jobs import JobRegistry

# "Big Buck Bunny" — Creative Commons, short, stable.
URL = "https://www.youtube.com/watch?v=aqz-KE-bpKQ"


@pytest.fixture
def job():
    registry = JobRegistry()
    created = registry.create()
    yield created
    registry.remove(created.id)


@pytest.mark.network
def test_downloads_audio_as_mp3(job):
    path = run(URL, Choices(mode="audio", audio_format="mp3", bitrate="128"), job.tmpdir)
    assert path.suffix == ".mp3"
    assert path.stat().st_size > 10_000


@pytest.mark.network
def test_downloads_video_at_capped_height(job):
    path = run(URL, Choices(mode="video", height=360), job.tmpdir)
    assert path.suffix in (".mp4", ".mkv")
    assert path.stat().st_size > 10_000
```

- [ ] **Step 2: Run the network tests**

Run: `uv run pytest -m network -v`
Expected: 3 passed (these two plus `test_probe_real_video`). If YouTube throttles, rerun — this is why they are excluded by default.

- [ ] **Step 3: Run the whole default suite**

Run: `uv run pytest -v`
Expected: all pass, network tests deselected.

- [ ] **Step 4: Write `README.md`**

```markdown
# yt-dl

A local YouTube downloader for personal use. Runs on `localhost`, downloads one
video at a time, and hands the file to your browser.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- ffmpeg (`sudo apt install ffmpeg`)

## Setup

    uv sync --extra dev

## Run

    ./run.sh

Then open http://127.0.0.1:8000

Set a different port with `PORT=9000 ./run.sh`.

## Use

1. Paste a YouTube URL and click **Probe**.
2. Pick **Video** (quality, container, subtitle tracks) or **Audio** (format,
   bitrate).
3. Click **Download**. Progress streams live; the file saves through your
   browser when it is ready.

Selecting subtitles switches the container to MKV, which handles subtitle
tracks better than MP4. You can switch back if you need MP4.

## Tests

    uv run pytest              # fast, offline
    uv run pytest -m network   # real downloads

## Notes

Nothing is stored after a download completes: each job works in its own temp
directory, which is deleted once the file has been sent (or after 30 minutes if
it never was). There is no history, no database, and no authentication — it is
built to run on your own machine, for your own use.
```

- [ ] **Step 5: Commit**

```bash
git add README.md tests/test_integration.py
git commit -m "test: add network integration tests and README"
```

---

## Self-Review

**Spec coverage:** probe (Task 2), opts mapping including MKV default and Best-audio rule (Task 3), job registry with TTL (Task 4), progress stages and error paths (Task 5), all routes with 404/409 handling (Task 6), UI including the disabled-bitrate rule (Task 7), test strategy and network marker (Task 8). The spec's `probe.py`/`downloader.py`/`jobs.py`/`main.py` layout is followed, with `worker.py` split out of `downloader.py` so the pure opts builder stays separate from thread and progress concerns.

**Placeholders:** none — every code step carries complete code. Task 7 specifies behavior rather than final markup because the frontend-design skill informs the visual layer; every function of the page is enumerated so nothing is left to taste.

**Type consistency:** `Choices` field names match between Tasks 3, 5, 6 and the JSON body in Task 6. `JobState.snapshot()` keys match what the SSE test and UI read. `downloader.run(url, choices, outdir, hook, pp_hook) -> Path` is called with that signature in Task 5 and Task 8.
