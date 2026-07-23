from fastapi.testclient import TestClient

from app.main import app, check_ffmpeg

client = TestClient(app)


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
