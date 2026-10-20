from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import or_, select

from app.api.deps import DB, CurrentUser, UserSettings, owned
from app.models import PublishingJob
from app.models.enums import PublishStatus
from app.schemas.api import PublishingJobOut, RescheduleRequest
from app.services.audit import audit
from app.services.publishing import cancel_publishing, next_publish_slot, reschedule

from .videos import pj_out

router = APIRouter(prefix="/publishing", tags=["publishing"])


@router.get("/calendar")
def calendar(db: DB, user: CurrentUser, start: datetime | None = None, end: datetime | None = None) -> dict:
    start = start or datetime.now(UTC) - timedelta(days=7)
    end = end or start + timedelta(days=42)
    rows = db.scalars(select(PublishingJob).where(
        PublishingJob.owner_id == user.id,
        or_(PublishingJob.publish_at.between(start, end),
            (PublishingJob.publish_at.is_(None) & PublishingJob.created_at.between(start, end))),
    ).order_by(PublishingJob.publish_at))
    items = []
    for pj in rows:
        out = pj_out(pj).model_dump(mode="json")
        out["date"] = (pj.publish_at or pj.created_at).isoformat()
        out["project_title"] = pj.project.title if pj.project else ""
        items.append(out)
    return {"start": start, "end": end, "items": items}


@router.get("/queue", response_model=list[PublishingJobOut])
def queue(db: DB, user: CurrentUser, include_done: bool = Query(False)) -> list:
    stmt = select(PublishingJob).where(PublishingJob.owner_id == user.id)
    if not include_done:
        stmt = stmt.where(PublishingJob.status.in_([PublishStatus.QUEUED, PublishStatus.UPLOADING,
                                                    PublishStatus.FAILED]))
    return [pj_out(pj) for pj in db.scalars(stmt.order_by(PublishingJob.id.desc()).limit(200))]


@router.get("/next-slot")
def next_slot(db: DB, app_settings: UserSettings) -> dict:
    return {"publish_at": next_publish_slot(db, app_settings), "timezone": app_settings.timezone}


@router.put("/{pj_id}", response_model=PublishingJobOut)
def update(pj_id: int, body: RescheduleRequest, db: DB, user: CurrentUser):
    pj = owned(db.get(PublishingJob, pj_id), user, "Publishing job")
    reschedule(db, pj, body.publish_at)
    audit(db, user.id, "publish.rescheduled", "publishing_job", pj.id, publish_at=body.publish_at.isoformat())
    db.commit()
    return pj_out(pj)


@router.post("/{pj_id}/cancel", response_model=PublishingJobOut)
def cancel(pj_id: int, db: DB, user: CurrentUser):
    pj = owned(db.get(PublishingJob, pj_id), user, "Publishing job")
    cancel_publishing(db, pj)
    audit(db, user.id, "publish.cancelled", "publishing_job", pj.id)
    db.commit()
    return pj_out(pj)
