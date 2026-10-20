from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import InvalidStateError
from app.models import Job, VideoProject
from app.models.enums import JobKind, JobStatus, ProjectStatus, VideoFormat
from app.services import jobs
from app.services.media import ffmpeg
from app.services.projects import create_project, retry_project
from app.services.settings_service import get_app_settings
from app.services.workflow import can_transition, fail_project, retry_target, transition
from app.workers.handlers import run_job


def _project(db, user, status=ProjectStatus.PENDING) -> VideoProject:
    p = create_project(db, user.id, get_app_settings(db, user.id), script=None, video_format=VideoFormat.SHORT)
    p.status = status
    db.commit()
    return p


def test_state_machine_happy_path_and_history(db, user):
    p = _project(db, user)
    for s in (ProjectStatus.SCRIPTING, ProjectStatus.GENERATING_MEDIA, ProjectStatus.RENDERING,
              ProjectStatus.VALIDATING, ProjectStatus.READY, ProjectStatus.UPLOADING, ProjectStatus.SCHEDULED,
              ProjectStatus.PUBLISHED):
        transition(p, s)
    assert [h["to"] for h in p.status_history][-1] == "PUBLISHED"
    assert len(p.status_history) == 8


def test_invalid_transitions_rejected(db, user):
    p = _project(db, user)
    with pytest.raises(InvalidStateError):
        transition(p, ProjectStatus.PUBLISHED)
    assert not can_transition(ProjectStatus.PUBLISHED, ProjectStatus.FAILED)
    assert can_transition(ProjectStatus.RENDERING, ProjectStatus.CANCELLED)


def test_retry_target_resumes_from_failed_step(db, user):
    p = _project(db, user)
    transition(p, ProjectStatus.SCRIPTING)
    fail_project(p, "boom")
    assert p.status == ProjectStatus.FAILED and p.error.startswith("[SCRIPTING]")
    assert retry_target(p) == ProjectStatus.SCRIPTING
    p2 = _project(db, user, ProjectStatus.READY)
    p2.script_id = None
    transition(p2, ProjectStatus.UPLOADING)
    fail_project(p2, "upload exploded")
    assert retry_target(p2) == ProjectStatus.READY
    retry_project(db, p2)
    assert p2.status == ProjectStatus.READY


def test_queue_claim_fail_retry_cancel(db, user):
    j1 = jobs.enqueue(db, user.id, JobKind.RECOMMEND, {})
    j2 = jobs.enqueue(db, user.id, JobKind.RECOMMEND, {}, run_after=datetime.now(UTC) + timedelta(hours=1))
    db.commit()
    claimed = jobs.claim_next(db, "w1")
    assert claimed.id == j1.id and claimed.status == JobStatus.RUNNING and claimed.attempts == 1
    assert jobs.claim_next(db, "w1") is None  # j2 is not due yet
    assert jobs.fail(claimed, "transient", retryable=True)
    assert claimed.status == JobStatus.QUEUED and claimed.run_after > datetime.now(UTC)
    claimed.attempts = claimed.max_attempts
    assert not jobs.fail(claimed, "again", retryable=True)
    assert claimed.status == JobStatus.FAILED
    jobs.retry(db, claimed.id, user.id)
    assert claimed.status == JobStatus.QUEUED
    jobs.request_cancel(db, j2.id, user.id)
    assert db.get(Job, j2.id).status == JobStatus.CANCELLED
    with pytest.raises(InvalidStateError):
        jobs.request_cancel(db, j2.id, user.id)


def test_dedupe_key_prevents_duplicate_jobs(db, user):
    a = jobs.enqueue(db, user.id, JobKind.ANALYTICS, {}, dedupe_key="analytics:x")
    b = jobs.enqueue(db, user.id, JobKind.ANALYTICS, {}, dedupe_key="analytics:x")
    assert a.id == b.id


def test_recover_stale_running_jobs(db, user):
    j = jobs.enqueue(db, user.id, JobKind.RECOMMEND, {})
    db.commit()
    jobs.claim_next(db, "dead-worker")
    j.locked_at = datetime.now(UTC) - timedelta(hours=2)
    db.commit()
    assert jobs.recover_stale(db) == 1
    assert j.status == JobStatus.QUEUED


@pytest.mark.skipif(not ffmpeg.ffmpeg_available(), reason="FFmpeg not installed")
def test_generate_and_render_job_end_to_end(db, user, fast_providers):
    p = _project(db, user)
    job = jobs.enqueue(db, user.id, JobKind.GENERATE_CONTENT, {
        "mode": "script", "auto_render": True,
        "request": {"topic": "Shapes everywhere", "theme": "shapes", "language": "en", "video_format": "short"}},
        project_id=p.id)
    db.commit()
    job = run_job(db, jobs.claim_next(db, "t"), providers=fast_providers)
    assert job.status == JobStatus.SUCCEEDED, job.error
    assert [s["step"] for s in job.steps] == ["SCRIPTING", "GENERATING_MEDIA", "RENDERING", "VALIDATING",
                                              "PUBLISH_POLICY"]
    assert all(s["status"] == "succeeded" for s in job.steps)
    db.refresh(p)
    assert p.status == ProjectStatus.READY and p.validation["passed"]
    assert job.result["is_fallback"] is True


def test_cancel_running_job_marks_project_cancelled(db, user, fast_providers):
    p = _project(db, user)
    job = jobs.enqueue(db, user.id, JobKind.GENERATE_CONTENT, {
        "mode": "script", "auto_render": True,
        "request": {"topic": "Moon", "theme": "bedtime", "language": "hi", "video_format": "short"}}, project_id=p.id)
    db.commit()
    job = jobs.claim_next(db, "t")
    job.cancel_requested = True
    db.commit()
    job = run_job(db, job, providers=fast_providers)
    assert job.status == JobStatus.CANCELLED
    db.refresh(p)
    assert p.status == ProjectStatus.CANCELLED


def test_permanent_failure_marks_project_failed(db, user):
    p = _project(db, user)
    job = jobs.enqueue(db, user.id, JobKind.RENDER, {"project_id": p.id}, project_id=p.id)
    db.commit()
    job = run_job(db, jobs.claim_next(db, "t"))
    assert job.status == JobStatus.FAILED and "no script" in job.error
    db.refresh(p)
    assert p.status == ProjectStatus.FAILED
