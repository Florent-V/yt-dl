import threading

from app.jobs import TTL_SECONDS, JobRegistry


def test_create_returns_job_with_temp_dir():
    registry = JobRegistry()
    job = registry.create()
    assert job.tmpdir.is_dir()
    assert registry.get(job.id) is job
    registry.remove(job.id)


def test_remove_deletes_temp_dir_and_forgets_job():
    registry = JobRegistry()
    job = registry.create()
    tmpdir = job.tmpdir
    registry.remove(job.id)
    assert not tmpdir.exists()
    assert registry.get(job.id) is None


def test_get_unknown_id_returns_none():
    assert JobRegistry().get("nope") is None


def test_snapshot_exposes_progress_fields():
    registry = JobRegistry()
    job = registry.create()
    job.stage = "video"
    job.percent = 42.5
    snapshot = job.snapshot()
    assert snapshot["id"] == job.id
    assert snapshot["stage"] == "video"
    assert snapshot["percent"] == 42.5
    assert snapshot["status"] == "pending"
    registry.remove(job.id)


def test_emit_queues_a_snapshot():
    registry = JobRegistry()
    job = registry.create()
    job.stage = "merging"
    job.emit()
    assert job.events.get_nowait()["stage"] == "merging"
    registry.remove(job.id)


def test_fail_sets_status_and_emits():
    registry = JobRegistry()
    job = registry.create()
    job.fail("Video unavailable")
    assert job.status == "failed"
    assert job.error == "Video unavailable"
    assert job.events.get_nowait()["error"] == "Video unavailable"
    registry.remove(job.id)


def test_finish_records_file_and_completes_progress():
    registry = JobRegistry()
    job = registry.create()
    target = job.tmpdir / "Example Video.mkv"
    target.write_bytes(b"data")
    job.finish(target)
    assert job.status == "done"
    assert job.percent == 100.0
    assert job.filename == "Example Video.mkv"
    assert job.events.get_nowait()["status"] == "done"
    registry.remove(job.id)


def test_sweep_removes_jobs_past_the_ttl():
    registry = JobRegistry()
    old = registry.create()
    fresh = registry.create()
    old.created_at -= TTL_SECONDS + 1
    removed = registry.sweep()
    assert removed == [old.id]
    assert registry.get(old.id) is None
    assert registry.get(fresh.id) is fresh
    assert not old.tmpdir.exists()
    registry.remove(fresh.id)


def test_registry_is_thread_safe():
    registry = JobRegistry()
    jobs = []

    def make():
        jobs.append(registry.create())

    threads = [threading.Thread(target=make) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len({job.id for job in jobs}) == 20
    for job in jobs:
        registry.remove(job.id)
