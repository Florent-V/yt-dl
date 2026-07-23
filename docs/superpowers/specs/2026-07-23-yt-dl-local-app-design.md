# yt-dl — Local YouTube Downloader

**Date:** 2026-07-23
**Status:** Approved

## Purpose

A local web app for downloading YouTube videos for personal use. Runs on
`localhost`, single user, no authentication. The user pastes a URL, picks a
format, and the file lands in their browser's Downloads folder.

Scope decisions made during brainstorming:

- Delivery: browser download (server keeps nothing permanently)
- Scope: one video at a time, no playlists or batch queue
- Subtitles: embedded as soft tracks in the container
- Stack: Python + FastAPI + vanilla JS, no build step

## Architecture

One FastAPI process serving both the API and a single static HTML page.
`yt-dlp` is used as a Python library, in-process — not as a subprocess. This
avoids parsing stdout and gives structured access to format lists and progress
callbacks.

```
browser (static/index.html)      FastAPI (localhost:8000)
  |                                |
  |-- POST /api/probe {url} ------->  yt_dlp.extract_info(download=False)
  |<-- title, thumb, formats, subs -|
  |                                 |
  |-- POST /api/jobs {url,choices} ->  create job, spawn worker thread
  |<-- {job_id} --------------------|
  |                                 |
  |-- GET /api/jobs/{id}/events ---->  SSE: stage, percent, speed, eta
  |<-- event: done -----------------|
  |                                 |
  |-- GET /api/jobs/{id}/file ------>  FileResponse; temp dir deleted after send
```

State lives in an in-memory dict. There is no database and no persistence
across restarts — appropriate for a single-user local tool.

Each job downloads into its own `tempfile.mkdtemp()` directory. The directory
is removed once the file has been sent, or by a background sweeper after a TTL
of 30 minutes, whichever comes first. Nothing accumulates on disk.

Downloads run in a `threading.Thread` per job because `yt-dlp` is blocking.
This keeps the FastAPI event loop responsive. Given the single-video scope,
no queue or worker pool is needed.

`ffmpeg` is a hard requirement — it merges separate video and audio streams,
embeds subtitles, and transcodes audio. Its presence is checked at startup and
the server refuses to start with a clear message if it is missing.

## File Layout

```
yt-dl/
  pyproject.toml          # uv project: fastapi, uvicorn, yt-dlp, pytest
  run.sh                  # uv run uvicorn app.main:app --port 8000
  app/
    main.py               # FastAPI app, routes, startup checks
    probe.py              # extract_info -> UI-shaped format/subtitle summary
    downloader.py         # opts builder (pure) + download runner
    jobs.py               # JobState, registry, TTL sweeper
    static/index.html     # markup + inline CSS + inline JS
  tests/
    fixtures/probe_sample.json
    test_probe.py
    test_downloader.py
    test_jobs.py
    test_api.py
    test_integration.py     # @pytest.mark.network, deselected by default
  docs/superpowers/specs/
```

Each module has one responsibility and can be understood and tested on its own.
`downloader.build_opts()` is a pure function from user choices to a `yt-dlp`
options dict, which makes the trickiest logic in the app directly testable
without network access.

## Components

### `probe.py`

Calls `yt_dlp.YoutubeDL(...).extract_info(url, download=False)` and reduces the
large raw info dict to what the UI needs:

```python
{
  "title": str,
  "uploader": str,
  "duration": int,          # seconds
  "thumbnail": str,         # URL
  "video_qualities": [      # descending, deduped by height
    {"height": 1080, "label": "1080p", "fps": 60, "filesize_approx": 84512000}
  ],
  "subtitles": [
    {"lang": "en", "name": "English", "auto": false}
  ]
}
```

Heights are deduplicated and sorted descending. Only heights actually present
in the format list are offered. Auto-generated (ASR) subtitle tracks come from
`automatic_captions` and are flagged `auto: true` so the UI can group them
separately.

### `downloader.py`

`build_opts(choices, outdir) -> dict` maps user choices to `yt-dlp` options:

**Video mode**

| Choice | Option |
|---|---|
| height H | `format: "bv*[height<=H]+ba/b[height<=H]"` |
| container | `merge_output_format: "mp4"` or `"mkv"` |
| subtitle langs | `writesubtitles: True`, `subtitleslangs: [...]` |
| auto subs included | `writeautomaticsub: True` |
| embed | postprocessor `FFmpegEmbedSubtitle` |

**Audio mode**

| Choice | Option |
|---|---|
| always | `format: "ba/b"` |
| mp3/m4a/opus | postprocessor `FFmpegExtractAudio` with `preferredcodec` |
| bitrate | `preferredquality: "320" \| "256" \| "192" \| "128"` |
| "Best (no re-encode)" | no `FFmpegExtractAudio`; native stream kept as-is |

Common options: `outtmpl` pointing into the job's temp directory,
`retries: 3`, `fragment_retries: 10`, `noplaylist: True`, `quiet: True`,
`progress_hooks: [hook]`.

`noplaylist: True` matters — pasting a URL that carries a `list=` parameter
must download the single video, not the whole playlist.

**Container defaulting:** when the user selects one or more subtitle tracks,
the container defaults to MKV, because MP4 requires converting subtitles to
`mov_text`, which several players handle poorly. The user can override back to
MP4 in the UI; the UI explains why the default changed.

### `jobs.py`

```python
@dataclass
class JobState:
    id: str
    status: Literal["pending","running","done","failed"]
    stage: str                # probing|video|audio|merging|embedding|ready
    percent: float
    speed: str | None
    eta: int | None
    error: str | None
    filepath: Path | None
    tmpdir: Path
    created_at: float
    events: queue.Queue       # progress messages for the SSE stream
```

The registry is a dict guarded by a `threading.Lock`. A daemon sweeper thread
runs every 5 minutes and removes jobs older than 30 minutes along with their
temp directories.

The `yt-dlp` progress hook pushes dicts onto `events`. The SSE endpoint drains
that queue and writes them to the client. Stage names are derived from the
hook payload: `downloading` with a video-only format is `video`, with an
audio-only format is `audio`, and the postprocessor hook supplies `merging`
and `embedding`.

### `static/index.html`

One page, no framework, no build step:

1. URL input → **Probe** button
2. Result card: thumbnail, title, uploader, duration
3. Two tabs — **Video** and **Audio**
   - Video: quality select, container select, subtitle language multiselect,
     "include auto-generated" checkbox
   - Audio: format select, bitrate select. Selecting
     **Best (no re-encode)** as the format disables the bitrate select, since
     the native stream is copied untouched; the API rejects a request that
     sends a bitrate alongside it.
4. **Download** button → progress bar fed by `EventSource`
5. On `done`, the page navigates to `/api/jobs/{id}/file`, which triggers the
   browser save dialog

## Data Flow

1. User pastes URL, clicks Probe.
2. `POST /api/probe` returns the summary; the UI populates the selects.
3. User picks a mode and options, clicks Download.
4. `POST /api/jobs` validates the request, creates a `JobState`, starts a
   worker thread, returns `{job_id}`.
5. The UI opens `EventSource("/api/jobs/{id}/events")`.
6. The worker runs `yt-dlp`; hooks push progress; SSE relays it.
7. On success the worker records `filepath` and status `done`; SSE emits a
   `done` event and closes.
8. The UI navigates to the file endpoint. `FileResponse` sends the file with a
   `Content-Disposition` filename sanitized from the video title.
9. A `BackgroundTask` on the response removes the temp directory.

## Error Handling

| Failure | Behavior |
|---|---|
| Malformed URL | `400` before any network call |
| Private / removed / geo-blocked / age-gated | `yt-dlp`'s own message returned verbatim — it is the most useful diagnostic |
| ffmpeg missing | Startup check fails with an explicit message; server does not start |
| Download fails mid-run | Job status `failed`, SSE `error` event, temp dir removed |
| Transient network errors | `yt-dlp` retries: 3 whole-file, 10 per fragment |
| File requested for a job that is not `done` | `409` |
| Unknown job id | `404` |
| Disk full | Error surfaced through the standard job-failure path |

## Testing

Written test-first, per the project's TDD practice.

- **`test_downloader.py`** — table-driven tests over `build_opts()`: each
  combination of mode, quality, container, and subtitle selection maps to the
  expected options dict. Covers the MKV-defaulting rule and the
  "Best (no re-encode)" path that omits the extract-audio postprocessor. No
  network, no ffmpeg.
- **`test_probe.py`** — runs the shaping function against a saved
  `extract_info` fixture: height dedup and ordering, ASR tracks flagged, videos
  with no subtitles at all, audio-only sources.
- **`test_jobs.py`** — registry lifecycle, TTL sweep removes old jobs and their
  directories, concurrent access under the lock.
- **`test_api.py`** — FastAPI `TestClient` with the downloader mocked: route
  validation, error status codes, SSE framing, the `409`/`404` cases.
- **`test_integration.py`** — one real download of a short Creative Commons
  video, marked `@pytest.mark.network` and deselected by default so the normal
  suite stays fast and offline.

## Out of Scope

Deliberately excluded to keep the app small:

- Playlists, channels, batch queues
- Download history or a persistent library
- Authentication, multi-user support, remote hosting
- Non-YouTube sites (`yt-dlp` supports many; the UI targets YouTube only)
- Login-gated or member-only videos (no cookie handling)
- Burned-in ("hardcoded") subtitles — soft tracks only

## Notes

This is a personal-use tool for local content archiving. It downloads only
what the user explicitly requests, one video at a time, and stores nothing
after delivery.
