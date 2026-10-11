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

MULTI_AUDIO_INFO = {
    **INFO,
    "formats": INFO["formats"]
    + [
        {
            "height": None,
            "vcodec": "none",
            "acodec": "opus",
            "language": "en",
            "language_preference": 10,
        },
        {
            "height": None,
            "vcodec": "none",
            "acodec": "opus",
            "language": "es",
            "language_preference": -1,
        },
    ],
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
    assert result["audio_tracks"] == []


def test_audio_tracks_empty_when_video_has_a_single_language():
    assert summarize(INFO)["audio_tracks"] == []


def test_audio_tracks_lists_distinct_languages_original_first():
    tracks = summarize(MULTI_AUDIO_INFO)["audio_tracks"]
    assert [t["lang"] for t in tracks] == ["en", "es"]


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
