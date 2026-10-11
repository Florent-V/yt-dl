"""Map user choices onto yt-dlp options and run the download."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yt_dlp

AUDIO_CODECS = ("mp3", "m4a", "opus")
AUDIO_FORMATS = ("best",) + AUDIO_CODECS
BITRATES = ("320", "256", "192", "128")
CONTAINERS = ("mp4", "mkv")
MAX_HEIGHT = 4320
MAX_SUBTITLES = 20
# Language codes go into yt-dlp format selectors and subtitle patterns:
# anything beyond plain codes (en, pt-BR, zh-Hans, live_chat) is refused.
LANG_RE = re.compile(r"[A-Za-z0-9_-]{1,35}")

# Only sites yt-dlp knows: the "generic" extractor would fetch any URL from
# the server, internal network included (SSRF). YTDL_ALLOW_GENERIC=1 lifts it.
ALLOWED_EXTRACTORS = (
    ["default"] if os.environ.get("YTDL_ALLOW_GENERIC") == "1" else ["default", "-generic"]
)

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
    audio_lang: str | None = None
    all_audio_langs: bool = False


def default_container(has_subtitles: bool) -> str:
    """MKV carries subtitle tracks that MP4 would mangle into mov_text."""
    return "mkv" if has_subtitles else "mp4"


def validate(choices: Choices) -> None:
    if choices.mode not in ("video", "audio"):
        raise InvalidChoices(f"Unknown mode: {choices.mode!r}")

    if choices.mode == "video":
        if choices.container not in CONTAINERS:
            raise InvalidChoices(f"Unknown container: {choices.container!r}")
        if choices.height is not None and not 0 < choices.height <= MAX_HEIGHT:
            raise InvalidChoices("Height must be a positive number.")
        if choices.audio_lang is not None and not LANG_RE.fullmatch(choices.audio_lang):
            raise InvalidChoices(f"Invalid audio language: {choices.audio_lang!r}")
        if len(choices.subtitle_langs) > MAX_SUBTITLES:
            raise InvalidChoices(f"At most {MAX_SUBTITLES} subtitle tracks.")
        for lang in choices.subtitle_langs:
            if not LANG_RE.fullmatch(lang):
                raise InvalidChoices(f"Invalid subtitle language: {lang!r}")
        if choices.audio_lang and choices.all_audio_langs:
            raise InvalidChoices(
                "Choose a single audio language or all of them, not both."
            )
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
        "allowed_extractors": ALLOWED_EXTRACTORS,
    }
    max_size = os.environ.get("MAX_FILESIZE")  # e.g. 2G, 500M
    if max_size:
        opts["max_filesize"] = yt_dlp.parse_bytes(max_size)
    if hook is not None:
        opts["progress_hooks"] = [hook]
    if pp_hook is not None:
        opts["postprocessor_hooks"] = [pp_hook]

    if choices.mode == "video":
        height = choices.height
        base_video = f"bv*[height<={height}]" if height else "bv*"
        base_best = f"b[height<={height}]" if height else "b"
        if choices.all_audio_langs:
            opts["format"] = f"{base_video}+mergeall[vcodec=none]/{base_best}"
            opts["allow_multiple_audio_streams"] = True
        elif choices.audio_lang:
            lang = choices.audio_lang
            opts["format"] = (
                f"{base_video}+ba[language={lang}]/{base_video}+ba/{base_best}"
            )
        else:
            opts["format"] = f"{base_video}+ba/{base_best}"
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
