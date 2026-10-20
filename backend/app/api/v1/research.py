from datetime import datetime

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser, Paging, owned
from app.core.config import get_settings
from app.core.errors import ConfigurationError
from app.models import CompetitorVideoSnapshot, ResearchQuery, TrendReport
from app.models.enums import JobKind, ResearchType
from app.schemas.api import (
    JobOut,
    Page,
    ResearchQueryOut,
    ResearchSearchRequest,
    SnapshotOut,
    TrendReportOut,
)
from app.services import jobs
from app.services.youtube.oauth import active_channel

router = APIRouter(prefix="/research", tags=["research"])


@router.post("/search", status_code=status.HTTP_202_ACCEPTED)
def search(body: ResearchSearchRequest, db: DB, user: CurrentUser) -> dict:
    if not get_settings().youtube_api_key and active_channel(db, user.id) is None:
        raise ConfigurationError("Research needs YOUTUBE_API_KEY in the environment or a connected YouTube channel.")
    filters = body.model_dump(mode="json", exclude={"query", "query_type"}, exclude_none=True)
    q = ResearchQuery(owner_id=user.id, query_type=ResearchType(body.query_type), query_text=body.query.strip(),
                      filters=filters)
    db.add(q)
    db.flush()
    job = jobs.enqueue(db, user.id, JobKind.RESEARCH, {"query_id": q.id})
    db.commit()
    return {"query": ResearchQueryOut.model_validate(q), "job": JobOut.model_validate(job)}


@router.get("/queries", response_model=Page[ResearchQueryOut])
def list_queries(db: DB, user: CurrentUser, paging: Paging) -> dict:
    base = select(ResearchQuery).where(ResearchQuery.owner_id == user.id)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    items = db.scalars(base.order_by(ResearchQuery.id.desc()).offset(paging.offset).limit(paging.page_size))
    return {"items": list(items), "total": total, "page": paging.page, "page_size": paging.page_size}


@router.get("/results", response_model=Page[SnapshotOut])
def results(db: DB, user: CurrentUser, paging: Paging, query_id: int | None = None,
            language: str | None = Query(None, pattern="^(hi|en|bilingual|unknown)$"),
            video_format: str | None = Query(None, pattern="^(short|long|unknown)$"),
            topic: str | None = Query(None, max_length=40), min_views: int = Query(0, ge=0),
            published_after: datetime | None = None, published_before: datetime | None = None,
            sort: str = Query("views_per_day", pattern="^(views_per_day|view_count|published_at|engagement_rate)$")
            ) -> dict:
    stmt = select(CompetitorVideoSnapshot).join(ResearchQuery).where(ResearchQuery.owner_id == user.id)
    if query_id:
        stmt = stmt.where(CompetitorVideoSnapshot.research_query_id == query_id)
    if language:
        stmt = stmt.where(CompetitorVideoSnapshot.language == language)
    if video_format:
        stmt = stmt.where(CompetitorVideoSnapshot.video_format == video_format)
    if min_views:
        stmt = stmt.where(CompetitorVideoSnapshot.view_count >= min_views)
    if published_after:
        stmt = stmt.where(CompetitorVideoSnapshot.published_at >= published_after)
    if published_before:
        stmt = stmt.where(CompetitorVideoSnapshot.published_at <= published_before)
    rows = list(db.scalars(stmt))
    if topic:
        rows = [r for r in rows if topic in (r.topics or [])]
    rows.sort(key=lambda r: (getattr(r, sort) is None, -(_num(getattr(r, sort)))))
    total = len(rows)
    return {"items": rows[paging.offset: paging.offset + paging.page_size], "total": total, "page": paging.page,
            "page_size": paging.page_size}


def _num(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, datetime):
        return v.timestamp()
    return float(v)


@router.get("/reports", response_model=Page[TrendReportOut])
def reports(db: DB, user: CurrentUser, paging: Paging) -> dict:
    base = select(TrendReport).where(TrendReport.owner_id == user.id)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    items = db.scalars(base.order_by(TrendReport.id.desc()).offset(paging.offset).limit(paging.page_size))
    return {"items": list(items), "total": total, "page": paging.page, "page_size": paging.page_size}


@router.get("/reports/{report_id}", response_model=TrendReportOut)
def report(report_id: int, db: DB, user: CurrentUser) -> TrendReport:
    return owned(db.get(TrendReport, report_id), user, "Trend report")
