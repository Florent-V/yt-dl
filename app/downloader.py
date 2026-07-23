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
