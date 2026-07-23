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
