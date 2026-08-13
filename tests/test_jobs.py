from __future__ import annotations

import time
from uuid import uuid4

from backend.app.config import LocalSettings
from backend.app.jobs.manager import JobManager, now
from backend.app.models import JobMode, JobRecord, JobState


def wait_terminal(manager: JobManager, job_id, timeout=3):
    deadline = time.time() + timeout
    while time.time() < deadline:
        record = manager.get(job_id)
        if record.state in {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED}:
            return record
        time.sleep(.03)
    raise AssertionError("job did not finish")


def test_demo_job_success_and_result_persists(tmp_path, water_project):
    manager = JobManager(LocalSettings(jobs_dir=str(tmp_path), demo_calculations=True))
    record = manager.create(water_project, JobMode.DEMO)
    finished = wait_terminal(manager, record.id)
    assert finished.state == JobState.SUCCEEDED
    result = manager.result(record.id)
    assert result.demo and result.geometry_converged
    assert [a.id for a in result.optimized_atoms] == [a.id for a in water_project.atoms]
    assert (tmp_path / str(record.id) / "project.json").is_file()
    assert (tmp_path / str(record.id) / "result.json").is_file()
    manager.executor.shutdown()


def test_job_cancel(tmp_path, water_project):
    manager = JobManager(LocalSettings(jobs_dir=str(tmp_path), demo_calculations=True))
    record = manager.create(water_project, JobMode.DEMO)
    cancelled = manager.cancel(record.id)
    assert cancelled.state == JobState.CANCELLED
    assert wait_terminal(manager, record.id).state == JobState.CANCELLED
    manager.executor.shutdown()


def test_restart_marks_running_as_interrupted(tmp_path):
    job_id = uuid4()
    folder = tmp_path / str(job_id)
    folder.mkdir()
    running = JobRecord(id=job_id, state=JobState.RUNNING, mode=JobMode.ORCA, created_at=now(), updated_at=now())
    (folder / "job.json").write_text(running.model_dump_json(), encoding="utf-8")
    manager = JobManager(LocalSettings(jobs_dir=str(tmp_path)))
    recovered = manager.get(job_id)
    assert recovered.state == JobState.FAILED and recovered.error_code == "INTERRUPTED"
    manager.executor.shutdown()


def test_uuid_job_paths_cannot_traverse(tmp_path):
    manager = JobManager(LocalSettings(jobs_dir=str(tmp_path)))
    path = manager._job_dir(uuid4())
    assert path.parent == tmp_path.resolve()
    manager.executor.shutdown()
