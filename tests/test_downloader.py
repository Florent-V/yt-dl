from pathlib import Path

import pytest

from app.downloader import (
    Choices,
    InvalidChoices,
    build_opts,
    cookie_options,
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


def test_all_audio_langs_uses_mergeall_and_sets_multistream_flag():
    opts = build_opts(Choices(mode="video", height=1080, all_audio_langs=True), OUT)
    assert opts["format"] == "bv*[height<=1080]+mergeall[vcodec=none]/b[height<=1080]"
    assert opts["allow_multiple_audio_streams"] is True


def test_single_audio_lang_filters_then_falls_back():
    opts = build_opts(Choices(mode="video", height=720, audio_lang="fr"), OUT)
    assert opts["format"] == (
        "bv*[height<=720]+ba[language=fr]/bv*[height<=720]+ba/b[height<=720]"
    )
    assert "allow_multiple_audio_streams" not in opts


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
        Choices(mode="video", audio_lang="en", all_audio_langs=True),
    ],
)
def test_validate_rejects_bad_input(choices):
    with pytest.raises(InvalidChoices):
        validate(choices)


def test_validate_accepts_good_input():
    validate(Choices(mode="video", height=1080, container="mkv"))
    validate(Choices(mode="audio", audio_format="opus", bitrate="192"))
    validate(Choices(mode="audio", audio_format="best"))


@pytest.mark.parametrize("field,value", [
    ("audio_lang", "en]+bv*[height>0"),
    ("audio_lang", "fr,de"),
    ("height", 100000),
    ("subtitle_langs", ["en", "all,-live_chat"]),
    ("subtitle_langs", [f"l{i}" for i in range(50)]),
])
def test_validate_rejects_injected_values(field, value):
    with pytest.raises(InvalidChoices):
        validate(Choices(mode="video", **{field: value}))


def test_generic_extractor_is_disabled():
    opts = build_opts(Choices(mode="audio"), Path("/tmp/x"))
    assert "-generic" in opts["allowed_extractors"]


def test_no_cookies_by_default(monkeypatch):
    monkeypatch.delenv("YTDL_COOKIES_FILE", raising=False)
    with cookie_options() as opts:
        assert opts == {}


def test_cookies_are_a_private_copy_removed_afterwards(monkeypatch, tmp_path):
    source = tmp_path / "cookies.txt"
    source.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setenv("YTDL_COOKIES_FILE", str(source))
    with cookie_options() as opts:
        copy = Path(opts["cookiefile"])
        assert copy != source
        assert copy.read_text() == source.read_text()
        assert copy.stat().st_mode & 0o777 == 0o600
        copy.write_text("rewritten by yt-dlp")
    assert not copy.exists()
    assert source.read_text() == "# Netscape HTTP Cookie File\n"


def test_missing_cookie_file_runs_without_cookies(monkeypatch, tmp_path):
    monkeypatch.setenv("YTDL_COOKIES_FILE", str(tmp_path / "absent.txt"))
    with cookie_options() as opts:
        assert opts == {}
