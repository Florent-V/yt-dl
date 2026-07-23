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
