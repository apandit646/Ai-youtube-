import asyncio
import json

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser, Paging, owned
from app.db.session import SessionLocal
from app.models import Job
from app.models.enums import JobKind, JobStatus
from app.schemas.api import JobOut, Page
from app.services import jobs
from app.services.audit import audit

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=Page[JobOut])
def list_jobs(db: DB, user: CurrentUser, paging: Paging, status: JobStatus | None = None,
              kind: JobKind | None = None, project_id: int | None = None) -> dict:
    base = select(Job).where(Job.owner_id == user.id)
    if status:
        base = base.where(Job.status == status)
    if kind:
        base = base.where(Job.kind == kind)
    if project_id:
        base = base.where(Job.project_id == project_id)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    items = db.scalars(base.order_by(Job.id.desc()).offset(paging.offset).limit(paging.page_size))
    return {"items": list(items), "total": total, "page": paging.page, "page_size": paging.page_size}


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: DB, user: CurrentUser) -> Job:
    return owned(db.get(Job, job_id), user, "Job")


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel(job_id: int, db: DB, user: CurrentUser) -> Job:
    job = jobs.request_cancel(db, job_id, user.id)
    audit(db, user.id, "job.cancel_requested", "job", job_id)
    db.commit()
    return job


@router.post("/{job_id}/retry", response_model=JobOut)
def retry(job_id: int, db: DB, user: CurrentUser) -> Job:
    job = jobs.retry(db, job_id, user.id)
    audit(db, user.id, "job.retry", "job", job_id)
    db.commit()
    return job


@router.get("/{job_id}/events")
async def events(job_id: int, db: DB, user: CurrentUser, timeout: int = Query(600, ge=5, le=3600)):
    """Server-sent events with job status until it reaches a terminal state."""
    owned(db.get(Job, job_id), user, "Job")

    def fetch() -> dict:
        with SessionLocal() as s:
            return JobOut.model_validate(s.get(Job, job_id)).model_dump(mode="json")

    async def stream():
        last = None
        for _ in range(timeout):
            payload = await asyncio.to_thread(fetch)
            if payload != last:
                yield f"data: {json.dumps(payload)}\n\n"
                last = payload
            if payload["status"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
                return
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
