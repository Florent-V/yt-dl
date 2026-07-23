"""Real downloads. Run with: uv run pytest -m network"""

import subprocess

import pytest

from app.downloader import Choices, run
from app.jobs import JobRegistry

# "Big Buck Bunny" — Creative Commons, Blender Foundation. No subtitle tracks.
URL = "https://www.youtube.com/watch?v=aqz-KE-bpKQ"
# A talk that publishes real (non-auto) subtitles, for the embedding path.
SUBTITLED_URL = "https://www.youtube.com/watch?v=8S0FDjFBj8o"


@pytest.fixture
def job():
    registry = JobRegistry()
    created = registry.create()
    yield created
    registry.remove(created.id)


def streams(path):
    """(codec_type, language) for every stream in a media file."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "stream=codec_type:stream_tags=language",
            "-of", "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.split(",") for line in result.stdout.strip().splitlines()]


@pytest.mark.network
def test_downloads_audio_as_mp3(job):
    path = run(URL, Choices(mode="audio", audio_format="mp3", bitrate="128"), job.tmpdir)
    assert path.suffix == ".mp3"
    assert path.stat().st_size > 10_000


@pytest.mark.network
def test_downloads_video_at_capped_height(job):
    path = run(URL, Choices(mode="video", height=144), job.tmpdir)
    assert path.suffix in (".mp4", ".mkv")
    assert path.stat().st_size > 10_000
    kinds = [kind for kind, *_ in streams(path)]
    assert "video" in kinds and "audio" in kinds


@pytest.mark.network
def test_embeds_selected_subtitle_tracks(job):
    choices = Choices(
        mode="video", height=144, container="mkv", subtitle_langs=["en", "fr"]
    )
    path = run(SUBTITLED_URL, choices, job.tmpdir)

    languages = [row[-1] for row in streams(path) if row[0] == "subtitle"]
    assert "eng" in languages
    assert "fra" in languages
