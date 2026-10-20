"""PostgreSQL-backed job queue (SELECT … FOR UPDATE SKIP LOCKED). No Redis/Celery needed for a single-channel
MVP: jobs are durable, observable from the API, retryable and cancellable."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import InvalidStateError, NotFoundError
from app.models import Job
from app.models.enums import JobKind, JobStatus

STALE_AFTER = timedelta(minutes=30)


def now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def enqueue(db: Session, owner_id: int, kind: JobKind, payload: dict | None = None, *, project_id: int | None = None,
            dedupe_key: str | None = None, run_after: datetime | None = None, max_attempts: int | None = None) -> Job:
    if dedupe_key:
        existing = db.scalar(select(Job).where(Job.dedupe_key == dedupe_key))
        if existing:
            return existing
    job = Job(owner_id=owner_id, kind=kind, payload=payload or {}, project_id=project_id, dedupe_key=dedupe_key,
              run_after=run_after or now(), max_attempts=max_attempts or get_settings().job_max_attempts)
    db.add(job)
    db.flush()
    return job


def claim_next(db: Session, worker_id: str, kinds: list[JobKind] | None = None) -> Job | None:
    stmt = (select(Job).where(Job.status == JobStatus.QUEUED, Job.run_after <= now(),
                              Job.cancel_requested.is_(False))
            .order_by(Job.run_after, Job.id).limit(1).with_for_update(skip_locked=True))
    if kinds:
        stmt = stmt.where(Job.kind.in_(kinds))
    job = db.scalar(stmt)
    if job is None:
        return None
    job.status = JobStatus.RUNNING
    job.locked_by = worker_id
    job.locked_at = now()
    job.started_at = job.started_at or now()
    job.attempts += 1
    job.error = None
    db.commit()
    return job


def step_start(job: Job, step: str) -> None:
    job.step = step
    job.steps = [*job.steps, {"step": step, "status": "running", "started_at": now().isoformat(),
                              "attempt": job.attempts}]


def step_finish(job: Job, status: str = "succeeded", error: str | None = None, **extra) -> None:
    steps = list(job.steps)
    if steps and steps[-1]["status"] == "running":
        steps[-1] = {**steps[-1], "status": status, "finished_at": now().isoformat(),
                     **({"error": error} if error else {}), **extra}
    job.steps = steps


def succeed(job: Job, result: dict | None = None) -> None:
    job.status = JobStatus.SUCCEEDED
    job.result = result or {}
    job.progress = 1.0
    job.finished_at = now()
    job.locked_by = None


def fail(job: Job, error: str, *, retryable: bool, retry_at: datetime | None = None) -> bool:
    """Mark failure. Returns True if the job was re-queued for another attempt."""
    job.error = error[:4000]
    job.locked_by = None
    if retryable and job.attempts < job.max_attempts:
        job.status = JobStatus.QUEUED
        job.run_after = retry_at or (now() + timedelta(seconds=min(30 * 2 ** (job.attempts - 1), 3600)))
        return True
    job.status = JobStatus.FAILED
    job.finished_at = now()
    return False


def mark_cancelled(job: Job) -> None:
    job.status = JobStatus.CANCELLED
    job.finished_at = now()
    job.locked_by = None


def request_cancel(db: Session, job_id: int, owner_id: int) -> Job:
    job = db.get(Job, job_id)
    if not job or job.owner_id != owner_id:
        raise NotFoundError("Job not found")
    if job.status in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED):
        raise InvalidStateError(f"Job is already {job.status.value}")
    job.cancel_requested = True
    if job.status == JobStatus.QUEUED:
        mark_cancelled(job)
    db.flush()
    return job


def is_cancel_requested(db: Session, job_id: int) -> bool:
    return bool(db.scalar(select(Job.cancel_requested).where(Job.id == job_id)))


def recover_stale(db: Session) -> int:
    """Requeue jobs whose worker died mid-run."""
    cutoff = now() - STALE_AFTER
    stale = list(db.scalars(select(Job).where(Job.status == JobStatus.RUNNING,
                                              or_(Job.locked_at.is_(None), Job.locked_at < cutoff))))
    for job in stale:
        fail(job, "Worker stopped responding; re-queued", retryable=True, retry_at=now())
    db.flush()
    return len(stale)


def retry(db: Session, job_id: int, owner_id: int) -> Job:
    job = db.get(Job, job_id)
    if not job or job.owner_id != owner_id:
        raise NotFoundError("Job not found")
    if job.status not in (JobStatus.FAILED, JobStatus.CANCELLED):
        raise InvalidStateError("Only failed or cancelled jobs can be retried")
    job.status = JobStatus.QUEUED
    job.cancel_requested = False
    job.run_after = now()
    job.max_attempts = job.attempts + get_settings().job_max_attempts
    job.finished_at = None
    db.flush()
    return job
