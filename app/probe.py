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
