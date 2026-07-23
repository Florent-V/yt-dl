import json

import pytest
from fastapi.testclient import TestClient

from app.jobs import registry
from app.main import app, check_ffmpeg

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_registry():
    yield
    for job_id in list(registry._jobs):
        registry.remove(job_id)


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


def test_file_download_returns_the_media():
    job = registry.create()
    target = job.tmpdir / "Example Video.mkv"
    target.write_bytes(b"media-bytes")
    job.finish(target)

    response = client.get(f"/api/jobs/{job.id}/file")
    assert response.status_code == 200
    assert response.content == b"media-bytes"
    # Starlette percent-encodes the name per RFC 5987; browsers decode it back.
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert "Example%20Video.mkv" in disposition


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
